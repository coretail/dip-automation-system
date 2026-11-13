"""E2E SEC-05: request dengan X-Forwarded-For palsu (spoof) ke halaman yang
menulis audit IP — IP yang tercatat harus dari sisi KANAN XFF (proxy
tepercaya), BUKAN entri spoof di kiri.

HANYA untuk staging lokal. Menolak jalan bila base URL bukan localhost.
Kredensial (STAGING_ADMIN_EMAIL / STAGING_ADMIN_PASSWORD) dibaca dari env
(di-export dari LOGIN.md), jangan di-hardcode.

Jalankan:
    venv\\Scripts\\python.exe tests/e2e_sec05_xff_spoof_staging.py \\
        --base-url http://127.0.0.1:8017

Exit 0 = semua PASS, 1 = ada FAIL.

Prasyarat:
- Server staging hidup (scripts/run_staging_8017.py) di 127.0.0.1:8017
- Kredensial admin staging di-export sebagai env var
- Service role key staging tersedia di .env.staging (untuk baca activity_logs)

Alur tes:
1. Login (POST /login) untuk dapat cookie sesi.
2. Jalankan aksi yang menulis audit (mis. POST /notes dengan body unik)
   dengan header X-Forwarded-For: "<spoof-ip>, <asli-ip>" — spoof di KIRI,
   IP yang seharusnya tercatat di KANAN (entri terakhir).
3. Query activity_logs terbaru untuk aksi itu; assert ip_address ==
   entri KANAN XFF (bukan spoof). Jika server belum menerapkan
   trusted-hops (perilaku lama), hasilnya = spoof -> FAIL.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.staging"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
    return bool(ok)


def load_staging_cfg() -> dict:
    """Pakai app.staging_preflight untuk parse + validate .env.staging."""
    sys.path.insert(0, str(ROOT))
    from app.staging_preflight import parse_dotenv_file, validate_staging_file
    cfg = parse_dotenv_file(str(ENV_FILE))
    validate_staging_file(cfg, caller="e2e-sec05-xff-spoof")
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8017")
    parser.add_argument("--spoof-ip", default="1.2.3.4",
                        help="IP palsu di sisi KIRI XFF (harus diabaikan)")
    parser.add_argument("--expect-ip", default="9.8.7.6",
                        help="IP yang HARUS tercatat (sisi KANAN XFF, = proxy tepercaya)")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    host = urlparse(base_url).hostname or ""
    if host not in ("127.0.0.1", "localhost"):
        sys.exit(f"[ABORT] base URL '{base_url}' bukan localhost (staging lokal saja).")
    if not ENV_FILE.exists():
        sys.exit(f"[ABORT] {ENV_FILE.name} tidak ditemukan.")
    cfg = load_staging_cfg()

    email = os.environ.get("STAGING_ADMIN_EMAIL", "").strip()
    password = os.environ.get("STAGING_ADMIN_PASSWORD", "").strip()
    if not email or not password:
        sys.exit("[ABORT] set STAGING_ADMIN_EMAIL dan STAGING_ADMIN_PASSWORD.")

    # XFF: spoof di kiri, IP yang diharapkan di kanan.
    # Dengan trusted_hops=1 (default), entri TERAKHIR (expect_ip) yang dipakai.
    xff = f"{args.spoof_ip}, {args.expect_ip}"

    token_marker = f"sec05-{uuid.uuid4().hex[:8]}"
    note_body = token_marker  # body note = marker unik (dipakai utk query audit + cleanup)

    with httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=False) as client:
        # 1. Login
        r = client.post("/login", data={"email": email, "password": password})
        ok_login = r.status_code in (302, 303) and "/login" not in (r.headers.get("location") or "")
        if not record("login staging", ok_login, f"status={r.status_code} loc={r.headers.get('location')!r}"):
            _report()
            return 1

        # Cookie access_token bersifat Secure -> httpx membuang saat HTTP polos.
        # Ambil nilai dari Set-Cookie login lalu kirim manual di request setelahnya.
        token_cookie = _extract_set_cookie(r, "access_token")
        if not token_cookie:
            record("cookie access_token tersedia dari Set-Cookie login", False, "tidak ada Set-Cookie access_token")
            _report()
            return 1

        # 2. Buat note dengan body unik + kirim XFF spoof (dengan cookie manual)
        note_headers = {"x-forwarded-for": xff, "cookie": f"access_token={token_cookie}"}
        r2 = client.post("/notes", data={"body": note_body}, headers=note_headers)
        record(
            f"POST /notes (XFF={xff!r}) diterima",
            r2.status_code in (200, 302, 303)
            and "/login" not in (r2.headers.get("location") or ""),
            f"status={r2.status_code} loc={r2.headers.get('location')!r}",
        )

    # 3. Query activity_logs untuk aksi note terakhir + cek ip_address
    #    (perlu sedikit jeda agar baris audit tercatat di DB)
    import time
    time.sleep(2)
    ip_found, detail = _query_latest_activity_ip(cfg, note_body, base_url)
    if ip_found is None:
        record("activity_logs: baris audit note ditemukan", False, detail)
        _report()
        return 1
    record("activity_logs: baris audit note ditemukan", True)

    # 4. Assert IP tercatat == entri KANAN XFF (expect_ip), BUKAN spoof
    record(
        f"ip_address tercatat == {args.expect_ip} (sisi kanan XFF), bukan {args.spoof_ip} (spoof)",
        ip_found == args.expect_ip,
        f"got ip_address={ip_found!r}",
    )
    # 5. Regresi: jangan sampai mencatat spoof (perilaku lama = entri pertama)
    record(
        "ip_address TIDAK sama dengan spoof (regresi entri-pertama)",
        ip_found != args.spoof_ip,
        f"got {ip_found!r} == spoof {args.spoof_ip!r}",
    )

    # 6. Bersihkan note tes (best-effort, tidak fatal)
    _cleanup_note(base_url, email, password, note_body)

    _report()
    return 0 if all(ok for _, ok, _ in RESULTS) else 1


def _extract_set_cookie(resp, name: str):
    """Ambil nilai cookie `name` dari header Set-Cookie respons (secure flag diabaikan).

    Cookie access_token di-set Secure; saat staging lokal pakai HTTP polos,
    httpx membuang cookie itu. Kita ekstrak nilai dari Set-Cookie lalu kirim
    manual di request berikutnya.
    """
    for raw in (resp.headers.get("set-cookie") or "").split(","):
        if ";" in raw:
            part = raw.split(";", 1)[0].strip()
        else:
            part = raw.strip()
        if part.startswith(f"{name}="):
            return part[len(name) + 1:]
    return None


def _cleanup_note(base_url: str, email: str, password: str, note_body: str) -> None:
    """Best-effort: hapus note tes. Kegagalan tidak fatal; note ber-marker unik
    jadi tidak mengganggu data lain bila ditinggalkan."""
    try:
        with httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=False) as c:
            r = c.post("/login", data={"email": email, "password": password})
            tok = _extract_set_cookie(r, "access_token")
            if not tok:
                print(f"[INFO] cleanup: cookie tidak tersedia; note {note_body!r} ditinggalkan.")
                return
            c.post("/notes/delete", data={"note_id": ""}, headers={"cookie": f"access_token={tok}"})
            print(f"[INFO] cleanup: dicoba hapus note {note_body!r} (best-effort).")
    except Exception as e:
        print(f"[INFO] cleanup gagal (diabaikan): {e}")


def _query_latest_activity_ip(cfg: dict, note_body: str, base_url: str):
    """Baca activity_logs terbaru untuk note_body; return (ip_address, detail).

    Pakai service role key dari cfg (bukan env global). IP bisa None bila
    baris belum ada atau kolom kosong. Query: entity_type=note +
    action=create + entity_label ILIKE %note_body%.
    """
    import os as _os
    # Baca service role key dari cfg (.env.staging) — JANGAN cetak.
    key = cfg.get("SUPABASE_SERVICE_ROLE_KEY") or _os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    url = cfg.get("SUPABASE_URL") or _os.environ.get("SUPABASE_URL") or ""
    if not key or not url:
        return None, "service role key / SUPABASE_URL tidak tersedia"
    # Client khusus (tidak mengganggu client global app.database.supabase)
    from supabase import create_client
    client = create_client(url, key)
    res = (
        client.table("activity_logs")
        .select("ip_address, action, entity_type, entity_label, created_at")
        .eq("entity_type", "note")
        .eq("action", "create")
        .ilike("entity_label", f"%{note_body}%")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None, f"tidak ada baris activity_logs note/create untuk {note_body!r}"
    target = rows[0]
    return target.get("ip_address"), (
        f"target action={target.get('action')!r} ip={target.get('ip_address')!r}"
    )


def _report() -> None:
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n=== RINGKASAN ===  PASS={passed} FAIL={total - passed} TOTAL={total}")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL: {name} - {detail}")


if __name__ == "__main__":
    raise SystemExit(main())
