"""Validation logic for user profile fields (display_name, etc.).

Pure functions — no side effects, no Supabase/network. Designed to be unit-testable
in isolation by CI without any external dependencies.
"""
from __future__ import annotations

import unicodedata

MAX_DISPLAY_NAME_LENGTH = 60
MIN_DISPLAY_NAME_LENGTH = 1


def _is_excluded_category(ch: str) -> bool:
    """True for control (Cc) and format/formatting (Cf) Unicode categories.

    These are rejected because they are invisible or can confuse rendering
    and storage. Zero-width spaces (Cf) and other formatting characters are
    not allowed in display names.
    """
    cat = unicodedata.category(ch)
    return cat == "Cc" or cat == "Cf"


def validate_display_name(raw_value: str) -> tuple[str | None, str | None]:
    """Validate and normalize a user-supplied display name.

    Rules (per migration/011 and feature plan):
      - Trim leading/trailing whitespace.
      - Collapse internal runs of whitespace into a single space.
      - Length must be 1..60 **code points** (after trim+collapse).
      - Reject control characters (Cc) and Unicode format characters (Cf).
      - If the input is empty or only whitespace, return (None, None)
        (i.e. clear the display name → fall back to full_name).

    Returns:
        A tuple ``(cleaned_value, error_message)``.
        - If the value is valid and non-empty: ``(cleaned_value, None)``.
        - If the value is empty/whitespace-only: ``(None, None)``.
        - If the value is invalid: ``(None, error_message)``.
    """
    if raw_value is None:
        return None, None

    if not isinstance(raw_value, str):
        return None, "Nama tampilan harus berupa teks."

    # Trim leading/trailing whitespace
    trimmed = raw_value.strip()

    # Collapse multiple whitespace characters into a single space
    # (includes spaces, tabs, newlines, etc.)
    collapsed = " ".join(trimmed.split())

    # Empty or whitespace-only → clear to NULL (fallback to full_name)
    if not collapsed:
        return None, None

    # Reject control (Cc) and format (Cf) characters
    for ch in collapsed:
        if _is_excluded_category(ch):
            return None, (
                "Nama tampilan tidak boleh mengandung karakter kontrol "
                "atau format tak terlihat."
            )

    # Length check: 1-60 code points
    if len(collapsed) < MIN_DISPLAY_NAME_LENGTH:
        return None, f"Nama tampilan minimal {MIN_DISPLAY_NAME_LENGTH} karakter."
    if len(collapsed) > MAX_DISPLAY_NAME_LENGTH:
        return None, (
            f"Nama tampilan maksimal {MAX_DISPLAY_NAME_LENGTH} karakter "
            f"(saat ini {len(collapsed)} karakter)."
        )

    return collapsed, None
