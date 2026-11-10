"""Security helpers shared by route modules.

This module must not import app.main (avoid circular imports).
"""

from typing import Any


def _norm_company(value: str | None) -> str:
    # Normalisasi sama seperti inline check lama di sample_routes:
    # "PT Erfi" ~= "erfi". Konsistensi ini yang membuat helper bisa
    # menggantikan inline check tanpa mengubah perilaku penolakan.
    return (value or "").strip().lower().replace("pt ", "").strip()


def assert_same_tenant(current_user: dict, row: dict | None, new_company: str | None = None) -> bool:
    """Return True when a non-admin user may access/modify a row.

    Keputusan pemilik repo 2026-11-09: staff (non-admin) DISENGAJA boleh
    mengerjakan data lintas perusahaan (PT Erfi dan PT Heka). Guard ini
    hanya membatasi akun yang perusahaan-nya diisi: non-admin dengan
    perusahaan kosong lolos untuk semua baris karena sistem per 2026-11-09
    belum memiliki profil yang mengisi perusahaan, dan itu bukan celah.
    Akun TANPA profil / query profil gagal tetap fail-closed (403/503)
    di get_current_user (sejak PR #69), terpisah dari guard ini.
    Row perusahaan dibaca dari kunci ``perusahaan`` (products/raw_materials)
    atau ``company`` (sample_submissions).
    """
    if (current_user or {}).get("role") == "admin":
        return True
    user_company = _norm_company((current_user or {}).get("perusahaan"))
    row_data = row or {}
    row_company = _norm_company(row_data.get("perusahaan") or row_data.get("company"))
    requested_company = _norm_company(new_company)
    if not user_company:
        return True
    if row_company and row_company != user_company:
        return False
    # new_company DIBERIKAN tapi kosong setelah normalisasi (mis. "   "):
    # FastAPI hanya menolak string kosong persis pada Form(...), sedangkan
    # spasi lolos dan tersimpan mentah. Tanpa cek ini non-admin bisa
    # mengosongkan perusahaan produk, lalu produk itu fail-open untuk semua
    # tenant. None (tidak ada perubahan perusahaan) tetap diizinkan.
    if new_company is not None and not requested_company:
        return False
    if requested_company and requested_company != user_company:
        return False
    return True
