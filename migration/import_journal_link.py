"""Import kolom raw_materials.journal_link dari xlsx bahan baku gabungan.

Sumber data: ``logs/bahan baku/Bahan_Baku_Gabungan.xlsx`` (folder /logs/
di-gitignore; FILE INI TIDAK BOLEH DI-COMMIT). Database tujuan di akses
lewat Supabase Management API (POST /v1/projects/{ref}/database/query),
sesuai jalur yang diizinkan AGENTS.md atas otorisasi pemilik repo.

Pemakaian (dari root repo):

    python migration/import_journal_link.py --target staging
    python migration/import_journal_link.py --target staging --apply
    python migration/import_journal_link.py --target prod
    python migration/import_journal_link.py --target prod --apply

Perilaku:
- DEFAULT dry-run: baca DB + xlsx, cocokkan, hitung, LAPORKAN — tidak ada
  tulis apa pun. ``--apply`` menulis lewat SATU statement UPDATE atomik
  (multi-row VALUES) dengan guard ``AND rm.journal_link IS NULL``.
- Kunci cocokan: ``kode_bahan_baku`` (trim + case-insensitive) sebagai kunci
  utama; fallback ``nama_dagang`` exact (trim + case-insensitive) HANYA bila
  kode kosong di baris xlsx.
- Baris xlsx yang cocok ke >1 bahan = AMBIGU -> lapor, jangan tulis.
- Satu bahan yang muncul di beberapa baris xlsx dengan link BERBEDA =
  KONFLIK -> lapor, jangan tulis, jangan memilih sendiri.
- Link dinormalisasi ``app.journal_link.normalize_journal_link``; tidak valid
  -> lapor dengan nomor baris xlsx, jangan tulis.
- Bahan yang journal_link-nya SUDAH terisi di DB -> skip + lapor
  (jangan menimpa).
- Sebelum ``--apply``: snapshot (id, kode, journal_link lama + rencana baru)
  ke CSV di folder gitignored (logs/journal_link_import/) untuk rollback.
- Sesudah ``--apply``: SELECT ulang (jumlah berubah harus sama dengan
  laporan), lalu komputasi dry-run ulang untuk membuktikan idempoten
  (0 perubahan).

Kolon/objek lain tidak disentuh; tidak ada perubahan skema.

Token Security:
- Token Management API dibaca dari env ``SUPABASE_ACCESS_TOKEN`` /
  ``SUPABASE_MANAGEMENT_TOKEN`` (diutamakan), atau diekstrak programatik dari
  ``.kilo/kilo.jsonc`` (blok mcp.supabase.command, flag --access-token).
- Token TIDAK PERNAH dicetak, di-log, atau ditulis ke file; error message
  di-redact terhadap nilai token.

Exit code: 0 = sukses/laporan bersih, 1 = dry-run ada temuan (unmatched/
ambigu/konflik/invalid) atau apply gagal, 2 = fatal (token tidak ada,
pre-check gagal, API error).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.journal_link import normalize_journal_link  # noqa: E402
from app.staging_preflight import PROD_REF, STAGING_REF  # noqa: E402

MGMT_API = "https://api.supabase.com/v1/projects/{ref}/database/query"
DEFAULT_XLSX = os.path.join(ROOT, "logs", "bahan baku", "Bahan_Baku_Gabungan.xlsx")
DEFAULT_SNAPSHOT_DIR = os.path.join(ROOT, "logs", "journal_link_import")


def _redact(text: str, token: str) -> str:
    """Potong error message; nilai token (bila muncul) digantikan ***."""
    s = str(text)
    if token:
        s = s.replace(token, "***")
    return s[:300]


def _load_jsonc(path: str) -> dict:
    """Parsai .jsonc sederhana: buang komentar // dan /* */, koma trailing."""
    raw = open(path, encoding="utf-8").read()
    out = []
    in_str = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < len(raw):
                out.append(raw[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < len(raw) and raw[i + 1] == "/":
            while i < len(raw) and raw[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < len(raw) and raw[i + 1] == "*":
            i += 2
            while i + 1 < len(raw) and not (raw[i] == "*" and raw[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    cleaned = re.sub(r",(\s*[\]\}])", r"\1", "".join(out))
    return json.loads(cleaned)


def _resolve_token(args: argparse.Namespace) -> tuple[str, str]:
    """(token, sumber) — token tidak pernah dicetak."""
    token = (os.environ.get("SUPABASE_ACCESS_TOKEN")
             or os.environ.get("SUPABASE_MANAGEMENT_TOKEN") or "").strip()
    if token:
        return token, "env(SUPABASE_ACCESS_TOKEN/SUPABASE_MANAGEMENT_TOKEN)"
    cfg_path = os.path.abspath(args.kilo_config)
    if not os.path.isfile(cfg_path):
        print("FATAL: token tidak ada. Set SUPABASE_ACCESS_TOKEN atau "
              f"sediakan --kilo-config yang benar (tidak ketemu: {cfg_path})")
        raise SystemExit(2)
    cfg = _load_jsonc(cfg_path)
    command = ((cfg.get("mcp") or {}).get("supabase") or {}).get("command") or []
    for idx, item in enumerate(command):
        if str(item) == "--access-token" and idx + 1 < len(command):
            return str(command[idx + 1]), "kilo.jsonc(mcp.supabase.command --access-token)"
    print("FATAL: token tidak ditemukan (env kosong dan kilo.jsonc tidak memuat "
          "mcp.supabase.command --access-token)")
    raise SystemExit(2)


def _mgmt_query(token: str, ref: str, sql: str) -> list[dict]:
    """Jalankan SQL lewat Management API -> daftar dict baris (SELECT)."""
    import httpx

    resp = httpx.post(
        MGMT_API.format(ref=ref),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql},
        timeout=60,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Management API HTTP {resp.status_code}: {_redact(resp.text, token)}")
    data = resp.json()
    if isinstance(data, list):
        return [dict(r) for r in data]
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        cols = [c.get("name") if isinstance(c, dict) else str(c)
                for c in (data.get("columns") or [])]
        rows = data["rows"]
        if all(isinstance(r, dict) for r in rows[:1]):
            return [dict(r) for r in rows]
        return [dict(zip(cols, r)) for r in rows]
    raise RuntimeError(f"bentuk respons Management API tidak dikenal: {type(data).__name__}")


def _precheck_columns(ref: str, token: str) -> None:
    """Migrasi 014 wajib sudah jalan di target: kolom journal_link harus ada."""
    rows = _mgmt_query(token, ref, (
        "SELECT count(*) FILTER (WHERE column_name = 'journal_link') AS ada "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'raw_materials';"
    ))
    ada = int(rows[0].get("ada") or 0)
    if ada != 1:
        print(f"FATAL: kolom raw_materials.journal_link TIDAK ada di ref {ref}. "
              "Jalankan migration/014_add_raw_material_journal_link.sql di target ini "
              "lebih dulu, lalu ulangi.")
        raise SystemExit(2)


def _fetch_raw_materials(ref: str, token: str) -> list[dict]:
    return _mgmt_query(token, ref, (
        "SELECT id, kode_bahan_baku, nama_dagang, journal_link "
        "FROM raw_materials ORDER BY id;"
    ))


def _norm(v) -> str:
    return str(v or "").strip()


def read_xlsx(path: str) -> tuple[str, list, list]:
    """(nama sheet, header, daftar (no_baris, kode, nama, link_mentah))."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    header = [_norm(c.value) for c in ws[1]]
    idx = {h.lower(): i for i, h in enumerate(header) if h}

    def col(*names) -> int:
        for n in names:
            if n.lower() in idx:
                return idx[n.lower()]
        raise SystemExit(f"FATAL: kolom tidak ditemukan di header {path}: {names!r}. "
                         f"Header aktual: {header}")

    i_kode = col("Kode Bahan Baku")
    i_nama = col("Nama Bahan Baku")
    i_link = col("Link Jurnal")
    rows = []
    # no_baris = nomor baris Excel Sebenarnya (int), dari enumerate, BUKAN nilai
    # kolom "No" (r[0]) yang bisa beda/tidak ada. start=2 karena baris 1 = header.
    for no_baris, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        kode = _norm(r[i_kode]) if len(r) > i_kode else ""
        nama = _norm(r[i_nama]) if len(r) > i_nama else ""
        link = _norm(r[i_link]) if len(r) > i_link else ""
        if not (kode or nama or link):
            continue
        rows.append((no_baris, kode, nama, link))
    return ws.title, header, rows


def _sql_quote(text: str) -> str:
    """Escape untuk literal SQL: single quote digandakan."""
    return text.replace("'", "''")


def compute_import_plan(db_rows: list[dict], xrows: list[tuple]) -> dict:
    """Pencocokan MURNI (tanpa DB/network) — bisa dites unit tanpa koneksi.

    xrows = [(no_baris, kode, nama, link_mentah), ...]  (no_baris: int, nomor
    baris Excel sebenarnya); db_rows = [{id, kode_bahan_baku, nama_dagang,
    journal_link}, ...].

    Aturan:
    - Kunci utama: kode_bahan_baku (trim + case-insensitive).
    - Fallback ke nama_dagang (trim + case-insensitive) HANYA bila kode di
      baris xlsx KOSONG. Kode terisi tapi tak ada di DB -> "unmatched"
      (TIDAK jatuh ke nama).
    - 1 baris xlsx cocok ke >1 bahan -> ambigu (jangan tulis).
    - 1 bahan muncul di beberapa baris xlsx dengan link berbeda -> konflik
      (jangan tulis, jangan memilih sendiri).
    - Link dinormalisasi normalize_journal_link; tidak valid -> lapor nomor
      baris xlsx, jangan tulis.
    - journal_link SUDAH terisi di DB -> already_filled (skip, tak ditimpa).
    """
    kode_map: dict[str, list[dict]] = {}
    nama_map: dict[str, list[dict]] = {}
    for r in db_rows:
        k = _norm(r.get("kode_bahan_baku")).casefold()
        n = _norm(r.get("nama_dagang")).casefold()
        if k:
            kode_map.setdefault(k, []).append(r)
        if n:
            nama_map.setdefault(n, []).append(r)

    unmatched: list[tuple] = []
    ambiguous: list[tuple] = []
    already_filled: list[tuple] = []
    invalid: list[tuple] = []
    per_material: dict[str, list[tuple]] = {}  # db_id -> [(no_baris, ident, link_norm)]
    for no_baris, kode, nama, link_mentah in xrows:
        if not link_mentah:
            continue  # tanpa link: tidak relevan untuk import
        if kode:
            cand = kode_map.get(_norm(kode).casefold()) or []
        else:
            cand = nama_map.get(_norm(nama).casefold()) or []
        ident = kode or f"(tanpa kode) {nama}"
        if len(cand) == 0:
            unmatched.append((no_baris, ident))
            continue
        if len(cand) > 1:
            ambiguous.append((no_baris, ident,
                              [_norm(c.get("nama_dagang")) for c in cand]))
            continue
        link_norm = None
        try:
            link_norm = normalize_journal_link(link_mentah)
        except ValueError as exc:
            invalid.append((no_baris, ident, str(exc)))
            continue
        if link_norm is None:
            continue  # kosong setelah strip: tidak ada yang diimpor
        db_row = cand[0]
        rid = str(db_row.get("id"))
        if _norm(db_row.get("journal_link")):
            already_filled.append((no_baris, ident, _norm(db_row.get("journal_link"))[:60]))
            continue
        per_material.setdefault(rid, []).append((no_baris, ident, link_norm))

    # Konflik: satu bahan, beberapa baris xlsx, link berbeda.
    conflicts = {rid: sorted({lk for _, _, lk in rows})
                 for rid, rows in per_material.items()
                 if len({lk for _, _, lk in rows}) > 1}
    planned: dict[str, str] = {rid: next(iter({lk for _, _, lk in rows}))
                               for rid, rows in per_material.items()
                               if len({lk for _, _, lk in rows}) == 1}
    # will_write: baris xlsx yang akan ditulis; no_baris selalu int (enumerate),
    # jadi sorted() aman (tidak ada tipe campuran).
    will_write = sorted((no, ident, link)
                        for rid, link in planned.items()
                        for (no, ident, _) in per_material[rid])

    return {
        "planned": planned,
        "will_write": will_write,
        "unmatched": unmatched,
        "ambiguous": ambiguous,
        "already_filled": already_filled,
        "invalid": invalid,
        "conflicts": conflicts,
    }


def build_update_sql(id2link: dict[str, str]) -> str:
    """SATU statement UPDATE atomik (multi-row VALUES).

    id selalu berasal dari hasil baca DB (divalidasi uuid); link sudah lolos
    normalize_journal_link (uji ulang di sini, defense-in-depth). Teks xlsx
    mentah TIDAK PERNAH masuk ke SQL tanpa normalisasi + escape.
    """
    pairs = []
    for rid, link in id2link.items():
        try:
            uuid.UUID(str(rid))
        except Exception:
            raise SystemExit(f"FATAL: id bukan uuid valid, ditolak: {rid!r}")
        normalized = normalize_journal_link(link)  # raise ValueError bila regresi
        if normalized is None:
            raise SystemExit(f"FATAL: link untuk {rid} menjadi kosong setelah normalisasi")
        if any(ord(ch) < 0x20 or ch == "\x7f" for ch in normalized):
            raise SystemExit(f"FATAL: link untuk {rid} mengandung karakter kontrol")
        pairs.append(f"('{rid}', '{_sql_quote(normalized)}')")
    values = ",\n".join(pairs)
    return (
        "UPDATE raw_materials AS rm\n"
        "SET journal_link = v.link\n"
        f"FROM (VALUES\n{values}\n) AS v(id, link)\n"
        "WHERE rm.id = v.id::uuid\n"
        "  AND rm.journal_link IS NULL;"
    )


def write_snapshot(snapshot_dir: str, target: str, planned: dict[str, str],
                   db_rows: list[dict]) -> str:
    """Snapshot pre-apply untuk rollback (CSV, folder gitignored)."""
    os.makedirs(snapshot_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(snapshot_dir, f"{target}_snapshot_{ts}.csv")
    by_id = {str(r.get("id")): r for r in db_rows}
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "kode_bahan_baku", "nama_dagang",
                    "journal_link_sebelum", "journal_link_rencana"])
        for rid, new_link in planned.items():
            row = by_id.get(rid, {})
            w.writerow([rid, _norm(row.get("kode_bahan_baku")),
                        _norm(row.get("nama_dagang")),
                        _norm(row.get("journal_link")) or "", new_link])
    return path


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", choices=("staging", "prod"), default="staging")
    ap.add_argument("--project-ref", help="override ref (default dari app.staging_preflight)")
    ap.add_argument("--xlsx", default=DEFAULT_XLSX)
    ap.add_argument("--apply", action="store_true", help="tulis ke DB (default dry-run)")
    ap.add_argument("--snapshot-dir", default=DEFAULT_SNAPSHOT_DIR)
    ap.add_argument("--kilo-config", default=os.path.join(ROOT, ".kilo", "kilo.jsonc"))
    ap.add_argument("--list-projects", action="store_true",
                    help="cetak daftar project (ref+nama, non-secret) lalu exit")
    args = ap.parse_args(argv)

    token, token_source = _resolve_token(args)
    print(f"[token] sumber={token_source} (nilai tidak dicetak)")

    if args.list_projects:
        import httpx
        resp = httpx.get("https://api.supabase.com/v1/projects",
                         headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if resp.status_code not in (200, 201):
            print(f"ERROR list projects: HTTP {resp.status_code} {_redact(resp.text, token)}")
            return 2
        for p in resp.json():
            if isinstance(p, dict):
                print(f"  ref={p.get('id')}  nama={p.get('name')}  region={p.get('region')}")
        return 0

    ref = args.project_ref or (STAGING_REF if args.target == "staging" else PROD_REF)
    # defense-in-depth: staging tidak boleh terarah ke prod dan sebaliknya.
    if args.target == "staging" and ref == PROD_REF:
        print("ERROR: --project-ref menunjuk ref PRODUKSI; target staging dilarang")
        return 2
    if args.target == "prod" and ref == STAGING_REF:
        print("ERROR: --project-ref menunjuk ref STAGING; target prod dilarang")
        return 2
    print(f"[target] {args.target} (ref tidak dicetak: …{ref[-6:]})")

    # ---------- Pre-check ----------
    # RuntimeError dari Management API (HTTP/timeout/bentuk respons) = fatal ->
    # exit 2 (sesuai docstring); pesan tetap di-redact terhadap token.
    try:
        _precheck_columns(ref, token)
    except RuntimeError as exc:
        print("FATAL (API saat pre-check): " + _redact(str(exc), token))
        return 2
    print("[pre-check] kolom journal_link ada (migrasi 014 terpasang) ✓")

    try:
        db_rows = _fetch_raw_materials(ref, token)
    except RuntimeError as exc:
        print("FATAL (API saat baca raw_materials): " + _redact(str(exc), token))
        return 2
    print(f"[db] {len(db_rows)} baris raw_materials terbaca")

    # ---------- Baca xlsx + cocokan (fungsi murni, teruji unit) ----------
    sheet, header, xrows = read_xlsx(args.xlsx)
    print(f"[xlsx] sheet '{sheet}', header={header}, baris={len(xrows)}")

    plan = compute_import_plan(db_rows, xrows)
    planned = plan["planned"]
    will_write = plan["will_write"]
    unmatched = plan["unmatched"]
    ambiguous = plan["ambiguous"]
    already_filled = plan["already_filled"]
    invalid = plan["invalid"]
    conflicts = plan["conflicts"]

    # ---------- Laporan ----------
    print("\n===== LAPORAN DRY-RUN =====")
    print(f"target            : {args.target} ({len(db_rows)} baris DB)")
    print(f"baris xlsx        : {len(xrows)} (sheet '{sheet}')")
    print(f"baris punya link  : {sum(1 for r in xrows if r[3])}")
    print(f"AKAN DITULIS      : {len(planned)} bahan / {len(will_write)} baris xlsx")
    print(f"sudah terisi (skip): {len(already_filled)}")
    print(f"tidak cocok       : {len(unmatched)}")
    print(f"ambigu (>1 bahan) : {len(ambiguous)}")
    print(f"konflik (1 bahan, link beda): {len(conflicts)}")
    print(f"link tidak valid  : {len(invalid)}")

    def dump(title: str, items: list, limit: int = 500) -> None:
        if not items:
            return
        print(f"\n-- {title} ({len(items)}) --")
        for it in items[:limit]:
            print(f"   {it}")

    dump("baris xlsx AKAN DITULIS",
         [f"baris {no}: {ident} -> {link[:90]}" for no, ident, link in will_write])
    dump("SUDAH TERISI (di-skip, tidak ditimpa)", already_filled)
    dump("TIDAK COCOK (kode/nama tidak ada di DB target)",
         [f"baris {no}: {ident}" for no, ident in unmatched])
    dump("AMBIGU (kode/nama cocok ke >1 bahan — tidak ditulis)",
         [f"baris {no}: {ident} -> {nms}" for no, ident, nms in ambiguous])
    dump("KONFLIK (satu bahan, beberapa baris xlsx, link berbeda — tidak ditulis)",
         [f"id {rid}: link {links}" for rid, links in sorted(conflicts.items())])
    dump("LINK TIDAK VALID (normalize_journal_link menolak — tidak ditulis)",
         [f"baris {no}: {ident} :: {why[:90]}" for no, ident, why in invalid])

    # ---------- apply ----------
    if not args.apply:
        print("\n[dry-run] tidak ada tulis. Tambah --apply untuk menuliskan "
              f"{len(planned)} baris (kalau memang ada).")
        return 1 if (unmatched or ambiguous or conflicts or invalid) else 0

    if not planned:
        print("\n[apply] tidak ada baris yang akan ditulis; tidak ada UPDATE.")
        return 0

    snapshot_path = write_snapshot(args.snapshot_dir, args.target, planned, db_rows)
    print(f"\n[snapshot] {snapshot_path}")
    sql = build_update_sql(planned)
    try:
        _mgmt_query(token, ref, sql)
    except RuntimeError as exc:
        print("FATAL (API saat apply UPDATE): " + _redact(str(exc), token))
        print(f"Snapshot untuk rollback: {snapshot_path}")
        return 2
    print(f"[apply] UPDATE dikirim: {len(planned)} id, 1 statement atomik")

    # Verifikasi pasca-apply.
    id_list = ", ".join(f"'{rid}'" for rid in planned)
    try:
        nulls = _mgmt_query(token, ref, (
            f"SELECT count(*) AS n FROM raw_materials "
            f"WHERE id IN ({id_list}) AND journal_link IS NULL;"
        ))
        after = _fetch_raw_materials(ref, token)
    except RuntimeError as exc:
        print("FATAL (API saat verifikasi pasca-apply): " + _redact(str(exc), token))
        return 2
    by_id = {str(r.get("id")): r for r in after}
    changed_now = 0
    for rid, link in planned.items():
        if _norm(by_id.get(rid, {}).get("journal_link")) == link:
            changed_now += 1
    expected = len(planned)
    print(f"[verifikasi] IS NULL tersisa di id target: {int(nulls[0]['n'])} (harus 0)")
    print(f"[verifikasi] baris terisi sesuai rencana: {changed_now}/{expected}")

    # Buktikan idempoten: komputasi ulang dry-run atas data terbaru.
    # (iterasi planned.items() -> pasangan (rid, link); BUKAN iterasi keys).
    planned2 = {rid: link for rid, link in planned.items()
                if not _norm(by_id.get(rid, {}).get("journal_link"))}
    print(f"[idempoten] rencana tersisa setelah apply: {len(planned2)} (harus 0)")

    ok = int(nulls[0]["n"]) == 0 and changed_now == expected and len(planned2) == 0
    print(f"[hasil] {'BERHASIL' if ok else 'GAGAL / PERLU PERIKSA ULANG'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
