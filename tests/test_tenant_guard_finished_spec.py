"""Tenant guard untuk POST /products/{id}/finished-spec (PR2: A-10).

Pola sama dengan tests/test_sec02_po_rm_guard.py dan PR1. Pure-local.
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
from app import products_routes  # noqa: E402
from app.products_routes import register_products_routes  # noqa: E402

STAFF_ERFI = {"id": "u-erfi", "role": "staff", "perusahaan": "PT Erfi"}
STAFF_HEKA = {"id": "u-heka", "role": "staff", "perusahaan": "PT Heka"}
ADMIN_HEKA = {"id": "u-admin", "role": "admin", "perusahaan": "PT Heka"}
PID = "00000000-0000-0000-0000-0000000000aa"


class FakeQuery:
    def __init__(self, backend, table_name):
        self.backend = backend
        self.table_name = table_name
        self.filters = []

    def select(self, *a):
        return self

    def eq(self, k, v):
        self.filters.append(("eq", k, v))
        return self

    def limit(self, n):
        return self

    def single(self):
        self._single = True
        return self

    def insert(self, p):
        self.backend.writes.append(("insert", self.table_name, p))
        return self

    def update(self, p):
        self.backend.writes.append(("update", self.table_name, p))
        return self

    def execute(self):
        self.backend.calls[self.table_name] = self.backend.calls.get(self.table_name, 0) + 1
        if self.table_name in self.backend.fail_tables:
            raise RuntimeError(f"simulated DB failure on {self.table_name}")
        rows = list(self.backend.tables.get(self.table_name, []))
        for op, k, v in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(k) == v]
        data = rows
        if getattr(self, "_single", False):
            data = rows[0] if rows else None
        return SimpleNamespace(data=data)


class FakeSupabase:
    def __init__(self, tables=None, fail_tables=None):
        self.tables = tables or {}
        self.writes = []
        self.calls = {}
        self.fail_tables = set(fail_tables or ())

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

    def post(self, path, **kw):
        return self._r("POST")(path, **kw)

    def get(self, path, **kw):
        return self._r("GET")(path, **kw)


class FakeRequest:
    headers = {}
    cookies = {}
    query_params = {}


def build(tables=None, fail_tables=None):
    w = FakeSupabase(tables=tables, fail_tables=fail_tables)
    app = FakeApp()
    logs = []
    register_products_routes(
        app, get_current_user=lambda: STAFF_ERFI, supabase=w,
        templates=type("T", (), {"TemplateResponse": staticmethod(lambda **k: "ok")})(),
        log_activity=lambda *a, **k: logs.append((a, k)),
        compute_status_na=lambda *a, **k: ("Belum", 0), get_company_info=lambda p: {},
        format_date_id=lambda d: "01-01-2026", get_ed_notification_count=lambda: 0,
        COMPANY_INFO={}, slugify=lambda s: "s", _resolve_variant_components=lambda *a, **k: [],
        _flag_bahan_aktif=lambda *a, **k: None, _build_diff_changes=lambda *a, **k: [],
        _logo_render_width=lambda *a, **k: 100, _pdf_link_callback=lambda _: None,
    )
    products_routes.supabase = w
    return app, w, logs


def _product(perusahaan="PT Erfi"):
    return {"id": PID, "nama_produk": "Produk Erfi", "perusahaan": perusahaan, "is_deleted": False}


async def _call(app, user):
    fn = app.routes[("POST", "/products/{product_id}/finished-spec")]
    return await fn(FakeRequest(), PID, None, None, None, "Bogor", "[]", user)


def test_other_tenant_blocked_no_writes():
    app, w, logs = build(tables={"products": [_product("PT Erfi")], "product_finished_specs": []})
    try:
        asyncio.run(_call(app, STAFF_HEKA))
        raise AssertionError("harus 403")
    except HTTPException as e:
        assert e.status_code == 403
    assert w.writes == []
    assert any(k.get("outcome") == "rejected" for _, k in logs)
    print("[PASS] finished-spec: tenant lain 403, nol tulis, outcome=rejected")


def test_same_tenant_proceeds():
    app, w, _ = build(tables={"products": [_product("PT Erfi")], "product_finished_specs": []})
    resp = asyncio.run(_call(app, STAFF_ERFI))
    assert any(t == "insert" for t, _, _ in w.writes)
    print("[PASS] finished-spec: tenant sama lolos (insert terjadi)")


def test_admin_allowed():
    app, w, _ = build(tables={"products": [_product("PT Erfi")], "product_finished_specs": []})
    resp = asyncio.run(_call(app, ADMIN_HEKA))
    assert any(t == "insert" for t, _, _ in w.writes)
    print("[PASS] finished-spec: admin lolos")


def test_no_company_row_allowed():
    app, w, _ = build(tables={"products": [{**_product(), "perusahaan": None}], "product_finished_specs": []})
    resp = asyncio.run(_call(app, STAFF_HEKA))
    assert any(t == "insert" for t, _, _ in w.writes)
    print("[PASS] finished-spec: baris tanpa perusahaan lolos (legacy)")


def test_read_failure_still_404():
    app, w, _ = build(tables={"products": [_product("PT Erfi")]}, fail_tables={"products"})
    try:
        asyncio.run(_call(app, STAFF_ERFI))
        raise AssertionError("harus 404")
    except HTTPException as e:
        assert e.status_code == 404
    assert w.writes == []
    print("[PASS] finished-spec: baca gagal -> 404 (perilaku lama dipertahankan)")


def main():
    test_other_tenant_blocked_no_writes()
    test_same_tenant_proceeds()
    test_admin_allowed()
    test_no_company_row_allowed()
    test_read_failure_still_404()
    print("\nSemua guard tenant finished-spec LULUS.")


if __name__ == "__main__":
    main()
