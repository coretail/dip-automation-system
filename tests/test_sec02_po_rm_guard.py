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
        rows = list(self.backend.tables.get(self.table_name, []))
        for op, key, value in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(key) == value]
            elif op == "neq":
                rows = [r for r in rows if r.get(key) != value]
        return SimpleNamespace(data=rows)


class FakeSupabase:
    def __init__(self, tables=None):
        self.tables = tables or {}
        self.writes = []
        self.limits = {}

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
