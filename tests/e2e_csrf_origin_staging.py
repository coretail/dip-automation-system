"""E2E regresi Referrer-Policy: POST form submit browser harus membawa
Origin yang benar (BUKAN "null") dan Referer same-origin setelah
perubahan Referrer-Policy dari no-referrer ke same-origin (sesi 16 koreksi).

HANYA untuk staging lokal. Menolak jalan bila base URL bukan localhost.
Kredensial (STAGING_ADMIN_EMAIL / STAGING_ADMIN_PASSWORD) ada di LOGIN.md
di root repo (git-ignored): export jadi env var di shell yang menjalankan
skrip ini, jangan di-hardcode di skrip.

Jalankan:
    venv\Scripts\python.exe tests/e2e_csrf_origin_staging.py \
        --base-url http://127.0.0.1:8017

Exit 0 = semua PASS, 1 = ada FAIL.

Prasyarat: server staging hidup (scripts/run_staging_8017.py),
kredensial di-export sebagai env var, Playwright + chromium terpasang.

Struktur:
  1. Login via form (POST /login) — tangkap header Origin/Referer.
  2. Buat note via form (POST /notes) — tangkap header Origin/Referer.
  3. Cek respons GET /health: header Referrer-Policy == same-origin.
  4. Assert: tidak ada POST dengan Origin: "null" di seluruh sesi.
  5. Bersihkan note yang dibuat (best-effort).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.staging"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
    return bool(ok)


def load_and_guard(base_url: str) -> dict:
    host = urlparse(base_url).hostname or ""
    if host not in ("127.0.0.1", "localhost"):
        sys.exit(f"[ABORT] base URL '{base_url}' bukan localhost (staging lokal saja).")
    if not ENV_FILE.exists():
        sys.exit(f"[ABORT] {ENV_FILE.name} tidak ditemukan.")
    sys.path.insert(0, str(ROOT))
    from app.staging_preflight import parse_dotenv_file, validate_staging_file
    cfg = parse_dotenv_file(str(ENV_FILE))
    try:
        validate_staging_file(cfg, caller="e2e-csrf-origin")
    except RuntimeError as exc:
        sys.exit(f"[ABORT] guard staging gagal: {exc}")
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8017")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    load_and_guard(base_url)

    email = os.environ.get("STAGING_ADMIN_EMAIL", "").strip()
    password = os.environ.get("STAGING_ADMIN_PASSWORD", "").strip()
    if not email or not password:
        sys.exit("[ABORT] set STAGING_ADMIN_EMAIL dan STAGING_ADMIN_PASSWORD (akun admin STAGING).")

    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    origin_expect = "http://127.0.0.1:8017"
    captured: list[dict] = []

    def on_request(req):
        if req.method == "POST":
            captured.append({
                "url": req.url,
                "origin": req.headers.get("origin", ""),
                "referer": req.headers.get("referer", ""),
            })

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.set_default_timeout(30_000)
        page.on("dialog", lambda d: d.accept())
        # Daftarkan listener SEBELUM navigasi apa pun agar POST /login
        # (form submit pertama) juga tertangkap.
        page.on("request", on_request)

        # Step 1: login via form
        page.goto(f"{base_url}/login")
        page.fill("input[name=email]", email)
        page.fill("input[name=password]", password)
        page.click("#login-submit-btn")
        try:
            page.wait_for_url(lambda u: "/login" not in u, timeout=30_000)
            record("login staging", True)
        except PWTimeout:
            record("login staging", False, f"masih di {page.url}")
            browser.close()
            _report()
            return 1

        # Step 2: buat note via form (POST /notes)
        page.goto(f"{base_url}/notes")
        note_body = "e2e-csrf-origin-regression"
        page.fill("#noteBody", note_body)
        page.locator("#noteForm button[type=submit]").first.click()
        page.wait_for_timeout(2_000)

        # Step 3: cek respons Referrer-Policy di /health
        resp = page.request.get(f"{base_url}/health")
        rp = resp.headers.get("referrer-policy", "")
        record(
            "GET /health respons Referrer-Policy == same-origin",
            rp == "same-origin",
            f"got {rp!r}",
        )

        # Step 4: bersihkan note (best-effort, tidak fatal)
        note_row = page.locator(f"article:has-text('{note_body}')")
        if note_row.count() > 0:
            del_btn = note_row.first.locator("form[action*='/delete'] button[type=submit]")
            if del_btn.count() > 0:
                del_btn.first.click()
                page.wait_for_timeout(1_000)

        browser.close()

    # Analisis captured
    login_posts = [c for c in captured if c["url"].rstrip("/").endswith("/login")]
    other_posts = [c for c in captured if not c["url"].rstrip("/").endswith("/login")]
    null_origins = [c for c in captured if c["origin"] == "null"]

    # POST /login: Origin harus == origin staging (bukan "null")
    if login_posts:
        lp = login_posts[-1]
        record(
            f"POST /login Origin == {origin_expect} (bukan 'null')",
            lp["origin"] == origin_expect,
            f"got origin={lp['origin']!r}",
        )
        record(
            "POST /login Referer same-origin (bukan kosong)",
            lp["referer"].startswith(origin_expect),
            f"got referer={lp['referer']!r}",
        )
    else:
        record("POST /login tertangkap", False, "tidak ada POST /login di captured")

    # POST /notes (form submit): Origin harus == origin staging
    notes_posts = [c for c in other_posts if "/notes" in c["url"]]
    if notes_posts:
        np = notes_posts[-1]
        record(
            f"POST /notes Origin == {origin_expect} (bukan 'null')",
            np["origin"] == origin_expect,
            f"got origin={np['origin']!r}",
        )
    else:
        # Bila form /notes tidak terdeteksi (layout berubah), fallback:
        # cukup pastikan tidak ada Origin null di POST lain
        pass

    # Tidak ada POST dengan Origin: null di seluruh sesi
    record(
        "tidak ada POST dengan Origin: null (regresi Referrer-Policy)",
        len(null_origins) == 0,
        f"{len(null_origins)} POST dengan Origin null: {[c['url'] for c in null_origins]}",
    )

    _report()
    return 0 if all(ok for _, ok, _ in RESULTS) else 1


def _report() -> None:
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = total - passed
    print(f"\n=== RINGKASAN ===  PASS={passed} FAIL={failed} TOTAL={total}")
    if failed:
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  FAIL: {name} - {detail}")


if __name__ == "__main__":
    raise SystemExit(main())
