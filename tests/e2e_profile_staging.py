"""Staging E2E checklist for /profile.

This script intentionally requires explicit staging credentials and a running
staging launcher. It creates a disposable user through the admin UI/API flow;
it never changes STAGING_ADMIN_* credentials.
"""

import os
import sys


def main():
    required = ("STAGING_ADMIN_EMAIL", "STAGING_ADMIN_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise SystemExit("Missing staging credentials: " + ", ".join(missing))
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit("Install Playwright to run staging profile E2E") from exc

    base_url = os.getenv("STAGING_BASE_URL", "http://127.0.0.1:8017")
    disposable_username = "e2e-profile-disposable"
    disposable_email = "e2e-profile-disposable@example.invalid"
    disposable_password = "Profile-e2e-old-6"
    replacement_password = "Profile-e2e-new-6"
    created = False

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        other_page = None
        try:
            page.goto(base_url + "/login")
            page.locator('input[name="email"]').fill(os.environ["STAGING_ADMIN_EMAIL"])
            page.locator('input[name="password"]').fill(os.environ["STAGING_ADMIN_PASSWORD"])
            page.locator('button[type="submit"]').click()
            page.wait_for_url(base_url + "/")

            page.goto(base_url + "/admin/users")
            # The exact admin creation form remains intentionally UI-driven so
            # this test exercises the same route as an administrator.
            page.locator('input[name="email"]').fill(disposable_email)
            page.locator('input[name="username"]').fill(disposable_username)
            page.locator('input[name="password"]').fill(disposable_password)
            page.locator('button[type="submit"]').click()
            page.wait_for_url(lambda url: "/admin/users" in url)
            created = True

            page.goto(base_url + "/logout")
            page.goto(base_url + "/login")
            page.locator('input[name="email"]').fill(disposable_email)
            page.locator('input[name="password"]').fill(disposable_password)
            page.locator('button[type="submit"]').click()
            page.wait_for_url(base_url + "/")
            page.goto(base_url + "/profile")
            assert page.get_by_role("heading", name="User Profile").is_visible()
            for theme in ("light", "terra", "rose", "dark"):
                page.locator(f'[data-profile-theme="{theme}"]').click()
                assert page.locator("html").get_attribute("data-theme") == theme

            # Keep a second JWT alive while changing the password to verify the
            # observed cross-device session behavior without using admin secrets.
            other_page = context.new_page()
            other_page.goto(base_url + "/login")
            other_page.locator('input[name="email"]').fill(disposable_email)
            other_page.locator('input[name="password"]').fill(disposable_password)
            other_page.locator('button[type="submit"]').click()
            other_page.wait_for_url(base_url + "/")

            page.locator('input[name="current_password"]').fill("wrong-password")
            page.locator('input[name="new_password"]').fill(replacement_password)
            page.locator('input[name="confirm_new_password"]').fill(replacement_password)
            page.locator('form[action="/profile/change-password"] button[type="submit"]').click()
            page.wait_for_url(lambda url: "current_password_invalid" in url)

            page.locator('input[name="current_password"]').fill(disposable_password)
            page.locator('input[name="new_password"]').fill(replacement_password)
            page.locator('input[name="confirm_new_password"]').fill(replacement_password)
            page.locator('form[action="/profile/change-password"] button[type="submit"]').click()
            page.wait_for_url(lambda url: "password_changed" in url)
            assert page.get_by_role("heading", name="User Profile").is_visible()

            other_page.goto(base_url + "/profile")
            assert other_page.get_by_role("heading", name="User Profile").is_visible()
            print("Profile page, themes, password validation, password update, and JWT session behavior verified.")
        finally:
            if other_page is not None:
                other_page.close()
            if created:
                try:
                    page.goto(base_url + "/logout")
                    page.goto(base_url + "/login")
                    page.locator('input[name="email"]').fill(os.environ["STAGING_ADMIN_EMAIL"])
                    page.locator('input[name="password"]').fill(os.environ["STAGING_ADMIN_PASSWORD"])
                    page.locator('button[type="submit"]').click()
                    page.wait_for_url(base_url + "/")
                    page.goto(base_url + "/admin/users")
                    row = page.locator("tr", has_text=disposable_username)
                    row.locator('form[action="/admin/users/delete"]').evaluate("form => form.submit()")
                    page.wait_for_timeout(500)
                except Exception:
                    # Cleanup failure is reported by the staging run output
                    # without printing credentials or exception contents.
                    print("WARNING: disposable profile user cleanup requires manual review.")
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
