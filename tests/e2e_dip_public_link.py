"""Live Playwright smoke test for one public DIP/BPOM URL.

The test is read-only. It does not log in, submit forms, change database rows,
or upload/delete storage objects. The supplied URL may be a hub URL with an
``access`` query parameter, for example::

    py tests/e2e_dip_public_link.py --url "https://staging.example.com/dip/product-<uuid>?access=<token>"

Setup (PowerShell)::

    venv\Scripts\python.exe -m pip install playwright
    venv\Scripts\python.exe -m playwright install chromium
    venv\Scripts\python.exe tests\e2e_dip_public_link.py --help
    venv\Scripts\python.exe tests\e2e_dip_public_link.py --url "<live DIP URL>"

Options::

    --headed       Show Chromium instead of running headless.
    --timeout MS   Per-operation timeout, default 30000.
    --allow-http   Permit an http:// URL (HTTPS is required by default).
    --json PATH    Write a machine-readable report without exposing tokens.

Exit codes: 0 means every assertion passed; 1 means an assertion failed;
2 means invalid usage or an environment/browser setup failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ERROR_MARKERS = ("Internal Server Error", "Traceback (most recent call last)", "NameError")
CHAPTERS = (
    ("Bab I preview", "/bab1"),
    ("Bab I download", "/bab1/download"),
    ("Bab II ZIP", "/bab2/zip"),
    ("Bab III preview", "/bab3"),
    ("Bab III download", "/bab3/download"),
    ("Bab IV preview", "/bab4"),
    ("Bab IV download", "/bab4/download"),
)


def check(results: list[dict], name: str, ok: bool, detail: str = "") -> None:
    results.append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def safe_url(url: str) -> str:
    """Return URL suitable for output, retaining only whether access exists."""
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    redacted = {key: ["<redacted>"] for key in query if key == "access"}
    redacted.update({key: value for key, value in query.items() if key != "access"})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(redacted, doseq=True), ""))


def with_access(url: str, access: str | None) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    if access:
        query["access"] = [access]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), ""))


def assert_response(results, name, response, *, accepted=(200,), allow_pdf=False):
    status = response.status
    content_type = (response.headers.get("content-type") or "").lower()
    content_length = response.headers.get("content-length")
    ok = status in accepted
    if allow_pdf:
        ok = ok and ("pdf" in content_type or "zip" in content_type or "octet-stream" in content_type)
    detail = f"HTTP {status}, content-type={content_type or '-'}"
    if content_length:
        detail += f", length={content_length}"
    check(results, name, ok, detail)
    return ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only live E2E check for a public DIP URL.")
    parser.add_argument("--url", required=True, help="Full public DIP hub URL, including access token when required.")
    parser.add_argument("--headed", action="store_true", help="Run Chromium visibly.")
    parser.add_argument("--timeout", type=int, default=30000, help="Playwright timeout in milliseconds.")
    parser.add_argument("--allow-http", action="store_true", help="Allow non-HTTPS URLs.")
    parser.add_argument("--json", dest="json_path", help="Write a redacted JSON report.")
    args = parser.parse_args(argv)
    parts = urlsplit(args.url)
    if parts.scheme not in ("http", "https") or not parts.netloc or not parts.path.startswith("/dip/"):
        parser.error("--url must be an absolute /dip/ URL")
    if parts.scheme != "https" and not args.allow_http:
        parser.error("HTTPS is required by default; use --allow-http only for an intentional local test")
    if args.timeout < 1000:
        parser.error("--timeout must be at least 1000 milliseconds")

    results: list[dict] = []
    report = {"url": safe_url(args.url), "checks": results}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not args.headed)
            context = browser.new_context()
            context.set_default_timeout(args.timeout)
            page = context.new_page()
            console_errors = []
            page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))

            response = page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout)
            page.wait_for_load_state("networkidle", timeout=args.timeout)
            status = response.status if response else 0
            body = page.locator("body").inner_text(timeout=args.timeout)
            check(results, "Hub returns successful HTTP response", bool(response) and status == 200, f"HTTP {status}")
            check(results, "Hub is not an error page", not any(marker in body for marker in ERROR_MARKERS), "error markers absent")
            check(results, "Hub renders DIP heading", page.locator("p").filter(has_text="Dokumen DIP").count() > 0, "heading present")
            check(results, "Hub renders product title", bool(page.locator("h1").first.inner_text()), "h1 present")

            current_query = parse_qs(urlsplit(page.url).query, keep_blank_values=True)
            access = current_query.get("access", [None])[0]
            check(results, "Hub URL has access token when supplied", access is not None, "access query present" if access else "no access query")

            links = page.locator('a[href^="/dip/"]')
            hrefs = links.evaluate_all("elements => elements.map(element => element.href)")
            chapter_links = []
            for label, suffix in CHAPTERS:
                matching = [href for href in hrefs if urlsplit(href).path.endswith(suffix)]
                if not matching:
                    check(results, f"{label} link is present", False, f"missing {suffix}")
                    continue
                target = matching[0]
                chapter_links.append((label, target))
                target_access = parse_qs(urlsplit(target).query, keep_blank_values=True).get("access", [None])[0]
                token_ok = (access is None and target_access is None) or (access is not None and target_access == access)
                check(results, f"{label} link is present", True, safe_url(target))
                check(results, f"{label} preserves access token", token_ok, "query token preserved" if token_ok else "query token missing or changed")

            for label, target in chapter_links:
                probe = context.request.get(target, timeout=args.timeout, fail_on_status_code=False)
                assert_response(results, f"{label} endpoint is reachable", probe, allow_pdf=True)

            check(results, "No browser console errors", not console_errors, f"{len(console_errors)} console error(s)")
            check(results, "No uncaught page errors", not page_errors, f"{len(page_errors)} page error(s)")
            report["final_url"] = safe_url(page.url)
            report["console_error_count"] = len(console_errors)
            report["page_error_count"] = len(page_errors)
            browser.close()
    except PlaywrightTimeoutError as exc:
        check(results, "Playwright completed within timeout", False, str(exc))
    except Exception as exc:  # noqa: BLE001
        check(results, "Playwright execution completed", False, f"{type(exc).__name__}: {exc}")

    failed = [item for item in results if not item["ok"]]
    report["passed"] = not failed
    report["failed_count"] = len(failed)
    print(f"\nSUMMARY: {'PASS' if not failed else 'FAIL'}; checks={len(results)}; failed={len(failed)}")
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
