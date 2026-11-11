"""Unit test pure-local guard SSRF E-04 (app/safe_fetch.py).

Tanpa koneksi jaringan (httpx.MockTransport), tanpa secret. Di-jalankan:
python tests/test_safe_fetch.py (dengan PYTHONPATH=. seperti di ci.yml).

Kasus:
- lolos: URL Supabase storage host dari config, URL r2.dev dari r2_public_bases,
  URL presigned R2, path %20/spasi tidak dinormalisasi.
- tolak: http, IP literal (127.0.0.1, 169.254.169.254, ::1), localhost,
  userinfo, host sufiks jahat, port 8443, skema file, host Supabase tanpa
  /storage/v1/object/, URL kosong/None, allowlist kosong.
- fetch_storage_bytes: redirect 302 -> None (request kedua tidak dilakukan),
  respons > max_bytes -> None, non-2xx -> None, exception jaringan -> None,
  log tidak memuat query string.
"""
import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402

from app.safe_fetch import (  # noqa: E402
    MAX_BYTES,
    build_allowed_hosts,
    fetch_storage_bytes,
    is_allowed_storage_url,
)

failures = 0
passes = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global failures, passes
    if cond:
        passes += 1
        print(f"PASS {label}")
    else:
        failures += 1
        print(f"FAIL {label}: {detail}")


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
    check("tolak: allowlist kosong menolak URL supabase sah",
          is_allowed_storage_url(SB_STORAGE_URL, allowed_hosts=set(), supabase_host=empty_sb) is False)
    check("tolak: allowlist kosong menolak URL r2 sah",
          is_allowed_storage_url(R2_URL, allowed_hosts=set(), supabase_host=None) is False)
    del all_hosts


def test_space_and_percent_path_preserved():
    hosts, sb_host = _hosts()
    spaced = f"https://{R2_HOST}/legal-documents-stg/hak%20lisensi%20merk.pdf"
    check("lolos: path %20 tidak dinormalisasi",
          is_allowed_storage_url(spaced, allowed_hosts=hosts, supabase_host=sb_host) is True)
    spaced2 = f"https://{R2_HOST}/legal-documents-stg/hak lisensi merk.pdf"
    check("lolos: path berisi spasi apa adanya",
          is_allowed_storage_url(spaced2, allowed_hosts=hosts, supabase_host=sb_host) is True)


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def test_fetch_success_and_redirect_and_toobig_and_non2xx_and_network_error():
    hosts, sb_host = _hosts()

    def ok_handler(request):
        return httpx.Response(200, content=b"%PDF-1.4 fake")

    client = httpx.AsyncClient(transport=_mock_transport(ok_handler))
    data = asyncio.run(fetch_storage_bytes(
        client, R2_URL, label="Uji", timeout=30,
        allowed_hosts=hosts, supabase_host=sb_host))
    check("fetch: URL sah -> bytes", data == b"%PDF-1.4 fake", f"got={data!r}")

    calls: list[str] = []

    def redirect_handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(302, headers={"Location": "https://169.254.169.254/latest/meta-data"})
        return httpx.Response(200, content=b"x")

    client2 = httpx.AsyncClient(transport=_mock_transport(redirect_handler))
    data2 = asyncio.run(fetch_storage_bytes(
        client2, R2_URL, label="Uji", timeout=30,
        allowed_hosts=hosts, supabase_host=sb_host))
    check("fetch: redirect 302 -> None", data2 is None, f"got={data2!r}")
    check("fetch: redirect tidak diikuti (request kedua tidak ada)", len(calls) == 1,
          f"calls={calls}")

    def big_handler(request):
        return httpx.Response(200, content=b"x" * (32 * 1024 * 1024))

    client3 = httpx.AsyncClient(transport=_mock_transport(big_handler))
    data3 = asyncio.run(fetch_storage_bytes(
        client3, R2_URL, label="Uji", timeout=30, max_bytes=16 * 1024 * 1024,
        allowed_hosts=hosts, supabase_host=sb_host))
    check("fetch: respons > max_bytes -> None", data3 is None, f"got len={len(data3) if data3 else 0}")

    def non2xx_handler(request):
        return httpx.Response(500)

    client4 = httpx.AsyncClient(transport=_mock_transport(non2xx_handler))
    data4 = asyncio.run(fetch_storage_bytes(
        client4, R2_URL, label="Uji", timeout=30,
        allowed_hosts=hosts, supabase_host=sb_host))
    check("fetch: non-2xx -> None", data4 is None, f"got={data4!r}")

    def net_error_handler(request):
        raise httpx.ConnectError("simulasi kegagalan jaringan")

    client5 = httpx.AsyncClient(transport=_mock_transport(net_error_handler))
    data5 = asyncio.run(fetch_storage_bytes(
        client5, R2_URL, label="Uji", timeout=30,
        allowed_hosts=hosts, supabase_host=sb_host))
    check("fetch: exception jaringan -> None tanpa raise", data5 is None, f"got={data5!r}")


def test_fetch_rejected_url_logs_no_query():
    hosts, sb_host = _hosts()
    cap = _Capture()
    logging.getLogger("app.safe_fetch").addHandler(cap)
    logging.getLogger("app.safe_fetch").setLevel(logging.WARNING)
    try:
        client = httpx.AsyncClient(transport=_mock_transport(ok_handler := lambda r: httpx.Response(200, content=b"x")))
        url_with_query = f"https://169.254.169.254/latest/meta-data?token=RAHASIA_XXXX"
        result = asyncio.run(fetch_storage_bytes(
            client, url_with_query, label="Uji", timeout=30,
            allowed_hosts=hosts, supabase_host=sb_host))
    finally:
        logging.getLogger("app.safe_fetch").removeHandler(cap)
    check("fetch: URL ditolak -> None", result is None, f"got={result!r}")
    warning_msgs = [m for m in cap.records if m.startswith("[SAFE_FETCH] Uji")]
    check("log: ada warning url_ditolak untuk URL ditolak", bool(warning_msgs),
          f"records={cap.records!r}")
    leaked = [m for m in warning_msgs if "RAHASIA_XXXX" in m or "token=" in m]
    check("log: query string tidak tercetak", not leaked, f"leaked={leaked!r}")


def test_empty_url_returns_none_without_client_call():
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=b"x")

    client = httpx.AsyncClient(transport=_mock_transport(handler))
    hosts, sb_host = _hosts()
    check("fetch: URL kosong -> None tanpa request",
          asyncio.run(fetch_storage_bytes(client, "", label="Uji", timeout=30,
                                          allowed_hosts=hosts, supabase_host=sb_host)) is None)
    check("fetch: URL kosong -> tidak ada request ke jaringan", len(calls) == 0, f"calls={calls}")
    check("fetch: URL None -> None",
          asyncio.run(fetch_storage_bytes(client, None, label="Uji", timeout=30,
                                          allowed_hosts=hosts, supabase_host=sb_host)) is None)


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


def main():
    test_allowed_cases()
    test_rejected_cases()
    test_empty_and_none()
    test_empty_allowlist_rejects_all()
    test_space_and_percent_path_preserved()
    test_fetch_success_and_redirect_and_toobig_and_non2xx_and_network_error()
    test_fetch_rejected_url_logs_no_query()
    test_empty_url_returns_none_without_client_call()
    test_build_allowed_hosts_from_config()
    test_max_bytes_constant_sensible()
    if failures:
        print(f"\nFAIL: {failures} dari {passes + failures} kasus")
        sys.exit(1)
    print(f"\nSemua test safe_fetch LULUS ({passes} kasus, tanpa koneksi jaringan)")


if __name__ == "__main__":
    main()
