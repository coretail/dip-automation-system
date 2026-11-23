"""Pure-local tests untuk helper validasi & template aktivasi (Task 4).

Tanpa jaringan, tanpa secret, tidak membaca `.env`.
Dijalankan: python tests/test_invite_validation.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.activate_routes import (  # noqa: E402
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    is_valid_activation_type,
    validate_activation_password,
)
from app.profile_validation import validate_display_name  # noqa: E402

FAILURES = []
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "app" / "templates" / "activate.html"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def test_activation_type_whitelist():
    check("type 'invite' diterima", is_valid_activation_type("invite"))
    check("type ' invite ' (trimmed) diterima", is_valid_activation_type(" invite "))
    for bad in ("recovery", "signup", "magiclink", "email", "", "INVITE", "invite2"):
        check(f"type {bad!r} ditolak", not is_valid_activation_type(bad))


def test_password_validation():
    check("password kosong ditolak", validate_activation_password("", "") is not None)
    check("password < 6 karakter ditolak", validate_activation_password("12345", "12345") is not None)
    check("password hanya spasi 6 karakter ditolak", validate_activation_password("      ", "      ") is not None)
    too_long = "a" * (MAX_PASSWORD_LENGTH + 1)
    check("password > 72 karakter ditolak", validate_activation_password(too_long, too_long) is not None)
    check("konfirmasi tidak cocok ditolak", validate_activation_password("rahasia1", "rahasia2") is not None)
    check(
        f"password tepat {MIN_PASSWORD_LENGTH} karakter diterima",
        validate_activation_password("123456", "123456") is None,
    )
    exact_max = "b" * MAX_PASSWORD_LENGTH
    check(
        f"password tepat {MAX_PASSWORD_LENGTH} karakter diterima",
        validate_activation_password(exact_max, exact_max) is None,
    )


def test_display_name_validation():
    check("display_name kosong -> (None, None)", validate_display_name("") == (None, None))
    check("display_name spasi saja -> (None, None)", validate_display_name("   \t ") == (None, None))
    cleaned, err = validate_display_name("  Budi   Santoso  ")
    check("display_name spasi ganda di-collapse", cleaned == "Budi Santoso" and err is None, repr((cleaned, err)))
    val_over, err_over = validate_display_name("x" * 61)
    check("display_name > 60 karakter -> error", val_over is None and err_over is not None)
    val_cc, err_cc = validate_display_name("Budi\x00")
    check("display_name kontrol Cc -> error", val_cc is None and err_cc is not None)
    val_cf, err_cf = validate_display_name("Budi\u200b")
    check("display_name format Cf -> error", val_cf is None and err_cf is not None)


def test_activate_template_invariants():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    low = html.lower()
    check("activate.html mandiri (tanpa extends)", "extends" not in low)
    check("activate.html tanpa URL eksternal http://", "http://" not in low)
    check("activate.html tanpa URL eksternal https://", "https://" not in low)
    check("activate.html tanpa tag <script", "<script" not in low)
    check("activate.html tanpa no-referrer", "no-referrer" not in low)
    check("activate.html tanpa input/label email", 'name="email"' not in low and "type=\"email\"" not in low)
    check("activate.html diakhiri newline", html.endswith("\n"))


def main():
    test_activation_type_whitelist()
    test_password_validation()
    test_display_name_validation()
    test_activate_template_invariants()

    print()
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} pemeriksaan")
        for name in FAILURES:
            print(f"  - {name}")
        sys.exit(1)
    print("OK: semua pemeriksaan validasi aktivasi lolos")


if __name__ == "__main__":
    main()
