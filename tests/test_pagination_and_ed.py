"""Unit test gabungan pagination & notifikasi ED/NA (pure-local, tanpa DB/jaringan):
  1. app/pagination.py: paginate_all & usage_counts badge "N Produk"
  2. app/pagination.py & app/ed_notifications.py: paginate_all_capped, critical_ed_items, critical_na_items (N-01/N-02)
  3. app/ed_notifications.py: build_ed_batch_query & build_ed_product_query (regresi PostgREST)

Digabungkan pada Task 8 dari:
  - test_paginate_all.py
  - test_po_pagination_correctness.py
  - test_ed_query_builder.py

Jalankan: python tests/test_pagination_and_ed.py
"""
import os
import sys
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from postgrest import SyncPostgrestClient  # noqa: E402

from app.ed_notifications import (  # noqa: E402
    build_ed_batch_query,
    build_ed_product_query,
    critical_ed_items,
    critical_na_items,
)
from app.pagination import paginate_all, paginate_all_capped, usage_counts  # noqa: E402

WIB = ZoneInfo("Asia/Jakarta")
_DUMMY_URL = "https://ci.invalid/rest/v1"


class FakeSource:
    """Simulasi tabel N baris dengan page size tetap; rekam offset yang diminta."""

    def __init__(self, total_rows, page_size=1000, row_factory=None):
        make_row = row_factory or (lambda i: {"n": i})
        self.rows = [make_row(i) for i in range(total_rows)]
        self.page_size = page_size
        self.offsets = []

    def fetch(self, offset):
        self.offsets.append(offset)
        return self.rows[offset:offset + self.page_size]


def _po_source(total_rows, page_size=1000):
    return FakeSource(
        total_rows,
        page_size=page_size,
        row_factory=lambda i: {"id": i, "tanggal_po": "2026-01-01"},
    )


# =====================================================================
# Bagian 1: paginate_all & usage_counts
# =====================================================================


def test_paginate_all_empty():
    src = FakeSource(0)
    out = paginate_all(src.fetch)
    assert out == []
    assert src.offsets == [0]


def test_paginate_all_one_full_page():
    src = FakeSource(1000)
    out = paginate_all(src.fetch)
    assert len(out) == 1000
    assert src.offsets == [0, 1000]


def test_paginate_all_2500_rows():
    src = FakeSource(2500)
    out = paginate_all(src.fetch)
    assert len(out) == 2500
    assert out == src.rows
    assert src.offsets == [0, 1000, 2000]


def test_paginate_all_last_page_exactly_full():
    src = FakeSource(3000)
    out = paginate_all(src.fetch)
    assert len(out) == 3000
    assert src.offsets == [0, 1000, 2000, 3000]


def test_paginate_all_custom_page_size():
    src = FakeSource(5, page_size=2)

    def fetch(offset):
        return src.rows[offset:offset + 2]

    out = paginate_all(fetch, page_size=2)
    assert out == src.rows


def _ln(rm, prod, embed):
    return {"raw_material_id": rm, "product_id": prod, "products": embed}


def test_usage_counts_dedup_per_product():
    rows = [
        _ln("rm1", "p1", {"is_deleted": False}),
        _ln("rm1", "p1", {"is_deleted": False}),
        _ln("rm1", "p2", {"is_deleted": False}),
    ]
    assert usage_counts(rows) == {"rm1": 2}


def test_usage_counts_deleted_product_excluded():
    rows = [
        _ln("rm1", "p1", {"is_deleted": True}),
        _ln("rm1", "p2", {"is_deleted": False}),
    ]
    assert usage_counts(rows) == {"rm1": 1}


def test_usage_counts_embed_as_list():
    rows = [
        _ln("rm1", "p1", [{"is_deleted": False}]),
        _ln("rm1", "p2", [{"is_deleted": True}]),
        _ln("rm1", "p3", []),
    ]
    assert usage_counts(rows) == {"rm1": 2}


def test_usage_counts_embed_null_and_missing_fields():
    rows = [
        _ln("rm1", "p1", None),
        {"product_id": "p2", "products": None},
        {"raw_material_id": "rm1", "products": None},
    ]
    assert usage_counts(rows) == {"rm1": 1}


def test_usage_counts_empty():
    assert usage_counts([]) == {}
    assert usage_counts(None) == {}


# =====================================================================
# Bagian 2: paginate_all_capped & critical_ed_items / critical_na_items
# =====================================================================


def test_capped_2500_rows_limit_1000():
    """2500 baris, max_rows=1000 -> 1000 baris + truncated=True."""
    src = _po_source(2500)
    rows, truncated = paginate_all_capped(src.fetch, page_size=1000, max_rows=1000)
    assert len(rows) == 1000, f"Harus 1000, dapat {len(rows)}"
    assert truncated is True, "Harus truncated (masih 1500 baris setelah batas)"
    ids = [r["id"] for r in rows]
    assert ids == list(range(1000)), "Urutan harus stabil"
    assert len(ids) == len(set(ids)), "Tidak boleh ada duplikat"
    print("[OK] capped 2500/batas 1000: 1000 + truncated=True")


def test_capped_total_exact_at_limit():
    """Total TEPAT di batas (1000 baris, max_rows=1000) -> truncated=False."""
    src = _po_source(1000)
    rows, truncated = paginate_all_capped(src.fetch, page_size=1000, max_rows=1000)
    assert len(rows) == 1000
    assert truncated is False, "Data habis tepat di batas -> tidak truncated"
    print("[OK] total tepat di batas: truncated=False")


def test_capped_below_limit():
    """Di bawah batas (500 baris, max_rows=1000) -> 500 + truncated=False."""
    src = _po_source(500)
    rows, truncated = paginate_all_capped(src.fetch, page_size=1000, max_rows=1000)
    assert len(rows) == 500
    assert truncated is False
    print("[OK] di bawah batas: truncated=False")


def test_capped_no_duplicates_across_pages():
    """2500 baris dengan page_size=1000: semua 2500 terambil, tanpa duplikat."""
    src = _po_source(2500)
    rows, truncated = paginate_all_capped(src.fetch, page_size=1000, max_rows=5000)
    assert len(rows) == 2500
    assert truncated is False
    ids = [r["id"] for r in rows]
    assert ids == list(range(2500)), "Urutan harus stabil tanpa lompat"
    assert len(ids) == len(set(ids))
    print("[OK] 2500 baris tanpa batas: semua terambil, tanpa duplikat")


def test_paginate_all_unchanged_behavior():
    """paginate_all tanpa max_rows: perilaku lama tidak berubah."""
    src = _po_source(2500)
    out = paginate_all(src.fetch)
    assert len(out) == 2500
    assert out == src.rows
    print("[OK] paginate_all tanpa max_rows: perilaku lama tidak berubah")


def _make_compute_status_na():
    """Versi mandiri compute_status_na untuk test (sama logika dengan main.py)."""
    def compute_status_na(tanggal_aktif_na, fallback_status):
        if not tanggal_aktif_na:
            return fallback_status, None
        try:
            if isinstance(tanggal_aktif_na, str):
                start = datetime.strptime(tanggal_aktif_na[:10], "%Y-%m-%d").date()
            else:
                start = tanggal_aktif_na
        except Exception:
            return fallback_status, None
        today = date(2026, 11, 13)
        try:
            expired = start.replace(year=start.year + 3)
        except ValueError:
            expired = start.replace(year=start.year + 3, day=28)
        days_remaining = (expired - today).days
        if days_remaining < 0:
            return "expired", days_remaining
        elif days_remaining <= 180:
            return "akan_expired", days_remaining
        return "aktif", None

    return compute_status_na


def test_ed_batch_exactly_180_days():
    """Batch tepat 180 hari: termasuk (kritis)."""
    today = date(2026, 11, 13)
    ed_date = today + timedelta(days=180)
    rows = [{"id": 1, "tanggal_ed": ed_date.isoformat(), "status_ed": "Active"}]
    items = critical_ed_items(rows, today)
    assert len(items) == 1, f"Harus 1 item, dapat {len(items)}"
    assert items[0]["days_remaining"] == 180
    assert items[0]["status_ed"] == "Kritis (<= 180 hari)"
    print("[OK] batch 180 hari: kritis")


def test_ed_batch_181_days():
    """Batch 181 hari: TIDAK termasuk."""
    today = date(2026, 11, 13)
    ed_date = today + timedelta(days=181)
    rows = [{"id": 1, "tanggal_ed": ed_date.isoformat(), "status_ed": "Active"}]
    items = critical_ed_items(rows, today)
    assert len(items) == 0, f"Harus 0 item, dapat {len(items)}"
    print("[OK] batch 181 hari: tidak kritis")


def test_ed_batch_zero_days():
    """Batch 0 hari (ED hari ini): termasuk, status Expired."""
    today = date(2026, 11, 13)
    rows = [{"id": 1, "tanggal_ed": today.isoformat(), "status_ed": "Active"}]
    items = critical_ed_items(rows, today)
    assert len(items) == 1
    assert items[0]["days_remaining"] == 0
    assert items[0]["status_ed"] == "Expired"
    print("[OK] batch 0 hari: Expired")


def test_ed_batch_negative_days():
    """Batch -1 hari (ED kemarin): termasuk, status Expired."""
    today = date(2026, 11, 13)
    ed_date = today - timedelta(days=1)
    rows = [{"id": 1, "tanggal_ed": ed_date.isoformat(), "status_ed": "Active"}]
    items = critical_ed_items(rows, today)
    assert len(items) == 1
    assert items[0]["days_remaining"] == -1
    assert items[0]["status_ed"] == "Expired"
    print("[OK] batch -1 hari: Expired")


def test_ed_batch_null_date():
    """Tanggal null: di-skip."""
    today = date(2026, 11, 13)
    rows = [{"id": 1, "tanggal_ed": None, "status_ed": "Active"}]
    items = critical_ed_items(rows, today)
    assert len(items) == 0
    print("[OK] tanggal null: di-skip")


def test_ed_batch_date_object_vs_string():
    """tanggal_ed sebagai date object dan string ISO: sama hasilnya."""
    today = date(2026, 11, 13)
    ed_date = today + timedelta(days=100)
    rows_str = [{"id": 1, "tanggal_ed": ed_date.isoformat(), "status_ed": "Active"}]
    rows_date = [{"id": 1, "tanggal_ed": ed_date, "status_ed": "Active"}]
    items_str = critical_ed_items(rows_str, today)
    items_date = critical_ed_items(rows_date, today)
    assert len(items_str) == 1 and len(items_date) == 1
    assert items_str[0]["days_remaining"] == items_date[0]["days_remaining"] == 100
    print("[OK] date object vs string: sama")


def test_ed_batch_dimusnahkan_filtered():
    """Status Dimusnahkan: di-filter di sisi Python (critical_ed_items)."""
    today = date(2026, 11, 13)
    ed_date = today + timedelta(days=50)
    rows = [
        {"id": 1, "tanggal_ed": ed_date.isoformat(), "status_ed": "Dimusnahkan"},
        {"id": 2, "tanggal_ed": ed_date.isoformat(), "status_ed": "Active"},
    ]
    items = critical_ed_items(rows, today)
    assert len(items) == 1, "Dimusnahkan harus terfilter"
    assert items[0]["id"] == 2
    print("[OK] Dimusnahkan: terfilter di sisi Python")


def test_ed_batch_embed_list():
    """Embed raw_materials sebagai list (supabase-py): di-handle."""
    today = date(2026, 11, 13)
    ed_date = today + timedelta(days=50)
    rows = [{
        "id": 1,
        "tanggal_ed": ed_date.isoformat(),
        "status_ed": "Active",
        "raw_materials": [{"nama_dagang": "Bahan X", "kode_bahan_baku": "BX-001"}],
    }]
    items = critical_ed_items(rows, today)
    assert len(items) == 1
    assert items[0]["nama_dagang"] == "Bahan X"
    print("[OK] embed list: di-handle")


def test_ed_batch_null_status_ed():
    """status_ed NULL kini termasuk (fallback Active)."""
    today = date(2026, 11, 13)
    ed_date = today + timedelta(days=50)
    rows = [{"id": 1, "tanggal_ed": ed_date.isoformat(), "status_ed": None}]
    items = critical_ed_items(rows, today)
    assert len(items) == 1, "NULL status_ed kini termasuk (fallback Active)"
    assert items[0]["status_ed"] == "Kritis (<= 180 hari)"
    print("[OK] NULL status_ed: termasuk (perubahan disengaja, lebih inklusif)")


def test_ed_batch_180_boundary_inclusive():
    """Batas 180 hari: days==180 termasuk, days==181 tidak."""
    today = date(2026, 11, 13)
    ed_180 = (today + timedelta(days=180)).isoformat()
    ed_181 = (today + timedelta(days=181)).isoformat()
    rows = [
        {"id": 1, "tanggal_ed": ed_180, "status_ed": "Active"},
        {"id": 2, "tanggal_ed": ed_181, "status_ed": "Active"},
    ]
    items = critical_ed_items(rows, today)
    assert len(items) == 1, "Hanya 180 hari yang masuk"
    assert items[0]["id"] == 1
    print("[OK] batas 180: inklusif (180 masuk, 181 tidak)")


def test_product_akan_expired():
    """Produk NA akan_expired: dihitung."""
    compute = _make_compute_status_na()
    rows = [{"id": 1, "tanggal_aktif_na": "2024-04-01", "status_na": "aktif"}]
    items = critical_na_items(rows, compute)
    assert len(items) == 1, f"Harus 1 item, dapat {len(items)}"
    assert items[0]["status_na"] == "akan_expired"
    print("[OK] produk akan_expired (dari tanggal_aktif_na): dihitung")


def test_product_expired():
    """Produk NA sudah expired: dihitung."""
    compute = _make_compute_status_na()
    rows = [{"id": 1, "tanggal_aktif_na": "2023-01-01", "status_na": "aktif"}]
    items = critical_na_items(rows, compute)
    assert len(items) == 1
    assert items[0]["status_na"] == "expired"
    print("[OK] produk expired: dihitung")


def test_product_aktif():
    """Produk NA masih aktif: tidak dihitung."""
    compute = _make_compute_status_na()
    rows = [{"id": 1, "tanggal_aktif_na": "2026-01-01", "status_na": "aktif"}]
    items = critical_na_items(rows, compute)
    assert len(items) == 0, f"Harus 0 item, dapat {len(items)}"
    print("[OK] produk aktif: tidak dihitung")


def test_product_tanggal_kosong():
    """Produk tanggal_aktif_na kosong: fallback ke status_na manual."""
    compute = _make_compute_status_na()
    rows = [{"id": 1, "tanggal_aktif_na": None, "status_na": "expired"}]
    items = critical_na_items(rows, compute)
    assert len(items) == 1
    rows2 = [{"id": 2, "tanggal_aktif_na": None, "status_na": "aktif"}]
    items2 = critical_na_items(rows2, compute)
    assert len(items2) == 0
    print("[OK] tanggal kosong: fallback status_na manual")


# =====================================================================
# Bagian 3: ED query builder (PostgREST regression)
# =====================================================================


def _client() -> SyncPostgrestClient:
    return SyncPostgrestClient(_DUMMY_URL)


def _query_string(q) -> str:
    r = getattr(q, "request", None)
    if r is not None and getattr(r, "params", None):
        return str(r.params)
    return str(q)


def test_batch_query_filters_present():
    """Query batch punya filter status_ed neq + tanggal_ed lte + order id + range."""
    client = _client()
    cutoff = "2027-05-13"
    q = build_ed_batch_query(client.table("raw_material_batches"), cutoff, offset=0)
    qs = _query_string(q)
    assert "status_ed" in qs and "Dimusnahkan" in qs, f"filter status_ed hilang: {qs}"
    assert "lte" in qs and cutoff in qs, f"filter tanggal_ed lte hilang: {qs}"
    assert "order" in qs and "id" in qs, f"order id hilang: {qs}"
    assert "offset" in qs or "limit" in qs or "range" in qs, f"range hilang: {qs}"
    print(f"[OK] query batch: {qs}")


def test_batch_query_no_notmethod():
    """REGRESI: rantai query TIDAK memakai method tak valid (.not_())."""
    client = _client()
    cutoff = "2027-05-13"
    q = build_ed_batch_query(client.table("raw_material_batches"), cutoff, offset=0)
    assert hasattr(q, "execute"), "hasil build bukan request builder"
    qs = _query_string(q)
    assert "not." not in qs and "not&" not in qs, f"metode tak valid .not_() terdeteksi: {qs}"
    print("[OK] query batch: tidak memakai method tak valid (.not_())")


def test_product_query_filters_present():
    """Query product: order id + range, TANPA filter status_na."""
    client = _client()
    q = build_ed_product_query(client.table("products"), offset=0)
    qs = _query_string(q)
    pairs = urllib.parse.parse_qsl(qs, keep_blank_values=True)
    filters = {k: v for k, v in pairs if k != "select"}
    assert "status_na" not in filters, f"filter status_na tidak boleh ada: {filters}"
    assert "order" in qs and "id" in qs, f"order id hilang: {qs}"
    assert "offset" in qs or "limit" in qs or "range" in qs, f"range hilang: {qs}"
    select_vals = [v for k, v in pairs if k == "select"]
    assert any("status_na" in s for s in select_vals), "status_na harus di select"
    print(f"[OK] query product: {qs}")


def test_extra_select_endpoint_variant():
    """Variasi endpoint: extra_select menambah raw_material_id + embed."""
    client = _client()
    cutoff = "2027-05-13"
    q = build_ed_batch_query(
        client.table("raw_material_batches"),
        cutoff,
        offset=0,
        extra_select="raw_material_id, raw_materials(nama_dagang, kode_bahan_baku)",
    )
    qs = _query_string(q)
    assert "raw_material_id" in qs, f"raw_material_id tidak termuat: {qs}"
    assert "raw_materials" in qs, f"embed raw_materials tidak termuat: {qs}"
    print(f"[OK] query endpoint: {qs}")


ALL_TESTS = [
    test_paginate_all_empty,
    test_paginate_all_one_full_page,
    test_paginate_all_2500_rows,
    test_paginate_all_last_page_exactly_full,
    test_paginate_all_custom_page_size,
    test_usage_counts_dedup_per_product,
    test_usage_counts_deleted_product_excluded,
    test_usage_counts_embed_as_list,
    test_usage_counts_embed_null_and_missing_fields,
    test_usage_counts_empty,
    test_capped_2500_rows_limit_1000,
    test_capped_total_exact_at_limit,
    test_capped_below_limit,
    test_capped_no_duplicates_across_pages,
    test_paginate_all_unchanged_behavior,
    test_ed_batch_exactly_180_days,
    test_ed_batch_181_days,
    test_ed_batch_zero_days,
    test_ed_batch_negative_days,
    test_ed_batch_null_date,
    test_ed_batch_date_object_vs_string,
    test_ed_batch_dimusnahkan_filtered,
    test_ed_batch_embed_list,
    test_ed_batch_null_status_ed,
    test_ed_batch_180_boundary_inclusive,
    test_product_akan_expired,
    test_product_expired,
    test_product_aktif,
    test_product_tanggal_kosong,
    test_batch_query_filters_present,
    test_batch_query_no_notmethod,
    test_product_query_filters_present,
    test_extra_select_endpoint_variant,
]


def main(reverse: bool = False) -> int:
    tests = list(reversed(ALL_TESTS)) if reverse else list(ALL_TESTS)
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if failed:
        print(f"\n{failed} dari {len(tests)} test pagination & ED GAGAL.")
        return 1
    print(f"\nSemua {len(tests)} test pagination & ED LULUS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
