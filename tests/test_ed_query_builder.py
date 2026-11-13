"""Regresi: query builder ED memakai method postgrest yang valid.

Membangun query yang BENAR-BENAR dipakai produksi (via
app.ed_notifications.build_ed_batch_query / build_ed_product_query) dengan
SyncPostgrestClient URL dummy TANPA .execute(). Tujuannya: bila ada method
tak valid di rantai query (mis. .not_() yang melempar TypeError/AttributeError
karena not_ adalah PROPERTY di postgrest 2.31.0), test ini MERAH — sedangkan
di runtime error itu tertelan except dan badge diam-diam 0.

Murni lokal, tanpa jaringan, tanpa DIP_APP_ENV.
Jalankan: python tests/test_ed_query_builder.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from postgrest import SyncPostgrestClient
from app.ed_notifications import build_ed_batch_query, build_ed_product_query

_DUMMY_URL = "https://ci.invalid/rest/v1"


def _client() -> SyncPostgrestClient:
    """Client dummy tanpa jaringan (tanpa .execute)."""
    return SyncPostgrestClient(_DUMMY_URL)


def _query_string(q) -> str:
    """Kembalikan query string (params) dari request builder postgrest."""
    # postgrest 2.31.0 menyimpan filter di q.request.params (string "a=op.b&...")
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
    """REGRESI: rantai query TIDAK memakai method tak valid (.not_()).

    Postgrest 2.31.0: not_ adalah PROPERTY. build_ed_batch_query tidak boleh
    memanggil .not_() (method) karena melempar AttributeError/TypeError yang
    tertelan except di runtime -> badge 0. Test ini memastikan build bersih.
    """
    client = _client()
    cutoff = "2027-05-13"
    q = build_ed_batch_query(client.table("raw_material_batches"), cutoff, offset=0)
    assert hasattr(q, "execute"), "hasil build bukan request builder"
    qs = _query_string(q)
    # JANGAN ada param "not" (yang akan muncul jika .not_() dipanggil)
    assert "not." not in qs and "not&" not in qs, f"metode tak valid .not_() terdeteksi: {qs}"
    print("[OK] query batch: tidak memakai method tak valid (.not_())")


def test_product_query_filters_present():
    """Query product: order id + range, TANPA filter status_na.

    status_na WAJIB ada di select (dipakai compute_status_na fallback), tapi
    TIDAK BOLEH ada di filter (mis. status_na=in.(...). Cek di query string:
    status_na hanya boleh muncul di select=, bukan sebagai parameter filter.
    """
    client = _client()
    q = build_ed_product_query(client.table("products"), offset=0)
    qs = _query_string(q)
    # Pisah parameter query (setelah & pertama = filter, kecuali select)
    import urllib.parse
    pairs = urllib.parse.parse_qsl(qs, keep_blank_values=True)
    filters = {k: v for k, v in pairs if k != "select"}
    assert "status_na" not in filters, f"filter status_na tidak boleh ada: {filters}"
    assert "order" in qs and "id" in qs, f"order id hilang: {qs}"
    assert "offset" in qs or "limit" in qs or "range" in qs, f"range hilang: {qs}"
    # select WAJIB memuat status_na (untuk fallback compute_status_na)
    select_vals = [v for k, v in pairs if k == "select"]
    assert any("status_na" in s for s in select_vals), "status_na harus di select"
    print(f"[OK] query product: {qs}")


def test_extra_select_endpoint_variant():
    """Variasi endpoint: extra_select menambah raw_material_id + embed."""
    client = _client()
    cutoff = "2027-05-13"
    q = build_ed_batch_query(
        client.table("raw_material_batches"), cutoff, offset=0,
        extra_select="raw_material_id, raw_materials(nama_dagang, kode_bahan_baku)",
    )
    qs = _query_string(q)
    assert "raw_material_id" in qs, f"raw_material_id tidak termuat: {qs}"
    assert "raw_materials" in qs, f"embed raw_materials tidak termuat: {qs}"
    print(f"[OK] query endpoint: {qs}")


def main():
    tests = [
        test_batch_query_filters_present,
        test_batch_query_no_notmethod,
        test_product_query_filters_present,
        test_extra_select_endpoint_variant,
    ]
    for test in tests:
        test()
        print(f"  -> {test.__name__}")
    print(f"\nSemua {len(tests)} test ED query builder lulus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
