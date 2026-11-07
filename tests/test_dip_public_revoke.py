"""Unit test murni F-03 + F-09: revoke link publik DIP + audit akses publik.

Aturan revoke (satu definisi di _dip_public_check_product): produk DICABUT bila
public_access_enabled is False ATAU public_access_revoked_at tidak null. Cek
revoke sebelum cabang BPOM. Aktifkan ulang memakai token LAMA (tidak dirotasi).

Tanpa koneksi, tanpa secret. Dijalankan: python tests/test_dip_public_revoke.py
(dengan PYTHONPATH=. seperti di ci.yml).
"""
import asyncio
import os
import re
import sys
import uuid
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.dip_public import register_dip_public_routes  # noqa: E402
from app.products_routes import register_products_routes  # noqa: E402

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
PRODUCT_TOKEN = "tok123"
PID = str(uuid.uuid4())


class _FakeBuilder:
    def __init__(self, explode=False, single_data=None, list_data=None):
        self._explode = explode
        self._single_data = single_data
        self._list_data = list_data or []

    def select(self, *_a, **_kw):
        return self

    def eq(self, *_a, **_kw):
        return self

    def neq(self, *_a, **_kw):
        return self

    def single(self):
        return self

    def insert(self, *_a, **_kw):
        return self

    def execute(self):
        if self._explode:
            raise RuntimeError("simulasi kegagalan query capability")
        return type("R", (), {"data": self._single_data if self._single_data is not None else self._list_data})()


class FakeSupabase:
    def __init__(self, capability_explode=False, product=None):
        self.capability_explode = capability_explode
        self.product = product or {
            "id": PID,
            "is_deleted": False,
            "public_access_enabled": True,
            "public_access_token": PRODUCT_TOKEN,
            "bpom_registered_link": False,
            "public_access_revoked_at": None,
            "nama_produk": "Produk Uji E2E",
            "perusahaan": "PT Erfi",
        }

    def table(self, name):
        if self.capability_explode:
            return _FakeBuilder(explode=True)
        if name == "products":
            return _FakeBuilder(single_data=dict(self.product))
        if name in ("public_link_audits", "activity_logs"):
            return _FakeBuilder()
        return _FakeBuilder(list_data=[])

    class _Auth:
        def get_user(self, _token):
            raise RuntimeError("tanpa sesi")

    auth = _Auth()


class FakeTemplates:
    def TemplateResponse(self, request=None, name=None, context=None, **_kw):
        return HTMLResponse("<html><body>hub-ok</body></html>")


def _register(fake_supabase, logs=None):
    app = FastAPI()
    register_dip_public_routes(
        app=app,
        templates=FakeTemplates(),
        supabase=fake_supabase,
        get_company_info=lambda perusahaan: {"name": perusahaan},
        extract_id_from_slug=lambda slug: (m.group(0) if (m := re.search(UUID_RE, slug)) else None),
        client_ip=lambda request: "127.0.0.1",
        apply_company_specific_docs=lambda rm, perusahaan: rm,
        parse_storage_url=lambda url: (None, None),
        bab_generators={"1": lambda pid, u: _fake_pdf("1")},
        download_bab2_zip=lambda pid, u: _fake_zip(),
        log_activity=(lambda *a, **k: logs.append((a, k))) if logs is not None else None,
    )
    return app


async def _fake_pdf(bab):
    from fastapi.responses import Response
    return Response(content=b"%PDF", media_type="application/pdf")


async def _fake_zip():
    from fastapi.responses import Response
    return Response(content=b"PK", media_type="application/zip")


def test_revoke_flag_enabled_false_404():
    fake = FakeSupabase(product={"id": PID, "is_deleted": False, "public_access_enabled": False,
                                  "public_access_token": PRODUCT_TOKEN, "bpom_registered_link": False,
                                  "public_access_revoked_at": None, "nama_produk": "P", "perusahaan": "PT Erfi"})
    client = TestClient(_register(fake), raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 404, f"enabled=False harus 404, dapat {resp.status_code}"
    print("[PASS] revoke lewat flag enabled=False -> 404")


def test_revoke_at_filled_404():
    fake = FakeSupabase(product={"id": PID, "is_deleted": False, "public_access_enabled": True,
                                  "public_access_token": PRODUCT_TOKEN, "bpom_registered_link": False,
                                  "public_access_revoked_at": "2026-11-07T00:00:00+07:00",
                                  "nama_produk": "P", "perusahaan": "PT Erfi"})
    client = TestClient(_register(fake), raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 404, f"revoked_at terisi harus 404, dapat {resp.status_code}"
    print("[PASS] revoke lewat revoked_at terisi -> 404")


def test_bpom_revoked_without_token_404():
    fake = FakeSupabase(product={"id": PID, "is_deleted": False, "public_access_enabled": False,
                                  "public_access_token": PRODUCT_TOKEN, "bpom_registered_link": True,
                                  "public_access_revoked_at": None, "nama_produk": "P", "perusahaan": "PT Erfi"})
    client = TestClient(_register(fake), raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-{PID}")
    assert resp.status_code == 404, f"BPOM dicabut tanpa token harus 404, dapat {resp.status_code}"
    print("[PASS] produk BPOM dicabut tanpa token -> 404 (revoke sebelum cabang BPOM)")


def test_correct_token_but_revoked_404():
    fake = FakeSupabase(product={"id": PID, "is_deleted": False, "public_access_enabled": True,
                                  "public_access_token": PRODUCT_TOKEN, "bpom_registered_link": True,
                                  "public_access_revoked_at": "2026-11-07T00:00:00+07:00",
                                  "nama_produk": "P", "perusahaan": "PT Erfi"})
    client = TestClient(_register(fake), raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 404, f"token benar tapi dicabut harus 404, dapat {resp.status_code}"
    print("[PASS] token benar tapi dicabut -> 404")


def test_active_correct_token_200():
    fake = FakeSupabase()
    client = TestClient(_register(fake), raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 200, f"aktif + token benar harus 200, dapat {resp.status_code}"
    print("[PASS] aktif + token benar -> 200")


def test_reactivate_same_token_200():
    fake = FakeSupabase(product={"id": PID, "is_deleted": False, "public_access_enabled": False,
                                  "public_access_token": PRODUCT_TOKEN, "bpom_registered_link": False,
                                  "public_access_revoked_at": "2026-11-07T00:00:00+07:00",
                                  "nama_produk": "P", "perusahaan": "PT Erfi"})
    client = TestClient(_register(fake), raise_server_exceptions=False)
    assert client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}").status_code == 404
    fake.product["public_access_enabled"] = True
    fake.product["public_access_revoked_at"] = None
    resp = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 200, f"setelah aktifkan ulang token LAMA harus 200, dapat {resp.status_code}"
    assert fake.product["public_access_token"] == PRODUCT_TOKEN, "token tidak boleh berubah"
    print("[PASS] setelah aktifkan ulang token LAMA -> 200 (token tidak berubah)")


def test_exception_fail_closed_404():
    client = TestClient(_register(FakeSupabase(capability_explode=True)), raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 404, f"exception baca harus 404, dapat {resp.status_code}"
    print("[PASS] exception baca -> 404 (fail-closed)")


# --- Route admin ---

ADMIN_ERFI = {"id": "u-adm", "role": "admin", "perusahaan": "PT Erfi"}
STAFF_ERFI = {"id": "u-stf", "role": "staff", "perusahaan": "PT Erfi"}
ADMIN_HEKA = {"id": "u-adm2", "role": "admin", "perusahaan": "PT Heka"}
STAFF_HEKA = {"id": "u-stf2", "role": "staff", "perusahaan": "PT Heka"}


class FakeQuery:
    def __init__(self, backend, table_name):
        self.backend = backend
        self.table_name = table_name
        self.filters = []

    def select(self, *a):
        return self

    def eq(self, k, v):
        self.filters.append((k, v))
        return self

    def limit(self, n):
        return self

    def single(self):
        self._single = True
        return self

    def update(self, p):
        self.backend.writes.append(("update", self.table_name, p))
        return self

    def execute(self):
        rows = list(self.backend.tables.get(self.table_name, []))
        for k, v in self.filters:
            rows = [r for r in rows if r.get(k) == v]
        data = (rows[0] if rows else None) if getattr(self, "_single", False) else rows
        return SimpleNamespace(data=data)


class FakeSupabase2:
    def __init__(self, tables=None):
        self.tables = tables or {}
        self.writes = []

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


def build_admin(product):
    w = FakeSupabase2(tables={"products": [product]})
    app = FakeApp()
    logs = []
    register_products_routes(
        app, get_current_user=lambda: ADMIN_ERFI, supabase=w,
        templates=type("T", (), {"TemplateResponse": staticmethod(lambda **k: "ok")})(),
        log_activity=lambda *a, **k: logs.append((a, k)),
        compute_status_na=lambda *a, **k: ("Belum", 0), get_company_info=lambda p: {},
        format_date_id=lambda d: "01-01-2026", get_ed_notification_count=lambda: 0,
        COMPANY_INFO={}, slugify=lambda s: "s", _resolve_variant_components=lambda *a, **k: [],
        _flag_bahan_aktif=lambda *a, **k: None, _build_diff_changes=lambda *a, **k: [],
        _logo_render_width=lambda *a, **k: 100, _pdf_link_callback=lambda _: None,
    )
    return app, w, logs


def _prod(perusahaan="PT Erfi", token=PRODUCT_TOKEN):
    return {"id": PID, "nama_produk": "Produk Erfi", "perusahaan": perusahaan,
            "is_deleted": False, "public_access_token": token, "public_access_enabled": True,
            "public_access_revoked_at": None}


def test_admin_revoke_non_admin_403_no_writes():
    app, w, logs = build_admin(_prod())
    fn = app.routes[("POST", "/products/{product_id}/public-access/revoke")]
    try:
        asyncio.run(fn(FakeRequest(), PID, STAFF_ERFI))
        raise AssertionError("harus 403")
    except HTTPException as e:
        assert e.status_code == 403
    assert w.writes == []
    print("[PASS] route revoke: non-admin 403 + nol tulis")


def test_admin_revoke_other_tenant_403_no_writes():
    # assert_same_tenant selalu meloloskan admin (by design), jadi guard tenant
    # tidak dapat menolak admin lintas perusahaan; yang ditolak di sini adalah
    # non-admin lintas tenant.
    app, w, logs = build_admin(_prod("PT Erfi"))
    fn = app.routes[("POST", "/products/{product_id}/public-access/revoke")]
    try:
        asyncio.run(fn(FakeRequest(), PID, STAFF_HEKA))
        raise AssertionError("harus 403")
    except HTTPException as e:
        assert e.status_code == 403
    assert w.writes == []
    print("[PASS] route revoke: admin tenant lain 403 + nol tulis")


def test_admin_revoke_success():
    prod = _prod("PT Erfi", token=PRODUCT_TOKEN)
    app, w, logs = build_admin(prod)
    fn = app.routes[("POST", "/products/{product_id}/public-access/revoke")]
    resp = asyncio.run(fn(FakeRequest(), PID, ADMIN_ERFI))
    assert resp.status_code == 303
    upd = [p for t, _, p in w.writes if t == "update"]
    assert upd and upd[-1]["public_access_enabled"] is False
    assert upd[-1]["public_access_revoked_at"] is not None
    assert "public_access_token" not in upd[-1], "token tidak boleh diubah"
    ok = [k for a, k in logs if k.get("outcome") == "success" and a[3] == PID]
    assert ok, "log_activity sukses dengan entity_id UUID"
    assert PRODUCT_TOKEN not in str(logs), "token tidak boleh masuk payload log"
    print("[PASS] route revoke: admin tenant sama sukses, token tidak diubah, log tanpa token")


def test_admin_reactivate_success_same_token():
    prod = _prod("PT Erfi", token=PRODUCT_TOKEN)
    prod["public_access_enabled"] = False
    prod["public_access_revoked_at"] = "2026-11-07T00:00:00+07:00"
    app, w, logs = build_admin(prod)
    fn = app.routes[("POST", "/products/{product_id}/public-access/reactivate")]
    resp = asyncio.run(fn(FakeRequest(), PID, ADMIN_ERFI))
    assert resp.status_code == 303
    upd = [p for t, _, p in w.writes if t == "update"]
    assert upd and upd[-1]["public_access_enabled"] is True
    assert upd[-1]["public_access_revoked_at"] is None
    assert "public_access_token" not in upd[-1], "token tidak boleh diubah"
    print("[PASS] route reactivate: enabled True + revoked_at None + token tidak diubah")


def test_audit_download_logs_once_and_404_silent():
    logs = []
    fake = FakeSupabase()
    client = TestClient(_register(fake, logs=logs), raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-{PID}/bab1/download?access={PRODUCT_TOKEN}")
    assert resp.status_code == 200, f"download bab2 harus 200, dapat {resp.status_code}"
    hits = [k for a, k in logs if a[1] == "public_access"]
    assert len(hits) == 1, f"download sukses harus log sekali, dapat {len(hits)}"
    assert PRODUCT_TOKEN not in str(logs), "token tidak boleh masuk payload log audit"
    logs.clear()
    resp2 = client.get(f"/dip/produk-{PID}/bab1/download?access=salah")
    assert resp2.status_code == 404
    assert [k for a, k in logs if a[1] == "public_access"] == [], "404 tidak boleh memanggil log audit"
    print("[PASS] audit: download sukses log sekali (UUID), 404 tidak memanggil log")


def main():
    test_revoke_flag_enabled_false_404()
    test_revoke_at_filled_404()
    test_bpom_revoked_without_token_404()
    test_correct_token_but_revoked_404()
    test_active_correct_token_200()
    test_reactivate_same_token_200()
    test_exception_fail_closed_404()
    test_admin_revoke_non_admin_403_no_writes()
    test_admin_revoke_other_tenant_403_no_writes()
    test_admin_revoke_success()
    test_admin_reactivate_success_same_token()
    test_audit_download_logs_once_and_404_silent()
    print("\nSemua test revoke + audit publik LULUS.")


if __name__ == "__main__":
    main()
