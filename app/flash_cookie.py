"""Shared helpers for flash message cookies and invisible character cleanup.

Pure-local module (no imports from app.main or app.database).
HTTP cookie values must be latin-1 encodable; flash messages can include
arbitrary user-supplied text (e.g. product names with em-dash, emoji, or
pasted invisible Unicode characters). Encoding with percent-encoding keeps
Set-Cookie headers strictly ASCII/latin-1-safe while round-tripping
original strings identically.
"""
from __future__ import annotations

import re
from urllib.parse import quote, unquote

FLASH_COOKIE_KEYS = ("success_msg", "error_msg", "warning_msg")

# Invisible / zero-width / line-separator characters commonly introduced via copy-paste.
INVISIBLE_CHARS_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e\u2028\u2029]+")


def encode_flash_value(message: str) -> str:
    """Percent-encode a flash message so Set-Cookie is strictly ASCII/latin-1-safe."""
    return quote(str(message), safe="")


def decode_flash_value(raw: str | None) -> str | None:
    """Decode a percent-encoded flash cookie value (None stays None)."""
    if raw is None:
        return None
    return unquote(str(raw))


def set_flash_cookie(response, key: str, message: str, **opts) -> None:
    """Set a flash cookie with percent-encoded value, preserving existing cookie options."""
    response.set_cookie(key, encode_flash_value(message), **opts)


def get_flash_cookie(request, key: str, default: str | None = None) -> str | None:
    """Read and decode a flash cookie from Request.cookies."""
    raw = request.cookies.get(key)
    if raw is None:
        return default
    return decode_flash_value(raw)


def delete_flash_cookie(response, key: str, **opts) -> None:
    """Delete a flash cookie on the response, preserving cookie options."""
    response.delete_cookie(key, **opts)


def clean_visible_text(value: str | None) -> str | None:
    """Strip invisible Unicode formatting/separator characters and outer whitespace."""
    if value is None or not isinstance(value, str):
        return value
    return INVISIBLE_CHARS_RE.sub("", value).strip()
