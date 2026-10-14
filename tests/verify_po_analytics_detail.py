"""Verifikasi tabel rincian analytics PO tanpa koneksi database.

Jalankan dari root repo:
    python tests\verify_po_analytics_detail.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.po_routes import _build_po_analytics


results = []


def check(name, condition, extra=""):
    ok = bool(condition)
    print(("  OK   " if ok else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    results.append(ok)
    return ok


POS = [
    {"id": "po-1", "no_po": "PO-1", "tanggal_po": "2026-01-10", "qty_pcs": 100},
    {"id": "po-2", "no_po": "PO-2", "tanggal_po": "2026-02-10", "qty_pcs": 50},
    {"id": "po-3", "no_po": "PO-3", "tanggal_po": "2026-07-10", "qty_pcs": 30},
    {"id": "po-r", "no_po": "PO-R", "tanggal_po": "2026-03-10", "qty_pcs": 40, "jenis_po": "Rework"},
]

ITEMS = [
    {"purchase_order_id": "po-1", "product_id": "p-a"},
    {"purchase_order_id": "po-1", "product_id": "p-b"},
    {"purchase_order_id": "po-1", "product_id": "p-c"},
    {"purchase_order_id": "po-2", "product_id": "p-a"},
    {"purchase_order_id": "po-3", "product_id": "p-c"},
    {"purchase_order_id": "po-r", "product_id": "p-a"},
]

PRODUCTS = [
    {"id": "p-a", "nama_produk": "beta", "perusahaan": "PT Erfi", "is_deleted": False,
     "brand_id": "brand-1", "brand": "Brand Sama", "laporan_uji_sig_file_url": None},
    {"id": "p-b", "nama_produk": "Alpha", "perusahaan": "PT Erfi", "is_deleted": False,
     "brand_id": "brand-1", "brand": "Brand Sama", "laporan_uji_sig_file_url": None},
    {"id": "p-c", "nama_produk": "Gamma", "perusahaan": "PT Heka", "is_deleted": False,
     "brand_id": "brand-2", "brand": "Brand Sama", "laporan_uji_sig_file_url": None},
    {"id": "p-none", "nama_produk": "No Brand", "perusahaan": "PT Heka", "is_deleted": False,
     "brand_id": None, "brand": None, "laporan_uji_sig_file_url": None},
    {"id": "p-zero", "nama_produk": "alpha zero", "perusahaan": "PT Heka", "is_deleted": False,
     "brand_id": None, "brand": None, "laporan_uji_sig_file_url": None},
    {"id": "p-zero2", "nama_produk": "Beta zero", "perusahaan": "PT Heka", "is_deleted": False,
     "brand_id": None, "brand": None, "laporan_uji_sig_file_url": None},
    {"id": "p-deleted", "nama_produk": "Deleted", "perusahaan": "PT Erfi", "is_deleted": True,
     "brand_id": "brand-3", "brand": "Hidden", "laporan_uji_sig_file_url": None},
]


def main():
    ana = _build_po_analytics(POS, ITEMS, PRODUCTS, 2026, sort="pcs")
    all_products = ana["detail"]["all"]["produk"]
    all_brands = ana["detail"]["all"]["merek"]
    by_product = {row["id"]: row for row in all_products}
    same_name_brands = [row for row in all_brands if row["nama"] == "Brand Sama"]

    check("semua produk aktif termasuk 0 PO", {r["id"] for r in all_products} == {"p-a", "p-b", "p-c", "p-none", "p-zero", "p-zero2"})
    check("produk mendapat qty penuh dari setiap PO unik", by_product["p-a"]["pcs"] == 150)
    check("brand id berbeda tetap menghasilkan dua agregat walau nama sama", len(same_name_brands) == 2)
    check("dua produk satu merek tidak menggandakan qty merek", sorted(r["pcs"] for r in same_name_brands) == [130, 150])
    check("po_count merek memakai union PO", sorted(r["po_count"] for r in same_name_brands) == [2, 3])
    check("brand tanpa id masuk bucket Tanpa merek", any(r["nama"] == "(Tanpa merek)" for r in all_brands))
    check("po rework dihitung di po_count", by_product["p-a"]["po_count"] == 3)
    check("po rework tidak dihitung di pcs", by_product["p-a"]["pcs"] == 150)

    erfi = ana["detail"]["erfi"]
    heka = ana["detail"]["heka"]
    check("tab Erfi hanya memuat produk Erfi", all(r["company"] == "PT Erfi" for r in erfi["produk"]))
    check("tab Heka hanya memuat produk Heka", all(r["company"] == "PT Heka" for r in heka["produk"]))

    q1 = _build_po_analytics(POS, ITEMS, PRODUCTS, 2026, qtr=1, sort="pcs")
    q1_ids = {r["id"] for r in q1["detail"]["all"]["produk"] if r["po_count"]}
    check("filter kuartal membatasi PO produk", q1_ids == {"p-a", "p-b", "p-c"})

    po_order = _build_po_analytics(POS, ITEMS, PRODUCTS, 2026, sort="po")["detail"]["all"]["produk"]
    check("sort po mengubah basis urutan", po_order[0]["po_count"] >= po_order[-1]["po_count"])
    zero_names = [r["nama"] for r in all_products if r["po_count"] == 0]
    check("tie-breaker nama case-insensitive", zero_names.index("alpha zero") < zero_names.index("Beta zero"))

    print()
    print(f"{'PASS' if all(results) else 'FAIL'}: {sum(results)}/{len(results)} pemeriksaan")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
