"""Pure-local tests for flash cookie percent-encoding and clean_visible_text.

Covers:
  - Round-trip ASCII flash messages identical to raw values.
  - Non-latin-1 flash messages (U+2060, U+2014, emoji, apostrophe, percent)
    never raise UnicodeEncodeError, produce latin-1-safe Set-Cookie headers,
    and decode back intact via get_flash_cookie and Jinja decode_flash filter.
  - Cookie attributes remain identical to Starlette's set_cookie / delete_cookie.
  - clean_visible_text strips all 9 target invisible Unicode characters and
    outer whitespace while preserving internal spaces and visible Indonesian text.
  - Route-level regression on POST/GET /products/{id}/edit with U+2060 and U+2014
    using a fake Supabase backend (no network/secrets).
  - Static AST/template invariants ensuring no raw flash cookie writers/readers remain.
"""
from __future__ import annotations

import ast
import asyncio
import glob
import html
import os
import sys
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

from app.flash_cookie import (  # noqa: E402
    FLASH_COOKIE_KEYS,
    clean_visible_text,
    decode_flash_value,
    delete_flash_cookie,
    encode_flash_value,
    get_flash_cookie,
    set_flash_cookie,
)
from app.products_routes import register_products_routes  # noqa: E402


INVISIBLE_CHARS = (
    "\u200b",
    "\u200c",
    "\u200d",
    "\u2060",
    "\ufeff",
    "\u00ad",
    "\u180e",
    "\u2028",
    "\u2029",
)

ADMIN_USER = {"id": "u-sintetis-1", "role": "admin", "perusahaan": "PT Erfi"}
PROD_ID = "00000000-0000-0000-0000-0000000000ff"


def _extract_cookie_pair(resp, key: str) -> tuple[str, str]:
    """Return (decoded_cookie_wire_value, raw_set_cookie_header) for cookie key."""
    headers = (
        resp.headers.get_list("set-cookie")
        if hasattr(resp.headers, "get_list")
        else [v for k, v in resp.headers.items() if k.lower() == "set-cookie"]
    )
    for hdr in headers:
        hdr.encode("latin-1")
        jar = SimpleCookie()
        jar.load(hdr)
        if key in jar:
            return jar[key].value, hdr
    raise AssertionError(f"Set-Cookie header for '{key}' not found in {headers!r}")


class _FakeQuery:
    def __init__(self, backend, table_name: str):
        self.backend = backend
        self.table_name = table_name
        self.op = "select"
        self.payload = None
        self.filters = []
        self._single = False

    def select(self, *args, **kwargs):
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def neq(self, col, val):
        self.filters.append(("neq", col, val))
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, n):
        return self

    def single(self):
        self._single = True
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = dict(payload)
        self.backend.updates.append((self.table_name, dict(payload)))
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = dict(payload)
        return self

    def execute(self):
        if self.op == "update" and self.table_name == "products":
            self.backend.product_row.update(self.payload)
            return SimpleNamespace(data=[dict(self.backend.product_row)])
        if self.table_name == "products":
            if self._single:
                return SimpleNamespace(data=dict(self.backend.product_row))
            return SimpleNamespace(data=[dict(self.backend.product_row)])
        return SimpleNamespace(data=[])


class _FakeSupabase:
    def __init__(self, product_row: dict):
        self.product_row = dict(product_row)
        self.updates: list[tuple[str, dict]] = []

    def table(self, name: str):
        return _FakeQuery(self, name)


class _FakeApp:
    def __init__(self):
        self.routes = {}

    def get(self, path, **kwargs):
        def deco(fn):
            self.routes[("GET", path)] = fn
            return fn
        return deco

    def post(self, path, **kwargs):
        def deco(fn):
            self.routes[("POST", path)] = fn
            return fn
        return deco


def _build_products_app(product_row: dict):
    fake_sb = _FakeSupabase(product_row)
    fake_app = _FakeApp()
    logs = []
    tpl = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
    tpl.env.filters["decode_flash"] = decode_flash_value
    tpl.env.filters["slugify"] = lambda v: str(v or "").lower().replace(" ", "-")

    async def _ed_count():
        return 0

    register_products_routes(
        fake_app,
        get_current_user=lambda: ADMIN_USER,
        supabase=fake_sb,
        templates=tpl,
        log_activity=lambda *a, **k: logs.append((a, k)),
        compute_status_na=lambda *a, **k: {},
        get_company_info=lambda p: {"nama": p},
        format_date_id=lambda d: str(d or ""),
        get_ed_notification_count=_ed_count,
        COMPANY_INFO={"PT Erfi": {"nama": "PT Erfi"}, "PT Heka": {"nama": "PT Heka"}},
        slugify=lambda v: str(v or "").lower().replace(" ", "-"),
        _resolve_variant_components=lambda *a, **k: [],
        _flag_bahan_aktif=lambda *a, **k: False,
        _build_diff_changes=lambda old, new, labels, files=None: [
            {"field": labels[k], "old": old.get(k), "new": new.get(k)}
            for k in labels
            if k in new and old.get(k) != new.get(k)
        ],
        _logo_render_width=lambda *a, **k: 100,
        _pdf_link_callback=lambda uri, rel: uri,
    )
    return fake_app, fake_sb, tpl, logs


# ---------------------------------------------------------------------------
# Unit tests: flash cookie helpers
# ---------------------------------------------------------------------------

def test_roundtrip_ascii_messages_identical():
    samples = [
        "File PDF berhasil dihapus.",
        "Data & dokumen DIP produk 'Serum Sintetis A' berhasil diperbarui!",
        "Gagal menyimpan produk 'Produk Uji-1'. Silakan coba lagi.",
        "Merk 'Merek Sintetis' sudah terdaftar di bawah produsen 'Produsen Uji'.",
        "100% selesai; cek tab Bab 2, #1.",
    ]
    for msg in samples:
        resp = RedirectResponse(url="/", status_code=303)
        set_flash_cookie(resp, "success_msg", msg)
        wire_val, hdr = _extract_cookie_pair(resp, "success_msg")
        hdr.encode("latin-1")
        req = SimpleNamespace(cookies={"success_msg": wire_val})
        assert get_flash_cookie(req, "success_msg") == msg
        assert decode_flash_value(wire_val) == msg


def test_non_latin1_characters_and_punctuation_roundtrip():
    samples = [
        "Data & dokumen DIP produk '\u2060Serum Uji' berhasil diperbarui!",
        "Produk 'Serum \u2014 Edisi Spesial' berhasil diperbarui!",
        "Berhasil \u2705 \U0001f680 catatan 'uji' 100% aman; lanjut!",
        "Nama mengandung kutip \"ganda\" dan 'tunggal' serta backslash \\.",
    ]
    for key in FLASH_COOKIE_KEYS:
        for msg in samples:
            resp = RedirectResponse(url="/", status_code=303)
            set_flash_cookie(resp, key, msg)
            wire_val, hdr = _extract_cookie_pair(resp, key)
            hdr.encode("latin-1")
            req = SimpleNamespace(cookies={key: wire_val})
            assert get_flash_cookie(req, key) == msg


def test_cookie_attributes_preserved():
    raw_resp = RedirectResponse(url="/", status_code=303)
    raw_resp.set_cookie("success_msg", "OK")
    _, raw_hdr = _extract_cookie_pair(raw_resp, "success_msg")

    helper_resp = RedirectResponse(url="/", status_code=303)
    set_flash_cookie(helper_resp, "success_msg", "OK")
    _, helper_hdr = _extract_cookie_pair(helper_resp, "success_msg")
    assert helper_hdr == raw_hdr

    # Verify explicit options are forwarded verbatim
    opts_resp = RedirectResponse(url="/", status_code=303)
    set_flash_cookie(opts_resp, "error_msg", "Gagal", max_age=60, httponly=True, path="/custom")
    _, opts_hdr = _extract_cookie_pair(opts_resp, "error_msg")
    assert "Max-Age=60" in opts_hdr
    assert "HttpOnly" in opts_hdr
    assert "Path=/custom" in opts_hdr

    # Delete helper matches delete_cookie
    del_raw = RedirectResponse(url="/", status_code=303)
    del_raw.delete_cookie("success_msg")
    _, del_raw_hdr = _extract_cookie_pair(del_raw, "success_msg")

    del_helper = RedirectResponse(url="/", status_code=303)
    delete_flash_cookie(del_helper, "success_msg")
    _, del_helper_hdr = _extract_cookie_pair(del_helper, "success_msg")
    assert del_helper_hdr == del_raw_hdr


def test_decode_edge_cases_and_legacy_unencoded():
    assert decode_flash_value(None) is None
    assert decode_flash_value("") == ""
    # Legacy cookie value written before encoding rollout should remain readable
    assert decode_flash_value("Produk berhasil diperbarui! 100% aman") == "Produk berhasil diperbarui! 100% aman"
    req_missing = SimpleNamespace(cookies={})
    assert get_flash_cookie(req_missing, "success_msg") is None
    assert get_flash_cookie(req_missing, "success_msg", "fallback") == "fallback"
    assert encode_flash_value("abc\u2060xyz").isascii()


# ---------------------------------------------------------------------------
# Unit tests: clean_visible_text
# ---------------------------------------------------------------------------

def test_clean_visible_text_strips_all_invisible_chars_and_outer_spaces():
    assert clean_visible_text(None) is None
    assert clean_visible_text("   ") == ""
    assert clean_visible_text("".join(INVISIBLE_CHARS) + "   ") == ""

    for ch in INVISIBLE_CHARS:
        assert clean_visible_text(f"{ch}Serum Uji") == "Serum Uji"
        assert clean_visible_text(f"Serum{ch} Uji") == "Serum Uji"
        assert clean_visible_text(f"Serum Uji{ch}") == "Serum Uji"
        assert clean_visible_text(f"  {ch}Serum{ch} Uji{ch}  ") == "Serum Uji"

    # Combined invisible characters + outer whitespace
    messy = " \t\u2060\ufeffSerum\u200b \u200cUji\u200d \u00adSintetis\u180e\u2028\u2029  "
    assert clean_visible_text(messy) == "Serum Uji Sintetis"


def test_clean_visible_text_preserves_normal_text_and_internal_spaces():
    normal_samples = [
        "Serum Wajah  Pagi - SPF 50+",
        "Krim Malam (\u00c9disi Khusus \u2014 Uji)",
        "PT Pelanggan Sintetis & Co.",
        "Bahan Aktif 10% (Grade A)",
    ]
    for s in normal_samples:
        assert clean_visible_text(s) == s


# ---------------------------------------------------------------------------
# Route-level regression test: POST /products/{id}/edit + GET /products/{id}/edit
# ---------------------------------------------------------------------------

def _post_edit_args(**overrides):
    base = {
        "request": SimpleNamespace(cookies={}, headers={}, url="http://test/products/edit"),
        "product_id": PROD_ID,
        "nama_produk": "Produk Awal",
        "perusahaan": "PT Erfi",
        "nama_customer": None,
        "sediaan": None,
        "warna": None,
        "netto": None,
        "kemasan": None,
        "no_na_produk": None,
        "status_na": "aktif",
        "tanggal_aktif_na": None,
        "acc_sampel": None,
        "tanggal_text_design": None,
        "teks_marketing": None,
        "cara_pakai": None,
        "peringatan": None,
        "penyimpanan": None,
        "status_progress": "R&D / Sample Phase",
        "brand_id": None,
        "no_notifikasi_file": None,
        "cara_pembuatan_file": None,
        "sistem_penomoran_batch_file": None,
        "spek_produk_jadi_file": None,
        "spek_pengemas_file": None,
        "laporan_uji_sig_file": None,
        "protokol_stabilitas_file": None,
        "hasil_stabilitas_file": None,
        "laporan_keamanan_file": None,
        "monitoring_efek_samping_file": None,
        "data_klaim_file": None,
        "desain_primer_file": None,
        "desain_sekunder_file": None,
        "formula_submitted": None,
        "raw_material_id": None,
        "percentage": None,
        "variant_id": None,
        "current_user": ADMIN_USER,
    }
    base.update(overrides)
    return base


def test_edit_product_route_strips_u2060_and_avoids_500():
    initial_row = {
        "id": PROD_ID,
        "nama_produk": "Produk Lama",
        "perusahaan": "PT Erfi",
        "nama_customer": None,
        "is_deleted": False,
    }
    fake_app, fake_sb, _, _ = _build_products_app(initial_row)
    post_fn = fake_app.routes[("POST", "/products/{product_id}/edit")]
    get_fn = fake_app.routes[("GET", "/products/{product_id}/edit")]

    resp = asyncio.run(post_fn(**_post_edit_args(
        nama_produk="\u2060Serum Uji Sintetis",
        nama_customer="  \u200bPT Pelanggan Sintetis\ufeff ",
    )))
    assert resp.status_code == 303
    wire_val, hdr = _extract_cookie_pair(resp, "success_msg")
    hdr.encode("latin-1")
    expected_msg = "Data & dokumen DIP produk 'Serum Uji Sintetis' berhasil diperbarui!"
    assert decode_flash_value(wire_val) == expected_msg

    # Verify DB payload received cleaned values
    assert fake_sb.updates
    _, upd_payload = fake_sb.updates[-1]
    assert upd_payload["nama_produk"] == "Serum Uji Sintetis"
    assert upd_payload["nama_customer"] == "PT Pelanggan Sintetis"

    # Simulate redirect follow to GET /products/{id}/edit and verify rendered HTML
    get_req = SimpleNamespace(
        cookies={"success_msg": wire_val},
        headers={},
        url=SimpleNamespace(path=f"/products/{PROD_ID}/edit"),
    )
    page_resp = asyncio.run(get_fn(get_req, PROD_ID, ADMIN_USER))
    html_body = page_resp.body.decode("utf-8")
    assert expected_msg in html.unescape(html_body)


def test_edit_product_route_visible_non_latin1_emdash_succeeds():
    initial_row = {
        "id": PROD_ID,
        "nama_produk": "Produk Lama",
        "perusahaan": "PT Erfi",
        "nama_customer": None,
        "is_deleted": False,
    }
    fake_app, fake_sb, _, _ = _build_products_app(initial_row)
    post_fn = fake_app.routes[("POST", "/products/{product_id}/edit")]
    get_fn = fake_app.routes[("GET", "/products/{product_id}/edit")]

    # Em-dash (U+2014) is visible non-latin-1, so clean_visible_text preserves it,
    # and flash cookie encoding must prevent UnicodeEncodeError (303, not 500).
    resp = asyncio.run(post_fn(**_post_edit_args(
        nama_produk="Serum \u2014 Edisi Uji",
    )))
    assert resp.status_code == 303
    wire_val, hdr = _extract_cookie_pair(resp, "success_msg")
    hdr.encode("latin-1")
    expected_msg = "Data & dokumen DIP produk 'Serum \u2014 Edisi Uji' berhasil diperbarui!"
    assert decode_flash_value(wire_val) == expected_msg

    get_req = SimpleNamespace(
        cookies={"success_msg": wire_val},
        headers={},
        url=SimpleNamespace(path=f"/products/{PROD_ID}/edit"),
    )
    page_resp = asyncio.run(get_fn(get_req, PROD_ID, ADMIN_USER))
    html_body = page_resp.body.decode("utf-8")
    assert expected_msg in html.unescape(html_body)


# ---------------------------------------------------------------------------
# Static invariants: no raw flash cookie writers/readers remain
# ---------------------------------------------------------------------------

def test_no_raw_flash_cookie_calls_in_app_or_templates():
    for path in sorted(glob.glob(str(ROOT / "app" / "*.py"))):
        if Path(path).name == "flash_cookie.py":
            continue
        src = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(src, filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("set_cookie", "delete_cookie"):
                    call_src = ast.unparse(node)
                    for fk in FLASH_COOKIE_KEYS:
                        assert fk not in call_src, f"Raw {node.func.attr} for {fk} in {path}:{node.lineno}"
                elif node.func.attr == "get" and "cookies" in ast.unparse(node.func.value):
                    call_src = ast.unparse(node)
                    for fk in FLASH_COOKIE_KEYS:
                        assert fk not in call_src, f"Raw cookies.get for {fk} in {path}:{node.lineno}"

    base_html = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    for fk in FLASH_COOKIE_KEYS:
        assert f"request.cookies.get('{fk}') | decode_flash" in base_html

    edit_html = (ROOT / "app" / "templates" / "edit_product.html").read_text(encoding="utf-8")
    for fk in ("error_msg", "success_msg"):
        assert f"request.cookies.get('{fk}') | decode_flash" in edit_html


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failures = []
    for name, func in tests:
        try:
            func()
            print(f"[PASS] {name}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
    if failures:
        return 1
    print(f"PASS {len(tests)} flash cookie & visible text tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
