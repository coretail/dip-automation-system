"""E2E smoke staging: pasca-refactor route ke modul terpisah (d9ab191 + 4b13cc4).

HANYA untuk staging lokal. Menolak jalan bila base URL bukan localhost atau
.env.staging gagal preflight (`app.staging_preflight.validate_staging_file`).
TIDAK menyentuh prod. Tidak mencetak secret.

Latar belakang: refactor memindahkan 31 route dari main.py ke 7 modul. Bug khas
yang lolos dari "app tetap boot" adalah NameError saat route dijalankan
(mis. dashboard `/` tanpa cookie greeting_cache, halaman /sample-submissions*,
/api/ed-notifications). Tes ini menyentuh route-route itu lewat browser nyata.

Isi:
  A. Halaman GET (tidak boleh 5xx, tidak ada teks "Internal Server Error"):
     /, /sample-submissions, /sample-submissions/form, /brands, /admin/users,
     /admin/trash, /admin/company-documents, /notes, dan halaman produk
     (inci report, qual-quan, finished-spec, edit) untuk produk pertama; plus
     endpoint file/redirect (finished-spec/preview, qual-quan export-xlsx).
  B. Dashboard `/` dua jalur: TANPA cookie greeting_cache (jalur yang dulu
     NameError) dan DENGAN cookie valid.
  C. API: GET /api/ed-notifications & /api/admin/users/presence (JSON),
     POST /api/presence/heartbeat.
  D. Alur tulis sample (UI): buat -> edit -> hapus. Setelah edit & hapus, cek
     `activity_logs` (update/delete sample_submission, request_id terisi).
     Memakai brand yang SUDAH ada (tidak membuat brand/producer baru).
  E. Upload dokumen merk (UI, PT Erfi) pada brand yang belum punya dokumen;
     baris `brand_legal_documents` dibuat lalu dibersihkan.
  F. Sapu 5xx: respons >= 500 mana pun selama sesi (termasuk XHR) = FAIL.

Efek samping di STAGING (bukan prod): sample uji dihapus lewat UI; baris
brand_legal_documents uji dihapus lewat service role; objek PDF uji pada key
deterministik `brands/hak_lisensi_merk_<brand>_erfi.pdf` bisa tertinggal di
bucket staging (aman ditimpa di run berikutnya).

Prasyarat (sekali):
    pip install playwright supabase python-dotenv httpx
    playwright install chromium

Jalankan (staging harus hidup, mis. scripts/run_staging_8017.py):
    set STAGING_ADMIN_EMAIL=...        (PowerShell: $env:STAGING_ADMIN_EMAIL="...")
    set STAGING_ADMIN_PASSWORD=...
    py tests/e2e_smoke_refactor.py [--headed] [--base-url http://127.0.0.1:8017]

Exit code 0 = semua PASS, 1 = ada FAIL.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.staging"

RESULTS: list[tuple[str, bool, str]] = []
SERVER_ERRORS: list[tuple[int, str]] = []

STATIC_PAGES = [
    "/",
    "/sample-submissions",
    "/sample-submissions/form",
    "/brands",
    "/admin/users",
    "/admin/trash",
    "/admin/company-documents",
    "/notes",
]
PRODUCT_PAGES = [
    "/products/{id}/inci-breakdown/report",
    "/products/{id}/qualitative-quantitative",
    "/products/{id}/finished-spec",
    "/products/{id}/edit",
]
# Respons berupa file/PDF atau redirect: dicek lewat request (bukan page.goto,
# karena Chromium headless memperlakukan PDF inline sebagai download).
PRODUCT_FILE_ENDPOINTS = [
    "/products/{id}/finished-spec/preview",
    "/products/{id}/qualitative-quantitative/export-xlsx",
]
ERROR_MARKERS = ("Internal Server Error", "Traceback (most recent call last)", "NameError")


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return bool(ok)


def skip(name: str, why: str) -> None:
    RESULTS.append((name, True, f"SKIP: {why}"))
    print(f"[SKIP] {name} - {why}")


def is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def make_pdf(marker: str) -> bytes:
    """PDF 1 halaman minimal dengan teks marker (valid, ~400 byte)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({marker}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


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
        validate_staging_file(cfg, caller="e2e-smoke-refactor")
    except RuntimeError as exc:
        sys.exit(f"[ABORT] guard staging gagal: {exc}")
    return cfg


def db_client(cfg: dict):
    from supabase import create_client

    return create_client(cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_ROLE_KEY"])


# --------------------------------------------------------------------------- #
# Langkah-langkah UI
# --------------------------------------------------------------------------- #
def visit(page, path: str, label: str | None = None) -> bool:
    """GET halaman lewat browser. FAIL bila status >= 400 atau ada penanda error."""
    label = label or f"GET {path}"
    try:
        resp = page.goto(path)
    except Exception as exc:  # noqa: BLE001
        return record(label, False, f"{type(exc).__name__}: {exc}")
    status = resp.status if resp else 0
    body = page.content()
    marker = next((m for m in ERROR_MARKERS if m in body[:20000]), None)
    ok = bool(resp) and status < 400 and "/login" not in page.url and not marker
    detail = f"HTTP {status}" + (f", ada '{marker}'" if marker else "")
    if "/login" in page.url:
        detail += ", ter-redirect ke /login (sesi hilang?)"
    return record(label, ok, detail if not ok else "")


def api_check(ctx, base_url: str) -> None:
    """C. Endpoint JSON (memakai cookie sesi browser)."""
    for path in ("/api/ed-notifications", "/api/admin/users/presence"):
        r = ctx.request.get(base_url + path)
        ok_json = False
        if r.status == 200:
            try:
                r.json()
                ok_json = True
            except Exception:  # noqa: BLE001
                pass
        record(f"API GET {path}", r.status == 200 and ok_json, f"HTTP {r.status}")
    r = ctx.request.post(base_url + "/api/presence/heartbeat",
                         data=json.dumps({"online": True, "active": True}),
                         headers={"Content-Type": "application/json"})
    body_ok = False
    if r.status == 200:
        try:
            body_ok = r.json().get("ok") is True
        except Exception:  # noqa: BLE001
            pass
    record("API POST /api/presence/heartbeat", r.status == 200 and body_ok, f"HTTP {r.status}")


def fetch_ok(ctx, base_url: str, path: str) -> bool:
    """GET via request (ikut redirect). OK bila status akhir < 400."""
    r = ctx.request.get(base_url + path)
    return record(f"GET {path} (file/redirect)", r.status < 400, f"HTTP {r.status}")


def dashboard_cookie_paths(ctx, page, base_url: str) -> None:
    """B. `/` tanpa cookie greeting_cache (jalur get_time_greeting) & dengan cookie."""
    ctx.clear_cookies(name="greeting_cache")
    visit(page, "/", "dashboard `/` TANPA cookie greeting_cache")
    greeting = {"text": "Selamat Pagi", "icon": "fa-solid fa-sun",
                "color": "text-amber-400", "phrase": "e2e"}
    ctx.add_cookies([{"name": "greeting_cache", "value": json.dumps(greeting),
                      "url": base_url}])
    visit(page, "/", "dashboard `/` DENGAN cookie greeting_cache valid")
    # Cookie rusak -> juga jatuh ke fallback get_time_greeting()
    ctx.add_cookies([{"name": "greeting_cache", "value": "bukan-json", "url": base_url}])
    visit(page, "/", "dashboard `/` dengan cookie greeting_cache RUSAK")


def first_product_id(page) -> str | None:
    page.goto("/")
    hrefs = page.eval_on_selector_all(
        "a[href^='/products/']", "els => els.map(e => e.getAttribute('href'))")
    for h in hrefs or []:
        m = re.match(r"^/products/([0-9a-fA-F-]{8,})/", h or "")
        if m:
            return m.group(1)
    return None


def sample_flow(page, db, marker: str) -> None:
    """D. Buat -> edit -> hapus sample lewat UI, lalu verifikasi activity_logs."""
    from playwright.sync_api import TimeoutError as PWTimeout

    page.goto("/sample-submissions/form")
    brand_values = page.eval_on_selector_all(
        "#brand_id option", "els => els.map(e => e.value)")
    brand_id = next((v for v in brand_values if v and v != "new"), None)
    if not brand_id:
        skip("alur sample (buat/edit/hapus)", "tidak ada brand di staging")
        return

    page.select_option("#brand_id", brand_id)
    page.fill("#product_name", marker)
    page.fill("input[name=qc_signer]", "E2E QC")
    page.fill("input[name=rd_signer]", "E2E RD")
    # create me-redirect ke /sample-submissions/preview/{id} (BUKAN ke daftar).
    preview_re = re.compile(r"/sample-submissions/preview/([^/?#]+)")
    try:
        with page.expect_navigation(url=lambda u: bool(preview_re.search(u)), timeout=20000):
            page.click("form[action='/sample-submissions/create'] button[type=submit]")
    except PWTimeout:
        record("UI: buat sample -> redirect ke preview", False, f"masih di {page.url}")
        return
    submission_id = preview_re.search(page.url).group(1)
    body = page.content()
    record("UI: buat sample -> redirect ke preview tanpa error",
           not any(m in body[:20000] for m in ERROR_MARKERS), f"id={submission_id}")

    # Tepat 1 baris DB (bukan duplikat insert) dan tepat 1 baris di daftar.
    n_db = len(db.table("sample_submissions").select("id")
               .eq("product_name", marker).execute().data or [])
    record("DB: sample terbuat tepat 1 baris", n_db == 1, f"count={n_db}")
    page.goto("/sample-submissions")
    row = page.locator("table tbody tr", has_text=marker)
    if not record("UI: sample baru muncul 1x di daftar", row.count() == 1, f"count={row.count()}"):
        return

    # --- edit (jalur yang memakai _build_diff_changes / FSP_FIELD_LABELS) ---
    # edit juga me-redirect ke preview/{id}.
    page.goto(f"/sample-submissions/edit/{submission_id}")
    page.fill("input[name=hero_ingredient]", "Niacinamide 5% (e2e)")
    try:
        with page.expect_navigation(url=lambda u: bool(preview_re.search(u)), timeout=20000):
            page.click(f"form[action='/sample-submissions/edit/{submission_id}'] button[type=submit]")
    except PWTimeout:
        record("UI: simpan edit sample -> redirect ke preview", False, f"masih di {page.url}")
        return
    body = page.content()
    record("UI: simpan edit sample tanpa error",
           not any(m in body[:20000] for m in ERROR_MARKERS), page.url)
    saved = (db.table("sample_submissions").select("hero_ingredient")
             .eq("id", submission_id).execute().data or [{}])[0]
    record("DB: hero_ingredient tersimpan", saved.get("hero_ingredient") == "Niacinamide 5% (e2e)",
           str(saved.get("hero_ingredient")))

    # --- preview ---
    visit(page, f"/sample-submissions/preview/{submission_id}",
          "GET /sample-submissions/preview/{id}")

    # --- hapus ---
    page.goto("/sample-submissions")
    del_form = page.locator(f"form[action='/sample-submissions/delete/{submission_id}'] button")
    try:
        with page.expect_navigation(url=lambda u: "/sample-submissions" in u, timeout=20000):
            del_form.click()
    except PWTimeout:
        record("UI: hapus sample", False, f"masih di {page.url}")
        return
    gone = not (db.table("sample_submissions").select("id")
                .eq("id", submission_id).execute().data)
    record("DB: sample terhapus", gone)

    logs = (db.table("activity_logs")
            .select("action, request_id, route, http_method, outcome")
            .eq("entity_type", "sample_submission").eq("entity_id", submission_id)
            .order("created_at").execute().data or [])
    actions = [l["action"] for l in logs]
    record("activity_logs: create/update/delete sample tercatat",
           actions[:1] == ["create"] and "update" in actions and actions[-1] == "delete",
           str(actions))
    record("activity_logs: request_id UUID & berbeda per request",
           all(is_uuid(l.get("request_id")) for l in logs)
           and len({l["request_id"] for l in logs}) == len(logs),
           str([l.get("request_id") for l in logs]))
    record("activity_logs: route/http_method terisi",
           all(l.get("route") and l.get("http_method") == "POST" for l in logs),
           str([(l.get("http_method"), l.get("route")) for l in logs]))


def brand_doc_flow(page, db, pdf_path: Path) -> None:
    """E. Upload dokumen merk PT Erfi pada brand yang belum punya dokumen."""
    from playwright.sync_api import TimeoutError as PWTimeout

    page.goto("/brands")
    rows = page.eval_on_selector_all(
        "tr[data-brand-id]",
        "els => els.map(e => ({id: e.dataset.brandId, docs: e.dataset.legalDocs,"
        " name: e.querySelector('td')?.innerText || ''}))")
    target = None
    for r in rows:
        try:
            docs = json.loads(r["docs"] or "{}")
        except ValueError:
            continue
        if not (docs.get("PT Erfi") or {}).get("hak_lisensi_merk_file_url"):
            target = r
            break
    if not target:
        skip("upload dokumen merk (PT Erfi)",
             "semua brand sudah punya dokumen; tidak menimpa data staging")
        return

    brand_id = target["id"]
    created = False
    try:
        page.evaluate("([id, name]) => openEditModal(id, name)", [brand_id, target["name"]])
        page.set_input_files("#edit-brand-form-erfi input[type=file]", str(pdf_path))
        try:
            with page.expect_navigation(url=lambda u: "/brands" in u, timeout=30000):
                page.click("#edit-brand-form-erfi button[type=submit]")
        except PWTimeout:
            record("UI: upload dokumen merk", False, f"masih di {page.url}")
            return
        row = (db.table("brand_legal_documents").select("hak_lisensi_merk_file_url")
               .eq("brand_id", brand_id).eq("perusahaan", "PT Erfi").execute().data or [])
        created = bool(row)
        record("DB: baris brand_legal_documents terbuat dengan URL",
               created and bool(row[0].get("hak_lisensi_merk_file_url")),
               f"brand_id={brand_id}")
    finally:
        if created:
            try:
                (db.table("brand_legal_documents").delete()
                 .eq("brand_id", brand_id).eq("perusahaan", "PT Erfi").execute())
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] cleanup brand_legal_documents gagal: {type(exc).__name__}: {exc}")


def run_ui(base_url: str, email: str, password: str, db, marker: str,
           pdf_path: Path, headed: bool) -> None:
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        ctx = browser.new_context(base_url=base_url)
        page = ctx.new_page()
        page.set_default_timeout(20000)
        page.on("dialog", lambda d: d.accept())
        page.on("response", lambda r: SERVER_ERRORS.append((r.status, r.url))
                if r.status >= 500 else None)
        try:
            page.goto("/login")
            page.fill("input[name=email]", email)
            page.fill("input[name=password]", password)
            page.click("#login-submit-btn")
            try:
                page.wait_for_url(lambda u: "/login" not in u, timeout=30000)
                record("login admin staging", True)
            except PWTimeout:
                record("login admin staging", False, f"masih di {page.url}")
                return

            dashboard_cookie_paths(ctx, page, base_url)          # B
            for path in STATIC_PAGES:                            # A
                visit(page, path)
            pid = first_product_id(page)
            if pid:
                for tpl in PRODUCT_PAGES:
                    visit(page, tpl.format(id=pid))
                for tpl in PRODUCT_FILE_ENDPOINTS:
                    fetch_ok(ctx, base_url, tpl.format(id=pid))
            else:
                skip("halaman produk", "tidak ada produk di dashboard staging")
            api_check(ctx, base_url)                              # C
            sample_flow(page, db, marker)                         # D
            brand_doc_flow(page, db, pdf_path)                    # E
        finally:
            browser.close()


def cleanup_sample(db, marker: str) -> None:
    """Sisa sample uji bila tes berhenti sebelum langkah hapus (staging saja)."""
    try:
        db.table("sample_submissions").delete().eq("product_name", marker).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] cleanup sample gagal: {type(exc).__name__}: {exc}")


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

    marker = f"E2E-SMOKE-{int(time.time())}"
    pdf_path = ROOT / "_e2e_smoke_tmp.pdf"
    pdf_path.write_bytes(make_pdf(marker))
    try:
        run_ui(args.base_url, email, password, db, marker, pdf_path, args.headed)
    finally:
        pdf_path.unlink(missing_ok=True)
        cleanup_sample(db, marker)

    record("F. tidak ada respons 5xx selama sesi", not SERVER_ERRORS,
           "; ".join(f"{s} {u}" for s, u in SERVER_ERRORS[:5]))

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
