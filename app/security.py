"""Security helpers shared by route modules.

This module must not import app.main (avoid circular imports).
"""

from typing import Any


def assert_same_tenant(current_user: dict, row: dict | None, new_company: str | None = None) -> bool:
    """Return True when a non-admin user may access/modify a row.

    Admins always pass. Backward-compatible: if either side has no company,
    access is allowed (legacy data). This helper is advisory during refactor;
    enforcement is intentionally left to callers so behavior stays unchanged.
    """
    if (current_user or {}).get("role") == "admin":
        return True
    user_company = ((current_user or {}).get("perusahaan") or "").strip().lower()
    row_company = ((row or {}).get("perusahaan") or "").strip().lower()
    requested_company = (new_company or "").strip().lower()
    if not user_company:
        return True
    if row_company and row_company != user_company:
        return False
    if requested_company and requested_company != user_company:
        return False
    return True
