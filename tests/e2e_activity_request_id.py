"""E2E staging: verifikasi refactor request-scoped `request_id` (commit 317d1fb).

HANYA untuk staging lokal. Menolak jalan bila base URL bukan localhost, atau
.env.staging gagal di preflight (`app.staging_preflight.validate_staging_file`:
DIP_APP_ENV=staging, SUPABASE_URL = project staging, key terikat staging).
TIDAK menyentuh prod. Tidak mencetak secret.

Yang diuji (lewat UI nyata, halaman /notes, akun admin staging):
  Satu siklus hidup note = 4 request HTTP terpisah:
      POST /notes                      -> log `create`
      POST /notes/{id}/complete        -> log `complete`
      POST /notes/{id}/reopen          -> log `reopen`
      POST /notes/{id}/delete          -> log `delete`
  Lalu baca tabel `activity_logs` (service role, staging) dan pastikan:
    1. tiap aksi menghasilkan tepat 1 baris log (4 baris, urutan benar)
    2. `request_id` terisi dan berformat UUID di semua baris
       (sebelum refactor handler complete/reopen/delete tidak meneruskan
       `request`, jadi kolom ini kosong)
    3. keempat `request_id` BERBEDA (request-scoped: tidak bocor/di-reuse
       antar request, bukan konstanta/global)
    4. `route` dan `http_method` terisi dan cocok dengan endpoint yang
       dipanggil (bukti `Request` benar-benar sampai ke `log_activity`)
    5. `actor_id` = akun admin yang login, `outcome` = success
  Plus: tidak ada redirect `?error=` di tiap langkah (signature handler
  `request: Request` yang baru tidak merusak route).

Catatan:
  - Note uji dihapus lewat UI di langkah terakhir (itu sendiri bagian tes).
    Baris `activity_logs` dibiarkan (audit trail, staging saja). Bila tes
    gagal di tengah jalan, note sisa dihapus lewat service role (cleanup).
  - Tidak ada route di commit ini yang menulis >1 log per request, jadi
    "beberapa log dalam SATU request berbagi ID yang sama" belum bisa diuji
    end-to-end; cakupannya ada di tes unit `_request_id_for` bila dibuat.

Prasyarat (sekali):
    pip install playwright supabase python-dotenv
    playwright install chromium

Jalankan (staging harus hidup, mis. scripts/run_staging_8017.py):
    set STAGING_ADMIN_EMAIL=...        (PowerShell: $env:STAGING_ADMIN_EMAIL="...")
    set STAGING_ADMIN_PASSWORD=...
    py tests/e2e_activity_request_id.py [--headed] [--base-url http://127.0.0.1:8017]

Exit code 0 = semua PASS, 1 = ada FAIL.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.staging"

RESULTS: list[tuple[str, bool, str]] = []

# (action, http_method, route) yang diharapkan, sesuai urutan siklus hidup note.
EXPECTED_STEPS = [
    ("create", "POST", "/notes"),
    ("complete", "POST", "/notes/{note_id}/complete"),
    ("reopen", "POST", "/notes/{note_id}/reopen"),
    ("delete", "POST", "/notes/{note_id}/delete"),
]


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return bool(ok)


def is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def load_and_guard(base_url: str) -> dict:
    """Muat .env.staging lalu fail-closed bila bukan staging lokal."""
    host = urlparse(base_url).hostname or ""
    if host not in ("127.0.0.1", "localhost"):
        sys.exit(f"[ABORT] base URL '{base_url}' bukan localhost (staging lokal saja).")
    if not ENV_FILE.exists():
        sys.exit(f"[ABORT] {ENV_FILE.name} tidak ditemukan.")

    sys.path.insert(0, str(ROOT))
    from app.staging_preflight import parse_dotenv_file, validate_staging_file

    cfg = parse_dotenv_file(str(ENV_FILE))
    try:
        validate_staging_file(cfg, caller="e2e-request-id")
    except RuntimeError as exc:
        sys.exit(f"[ABORT] guard staging gagal: {exc}")
    return cfg


def db_client(cfg: dict):
    from supabase import create_client

    return create_client(cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_ROLE_KEY"])


def fetch_logs_for_note(db, note_id: str, expected: int, timeout: float = 10.0) -> list[dict]:
    """Ambil log `note` untuk satu entity_id, tunggu sampai `expected` baris."""
    deadline = time.time() + timeout
    rows: list[dict] = []
    while time.time() < deadline:
        rows = (
            db.table("activity_logs")
            .select("action, entity_type, entity_id, request_id, route, http_method, "
                    "actor_id, outcome, source, created_at")
            .eq("entity_type", "note")
            .eq("entity_id", note_id)
            .order("created_at")
            .execute()
            .data
            or []
        )
        if len(rows) >= expected:
            break
        time.sleep(1)
    return rows


def find_note_id(db, marker: str, timeout: float = 10.0) -> str | None:
    """Cari id note dari log `create` (label diawali marker)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = (
            db.table("activity_logs")
            .select("entity_id")
            .eq("entity_type", "note")
            .eq("action", "create")
            .ilike("entity_label", f"{marker}%")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows and rows[0].get("entity_id") not in (None, "-"):
            return rows[0]["entity_id"]
        time.sleep(1)
    return None


def run_ui(base_url: str, email: str, password: str, marker: str, db, headed: bool) -> str | None:
    """Jalankan siklus hidup note di browser. Kembalikan note_id (atau None)."""
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    note_id: str | None = None

    def submit_and_expect(page, click_target, status: str, label: str) -> bool:
        """Klik, tunggu redirect /notes?status=<status>, pastikan bukan ?error=."""
        try:
            with page.expect_navigation(url=lambda u: "/notes" in u, timeout=20000):
                click_target.click()
            page.wait_for_load_state("domcontentloaded")
        except PWTimeout:
            return record(label, False, f"tidak ada redirect, masih di {page.url}")
        ok = f"status={status}" in page.url and "error=" not in page.url
        return record(label, ok, page.url if not ok else "")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        page = browser.new_context(base_url=base_url).new_page()
        page.set_default_timeout(20000)
        page.on("dialog", lambda d: d.accept())  # confirm() reopen & hapus
        try:
            # --- login ---
            page.goto("/login")
            page.fill("input[name=email]", email)
            page.fill("input[name=password]", password)
            page.click("#login-submit-btn")
            try:
                page.wait_for_url(lambda u: "/login" not in u, timeout=30000)
                record("login admin staging", True)
            except PWTimeout:
                record("login admin staging", False, f"masih di {page.url}")
                return None

            # --- 1. create ---
            page.goto("/notes")
            page.fill("#noteBody", marker)
            if not submit_and_expect(page, page.locator("#noteForm button[type=submit]"),
                                     "created", "UI: post note -> redirect created"):
                return None

            note_id = find_note_id(db, marker)
            if not record("log `create` ditemukan, entity_id = id note", bool(note_id),
                          f"id={note_id}" if note_id else "tidak ada baris log"):
                return None

            # --- 2. complete ---
            page.locator(f"button[onclick*='completeForm_{note_id}']").first.click()
            form = page.locator(f"#completeForm_{note_id}")
            form.locator("button[type=submit]").wait_for(state="visible")
            if not submit_and_expect(page, form.locator("button[type=submit]"),
                                     "completed", "UI: tandai selesai -> redirect completed"):
                return note_id

            # --- 3. reopen ---
            reopen = page.locator(f"form[action='/notes/{note_id}/reopen'] button")
            if not submit_and_expect(page, reopen, "reopened",
                                     "UI: buka kembali -> redirect reopened"):
                return note_id

            # --- 4. delete ---
            delete = page.locator(f"form[action='/notes/{note_id}/delete'] button")
            if not submit_and_expect(page, delete, "deleted",
                                     "UI: hapus -> redirect deleted"):
                return note_id
            return note_id
        finally:
            browser.close()


def check_logs(db, note_id: str) -> None:
    rows = fetch_logs_for_note(db, note_id, expected=len(EXPECTED_STEPS))
    record("tiap aksi = 1 baris log (4 baris)", len(rows) == len(EXPECTED_STEPS),
           f"ditemukan {len(rows)}: {[r['action'] for r in rows]}")
    if len(rows) != len(EXPECTED_STEPS):
        return

    record("urutan aksi create -> complete -> reopen -> delete",
           [r["action"] for r in rows] == [s[0] for s in EXPECTED_STEPS],
           str([r["action"] for r in rows]))

    ids = [r.get("request_id") for r in rows]
    record("request_id terisi di semua baris", all(ids), str(ids))
    record("request_id berformat UUID", all(is_uuid(i) for i in ids if i), str(ids))
    record("request_id BERBEDA antar request (request-scoped)",
           len({i for i in ids if i}) == len(EXPECTED_STEPS),
           f"{len({i for i in ids if i})} unik dari {len(ids)}")

    for row, (action, method, route) in zip(rows, EXPECTED_STEPS):
        record(f"route/method terisi benar untuk `{action}`",
               row.get("http_method") == method and row.get("route") == route,
               f"method={row.get('http_method')} route={row.get('route')}")

    actors = {r.get("actor_id") for r in rows}
    record("actor_id konsisten (1 admin, tidak null)", len(actors) == 1 and None not in actors,
           f"{len(actors)} aktor")
    record("outcome = success di semua baris", all(r.get("outcome") == "success" for r in rows),
           str([r.get("outcome") for r in rows]))

    try:
        prof = (db.table("profiles").select("id").eq("id", next(iter(actors))).execute().data
                or [])
        record("actor_id merujuk profil yang ada", len(prof) == 1)
    except Exception as exc:  # noqa: BLE001
        record("actor_id merujuk profil yang ada", False, f"{type(exc).__name__}: {exc}")


def cleanup(db, note_id: str | None, marker: str) -> None:
    """Hapus note sisa bila tes berhenti sebelum langkah delete (staging saja)."""
    try:
        if note_id:
            db.table("team_notes").delete().eq("id", note_id).execute()
        else:
            db.table("team_notes").delete().eq("body", marker).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] cleanup note gagal: {type(exc).__name__}: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.getenv("STAGING_BASE_URL", "http://127.0.0.1:8017"))
    ap.add_argument("--headed", action="store_true", help="tampilkan browser")
    args = ap.parse_args()

    email = os.getenv("STAGING_ADMIN_EMAIL", "")
    password = os.getenv("STAGING_ADMIN_PASSWORD", "")
    if not (email and password):
        sys.exit("[ABORT] set STAGING_ADMIN_EMAIL dan STAGING_ADMIN_PASSWORD (akun admin STAGING).")

    cfg = load_and_guard(args.base_url)
    db = db_client(cfg)

    import httpx

    try:
        r = httpx.get(args.base_url.rstrip("/") + "/health", timeout=5)
        if not record("staging hidup (/health)", r.status_code == 200, f"HTTP {r.status_code}"):
            return 1
    except Exception as exc:  # noqa: BLE001
        record("staging hidup (/health)", False, f"{type(exc).__name__}: {exc}")
        return 1

    # Hindari karakter pemicu parser @ # / ! di isi note.
    marker = f"E2E-REQID-{int(time.time())}"
    note_id = None
    try:
        note_id = run_ui(args.base_url, email, password, marker, db, args.headed)
        if note_id:
            check_logs(db, note_id)
    finally:
        cleanup(db, note_id, marker)

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
