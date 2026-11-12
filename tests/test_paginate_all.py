"""Unit test murni: app/pagination.py (paginate_all + usage_counts) untuk
badge "N Produk" di /raw-materials. Tanpa DB/network: fetch_page palsu.

Dijalankan: python tests/test_paginate_all.py (dengan PYTHONPATH=. seperti
di ci.yml).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pagination import paginate_all, usage_counts  # noqa: E402


class FakeSource:
    """Simulasi tabel N baris dengan page size tetap; rekam offset yang diminta."""

    def __init__(self, total_rows, page_size=1000):
        self.rows = [{"n": i} for i in range(total_rows)]
        self.page_size = page_size
        self.offsets = []

    def fetch(self, offset):
        self.offsets.append(offset)
        return self.rows[offset:offset + self.page_size]


# ---------- paginate_all ----------

def test_paginate_all_empty():
    src = FakeSource(0)
    out = paginate_all(src.fetch)
    assert out == []
    assert src.offsets == [0]  # 1 fetch (halaman kosong), lalu berhenti


def test_paginate_all_one_full_page():
    src = FakeSource(1000)
    out = paginate_all(src.fetch)
    assert len(out) == 1000
    # Halaman penuh -> fetch satu kali lagi (kosong) untuk memastikan akhir.
    assert src.offsets == [0, 1000]


def test_paginate_all_2500_rows():
    src = FakeSource(2500)
    out = paginate_all(src.fetch)
    assert len(out) == 2500
    assert out == src.rows
    assert src.offsets == [0, 1000, 2000]  # 3 halaman, halaman terakhir 500


def test_paginate_all_last_page_exactly_full():
    # Total kelipatan page_size: halaman terakhir PAS 1000 -> perlu fetch
    # keempat (kosong) untuk berhenti.
    src = FakeSource(3000)
    out = paginate_all(src.fetch)
    assert len(out) == 3000
    assert src.offsets == [0, 1000, 2000, 3000]


def test_paginate_all_custom_page_size():
    src = FakeSource(5, page_size=2)

    def fetch(offset):
        return src.rows[offset:offset + 2]

    out = paginate_all(fetch, page_size=2)
    assert out == src.rows  # [2,2,1] -> berhenti di halaman pendek


# ---------- usage_counts ----------

def _ln(rm, prod, embed):
    return {"raw_material_id": rm, "product_id": prod, "products": embed}


def test_usage_counts_dedup_per_product():
    rows = [
        _ln("rm1", "p1", {"is_deleted": False}),
        _ln("rm1", "p1", {"is_deleted": False}),  # duplikat produk -> tetap 1
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
        _ln("rm1", "p2", [{"is_deleted": True}]),   # list berisi deleted -> skip
        _ln("rm1", "p3", []),                          # list kosong -> hitung
    ]
    assert usage_counts(rows) == {"rm1": 2}


def test_usage_counts_embed_null_and_missing_fields():
    rows = [
        _ln("rm1", "p1", None),                        # embed null -> dianggap aktif
        {"product_id": "p2", "products": None},        # tanpa raw_material_id -> skip
        {"raw_material_id": "rm1", "products": None},  # tanpa product_id -> skip
    ]
    assert usage_counts(rows) == {"rm1": 1}


def test_usage_counts_empty():
    assert usage_counts([]) == {}
    assert usage_counts(None) == {}


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for _name, func in tests:
        func()
        print(f"[PASS] {func.__name__}")
    print(f"PASS {len(tests)} pemeriksaan pagination + usage_counts (murni, tanpa DB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
