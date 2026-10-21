"""Verifikasi state database STAGING (Batch B) untuk audit codebase 2026-10-21.

Tujuan
  Mengjawab pertanyaan yang TIDAK bisa dijawab dari kode saja, yaitu butir
  `catatan/catatan_audit_codebase_2026-10-21.md` section 11 ("Yang Tidak Dapat
  Diverifikasi Tanpa Runtime / Database"), dengan membaca skema + data live:
    - status eksekusi migrasi 001-007 (khususnya 007 capability publik)
    - data `profiles.full_name` NULL (BE-25)
    - kolom `percent_internal` NULL (BE-10)
    - privat/publik bucket Supabase (F-19)
    - volume data (FE-03, B4)
    - risiko produksi & kepatuhan: privasi bucket, guard tenant, DDL audit
      publik, cakupan detail storage, distribusi outcome, soft-delete (G9)

  Keluaran script ini adalah tabel bukti "Batch B" untuk dokumen audit.

Audit ID yang diverifikasi
  SEC-01, SEC-09, BE-10, BE-20, BE-25, FE-02, FE-03, B4, B6, D13, U6,
  U10 dan F-19.
  GROUP 9 memakai audit ID BARU (hasil audit read-only produksi 2026-10-21,
  belum ada di dokumen audit 2026-10-21): PROD-01 (privasi bucket storage),
  PROD-02 (kelengkapan profiles.perusahaan), PROD-03 (tabel public_link_audits
  + DDL-nya), PROD-04 (cakupan detail storage di audit trail), PROD-05
  (distribusi outcome/source), dan PROD-06 (konsistensi soft-delete produk).
  CATATAN: dokumen audit 2026-10-21 tidak punya ID "U10" maupun "F-19";
  label itu dipakai script ini untuk item section 11 ("status eksekusi migrasi
  001-007" dan "privat/publik bucket Supabase"). "B4" merujuk ke badge Bab IV
  hardcode "5/5" (dokumen section 8 + 7.3), "D13" ke temuan integritas
  constraint/data section 7.3, "B6" ke PO tanpa `tanggal_po` yang tidak masuk
  KPI /po-analytics.

KEAMANAN (WAJIB DIBACA)
  READ-ONLY. Skrip ini HANYA issuing SELECT (atau read-RPC yang tidak
  dieksekusi sebagai write). Tidak ada insert / update / delete / upsert,
  tidak ada pemanggilan fungsi yang mengubah data, dan tidak ada penulisan ke
  database. Satu-satunya keluaran adalah stdout.
  STAGING-ONLY. Skrip menolak jalan bila target bukan host staging eksak
  (`odtfppboyjlbatajncgj.supabase.co`). Guard yang dipakai milik repo sendiri:
  `app.staging_preflight.validate_staging_file()` (sumber tunggal
  `.env.staging`) plus `validate_mapping(..., source="effective-env")` untuk
  memvalidasi ulang setiap override dari environment proses. Override tetap
  WAJIB lolos guard, jadi override tidak pernah bisa mengarahkan skrip ke
  produksi. File `.env` produksi tidak pernah dibaca.
  TIDAK MENYECREK SEKALI PUN. Nilai env, token, service-role key, dan URL
  penuh tidak pernah dicetak; hanya hostname target yang ditampilkan. Data
  `profiles` (email / full_name) tidak pernah dicetak - hanya count dan
  boolean. Nama produk tidak dicetak di sini karena tidak diperlukan.

Prasyarat
  - venv repo aktif: `venv\Scripts\python.exe` (Python 3.11)
  - package `supabase` (sudah ada di requirements.txt) - tidak butuh pytest
  - file `.env.staging` LENGKAP (10 env var wajib preflight: DIP_APP_ENV,
    SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_ROLE_KEY, STORAGE_BACKEND,
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_PUBLIC_BASES,
    R2_BUCKET_SUFFIX)
  - jaringan keluar ke host staging Supabase
  - TIDAK perlu menjalankan server aplikasi (skrip ini tidak menyentuh app)

Perintah
  venv\Scripts\python.exe tests\verify_audit_db_state.py
  (dari root repo `D:\dip-app`)

Environment yang dipakai
  - `SUPABASE_URL`              : opsional, override dari `.env.staging`
  - `SUPABASE_SERVICE_ROLE_KEY` : opsional, override dari `.env.staging`
  Keduanya WAJIB tetap lolos guard staging (hostname eksak + binding key).

Exit code
  0 = semua check PASS (tidak ada FAIL)
  1 = ada >= 1 check FAIL
  2 = skrip tidak bisa dijalankan (`.env.staging` hilang/tidak lengkap, guard
      gagal, atau database tidak terjangkau) - tidak ada check yang dievaluasi
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.staging"

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_CANNOT_RUN = 2

CALLER = "verify-audit-db-state"
WIB = timezone(timedelta(hours=7))
PAGE = 1000
MAX_PAGES = 50

RESULTS: list[dict] = []
AUDIT: dict[str, dict] = {}

# --------------------------------------------------------------------------- #
# Helper output
# --------------------------------------------------------------------------- #
def check(name, ok, value, detail="", known=None, *, cid="", targets=(), conclusion=None):
    """Cetak satu baris hasil check dan simpan untuk ringkasan.

    ok    : True  -> [PASS]
            False -> [FAIL]
            None  -> [INFO] (informasi, bukan pass/fail)
            str   -> verdict literal, mis. "WARN"
    value : nilai terukur (dicetak apa adanya)
    detail: penjelasan singkat (tanpa secret)
    known : baseline yang tertulis di dokumen audit (dicetak sebagai anotasi)
    cid   : id check, mis. "G1.1"
    targets   : tuple audit ID yang disentuh check ini
    conclusion: "confirmed" | "refuted" | "unverifiable" | "neutral"
    """
    if ok is True:
        verdict = "PASS"
    elif ok is False:
        verdict = "FAIL"
    elif ok is None:
        verdict = "INFO"
    else:
        verdict = str(ok).upper()

    label = name if (cid and name.startswith(cid)) else f"{cid} {name}".strip()
    line = f"[{verdict}] {label} = {value}"
    if detail:
        line += f" - {detail}"
    if known is not None:
        line += f" (audit: {known})"
    print(line)

    RESULTS.append({
        "verdict": verdict,
        "cid": cid,
        "name": name,
        "value": value,
        "detail": detail,
        "targets": tuple(targets),
    })
    if conclusion:
        order = {"confirmed": 3, "refuted": 2, "unverifiable": 1, "neutral": 0}
        for target in targets:
            slot = AUDIT.setdefault(target, {"verdict": None, "checks": []})
            slot["checks"].append(cid)
            if slot["verdict"] is None or order[conclusion] > order[slot["verdict"]]:
                slot["verdict"] = conclusion
    return verdict


def info(name, value, detail="", known=None, *, cid="", targets=(), conclusion=None):
    return check(name, None, value, detail, known, cid=cid, targets=targets, conclusion=conclusion)


def warn(name, value, detail="", known=None, *, cid="", targets=(), conclusion=None):
    return check(name, "WARN", value, detail, known, cid=cid, targets=targets, conclusion=conclusion)


def abort(message):
    """Batalkan skrip dengan pesan [ABORT] dan exit code 2 (tidak bisa dijalankan)."""
    print(message, file=sys.stderr)
    raise SystemExit(EXIT_CANNOT_RUN)


# --------------------------------------------------------------------------- #
# Guard staging (cermin tests/e2e_smoke_refactor.py)
# --------------------------------------------------------------------------- #
def load_and_guard():
    """Muat .env.staging lalu fail-closed bila target bukan staging eksak.

    Sama seperti `load_and_guard()` di tests/e2e_smoke_refactor.py, dengan satu
    tambahan: override dari environment proses (SUPABASE_URL /
    SUPABASE_SERVICE_ROLE_KEY) divalidasi ulang terhadap guard yang sama, jadi
    override tidak pernah bisa mengarahkan skrip ke produksi.
    """
    if not ENV_FILE.exists():
        abort(f"[ABORT] {ENV_FILE.name} tidak ditemukan.")
    sys.path.insert(0, str(ROOT))
    from app.staging_preflight import (
        parse_dotenv_file,
        validate_mapping,
        validate_staging_file,
    )

    cfg = parse_dotenv_file(str(ENV_FILE))
    try:
        validate_staging_file(cfg, caller=CALLER)
    except RuntimeError as exc:
        abort(f"[ABORT] guard staging gagal: {exc}")

    eff = dict(cfg)
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        override = (os.getenv(key) or "").strip()
        if override:
            eff[key] = override
    try:
        validate_mapping(eff, source="effective-env", caller=CALLER)
    except RuntimeError as exc:
        abort(f"[ABORT] guard staging gagal (effective-env): {exc}")
    return eff


def db_client(cfg: dict):
    """Klien Supabase service-role (pemakaian read-only pada skrip ini)."""
    from supabase import create_client

    return create_client(cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_ROLE_KEY"])


def target_label(cfg: dict) -> str:
    """Hostname target saja - JANGAN pernah mencetak URL penuh / key."""
    return urlparse(cfg.get("SUPABASE_URL", "")).hostname or "?"


# --------------------------------------------------------------------------- #
# Helper query (semua READ-ONLY)
# --------------------------------------------------------------------------- #
def err_text(exc) -> str:
    return f"{type(exc).__name__}: {exc}"


def is_missing_relation(exc) -> bool:
    text = str(exc).lower()
    return (
        "pgrst205" in text
        or "42p01" in text
        or "could not find the table" in text
        or "could not find the view" in text
        or ("relation" in text and "does not exist" in text)
    )


def is_missing_column(exc) -> bool:
    text = str(exc).lower()
    return (
        "pgrst204" in text
        or "42703" in text
        or "does not exist" in text
        or ("column" in text and ("schema cache" in text or "could not find" in text))
    )


def relation_exists(db, table) -> tuple[bool, str]:
    """Cek tabel/view ada atau tidak. (True, "") = ada."""
    try:
        db.table(table).select("*").limit(1).execute()
        return True, ""
    except Exception as exc:  # noqa: BLE001
        if is_missing_relation(exc):
            return False, err_text(exc)
        return True, err_text(exc)


def probe_columns(db, table, columns) -> tuple[dict, bool, str]:
    """Probe tiap kolom satu per satu. -> ({kolom: bool}, tabel_ada, err)."""
    present: dict[str, bool] = {}
    table_ok = True
    err = ""
    for col in columns:
        try:
            db.table(table).select(col).limit(1).execute()
            present[col] = True
        except Exception as exc:  # noqa: BLE001
            if is_missing_relation(exc):
                table_ok = False
                err = err_text(exc)
                present[col] = False
            elif is_missing_column(exc):
                present[col] = False
            else:
                present[col] = False
                err = err_text(exc)
    return present, table_ok, err


def count_where(db, table, filters=(), column="id"):
    """Count exact dengan filter PostgREST. -> int (atau None bila error).

    `count="exact"` + `limit(1)` mengembalikan jumlah total hasil filter di
    header Content-Range tanpa menarik seluruh baris.
    """
    query = db.table(table).select(column, count="exact").limit(1)
    for apply_filter in filters:
        query = apply_filter(query)
    resp = query.execute()
    return resp.count


def fetch_rows(db, table, columns, page=PAGE, max_pages=MAX_PAGES):
    """Baca baris (bounded) untuk deteksi duplikat di Python. -> (rows, truncated)."""
    rows: list[dict] = []
    offset = 0
    for _ in range(max_pages):
        resp = (
            db.table(table)
            .select(", ".join(columns))
            .range(offset, offset + page - 1)
            .execute()
        )
        data = resp.data or []
        rows.extend(data)
        if len(data) < page:
            return rows, False
        offset += page
    return rows, True


def pct(part: int, whole: int) -> str:
    if not whole:
        return "n/a"
    return f"{part / whole * 100:.1f}%"


def parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------- #
# Helper tambahan untuk GROUP 9 (katalog PostgREST, storage, folder migrasi)
# --------------------------------------------------------------------------- #
def json_text(value) -> str:
    """Serialisasi nilai JSON seperti `changes::text` (dipakai untuk pencocokan LIKE)."""
    return json.dumps(value, default=str, ensure_ascii=False)


def fetch_filtered(db, table, columns, filters=(), page=PAGE, max_pages=MAX_PAGES):
    """Baca baris (bounded) dengan filter PostgREST. -> (rows, truncated)."""
    rows: list[dict] = []
    offset = 0
    for _ in range(max_pages):
        query = (db.table(table)
                 .select(", ".join(columns))
                 .range(offset, offset + page - 1))
        for apply_filter in filters:
            query = apply_filter(query)
        resp = query.execute()
        data = resp.data or []
        rows.extend(data)
        if len(data) < page:
            return rows, False
        offset += page
    return rows, True


def information_schema_columns(db, schema, table):
    """Baca `information_schema.columns` lewat PostgREST. -> ({kolom: tipe}, err)."""
    try:
        resp = (db.table("information_schema.columns")
                .select("column_name, data_type")
                .eq("table_schema", schema)
                .eq("table_name", table)
                .limit(200)
                .execute())
    except Exception as exc:  # noqa: BLE001
        return {}, err_text(exc)
    data = resp.data or []
    return {str(r.get("column_name")): str(r.get("data_type")) for r in data}, ""


def rest_openapi_columns(cfg, table):
    """Definisi kolom dari OpenAPI PostgREST (GET /rest/v1/) - metadata saja.

    -> {kolom: tipe} (format Postgres: jsonb / uuid / text / ...).
    """
    import httpx

    key = cfg["SUPABASE_SERVICE_ROLE_KEY"]
    url = cfg["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
    resp = httpx.get(
        url,
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=30,
    )
    resp.raise_for_status()
    props = ((resp.json().get("definitions") or {}).get(table) or {}).get("properties") or {}
    return {str(name): str(spec.get("format") or spec.get("type") or "")
            for name, spec in props.items()}


def table_columns(db, cfg, table, schema="public"):
    """Nama + tipe kolom sebuah tabel (READ-ONLY). -> ({kolom: tipe}, sumber, err).

    Sumber utama `information_schema.columns`. Kalau skema katalog tidak
    diekspos PostgREST (di Supabase biasanya hanya `public`), fallback ke OpenAPI
    PostgREST (`GET /rest/v1/`) - keduanya metadata, tanpa membaca isi tabel.
    """
    cols, err = information_schema_columns(db, schema, table)
    if cols:
        return cols, "information_schema.columns", ""
    try:
        props = rest_openapi_columns(cfg, table)
    except Exception as exc:  # noqa: BLE001
        return {}, "gagal", f"{err} | {err_text(exc)}"
    if props:
        return props, "OpenAPI PostgREST (GET /rest/v1/)", ""
    return {}, "OpenAPI PostgREST (GET /rest/v1/)", err or "tabel tidak ada di schema cache"


def storage_path_from_url(url: str) -> str:
    """Path objek dari URL storage (Supabase public / R2 public), tanpa host."""
    if not url:
        return ""
    parts = [p for p in (urlparse(str(url)).path or "").split("/") if p]
    # Supabase: /storage/v1/object/public/<bucket>/<path>
    if len(parts) >= 5 and parts[:4] == ["storage", "v1", "object", "public"]:
        parts = parts[4:]
    if parts and parts[0] in BUCKETS:
        parts = parts[1:]
    return "/".join(parts)


def list_bucket_objects(db, bucket, max_depth=3, max_objects=500):
    """Daftar path objek di sebuah bucket (metadata saja, tanpa mengunduh).
    -> (paths, truncated)
    """
    paths: list[str] = []
    frontier = [""]
    for _ in range(max_depth):
        next_frontier: list[str] = []
        for prefix in frontier:
            try:
                entries = db.storage.from_(bucket).list(prefix) or []
            except Exception:  # noqa: BLE001
                continue
            for entry in entries:
                name = str(entry.get("name") or "")
                if not name:
                    continue
                full = f"{prefix}/{name}" if prefix else name
                if entry.get("id"):
                    paths.append(full)
                    if len(paths) >= max_objects:
                        return paths, True
                else:
                    next_frontier.append(full)
        frontier = next_frontier
        if not frontier:
            break
    return paths, False


def find_migration_files(table_name):
    """File .sql di folder migration/ yang menyebut sebuah nama tabel. -> [nama file]."""
    found: list[str] = []
    if not MIGRATION_DIR.is_dir():
        return found
    needle = table_name.lower()
    for sql_file in sorted(MIGRATION_DIR.glob("*.sql")):
        try:
            text = sql_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if needle in text.lower():
            found.append(sql_file.name)
    return found

# --------------------------------------------------------------------------- #
# GROUP 1 - Migrasi & kapabilitas akses publik (SEC-09, BE-20, U10)
# --------------------------------------------------------------------------- #
CAPABILITY_COLS = ["public_access_enabled", "public_access_token", "bpom_registered_link"]


def group1(db):
    print("\n-- GROUP 1: Migrasi & kapabilitas akses publik (SEC-09, BE-20, U10) --")
    present, table_ok, err = probe_columns(db, "products", CAPABILITY_COLS)
    missing = [c for c in CAPABILITY_COLS if not present.get(c)]
    found = [c for c in CAPABILITY_COLS if present.get(c)]

    if not table_ok:
        check("G1.1 kolom-kapability-public-access", "FAIL", "TABEL products TIDAK ADA",
              err or "tabel products tidak ditemukan",
              "migrasi 007 menambah 3 kolom ini",
              cid="G1.1", targets=("SEC-09", "BE-20", "U10"), conclusion="unverifiable")
        missing = list(CAPABILITY_COLS)
    elif missing:
        check("G1.1 kolom-kapability-public-access", "FAIL",
              f"HANYA {len(found)}/{len(CAPABILITY_COLS)} (missing: {', '.join(missing)})",
              "fallback dip_public.py:294-300 aktif (fail-OPEN): semua produk publik "
              "dengan UUID saja tanpa token",
              "migrasi 007 harus sudah dieksekusi",
              cid="G1.1", targets=("SEC-09", "BE-20", "U10"), conclusion="confirmed")
    else:
        check("G1.1 kolom-kapability-public-access", "PASS", f"3/3 ({', '.join(found)})",
              "fallback fail-OPEN tidak terpicu; token wajib untuk produk non-BPOM",
              "migrasi 007 harus sudah dieksekusi",
              cid="G1.1", targets=("SEC-09", "BE-20", "U10"), conclusion="refuted")

    total = count_where(db, "products")
    total = total if isinstance(total, int) else 0

    if missing:
        for cid, name, detail in [
            ("G1.2", "produk-public_access_token-NULL",
             "tidak terukur: kolom public_access_token tidak ada di DB staging"),
            ("G1.3", "produk-public_access_enabled-false",
             "tidak terukur: kolom public_access_enabled tidak ada di DB staging"),
            ("G1.4", "produk-bpom_registered_link-true",
             "tidak terukur: kolom bpom_registered_link tidak ada di DB staging"),
            ("G1.5", "produk-token-set-tapi-enabled-false",
             "tidak terukur: kolom capability tidak ada di DB staging"),
        ]:
            info(name, "TIDAK TERUKUR", detail,
                 "migrasi 007 harus sudah dieksekusi",
                 cid=cid, targets=("BE-20", "SEC-09"), conclusion="unverifiable")
        return

    null_token = count_where(db, "products", [lambda q: q.is_("public_access_token", "null")])
    null_token = null_token if isinstance(null_token, int) else 0
    check("G1.2 produk-public_access_token-NULL", "PASS" if null_token == 0 else "FAIL",
          f"{null_token}/{total} ({pct(null_token, total)})",
          "produk tanpa token = produk yang tetap bisa diakses publik hanya dengan UUID"
          if null_token else "semua produk punya token capability",
          "BE-20: produk legacy tanpa token tetap publik",
          cid="G1.2", targets=("BE-20",),
          conclusion="confirmed" if null_token else "refuted")

    disabled = count_where(db, "products", [lambda q: q.eq("public_access_enabled", False)])
    disabled = disabled if isinstance(disabled, int) else 0
    check("G1.3 produk-public_access_enabled-false", "PASS" if disabled else "INFO",
          f"{disabled}/{total}",
          "produk dengan akses publik dimatikan (gate berfungsi bila token global)"
          if disabled else "tidak ada produk yang akses publiknya dimatikan",
          cid="G1.3", targets=("SEC-09",), conclusion="neutral")

    bpom = count_where(db, "products", [lambda q: q.eq("bpom_registered_link", True)])
    bpom = bpom if isinstance(bpom, int) else 0
    check("G1.4 produk-bpom_registered_link-true", "PASS" if bpom else "INFO",
          f"{bpom}/{total}",
          "produk terdaftar BPOM boleh diakses tanpa token (jalur legacy yang disengaja)"
          if bpom else "tidak ada produk terdaftar BPOM di staging",
          cid="G1.4", targets=("SEC-09",), conclusion="neutral")

    inconsistent = count_where(db, "products", [
        lambda q: q.not_.is_("public_access_token", "null").eq("public_access_enabled", False)
    ])
    inconsistent = inconsistent if isinstance(inconsistent, int) else 0
    check("G1.5 produk-token-set-tapi-enabled-false", "PASS" if inconsistent == 0 else "WARN",
          f"{inconsistent}/{total}",
          "INKONSISTEN: punya token tapi akses dimatikan (state tak terduga)" if inconsistent
          else "tidak ada state inkonsisten (token set & enabled=false)",
          cid="G1.5", targets=("SEC-09",), conclusion="neutral")


# --------------------------------------------------------------------------- #
# GROUP 2 - Soft delete produk (SEC-01)
# --------------------------------------------------------------------------- #
def group2(db):
    print("\n-- GROUP 2: Soft delete produk (SEC-01) --")
    total = count_where(db, "products")
    total = total if isinstance(total, int) else 0
    deleted = count_where(db, "products", [lambda q: q.eq("is_deleted", True)])
    deleted = deleted if isinstance(deleted, int) else 0

    if deleted == 0:
        check("G2.1 produk-is_deleted-true", "PASS", f"0/{total}",
              "fitur Sampah belum pernah dipakai: tidak ada route di app/ yang menulis "
              "is_deleted=True, konsisten dengan temuan SEC-01",
              "SEC-01: tidak ada route soft delete produk",
              cid="G2.1", targets=("SEC-01",), conclusion="confirmed")
    else:
        check("G2.1 produk-is_deleted-true", "WARN", f"{deleted}/{total}",
              "ADA produk soft-deleted di staging padahal tidak ada route delete di app/ "
              "(route restore /admin/products/{id}/restore ADA) -> baris kemungkinan dibuat "
              "manual lewat SQL Editor, bukan lewat UI",
              "SEC-01: tidak ada route soft delete produk",
              cid="G2.1", targets=("SEC-01",), conclusion="refuted")

    has_deleted_at, _tbl_ok, _err = probe_columns(db, "products", ["deleted_at"])
    if not has_deleted_at.get("deleted_at"):
        info("G2.2 produk-deleted_at-not-null", "TIDAK TERUKUR",
             "kolom products.deleted_at tidak ada di DB staging",
             cid="G2.2", targets=("SEC-01",), conclusion="unverifiable")
        return
    stamped = count_where(db, "products", [lambda q: q.not_.is_("deleted_at", "null")])
    stamped = stamped if isinstance(stamped, int) else 0
    consistent = (stamped == deleted)
    check("G2.2 produk-deleted_at-not-null", "PASS" if consistent else "WARN",
          f"{stamped} (is_deleted_true={deleted})",
          "konsisten: baris deleted_at terisi tepat pada produk soft-deleted" if consistent
          else "TIDAK konsisten: jumlah deleted_at terisi tidak sama dengan is_deleted=true",
          cid="G2.2", targets=("SEC-01",), conclusion="neutral")


# --------------------------------------------------------------------------- #
# GROUP 3 - Constraint database (D13, B4)
# --------------------------------------------------------------------------- #
def group3(db):
    print("\n-- GROUP 3: Constraint database (D13, B4) --")
    detail_empty = ("tabel kosong di staging -> duplikat tidak dapat dibuktikan ada/tidak; "
                    "keberadaan UNIQUE constraint hanya bisa dipastikan lewat SQL Editor "
                    "(information_schema / pg_constraint), yang TIDAK dieksekusi skrip ini")

    # 8. purchase_orders.no_po UNIQUE?
    po_rows, po_trunc = fetch_rows(db, "purchase_orders", ["no_po"])
    po_total = count_where(db, "purchase_orders")
    po_total = po_total if isinstance(po_total, int) else len(po_rows)
    po_counter = Counter((r.get("no_po") or "").strip() for r in po_rows)
    po_dups = {k: v for k, v in po_counter.items() if v > 1 and k}
    blank_po = po_counter.get("", 0)
    if po_trunc or len(po_rows) < po_total:
        info("G3.1 purchase_orders-no_po-duplikat", "TIDAK TERUKUR",
             f"hanya {len(po_rows)}/{po_total} baris terbaca (truncasi PostgREST)",
             cid="G3.1", targets=("D13", "B4"), conclusion="unverifiable")
    elif po_total == 0:
        info("G3.1 purchase_orders-no_po-duplikat", "0 grup (0 baris)", detail_empty,
             cid="G3.1", targets=("D13", "B4"), conclusion="unverifiable")
    else:
        check("G3.1 purchase_orders-no_po-duplikat",
              "PASS" if not po_dups else "FAIL",
              f"{len(po_dups)} grup duplikat dari {po_total} baris"
              + (f", {blank_po} baris no_po kosong" if blank_po else ""),
              "constraint UNIQUE(no_po) terpenuhi" if not po_dups
              else "DUPLIKAT ada -> constraint UNIQUE(no_po) tidak ada/terbypass",
              "D13: integritas constraint DB",
              cid="G3.1", targets=("D13", "B4"),
              conclusion="refuted" if not po_dups else "confirmed")

    # 9. purchase_order_items UNIQUE(purchase_order_id, urutan)
    item_rows, item_trunc = fetch_rows(db, "purchase_order_items",
                                        ["purchase_order_id", "urutan"])
    item_total = count_where(db, "purchase_order_items")
    item_total = item_total if isinstance(item_total, int) else len(item_rows)
    item_counter = Counter(
        (str(r.get("purchase_order_id")), str(r.get("urutan"))) for r in item_rows
    )
    item_dups = {k: v for k, v in item_counter.items() if v > 1}
    max_group = max(item_dups.values()) if item_dups else 0
    if item_trunc or len(item_rows) < item_total:
        info("G3.2 purchase_order_items-duplikat-po_urutan", "TIDAK TERUKUR",
             f"hanya {len(item_rows)}/{item_total} baris terbaca (truncasi PostgREST)",
             cid="G3.2", targets=("D13", "B4"), conclusion="unverifiable")
    elif item_total == 0:
        info("G3.2 purchase_order_items-duplikat-po_urutan", "0 grup (0 baris)", detail_empty,
             cid="G3.2", targets=("D13", "B4"), conclusion="unverifiable")
    else:
        check("G3.2 purchase_order_items-duplikat-po_urutan",
              "PASS" if not item_dups else "FAIL",
              f"{len(item_dups)} grup duplikat, max {max_group} baris per grup, "
              f"dari {item_total} baris",
              "constraint UNIQUE(purchase_order_id, urutan) terpenuhi" if not item_dups
              else "DUPLIKAT ada -> constraint UNIQUE(purchase_order_id, urutan) tidak ada/terbypass",
              "D13: integritas constraint DB",
              cid="G3.2", targets=("D13", "B4"),
              conclusion="refuted" if not item_dups else "confirmed")

    # 10. product_batches UNIQUE(product_id, no_batch)
    batch_rows, batch_trunc = fetch_rows(db, "product_batches", ["product_id", "no_batch"])
    batch_total = count_where(db, "product_batches")
    batch_total = batch_total if isinstance(batch_total, int) else len(batch_rows)
    batch_counter = Counter(
        (str(r.get("product_id")), (r.get("no_batch") or "").strip()) for r in batch_rows
    )
    batch_dups = {k: v for k, v in batch_counter.items() if v > 1}
    if batch_trunc or len(batch_rows) < batch_total:
        info("G3.3 product_batches-duplikat-product_no_batch", "TIDAK TERUKUR",
             f"hanya {len(batch_rows)}/{batch_total} baris terbaca (truncasi PostgREST)",
             cid="G3.3", targets=("D13", "B4"), conclusion="unverifiable")
    elif batch_total == 0:
        info("G3.3 product_batches-duplikat-product_no_batch", "0 grup (0 baris)", detail_empty,
             cid="G3.3", targets=("D13", "B4"), conclusion="unverifiable")
    else:
        check("G3.3 product_batches-duplikat-product_no_batch",
              "PASS" if not batch_dups else "FAIL",
              f"{len(batch_dups)} grup duplikat dari {batch_total} baris",
              "tidak ada nomor batch kembar per produk" if not batch_dups
              else "DUPLIKAT ada -> nomor batch kembar bisa menimpa path file yang sama (BE-10)",
              "D13: integritas constraint DB; BE-10: path file berbasis nomor batch "
              "(baris sedikit: ini indikasi, bukan bukti constraint)",
              cid="G3.3", targets=("D13", "B4", "BE-10"),
              conclusion="unverifiable")

    # 11. purchase_order_items dengan product_id / product_batch_id NULL
    null_pid = count_where(db, "purchase_order_items", [lambda q: q.is_("product_id", "null")])
    null_pid = null_pid if isinstance(null_pid, int) else 0
    null_bid = count_where(db, "purchase_order_items",
                            [lambda q: q.is_("product_batch_id", "null")])
    null_bid = null_bid if isinstance(null_bid, int) else 0
    if item_total == 0:
        info("G3.4 purchase_order_items-product_id/product_batch_id-NULL",
             "0/0 (tabel kosong)",
             "audit menyebut keduanya NOT NULL; tidak ada data untuk mengonfirmasi",
             cid="G3.4", targets=("D13",), conclusion="unverifiable")
    else:
        check("G3.4 purchase_order_items-product_id/product_batch_id-NULL",
              "PASS" if (null_pid == 0 and null_bid == 0) else "FAIL",
              f"product_id NULL={null_pid}, product_batch_id NULL={null_bid} (total {item_total})",
              "sesuai constraint NOT NULL di migrasi 001" if (null_pid == 0 and null_bid == 0)
              else "ada NULL padahal kolom NOT NULL (kemungkinan data lama sebelum migrasi)",
              "D13: integritas constraint DB",
              cid="G3.4", targets=("D13",), conclusion="neutral")


# --------------------------------------------------------------------------- #
# GROUP 4 - Nullability berisiko TypeError/KeyError (BE-10, BE-25)
# --------------------------------------------------------------------------- #
def group4(db):
    print("\n-- GROUP 4: Nullability berisiko TypeError/KeyError (BE-10, BE-25) --")
    fn_null = count_where(db, "profiles", [lambda q: q.is_("full_name", "null")])
    fn_null = fn_null if isinstance(fn_null, int) else 0
    prof_total = count_where(db, "profiles")
    prof_total = prof_total if isinstance(prof_total, int) else 0
    check("G4.1 profiles-full_name-NULL", "PASS" if fn_null == 0 else "FAIL",
          f"{fn_null}/{prof_total}",
          "tidak ada profil tanpa nama -> BE-25 (KeyError full_name saat login) tidak terpicu"
          if fn_null == 0 else
          "ADA profil tanpa nama -> main.py:1112 `profile_resp.data[0]['full_name']` KeyError",
          "BE-25: full_name NULL -> KeyError",
          cid="G4.1", targets=("BE-25",),
          conclusion="refuted" if fn_null == 0 else "confirmed")

    pi_null = count_where(db, "raw_material_components",
                           [lambda q: q.is_("percent_internal", "null")])
    pi_null = pi_null if isinstance(pi_null, int) else 0
    rmc_total = count_where(db, "raw_material_components")
    rmc_total = rmc_total if isinstance(rmc_total, int) else 0
    check("G4.2 raw_material_components-percent_internal-NULL",
          "PASS" if pi_null == 0 else "FAIL", f"{pi_null}/{rmc_total}",
          "tidak ada persentase NULL -> tidak ada TypeError di raw_materials_routes.py:587"
          if pi_null == 0 else
          "ADA persen NULL -> float(None) pada raw_materials_routes.py:587 bisa TypeError",
          "section 11: kolom percent_internal NULL menentukan TypeError",
          cid="G4.2", targets=("BE-10",),
          conclusion=("unverifiable" if rmc_total == 0
                      else ("refuted" if pi_null == 0 else "confirmed")))

    ed_null = count_where(db, "raw_material_batches", [lambda q: q.is_("tanggal_ed", "null")])
    ed_null = ed_null if isinstance(ed_null, int) else 0
    rmb_total = count_where(db, "raw_material_batches")
    rmb_total = rmb_total if isinstance(rmb_total, int) else 0
    check("G4.3 raw_material_batches-tanggal_ed-NULL",
          "PASS" if ed_null == 0 else "WARN", f"{ed_null}/{rmb_total}",
          "semua batch punya tanggal ED" if ed_null == 0 else
          "batch tanpa tanggal ED dilewati (continue) oleh notifikasi ED",
          "section 11: baris tanpa ED dilewati notifikasi ED",
          cid="G4.3", targets=("FE-03",),
          conclusion="unverifiable" if rmb_total == 0 else "neutral")

    po_null = count_where(db, "purchase_orders", [lambda q: q.is_("tanggal_po", "null")])
    po_null = po_null if isinstance(po_null, int) else 0
    po_total = count_where(db, "purchase_orders")
    po_total = po_total if isinstance(po_total, int) else 0
    if po_total == 0:
        info("G4.4 purchase_orders-tanggal_po-NULL", "0/0 (tabel kosong)",
             "tidak ada data untuk mengukur dampak KPI total_po/total_pcs",
             "B6: PO tanpa tanggal_po tidak masuk KPI",
             cid="G4.4", targets=("B6",), conclusion="unverifiable")
    else:
        check("G4.4 purchase_orders-tanggal_po-NULL",
              "PASS" if po_null == 0 else "FAIL", f"{po_null}/{po_total}",
              "semua PO punya tanggal -> KPI /po-analytics menghitung semua PO" if po_null == 0
              else f"{po_null} PO dikeluarkan dari KPI total_po/total_pcs (po_routes.py:318-321)",
              "B6: PO tanpa tanggal_po tidak masuk KPI",
              cid="G4.4", targets=("B6",),
              conclusion="refuted" if po_null == 0 else "confirmed")


# --------------------------------------------------------------------------- #
# GROUP 5 - Skema presence (FE-02)
# --------------------------------------------------------------------------- #
def group5(db):
    print("\n-- GROUP 5: Skema presence (FE-02) --")
    presence_cols = ["last_seen_at", "last_activity_at", "is_online"]
    present, table_ok, err = probe_columns(db, "profiles", presence_cols)
    missing = [c for c in presence_cols if not present.get(c)]
    if not table_ok:
        check("G5.1 profiles-kolom-presence", "FAIL", "TABEL profiles TIDAK ADA", err,
              cid="G5.1", targets=("FE-02",), conclusion="confirmed")
    else:
        check("G5.1 profiles-kolom-presence", "PASS" if not missing else "FAIL",
              f"{len(presence_cols) - len(missing)}/{len(presence_cols)} ada"
              + (f" (missing: {', '.join(missing)})" if missing else ""),
              "heartbeat presence_routes.py:37 menulis ke kolom yang ADA -> bukan no-op, "
              "jadi 144 tulis/jam/user benar-benar terjadi" if not missing else
              "heartbeat diam-diam: kolom presence tidak ada -> semua user tampil Offline",
              "FE-02: heartbeat menulis 144 baris/jam/user",
              cid="G5.1", targets=("FE-02",),
              conclusion="confirmed" if not missing else "refuted")

    view_ok, _ = relation_exists(db, "product_formula_presence")
    if view_ok:
        view_count = None
        try:
            resp = (db.table("product_formula_presence")
                    .select("product_id", count="exact").limit(1).execute())
            view_count = resp.count
        except Exception:  # noqa: BLE001
            pass
        check("G5.2 view-product_formula_presence", "PASS",
              f"ADA ({view_count} produk punya formula)",
              "dashboard memakai view agregat (dashboard_routes.py:93-108), bukan fetch "
              "product_formula_lines penuh yang bisa terpotong 1000 baris",
              cid="G5.2", targets=("B4",), conclusion="neutral")
    else:
        check("G5.2 view-product_formula_presence", "FAIL", "TIDAK ADA",
              "dashboard jatuh ke jalur fallback pagination (dashboard_routes.py:93-108); "
              "status Bab II bisa salah tampil 'Kosong'",
              cid="G5.2", targets=("B4",), conclusion="confirmed")

    dash_cols = ["tanggal_aktif_na", "status_na", "data_klaim_file_url",
                 "monitoring_efek_samping_file_url"]
    d_present, _table_ok, _d_err = probe_columns(db, "products", dash_cols)
    d_missing = [c for c in dash_cols if not d_present.get(c)]
    check("G5.3 products-kolom-dashboard", "PASS" if not d_missing else "FAIL",
          f"{len(dash_cols) - len(d_missing)}/{len(dash_cols)} ada"
          + (f" (missing: {', '.join(d_missing)})" if d_missing else ""),
          "semua kolom yang dipakai dashboard tersedia" if not d_missing
          else "dashboard/NA/NIES memakai kolom yang tidak ada",
          cid="G5.3", targets=("FE-02", "FE-03"),
          conclusion="neutral" if not d_missing else "confirmed")


# --------------------------------------------------------------------------- #
# GROUP 6 - Volume data (FE-03, B4)
# --------------------------------------------------------------------------- #
VOLUME_TABLES = [
    "raw_material_batches", "products", "raw_materials", "purchase_orders",
    "purchase_order_items", "product_formula_lines", "team_notes",
    "product_attachments", "activity_logs",
]


def group6(db):
    print("\n-- GROUP 6: Volume data (FE-03, B4) --")
    total_rows = 0
    for table in VOLUME_TABLES:
        exists, _ = relation_exists(db, table)
        if not exists:
            warn("G6.1 volume-tabel", "TABEL TIDAK ADA",
                 f"tabel {table} tidak ada di DB staging -> migrasi yang membangunnya "
                 "belum dieksekusi; route yang memakainya akan error",
                 cid="G6.1", targets=("U10",), conclusion="confirmed")
            continue
        count = count_where(db, table)
        count = count if isinstance(count, int) else 0
        total_rows += count
        info("G6.1 volume-tabel", count, f"tabel {table}",
             cid="G6.1", targets=("FE-03", "B4"), conclusion="neutral")
    info("G6.1b volume-total-seluruh-9-tabel", total_rows,
         "gabungan 9 tabel (batas 5.000 baris PO analytics di po_routes.py)",
         cid="G6.1b", targets=("FE-03", "B4"), conclusion="unverifiable")

    # 20. ED-critical set: tanggal_ed dalam 180 hari & status_ed != Dimusnahkan
    today = datetime.now(WIB).date()
    ed_rows, _ed_trunc = fetch_rows(db, "raw_material_batches", ["tanggal_ed", "status_ed"])
    ed_total = count_where(db, "raw_material_batches")
    ed_total = ed_total if isinstance(ed_total, int) else len(ed_rows)
    null_status = 0
    critical = 0
    expired = 0
    for row in ed_rows:
        if row.get("status_ed") is None:
            null_status += 1
            continue
        if str(row.get("status_ed")).strip() == "Dimusnahkan":
            continue
        ed_date = parse_date(row.get("tanggal_ed"))
        if ed_date is None:
            continue
        days = (ed_date - today).days
        if days <= 180:
            critical += 1
            if days < 0:
                expired += 1

    na_expired = count_na_expired(db, today)

    if ed_total == 0:
        info("G6.2 ED-critical-<=180-hari", 0,
             "0 batch di staging -> badge ED = 0; volume produksi tidak terukur di staging",
             "FE-03: badge ED menarik seluruh batch + join + seluruh produk",
             cid="G6.2", targets=("FE-03",), conclusion="unverifiable")
    else:
        check("G6.2 ED-critical-<=180-hari", "PASS" if critical == 0 else "INFO",
              f"{critical} batch (dari {ed_total}; {expired} sudah lewat ED)",
              f"bandingkan dengan badge ED di UI; badge juga menambah {na_expired} produk "
              "ber-status NA expired/akan_expired",
              "FE-03: query ED-notification berat di setiap page load",
              cid="G6.2", targets=("FE-03",), conclusion="neutral")
    if null_status:
        warn("G6.2b batch-dengan-status_ed-NULL", null_status,
             "status_ed NULL tersaring oleh neq('status_ed','Dimusnahkan') -> batch ini "
             "tidak pernah muncul di badge ED",
             cid="G6.2b", targets=("FE-03",), conclusion="neutral")


def count_na_expired(db, today) -> int:
    """Hitung produk dengan NA expired / akan_expired (meniru main.py)."""
    try:
        resp = (db.table("products")
                .select("id, tanggal_aktif_na, status_na")
                .in_("status_na", ["akan_expired", "expired"])
                .execute())
    except Exception:  # noqa: BLE001
        return 0
    total = 0
    for row in resp.data or []:
        start = parse_date(row.get("tanggal_aktif_na"))
        if start is None:
            continue
        try:
            expired_date = start.replace(year=start.year + 3)
        except ValueError:
            expired_date = start.replace(year=start.year + 3, day=28)
        if expired_date <= today:
            total += 1
    return total


# --------------------------------------------------------------------------- #
# GROUP 7 - Bucket privacy (SEC / F-19)
# --------------------------------------------------------------------------- #
BUCKETS = ["raw-material-docs", "legal-documents", "product-attachments"]


def group7(db):
    print("\n-- GROUP 7: Bucket privacy (SEC / F-19) --")
    for bucket in BUCKETS:
        try:
            entries = db.storage.from_(bucket).list("")
            info("G7.1 bucket-list-dengan-service-role", f"OK ({len(entries)} entri)",
                 f"bucket {bucket} ada & terjangkau PAKAI service-role; service-role "
                 "melewati RLS/privat bucket, jadi ini TIDAK membuktikan bucket bisa "
                 "diunduh publik - pembuktian butuh probe dengan anon key (tidak dijalankan)",
                 cid="G7.1", targets=("F-19",), conclusion="unverifiable")
        except Exception as exc:  # noqa: BLE001
            check("G7.1 bucket-list-dengan-service-role", "FAIL", "GAGAL",
                 f"bucket {bucket}: {err_text(exc)[:160]}",
                 cid="G7.1", targets=("F-19",), conclusion="confirmed")

    total = count_where(db, "raw_material_batches")
    total = total if isinstance(total, int) else 0
    coa = count_where(db, "raw_material_batches", [lambda q: q.not_.is_("coa_file_url", "null")])
    coa = coa if isinstance(coa, int) else 0
    public_like = 0
    if coa:
        rows, _ = fetch_rows(db, "raw_material_batches", ["coa_file_url"])
        public_like = sum(1 for r in rows
                          if "/storage/v1/object/public/" in str(r.get("coa_file_url") or ""))
    if total == 0:
        info("G7.2 coa_file_url-non-null", "0/0 (tabel kosong)",
             "tidak ada URL CoA tersimpan -> tidak bisa diuji apakah URL publik "
             "(object_store.public_url) sudah bocor ke DB",
             "F-19: privat/publik bucket menentukan apakah CoA bisa diunduh siapa pun",
             cid="G7.2", targets=("F-19",), conclusion="unverifiable")
    else:
        check("G7.2 coa_file_url-non-null", "PASS" if coa == 0 else "WARN",
              f"{coa}/{total} (pola URL publik: {public_like})",
              "tidak ada CoA tersimpan" if coa == 0 else
              "URL hasil object_store.public_url() tersimpan di DB -> objek public "
              "by construction (dapat diunduh tanpa auth bila bucket tidak privat)",
              "F-19: privat/publik bucket menentukan apakah CoA bisa diunduh siapa pun",
              cid="G7.2", targets=("F-19",),
              conclusion="refuted" if coa == 0 else "confirmed")


# --------------------------------------------------------------------------- #
# GROUP 8 - Audit trail schema (migrasi 003)
# --------------------------------------------------------------------------- #
AUDIT_LOG_COLS = ["outcome", "source", "ip_address", "user_agent", "route",
                  "http_method", "request_id"]


def group8(db):
    print("\n-- GROUP 8: Audit trail schema (migrasi 003) --")
    present, table_ok, err = probe_columns(db, "activity_logs", AUDIT_LOG_COLS)
    missing = [c for c in AUDIT_LOG_COLS if not present.get(c)]
    if not table_ok:
        check("G8.1 activity_logs-kolom-audit-hardening", "FAIL",
              "TABEL activity_logs TIDAK ADA", err,
              "migrasi 003 menambah 7 kolom ini",
              cid="G8.1", targets=("U10",), conclusion="unverifiable")
    else:
        check("G8.1 activity_logs-kolom-audit-hardening", "PASS" if not missing else "FAIL",
              f"{len(AUDIT_LOG_COLS) - len(missing)}/{len(AUDIT_LOG_COLS)} ada"
              + (f" (missing: {', '.join(missing)})" if missing else ""),
              "audit trail punya konteks request + verdict -> jejak investigasi lengkap"
              if not missing else "jejak audit tidak lengkap",
              "migrasi 003 menambah 7 kolom",
              cid="G8.1", targets=("U10",),
              conclusion="neutral" if not missing else "confirmed")

    total = count_where(db, "activity_logs")
    total = total if isinstance(total, int) else 0
    with_outcome = count_where(db, "activity_logs", [lambda q: q.not_.is_("outcome", "null")])
    with_outcome = with_outcome if isinstance(with_outcome, int) else 0
    if total == 0:
        info("G8.2 activity_logs-outcome-not-null", "0/0 (tabel kosong)",
             "tidak ada data audit untuk diperiksa",
             cid="G8.2", targets=("U6",), conclusion="unverifiable")
    else:
        check("G8.2 activity_logs-outcome-not-null", "PASS" if with_outcome == total else "WARN",
              f"{with_outcome}/{total} ({pct(with_outcome, total)})",
              "outcome terisi di semua baris (migrasi 003 NOT NULL DEFAULT 'success' + "
              "backfill, jadi baris lama juga terisi - bukan bukti baris baru)",
              cid="G8.2", targets=("U6",), conclusion="neutral")

    # U6: entity_type yang dipakai app (tanpa PII)
    #
    # KOREKSI 2026-10-21: `storage_note` BUKAN entity_type dan BUKAN kolom.
    # Ia keyword-only parameter log_activity (app/main.py:829) yang
    # diserialisasi ke kolom JSON `changes` sebagai
    # {"field": "Storage (R2)", "note": ...} (app/main.py:849-851).
    # Versi lama mengujinya sebagai entity_type -> has_sn permanen False ->
    # verdict permanen "confirmed" (false positive yang tidak pernah bisa refute).
    # Sekarang diuji dua fakta yang saling bebas dan bisa dibuktikan:
    #   (a) entity_type "product_attachment" hadir -> jalur audit lampiran jalan;
    #   (b) kolom changes memuat entri field "Storage (R2)" -> storage_note dipakai.
    try:
        rows = (db.table("activity_logs")
                .select("entity_type, changes")
                .limit(1000).execute().data or [])
        types = sorted({str(r.get("entity_type")) for r in rows if r.get("entity_type")})
        # (a) jalur audit lampiran
        has_pa = "product_attachment" in types
        # (b) mekanisme storage_note (berada di dalam JSON changes, bukan kolom)
        has_sn = any(
            "Storage (R2)" in json.dumps(r.get("changes") or [], default=str)
            for r in rows
        )
        if types:
            if has_pa and has_sn:
                conclusion = "refuted"
                detail = ("(a) entity_type 'product_attachment' ADA -> jalur audit lampiran "
                          "terbukti bekerja; (b) ADA entri changes field 'Storage (R2)' -> "
                          "mekanisme storage_note terekskursi; U6 bukan temuan kode, "
                          "hanya celah dokumentasi")
            elif has_pa:
                conclusion = "confirmed"
                detail = ("(a) entity_type 'product_attachment' ADA -> jalur audit lampiran "
                          "terbukti bekerja; (b) TIDAK ADA entri changes field 'Storage (R2)' "
                          "-> mekanisme storage_note belum pernah terekskursi "
                          "(celah storage_note yang lebih sempit, bukan celah lampiran)")
            else:
                conclusion = "unverifiable"
                detail = ("(a) entity_type 'product_attachment' TIDAK ADA -> jalur audit "
                          "lampiran belum terbukti dari data; (b) "
                          + ("ADA" if has_sn else "TIDAK ADA")
                          + " entri changes field 'Storage (R2)'")
            check("G8.3 activity_logs-entity_type-yang-dipakai", "INFO",
                  f"{len(types)} jenis: {', '.join(types)}",
                  detail,
                  "U6: tabel entitas audit (panduan:699-713) tidak menyebut 5 entity_type - "
                  "product_attachment, product_file, product_batch, purchase_order, "
                  "purchase_order_item; storage_note bukan entity_type melainkan parameter "
                  "log_activity yang masuk ke kolom JSON changes",
                  cid="G8.3", targets=("U6",),
                  conclusion=conclusion)
        else:
            info("G8.3 activity_logs-entity_type-yang-dipakai", "TIDAK ADA DATA",
                 "activity_logs kosong",
                 cid="G8.3", targets=("U6",), conclusion="unverifiable")
    except Exception as exc:  # noqa: BLE001
        info("G8.3 activity_logs-entity_type-yang-dipakai", "TIDAK TERUKUR",
             err_text(exc)[:160],
             cid="G8.3", targets=("U6",), conclusion="unverifiable")


# --------------------------------------------------------------------------- #
# GROUP 9 - Risiko Produksi & Kepatuhan (PROD-01 .. PROD-06)
# --------------------------------------------------------------------------- #
# Audit ID BARU - hasil audit read-only produksi 2026-10-21; belum ada di
# dokumen audit 2026-10-21, jadi ID-nya dipakai script ini:
#   PROD-01  privasi bucket storage + apakah URL publiknya bisa ditebak
#   PROD-02  kelengkapan profiles.perusahaan (tenant guard fail-open)
#   PROD-03  tabel public_link_audits + DDL-nya di folder migration/
#   PROD-04  cakupan detail storage (storage_note) di audit trail
#   PROD-05  distribusi outcome/source activity_logs
#   PROD-06  konsistensi soft-delete produk vs audit trail
#
# Semua check di grup ini READ-ONLY: SELECT PostgREST, Storage API (GET
# metadata bucket), dan GET /rest/v1/ (OpenAPI). Tidak ada request HTTP ke
# objek storage, tidak ada objek yang diunduh, tidak ada insert/update/delete.
MIGRATION_DIR = Path(__file__).resolve().parent.parent / "migration"

# Pola path objek yang bisa disusun ulang dari field bisnis (nomor batch /
# kode bahan baku + slug perusahaan). Sumber: app/raw_materials_routes.py:910
# (coa), :925 (halal), :942 (qc report) dan app/main.py:45 (msds), :56 (spec).
STORAGE_PATH_TEMPLATES = (
    ("coa/coa_{no_batch}.pdf", re.compile(r"^coa/coa_[^/]+\.pdf$")),
    ("qc-reports/qcreport_{no_batch}.pdf", re.compile(r"^qc-reports/qcreport_[^/]+\.pdf$")),
    ("halal/halal_{no_batch}.pdf", re.compile(r"^halal/halal_[^/]+\.pdf$")),
    ("msds/msds_{kode}_{slug}.pdf", re.compile(r"^msds/msds_[^/]+_[^/]+\.pdf$")),
    ("spec-sheets/specsheet_{kode}_{slug}.pdf",
     re.compile(r"^spec-sheets/specsheet_[^/]+_[^/]+\.pdf$")),
)

# Kolom DB yang menyimpan URL hasil object_store.public_url() (publik by
# construction) + bucket tempat path tersebut hidup.
STORAGE_URL_COLUMNS = (
    ("raw_material_batches", "coa_file_url", "raw-material-docs"),
    ("raw_material_batches", "halal_batch_file_url", "raw-material-docs"),
    ("raw_material_batches", "qc_report_file_url", "raw-material-docs"),
    ("raw_material_company_docs", "msds_file_url", "raw-material-docs"),
    ("raw_material_company_docs", "spec_sheet_file_url", "raw-material-docs"),
)


def group9(db, cfg):
    print("\n-- GROUP 9: Risiko Produksi & Kepatuhan (PROD-01 .. PROD-06) --")
    g9_1_bucket_privacy(db)
    g9_2_profiles_perusahaan(db)
    g9_3_public_link_audits(db, cfg)
    g9_4_storage_note_coverage(db, cfg)
    g9_5_outcome_distribution(db)
    g9_6_soft_delete_consistency(db)


def g9_1_bucket_privacy(db):
    """G9.1 - privasi bucket storage + apakah URL-nya bisa ditebak tanpa auth."""
    try:
        buckets = db.storage.list_buckets() or []
    except Exception as exc:  # noqa: BLE001
        check("G9.1 bucket-privasi-storage", "FAIL", "GAGAL",
              f"tidak bisa membaca daftar bucket: {err_text(exc)[:160]}",
              "F-19: privat/publik bucket menentukan apakah CoA bisa diunduh siapa pun",
              cid="G9.1", targets=("PROD-01",), conclusion="unverifiable")
        return

    meta: dict[str, dict] = {}
    for bucket in buckets:
        name = str(getattr(bucket, "id", "") or getattr(bucket, "name", "") or "")
        if name:
            meta[name] = {
                "public": bool(getattr(bucket, "public", False)),
                "limit": getattr(bucket, "file_size_limit", None),
            }

    # Pola path yang terpakai: (1) objek yang ada di bucket, (2) URL di kolom DB.
    guessable: dict[str, set] = {}

    def mark(bucket, label):
        guessable.setdefault(bucket, set()).add(label)

    object_paths: dict[str, list] = {}
    for bucket in BUCKETS:
        if bucket not in meta:
            continue
        paths, _trunc = list_bucket_objects(db, bucket)
        object_paths[bucket] = paths
        for path in paths:
            for label, pattern in STORAGE_PATH_TEMPLATES:
                if pattern.match(path):
                    mark(bucket, label)

    for table, column, bucket in STORAGE_URL_COLUMNS:
        if not relation_exists(db, table)[0]:
            continue
        present, _tbl_ok, _err = probe_columns(db, table, [column])
        if not present.get(column):
            continue
        rows, _trunc = fetch_filtered(
            db, table, [column], [lambda q, c=column: q.not_.is_(c, "null")])
        for row in rows:
            path = storage_path_from_url(row.get(column))
            for label, pattern in STORAGE_PATH_TEMPLATES:
                if pattern.match(path):
                    mark(bucket, label)

    parts: list[str] = []
    bits: list[str] = []
    warn_buckets: list[str] = []
    for bucket in BUCKETS:
        meta_bucket = meta.get(bucket)
        if meta_bucket is None:
            parts.append(f"{bucket}=tidak ada")
            bits.append(f"{bucket} tidak terdaftar di Supabase Storage sehingga flag "
                        "public-nya tidak bisa diukur di environment ini")
            continue
        labels = sorted(guessable.get(bucket, set()))
        limit = meta_bucket["limit"]
        parts.append(
            f"{bucket}={'public' if meta_bucket['public'] else 'private'}"
            f"({len(object_paths.get(bucket, []))} objek"
            + (f", limit {limit}" if limit else "")
            + (f", {len(labels)} pola ditebak" if labels else ", 0 pola ditebak")
            + ")"
        )
        if meta_bucket["public"] and labels:
            warn_buckets.append(bucket)
            bits.append(
                f"{bucket} PUBLIC + path yang bisa disusun dari field bisnis "
                f"({', '.join(labels)}) -> dokumen dapat diambil TANPA autentikasi "
                "oleh pengguna yang hanya tahu nomor batch / kode bahan baku"
            )
        elif meta_bucket["public"]:
            bits.append(f"{bucket} PUBLIC tapi tidak ada pola template yang diuji "
                        "(path-nya tidak bisa disusun dari nomor batch / kode bahan baku)")
        else:
            bits.append(f"{bucket} private -> objeknya tidak bisa diambil tanpa autentikasi")

    fail_buckets = [b for b in ("product-attachments",) if meta.get(b) and meta[b]["public"]]
    head = ("audit ID baru grup ini: PROD-01 (privasi bucket), PROD-02 (tenant "
            "profiles.perusahaan), PROD-03 (DDL public_link_audits), PROD-04 (detail "
            "storage di audit trail), PROD-05 (distribusi outcome), PROD-06 (soft-delete).")
    known = "F-19: privat/publik bucket menentukan apakah CoA bisa diunduh siapa pun"
    if fail_buckets:
        check("G9.1 bucket-privasi-storage", "FAIL", "; ".join(parts),
              head + " BUCKET WAJIB PRIVAT public: " + ", ".join(fail_buckets)
              + " - app/product_attachments_routes.py menyajikan lampiran lewat signed URL, "
              "jadi bucket public membuat lampiran bisa diambil tanpa autentikasi. "
              + " | ".join(bits),
              known, cid="G9.1", targets=("PROD-01",), conclusion="confirmed")
        return
    if warn_buckets:
        check("G9.1 bucket-privasi-storage", "WARN", "; ".join(parts),
              head + " " + " | ".join(bits)
              + " Tidak ada request HTTP ke objek dan tidak ada objek yang dibaca; "
              "penilaian hanya dari metadata bucket + pola path.",
              known, cid="G9.1", targets=("PROD-01",), conclusion="confirmed")
        return
    check("G9.1 bucket-privasi-storage", "INFO", "; ".join(parts),
          head + " " + " | ".join(bits),
          known, cid="G9.1", targets=("PROD-01",), conclusion="neutral")


def g9_2_profiles_perusahaan(db):
    """G9.2 - kelengkapan profiles.perusahaan (guard tenant fail-open)."""
    total = count_where(db, "profiles")
    total = total if isinstance(total, int) else 0
    rows, truncated = fetch_rows(db, "profiles", ["role", "perusahaan"])
    empty_by_role: Counter = Counter()
    for row in rows:
        if not str(row.get("perusahaan") or "").strip():
            empty_by_role[str(row.get("role") or "?")] += 1
    empty = sum(empty_by_role.values())
    roles = ", ".join(f"{role} {n}" for role, n in sorted(empty_by_role.items()))
    trunc_note = " (data terpotong oleh batas pagination)" if truncated else ""

    if total == 0:
        info("G9.2 profiles-perusahaan-lengkap", "0/0 (tabel kosong)",
             "tidak ada profil untuk diukur; guard tenant tidak bisa diuji",
             cid="G9.2", targets=("PROD-02",), conclusion="unverifiable")
        return
    if empty == 0:
        check("G9.2 profiles-perusahaan-lengkap", "PASS", f"0/{total}" + trunc_note,
              "semua profil punya perusahaan -> assert_same_tenant() tidak bisa fail-open "
              "karena sisi pemanggil selalu terisi",
              cid="G9.2", targets=("PROD-02",), conclusion="refuted")
        return
    warn("G9.2 profiles-perusahaan-lengkap", f"{empty}/{total}" + trunc_note,
         f"guard tenant fail-open: check tenant tidak pernah menolak untuk profil tanpa "
         f"perusahaan (role: {roles}) - app/security.py:21-22 assert_same_tenant() "
         "return True bila perusahaan kosong; app/products_routes.py:863-864 dan "
         ":1093-1096 menolak hanya bila KEDUA sisi non-kosong -> akses lintas "
         "perusahaan lolos untuk profil ini",
         cid="G9.2", targets=("PROD-02",), conclusion="confirmed")


def g9_3_public_link_audits(db, cfg):
    """G9.3 - keberadaan public_link_audits + apakah DDL-nya ada di migration/."""
    exists, _err = relation_exists(db, "public_link_audits")
    cols, source, _col_err = table_columns(db, cfg, "public_link_audits")
    if not cols and exists:
        try:
            data = db.table("public_link_audits").select("*").limit(1).execute().data or []
        except Exception:  # noqa: BLE001
            data = []
        if data:
            cols = {str(k): "" for k in data[0].keys()}
            source = "baris pertama (PostgREST)"
    migrations = find_migration_files("public_link_audits")

    if not exists:
        info("G9.3 public_link_audits-dan-ddl", "TABEL TIDAK ADA",
             "tabel public_link_audits tidak ada di environment ini - app/dip_public.py:128-144 "
             "jatuh ke fallback activity_logs tanpa set source (tercatat source='app')",
             cid="G9.3", targets=("PROD-03",), conclusion="unverifiable")
        return

    count = count_where(db, "public_link_audits")
    count = count if isinstance(count, int) else 0
    col_names = ", ".join(sorted(cols)) if cols else "tidak diketahui"
    value = (f"ADA ({count} baris; kolom: {col_names}); DDL migration: "
             + (", ".join(migrations) if migrations else "TIDAK ADA"))
    if migrations:
        check("G9.3 public_link_audits-dan-ddl", "PASS", value,
              f"tabel audit publik ada dan DDL-nya ter-codify di migration/ "
              f"(sumber nama kolom: {source})",
              cid="G9.3", targets=("PROD-03",), conclusion="refuted")
        return
    warn("G9.3 public_link_audits-dan-ddl", value,
         "DDL tidak codified: fallback fail-open aktif di environment baru - "
         "app/dip_public.py:128-144 jatuh ke activity_logs tanpa set source, "
         "sehingga akses portal publik tercatat source='app' dan tabel audit "
         "khusus hilang saat environment baru dibangun dari migration/",
         cid="G9.3", targets=("PROD-03",), conclusion="confirmed")


def g9_4_storage_note_coverage(db, cfg):
    """G9.4 - cakupan detail storage (storage_note) di audit trail."""
    cols, source, _err = table_columns(db, cfg, "activity_logs")
    changes_type = (cols or {}).get("changes", "tidak diketahui")
    pf_total = count_where(db, "activity_logs", [
        lambda q: q.eq("entity_type", "product_file").eq("action", "delete")])
    pf_total = pf_total if isinstance(pf_total, int) else 0
    pa_total = count_where(db, "activity_logs", [
        lambda q: q.eq("entity_type", "product_attachment")])
    pa_total = pa_total if isinstance(pa_total, int) else 0
    rows, truncated = fetch_rows(db, "activity_logs", ["entity_type", "action", "changes"])
    pf_deletes = [r for r in rows
                  if r.get("entity_type") == "product_file" and r.get("action") == "delete"]
    pf_storage = [r for r in pf_deletes if "Storage" in json_text(r.get("changes"))]
    pf_label = [r for r in pf_deletes if "Storage (R2)" in json_text(r.get("changes"))]
    pa_rows = [r for r in rows if r.get("entity_type") == "product_attachment"]
    pa_storage = [r for r in pa_rows if "Storage" in json_text(r.get("changes"))]
    seen = len(pf_deletes)
    trunc_note = ""
    if truncated or seen != pf_total:
        trunc_note = f" (hanya {seen}/{pf_total} baris terbaca, data terpotong)"
    denom = pf_total if seen == pf_total else seen

    if pf_total == 0:
        info("G9.4 audit-trail-detail-storage", "0 baris product_file delete",
             "tidak ada baris entity_type='product_file' action='delete' di environment "
             "ini -> cakupan storage_note tidak bisa diukur (bukan kegagalan)",
             cid="G9.4", targets=("PROD-04",), conclusion="unverifiable")
        return
    if len(pf_storage) == denom:
        check("G9.4 audit-trail-detail-storage", "PASS",
              f"changes={changes_type}; product_file delete {len(pf_storage)}/{denom} "
              f"punya catatan Storage (label 'Storage (R2)' {len(pf_label)}); "
              f"product_attachment {len(pa_storage)}/{pa_total} punya catatan Storage"
              + trunc_note,
              f"setiap penghapusan file produk tercatat detail storage-nya -> jejak audit "
              f"menyimpan status R2/Supabase (tipe kolom dari {source})",
              cid="G9.4", targets=("PROD-04",), conclusion="refuted")
        return
    warn("G9.4 audit-trail-detail-storage",
         f"changes={changes_type}; product_file delete {len(pf_storage)}/{denom} "
         f"({pct(len(pf_storage), denom)}) punya catatan Storage (label persis "
         f"'Storage (R2)' {len(pf_label)}); product_attachment {len(pa_storage)}/{pa_total} "
         f"punya catatan Storage" + trunc_note,
         "detail storage TIDAK tercatat di semua baris delete -> status R2/Supabase "
         "hilang dari jejak audit untuk sebagian penghapusan file produk "
         f"(tipe kolom dari {source})",
         cid="G9.4", targets=("PROD-04",), conclusion="confirmed")


def g9_5_outcome_distribution(db):
    """G9.5 - distribusi outcome/source activity_logs."""
    total = count_where(db, "activity_logs")
    total = total if isinstance(total, int) else 0
    rows, truncated = fetch_rows(db, "activity_logs", ["entity_type", "outcome", "source"])
    outcomes: Counter = Counter(str(r.get("outcome") or "NULL") for r in rows)
    sources: Counter = Counter(str(r.get("source") or "NULL") for r in rows)
    rejected = outcomes.get("rejected", 0)
    failed = outcomes.get("failed", 0)
    product_rows = count_where(db, "activity_logs", [lambda q: q.eq("entity_type", "product")])
    product_rows = product_rows if isinstance(product_rows, int) else 0
    out_txt = ", ".join(f"{k} {v}" for k, v in sorted(outcomes.items())) or "tidak ada"
    src_txt = ", ".join(f"{k} {v}" for k, v in sorted(sources.items())) or "tidak ada"
    trunc_note = " (data terpotong oleh batas pagination)" if truncated else ""

    if total == 0:
        info("G9.5 activity_logs-distribusi-outcome", "0 baris (tabel kosong)",
             "tidak ada data audit untuk mengukur jalur penolakan",
             cid="G9.5", targets=("PROD-05",), conclusion="unverifiable")
        return
    if rejected + failed > 0:
        check("G9.5 activity_logs-distribusi-outcome", "PASS",
              f"outcome: {out_txt} | source: {src_txt}" + trunc_note,
              f"ada {rejected} baris outcome='rejected' dan {failed} baris "
              "outcome='failed' -> jalur penolakan terbukti hidup di environment ini "
              "(guard tidak fail-open total)",
              cid="G9.5", targets=("PROD-05",), conclusion="refuted")
        return
    warn("G9.5 activity_logs-distribusi-outcome",
         f"outcome: {out_txt} | source: {src_txt}" + trunc_note,
         f"TIDAK ada baris outcome='rejected'/'failed' padahal {product_rows} baris "
         "entity_type='product' -> jalur penolakan tidak punya bukti pernah "
         "dieksekusi di environment ini (guard fail-open atau modul belum pernah "
         "dipakai), bukan 'tidak pernah ada penolakan'",
         cid="G9.5", targets=("PROD-05",), conclusion="confirmed")


def g9_6_soft_delete_consistency(db):
    """G9.6 - konsistensi soft-delete produk vs jejak audit."""
    total = count_where(db, "products")
    total = total if isinstance(total, int) else 0
    deleted = count_where(db, "products", [lambda q: q.eq("is_deleted", True)])
    deleted = deleted if isinstance(deleted, int) else 0
    stamped = count_where(db, "products", [
        lambda q: q.eq("is_deleted", True).not_.is_("deleted_at", "null")])
    stamped = stamped if isinstance(stamped, int) else 0
    inconsistent = count_where(db, "products", [
        lambda q: q.eq("is_deleted", False).not_.is_("deleted_at", "null")])
    inconsistent = inconsistent if isinstance(inconsistent, int) else 0

    soft_rows, _trunc = fetch_filtered(db, "products", ["id", "deleted_at"],
                                        [lambda q: q.eq("is_deleted", True)])
    log_rows, _trunc2 = fetch_rows(db, "activity_logs", ["entity_type", "action", "entity_id"])
    delete_ids = {str(r.get("entity_id")) for r in log_rows
                  if r.get("entity_type") == "product" and r.get("action") == "delete"
                  and r.get("entity_id")}
    missing = [str(r.get("id")) for r in soft_rows if str(r.get("id")) not in delete_ids]
    ids_txt = ", ".join(str(r.get("id")) for r in soft_rows) or "tidak ada"

    if deleted == 0:
        info("G9.6 soft-delete-konsistensi-audit", f"0/{total}",
             "tidak ada produk soft-deleted di environment ini -> konsistensi "
             "deleted_at dan jejak audit delete tidak bisa diukur",
             cid="G9.6", targets=("PROD-06",), conclusion="unverifiable")
        return
    value = (f"is_deleted=true {deleted}/{total}; deleted_at terisi {stamped}/{deleted}; "
             f"tanpa audit delete {len(missing)}/{deleted}; "
             f"is_deleted=false tapi deleted_at terisi {inconsistent}")
    if missing or stamped != deleted or inconsistent:
        detail = ("TIDAK konsisten: ada produk soft-deleted tanpa deleted_at atau tanpa "
                  "baris audit action='delete' -> soft delete terjadi tanpa jejak audit "
                  "(mis. dibuang manual lewat SQL Editor, atau dilakukan saat route "
                  "POST /products/delete/{id} belum terdaftar - route itu hilang di "
                  "commit 5f82f94 dan dipulihkan 2026-10-21). Produk soft-deleted: " + ids_txt)
        if missing:
            detail += " (id tanpa audit delete: " + ", ".join(missing) + ")"
        verdict = "WARN"
    else:
        detail = ("konsisten: setiap produk soft-deleted punya deleted_at dan baris audit "
                  "entity_type='product' action='delete' untuk id yang sama. Produk "
                  "soft-deleted: " + ids_txt)
        verdict = "PASS"
    check("G9.6 soft-delete-konsistensi-audit", verdict, value, detail,
          cid="G9.6", targets=("PROD-06",), conclusion="neutral")

# --------------------------------------------------------------------------- #
# EXTRA - Status eksekusi migrasi 001-007 (item section 11 / "U10")
# --------------------------------------------------------------------------- #
def group_migration_status(db):
    print("\n-- EXTRA: Status eksekusi migrasi 001-007 terlihat dari skema (U10 / section 11) --")
    checks = [
        ("001", "tabel purchase_orders + purchase_order_items",
         lambda: relation_exists(db, "purchase_orders")[0]
         and relation_exists(db, "purchase_order_items")[0]),
        ("002", "kolom purchase_orders.jenis_po",
         lambda: probe_columns(db, "purchase_orders", ["jenis_po"])[0].get("jenis_po", False)),
        ("003", "kolom audit activity_logs (outcome/source/request_id/...)",
         lambda: all(probe_columns(db, "activity_logs", AUDIT_LOG_COLS)[0].values())),
        ("004", "tabel product_attachments + view product_attachment_counts",
         lambda: relation_exists(db, "product_attachments")[0]
         and relation_exists(db, "product_attachment_counts")[0]),
        ("005", "kolom legacy brands.hak_merk_file_url & lisensi_merk_file_url",
         lambda: all(probe_columns(
             db, "brands", ["hak_merk_file_url", "lisensi_merk_file_url"])[0].values())),
        ("006", "view product_formula_presence",
         lambda: relation_exists(db, "product_formula_presence")[0]),
        ("007", "kolom products.public_access_enabled/token/bpom_registered_link",
         lambda: all(probe_columns(db, "products", CAPABILITY_COLS)[0].values())),
    ]
    for mig, label, probe in checks:
        try:
            ok = bool(probe())
        except Exception as exc:  # noqa: BLE001
            ok = False
            label = f"{label} ({err_text(exc)[:80]})"
        check(f"E1 migrasi-{mig}", "PASS" if ok else "FAIL",
              "TERPASANG" if ok else "BELUM TERPASANG", label,
              "section 11: status eksekusi migrasi 001-007 tidak tersimpan di repo",
              cid="E1", targets=("U10",),
              conclusion="neutral" if ok else "confirmed")


# --------------------------------------------------------------------------- #
# Ringkasan
# --------------------------------------------------------------------------- #
def print_summary():
    counts = Counter(r["verdict"] for r in RESULTS)
    failed = counts.get("FAIL", 0)
    print("\n" + "=" * 78)
    print("RINGKASAN VERIFIKASI STATE DB STAGING (Batch B)")
    print("=" * 78)
    print(f"Total check   : {len(RESULTS)}")
    print(f"PASS          : {counts.get('PASS', 0)}")
    print(f"FAIL          : {counts.get('FAIL', 0)}")
    print(f"WARN          : {counts.get('WARN', 0)}")
    print(f"INFO          : {counts.get('INFO', 0)}")

    print("\n## RINGKASAN TEMUAN AUDIT YANG TERKONFIRMASI")
    buckets = {"confirmed": [], "refuted": [], "unverifiable": [], "neutral": []}
    for audit_id in sorted(AUDIT):
        slot = AUDIT[audit_id]
        seen = list(dict.fromkeys(slot["checks"]))
        buckets.setdefault(slot["verdict"] or "neutral", []).append(
            f"{audit_id} (bukti: {', '.join(seen)})"
        )
    for key, title in [
        ("confirmed", "CONFIRMED (bukti DB mendukung temuan audit)"),
        ("refuted", "REFUTED (bukti DB / mitigasi - temuan audit tidak terjadi di staging)"),
        ("unverifiable", "UNVERIFIABLE (tidak bisa dijawab dari DB staging)"),
        ("neutral", "NEUTRAL (terukur, tidak ada klaim audit yang diuji)"),
    ]:
        print(f"\n{title}:")
        items = buckets.get(key) or []
        if not items:
            print("  - (tidak ada)")
        for item in items:
            print(f"  - {item}")

    print("\nExit code: " + ("1 (ada FAIL)" if failed else "0 (tidak ada FAIL)"))
    return EXIT_CHECK_FAILED if failed else EXIT_OK


# --------------------------------------------------------------------------- #
def main() -> int:
    print("=" * 78)
    print("VERIFIKASI STATE DATABASE STAGING - Bukti Batch B audit 2026-10-21")
    print("=" * 78)
    print("Mode: READ-ONLY (SELECT saja; tidak ada insert/update/delete/upsert)")
    print("Target: staging SAJA - guard dipin repo (app/staging_preflight)")

    cfg = load_and_guard()
    print(f"Target host: {target_label(cfg)} (host staging eksak, diverifikasi guard)")

    db = db_client(cfg)
    try:
        db.table("products").select("id", count="exact").limit(1).execute()
    except Exception as exc:  # noqa: BLE001
        abort(f"[ABORT] database tidak terjangkau: {err_text(exc)[:200]}")

    group1(db)
    group2(db)
    group3(db)
    group4(db)
    group5(db)
    group6(db)
    group7(db)
    group8(db)
    group9(db, cfg)
    group_migration_status(db)

    return print_summary()


if __name__ == "__main__":
    sys.exit(main())
