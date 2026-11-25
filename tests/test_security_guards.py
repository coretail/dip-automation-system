"""Unit test gabungan security guards (pure-local, tanpa koneksi/secret):
  1. app/security.py (assert_same_tenant) & app/static/common.js (escapeHtml via Node)
  2. app/file_validation.py (validate_pdf_bytes)
  3. app/client_ip.py (client_ip_from SEC-05)
  4. app/safe_fetch.py (guard SSRF E-04, httpx.MockTransport)
  5. app/templates/base.html (guard presigned URL cache-bust & selektor .r2.dev/)

Digabungkan pada Task 10 dari:
  - test_security_helpers.py
  - test_upload_validation.py
  - test_client_ip.py
  - test_safe_fetch.py
  - test_base_cachebust.py

Jalankan: python tests/test_security_guards.py
"""
import asyncio
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402

from app.client_ip import client_ip_from  # noqa: E402
from app.file_validation import MAX_PDF_SIZE, validate_pdf_bytes  # noqa: E402
from app.safe_fetch import (  # noqa: E402
    MAX_BYTES,
    build_allowed_hosts,
    fetch_storage_bytes,
    is_allowed_storage_url,
)
from app.security import assert_same_tenant  # noqa: E402


# =====================================================================
# Bagian 1: app.security & common.js escapeHtml
# =====================================================================


def test_admin_bypasses_tenant_check():
    user = {"role": "admin", "perusahaan": "PT Erfi"}
    assert assert_same_tenant(user, {"perusahaan": "PT Heka"}) is True


def test_same_company_allowed():
    user = {"role": "staff", "perusahaan": "PT Erfi"}
    assert assert_same_tenant(user, {"perusahaan": "PT Erfi"}) is True


def test_cross_tenant_denied():
    user = {"role": "staff", "perusahaan": "PT Erfi"}
    assert assert_same_tenant(user, {"perusahaan": "PT Heka"}) is False


def test_legacy_null_user_company_allowed():
    user = {"role": "staff", "perusahaan": None}
    assert assert_same_tenant(user, {"perusahaan": "PT Heka"}) is True


def test_legacy_null_row_company_allowed():
    user = {"role": "staff", "perusahaan": "PT Erfi"}
    assert assert_same_tenant(user, {"perusahaan": None}) is True


def test_requested_company_mismatch_denied():
    user = {"role": "staff", "perusahaan": "PT Erfi"}
    assert assert_same_tenant(user, {"perusahaan": "PT Erfi"}, new_company="PT Heka") is False


def test_requested_company_match_allowed():
    user = {"role": "staff", "perusahaan": "PT Erfi"}
    assert assert_same_tenant(user, {"perusahaan": "PT Erfi"}, new_company="PT Erfi") is True


def test_blank_requested_company_denied_for_tenant_user():
    user = {"role": "staff", "perusahaan": "PT Erfi"}
    for blank in ("   ", "\t", " \n "):
        assert assert_same_tenant(user, {"perusahaan": "PT Erfi"}, new_company=blank) is False
        assert assert_same_tenant(user, None, new_company=blank) is False


def test_blank_requested_company_does_not_lock_out_admin_or_legacy_user():
    admin = {"role": "admin", "perusahaan": "PT Erfi"}
    legacy = {"role": "staff", "perusahaan": None}
    assert assert_same_tenant(admin, {"perusahaan": "PT Erfi"}, new_company="   ") is True
    assert assert_same_tenant(legacy, {"perusahaan": "PT Heka"}, new_company="   ") is True


def test_none_requested_company_means_no_company_change():
    user = {"role": "staff", "perusahaan": "PT Erfi"}
    assert assert_same_tenant(user, {"perusahaan": "PT Erfi"}, new_company=None) is True


def test_sample_rows_use_company_key():
    user = {"role": "staff", "perusahaan": "PT Erfi"}
    assert assert_same_tenant(user, {"company": "PT Heka"}) is False
    assert assert_same_tenant(user, {"company": "erfi"}) is True


def test_company_normalization_ignores_pt_prefix_and_case():
    user = {"role": "staff", "perusahaan": "PT Erfi"}
    assert assert_same_tenant(user, {"perusahaan": "erfi"}) is True
    assert assert_same_tenant(user, {"perusahaan": "  PT ERFI "}) is True
    assert assert_same_tenant(user, {"perusahaan": "PT Heka"}, new_company="pt erfi") is False


def _run_escape_html(values):
    """Jalankan app/static/common.js di Node dan kembalikan hasil escapeHtml."""
    script = (
        "global.window = {};"
        "require(process.argv[1]);"
        "const vals = JSON.parse(process.argv[2]);"
        "console.log(JSON.stringify(vals.map(v => window.escapeHtml(v))));"
    )
    out = subprocess.run(
        ["node", "-e", script, str(ROOT / "app" / "static" / "common.js"), json.dumps(values)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_common_js_escape_html_escapes_quotes_for_attribute_context():
    if shutil.which("node") is None:
        print("SKIP common.js (node tidak tersedia)")
        return
    payload = 'x" autofocus onfocus="alert(1)" y="'
    got = _run_escape_html([payload, "a'b", "<b>&</b>", None, 0, "aman"])
    assert '"' not in got[0] and "&quot;" in got[0], got[0]
    assert got[1] == "a&#39;b", got[1]
    assert got[2] == "&lt;b&gt;&amp;&lt;/b&gt;", got[2]
    assert got[3] == "" and got[4] == "0" and got[5] == "aman", got[3:]


# =====================================================================
# Bagian 2: app.file_validation (validate_pdf_bytes)
# =====================================================================


def test_valid_pdf_accepted():
    data = b"%PDF-1.4\n" + b"x" * 100
    assert validate_pdf_bytes(data, "doc.pdf") is None


def test_empty_rejected():
    assert validate_pdf_bytes(b"", "doc.pdf") is not None


def test_non_pdf_rejected():
    data = b"not a pdf"
    assert validate_pdf_bytes(data, "doc.pdf") is not None


def test_oversized_rejected():
    data = b"%PDF-1.4\n" + b"x" * (MAX_PDF_SIZE + 1)
    assert validate_pdf_bytes(data, "doc.pdf") is not None


def test_exact_limit_accepted():
    data = b"%PDF-1.4\n" + b"x" * (MAX_PDF_SIZE - len(b"%PDF-1.4\n"))
    assert validate_pdf_bytes(data, "doc.pdf") is None


def test_wrong_magic_bytes_rejected():
    data = b"XPDF" + b"x" * 100
    assert validate_pdf_bytes(data, "doc.pdf") is not None


# =====================================================================
# Bagian 3: app.client_ip (SEC-05)
# =====================================================================


def _h(xff, client="203.0.113.7", real=None, hops=1):
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    if real is not None:
        headers["x-real-ip"] = real
    return client_ip_from(headers, client, hops)


def test_single_entry_hops1():
    assert _h("1.2.3.4", hops=1) == "1.2.3.4"
    print("[OK] '1.2.3.4' hops=1 -> 1.2.3.4")


def test_spoof_ignored_last_valid_wins():
    assert _h("spoof, 9.9.9.9", hops=1) == "9.9.9.9"
    print("[OK] 'spoof, 9.9.9.9' -> entri terakhir (9.9.9.9), spoof diabaikan")


def test_multi_hop_indexing():
    assert _h("1.1.1.1, 2.2.2.2, 3.3.3.3", hops=1) == "3.3.3.3"
    assert _h("1.1.1.1, 2.2.2.2, 3.3.3.3", hops=2) == "2.2.2.2"
    assert _h("1.1.1.1, 2.2.2.2, 3.3.3.3", hops=3) == "1.1.1.1"
    print("[OK] multi-hop: hops=1->3.3.3.3, hops=2->2.2.2.2, hops=3->1.1.1.1")


def test_hops_greater_than_entries_uses_first():
    assert _h("8.8.8.8", hops=5) == "8.8.8.8"
    print("[OK] hops > jumlah entri -> entri pertama")


def test_empty_header_falls_back_to_real_ip():
    assert _h(None, client="203.0.113.7", real="7.7.7.7") == "7.7.7.7"
    print("[OK] XFF kosong -> X-Real-IP valid")


def test_empty_header_falls_back_to_client_host():
    assert _h(None, client="203.0.113.7", real=None) == "203.0.113.7"
    print("[OK] XFF/X-Real kosong -> client_host")


def test_all_empty_returns_dash():
    assert _h(None, client=None, real=None) == "-"
    print("[OK] semua kosong -> '-'")


def test_invalid_entries_fall_back():
    assert _h("abc", client="203.0.113.7", real="6.6.6.6", hops=1) == "6.6.6.6"
    assert _h("1.2.3.4:80", client="203.0.113.7", real=None, hops=1) == "203.0.113.7"
    assert _h("<script>", client="203.0.113.7", real="5.5.5.5", hops=1) == "5.5.5.5"
    assert _h("<script>", client="203.0.113.7", real=None, hops=1) == "203.0.113.7"
    print("[OK] entri tidak valid (abc, dengan-port, <script>) -> fallback aman")


def test_ipv6_valid():
    assert _h("2001:db8::1", client="203.0.113.7", hops=1) == "2001:db8::1"
    assert _h("1.1.1.1, 2001:db8::2", client="203.0.113.7", hops=1) == "2001:db8::2"
    print("[OK] IPv6 valid ditangani")


def test_trusted_hops_zero_uses_client_host():
    assert _h("9.9.9.9", client="203.0.113.7", real="7.7.7.7", hops=0) == "203.0.113.7"
    print("[OK] trusted_hops=0 -> client_host (XFF/X-Real diabaikan)")


# =====================================================================
# Bagian 4: app.safe_fetch (guard SSRF E-04)
# =====================================================================


def check(label: str, cond: bool, detail: str = "") -> None:
    """Stateless check helper; raises AssertionError immediately on failure."""
    if not cond:
        print(f"FAIL {label}: {detail}")
        raise AssertionError(f"{label}: {detail}")
    print(f"PASS {label}")


SB_HOST = "abc123.supabase.co"
SB_STORAGE_URL = f"https://{SB_HOST}/storage/v1/object/public/raw-material-docs/coa/x.pdf"
R2_HOST = "pub-rmd.r2.dev"
R2_URL = f"https://{R2_HOST}/raw-material-docs-stg/coa/x.pdf"
R2_SIGNED_HOST = "acct123.r2.cloudflarestorage.com"
R2_SIGNED_URL = (
    f"https://{R2_SIGNED_HOST}/raw-material-docs-stg/coa/x.pdf"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=cred&X-Amz-Signature=sig"
)

BASES = {
    "raw-material-docs-stg": f"https://{R2_HOST}",
    "legal-documents-stg": "https://pub-legal.r2.dev",
}


def _hosts():
    return build_allowed_hosts(
        supabase_url=f"https://{SB_HOST}",
        r2_public_bases=BASES,
        r2_account_id="acct123",
    )


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[str] = []

    def emit(self, record):
        self.records.append(record.getMessage())


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def test_allowed_cases():
    hosts, sb_host = _hosts()
    cases = [
        ("supabase storage url", SB_STORAGE_URL, True),
        ("r2 public base url", R2_URL, True),
        ("r2 presigned url", R2_SIGNED_URL, True),
        ("host case-insensitive", f"https://{SB_HOST.upper()}/storage/v1/object/public/x/y.pdf", True),
    ]
    for label, url, expected in cases:
        got = is_allowed_storage_url(url, allowed_hosts=hosts, supabase_host=sb_host)
        check(f"lolos: {label}", got is expected, f"url={url} expected={expected} got={got}")


def test_rejected_cases():
    hosts, sb_host = _hosts()
    cases = [
        ("http skema", "http://example.com/x.pdf"),
        ("ip loopback v4", "https://127.0.0.1/x.pdf"),
        ("ip link-local metadata", "https://169.254.169.254/latest/meta-data"),
        ("ip loopback v6", "https://[::1]/x.pdf"),
        ("localhost", "https://localhost/x.pdf"),
        ("userinfo", "https://host.supabase.co@evil.com/x"),
        ("host sufiks jahat", "https://evil.supabase.co.attacker.com/storage/v1/object/public/x/y.pdf"),
        ("port 8443", f"https://{SB_HOST}:8443/storage/v1/object/public/x/y.pdf"),
        ("skema file", "file:///etc/passwd"),
        ("supabase path bukan storage", f"https://{SB_HOST}/auth/v1/token"),
        ("host tak dikenal", "https://example.com/x.pdf"),
    ]
    for label, url in cases:
        got = is_allowed_storage_url(url, allowed_hosts=hosts, supabase_host=sb_host)
        check(f"tolak: {label}", got is False, f"url={url}")


def test_empty_and_none():
    hosts, sb_host = _hosts()
    check("tolak: URL kosong", is_allowed_storage_url("", allowed_hosts=hosts, supabase_host=sb_host) is False)
    check("tolak: URL None", is_allowed_storage_url(None, allowed_hosts=hosts, supabase_host=sb_host) is False)


def test_empty_allowlist_rejects_all():
    hosts, sb_host = _hosts()
    _, empty_sb = build_allowed_hosts()
    all_hosts, _ = _hosts()
    check(
        "tolak: allowlist kosong menolak URL supabase sah",
        is_allowed_storage_url(SB_STORAGE_URL, allowed_hosts=set(), supabase_host=empty_sb) is False,
    )
    check(
        "tolak: allowlist kosong menolak URL r2 sah",
        is_allowed_storage_url(R2_URL, allowed_hosts=set(), supabase_host=None) is False,
    )
    del all_hosts, hosts, sb_host


def test_space_and_percent_path_preserved():
    hosts, sb_host = _hosts()
    spaced = f"https://{R2_HOST}/legal-documents-stg/hak%20lisensi%20merk.pdf"
    check(
        "lolos: path %20 tidak dinormalisasi",
        is_allowed_storage_url(spaced, allowed_hosts=hosts, supabase_host=sb_host) is True,
    )
    spaced2 = f"https://{R2_HOST}/legal-documents-stg/hak lisensi merk.pdf"
    check(
        "lolos: path berisi spasi apa adanya",
        is_allowed_storage_url(spaced2, allowed_hosts=hosts, supabase_host=sb_host) is True,
    )


def test_fetch_success_and_redirect_and_toobig_and_non2xx_and_network_error():
    hosts, sb_host = _hosts()

    def ok_handler(request):
        return httpx.Response(200, content=b"%PDF-1.4 fake")

    client = httpx.AsyncClient(transport=_mock_transport(ok_handler))
    data = asyncio.run(
        fetch_storage_bytes(
            client, R2_URL, label="Uji", timeout=30, allowed_hosts=hosts, supabase_host=sb_host
        )
    )
    check("fetch: URL sah -> bytes", data == b"%PDF-1.4 fake", f"got={data!r}")

    calls: list[str] = []

    def redirect_handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(302, headers={"Location": "https://169.254.169.254/latest/meta-data"})
        return httpx.Response(200, content=b"x")

    client2 = httpx.AsyncClient(transport=_mock_transport(redirect_handler))
    data2 = asyncio.run(
        fetch_storage_bytes(
            client2, R2_URL, label="Uji", timeout=30, allowed_hosts=hosts, supabase_host=sb_host
        )
    )
    check("fetch: redirect 302 -> None", data2 is None, f"got={data2!r}")
    check("fetch: redirect tidak diikuti (request kedua tidak ada)", len(calls) == 1, f"calls={calls}")

    def big_handler(request):
        return httpx.Response(200, content=b"x" * (32 * 1024 * 1024))

    client3 = httpx.AsyncClient(transport=_mock_transport(big_handler))
    data3 = asyncio.run(
        fetch_storage_bytes(
            client3,
            R2_URL,
            label="Uji",
            timeout=30,
            max_bytes=16 * 1024 * 1024,
            allowed_hosts=hosts,
            supabase_host=sb_host,
        )
    )
    check("fetch: respons > max_bytes -> None", data3 is None, f"got len={len(data3) if data3 else 0}")

    def non2xx_handler(request):
        return httpx.Response(500)

    client4 = httpx.AsyncClient(transport=_mock_transport(non2xx_handler))
    data4 = asyncio.run(
        fetch_storage_bytes(
            client4, R2_URL, label="Uji", timeout=30, allowed_hosts=hosts, supabase_host=sb_host
        )
    )
    check("fetch: non-2xx -> None", data4 is None, f"got={data4!r}")

    def net_error_handler(request):
        raise httpx.ConnectError("simulasi kegagalan jaringan")

    client5 = httpx.AsyncClient(transport=_mock_transport(net_error_handler))
    data5 = asyncio.run(
        fetch_storage_bytes(
            client5, R2_URL, label="Uji", timeout=30, allowed_hosts=hosts, supabase_host=sb_host
        )
    )
    check("fetch: exception jaringan -> None tanpa raise", data5 is None, f"got={data5!r}")


def test_fetch_rejected_url_logs_no_query():
    hosts, sb_host = _hosts()
    logger = logging.getLogger("app.safe_fetch")
    orig_level = logger.level
    cap = _Capture()
    logger.addHandler(cap)
    logger.setLevel(logging.WARNING)
    try:
        client = httpx.AsyncClient(
            transport=_mock_transport(lambda r: httpx.Response(200, content=b"x"))
        )
        url_with_query = "https://169.254.169.254/latest/meta-data?token=RAHASIA_XXXX"
        result = asyncio.run(
            fetch_storage_bytes(
                client, url_with_query, label="Uji", timeout=30, allowed_hosts=hosts, supabase_host=sb_host
            )
        )
    finally:
        logger.removeHandler(cap)
        logger.setLevel(orig_level)
    check("fetch: URL ditolak -> None", result is None, f"got={result!r}")
    warning_msgs = [m for m in cap.records if m.startswith("[SAFE_FETCH] Uji")]
    check("log: ada warning url_ditolak untuk URL ditolak", bool(warning_msgs), f"records={cap.records!r}")
    leaked = [m for m in warning_msgs if "RAHASIA_XXXX" in m or "token=" in m]
    check("log: query string tidak tercetak", not leaked, f"leaked={leaked!r}")


def test_empty_url_returns_none_without_client_call():
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=b"x")

    client = httpx.AsyncClient(transport=_mock_transport(handler))
    hosts, sb_host = _hosts()
    check(
        "fetch: URL kosong -> None tanpa request",
        asyncio.run(
            fetch_storage_bytes(
                client, "", label="Uji", timeout=30, allowed_hosts=hosts, supabase_host=sb_host
            )
        ) is None,
    )
    check("fetch: URL kosong -> tidak ada request ke jaringan", len(calls) == 0, f"calls={calls}")
    check(
        "fetch: URL None -> None",
        asyncio.run(
            fetch_storage_bytes(
                client, None, label="Uji", timeout=30, allowed_hosts=hosts, supabase_host=sb_host
            )
        ) is None,
    )


def test_build_allowed_hosts_from_config():
    hosts, sb_host = build_allowed_hosts(
        supabase_url=f"https://{SB_HOST}",
        r2_public_bases=BASES,
        r2_account_id="acct123",
    )
    check("allowlist: host supabase ada", SB_HOST in hosts, f"hosts={hosts}")
    check("allowlist: supabase_host dikembalikan", sb_host == SB_HOST, f"got={sb_host}")
    check("allowlist: host r2 base ada", R2_HOST in hosts, f"hosts={hosts}")
    check("allowlist: host presigned R2 ada", R2_SIGNED_HOST in hosts, f"hosts={hosts}")
    hosts_empty, sb_empty = build_allowed_hosts(supabase_url="", r2_public_bases={}, r2_account_id="")
    check("allowlist kosong -> set kosong (fail-closed)", hosts_empty == set() and sb_empty is None)


def test_max_bytes_constant_sensible():
    check("konstanta MAX_BYTES = 25 MB", MAX_BYTES == 25 * 1024 * 1024, f"got={MAX_BYTES}")


# =====================================================================
# Bagian 5: base.html cache-bust presign guard & .r2.dev/ selector
# =====================================================================

BASE_TEMPLATE = ROOT / "app" / "templates" / "base.html"
GUARD = "if (/[?&](X-Amz-Signature|X-Amz-Algorithm|token)=/i.test(url)) return url;"


def test_base_cachebust_presign_guard_and_r2_selector():
    """Converted from test_base_cachebust.py::main."""
    source = BASE_TEMPLATE.read_text(encoding="utf-8")
    bust_index = source.index("function bust(url)")
    guard_index = source.find(GUARD, bust_index)
    separator_index = source.find("var sep =", bust_index)

    assert guard_index >= 0, "guard presign tidak ditemukan di fungsi bust()"
    assert separator_index >= 0 and guard_index < separator_index, (
        "guard presign harus dijalankan sebelum penambahan cache-buster"
    )
    assert 'a[href*=".r2.dev/"]' in source, (
        "selektor cache-bust pola host .r2.dev/ tidak ditemukan di base.html"
    )
    print("PASS guard URL presign pada cache-bust base.html")
    print("PASS selektor cache-bust pola host .r2.dev/ pada base.html")


ALL_TESTS = [
    test_admin_bypasses_tenant_check,
    test_same_company_allowed,
    test_cross_tenant_denied,
    test_legacy_null_user_company_allowed,
    test_legacy_null_row_company_allowed,
    test_requested_company_mismatch_denied,
    test_requested_company_match_allowed,
    test_blank_requested_company_denied_for_tenant_user,
    test_blank_requested_company_does_not_lock_out_admin_or_legacy_user,
    test_none_requested_company_means_no_company_change,
    test_sample_rows_use_company_key,
    test_company_normalization_ignores_pt_prefix_and_case,
    test_common_js_escape_html_escapes_quotes_for_attribute_context,
    test_valid_pdf_accepted,
    test_empty_rejected,
    test_non_pdf_rejected,
    test_oversized_rejected,
    test_exact_limit_accepted,
    test_wrong_magic_bytes_rejected,
    test_single_entry_hops1,
    test_spoof_ignored_last_valid_wins,
    test_multi_hop_indexing,
    test_hops_greater_than_entries_uses_first,
    test_empty_header_falls_back_to_real_ip,
    test_empty_header_falls_back_to_client_host,
    test_all_empty_returns_dash,
    test_invalid_entries_fall_back,
    test_ipv6_valid,
    test_trusted_hops_zero_uses_client_host,
    test_allowed_cases,
    test_rejected_cases,
    test_empty_and_none,
    test_empty_allowlist_rejects_all,
    test_space_and_percent_path_preserved,
    test_fetch_success_and_redirect_and_toobig_and_non2xx_and_network_error,
    test_fetch_rejected_url_logs_no_query,
    test_empty_url_returns_none_without_client_call,
    test_build_allowed_hosts_from_config,
    test_max_bytes_constant_sensible,
    test_base_cachebust_presign_guard_and_r2_selector,
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
        print(f"\n{failed} dari {len(tests)} test security guards GAGAL.")
        return 1
    print(f"\nSemua {len(tests)} test security guards LULUS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
