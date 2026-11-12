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


def build_daftar_jurnal(product_name: str, perusahaan: str,
                        materials: list[dict]) -> str | None:
    """Isi file ``Daftar_Jurnal.txt`` untuk ZIP Bab II (generator dokumen).

    Murni fungsi tanpa DB/network: ``materials`` adalah daftar dict bahan baku
    (min. kunci ``nama_dagang``, ``kode_bahan_baku``, ``journal_link``) dalam
    URUTAN SAMA dengan penomoran folder bahan di ZIP (01_, 02_, ...), jadi
    nomor entri memakai posisi ``idx`` di list, bukan urutan jurnal yang ada.
    URL jurnal HANYA ditulis sebagai teks (tidak di-fetch, bukan storage).

    Return ``None`` bila tidak ada satu pun bahan dengan journal_link valid,
    supaya pemanggil tidak membuat file-nya. Entri jurnal tidak valid
    (non-http(s), spasi, >2048, dsb.) diabaikan lewat ``safe_journal_href``.
    """
    entries: list[str] = []
    for idx, material in enumerate(materials or [], start=1):
        if not isinstance(material, dict):
            continue
        link = safe_journal_href(material.get("journal_link"))
        if not link:
            continue
        nama = str(material.get("nama_dagang") or "").strip() or f"Bahan {idx}"
        kode = str(material.get("kode_bahan_baku") or "").strip() or "-"
        entries.append(f"{idx:02d}. {nama} ({kode})\n{link}")
    if not entries:
        return None
    header = (
        "DAFTAR JURNAL REFERENSI BAHAN BAKU\n"
        f"Produk: {product_name}\n"
        f"Perusahaan: {perusahaan}\n"
        + "-" * 40 + "\n"
    )
    return header + "\n".join(entries) + "\n"
