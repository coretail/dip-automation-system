"""Unit test murni F-08 + F-05: rate-limit portal publik /dip/* + redaction token.

Tanpa koneksi, tanpa secret. Dijalankan: python tests/test_dip_public_rate_limit.py
(dengan PYTHONPATH=. seperti di ci.yml).
"""
import logging
import os
import re
import sys
import uuid

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from slowapi import Limiter  # noqa: E402

from app.dip_public import DIP_BAB_LIMIT, DIP_HUB_LIMIT, DIP_PRODUCT_LIMIT, DIP_ZIP_LIMIT, register_dip_public_routes  # noqa: E402

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
PRODUCT_TOKEN = "tok123"
PID = str(uuid.uuid4())
PID2 = str(uuid.uuid4())


def _client_ip(request):
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "-"


def _extract_slug_uuid(slug):
    # Sama seperti app/main.py extract_id_from_slug: ambil 36 char terakhir
    # bila UUID valid, selain itu kembalikan slug (lalu handler 404).
    if not slug:
        return slug
    if len(slug) >= 36:
        cand = slug[-36:]
        if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', cand, re.IGNORECASE):
            return cand
    return slug


class _FakeBuilder:
    def __init__(self, single_data=None, list_data=None):
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
        return type("R", (), {"data": self._single_data if self._single_data is not None else self._list_data})()


class FakeSupabase:
    def __init__(self):
        self.product = {
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


async def _fake_pdf(pid, u):
    from fastapi.responses import Response
    return Response(content=b"%PDF", media_type="application/pdf")


async def _fake_zip(pid, u):
    from fastapi.responses import Response
    return Response(content=b"PK", media_type="application/zip")


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


def _build(supabase=None):
    from fastapi import Request as _Req  # noqa
    from fastapi.responses import JSONResponse as _JR  # noqa
    from slowapi.errors import RateLimitExceeded as _RLE  # noqa

    app = FastAPI()
    limiter = Limiter(key_func=_client_ip)
    app.state.limiter = limiter

    @app.exception_handler(_RLE)
    async def _handler(request, exc):
        if request.url.path.startswith("/dip/"):
            return _JR(status_code=429,
                       content={"detail": "Terlalu banyak permintaan, coba lagi sebentar lagi."},
                       headers={"Retry-After": "60"})
        return _JR(status_code=429, content={"detail": "login"})

    register_dip_public_routes(
        app=app,
        templates=FakeTemplates(),
        supabase=supabase or FakeSupabase(),
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
    app, limiter = _build()
    client = TestClient(app, raise_server_exceptions=False)
    n = _bab_limit()
    for _ in range(n):
        r = client.get(f"/dip/produk-{PID}/bab1/download?access={PRODUCT_TOKEN}",
                       headers={"x-forwarded-for": "10.9.9.9"})
        assert r.status_code == 200, f"di bawah batas harus 200, dapat {r.status_code}"
    r = client.get(f"/dip/produk-{PID}/bab1/download?access={PRODUCT_TOKEN}",
                   headers={"x-forwarded-for": "10.9.9.9"})
    assert r.status_code == 429, f"request ke-{n + 1} harus 429, dapat {r.status_code}"
    assert r.headers.get("retry-after") is not None, "header Retry-After wajib ada"
    assert "/login" not in str(r.headers.get("location", "")), "bukan redirect ke /login"
    assert PRODUCT_TOKEN not in r.text, "body 429 tidak boleh memuat token"
    assert str(n) not in r.text, "body 429 tidak boleh memuat angka limit"
    print(f"[PASS] burst bab per-IP: request ke-{n + 1} -> 429 + Retry-After, bukan redirect login")


def test_bpom_spam_does_not_lock_other_ip():
    app, limiter = _build(supabase=FakeSupabaseBpom())
    client = TestClient(app, raise_server_exceptions=False)
    n = _bab_limit()
    for _ in range(n):
        r = client.get(f"/dip/produk-{PID}/bab1/download",
                       headers={"x-forwarded-for": "10.0.0.9"})
        assert r.status_code == 200, f"BPOM tanpa token di bawah batas harus 200, dapat {r.status_code}"
    r_a = client.get(f"/dip/produk-{PID}/bab1/download",
                     headers={"x-forwarded-for": "10.0.0.9"})
    assert r_a.status_code == 429, f"IP penyerang harus 429, dapat {r_a.status_code}"
    r_b = client.get(f"/dip/produk-{PID}/bab1/download",
                     headers={"x-forwarded-for": "10.0.0.10"})
    assert r_b.status_code == 200, f"IP reviewer lain tidak boleh terkunci per-IP (dapat {r_b.status_code})"
    print("[PASS] produk BPOM: spam IP A 429 tidak mengunci IP B")


def test_rotating_token_does_not_open_new_bucket():
    app, limiter = _build()
    client = TestClient(app, raise_server_exceptions=False)
    n = _bab_limit()
    codes = []
    for i in range(n + 3):
        r = client.get(f"/dip/produk-{PID}/bab1/download?access=token-{i}",
                       headers={"x-forwarded-for": "10.1.1.1"})
        codes.append(r.status_code)
    assert 429 in codes, f"mengganti ?access= tidak boleh membuka bucket baru, dapat {codes[:3]}..."
    print("[PASS] mengganti ?access= tidak membuka bucket baru")


def test_per_product_stops_spoofed_ip():
    app, limiter = _build()
    client = TestClient(app, raise_server_exceptions=False)
    n = _product_limit()
    codes = []
    for i in range(n + 5):
        r = client.get(f"/dip/produk-{PID}/bab1/download?access={PRODUCT_TOKEN}",
                       headers={"x-forwarded-for": f"10.0.0.{i % 250}"})
        codes.append(r.status_code)
    assert 429 in codes, f"limit per-produk harus menghentikan XFF berganti di {n}, dapat {codes[:3]}..."
    print(f"[PASS] limit per-produk menghentikan XFF berganti (tercapai di {n})")


def test_bare_uuid_stops_at_product_limit():
    app, limiter = _build()
    client = TestClient(app, raise_server_exceptions=False)
    n = _product_limit()
    codes = []
    for i in range(n + 5):
        r = client.get(f"/dip/{PID}/bab1/download?access={PRODUCT_TOKEN}",
                       headers={"x-forwarded-for": f"10.4.0.{i % 250}"})
        codes.append(r.status_code)
    assert 429 in codes, f"UUID polos harus kena batas per-produk di {n}, dapat {codes[:3]}..."
    print(f"[PASS] UUID polos kena batas per-produk di {n}")


def test_uuid_case_variants_share_bucket():
    app, limiter = _build()
    client = TestClient(app, raise_server_exceptions=False)
    n = _product_limit()
    codes = []
    for i in range(n + 5):
        pid = PID.upper() if i % 2 else PID.lower()
        r = client.get(f"/dip/{pid}/bab1/download?access={PRODUCT_TOKEN}",
                       headers={"x-forwarded-for": f"10.5.0.{i % 250}"})
        codes.append(r.status_code)
    assert 429 in codes, f"variasi huruf harus satu bucket di {n}, dapat {codes[:3]}..."
    print("[PASS] variasi huruf besar/kecil berbagi satu bucket per-produk")


def test_slug_and_bare_uuid_share_bucket():
    app, limiter = _build()
    client = TestClient(app, raise_server_exceptions=False)
    n = _product_limit()
    codes = []
    for i in range(n + 5):
        slug = f"produk-{PID}" if i % 2 else PID
        r = client.get(f"/dip/{slug}/bab1/download?access={PRODUCT_TOKEN}",
                       headers={"x-forwarded-for": f"10.6.0.{i % 250}"})
        codes.append(r.status_code)
    assert 429 in codes, f"slug vs UUID polos harus satu bucket di {n}, dapat {codes[:3]}..."
    print("[PASS] slug nama-<uuid> dan UUID polos berbagi bucket yang sama")


def test_shared_scope_across_bab_routes():
    app, limiter = _build()
    client = TestClient(app, raise_server_exceptions=False)
    n = _bab_limit()
    routes = ["bab1/download", "bab1", "bab1/download"]
    for i in range(n):
        suf = routes[i % len(routes)]
        r = client.get(f"/dip/produk-{PID}/{suf}?access={PRODUCT_TOKEN}",
                       headers={"x-forwarded-for": "10.2.2.2"})
        assert r.status_code == 200, f"campuran route di bawah total harus 200, dapat {r.status_code}"
    r = client.get(f"/dip/produk-{PID}/bab1?access={PRODUCT_TOKEN}",
                   headers={"x-forwarded-for": "10.2.2.2"})
    assert r.status_code == 429, f"total lintas route harus 429 ke-{n + 1}, dapat {r.status_code}"
    print("[PASS] scope bersama: campuran bab1/bab1dl total per-IP lintas route")


def test_invalid_slug_falls_back_to_ip():
    app, limiter = _build()
    client = TestClient(app, raise_server_exceptions=False)
    n = _bab_limit()
    codes_a, codes_b = [], []
    for _ in range(n):
        codes_a.append(client.get("/dip/produk-INVALID/bab1/download",
                                  headers={"x-forwarded-for": "10.3.3.3"}).status_code)
    for _ in range(2):
        codes_b.append(client.get("/dip/produk-INVALID/bab1/download",
                                  headers={"x-forwarded-for": "10.3.3.4"}).status_code)
    assert 429 not in codes_b, f"slug invalid IP lain tidak boleh mengunci, dapat {codes_b}"
    r_a = client.get("/dip/produk-INVALID/bab1/download",
                     headers={"x-forwarded-for": "10.3.3.3"})
    assert r_a.status_code == 429, f"IP slug invalid harus 429 sendiri, dapat {r_a.status_code}"
    print("[PASS] slug tidak valid -> bucket IP, dua IP tidak saling mengunci")


def test_limiter_required():
    app = FastAPI()
    try:
        register_dip_public_routes(
            app=app, templates=FakeTemplates(), supabase=FakeSupabase(),
            get_company_info=lambda p: {}, extract_id_from_slug=lambda s: None,
            client_ip=_client_ip, apply_company_specific_docs=lambda rm, p: rm,
            parse_storage_url=lambda u: (None, None), bab_generators={},
            download_bab2_zip=None,
        )
        raise AssertionError("tanpa limiter harus TypeError")
    except TypeError:
        print("[PASS] register tanpa limiter -> TypeError (limiter wajib)")


def test_hub_and_zip_have_own_limits():
    app, limiter = _build()
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
    app, limiter = _build()
    client = TestClient(app, raise_server_exceptions=False)
    # produk kedua (PID2) belum pernah diakses: request pertama harus 200,
    # membuktikan key per-produk terisolasi dari produk pertama.
    r = client.get(f"/dip/produk-{PID2}/bab1/download?access={PRODUCT_TOKEN}")
    assert r.status_code == 200, f"produk berbeda harus 200 pada akses pertama, dapat {r.status_code}"
    print("[PASS] produk berbeda tidak saling mengunci pada limit per-produk")


def test_different_ip_not_locked_by_per_ip():
    app, limiter = _build()
    client = TestClient(app, raise_server_exceptions=False)
    hn = _hub_limit()
    for _ in range(hn + 3):
        client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}",
                   headers={"x-forwarded-for": "1.2.3.4"})
    r_other = client.get(f"/dip/produk-{PID}?access={PRODUCT_TOKEN}",
                         headers={"x-forwarded-for": "5.6.7.8"})
    assert r_other.status_code in (200, 404), f"IP lain tidak boleh terkunci per-IP (dapat {r_other.status_code})"
    print("[PASS] IP berbeda tidak saling mengunci pada limit per-IP (hub)")


def test_rejected_requests_still_counted():
    app, limiter = _build()
    client = TestClient(app, raise_server_exceptions=False)
    n = _bab_limit()
    codes = []
    for _ in range(n + 2):
        r = client.get(f"/dip/produk-{PID}/bab1/download?access=salah")
        codes.append(r.status_code)
    assert 429 in codes, f"request 404/token salah harus tetap dihitung, dapat {codes[:3]}..."
    print("[PASS] request ditolak 404 tetap dihitung menuju limit")


def test_login_still_redirects_after_5():
    # Verifikasi perilaku handler lama via ekstraksi sumber (import app.main
    # ditolak guard G-11 di mesin lokal yang memiliki .env; di clone CI tanpa
    # .env import aman dan cabang /login tetap redirect).
    import pathlib
    src = pathlib.Path("app/main.py").read_text(encoding="utf-8")
    seg = src[src.index("async def rate_limit_handler"):]
    seg = seg[:seg.index("\n\n") + 1]
    assert 'startswith("/dip/")' in seg, "cabang /dip/ wajib ada di handler"
    assert 'RedirectResponse(url="/login?error=too_many_attempts"' in seg, "cabang non-/dip/ harus redirect login lama"
    assert 'Berlalu banyak percobaan login' not in seg, "log 429 dip tidak boleh menyebut login"
    print("[PASS] /login tetap redirect (cabang lama utuh di handler)")


def main():
    test_bab_burst_429_with_retry_after()
    test_bpom_spam_does_not_lock_other_ip()
    test_rotating_token_does_not_open_new_bucket()
    test_per_product_stops_spoofed_ip()
    test_bare_uuid_stops_at_product_limit()
    test_uuid_case_variants_share_bucket()
    test_slug_and_bare_uuid_share_bucket()
    test_shared_scope_across_bab_routes()
    test_invalid_slug_falls_back_to_ip()
    test_limiter_required()
    test_different_ip_not_locked_by_per_ip()
    test_hub_and_zip_have_own_limits()
    test_different_products_not_locked()
    test_rejected_requests_still_counted()
    test_login_still_redirects_after_5()
    print("\nSemua test rate-limit publik LULUS.")


if __name__ == "__main__":
    main()
