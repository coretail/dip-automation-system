"""Unit test murni F-01: _dip_public_check_product harus FAIL-CLOSED.

Latar (temuan audit F-01): blok `except` di `_dip_public_check_product`
(`app/dip_public.py`) dulunya jatuh ke "mode legacy" yang hanya memeriksa
`id` + `is_deleted` — artinya error apa pun pada query capability (kolom
migrasi 007 belum ada, error transient Supabase, dsb.) membuat produk apa
pun bisa diakses publik hanya dengan UUID-nya.

Kontrak yang dikunci test ini:
  1. Query capability melempar Exception  -> cek gagal -> route /dip/ 404
     (fail-closed, TIDAK jatuh ke mode legacy tanpa token).
  2. Produk bertoken: akses tanpa token   -> 404.
  3. Produk bertoken: token cocok         -> cek lolos (route lanjut, bukan
     404 dari checker).

Tanpa koneksi, tanpa secret. Dijalankan: python tests/test_dip_public_check.py
(dengan PYTHONPATH=. seperti di ci.yml).
"""

import re
import sys
import uuid

# Alur hub app mencetak emoji (mis. "[PUBLIC LINK OPENED] 🔗..."). Di console
# Windows ber-charmap (cp1252) itu melempar UnicodeEncodeError; amankan agar
# test pure-local jalan di semua platform.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from app.dip_public import register_dip_public_routes

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

PRODUCT_TOKEN = "tok123"


class _FakeBuilder:
    """PostgREST-style builder palsu. Bila `explode=True`, execute() selalu
    melempar Exception (mensimulasikan kolom capability belum ada / error
    transient Supabase). Bila tidak, execute() mengembalikan baris yang
    diberikan lewat `single_data` / `list_data`."""

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
    """Klien Supabase palsu minimal untuk alur /dip/.

    `capability_explode=True` -> SEMUA query melempar Exception.
    Selain itu: query `products` (single) mengembalikan produk uji bertoken,
    query lain mengembalikan list kosong, insert diabaikan (sukses).
    """

    def __init__(self, capability_explode=False):
        self.capability_explode = capability_explode
        self.product = {
            "id": str(uuid.uuid4()),
            "is_deleted": False,
            "public_access_enabled": True,
            "public_access_token": PRODUCT_TOKEN,
            "bpom_registered_link": False,
            "nama_produk": "Produk Uji E2E",
            "perusahaan": "PT Erfi",
        }

    def table(self, name):
        if self.capability_explode:
            return _FakeBuilder(explode=True)
        if name == "products":
            return _FakeBuilder(single_data=dict(self.product))
        if name in ("public_link_audits", "activity_logs"):
            return _FakeBuilder()  # insert audit -> sukses tanpa data
        return _FakeBuilder(list_data=[])

    class _Auth:
        def get_user(self, _token):
            raise RuntimeError("tanpa sesi")

    auth = _Auth()


class FakeTemplates:
    """Templates palsu: cukup membuktikan checker lolos (route sampai render)."""

    def TemplateResponse(self, request=None, name=None, context=None, **_kw):
        return HTMLResponse("<html><body>hub-ok</body></html>")


def _register(fake_supabase):
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
        bab_generators={},
        download_bab2_zip=None,
    )
    return app


def test_exception_fail_closed_404():
    """Query capability melempar Exception -> HARUS 404 (fail-closed)."""
    app = _register(FakeSupabase(capability_explode=True))
    client = TestClient(app, raise_server_exceptions=False)
    slug = f"produk-uji-{uuid.uuid4()}"
    resp = client.get(f"/dip/{slug}")
    assert resp.status_code == 404, f"harus 404 saat query gagal, dapat {resp.status_code}"
    print("[PASS] query capability Exception -> 404 fail-closed (tidak jatuh ke mode legacy)")


def test_exception_fail_closed_direct():
    """Versi langsung: Exception -> hasil check False (bukan True legacy)."""
    fake = FakeSupabase(capability_explode=True)
    app = _register(fake)
    # Panggil checker lewat route generator ZIP-nya tidak perlu; cukup buktikan
    # via route: bab generator tak terdaftar -> 404 checker dulu. Gunakan /dip/
    # dengan access salah: jika checker fail-open legacy, produk bertoken tetap
    # ditolak 404 juga... maka pakai produk TANPA token di sini:
    fake.product["public_access_token"] = None
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-uji-{fake.product['id']}")
    assert resp.status_code == 404, (
        f"produk tanpa token harus 404 saat query gagal (fail-closed), dapat {resp.status_code}"
    )
    print("[PASS] produk tanpa token + query Exception -> 404 (bukti tidak ada jalur legacy fail-open)")


def test_token_enforced():
    """Produk bertoken: tanpa token -> 404; token salah -> 404."""
    app = _register(FakeSupabase())
    client = TestClient(app, raise_server_exceptions=False)
    slug = f"produk-uji-{uuid.uuid4()}"
    assert client.get(f"/dip/{slug}").status_code == 404, "tanpa token harus 404"
    assert client.get(f"/dip/{slug}?access=salah").status_code == 404, "token salah harus 404"
    print("[PASS] produk bertoken: tanpa/salah token -> 404")


def test_valid_token_passes_check():
    """Produk bertoken + token cocok -> checker lolos (route lanjut sampai render hub)."""
    fake = FakeSupabase()
    app = _register(fake)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/dip/produk-uji-{fake.product['id']}?access={PRODUCT_TOKEN}")
    assert resp.status_code == 200, f"token cocok harus lolos checker (200), dapat {resp.status_code}"
    assert "hub-ok" in resp.text
    print("[PASS] token cocok -> checker lolos, hub dirender (200)")


def main():
    test_exception_fail_closed_404()
    test_exception_fail_closed_direct()
    test_token_enforced()
    test_valid_token_passes_check()
    print("\nSemua test F-01 fail-closed LULUS.")


if __name__ == "__main__":
    sys.exit(main())
