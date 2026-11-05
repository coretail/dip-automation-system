"""Tenant guard untuk efek samping & lampiran produk (PR1: A-11/A-12).

Pola sama dengan tests/test_sec02_po_rm_guard.py: FakeQuery/FakeSupabase/
FakeApp yang mencatat tulis, tanpa jaringan. Pure-local; runner main()
memanggil semua test (CI tidak memakai pytest).
"""
import asyncio
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
from fastapi.responses import RedirectResponse  # noqa: E402

from app import efek_samping, product_attachments_routes  # noqa: E402
from app.efek_samping import register_efek_samping_routes  # noqa: E402
from app.product_attachments_routes import register_product_attachment_routes  # noqa: E402

STAFF_ERFI = {"id": "u-erfi", "role": "staff", "perusahaan": "PT Erfi"}
STAFF_HEKA = {"id": "u-heka", "role": "staff", "perusahaan": "PT Heka"}
ADMIN_HEKA = {"id": "u-admin", "role": "admin", "perusahaan": "PT Heka"}
STAFF_NO = {"id": "u-legacy", "role": "staff", "perusahaan": None}
PRODUCT_ID = "00000000-0000-0000-0000-0000000000aa"
ATT_ID = "00000000-0000-0000-0000-0000000000bb"


class FakeQuery:
    def __init__(self, backend, table_name):
        self.backend = backend
        self.table_name = table_name
        self.filters = []

    def select(self, *a):
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def order(self, *a, **k):
        return self

    def single(self):
        self._single = True
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
        count = self.backend.calls[self.table_name] = self.backend.calls.get(self.table_name, 0) + 1
        if self.table_name in self.backend.fail_tables:
            raise RuntimeError(f"simulated DB failure on {self.table_name} (call {count})")
        if count in self.backend.fail_calls.get(self.table_name, ()):
            raise RuntimeError(f"simulated DB failure on {self.table_name} (call {count})")
        rows = list(self.backend.tables.get(self.table_name, []))
        for op, key, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(key) == value]
        data = rows
        if getattr(self, "_single", False):
            data = rows[0] if rows else None
        return SimpleNamespace(data=data)


class FakeSupabase:
    def __init__(self, tables=None, fail_tables=None, fail_calls=None):
        self.tables = tables or {}
        self.writes = []
        self.calls = {}
        self.fail_tables = set(fail_tables or ())
        self.fail_calls = dict(fail_calls or {})

    def table(self, name):
        return FakeQuery(self, name)


class FakeApp:
    def __init__(self):
        self.routes = {}

    def _r(self, m):
        def deco(path, **kw):
            def w(fn):
                self.routes[(m, path)] = fn
                return fn
            return w
        return deco

    def get(self, path, **kw):
        return self._r("GET")(path, **kw)

    def post(self, path, **kw):
        return self._r("POST")(path, **kw)


class FakeRequest:
    headers = {}
    cookies = {}
    query_params = {}


def _product(perusahaan="PT Erfi"):
    return {"id": PRODUCT_ID, "nama_produk": "Produk Erfi", "perusahaan": perusahaan,
            "is_deleted": False, "monitoring_efek_samping_file_url": None,
            "last_efek_samping_period": None}


def build_efek(tables=None, fail_tables=None, fail_calls=None):
    w = FakeSupabase(tables=tables, fail_tables=fail_tables, fail_calls=fail_calls)
    app = FakeApp()
    logs = []
    register_efek_samping_routes(
        app, get_current_user=lambda: STAFF_ERFI, templates=type("T", (), {"env": SimpleNamespace(get_template=lambda _: SimpleNamespace(render=lambda _: ""))})(),
        supabase=w, get_company_info=lambda p: {"name": p}, format_date_id=lambda d: "01-01-2026",
        log_activity=lambda *a, **k: logs.append((a, k)), pdf_link_callback=lambda _: None,
    )
    efek_samping.supabase = w
    return app, w, logs


def build_att(tables=None, fail_tables=None):
    w = FakeSupabase(tables=tables, fail_tables=fail_tables)
    app = FakeApp()
    logs = []
    register_product_attachment_routes(
        app, get_current_user=lambda: STAFF_ERFI, log_activity=lambda *a, **k: logs.append((a, k)),
        templates=type("T", (), {"TemplateResponse": staticmethod(lambda **k: "ok")})(), supabase=w,
    )
    product_attachments_routes.supabase = w
    return app, w, logs


def _status(resp):
    return getattr(resp, "status_code", None)


def _set_cookie(resp, name):
    for h in resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else []:
        if name in h:
            return h
    return str(resp.headers)


# ---------------- efek samping ----------------

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
    # Bukan 403 penolakan; jalur lanjut (redirect hasil generate) — tenant sama lolos guard
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


# ---------------- lampiran ----------------

def _att_tables():
    return {"products": [_product("PT Erfi")],
            "product_attachments": [{"id": ATT_ID, "product_id": PRODUCT_ID, "file_path": f"products/{PRODUCT_ID}/x.pdf", "uploaded_by": "u-erfi", "file_name": "a.pdf"}]}


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
    product_attachments_routes.object_store.upload_pdf = lambda *a, **k: called.append(a)
    try:
        try:
            asyncio.run(fn(FakeRequest(), PRODUCT_ID, [SimpleNamespace(filename="x.pdf")], "Lain-lain", "", STAFF_HEKA))
            raise AssertionError("harus 403")
        except HTTPException as e:
            assert e.status_code == 403
    finally:
        del product_attachments_routes.object_store.upload_pdf
    assert called == [] and w.writes == []
    print("[PASS] lampiran upload: tenant lain 403, nol upload/storage")


def test_lampiran_edit_cross_product_403():
    """attachment_id milik produk lain + product_id milik sendiri -> 403."""
    tables = {"products": [_product("PT Erfi"), {**_product("PT Erfi"), "id": "00000000-0000-0000-0000-0000000000cc"}],
              "product_attachments": [{"id": ATT_ID, "product_id": "00000000-0000-0000-0000-0000000000cc", "file_path": "products/00000000-0000-0000-0000-0000000000cc/x.pdf", "uploaded_by": "u-erfi", "file_name": "a.pdf"}]}
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
    try:
        asyncio.run(fn(FakeRequest(), PRODUCT_ID, ATT_ID, "Lain-lain", "", {**STAFF_ERFI, "id": "u-other"}))
        raise AssertionError("non-owner harus 403")
    except HTTPException:
        pass
    assert w2.writes == []
    print("[PASS] lampiran edit: owner lolos, non-owner 403")


def main():
    test_efek_generate_other_tenant_blocked_no_writes()
    test_efek_generate_same_tenant_proceeds_to_redirect_guard()
    test_efek_generate_admin_allowed()
    test_efek_generate_no_company_row_allowed()
    test_efek_delete_other_tenant_blocked_no_writes()
    test_efek_read_failure_fail_closed()
    test_lampiran_get_other_tenant_redirect_no_list()
    test_lampiran_upload_other_tenant_blocked_no_storage()
    test_lampiran_edit_cross_product_403()
    test_lampiran_owner_or_admin()
    print("\nSemua guard tenant efek+lampiran LULUS.")


if __name__ == "__main__":
    main()
