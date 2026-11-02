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

    Admins always pass. Backward-compatible: if either side has no company,
    access is allowed (legacy data -- pre-check staging 2026-11-02: 2/5
    profiles belum punya perusahaan, menolak mereka = lockout).
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
