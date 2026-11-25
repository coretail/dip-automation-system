"""Pure-local tests gabungan untuk seluruh guard tenant (Task 3 refactor test).

Menggabungkan empat file lama tanpa mengurangi satu pun fungsi/assertion:
  - test_sec02_po_rm_guard.py          -> SEC-02 API PO + tulis raw-materials (24 fungsi, 52 assert)
  - test_tenant_guard_efek_lampiran.py -> efek samping & lampiran produk A-11/A-12 (10 fungsi, 15 assert)
  - test_tenant_guard_finished_spec.py -> POST /products/{id}/finished-spec A-10 (5 fungsi, 8 assert)
  - test_tenant_guard_sample.py        -> sample/FSP A-13 (6 fungsi, 10 assert)

Tanpa jaringan: seluruh akses Supabase lewat fake yang mencatat query/tulis.
Runner ``main()`` memulihkan atribut ``.supabase`` modul rute setelah setiap test.

Dijalankan: python tests/test_tenant_guards.py
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

from _fakes import FakeApp, FakeRequest  # noqa: E402
from app import (  # noqa: E402
    efek_samping,
    po_routes,
    product_attachments_routes,
    products_routes,
    raw_materials_routes,
    sample_routes,
)
from app.efek_samping import register_efek_samping_routes  # noqa: E402
from app.po_routes import register_po_routes  # noqa: E402
from app.product_attachments_routes import register_product_attachment_routes  # noqa: E402
from app.products_routes import register_products_routes  # noqa: E402
from app.raw_materials_routes import register_raw_materials_routes  # noqa: E402
from app.sample_routes import register_sample_routes  # noqa: E402

STAFF_HEKA = {"id": "u-heka", "role": "staff", "perusahaan": "PT Heka"}
STAFF_ERFI = {"id": "u-erfi", "role": "staff", "perusahaan": "PT Erfi"}
ADMIN_ERFI = {"id": "u-admin", "role": "admin", "perusahaan": "PT Erfi"}
ADMIN_HEKA = {"id": "u-admin", "role": "admin", "perusahaan": "PT Heka"}
STAFF_NO_COMPANY = {"id": "u-legacy", "role": "staff", "perusahaan": None}

PRODUCT_ID = "00000000-0000-0000-0000-0000000000aa"
ATT_ID = "00000000-0000-0000-0000-0000000000bb"
PID = "00000000-0000-0000-0000-0000000000aa"
SID = "00000000-0000-0000-0000-0000000000aa"
SAMPLE_PID = "00000000-0000-0000-0000-0000000000bb"


class FakeQuery:
    def __init__(self, backend, table_name):
        self.backend = backend
        self.table_name = table_name
        self.filters = []
        self._insert_payload = None
        self._single = False

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

    def gte(self, *args):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, n):
        self.backend.limits.setdefault(self.table_name, []).append(n)
        return self

    def single(self):
        self._single = True
        return self

    def insert(self, payload):
        self.backend.writes.append(("insert", self.table_name, payload))
        self._insert_payload = payload
        return self

    def update(self, payload):
        self.backend.writes.append(("update", self.table_name, payload))
        return self

    def delete(self):
        self.backend.writes.append(("delete", self.table_name, None))
        return self

    def execute(self):
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
        if self._single:
            data = rows[0] if rows else None
        elif self._insert_payload is not None:
            data = [{"id": "new-id", **self._insert_payload}]
        else:
            data = rows
        return SimpleNamespace(data=data)


class FakeSupabase:
    def __init__(self, tables=None, fail_tables=None, fail_calls=None):
        self.tables = tables or {}
        self.writes = []
        self.limits = {}
        self.calls = {}
        self.fail_tables = set(fail_tables or ())
        norm_fail_calls = set()
        if isinstance(fail_calls, dict):
            for tbl, counts in fail_calls.items():
                for cnt in counts:
                    norm_fail_calls.add((tbl, cnt))
        elif fail_calls:
            norm_fail_calls = set(fail_calls)
        self.fail_calls = norm_fail_calls

    def table(self, name):
        return FakeQuery(self, name)


class FakeFile:
    filename = "probe.pdf"

    async def read(self):
        return b""


def _json(resp):
    return json.loads(resp.body)


def _status(resp):
    return getattr(resp, "status_code", None)


def _product(perusahaan="PT Erfi"):
    return {
        "id": PRODUCT_ID,
        "nama_produk": "Produk Erfi",
        "perusahaan": perusahaan,
        "is_deleted": False,
        "monitoring_efek_samping_file_url": None,
        "last_efek_samping_period": None,
    }


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


def build_efek(tables=None, fail_tables=None, fail_calls=None):
    w = FakeSupabase(tables=tables, fail_tables=fail_tables, fail_calls=fail_calls)
    app = FakeApp()
    logs = []
    register_efek_samping_routes(
        app,
        get_current_user=lambda: STAFF_ERFI,
        templates=type("T", (), {"env": SimpleNamespace(get_template=lambda _: SimpleNamespace(render=lambda _: ""))})(),
        supabase=w,
        get_company_info=lambda p: {"name": p},
        format_date_id=lambda d: "01-01-2026",
        log_activity=lambda *a, **k: logs.append((a, k)),
        pdf_link_callback=lambda _: None,
    )
    efek_samping.supabase = w
    return app, w, logs


def build_att(tables=None, fail_tables=None):
    w = FakeSupabase(tables=tables, fail_tables=fail_tables)
    app = FakeApp()
    logs = []
    register_product_attachment_routes(
        app,
        get_current_user=lambda: STAFF_ERFI,
        log_activity=lambda *a, **k: logs.append((a, k)),
        templates=type("T", (), {"TemplateResponse": staticmethod(lambda **k: "ok")})(),
        supabase=w,
    )
    product_attachments_routes.supabase = w
    return app, w, logs


def build_finished_spec(tables=None, fail_tables=None):
    w = FakeSupabase(tables=tables, fail_tables=fail_tables)
    app = FakeApp()
    logs = []
    register_products_routes(
        app,
        get_current_user=lambda: STAFF_ERFI,
        supabase=w,
        templates=type("T", (), {"TemplateResponse": staticmethod(lambda **k: "ok")})(),
        log_activity=lambda *a, **k: logs.append((a, k)),
        compute_status_na=lambda *a, **k: ("Belum", 0),
        get_company_info=lambda p: {},
        format_date_id=lambda d: "01-01-2026",
        get_ed_notification_count=lambda: 0,
        COMPANY_INFO={},
        slugify=lambda s: "s",
        _resolve_variant_components=lambda *a, **k: [],
        _flag_bahan_aktif=lambda *a, **k: None,
        _build_diff_changes=lambda *a, **k: [],
        _logo_render_width=lambda *a, **k: 100,
        _pdf_link_callback=lambda _: None,
    )
    products_routes.supabase = w
    return app, w, logs


def build_sample(tables=None, fail_tables=None):
    w = FakeSupabase(tables=tables, fail_tables=fail_tables)
    app = FakeApp()
    logs = []

    async def _ed():
        return 0

    register_sample_routes(
        app,
        get_current_user=lambda: STAFF_ERFI,
        supabase=w,
        templates=type("T", (), {"TemplateResponse": staticmethod(lambda **k: "ok")})(),
        log_activity=lambda *a, **k: logs.append((a, k)),
        get_company_info=lambda p: {},
        format_date_id=lambda d: "01-01-2026",
        mask_email=lambda e: e,
        get_ed_notification_count=_ed,
        _build_diff_changes=lambda *a, **k: [],
        _fsp_notes_changes=lambda *a, **k: [],
        FSP_FIELD_LABELS={},
        FSP_NOTES_LABELS={},
    )
    sample_routes.supabase = w
    return app, w, logs


# ===========================================================================
# A. SEC-02 API PO + tulis raw-materials (dari test_sec02_po_rm_guard.py)
# ===========================================================================
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
            kode_bahan_baku="K-ERFI", tipe="single", journal_link=None,
            current_user=STAFF_HEKA,
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
            kode_bahan_baku="DUP", tipe="single", journal_link=None,
            current_user=STAFF_HEKA,
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
                tanggal_sampling=None, qc_signer=None, qa_signer=None, mengetahui_signer=None, qc_results="[]",
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


_PO_ITEM_OPTIONAL_NONE = dict(
    tanggal_catatan_batch=None, wip=None, netto=None, qty_kg=None, keterangan=None,
    qty_belum_sop=None, qty_po_kg=None, status_bpom=None, catatan_produksi=None,
    revisi_produksi=None, temporary_reject=None,
)


def _assert_po_error_redirect(resp):
    assert resp.status_code == 303, resp.status_code
    location = resp.headers.get("location", "")
    assert "error=" in location and "success=" not in location, location
    assert "memverifikasi" in location, location


def test_po_item_update_old_product_lookup_failure_fails_closed():
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
            tanggal_sampling=None, qc_signer=None, qa_signer=None, mengetahui_signer=None, qc_results="[]",
            harga_per_kg=1.0, coa_file=FakeFile(), halal_file=None, qc_report_file=None,
            quantity=None, quantity_unit=None, keterangan=None, current_user=STAFF_HEKA,
        ))
    finally:
        raw_materials_routes.object_store.upload_pdf = old_upload
    assert resp.status_code == 303
    assert "error_msg" in resp.headers.get("set-cookie", "")
    assert w.writes == []
    assert uploads == []


# ===========================================================================
# B. Efek samping & lampiran produk A-11/A-12 (dari test_tenant_guard_efek_lampiran.py)
# ===========================================================================
def test_efek_generate_other_tenant_blocked_no_writes():
    app, w, logs = build_efek(tables={"products": [_product("PT Erfi")]})
    fn = app.routes[("POST", "/products/{product_id}/monitoring-efek-samping/generate")]
    resp = asyncio.run(fn(SimpleNamespace(), PRODUCT_ID, "0", None, None, None, None, None, None, STAFF_HEKA))
    assert _status(resp) == 303 and w.writes == []
    assert any(k.get("outcome") == "rejected" for _, k in logs)
    print("[PASS] efek generate: tenant lain ditolak, nol tulis, outcome=rejected")


def test_efek_generate_same_tenant_proceeds_to_redirect_guard():
    app, w, _ = build_efek(tables={"products": [_product("PT Erfi")]})
    fn = app.routes[("POST", "/products/{product_id}/monitoring-efek-samping/generate")]
    resp = asyncio.run(fn(SimpleNamespace(), PRODUCT_ID, "0", None, None, None, None, None, None, STAFF_ERFI))
    assert _status(resp) == 303
    print("[PASS] efek generate: tenant sama lolos guard")


def test_efek_generate_admin_allowed():
    app, w, _ = build_efek(tables={"products": [_product("PT Erfi")]})
    fn = app.routes[("POST", "/products/{product_id}/monitoring-efek-samping/generate")]
    resp = asyncio.run(fn(SimpleNamespace(), PRODUCT_ID, "0", None, None, None, None, None, None, ADMIN_HEKA))
    assert _status(resp) == 303
    print("[PASS] efek generate: admin lolos")


def test_efek_generate_no_company_row_allowed():
    app, w, _ = build_efek(tables={"products": [{**_product(), "perusahaan": None}]})
    fn = app.routes[("POST", "/products/{product_id}/monitoring-efek-samping/generate")]
    resp = asyncio.run(fn(SimpleNamespace(), PRODUCT_ID, "0", None, None, None, None, None, None, STAFF_HEKA))
    assert _status(resp) == 303
    print("[PASS] efek generate: baris tanpa perusahaan lolos (legacy fail-open)")


def test_efek_delete_other_tenant_blocked_no_writes():
    app, w, logs = build_efek(tables={"products": [_product("PT Erfi")]})
    fn = app.routes[("POST", "/products/{product_id}/monitoring-efek-samping/delete")]
    resp = asyncio.run(fn(SimpleNamespace(), PRODUCT_ID, STAFF_HEKA))
    assert _status(resp) == 303 and w.writes == []
    assert any(k.get("outcome") == "rejected" for _, k in logs)
    print("[PASS] efek delete: tenant lain ditolak, nol tulis")


def test_efek_read_failure_fail_closed():
    app, w, _ = build_efek(tables={"products": [_product("PT Erfi")]}, fail_tables={"products"})
    fn = app.routes[("POST", "/products/{product_id}/monitoring-efek-samping/delete")]
    resp = asyncio.run(fn(SimpleNamespace(), PRODUCT_ID, STAFF_ERFI))
    assert _status(resp) == 303 and w.writes == []
    print("[PASS] efek delete: baca gagal -> fail-closed (redirect '/', nol tulis)")


def _att_tables():
    return {
        "products": [_product("PT Erfi")],
        "product_attachments": [
            {"id": ATT_ID, "product_id": PRODUCT_ID,
             "file_path": f"products/{PRODUCT_ID}/x.pdf",
             "uploaded_by": "u-erfi", "file_name": "a.pdf"}
        ],
    }


def test_lampiran_get_other_tenant_redirect_no_list():
    app, w, _ = build_att(tables=_att_tables())
    fn = app.routes[("GET", "/products/{product_id}/lampiran")]
    resp = asyncio.run(fn(FakeRequest(), PRODUCT_ID, STAFF_HEKA))
    assert _status(resp) == 303 and "lampiran_groups" not in str(resp)
    print("[PASS] lampiran GET: tenant lain redirect, daftar tidak bocor")


def test_lampiran_upload_other_tenant_blocked_no_storage():
    app, w, _ = build_att(tables=_att_tables())
    fn = app.routes[("POST", "/products/{product_id}/lampiran")]
    called = []
    old_upload = product_attachments_routes.object_store.upload_pdf
    product_attachments_routes.object_store.upload_pdf = lambda *a, **k: called.append(a)
    try:
        try:
            asyncio.run(fn(FakeRequest(), PRODUCT_ID, [SimpleNamespace(filename="x.pdf")], "Lain-lain", "", STAFF_HEKA))
            raise AssertionError("harus 403")
        except HTTPException as e:
            assert e.status_code == 403
    finally:
        product_attachments_routes.object_store.upload_pdf = old_upload
    assert called == [] and w.writes == []
    print("[PASS] lampiran upload: tenant lain 403, nol upload/storage")


def test_lampiran_edit_cross_product_403():
    """attachment_id milik produk lain + product_id milik sendiri -> 403."""
    tables = {
        "products": [_product("PT Erfi"), {**_product("PT Erfi"), "id": "00000000-0000-0000-0000-0000000000cc"}],
        "product_attachments": [
            {"id": ATT_ID, "product_id": "00000000-0000-0000-0000-0000000000cc",
             "file_path": "products/00000000-0000-0000-0000-0000000000cc/x.pdf",
             "uploaded_by": "u-erfi", "file_name": "a.pdf"}
        ],
    }
    app, w, _ = build_att(tables=tables)
    fn = app.routes[("POST", "/products/{product_id}/lampiran/{attachment_id}/edit")]
    try:
        asyncio.run(fn(FakeRequest(), PRODUCT_ID, ATT_ID, "Lain-lain", "", STAFF_ERFI))
        raise AssertionError("harus 403 untuk attachment lintas produk")
    except HTTPException as e:
        assert e.status_code in (403, 404), f"harus 403/404 lintas produk, dapat {e.status_code}"
    assert w.writes == []
    print("[PASS] lampiran edit: attachment lintas produk ditolak (403/404), nol tulis")


def test_lampiran_owner_or_admin():
    # Owner tetap lolos edit
    app, w, _ = build_att(tables=_att_tables())
    fn = app.routes[("POST", "/products/{product_id}/lampiran/{attachment_id}/edit")]
    asyncio.run(fn(FakeRequest(), PRODUCT_ID, ATT_ID, "Lain-lain", "", STAFF_ERFI))
    assert any(t == "update" for t, _, _ in w.writes)
    # Non-owner satu tenant tetap 403
    app2, w2, _ = build_att(tables=_att_tables())
    fn2 = app2.routes[("POST", "/products/{product_id}/lampiran/{attachment_id}/edit")]
    try:
        asyncio.run(fn2(FakeRequest(), PRODUCT_ID, ATT_ID, "Lain-lain", "", {**STAFF_ERFI, "id": "u-other"}))
        raise AssertionError("non-owner harus 403")
    except HTTPException:
        pass
    assert w2.writes == []
    print("[PASS] lampiran edit: owner lolos, non-owner 403")


# ===========================================================================
# C. Finished-spec A-10 (dari test_tenant_guard_finished_spec.py)
# ===========================================================================
def _finished_product(perusahaan="PT Erfi"):
    return {"id": PID, "nama_produk": "Produk Erfi", "perusahaan": perusahaan, "is_deleted": False}


async def _call_finished_spec(app, user):
    fn = app.routes[("POST", "/products/{product_id}/finished-spec")]
    return await fn(FakeRequest(), PID, None, None, None, "Bogor", "[]", user)


def test_other_tenant_blocked_no_writes():
    app, w, logs = build_finished_spec(tables={"products": [_finished_product("PT Erfi")], "product_finished_specs": []})
    try:
        asyncio.run(_call_finished_spec(app, STAFF_HEKA))
        raise AssertionError("harus 403")
    except HTTPException as e:
        assert e.status_code == 403
    assert w.writes == []
    assert any(k.get("outcome") == "rejected" for _, k in logs)
    print("[PASS] finished-spec: tenant lain 403, nol tulis, outcome=rejected")


def test_same_tenant_proceeds():
    app, w, _ = build_finished_spec(tables={"products": [_finished_product("PT Erfi")], "product_finished_specs": []})
    asyncio.run(_call_finished_spec(app, STAFF_ERFI))
    assert any(t == "insert" for t, _, _ in w.writes)
    print("[PASS] finished-spec: tenant sama lolos (insert terjadi)")


def test_admin_allowed():
    app, w, _ = build_finished_spec(tables={"products": [_finished_product("PT Erfi")], "product_finished_specs": []})
    asyncio.run(_call_finished_spec(app, ADMIN_HEKA))
    assert any(t == "insert" for t, _, _ in w.writes)
    print("[PASS] finished-spec: admin lolos")


def test_no_company_row_allowed():
    app, w, _ = build_finished_spec(tables={"products": [{**_finished_product(), "perusahaan": None}], "product_finished_specs": []})
    asyncio.run(_call_finished_spec(app, STAFF_HEKA))
    assert any(t == "insert" for t, _, _ in w.writes)
    print("[PASS] finished-spec: baris tanpa perusahaan lolos (legacy)")


def test_read_failure_still_404():
    app, w, _ = build_finished_spec(tables={"products": [_finished_product("PT Erfi")]}, fail_tables={"products"})
    try:
        asyncio.run(_call_finished_spec(app, STAFF_ERFI))
        raise AssertionError("harus 404")
    except HTTPException as e:
        assert e.status_code == 404
    assert w.writes == []
    print("[PASS] finished-spec: baca gagal -> 404 (perilaku lama dipertahankan)")


# ===========================================================================
# D. Sample / FSP A-13 (dari test_tenant_guard_sample.py)
# ===========================================================================
async def _create_sample(app, user, company=None, product_id=None):
    fn = app.routes[("POST", "/sample-submissions/create")]
    return await fn(
        FakeRequest(), "FSP", "brand-1", company, None, None, product_id,
        "Produk Test", None, "100ml", "Serum", "Tube", None, "desc", "QC", "RD",
        None, None, None, user,
    )


async def _delete_sample(app, user):
    fn = app.routes[("POST", "/sample-submissions/delete/{submission_id}")]
    return await fn(FakeRequest(), SID, user)


def test_create_other_company_blocked_no_writes():
    app, w, _logs = build_sample(tables={"products": [], "sample_submissions": [], "brands": [{"id": "brand-1", "name": "B"}], "producers": []})
    try:
        asyncio.run(_create_sample(app, STAFF_ERFI, company="Heka"))
        raise AssertionError("harus 403")
    except HTTPException as e:
        assert e.status_code == 403
    assert w.writes == []
    print("[PASS] create: company tenant lain 403, nol tulis")


def test_create_referenced_product_other_tenant_blocked():
    app, w, _ = build_sample(tables={"products": [{"id": SAMPLE_PID, "nama_produk": "Produk Erfi", "perusahaan": "PT Erfi"}], "sample_submissions": [], "brands": [{"id": "brand-1", "name": "B"}], "producers": []})
    try:
        asyncio.run(_create_sample(app, STAFF_HEKA, company=None, product_id=SAMPLE_PID))
        raise AssertionError("harus 403")
    except HTTPException as e:
        assert e.status_code == 403
    assert w.writes == []
    print("[PASS] create: produk rujukan tenant lain 403, nol tulis")


def test_create_same_tenant_proceeds():
    app, w, _ = build_sample(tables={"products": [], "sample_submissions": [], "brands": [{"id": "brand-1", "name": "B"}], "producers": []})
    asyncio.run(_create_sample(app, STAFF_ERFI, company="Erfi"))
    assert any(t == "insert" for t, _, _ in w.writes)
    print("[PASS] create: tenant sama lolos (insert terjadi)")


def test_delete_fail_closed_on_read_error():
    app, w, _ = build_sample(tables={"sample_submissions": [{"id": SID, "sample_code": "FSP/01-01-2026/1.1", "company": "Erfi"}]}, fail_tables={"sample_submissions"})
    try:
        asyncio.run(_delete_sample(app, STAFF_ERFI))
        raise AssertionError("harus 403 fail-closed")
    except HTTPException as e:
        assert e.status_code == 403
    assert w.writes == []
    print("[PASS] delete: baca gagal -> fail-closed 403, nol tulis")


def test_delete_other_tenant_blocked():
    app, w, _ = build_sample(tables={"sample_submissions": [{"id": SID, "sample_code": "FSP/01-01-2026/1.1", "company": "Erfi"}]})
    try:
        asyncio.run(_delete_sample(app, STAFF_HEKA))
        raise AssertionError("harus 403")
    except HTTPException as e:
        assert e.status_code == 403
    assert w.writes == []
    print("[PASS] delete: tenant lain 403, nol tulis")


def test_delete_not_found_404():
    app, w, _ = build_sample(tables={"sample_submissions": []})
    try:
        asyncio.run(_delete_sample(app, STAFF_ERFI))
        raise AssertionError("harus 404")
    except HTTPException as e:
        assert e.status_code == 404
    print("[PASS] delete: tidak ditemukan -> 404 (perilaku lama)")


# ---------------------------------------------------------------------------
ALL_TESTS = (
    # A. SEC-02 PO + RM (24)
    test_po_products_staff_only_own_and_shared,
    test_po_products_admin_sees_all,
    test_po_products_user_without_company_sees_all,
    test_po_batches_foreign_product_forbidden,
    test_po_batches_own_product_ok,
    test_po_batches_unknown_product_empty_items,
    test_edit_raw_material_foreign_company_forbidden_no_writes,
    test_edit_raw_material_shared_row_passes_guard,
    test_acc_dipakai_foreign_batch_forbidden_before_update,
    test_acc_dimusnahkan_foreign_batch_forbidden_before_update,
    test_edit_batch_foreign_company_forbidden_before_upload,
    test_add_batch_foreign_parent_forbidden_before_upload_or_insert,
    test_quick_upload_foreign_batch_forbidden_before_upload_or_write,
    test_po_product_batch_foreign_product_forbidden_before_insert,
    test_po_item_create_foreign_product_forbidden_before_insert,
    test_po_item_update_foreign_old_product_forbidden_before_update,
    test_po_item_update_foreign_new_product_forbidden_before_validation_or_update,
    test_po_item_delete_foreign_product_forbidden_before_delete,
    test_po_batches_missing_product_returns_empty_items,
    test_po_item_update_old_product_lookup_failure_fails_closed,
    test_po_item_update_new_product_lookup_failure_fails_closed,
    test_po_item_delete_product_lookup_failure_fails_closed,
    test_po_item_delete_missing_product_row_keeps_previous_behavior,
    test_add_batch_parent_lookup_failure_fails_closed_before_upload_or_insert,
    # B. Efek samping & lampiran (10)
    test_efek_generate_other_tenant_blocked_no_writes,
    test_efek_generate_same_tenant_proceeds_to_redirect_guard,
    test_efek_generate_admin_allowed,
    test_efek_generate_no_company_row_allowed,
    test_efek_delete_other_tenant_blocked_no_writes,
    test_efek_read_failure_fail_closed,
    test_lampiran_get_other_tenant_redirect_no_list,
    test_lampiran_upload_other_tenant_blocked_no_storage,
    test_lampiran_edit_cross_product_403,
    test_lampiran_owner_or_admin,
    # C. Finished-spec (5)
    test_other_tenant_blocked_no_writes,
    test_same_tenant_proceeds,
    test_admin_allowed,
    test_no_company_row_allowed,
    test_read_failure_still_404,
    # D. Sample / FSP (6)
    test_create_other_company_blocked_no_writes,
    test_create_referenced_product_other_tenant_blocked,
    test_create_same_tenant_proceeds,
    test_delete_fail_closed_on_read_error,
    test_delete_other_tenant_blocked,
    test_delete_not_found_404,
)

_ROUTE_MODULES = (
    po_routes,
    raw_materials_routes,
    efek_samping,
    product_attachments_routes,
    products_routes,
    sample_routes,
)


_MISSING = object()


def main(reverse: bool = False) -> int:
    tests = list(reversed(ALL_TESTS)) if reverse else list(ALL_TESTS)
    failures = []
    for func in tests:
        saved_supabase = [(mod, getattr(mod, "supabase", _MISSING)) for mod in _ROUTE_MODULES]
        try:
            func()
        except Exception as exc:  # noqa: BLE001 - laporkan semua jenis kegagalan
            failures.append(f"{func.__name__}: {type(exc).__name__}: {exc}")
        finally:
            for mod, orig in saved_supabase:
                if orig is _MISSING:
                    if hasattr(mod, "supabase"):
                        delattr(mod, "supabase")
                else:
                    mod.supabase = orig

    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        return 1
    print(f"PASS {len(tests)} pemeriksaan guard tenant (SEC-02, efek+lampiran, finished-spec, sample)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
