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
_DEFAULT_MAX_ROWS = 5000


def paginate_all(fetch_page, page_size: int = DEFAULT_PAGE_SIZE, max_rows: int | None = None) -> list:
    """Ambil SELURUH baris lewat halaman: ``fetch_page(offset) -> list[dict]``.

    ``fetch_page`` harus mengaplikasikan ``.range(offset, offset+page_size-1)``
    (plus ``.order`` pada kolom unik agar urutan deterministik) dan
    mengembalikan daftar baris halaman itu (bukan objek response). Loop
    berhenti saat satu halaman mengembalikan kurang dari ``page_size`` baris
    (halaman terakhir lebih pendek ATAU halaman kosong) — pola sama dengan
    fallback di dashboard_routes.py.

    ``max_rows`` (opsional): jaring pengaman keras — hentikan loop saat jumlah
    baris mencapai batas ini dan potong hasil ke ``max_rows``. Default None
    = tanpa batas (perilaku lama, tidak berubah untuk caller eksisting).

    Error dari fetch (query gagal) dilempar ke pemanggil (jangan ditelan di
    sini, supaya fallback caller tetap print-nya).
    """
    if page_size < 1:
        raise ValueError("page_size harus >= 1")
    if max_rows is not None and max_rows < 1:
        raise ValueError("max_rows harus >= 1 atau None")
    rows: list = []
    offset = 0
    while True:
        page = list(fetch_page(offset) or [])
        rows.extend(page)
        if max_rows is not None and len(rows) >= max_rows:
            return rows[:max_rows]
        if len(page) < page_size:
            break
        offset += page_size
    return rows


def paginate_all_capped(fetch_page, page_size: int = DEFAULT_PAGE_SIZE,
                       max_rows: int = _DEFAULT_MAX_ROWS) -> tuple[list, bool]:
    """Sama dengan ``paginate_all`` tapi mengembalikan ``(rows, truncated)``.

    ``truncated=True`` hanya jika masih ada baris setelah batas:
    - halaman terakhir TEPAT penuh di offset max_rows (perlu cek halaman
      berikutnya untuk memastikan masih ada data), ATAU
    - ``fetch_page`` di offset max_rows mengembalikan >= 1 baris.

    ``max_rows`` default 5000 (jaring pengaman; PostgREST db.max-rows default
    1000 baris per halaman, jadi 5000 = 5 halaman penuh + margin).
    """
    if page_size < 1:
        raise ValueError("page_size harus >= 1")
    if max_rows < 1:
        raise ValueError("max_rows harus >= 1")
    rows: list = []
    offset = 0
    truncated = False
    while True:
        page = list(fetch_page(offset) or [])
        rows.extend(page)
        if len(rows) >= max_rows:
            rows = rows[:max_rows]
            # Cek apakah masih ada data setelah batas:
            # ambil 1 baris dari halaman berikutnya (offset = max_rows).
            # Kalau fetch_page di max_rows mengembalikan >= 1 baris -> truncated.
            # Kalau halaman di max_rows kosong -> tidak truncated (data habis tepat di batas).
            probe = fetch_page(max_rows) or []
            truncated = len(probe) > 0
            break
        if len(page) < page_size:
            break
        offset += page_size
    return rows, truncated


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
