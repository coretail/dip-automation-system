"""Unit tests for app.file_validation helpers."""

from app.file_validation import MAX_PDF_SIZE, validate_pdf_bytes


def test_valid_pdf_accepted():
    data = b"%PDF-1.4\n" + b"x" * 100
    assert validate_pdf_bytes(data, "doc.pdf") is None


def test_empty_rejected():
    assert validate_pdf_bytes(b"", "doc.pdf") is not None


def test_non_pdf_rejected():
    data = b"not a pdf"
    assert validate_pdf_bytes(data, "doc.pdf") is not None


def test_oversized_rejected():
    data = b"%PDF-1.4\n" + b"x" * (MAX_PDF_SIZE + 1)
    assert validate_pdf_bytes(data, "doc.pdf") is not None


def test_exact_limit_accepted():
    data = b"%PDF-1.4\n" + b"x" * (MAX_PDF_SIZE - len(b"%PDF-1.4\n"))
    assert validate_pdf_bytes(data, "doc.pdf") is None


def test_wrong_magic_bytes_rejected():
    data = b"XPDF" + b"x" * 100
    assert validate_pdf_bytes(data, "doc.pdf") is not None
