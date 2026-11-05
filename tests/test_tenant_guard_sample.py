"""Tenant guard untuk sample/FSP (PR3: A-13). Pure-local, fake Supabase."""
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
from app import sample_routes  # noqa: E402
from app.sample_routes import register_sample_routes  # noqa: E402

STAFF_ERFI = {"id": "u-erfi", "role": "staff", "perusahaan": "PT Erfi"}
STAFF_HEKA = {"id": "u-heka", "role": "staff", "perusahaan": "PT Heka"}
ADMIN_HEKA = {"id": "u-admin", "role": "admin", "perusahaan": "PT Heka"}
SID = "00000000-0000-0000-0000-0000000000aa"
PID = "00000000-0000-0000-0000-0000000000bb"


class FakeQuery:
    def __init__(self, backend, table_name):
        self.backend = backend
        self.table_name = table_name
        self.filters = []
        self._payload = None

    def select(self, *a):
        return self

    def eq(self, k, v):
        self.filters.append(("eq", k, v))
        return self

    def gte(self, *a):
        return self

    def ilike(self, *a):
        return self

    def single(self):
        self._single = True
        return self

    def insert(self, p):
        self.backend.writes.append(("insert", self.table_name, p))
        self._payload = p
        return self

    def update(self, p):
        self.backend.writes.append(("update", self.table_name, p))
        return self

    def delete(self):
        self.backend.writes.append(("delete", self.table_name, None))
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
        elif self._payload is not None:
            data = [{"id": "new-id", **self._payload}]
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

    async def _ed():
        return 0

    register_sample_routes(
        app, get_current_user=lambda: STAFF_ERFI, supabase=w,
        templates=type("T", (), {"TemplateResponse": staticmethod(lambda **k: "ok")})(),
        log_activity=lambda *a, **k: logs.append((a, k)), get_company_info=lambda p: {},
        format_date_id=lambda d: "01-01-2026", mask_email=lambda e: e,
        get_ed_notification_count=_ed, _build_diff_changes=lambda *a, **k: [],
        _fsp_notes_changes=lambda *a, **k: [], FSP_FIELD_LABELS={}, FSP_NOTES_LABELS={},
    )
    sample_routes.supabase = w
    return app, w, logs


async def _create(app, user, company=None, product_id=None):
    fn = app.routes[("POST", "/sample-submissions/create")]
    return await fn(FakeRequest(), "FSP", "brand-1", company, None, None, product_id, "Produk Test", None, "100ml", "Serum", "Tube", None, "desc", "QC", "RD", None, None, None, user)


async def _delete(app, user):
    fn = app.routes[("POST", "/sample-submissions/delete/{submission_id}")]
    return await fn(FakeRequest(), SID, user)


def test_create_other_company_blocked_no_writes():
    app, w, logs = build(tables={"products": [], "sample_submissions": [], "brands": [{"id": "brand-1", "name": "B"}], "producers": []})
    try:
        asyncio.run(_create(app, STAFF_ERFI, company="Heka"))
        raise AssertionError("harus 403")
    except HTTPException as e:
        assert e.status_code == 403
    assert w.writes == []
    print("[PASS] create: company tenant lain 403, nol tulis")


def test_create_referenced_product_other_tenant_blocked():
    app, w, _ = build(tables={"products": [{"id": PID, "nama_produk": "Produk Erfi", "perusahaan": "PT Erfi"}], "sample_submissions": [], "brands": [{"id": "brand-1", "name": "B"}], "producers": []})
    try:
        asyncio.run(_create(app, STAFF_HEKA, company=None, product_id=PID))
        raise AssertionError("harus 403")
    except HTTPException as e:
        assert e.status_code == 403
    assert w.writes == []
    print("[PASS] create: produk rujukan tenant lain 403, nol tulis")


def test_create_same_tenant_proceeds():
    app, w, _ = build(tables={"products": [], "sample_submissions": [], "brands": [{"id": "brand-1", "name": "B"}], "producers": []})
    resp = asyncio.run(_create(app, STAFF_ERFI, company="Erfi"))
    assert any(t == "insert" for t, _, _ in w.writes)
    print("[PASS] create: tenant sama lolos (insert terjadi)")


def test_delete_fail_closed_on_read_error():
    app, w, _ = build(tables={"sample_submissions": [{"id": SID, "sample_code": "FSP/01-01-2026/1.1", "company": "Erfi"}]}, fail_tables={"sample_submissions"})
    try:
        asyncio.run(_delete(app, STAFF_ERFI))
        raise AssertionError("harus 403 fail-closed")
    except HTTPException as e:
        assert e.status_code == 403
    assert w.writes == []
    print("[PASS] delete: baca gagal -> fail-closed 403, nol tulis")


def test_delete_other_tenant_blocked():
    app, w, _ = build(tables={"sample_submissions": [{"id": SID, "sample_code": "FSP/01-01-2026/1.1", "company": "Erfi"}]})
    try:
        asyncio.run(_delete(app, STAFF_HEKA))
        raise AssertionError("harus 403")
    except HTTPException as e:
        assert e.status_code == 403
    assert w.writes == []
    print("[PASS] delete: tenant lain 403, nol tulis")


def test_delete_not_found_404():
    app, w, _ = build(tables={"sample_submissions": []})
    try:
        asyncio.run(_delete(app, STAFF_ERFI))
        raise AssertionError("harus 404")
    except HTTPException as e:
        assert e.status_code == 404
    print("[PASS] delete: tidak ditemukan -> 404 (perilaku lama)")


def main():
    test_create_other_company_blocked_no_writes()
    test_create_referenced_product_other_tenant_blocked()
    test_create_same_tenant_proceeds()
    test_delete_fail_closed_on_read_error()
    test_delete_other_tenant_blocked()
    test_delete_not_found_404()
    print("\nSemua guard tenant sample LULUS.")


if __name__ == "__main__":
    main()
