"""Pure-local tests for display_name validation; no Supabase network."""
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

from app.profile_validation import (
    validate_display_name,
    MAX_DISPLAY_NAME_LENGTH,
    MIN_DISPLAY_NAME_LENGTH,
)


def test_valid_display_name():
    cleaned, error = validate_display_name("Budi")
    assert cleaned == "Budi"
    assert error is None
    print("[PASS] valid display name returns cleaned value, no error")


def test_trim_leading_trailing():
    cleaned, error = validate_display_name("   Budi Santoso   ")
    assert cleaned == "Budi Santoso"
    assert error is None
    print("[PASS] leading/trailing whitespace trimmed")


def test_collapse_multiple_spaces():
    cleaned, error = validate_display_name("Budi   Santoso")
    assert cleaned == "Budi Santoso"
    assert error is None
    print("[PASS] multiple internal spaces collapsed to single")


def test_collapse_tabs_and_newlines():
    cleaned, error = validate_display_name("Budi\t\tSantoso\nBudi")
    assert cleaned == "Budi Santoso Budi"
    assert error is None
    print("[PASS] tabs/newlines collapsed to single space")


def test_empty_returns_null():
    cleaned, error = validate_display_name("")
    assert cleaned is None
    assert error is None
    print("[PASS] empty string returns (None, None) to clear display name")


def test_whitespace_only_returns_null():
    cleaned, error = validate_display_name("   \t\n  ")
    assert cleaned is None
    assert error is None
    print("[PASS] whitespace-only returns (None, None) to clear display name")


def test_none_returns_null():
    cleaned, error = validate_display_name(None)
    assert cleaned is None
    assert error is None
    print("[PASS] None input returns (None, None)")


def test_too_long_rejected():
    long_name = "A" * (MAX_DISPLAY_NAME_LENGTH + 1)
    cleaned, error = validate_display_name(long_name)
    assert cleaned is None
    assert error is not None
    assert str(MAX_DISPLAY_NAME_LENGTH) in error
    print("[PASS] display name exceeding 60 chars is rejected")


def test_max_length_accepted():
    name = "A" * MAX_DISPLAY_NAME_LENGTH
    cleaned, error = validate_display_name(name)
    assert cleaned == name
    assert error is None
    print("[PASS] display name at exactly 60 chars is accepted")


def test_control_chars_rejected():
    cleaned, error = validate_display_name("Budi\x00Santoso")
    assert cleaned is None
    assert error is not None
    print("[PASS] control characters (Cc) rejected")


def test_format_chars_rejected():
    # Zero-width space U+200B is Cf (format)
    cleaned, error = validate_display_name("Budi\u200bSantoso")
    assert cleaned is None
    assert error is not None
    print("[PASS] zero-width space (Cf) rejected")


def test_non_string_rejected():
    cleaned, error = validate_display_name(12345)
    assert cleaned is None
    assert error is not None
    print("[PASS] non-string input rejected")


def test_underscore_hyphen_accepted():
    cleaned, error = validate_display_name("Budi-Santoso_123")
    assert cleaned == "Budi-Santoso_123"
    assert error is None
    print("[PASS] hyphens and underscores preserved")


def test_unicode_chars_accepted():
    cleaned, error = validate_display_name("José María")
    assert cleaned == "José María"
    assert error is None
    print("[PASS] unicode characters (é, í) preserved")


if __name__ == "__main__":
    test_valid_display_name()
    test_trim_leading_trailing()
    test_collapse_multiple_spaces()
    test_collapse_tabs_and_newlines()
    test_empty_returns_null()
    test_whitespace_only_returns_null()
    test_none_returns_null()
    test_too_long_rejected()
    test_max_length_accepted()
    test_control_chars_rejected()
    test_format_chars_rejected()
    test_non_string_rejected()
    test_underscore_hyphen_accepted()
    test_unicode_chars_accepted()
    print("All profile validation tests passed.")
