"""Shared, behavior-preserving helpers for validating uploaded PDF files."""

MAX_PDF_SIZE = 10 * 1024 * 1024


def validate_pdf_bytes(data: bytes, filename: str | None = None) -> str | None:
    """Return an error message if *data* is not an acceptable PDF upload.

    Behavior matches the inline checks already used across the app:
    - file must look like a PDF (`%PDF` magic bytes)
    - size must not exceed 10 MB
    """
    if not data:
        return "File kosong atau tidak valid."
    if data[:4] != b"%PDF":
        label = filename or "File"
        return f"{label} harus berupa PDF yang valid."
    if len(data) > MAX_PDF_SIZE:
        return "Ukuran file terlalu besar! Maksimal ukuran file adalah 10 MB. Silakan kompres PDF Anda terlebih dahulu."
    return None


def is_pdf_bytes(data: bytes) -> bool:
    return bool(data) and data[:4] == b"%PDF" and len(data) <= MAX_PDF_SIZE
