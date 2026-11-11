"""Validasi kolom ``journal_link`` (link jurnal/literatur keselamatan bahan baku).

Murni fungsi tanpa import app/supabase, supaya bisa di-import unit test
tanpa booting aplikasi (pola sama dengan modul util lain di ``app/``).
Dipakai ``app/raw_materials_routes.py`` untuk menormalisasi field form
"Tambah/Edit Bahan Baku"; nilai yang lolos harus memenuhi CHECK
constraint migrasi 014 (NULL atau URL http(s) maksimal 2048 karakter).
"""
from __future__ import annotations

from urllib.parse import urlsplit

JOURNAL_LINK_MAX_LEN = 2048


def _validasi(text: str) -> None:
    """Throw ValueError (pesan Indonesia) bila ``text`` bukan URL journal yang sah."""
    if len(text) > JOURNAL_LINK_MAX_LEN:
        raise ValueError(
            f"Link jurnal maksimal {JOURNAL_LINK_MAX_LEN} karakter "
            f"(terdeteksi {len(text)}). Pendekkan URL-nya."
        )
    if any(ch.isspace() or ord(ch) < 0x20 or ch == "\x7f" for ch in text):
        raise ValueError(
            "Link jurnal tidak boleh mengandung spasi atau karakter kontrol; "
            "tulis URL secara utuh (pakai %20 bila memang perlu)."
        )
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        hint = "" if parts.scheme else " (tanpa scheme http:// atau https://)"
        raise ValueError(
            f"Link jurnal harus diawali http:// atau https://{hint} "
            f"(terdeteksi '{text[:32]}...'). Skema lainnya ditolak."
        )
    if not parts.netloc:
        raise ValueError(
            "Link jurnal harus punya nama host "
            "(contoh: https://cir-safety.org/contoh.pdf)."
        )


def normalize_journal_link(value: str | None) -> str | None:
    """Normalisasi input form journal_link.

    - ``None`` / kosong / whitespace penuh -> ``None`` (biar tetap NULL di DB).
    - Nilai valid -> string ter-strip.
    - Tidak valid -> ``ValueError`` dengan pesan Indonesia.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    _validasi(text)
    return text


def safe_journal_href(value: str | None) -> str | None:
    """Versi non-raising untuk render (defense-in-depth saat menampilkan href).

    Return string ter-strip bila valid, ``None`` bila kosong/tidak valid.
    Data lama yang melanggar (mis. diinput lewat jalur lain) tidak boleh
    meruntuhkan halaman saat dirender.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        _validasi(text)
    except ValueError:
        return None
    return text
