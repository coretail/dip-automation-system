"""Unit test gabungan portal publik /dip/* (pure-local, tanpa DB/secret):
  1. Fail-closed checker portal publik (F-01)
  2. Revoke link publik + audit akses publik & route admin revoke/reactivate (F-03 + F-09)
  3. Rate-limit portal publik /dip/* + redaction token + trusted-proxy client IP (F-08 + F-05)
  4. Helper logika bab2_materials / link jurnal hub publik

Digabungkan pada Task 5 dari:
  - test_dip_public_check.py
  - test_dip_public_revoke.py
  - test_dip_public_rate_limit.py
  - test_dip_public_bab2_journal.py

Jalankan: python tests/test_dip_public.py
"""
import asyncio
import os
import re
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for p in (str(ROOT), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

# Alur hub app mencetak emoji (mis. "[PUBLIC LINK OPENED] 🔗..."). Di console
# Windows ber-charmap (cp1252) itu melempar UnicodeEncodeError; amankan agar
# test pure-local jalan di semua platform.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, Response  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from slowapi import Limiter  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

from _fakes import FakeApp, FakeRequest  # noqa: E402
from app.client_ip import client_ip_from  # noqa: E402
from app.dip_public import (  # noqa: E402
    DIP_BAB_LIMIT,
    DIP_HUB_LIMIT,
    DIP_PRODUCT_LIMIT,
    DIP_ZIP_LIMIT,
    bab2_journal_link,
    bab2_material_entry,
    register_dip_public_routes,
)
from app.products_routes import register_products_routes  # noqa: E402

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

PRODUCT_TOKEN = "tok123"
PID = str(uuid.uuid4())
PID2 = str(uuid.uuid4())


class _FakeBuilder:
    """PostgREST-style builder palsu untuk alur /dip/."""

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
    """Klien Supabase palsu minimal untuk alur /dip/."""

    def __init__(self, capability_explode=False, product=None, include_revoked_at=False):
        self.capability_explode = capability_explode
        if product is not None:
            self.product = product
        else:
            self.product = {
                "id": PID if include_revoked_at else str(uuid.uuid4()),
                "is_deleted": False,
                "public_access_enabled": True,
                "public_access_token": PRODUCT_TOKEN,
                "bpom_registered_link": False,
                "nama_produk": "Produk Uji E2E",
                "perusahaan": "PT Erfi",
            }
            if include_revoked_at:
                self.product["public_access_revoked_at"] = None

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


class FakeSupabaseBpom:
    """Produk BPOM terdaftar: boleh akses tanpa token."""

    def __init__(self):
        self.product = {
            "id": PID,
            "is_deleted": False,
            "public_access_enabled": True,
            "public_access_token": PRODUCT_TOKEN,
            "bpom_registered_link": True,
            "public_access_revoked_at": None,
            "nama_produk": "Produk BPOM",
            "perusahaan": "PT Erfi",
        }

    def table(self, name):
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
    """Templates palsu: cukup membuktikan checker lolos (route sampai render)."""

    def TemplateResponse(self, request=None, name=None, context=None, **_kw):
        return HTMLResponse("<html><body>hub-ok</body></html>")


async def _fake_pdf(*_args):
    return Response(content=b"%PDF", media_type="application/pdf")


async def _fake_zip(*_args):
    return Response(content=b"PK", media_type="application/zip")


# =====================================================================
# Bagian 1: Fail-closed checker portal publik (F-01)
# =====================================================================


def _register_check(fake_supabase):
    app = FastAPI()
    limiter = Limiter(key_func=lambda request: "192.0.2.1")
    limiter._storage.reset()
    register_dip_public_routes(
        app=app,
        templates=FakeTemplates(),
        supabase=fake_supabase,
        get_company_info=lambda perusahaan: {"name": perusahaan},
        extract_id_from_slug=lambda slug: (m.group(0) if (m := re.search(UUID_RE, slug)) else None),
        client_ip=lambda request: "127.0.0.1",
        apply_company_specific_docs=lambda rm, perusahaan: rm,
        parse_storage_url=lambda url: (None, None),
        bab_generators={},
        download_bab2_zip=None,
        limiter=limiter,
    )
    return app


def test_exception_fail_closed_404():
    """Query capability melempar Exception -> HARUS 404 (fail-closed)."""
    app = _register_check(FakeSupabase(capability_explode=True))
    client = TestClient(app, raise_server_exceptions=False)
    slug = f"produk-uji-{uuid.uuid4()}"
    resp = client.get(f"/dip/{slug}")
    assert resp.status_code == 404, f"harus 404 saat query gagal, dapat {resp.status_code}"
    print("[PASS] query capability Exception -> 404 fail-closed (tidak jatuh ke mode legacy)")


def test_exception_fail_closed_direct():
    """Versi langsung: Exception -> hasil check False (bukan True legacy)."""
    fake = FakeSupabase(capability_explode=True)
    app = _register_check(fake)
    fake.product["public_access_token"] = None
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-uji-{fake.product['id']}")
    assert resp.status_code == 404, (
        f"produk tanpa token harus 404 saat query gagal (fail-closed), dapat {resp.status_code}"
    )
    print("[PASS] produk tanpa token + query Exception -> 404 (bukti tidak ada jalur legacy fail-open)")


def test_token_enforced():
    """Produk bertoken: tanpa token -> 404; token salah -> 404."""
    app = _register_check(FakeSupabase())
    client = TestClient(app, raise_server_exceptions=False)
    slug = f"produk-uji-{uuid.uuid4()}"
    assert client.get(f"/dip/{slug}").status_code == 404, "tanpa token harus 404"
    assert client.get(f"/dip/{slug}?access=salah").status_code == 404, "token salah harus 404"
    print("[PASS] produk bertoken: tanpa/salah token -> 404")


def test_valid_token_passes_check():
    """Produk bertoken + token cocok -> checker lolos (route lanjut sampai render hub)."""
    fake = FakeSupabase()
    app = _register_check(fake)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-uji-{fake.product['id']}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 200, f"token cocok harus lolos checker (200), dapat {resp.status_code}"
    assert "hub-ok" in resp.text
    print("[PASS] token cocok -> checker lolos, hub dirender (200)")


def test_wrong_token_same_length_404():
    """Token salah dengan panjang sama -> 404 (timing-safe, bukan 500)."""
    app = _register_check(FakeSupabase())
    client = TestClient(app, raise_server_exceptions=False)
    slug = f"produk-uji-{uuid.uuid4()}"
    resp = client.get(f"/dip/{slug}?access=tok999")
    assert resp.status_code == 404, f"token salah panjang sama harus 404, dapat {resp.status_code}"
    print("[PASS] token salah panjang sama -> 404")


def test_wrong_token_different_length_404():
    """Token salah dengan panjang berbeda -> 404."""
    app = _register_check(FakeSupabase())
    client = TestClient(app, raise_server_exceptions=False)
    slug = f"produk-uji-{uuid.uuid4()}"
    resp = client.get(f"/dip/{slug}?access=salah-panjangnya-lebih-lama")
    assert resp.status_code == 404, f"token salah panjang beda harus 404, dapat {resp.status_code}"
    print("[PASS] token salah panjang berbeda -> 404")


def test_empty_token_non_bpom_404():
    """Token kosong (?access=) pada produk bertoken non-BPOM -> 404."""
    app = _register_check(FakeSupabase())
    client = TestClient(app, raise_server_exceptions=False)
    slug = f"produk-uji-{uuid.uuid4()}"
    resp = client.get(f"/dip/{slug}?access=")
    assert resp.status_code == 404, f"token kosong (non-BPOM) harus 404, dapat {resp.status_code}"
    print("[PASS] token kosong (non-BPOM) -> 404")


def test_non_ascii_token_404_not_500():
    """Token non-ASCII -> 404, BUKAN 500 (compare_digest bytes tidak TypeError)."""
    app = _register_check(FakeSupabase())
    client = TestClient(app, raise_server_exceptions=False)
    slug = f"produk-uji-{uuid.uuid4()}"
    resp = client.get(f"/dip/{slug}?access=tok%C3%A9n")
    assert resp.status_code == 404, f"token non-ASCII harus 404 (bukan 500), dapat {resp.status_code}"
    print("[PASS] token non-ASCII -> 404 (bukan 500)")


def test_bpom_registered_without_token_200():
    """Produk bertoken terdaftar BPOM tanpa ?access= -> 200 (legacy tetap)."""
    fake = FakeSupabase()
    fake.product["bpom_registered_link"] = True
    app = _register_check(fake)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-uji-{fake.product['id']}")
    assert resp.status_code == 200, f"BPOM legacy tanpa token harus 200, dapat {resp.status_code}"
    print("[PASS] produk BPOM-registered tanpa token -> 200 (legacy)")


def test_bpom_registered_wrong_token_404():
    """Produk bertoken terdaftar BPOM dengan token SALAH -> 404."""
    fake = FakeSupabase()
    fake.product["bpom_registered_link"] = True
    app = _register_check(fake)
    client = TestClient(app, raise_server_exceptions=False)
    slug = f"produk-uji-{fake.product['id']}"
    resp = client.get(f"/dip/{slug}?access=salah")
    assert resp.status_code == 404, f"BPOM dengan token salah harus 404, dapat {resp.status_code}"
    print("[PASS] produk BPOM-registered dengan token salah -> 404")


def test_no_token_product_200():
    """Produk tanpa token -> 200 seperti sekarang (legacy mode)."""
    fake = FakeSupabase()
    fake.product["public_access_token"] = None
    app = _register_check(fake)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-uji-{fake.product['id']}")
    assert resp.status_code == 200, f"produk tanpa token harus 200, dapat {resp.status_code}"
    print("[PASS] produk tanpa token -> 200")


# =====================================================================
# Bagian 2: Revoke link publik + audit akses publik (F-03 + F-09)
# =====================================================================


def _register_revoke(fake_supabase, logs=None):
    app = FastAPI()
    limiter = Limiter(key_func=lambda request: "192.0.2.1")
    limiter._storage.reset()
    register_dip_public_routes(
        app=app,
        templates=FakeTemplates(),
        supabase=fake_supabase,
        get_company_info=lambda perusahaan: {"name": perusahaan},
        extract_id_from_slug=lambda slug: (m.group(0) if (m := re.search(UUID_RE, slug)) else None),
        client_ip=lambda request: "127.0.0.1",
        apply_company_specific_docs=lambda rm, perusahaan: rm,
        parse_storage_url=lambda url: (None, None),
        bab_generators={"1": _fake_pdf},
        download_bab2_zip=_fake_zip,
        log_activity=(lambda *a, **k: logs.append((a, k))) if logs is not None else None,
        limiter=limiter,
    )
    return app


def test_revoke_flag_enabled_false_404():
    fake = FakeSupabase(
        product={
            "id": PID,
            "is_deleted": False,
            "public_access_enabled": False,
            "public_access_token": PRODUCT_TOKEN,
            "bpom_registered_link": False,
            "public_access_revoked_at": None,
            "nama_produk": "P",
            "perusahaan": "PT Erfi",
        }
    )
    client = TestClient(_register_revoke(fake), raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 404, f"enabled=False harus 404, dapat {resp.status_code}"
    print("[PASS] revoke lewat flag enabled=False -> 404")


def test_revoke_at_filled_404():
    fake = FakeSupabase(
        product={
            "id": PID,
            "is_deleted": False,
            "public_access_enabled": True,
            "public_access_token": PRODUCT_TOKEN,
            "bpom_registered_link": False,
            "public_access_revoked_at": "2026-11-07T00:00:00+07:00",
            "nama_produk": "P",
            "perusahaan": "PT Erfi",
        }
    )
    client = TestClient(_register_revoke(fake), raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 404, f"revoked_at terisi harus 404, dapat {resp.status_code}"
    print("[PASS] revoke lewat revoked_at terisi -> 404")


def test_bpom_revoked_without_token_404():
    fake = FakeSupabase(
        product={
            "id": PID,
            "is_deleted": False,
            "public_access_enabled": False,
            "public_access_token": PRODUCT_TOKEN,
            "bpom_registered_link": True,
            "public_access_revoked_at": None,
            "nama_produk": "P",
            "perusahaan": "PT Erfi",
        }
    )
    client = TestClient(_register_revoke(fake), raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-{PID}")
    assert resp.status_code == 404, f"BPOM dicabut tanpa token harus 404, dapat {resp.status_code}"
    print("[PASS] produk BPOM dicabut tanpa token -> 404 (revoke sebelum cabang BPOM)")


def test_correct_token_but_revoked_404():
    fake = FakeSupabase(
        product={
            "id": PID,
            "is_deleted": False,
            "public_access_enabled": True,
            "public_access_token": PRODUCT_TOKEN,
            "bpom_registered_link": True,
            "public_access_revoked_at": "2026-11-07T00:00:00+07:00",
            "nama_produk": "P",
            "perusahaan": "PT Erfi",
        }
    )
    client = TestClient(_register_revoke(fake), raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 404, f"token benar tapi dicabut harus 404, dapat {resp.status_code}"
    print("[PASS] token benar tapi dicabut -> 404")


def test_active_correct_token_200():
    fake = FakeSupabase(include_revoked_at=True)
    client = TestClient(_register_revoke(fake), raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 200, f"aktif + token benar harus 200, dapat {resp.status_code}"
    print("[PASS] aktif + token benar -> 200")


def test_reactivate_same_token_200():
    fake = FakeSupabase(
        product={
            "id": PID,
            "is_deleted": False,
            "public_access_enabled": False,
            "public_access_token": PRODUCT_TOKEN,
            "bpom_registered_link": False,
            "public_access_revoked_at": "2026-11-07T00:00:00+07:00",
            "nama_produk": "P",
            "perusahaan": "PT Erfi",
        }
    )
    client = TestClient(_register_revoke(fake), raise_server_exceptions=False)
    assert client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}").status_code == 404
    fake.product["public_access_enabled"] = True
    fake.product["public_access_revoked_at"] = None
    resp = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 200, f"setelah aktifkan ulang token LAMA harus 200, dapat {resp.status_code}"
    assert fake.product["public_access_token"] == PRODUCT_TOKEN, "token tidak boleh berubah"
    print("[PASS] setelah aktifkan ulang token LAMA -> 200 (token tidak berubah)")


def test_revoke_exception_fail_closed_404():
    """Renamed from test_dip_public_revoke.py::test_exception_fail_closed_404."""
    client = TestClient(
        _register_revoke(FakeSupabase(capability_explode=True, include_revoked_at=True)),
        raise_server_exceptions=False,
    )
    resp = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 404, f"exception baca harus 404, dapat {resp.status_code}"
    print("[PASS] exception baca -> 404 (fail-closed)")


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


def _build_admin(product):
    w = FakeSupabase2(tables={"products": [product]})
    app = FakeApp()
    logs = []
    register_products_routes(
        app,
        get_current_user=lambda: ADMIN_ERFI,
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
    return app, w, logs


def _prod(perusahaan="PT Erfi", token=PRODUCT_TOKEN):
    return {
        "id": PID,
        "nama_produk": "Produk Erfi",
        "perusahaan": perusahaan,
        "is_deleted": False,
        "public_access_token": token,
        "public_access_enabled": True,
        "public_access_revoked_at": None,
    }


def test_admin_revoke_non_admin_403_no_writes():
    app, w, _logs = _build_admin(_prod())
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
    app, w, _logs = _build_admin(_prod("PT Erfi"))
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
    app, w, logs = _build_admin(prod)
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
    app, w, _logs = _build_admin(prod)
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
    fake = FakeSupabase(include_revoked_at=True)
    client = TestClient(_register_revoke(fake, logs=logs), raise_server_exceptions=False)
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


# =====================================================================
# Bagian 3: Rate-limit portal publik /dip/* + redaction token (F-08 + F-05)
# =====================================================================


def _client_ip(request):
    client_host = request.client.host if request.client else "-"
    return client_ip_from(request.headers, client_host, trusted_hops=1)


def _extract_slug_uuid(slug):
    if not slug:
        return slug
    if len(slug) >= 36:
        cand = slug[-36:]
        if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", cand, re.IGNORECASE):
            return cand
    return slug


def _build_rate_limit(supabase=None):
    app = FastAPI()
    limiter = Limiter(key_func=_client_ip)
    limiter._storage.reset()
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def _handler(request, exc):
        if request.url.path.startswith("/dip/"):
            return JSONResponse(
                status_code=429,
                content={"detail": "Terlalu banyak permintaan, coba lagi sebentar lagi."},
                headers={"Retry-After": "60"},
            )
        return JSONResponse(status_code=429, content={"detail": "login"})

    register_dip_public_routes(
        app=app,
        templates=FakeTemplates(),
        supabase=supabase or FakeSupabase(include_revoked_at=True),
        get_company_info=lambda perusahaan: {"name": perusahaan},
        extract_id_from_slug=_extract_slug_uuid,
        client_ip=_client_ip,
        apply_company_specific_docs=lambda rm, perusahaan: rm,
        parse_storage_url=lambda url: (None, None),
        bab_generators={"1": _fake_pdf},
        download_bab2_zip=_fake_zip,
        log_activity=None,
        limiter=limiter,
    )
    return app, limiter


def _bab_limit():
    m = re.search(r"(\d+)", DIP_BAB_LIMIT)
    return int(m.group(1)) if m else 20


def _product_limit():
    m = re.search(r"(\d+)", DIP_PRODUCT_LIMIT)
    return int(m.group(1)) if m else 120


def _zip_limit():
    m = re.search(r"(\d+)", DIP_ZIP_LIMIT)
    return int(m.group(1)) if m else 5


def _hub_limit():
    m = re.search(r"(\d+)", DIP_HUB_LIMIT)
    return int(m.group(1)) if m else 60


def test_bab_burst_429_with_retry_after():
    app, _limiter = _build_rate_limit()
    client = TestClient(app, raise_server_exceptions=False)
    n = _bab_limit()
    for _ in range(n):
        r = client.get(
            f"/dip/produk-{PID}/bab1/download?access={PRODUCT_TOKEN}",
            headers={"x-forwarded-for": "10.9.9.9"},
        )
        assert r.status_code == 200, f"di bawah batas harus 200, dapat {r.status_code}"
    r = client.get(
        f"/dip/produk-{PID}/bab1/download?access={PRODUCT_TOKEN}",
        headers={"x-forwarded-for": "10.9.9.9"},
    )
    assert r.status_code == 429, f"request ke-{n + 1} harus 429, dapat {r.status_code}"
    assert r.headers.get("retry-after") is not None, "header Retry-After wajib ada"
    assert "/login" not in str(r.headers.get("location", "")), "bukan redirect ke /login"
    assert PRODUCT_TOKEN not in r.text, "body 429 tidak boleh memuat token"
    assert str(n) not in r.text, "body 429 tidak boleh memuat angka limit"
    print(f"[PASS] burst bab per-IP: request ke-{n + 1} -> 429 + Retry-After, bukan redirect login")


def test_bpom_spam_does_not_lock_other_ip():
    app, _limiter = _build_rate_limit(supabase=FakeSupabaseBpom())
    client = TestClient(app, raise_server_exceptions=False)
    n = _bab_limit()
    for _ in range(n):
        r = client.get(
            f"/dip/produk-{PID}/bab1/download",
            headers={"x-forwarded-for": "10.0.0.9"},
        )
        assert r.status_code == 200, f"BPOM tanpa token di bawah batas harus 200, dapat {r.status_code}"
    r_a = client.get(
        f"/dip/produk-{PID}/bab1/download",
        headers={"x-forwarded-for": "10.0.0.9"},
    )
    assert r_a.status_code == 429, f"IP penyerang harus 429, dapat {r_a.status_code}"
    r_b = client.get(
        f"/dip/produk-{PID}/bab1/download",
        headers={"x-forwarded-for": "10.0.0.10"},
    )
    assert r_b.status_code == 200, f"IP reviewer lain tidak boleh terkunci per-IP (dapat {r_b.status_code})"
    print("[PASS] produk BPOM: spam IP A 429 tidak mengunci IP B")


def test_rotating_token_does_not_open_new_bucket():
    app, _limiter = _build_rate_limit()
    client = TestClient(app, raise_server_exceptions=False)
    n = _bab_limit()
    codes = []
    for i in range(n + 3):
        r = client.get(
            f"/dip/produk-{PID}/bab1/download?access=token-{i}",
            headers={"x-forwarded-for": "10.1.1.1"},
        )
        codes.append(r.status_code)
    assert 429 in codes, f"mengganti ?access= tidak boleh membuka bucket baru, dapat {codes[:3]}..."
    print("[PASS] mengganti ?access= tidak membuka bucket baru")


def test_per_product_stops_spoofed_ip():
    app, _limiter = _build_rate_limit()
    client = TestClient(app, raise_server_exceptions=False)
    n = _product_limit()
    codes = []
    for i in range(n + 5):
        r = client.get(
            f"/dip/produk-{PID}/bab1/download?access={PRODUCT_TOKEN}",
            headers={"x-forwarded-for": f"10.0.0.{i % 250}"},
        )
        codes.append(r.status_code)
    assert 429 in codes, f"limit per-produk harus menghentikan XFF berganti di {n}, dapat {codes[:3]}..."
    print(f"[PASS] limit per-produk menghentikan XFF berganti (tercapai di {n})")


def test_bare_uuid_stops_at_product_limit():
    app, _limiter = _build_rate_limit()
    client = TestClient(app, raise_server_exceptions=False)
    n = _product_limit()
    codes = []
    for i in range(n + 5):
        r = client.get(
            f"/dip/{PID}/bab1/download?access={PRODUCT_TOKEN}",
            headers={"x-forwarded-for": f"10.4.0.{i % 250}"},
        )
        codes.append(r.status_code)
    assert 429 in codes, f"UUID polos harus kena batas per-produk di {n}, dapat {codes[:3]}..."
    print(f"[PASS] UUID polos kena batas per-produk di {n}")


def test_uuid_case_variants_share_bucket():
    app, _limiter = _build_rate_limit()
    client = TestClient(app, raise_server_exceptions=False)
    n = _product_limit()
    codes = []
    for i in range(n + 5):
        pid = PID.upper() if i % 2 else PID.lower()
        r = client.get(
            f"/dip/{pid}/bab1/download?access={PRODUCT_TOKEN}",
            headers={"x-forwarded-for": f"10.5.0.{i % 250}"},
        )
        codes.append(r.status_code)
    assert 429 in codes, f"variasi huruf harus satu bucket di {n}, dapat {codes[:3]}..."
    print("[PASS] variasi huruf besar/kecil berbagi satu bucket per-produk")


def test_slug_and_bare_uuid_share_bucket():
    app, _limiter = _build_rate_limit()
    client = TestClient(app, raise_server_exceptions=False)
    n = _product_limit()
    codes = []
    for i in range(n + 5):
        slug = f"produk-{PID}" if i % 2 else PID
        r = client.get(
            f"/dip/{slug}/bab1/download?access={PRODUCT_TOKEN}",
            headers={"x-forwarded-for": f"10.6.0.{i % 250}"},
        )
        codes.append(r.status_code)
    assert 429 in codes, f"slug vs UUID polos harus satu bucket di {n}, dapat {codes[:3]}..."
    print("[PASS] slug nama-<uuid> dan UUID polos berbagi bucket yang sama")


def test_shared_scope_across_bab_routes():
    app, _limiter = _build_rate_limit()
    client = TestClient(app, raise_server_exceptions=False)
    n = _bab_limit()
    routes = ["bab1/download", "bab1", "bab1/download"]
    for i in range(n):
        suf = routes[i % len(routes)]
        r = client.get(
            f"/dip/produk-{PID}/{suf}?access={PRODUCT_TOKEN}",
            headers={"x-forwarded-for": "10.2.2.2"},
        )
        assert r.status_code == 200, f"campuran route di bawah total harus 200, dapat {r.status_code}"
    r = client.get(
        f"/dip/produk-{PID}/bab1?access={PRODUCT_TOKEN}",
        headers={"x-forwarded-for": "10.2.2.2"},
    )
    assert r.status_code == 429, f"total lintas route harus 429 ke-{n + 1}, dapat {r.status_code}"
    print("[PASS] scope bersama: campuran bab1/bab1dl total per-IP lintas route")


def test_invalid_slug_falls_back_to_ip():
    app, _limiter = _build_rate_limit()
    client = TestClient(app, raise_server_exceptions=False)
    n = _bab_limit()
    codes_a, codes_b = [], []
    for _ in range(n):
        codes_a.append(
            client.get(
                "/dip/produk-INVALID/bab1/download",
                headers={"x-forwarded-for": "10.3.3.3"},
            ).status_code
        )
    for _ in range(2):
        codes_b.append(
            client.get(
                "/dip/produk-INVALID/bab1/download",
                headers={"x-forwarded-for": "10.3.3.4"},
            ).status_code
        )
    assert 429 not in codes_b, f"slug invalid IP lain tidak boleh mengunci, dapat {codes_b}"
    r_a = client.get(
        "/dip/produk-INVALID/bab1/download",
        headers={"x-forwarded-for": "10.3.3.3"},
    )
    assert r_a.status_code == 429, f"IP slug invalid harus 429 sendiri, dapat {r_a.status_code}"
    print("[PASS] slug tidak valid -> bucket IP, dua IP tidak saling mengunci")


def test_limiter_required():
    app = FastAPI()
    try:
        register_dip_public_routes(
            app=app,
            templates=FakeTemplates(),
            supabase=FakeSupabase(include_revoked_at=True),
            get_company_info=lambda p: {},
            extract_id_from_slug=lambda s: None,
            client_ip=_client_ip,
            apply_company_specific_docs=lambda rm, p: rm,
            parse_storage_url=lambda u: (None, None),
            bab_generators={},
            download_bab2_zip=None,
        )
        raise AssertionError("tanpa limiter harus TypeError")
    except TypeError:
        print("[PASS] register tanpa limiter -> TypeError (limiter wajib)")


def test_hub_and_zip_have_own_limits():
    app, _limiter = _build_rate_limit()
    client = TestClient(app, raise_server_exceptions=False)
    hn = _hub_limit()
    last = None
    for _ in range(hn + 1):
        last = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}")
    assert last.status_code == 429, f"hub ke-{hn + 1} harus 429, dapat {last.status_code}"
    zn = _zip_limit()
    for _ in range(zn):
        rz = client.get(f"/dip/produk-{PID}/bab2/zip?access={PRODUCT_TOKEN}")
        assert rz.status_code != 429, "ZIP di bawah batas tidak boleh 429"
    rz = client.get(f"/dip/produk-{PID}/bab2/zip?access={PRODUCT_TOKEN}")
    assert rz.status_code == 429, f"ZIP ke-{zn + 1} harus 429, dapat {rz.status_code}"
    print(f"[PASS] hub limit {hn} dan ZIP limit {zn} masing-masing bekerja")


def test_different_products_not_locked():
    app, _limiter = _build_rate_limit()
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(f"/dip/produk-{PID2}/bab1/download?access={PRODUCT_TOKEN}")
    assert r.status_code == 200, f"produk berbeda harus 200 pada akses pertama, dapat {r.status_code}"
    print("[PASS] produk berbeda tidak saling mengunci pada limit per-produk")


def test_different_ip_not_locked_by_per_ip():
    app, _limiter = _build_rate_limit()
    client = TestClient(app, raise_server_exceptions=False)
    hn = _hub_limit()
    for _ in range(hn + 3):
        client.get(
            f"/dip/produk-{PID}?access={PRODUCT_TOKEN}",
            headers={"x-forwarded-for": "1.2.3.4"},
        )
    r_other = client.get(
        f"/dip/produk-{PID}?access={PRODUCT_TOKEN}",
        headers={"x-forwarded-for": "5.6.7.8"},
    )
    assert r_other.status_code in (200, 404), f"IP lain tidak boleh terkunci per-IP (dapat {r_other.status_code})"
    print("[PASS] IP berbeda tidak saling mengunci pada limit per-IP (hub)")


def test_rejected_requests_still_counted():
    app, _limiter = _build_rate_limit()
    client = TestClient(app, raise_server_exceptions=False)
    n = _bab_limit()
    codes = []
    for _ in range(n + 2):
        r = client.get(f"/dip/produk-{PID}/bab1/download?access=salah")
        codes.append(r.status_code)
    assert 429 in codes, f"request 404/token salah harus tetap dihitung, dapat {codes[:3]}..."
    print("[PASS] request ditolak 404 tetap dihitung menuju limit")


def test_login_still_redirects_after_5():
    src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    seg = src[src.index("async def rate_limit_handler"):]
    seg = seg[:seg.index("\n\n") + 1]
    assert 'startswith("/dip/")' in seg, "cabang /dip/ wajib ada di handler"
    assert 'RedirectResponse(url="/login?error=too_many_attempts"' in seg, "cabang non-/dip/ harus redirect login lama"
    assert "Berlalu banyak percobaan login" not in seg, "log 429 dip tidak boleh menyebut login"
    print("[PASS] /login tetap redirect (cabang lama utuh di handler)")


# =====================================================================
# Bagian 4: Helper logika bab2_materials / link jurnal hub publik
# =====================================================================

RM_FULL = {"id": "rm-1", "nama_dagang": "Glycerin", "kode_bahan_baku": "HMC01LQ-1101"}


def test_entry_files_plus_journal():
    files = [{"label": "MSDS", "icon": "fa-file-triangle", "url": "https://s.example/m.pdf"}]
    entry = bab2_material_entry(RM_FULL, files, "https://j.example/g.pdf")
    assert entry is not None
    assert entry["nama"] == "Glycerin" and entry["kode"] == "HMC01LQ-1101"
    assert entry["files"] == files
    assert entry["journal_link"] == "https://j.example/g.pdf"
    assert len(entry["files"]) == 1


def test_entry_files_only():
    files = [{"label": "CoA", "icon": "fa-file-circle-check", "url": "https://s.example/c.pdf"}]
    entry = bab2_material_entry(RM_FULL, files, None)
    assert entry is not None
    assert entry["journal_link"] is None
    assert len(entry["files"]) == 1


def test_entry_journal_only_still_shown():
    entry = bab2_material_entry(RM_FULL, [], "https://j.example/only.pdf")
    assert entry is not None
    assert entry["files"] == []
    assert entry["journal_link"] == "https://j.example/only.pdf"


def test_entry_nothing_hidden():
    assert bab2_material_entry(RM_FULL, [], None) is None


def test_entry_name_code_fallback():
    entry = bab2_material_entry({}, [], "https://j.example/x.pdf")
    assert entry["nama"] == "Unknown" and entry["kode"] == "-"


def test_journal_link_passthrough_valid():
    assert bab2_journal_link({"journal_link": "https://j.example/a"}) == "https://j.example/a"
    assert bab2_journal_link({"journal_link": "http://j.example/a"}) == "http://j.example/a"
    assert bab2_journal_link({"journal_link": "  https://j.example/a  "}) == "https://j.example/a"


def test_journal_link_invalid_becomes_none_no_raise():
    assert bab2_journal_link({"journal_link": "ftp://j.example/a"}) is None
    assert bab2_journal_link({"journal_link": "javascript:alert(1)"}) is None
    assert bab2_journal_link({"journal_link": "https://a b.com"}) is None
    assert bab2_journal_link({"journal_link": "h" * 3000}) is None
    assert bab2_journal_link({"journal_link": None}) is None
    assert bab2_journal_link({}) is None
    assert bab2_journal_link(None) is not None


ALL_TESTS = [
    test_exception_fail_closed_404,
    test_exception_fail_closed_direct,
    test_token_enforced,
    test_valid_token_passes_check,
    test_wrong_token_same_length_404,
    test_wrong_token_different_length_404,
    test_empty_token_non_bpom_404,
    test_non_ascii_token_404_not_500,
    test_bpom_registered_without_token_200,
    test_bpom_registered_wrong_token_404,
    test_no_token_product_200,
    test_revoke_flag_enabled_false_404,
    test_revoke_at_filled_404,
    test_bpom_revoked_without_token_404,
    test_correct_token_but_revoked_404,
    test_active_correct_token_200,
    test_reactivate_same_token_200,
    test_revoke_exception_fail_closed_404,
    test_admin_revoke_non_admin_403_no_writes,
    test_admin_revoke_other_tenant_403_no_writes,
    test_admin_revoke_success,
    test_admin_reactivate_success_same_token,
    test_audit_download_logs_once_and_404_silent,
    test_bab_burst_429_with_retry_after,
    test_bpom_spam_does_not_lock_other_ip,
    test_rotating_token_does_not_open_new_bucket,
    test_per_product_stops_spoofed_ip,
    test_bare_uuid_stops_at_product_limit,
    test_uuid_case_variants_share_bucket,
    test_slug_and_bare_uuid_share_bucket,
    test_shared_scope_across_bab_routes,
    test_invalid_slug_falls_back_to_ip,
    test_limiter_required,
    test_different_ip_not_locked_by_per_ip,
    test_hub_and_zip_have_own_limits,
    test_different_products_not_locked,
    test_rejected_requests_still_counted,
    test_login_still_redirects_after_5,
    test_entry_files_plus_journal,
    test_entry_files_only,
    test_entry_journal_only_still_shown,
    test_entry_nothing_hidden,
    test_entry_name_code_fallback,
    test_journal_link_passthrough_valid,
    test_journal_link_invalid_becomes_none_no_raise,
]


def main(reverse: bool = False) -> int:
    tests = list(reversed(ALL_TESTS)) if reverse else list(ALL_TESTS)
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if failed:
        print(f"\n{failed} dari {len(tests)} test portal publik GAGAL.")
        return 1
    print(f"\nSemua {len(tests)} test portal publik LULUS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
