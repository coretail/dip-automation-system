"""E2E staging: upload PDF lewat UI -> pastikan sampai di R2 (bucket -stg).

HANYA untuk staging lokal. Menolak jalan bila base URL bukan localhost atau
.env.staging bukan DIP_APP_ENV=staging / R2_BUCKET_SUFFIX=-stg / STORAGE_BACKEND
dual|r2. TIDAK menyentuh prod. Tidak mencetak secret.
Kredensial (STAGING_BASE_URL, STAGING_ADMIN_EMAIL, STAGING_ADMIN_PASSWORD) ada di LOGIN.md di root repo (git-ignored): export jadi env var di shell yang menjalankan skrip ini, jangan di-hardcode di skrip.

Alur (halaman /admin/company-documents, butuh akun role admin staging):
  1. login lewat form /login
  2. klik "Upload/Ganti" baris NIB PT Erfi, pilih PDF uji bermarker unik, Simpan
  3. cek flash "berhasil diperbarui" di halaman
  4. baca balik objek dari R2 (legal-documents-stg) dan bandingkan byte-nya
  5. (opsional, --log) cek log staging: ada `storage_r2_ok ... path=<key>`
     dan TIDAK ada `storage_repair` baru sejak sebelum upload

Catatan: upload menimpa dokumen NIB PT Erfi di project Supabase STAGING
(bukan prod) dan objek `company-docs/nib_erfi.pdf` di bucket -stg. Key-nya
deterministik, jadi aman dijalankan berulang.

Prasyarat (sekali):
    pip install playwright boto3 python-dotenv
    playwright install chromium

Jalankan (staging harus hidup, mis. scripts/run_staging_8017.py dengan output
diarahkan ke file log):
    set STAGING_ADMIN_EMAIL=...        (PowerShell: $env:STAGING_ADMIN_EMAIL="...")
    set STAGING_ADMIN_PASSWORD=...
    py tests/e2e_upload_staging.py --log staging.log [--headed]

Exit code 0 = semua PASS, 1 = ada FAIL.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.staging"

DOC_TYPE = "nib"
COMPANY = "PT Erfi"
BUCKET_LOGICAL = "legal-documents"
KEY = "company-docs/nib_erfi.pdf"  # COMPANY_DOC_MAP["nib"] + slug "erfi"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return bool(ok)


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


def load_staging_env() -> dict:
    from dotenv import dotenv_values

    if not ENV_FILE.exists():
        sys.exit(f"[ABORT] {ENV_FILE.name} tidak ditemukan.")
    return {k: (v or "").strip() for k, v in dotenv_values(str(ENV_FILE)).items()}


def guard(cfg: dict, base_url: str) -> None:
    problems = []
    host = urlparse(base_url).hostname or ""
    if host not in ("127.0.0.1", "localhost"):
        problems.append(f"base URL '{base_url}' bukan localhost (staging lokal saja)")
    if cfg.get("DIP_APP_ENV", "").lower() != "staging":
        problems.append("DIP_APP_ENV != staging")
    if cfg.get("R2_BUCKET_SUFFIX", "") != "-stg":
        problems.append("R2_BUCKET_SUFFIX != -stg")
    if cfg.get("STORAGE_BACKEND", "").lower() not in ("dual", "r2"):
        problems.append("STORAGE_BACKEND bukan dual/r2")
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        if not cfg.get(k):
            problems.append(f"{k} kosong di .env.staging")
    if problems:
        sys.exit("[ABORT] guard gagal: " + "; ".join(problems))


def r2_client(cfg: dict):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=f"https://{cfg['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=cfg["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=cfg["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def run_ui(base_url: str, email: str, password: str, pdf_path: Path, headed: bool) -> None:
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        page = browser.new_context(base_url=base_url).new_page()
        page.set_default_timeout(20000)
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

            page.goto("/admin/company-documents")
            if "/admin/company-documents" not in page.url:
                record("akses halaman admin dokumen perusahaan", False,
                       f"redirect ke {page.url} (akun bukan admin?)")
                return
            btn = page.locator(
                f"button[onclick^='openUploadModal(\"{DOC_TYPE}\", \"{COMPANY}\"']"
            )
            record("tombol upload NIB PT Erfi ada", btn.count() == 1, f"count={btn.count()}")
            if btn.count() != 1:
                return
            btn.click()
            page.set_input_files("#modal-file-input", str(pdf_path))
            page.click("#modal-submit-btn")
            page.wait_for_url("**/admin/company-documents")
            flash = page.get_by_text("berhasil diperbarui")
            try:
                flash.first.wait_for(state="visible", timeout=15000)
                record("flash 'berhasil diperbarui' tampil", True)
            except PWTimeout:
                err = page.get_by_text("Gagal upload")
                record("flash 'berhasil diperbarui' tampil", False,
                       "muncul 'Gagal upload'" if err.count() else "flash tidak muncul")
        finally:
            browser.close()


def check_r2(cfg: dict, expected: bytes) -> None:
    from botocore.exceptions import ClientError

    bucket = f"{BUCKET_LOGICAL}{cfg['R2_BUCKET_SUFFIX']}"
    try:
        body = r2_client(cfg).get_object(Bucket=bucket, Key=KEY)["Body"].read()
    except ClientError as exc:
        record(f"objek ada di R2 {bucket}/{KEY}", False, str(exc.response.get("Error", {})))
        return
    record(f"objek ada di R2 {bucket}/{KEY}", True, f"{len(body)} byte")
    record("isi objek R2 identik dengan file yang diupload", body == expected)


def check_log(log_path: Path, start_offset: int) -> None:
    deadline = time.time() + 10
    text = ""
    while time.time() < deadline:
        with open(log_path, "rb") as f:
            f.seek(start_offset)
            text = f.read().decode("utf-8", errors="replace")
        if "storage_r2_ok" in text:
            break
        time.sleep(1)
    ok_lines = [l for l in text.splitlines() if "storage_r2_ok" in l and KEY in l]
    record("log staging: storage_r2_ok untuk key ini", len(ok_lines) >= 1,
           ok_lines[0].strip() if ok_lines else "baris tidak ditemukan")
    repair = [l for l in text.splitlines() if "storage_repair" in l]
    record("log staging: tidak ada storage_repair baru", not repair,
           repair[0].strip() if repair else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.getenv("STAGING_BASE_URL", "http://127.0.0.1:8017"))
    ap.add_argument("--log", help="path file log output staging (opsional tapi disarankan)")
    ap.add_argument("--headed", action="store_true", help="tampilkan browser")
    args = ap.parse_args()

    email = os.getenv("STAGING_ADMIN_EMAIL", "")
    password = os.getenv("STAGING_ADMIN_PASSWORD", "")
    if not (email and password):
        sys.exit("[ABORT] set STAGING_ADMIN_EMAIL dan STAGING_ADMIN_PASSWORD (akun admin STAGING).")

    cfg = load_staging_env()
    guard(cfg, args.base_url)

    import httpx

    try:
        r = httpx.get(args.base_url.rstrip("/") + "/health", timeout=5)
        record("staging hidup (/health)", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        record("staging hidup (/health)", False, f"{type(exc).__name__}: {exc}")
        return 1

    marker = f"E2E-R2-{int(time.time())}"
    pdf = make_pdf(marker)
    pdf_path = ROOT / "_e2e_upload_tmp.pdf"
    pdf_path.write_bytes(pdf)

    log_path = Path(args.log) if args.log else None
    start_offset = log_path.stat().st_size if log_path and log_path.exists() else 0
    if log_path and not log_path.exists():
        print(f"[WARN] file log {log_path} belum ada; cek log dilewati.")
        log_path = None

    try:
        run_ui(args.base_url, email, password, pdf_path, args.headed)
        check_r2(cfg, pdf)
        if log_path:
            check_log(log_path, start_offset)
        else:
            print("[SKIP] cek log (tanpa --log)")
    finally:
        pdf_path.unlink(missing_ok=True)

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
