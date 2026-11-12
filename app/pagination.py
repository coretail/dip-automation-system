"""Helper pagination + hitung pemakaian bahan baku — MURNI, tanpa import
supabase/DB, supaya bisa dites tanpa koneksi (pola modul util ``app/``).

Dipakai ``app/raw_materials_routes.py`` untuk badge "N Produk" di
/raw-materials: query PostgREST tanpa paginasi terpotong diam-diam di batas
``db.max-rows`` (default 1000 baris), jadi jumlah produk pemakai tiap bahan
baku bisa kurang dari yang sebenarnya (modal "Dipakai di Produk" query per
bahan jadi tidak terpengaruh). Pola berhalaman sama dengan fallback di
``app/dashboard_routes.py``.
"""
from __future__ import annotations

DEFAULT_PAGE_SIZE = 1000


def paginate_all(fetch_page, page_size: int = DEFAULT_PAGE_SIZE) -> list:
    """Ambil SELURUH baris lewat halaman: ``fetch_page(offset) -> list[dict]``.

    ``fetch_page`` harus mengaplikasikan ``.range(offset, offset+page_size-1)``
    (plus ``.order`` pada kolom unik agar urutan deterministik) dan
    mengembalikan daftar baris halaman itu (bukan objek response). Loop
    berhenti saat satu halaman mengembalikan kurang dari ``page_size`` baris
    (halaman terakhir lebih pendek ATAU halaman kosong) — pola sama dengan
    fallback di dashboard_routes.py.

    Error dari fetch (query gagal) dilempar ke pemanggil (jangan ditelan di
    sini, supaya fallback caller tetap print-nya).
    """
    if page_size < 1:
        raise ValueError("page_size harus >= 1")
    rows: list = []
    offset = 0
    while True:
        page = list(fetch_page(offset) or [])
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows


def _embed_is_deleted(embedded) -> bool:
    """embed relasi many-to-one produk bisa dict ATAU list (supabase-py);
    kosong/None dianggap tidak terhapus (sama dengan _is_deleted_product
    di raw_materials_routes, versi mandiri agar modul ini tetap murni)."""
    if isinstance(embedded, list):
        embedded = embedded[0] if embedded else None
    return bool((embedded or {}).get("is_deleted"))


def usage_counts(rows: list) -> dict:
    """Hitung produk aktif per bahan baku dari baris product_formula_lines.

    Aturan (sama dengan endpoint popup /used-in-products):
    - 1 bahan dihitung maksimal sekali per produk (dedup via ``product_id``);
    - produk soft-delete (embed ``products.is_deleted``) tidak dihitung;
    - embed ``products`` boleh dict, list, atau None; baris tanpa
      ``raw_material_id``/``product_id`` diabaikan.

    Return ``{raw_material_id: jumlah produk aktif}``.
    """
    sets: dict = {}
    for ln in rows or []:
        rm_id = ln.get("raw_material_id")
        prod_id = ln.get("product_id")
        if rm_id and prod_id and not _embed_is_deleted(ln.get("products")):
            sets.setdefault(rm_id, set()).add(prod_id)
    return {rm_id: len(ids) for rm_id, ids in sets.items()}
