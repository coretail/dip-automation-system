"""Staging E2E for live profile display names on Team Notes.

Requires a running local staging server and STAGING_ADMIN_EMAIL/PASSWORD.
The disposable user is created and removed through the admin UI; credentials
are read only from environment variables and are never printed.
"""
from __future__ import annotations

import os
import sys
import uuid


def login(page, base_url: str, email: str, password: str) -> None:
    page.goto(base_url + "/login")
    page.locator('input[name="email"]').fill(email)
    page.locator('input[name="password"]').fill(password)
    page.locator('button[type="submit"]').click()
    page.wait_for_url(lambda url: "/login" not in url)


def logout(page, base_url: str) -> None:
    page.goto(base_url + "/")
    page.evaluate(
        "() => { const f = document.createElement('form');"
        " f.method = 'POST'; f.action = '/logout';"
        " document.body.appendChild(f); f.submit(); }"
    )
    page.wait_for_url(lambda url: "/login" in url)


def main() -> int:
    email = os.getenv("STAGING_ADMIN_EMAIL", "")
    password = os.getenv("STAGING_ADMIN_PASSWORD", "")
    if not email or not password:
        print("[ABORT] set STAGING_ADMIN_EMAIL and STAGING_ADMIN_PASSWORD")
        return 1
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ABORT] install Playwright to run notes E2E")
        return 1

    base_url = os.getenv("STAGING_BASE_URL", "http://127.0.0.1:8017")
    disposable_username = "e2e-notes-display"
    disposable_email = "e2e-notes-display@example.invalid"
    disposable_password = "Notes-display-e2e-6"
    display_name = "Notes Display QA"
    marker_base = "e2e-notes-display-name"
    # Marker unik per run: sisa note dari run gagal sebelumnya tidak ikut cocok.
    marker = f"{marker_base}-{uuid.uuid4().hex[:8]}"
    created = False

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            login(page, base_url, email, password)
            page.goto(base_url + "/admin/users")
            page.locator('input[name="email"]').fill(disposable_email)
            page.locator('input[name="username"]').fill(disposable_username)
            page.locator('input[name="password"]').fill(disposable_password)
            page.locator('form[action="/admin/users/create"] button[type="submit"]').click()
            page.wait_for_url(lambda url: "/admin/users" in url)
            created = True

            logout(page, base_url)
            login(page, base_url, disposable_email, disposable_password)
            page.goto(base_url + "/profile")
            page.locator('input[name="display_name"]').fill(display_name)
            page.locator('form[action="/profile/display-name"] button[type="submit"]').click()
            page.wait_for_url(lambda url: "display_name_changed" in url)

            logout(page, base_url)
            login(page, base_url, email, password)
            page.goto(base_url + "/notes")
            users = page.evaluate(
                """async () => (await fetch('/api/notes/users?q=e2e-notes-display')).json()"""
            )
            target = next(
                (item for item in users["items"] if item["full_name"] == disposable_username),
                None,
            )
            assert target and target["display_name"] == display_name, (
                "notes users autocomplete did not return the live display_name"
            )
            body = f"@{disposable_username} {marker}"
            page.locator("#noteBody").fill(body)
            page.locator("#noteForm button[type='submit']").click()
            page.wait_for_url(lambda url: "status=created" in url)

            logout(page, base_url)
            login(page, base_url, email, password)
            page.goto(base_url + "/notes")
            note = page.locator("article", has_text=marker)
            # Catatan ditulis oleh admin, jadi display_name user sekali-pakai hanya
            # tampil di chip mention. Ikon "@" adalah glyph CSS (fa-at), bukan teks.
            chip = note.get_by_text(f"{disposable_username} ({display_name})", exact=True)
            assert chip.is_visible(), "mention chip did not render the live display_name"
            print("[PASS] Team Notes mention display_name rendering verified")
            return 0
        finally:
            if created:
                try:
                    logout(page, base_url)
                    login(page, base_url, email, password)
                    # Hapus note e2e (run ini dan sisa run gagal) sebelum user dihapus.
                    page.goto(base_url + "/notes")
                    for _ in range(20):
                        leftover = page.locator("article", has_text=marker_base)
                        if leftover.count() == 0:
                            break
                        leftover.first.locator('form[action$="/delete"]').evaluate("form => form.submit()")
                        page.wait_for_url(lambda url: "status=deleted" in url or "error=" in url)
                        page.goto(base_url + "/notes")
                    page.goto(base_url + "/admin/users")
                    row = page.locator("tr", has_text=disposable_username)
                    row.locator('form[action="/admin/users/delete"]').evaluate("form => form.submit()")
                except Exception:
                    print("[WARNING] disposable user cleanup requires manual review")
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
