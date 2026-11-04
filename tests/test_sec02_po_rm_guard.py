"""Pure-local tests untuk guard tenant SEC-02 (API PO + tulis raw-materials).

Tanpa jaringan: seluruh akses Supabase lewat fake yang mencatat query dan
TIDAK PERNAH mengirim permintaan; operasi tulis dicatat supaya tes bisa
menegaskan tidak ada tulis sebelum guard. Dijalankan CI sebagai
``python tests/test_sec02_po_rm_guard.py`` (runner ``main()`` di bawah).
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException  # noqa: E402

from app import po_routes, raw_materials_routes  # noqa: E402
from app.po_routes import register_po_routes  # noqa: E402
from app.raw_materials_routes import register_raw_materials_routes  # noqa: E402

STAFF_HEKA = {"id": "u-heka", "role": "staff", "perusahaan": "PT Heka"}
STAFF_ERFI = {"id": "u-erfi", "role": "staff", "perusahaan": "PT Erfi"}
ADMIN_ERFI = {"id": "u-admin", "role": "admin", "perusahaan": "PT Erfi"}
STAFF_NO_COMPANY = {"id": "u-legacy", "role": "staff", "perusahaan": None}


class FakeQuery:
    def __init__(self, backend, table_name):
        self.backend = backend
        self.table_name = table_name
        self.filters = []

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def neq(self, key, value):
        self.filters.append(("neq", key, value))
        return self

    def ilike(self, *args):
        return self

    def is_(self, *args):
        return self

    def or_(self, *args):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, n):
        self.backend.limits.setdefault(self.table_name, []).append(n)
        return self

    def insert(self, payload):
        self.backend.writes.append(("insert", self.table_name, payload))
        return self

    def update(self, payload):
        self.backend.writes.append(("update", self.table_name, payload))
        return self

    def delete(self):
        self.backend.writes.append(("delete", self.table_name, None))
        return self

    def execute(self):
        # Simulasi gangguan DB: seluruh tabel (fail_tables) atau hanya pembacaan
        # ke-N pada tabel itu (fail_calls berisi pasangan (tabel, N) berbasis 1).
        count = self.backend.calls[self.table_name] = self.backend.calls.get(self.table_name, 0) + 1
        if (self.table_name in self.backend.fail_tables
                or (self.table_name, count) in self.backend.fail_calls):
            raise RuntimeError(f"simulated DB failure on {self.table_name} (call {count})")
        rows = list(self.backend.tables.get(self.table_name, []))
        for op, key, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(key) == value]
            elif op == "neq":
                rows = [r for r in rows if r.get(key) != value]
        return SimpleNamespace(data=rows)


class FakeSupabase:
    def __init__(self, tables=None, fail_tables=None, fail_calls=None):
        self.tables = tables or {}
        self.writes = []
        self.limits = {}
        self.calls = {}
        self.fail_tables = set(fail_tables or ())
        self.fail_calls = set(fail_calls or ())

    def table(self, name):
        return FakeQuery(self, name)


class FakeApp:
    def __init__(self):
        self.routes = {}

    def _register(self, method):
        def deco(path, **kwargs):
            def wrapper(fn):
                self.routes[(method, path)] = fn
                return fn
            return wrapper
        return deco

    def get(self, path, **kwargs):
        return self._register("GET")(path, **kwargs)

    def post(self, path, **kwargs):
        return self._register("POST")(path, **kwargs)


def build_po(w=None):
    w = w or FakeSupabase()
    app = FakeApp()
    register_po_routes(app, None, lambda *a, **k: None, None)
    po_routes.supabase = w
    return app, w


def build_rm(ensure_variant):
    w = FakeSupabase()
    app = FakeApp()
    logs = []

    def fake_log(*args, **kwargs):
        logs.append((args, kwargs))

    register_raw_materials_routes(
        app, None, fake_log, None, None, None, ensure_variant, None, None, None, None,
    )
    raw_materials_routes.supabase = w
    return app, w, logs


class FakeRequest:
    def __init__(self):
        self.headers = {}


class FakeFile:
    filename = "probe.pdf"

    async def read(self):
        return b""


def _json(resp):
    return json.loads(resp.body)


# --------------------------------------------------------------------------- #
# /api/po/products
# --------------------------------------------------------------------------- #
PRODUCTS = [
    {"id": "p1", "nama_produk": "Krim Heka", "no_na_produk": "NA-1", "perusahaan": "PT Heka", "is_deleted": False},
    {"id": "p2", "nama_produk": "Serum Erfi", "no_na_produk": "NA-2", "perusahaan": "PT Erfi", "is_deleted": False},
    {"id": "p3", "nama_produk": "Shared Katalog", "no_na_produk": "", "perusahaan": None, "is_deleted": False},
]


def test_po_products_staff_only_own_and_shared():
    app, _w = build_po(FakeSupabase({"products": PRODUCTS}))
    handler = app.routes[("GET", "/api/po/products")]
    out = asyncio.run(handler(q="", current_user=STAFF_HEKA))
    ids = {i["id"] for i in _json(out)["items"]}
    assert ids == {"p1", "p3"}, ids


def test_po_products_admin_sees_all():
    app, _w = build_po(FakeSupabase({"products": PRODUCTS}))
    handler = app.routes[("GET", "/api/po/products")]
    out = asyncio.run(handler(q="", current_user=ADMIN_ERFI))
    ids = {i["id"] for i in _json(out)["items"]}
    assert ids == {"p1", "p2", "p3"}, ids


def test_po_products_user_without_company_sees_all():
    app, _w = build_po(FakeSupabase({"products": PRODUCTS}))
    handler = app.routes[("GET", "/api/po/products")]
    out = asyncio.run(handler(q="", current_user=STAFF_NO_COMPANY))
    ids = {i["id"] for i in _json(out)["items"]}
    assert ids == {"p1", "p2", "p3"}, ids


# --------------------------------------------------------------------------- #
# /api/po/batches
# --------------------------------------------------------------------------- #
def _batches_handler(w):
    app, _ = build_po(w)
    return app.routes[("GET", "/api/po/batches")]


def test_po_batches_foreign_product_forbidden():
    w = FakeSupabase({
        "products": [{"id": "p2", "perusahaan": "PT Erfi"}],
        "product_batches": [{"id": "b1", "no_batch": "B-1", "product_id": "p2"}],
    })
    try:
        asyncio.run(_batches_handler(w)(product_id="p2", current_user=STAFF_HEKA))
    except HTTPException as exc:
        assert exc.status_code == 403, exc.status_code
    else:
        raise AssertionError("harusnya 403 untuk produk badan hukum lain")


def test_po_batches_own_product_ok():
    w = FakeSupabase({
        "products": [{"id": "p1", "perusahaan": "PT Heka"}],
        "product_batches": [{"id": "b1", "no_batch": "B-1", "product_id": "p1"}],
    })
    out = asyncio.run(_batches_handler(w)(product_id="p1", current_user=STAFF_HEKA))
    items = _json(out)["items"]
    assert [i["id"] for i in items] == ["b1"], items


def test_po_batches_unknown_product_empty_items():
    w = FakeSupabase({"products": [], "product_batches": []})
    out = asyncio.run(_batches_handler(w)(product_id="p-missing", current_user=STAFF_HEKA))
    assert _json(out)["items"] == []


# --------------------------------------------------------------------------- #
# POST /raw-materials/edit/{rm_id}
# --------------------------------------------------------------------------- #
def test_edit_raw_material_foreign_company_forbidden_no_writes():
    ensure_calls = []
    app, w, logs = build_rm(lambda rm_id, produsen: ensure_calls.append((rm_id, produsen)))
    w.tables["raw_materials"] = [
        {"id": "rm-erfi", "nama_dagang": "Bahan Erfi", "kode_bahan_baku": "K-ERFI",
         "perusahaan": "PT Erfi", "tipe": "single"},
    ]
    handler = app.routes[("POST", "/raw-materials/edit/{rm_id}")]
    try:
        asyncio.run(handler(
            request=None, rm_id="rm-erfi", nama_dagang="Bahan Erfi",
            kode_bahan_baku="K-ERFI", tipe="single", current_user=STAFF_HEKA,
        ))
    except HTTPException as exc:
        assert exc.status_code == 403, exc.status_code
    else:
        raise AssertionError("harusnya 403 untuk baris perusahaan lain")
    # Tidak boleh ada tulis apa pun sebelum guard (termasuk _ensure_default_variant).
    assert w.writes == [], w.writes
    assert ensure_calls == [], ensure_calls
    rejected = [kw for (args, kw) in logs if kw.get("outcome") == "rejected"]
    assert len(rejected) == 1, logs


def test_edit_raw_material_shared_row_passes_guard():
    # Baris tanpa perusahaan = fail-open disengaja: guard harus LOLOS. Dibuktikan
    # dengan handler berlanjut ke cek duplikat kode (400), bukan 403.
    ensure_calls = []
    app, w, _logs = build_rm(lambda rm_id, produsen: ensure_calls.append((rm_id, produsen)))
    w.tables["raw_materials"] = [
        {"id": "rm-shared", "nama_dagang": "Bahan Katalog", "kode_bahan_baku": "DUP",
         "perusahaan": None, "tipe": "single"},
        {"id": "rm-lain", "nama_dagang": "Bahan Lain", "kode_bahan_baku": "DUP",
         "perusahaan": "PT Erfi", "tipe": "single"},
    ]
    handler = app.routes[("POST", "/raw-materials/edit/{rm_id}")]
    try:
        asyncio.run(handler(
            request=None, rm_id="rm-shared", nama_dagang="Bahan Katalog",
            kode_bahan_baku="DUP", tipe="single", current_user=STAFF_HEKA,
        ))
    except HTTPException as exc:
        assert exc.status_code == 400, f"harusnya lolos guard lalu 400 duplikat, dapat {exc.status_code}"
    else:
        raise AssertionError("cek duplikat kode seharusnya menolak dengan 400")
    assert ensure_calls == [], ensure_calls


def test_acc_dipakai_foreign_batch_forbidden_before_update():
    app, w, logs = build_rm(lambda *_args: None)
    w.tables.update({
        "raw_material_batches": [{"id": "b-erfi", "perusahaan": "PT Erfi",
                                  "raw_materials": {"perusahaan": "PT Erfi"}}],
    })
    handler = app.routes[("POST", "/raw-materials/batches/acc-dipakai")]
    try:
        asyncio.run(handler(request=FakeRequest(), batch_id="b-erfi", new_expiry_date="2030-01-01",
                             new_status_ed="ACC Dipakai", catatan_qc="ok", current_user=STAFF_HEKA))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("foreign ACC batch harus 403")
    assert w.writes == []
    assert any(kwargs.get("outcome") == "rejected" for _args, kwargs in logs)


def test_acc_dimusnahkan_foreign_batch_forbidden_before_update():
    app, w, logs = build_rm(lambda *_args: None)
    w.tables.update({
        "raw_material_batches": [{"id": "b-erfi", "perusahaan": "PT Erfi",
                                  "raw_materials": {"perusahaan": "PT Erfi"}}],
    })
    handler = app.routes[("POST", "/raw-materials/batches/acc-dimusnahkan")]
    try:
        asyncio.run(handler(request=FakeRequest(), batch_id="b-erfi", catatan_qc="ok",
                             current_user=STAFF_HEKA))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("foreign dispose batch harus 403")
    assert w.writes == []
    assert any(kwargs.get("outcome") == "rejected" for _args, kwargs in logs)


def test_edit_batch_foreign_company_forbidden_before_upload():
    app, w, logs = build_rm(lambda *_args: None)
    w.tables.update({
        "raw_material_batches": [{"id": "b-erfi", "no_batch": "B-1",
                                  "coa_file_url": None, "halal_batch_file_url": None,
                                  "qc_report_file_url": None, "perusahaan": "PT Erfi",
                                  "raw_materials": {"perusahaan": "PT Erfi"}}],
    })
    handler = app.routes[("POST", "/raw-materials/batches/edit/{batch_id}")]
    try:
        asyncio.run(handler(
            request=FakeRequest(), batch_id="b-erfi", no_batch="B-1", supplier="S",
            tanggal_terima_sampel="2026-01-01", tanggal_ed="2027-01-01", kesimpulan="ok",
            asal_negara=None, nama_produsen=None, coa_file=FakeFile(), halal_file=FakeFile(),
            qc_report_file=FakeFile(), quantity=None, quantity_unit=None, keterangan=None,
            current_user=STAFF_HEKA,
        ))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("foreign batch edit harus 403")
    assert w.writes == []
    assert any(kwargs.get("outcome") == "rejected" for _args, kwargs in logs)


def test_add_batch_foreign_parent_forbidden_before_upload_or_insert():
    app, w, logs = build_rm(lambda *_args: None)
    w.tables["raw_materials"] = [{"id": "rm-erfi", "nama_dagang": "Bahan Erfi",
                                  "perusahaan": "PT Erfi"}]
    uploads = []
    old_upload = raw_materials_routes.object_store.upload_pdf
    raw_materials_routes.object_store.upload_pdf = lambda *args, **kwargs: uploads.append(args)
    handler = app.routes[("POST", "/raw-materials/batches/add")]
    try:
        try:
            asyncio.run(handler(
                request=FakeRequest(), raw_material_id="rm-erfi", no_batch="B-1", supplier="S",
                tanggal_terima_sampel="2026-01-01", tanggal_ed="2027-01-01", kesimpulan="ok",
                perusahaan="PT Erfi", asal_negara=None, nama_produsen=None,
                tanggal_sampling=None, qc_signer=None, qa_signer=None, qc_results="[]",
                harga_per_kg=1.0, coa_file=FakeFile(), halal_file=None, qc_report_file=None,
                quantity=None, quantity_unit=None, keterangan=None, current_user=STAFF_HEKA,
            ))
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("foreign parent batch create harus 403")
    finally:
        raw_materials_routes.object_store.upload_pdf = old_upload
    assert w.writes == []
    assert uploads == []
    assert any(kwargs.get("outcome") == "rejected" for _args, kwargs in logs)


def test_quick_upload_foreign_batch_forbidden_before_upload_or_write():
    app, w, logs = build_rm(lambda *_args: None)
    w.tables["raw_material_batches"] = [{
        "id": "b-erfi", "no_batch": "B-1", "perusahaan": "PT Erfi",
        "coa_file_url": None, "halal_batch_file_url": None, "qc_report_file_url": None,
        "raw_materials": {"nama_dagang": "Bahan Erfi", "perusahaan": "PT Erfi"},
    }]
    uploads = []
    old_upload = raw_materials_routes.object_store.upload_pdf
    raw_materials_routes.object_store.upload_pdf = lambda *args, **kwargs: uploads.append(args)
    handler = app.routes[("POST", "/raw-materials/batches/{batch_id}/quick-upload-doc")]
    try:
        try:
            asyncio.run(handler(request=FakeRequest(), batch_id="b-erfi", coa_file=FakeFile(),
                                 halal_file=None, qc_report_file=None, current_user=STAFF_HEKA))
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("foreign quick upload harus 403")
    finally:
        raw_materials_routes.object_store.upload_pdf = old_upload
    assert w.writes == []
    assert uploads == []
    assert any(kwargs.get("outcome") == "rejected" for _args, kwargs in logs)


def test_po_product_batch_foreign_product_forbidden_before_insert():
    app, w = build_po(FakeSupabase({"products": [{"id": "p2", "perusahaan": "PT Erfi", "is_deleted": False}]}))
    handler = app.routes[("POST", "/product-batches")]
    try:
        asyncio.run(handler(request=FakeRequest(), product_id="p2", no_batch="B-1",
                             tanggal_produksi=None, tanggal_ed=None, po_id=None,
                             current_user=STAFF_HEKA))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("foreign product batch harus 403")
    assert w.writes == []


def test_po_item_create_foreign_product_forbidden_before_insert():
    app, w = build_po(FakeSupabase({
        "purchase_orders": [{"id": "po1", "no_po": "PO-1"}],
        "products": [{"id": "p2", "perusahaan": "PT Erfi", "is_deleted": False}],
    }))
    handler = app.routes[("POST", "/purchase-orders/{po_id}/items")]
    try:
        asyncio.run(handler(request=FakeRequest(), po_id="po1", product_id="p2", product_batch_id="b2",
                             current_user=STAFF_HEKA))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("foreign PO item create harus 403")
    assert w.writes == []


def test_po_item_update_foreign_old_product_forbidden_before_update():
    app, w = build_po(FakeSupabase({
        "purchase_order_items": [{"id": "i1", "purchase_order_id": "po1", "product_id": "p2"}],
        "products": [{"id": "p2", "perusahaan": "PT Erfi"}],
    }))
    handler = app.routes[("POST", "/purchase-orders/{po_id}/items/{item_id}/update")]
    try:
        asyncio.run(handler(request=FakeRequest(), po_id="po1", item_id="i1", product_id="p1",
                             product_batch_id="b1", current_user=STAFF_HEKA))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("update item dengan produk lama foreign harus 403")
    assert w.writes == []


def test_po_item_update_foreign_new_product_forbidden_before_validation_or_update():
    app, w = build_po(FakeSupabase({
        "purchase_order_items": [{"id": "i1", "purchase_order_id": "po1", "product_id": "p1"}],
        "products": [
            {"id": "p1", "perusahaan": "PT Heka"},
            {"id": "p2", "perusahaan": "PT Erfi"},
        ],
    }))
    handler = app.routes[("POST", "/purchase-orders/{po_id}/items/{item_id}/update")]
    try:
        asyncio.run(handler(request=FakeRequest(), po_id="po1", item_id="i1", product_id="p2",
                             product_batch_id="b2", tanggal_catatan_batch="not-a-date",
                             current_user=STAFF_HEKA))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("produk baru foreign harus ditolak sebelum validasi tanggal")
    assert w.writes == []


def test_po_item_delete_foreign_product_forbidden_before_delete():
    app, w = build_po(FakeSupabase({
        "purchase_order_items": [{"id": "i1", "purchase_order_id": "po1", "product_id": "p2"}],
        "products": [{"id": "p2", "perusahaan": "PT Erfi"}],
    }))
    handler = app.routes[("POST", "/purchase-orders/{po_id}/items/{item_id}/delete")]
    try:
        asyncio.run(handler(request=FakeRequest(), po_id="po1", item_id="i1", current_user=STAFF_HEKA))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("delete item foreign harus 403")
    assert w.writes == []


def test_po_batches_missing_product_returns_empty_items():
    w = FakeSupabase({"products": [], "product_batches": [{"id": "orphan", "product_id": "missing"}]})
    out = asyncio.run(_batches_handler(w)(product_id="missing", current_user=STAFF_HEKA))
    assert _json(out)["items"] == []


# --------------------------------------------------------------------------- #
# Fail-closed: pembacaan produk/bahan baku yang GAGAL (exception) tidak boleh
# melewati guard. Baris yang tidak ditemukan tetap diperlakukan seperti dulu.
# --------------------------------------------------------------------------- #
_PO_ITEM_OPTIONAL_NONE = dict(
    tanggal_catatan_batch=None, wip=None, netto=None, qty_kg=None, keterangan=None,
    qty_belum_sop=None, qty_po_kg=None, status_bpom=None, catatan_produksi=None,
    revisi_produksi=None, temporary_reject=None,
)


def _assert_po_error_redirect(resp):
    # Pesan harus berasal dari guard ("memverifikasi"), bukan dari validasi lain
    # yang kebetulan menolak -- tanpa ini test lolos untuk alasan yang salah.
    assert resp.status_code == 303, resp.status_code
    location = resp.headers.get("location", "")
    assert "error=" in location and "success=" not in location, location
    assert "memverifikasi" in location, location


def test_po_item_update_old_product_lookup_failure_fails_closed():
    # Pembacaan products ke-1 (produk lama item, milik PT Erfi) gagal. Batch
    # cocok disediakan supaya tanpa guard fail-closed alur lama SAMPAI ke
    # update (dan menulis); test ini harus gagal pada kode lama.
    app, w = build_po(FakeSupabase({
        "purchase_order_items": [{"id": "i1", "purchase_order_id": "po1", "product_id": "p2"}],
        "products": [{"id": "p2", "perusahaan": "PT Erfi"}],
        "product_batches": [{"id": "b1", "product_id": "p2"}],
    }, fail_calls={("products", 1)}))
    handler = app.routes[("POST", "/purchase-orders/{po_id}/items/{item_id}/update")]
    resp = asyncio.run(handler(request=FakeRequest(), po_id="po1", item_id="i1", product_id="p2",
                                product_batch_id="b1", current_user=STAFF_HEKA,
                                **_PO_ITEM_OPTIONAL_NONE))
    _assert_po_error_redirect(resp)
    assert w.writes == []


def test_po_item_update_new_product_lookup_failure_fails_closed():
    # Produk lama terbaca (milik sendiri); pembacaan products ke-2 (produk baru,
    # milik PT Erfi) gagal. Batch cocok disediakan: tanpa fail-closed, item akan
    # dipindahkan ke produk perusahaan lain (test harus gagal pada kode lama).
    app, w = build_po(FakeSupabase({
        "purchase_order_items": [{"id": "i1", "purchase_order_id": "po1", "product_id": "p1"}],
        "products": [{"id": "p1", "perusahaan": "PT Heka"}, {"id": "p2", "perusahaan": "PT Erfi"}],
        "product_batches": [{"id": "b2", "product_id": "p2"}],
    }, fail_calls={("products", 2)}))
    handler = app.routes[("POST", "/purchase-orders/{po_id}/items/{item_id}/update")]
    resp = asyncio.run(handler(request=FakeRequest(), po_id="po1", item_id="i1", product_id="p2",
                                product_batch_id="b2", current_user=STAFF_HEKA,
                                **_PO_ITEM_OPTIONAL_NONE))
    _assert_po_error_redirect(resp)
    assert w.writes == []


def test_po_item_delete_product_lookup_failure_fails_closed():
    app, w = build_po(FakeSupabase({
        "purchase_order_items": [{"id": "i1", "purchase_order_id": "po1", "product_id": "p2"}],
        "products": [{"id": "p2", "perusahaan": "PT Erfi"}],
    }, fail_tables={"products"}))
    handler = app.routes[("POST", "/purchase-orders/{po_id}/items/{item_id}/delete")]
    resp = asyncio.run(handler(request=FakeRequest(), po_id="po1", item_id="i1", current_user=STAFF_HEKA))
    _assert_po_error_redirect(resp)
    assert w.writes == []


def test_po_item_delete_missing_product_row_keeps_previous_behavior():
    # Tidak ada exception, produk memang tidak ditemukan -> helper fail-open
    # (perilaku lama dipertahankan): hapus tetap berjalan.
    app, w = build_po(FakeSupabase({
        "purchase_order_items": [{"id": "i1", "purchase_order_id": "po1", "product_id": "gone"}],
        "products": [],
    }))
    handler = app.routes[("POST", "/purchase-orders/{po_id}/items/{item_id}/delete")]
    resp = asyncio.run(handler(request=FakeRequest(), po_id="po1", item_id="i1", current_user=STAFF_HEKA))
    assert resp.status_code == 303 and "success=" in resp.headers.get("location", "")
    assert ("delete", "purchase_order_items", None) in w.writes


def test_add_batch_parent_lookup_failure_fails_closed_before_upload_or_insert():
    app, w, logs = build_rm(lambda *_args: None)
    w.fail_tables = {"raw_materials"}
    uploads = []
    old_upload = raw_materials_routes.object_store.upload_pdf
    raw_materials_routes.object_store.upload_pdf = lambda *args, **kwargs: uploads.append(args)
    handler = app.routes[("POST", "/raw-materials/batches/add")]
    try:
        resp = asyncio.run(handler(
            request=FakeRequest(), raw_material_id="rm-erfi", no_batch="B-1", supplier="S",
            tanggal_terima_sampel="2026-01-01", tanggal_ed="2027-01-01", kesimpulan="ok",
            perusahaan="PT Heka", asal_negara=None, nama_produsen=None,
            tanggal_sampling=None, qc_signer=None, qa_signer=None, qc_results="[]",
            harga_per_kg=1.0, coa_file=FakeFile(), halal_file=None, qc_report_file=None,
            quantity=None, quantity_unit=None, keterangan=None, current_user=STAFF_HEKA,
        ))
    finally:
        raw_materials_routes.object_store.upload_pdf = old_upload
    assert resp.status_code == 303
    assert "error_msg" in resp.headers.get("set-cookie", "")
    assert w.writes == []
    assert uploads == []


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failures = []
    for name, func in tests:
        try:
            func()
        except Exception as exc:  # noqa: BLE001 - laporkan semua jenis kegagalan
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        return 1
    print(f"PASS {len(tests)} pemeriksaan guard tenant SEC-02 (PO + raw-materials)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
