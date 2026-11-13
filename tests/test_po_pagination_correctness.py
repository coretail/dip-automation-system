"""Test paginasi kebenaran data N-01/N-02 — memanggil kode nyata.

- app/pagination.py: paginate_all_capped (2500 baris, batas 1000 -> 1000 +
  truncated=True; total tepat di batas; di bawah batas -> False; urutan
  stabil, tanpa duplikat).
- app/ed_notifications.py: critical_ed_items + critical_na_items (tepat 180
  hari, 181 hari, 0 hari, -1 hari, tanggal null, format string vs date,
  produk akan_expired/expired/aktif/tanggal kosong).

Murni lokal, tanpa DB, tanpa DIP_APP_ENV.
Jalankan: python tests/test_po_pagination_correctness.py
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Set env dummy SEBELUM import app modules (pola ci.yml: SUPABASE_URL + key
# dummy; DIP_APP_ENV TIDAK diset).
import os
os.environ["SUPABASE_URL"] = "https://ci.invalid.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "ci-dummy-service-role-key"
os.environ["SUPABASE_KEY"] = "ci-dummy-anon-key"
os.environ["STORAGE_BACKEND"] = "supabase"

# Mock find_dotenv_files untuk mesin lokal yang punya file .env
# (di CI tidak ada file .env, mock tidak diperlukan).
import app.env_guard as env_guard
env_guard.find_dotenv_files = lambda: []

WIB = ZoneInfo("Asia/Jakarta")


class FakeSource:
    """Simulasi fetch_page atas N baris deterministik (urutan id naik)."""

    def __init__(self, total_rows, page_size=1000):
        self.rows = [{"id": i, "tanggal_po": "2026-01-01"} for i in range(total_rows)]
        self.page_size = page_size
        self.offsets = []

    def fetch(self, offset):
        self.offsets.append(offset)
        return self.rows[offset:offset + self.page_size]


# ---------- paginate_all_capped ----------

def test_capped_2500_rows_limit_1000():
    """2500 baris, max_rows=1000 -> 1000 baris + truncated=True."""
    from app.pagination import paginate_all_capped
    src = FakeSource(2500)
    rows, truncated = paginate_all_capped(src.fetch, page_size=1000, max_rows=1000)
    assert len(rows) == 1000, f"Harus 1000, dapat {len(rows)}"
    assert truncated is True, "Harus truncated (masih 1500 baris setelah batas)"
    # Urutan stabil, tanpa duplikat
    ids = [r["id"] for r in rows]
    assert ids == list(range(1000)), "Urutan harus stabil"
    assert len(ids) == len(set(ids)), "Tidak boleh ada duplikat"
    print("[OK] capped 2500/batas 1000: 1000 + truncated=True")


def test_capped_total_exact_at_limit():
    """Total TEPAT di batas (1000 baris, max_rows=1000) -> truncated=False."""
    from app.pagination import paginate_all_capped
    src = FakeSource(1000)
    rows, truncated = paginate_all_capped(src.fetch, page_size=1000, max_rows=1000)
    assert len(rows) == 1000
    assert truncated is False, "Data habis tepat di batas -> tidak truncated"
    print("[OK] total tepat di batas: truncated=False")


def test_capped_below_limit():
    """Di bawah batas (500 baris, max_rows=1000) -> 500 + truncated=False."""
    from app.pagination import paginate_all_capped
    src = FakeSource(500)
    rows, truncated = paginate_all_capped(src.fetch, page_size=1000, max_rows=1000)
    assert len(rows) == 500
    assert truncated is False
    print("[OK] di bawah batas: truncated=False")


def test_capped_no_duplicates_across_pages():
    """2500 baris dengan page_size=1000: semua 2500 terambil, tanpa duplikat."""
    from app.pagination import paginate_all_capped
    src = FakeSource(2500)
    rows, truncated = paginate_all_capped(src.fetch, page_size=1000, max_rows=5000)
    assert len(rows) == 2500
    assert truncated is False
    ids = [r["id"] for r in rows]
    assert ids == list(range(2500)), "Urutan harus stabil tanpa lompat"
    assert len(ids) == len(set(ids))
    print("[OK] 2500 baris tanpa batas: semua terambil, tanpa duplikat")


def test_paginate_all_unchanged_behavior():
    """paginate_all tanpa max_rows: perilaku lama tidak berubah (test_paginate_all.py)."""
    from app.pagination import paginate_all
    src = FakeSource(2500)
    out = paginate_all(src.fetch)
    assert len(out) == 2500
    assert out == src.rows
    print("[OK] paginate_all tanpa max_rows: perilaku lama tidak berubah")


# ---------- ed_notifications ----------

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
        # Sederhana untuk test: expired jika <= 180 hari dari tanggal aktif + 3 tahun
        today = date(2026, 11, 13)  # fixed "hari ini" untuk deterministik
        from datetime import date as _d
        import calendar
        # 3 tahun dari start
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
    from app.ed_notifications import critical_ed_items
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
    from app.ed_notifications import critical_ed_items
    today = date(2026, 11, 13)
    ed_date = today + timedelta(days=181)
    rows = [{"id": 1, "tanggal_ed": ed_date.isoformat(), "status_ed": "Active"}]
    items = critical_ed_items(rows, today)
    assert len(items) == 0, f"Harus 0 item, dapat {len(items)}"
    print("[OK] batch 181 hari: tidak kritis")


def test_ed_batch_zero_days():
    """Batch 0 hari (ED hari ini): termasuk, status Expired."""
    from app.ed_notifications import critical_ed_items
    today = date(2026, 11, 13)
    rows = [{"id": 1, "tanggal_ed": today.isoformat(), "status_ed": "Active"}]
    items = critical_ed_items(rows, today)
    assert len(items) == 1
    assert items[0]["days_remaining"] == 0
    assert items[0]["status_ed"] == "Expired"
    print("[OK] batch 0 hari: Expired")


def test_ed_batch_negative_days():
    """Batch -1 hari (ED kemarin): termasuk, status Expired."""
    from app.ed_notifications import critical_ed_items
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
    from app.ed_notifications import critical_ed_items
    today = date(2026, 11, 13)
    rows = [{"id": 1, "tanggal_ed": None, "status_ed": "Active"}]
    items = critical_ed_items(rows, today)
    assert len(items) == 0
    print("[OK] tanggal null: di-skip")


def test_ed_batch_date_object_vs_string():
    """tanggal_ed sebagai date object dan string ISO: sama hasilnya."""
    from app.ed_notifications import critical_ed_items
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
    from app.ed_notifications import critical_ed_items
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
    from app.ed_notifications import critical_ed_items
    today = date(2026, 11, 13)
    ed_date = today + timedelta(days=50)
    rows = [{
        "id": 1, "tanggal_ed": ed_date.isoformat(), "status_ed": "Active",
        "raw_materials": [{"nama_dagang": "Bahan X", "kode_bahan_baku": "BX-001"}],
    }]
    items = critical_ed_items(rows, today)
    assert len(items) == 1
    assert items[0]["nama_dagang"] == "Bahan X"
    print("[OK] embed list: di-handle")


def test_product_akan_expired():
    """Produk NA akan_expired (status_na manual 'aktif' tapi tanggal dekat): dihitung."""
    from app.ed_notifications import critical_na_items
    compute = _make_compute_status_na()
    # NA aktif 2024-04-01 -> expired 2027-04-01; today fixed 2026-11-13
    # days_remaining dari expired: ~139 hari -> akan_expired
    rows = [{"id": 1, "tanggal_aktif_na": "2024-04-01", "status_na": "aktif"}]
    items = critical_na_items(rows, compute)
    assert len(items) == 1, f"Harus 1 item, dapat {len(items)}"
    assert items[0]["status_na"] == "akan_expired"
    print("[OK] produk akan_expired (dari tanggal_aktif_na): dihitung")


def test_product_expired():
    """Produk NA sudah expired: dihitung."""
    from app.ed_notifications import critical_na_items
    compute = _make_compute_status_na()
    rows = [{"id": 1, "tanggal_aktif_na": "2023-01-01", "status_na": "aktif"}]
    items = critical_na_items(rows, compute)
    assert len(items) == 1
    assert items[0]["status_na"] == "expired"
    print("[OK] produk expired: dihitung")


def test_product_aktif():
    """Produk NA masih aktif: tidak dihitung."""
    from app.ed_notifications import critical_na_items
    compute = _make_compute_status_na()
    rows = [{"id": 1, "tanggal_aktif_na": "2026-01-01", "status_na": "aktif"}]
    items = critical_na_items(rows, compute)
    assert len(items) == 0, f"Harus 0 item, dapat {len(items)}"
    print("[OK] produk aktif: tidak dihitung")


def test_product_tanggal_kosong():
    """Produk tanggal_aktif_na kosong: fallback ke status_na manual."""
    from app.ed_notifications import critical_na_items
    compute = _make_compute_status_na()
    # status_na manual "expired" -> dihitung
    rows = [{"id": 1, "tanggal_aktif_na": None, "status_na": "expired"}]
    items = critical_na_items(rows, compute)
    assert len(items) == 1
    # status_na manual "aktif" -> tidak dihitung
    rows2 = [{"id": 2, "tanggal_aktif_na": None, "status_na": "aktif"}]
    items2 = critical_na_items(rows2, compute)
    assert len(items2) == 0
    print("[OK] tanggal kosong: fallback status_na manual")


def test_ed_batch_null_status_ed():
    """status_ed NULL: perilaku lama .neq('status_ed','Dimusnahkan') di PostgREST
    mengeksklusi baris NULL dari hasil (NULL <> 'x' = NULL, bukan TRUE).
    critical_ed_items tidak mengeksklusi NULL (fallback 'Active'), jadi badge
    kini termasuk batch yang status_ed-nya NULL. Perubahan disengaja:
    lebih inklusif (dulu terlewat karena SQL semantik NULL)."""
    from app.ed_notifications import critical_ed_items
    today = date(2026, 11, 13)
    ed_date = today + timedelta(days=50)
    rows = [{"id": 1, "tanggal_ed": ed_date.isoformat(), "status_ed": None}]
    items = critical_ed_items(rows, today)
    assert len(items) == 1, "NULL status_ed kini termasuk (fallback Active)"
    assert items[0]["status_ed"] == "Kritis (<= 180 hari)"
    print("[OK] NULL status_ed: termasuk (perubahan disengaja, lebih inklusif)")


def test_ed_batch_180_boundary_inclusive():
    """Batas 180 hari: days==180 termasuk, days==181 tidak."""
    from app.ed_notifications import critical_ed_items
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


def main():
    tests = [
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
    ]
    for test in tests:
        test()
        print(f"  -> {test.__name__}")
    print(f"\nSemua {len(tests)} test pagination correctness lulus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
