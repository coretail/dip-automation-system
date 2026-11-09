"""""Unit test murni F-05: redaction token ?access= di access log (sisi aplikasi).

Tanpa koneksi, tanpa secret. Dijalankan: python tests/test_access_log_redaction.py
(dengan PYTHONPATH=. seperti di ci.yml).
"""
import logging
import os
import sys
from unittest import mock as _mock

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import importlib  # noqa: E402

# Import filter dari app.main (module-level, tanpa server).
# app/main.py memuat config yang membaca env; di clean clone CI tanpa .env
# import aman. Di mesin lokal (ada .env) guard G-11 menolak import tanpa
# DIP_APP_ENV - uji filter lewat ekstraksi sumber alih-alih import penuh.
try:
    import app.main as main_mod  # noqa: E402
    _Redact = main_mod._RedactAccessTokenFilter
    _Quiet = main_mod._QuietAccessLogFilter
    _install = main_mod._install_quiet_access_log
except RuntimeError:
    import pathlib as _pl

    _src = _pl.Path("app/main.py").read_text(encoding="utf-8")
    _ns = {"logging": logging}
    _exec_src = _src[_src.index("class _QuietAccessLogFilter"):_src.index("@app.on_event")]
    exec(_exec_src, _ns)
    _Redact = _ns["_RedactAccessTokenFilter"]
    _Quiet = _ns["_QuietAccessLogFilter"]
    _install = _ns["_install_quiet_access_log"]


def _record(args):
    return logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, "msg %s %s %s %s %s", args, None, None)


def _formatted(record, fmt="%(message)s"):
    record.getMessage = lambda: fmt % record.args if record.args else fmt
    return record.getMessage()


def test_basic_redact():
    r = _record(("1.2.3.4:5", "GET", "/dip/x-uuid/bab1?access=SECRET&foo=1", "1.1", 200))
    assert _Redact().filter(r) is True
    out = _formatted(r, "%s %s %s %s %s")
    assert "SECRET" not in out, f"token bocor: {out}"
    assert "foo=1" in out, "parameter lain harus utuh"
    assert "access=***" in out, "harus jadi access=***"
    print("[PASS] redaction dasar: SECRET hilang, foo=1 utuh, access=***")


def test_token_positions():
    for path in ["/dip/x?access=SECRET", "/dip/x?foo=1&access=SECRET", "/dip/x?foo=1&access=SECRET&bar=2"]:
        r = _record(("c", "GET", path, "1.1", 200))
        assert _Redact().filter(r) is True
        out = _formatted(r, "%s %s %s %s %s")
        assert "SECRET" not in out and "access=***" in out, f"gagal: {path} -> {out}"
    print("[PASS] token di awal/tengah/akhir query semua disamarkan")


def test_url_encoded_token():
    r = _record(("c", "GET", "/dip/x?access=a%20b&foo=1", "1.1", 200))
    assert _Redact().filter(r) is True
    out = _formatted(r, "%s %s %s %s %s")
    assert "a%20b" not in out and "access=***" in out, f"encoded token bocor: {out}"
    print("[PASS] token ter-URL-encode disamarkan")


def test_no_query_unchanged():
    r = _record(("c", "GET", "/dip/x-uuid", "1.1", 200))
    assert _Redact().filter(r) is True
    out = _formatted(r, "%s %s %s %s %s")
    assert "/dip/x-uuid" in out, "path tanpa query harus tidak berubah"
    print("[PASS] path tanpa query tidak berubah")


def test_dict_and_weird_args():
    r = logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, "%(full_path)s", ({"full_path": "/dip/x?access=SECRET"},), None, None)
    assert _Redact().filter(r) is True
    out = r.getMessage()
    assert "SECRET" not in out and "access=***" in out, f"dict args: {out}"
    for weird in [None, (), ("only-one",), (1, 2, 3), "string-arg"]:
        r2 = logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, "msg", weird, None, None)
        assert _Redact().filter(r2) is True, f"harus return True untuk args={weird!r}"
    print("[PASS] args dict/aneh tidak melempar, return True")


def test_quiet_filter_still_works():
    for path in ["/health", "/api/presence/heartbeat", "/api/ed-notifications"]:
        r = _record(("c", "GET", path, "1.1", 200))
        assert _Quiet().filter(r) is False, f"filter polling harus menyaring {path}"
    r = _record(("c", "GET", "/dip/x?access=SECRET", "1.1", 200))
    assert _Quiet().filter(r) is True, "path /dip/ tidak boleh disaring filter polling"
    print("[PASS] filter polling lama tetap menyaring; /dip/ tidak terpengaruh")


def test_install_idempotent():
    lg = logging.getLogger("uvicorn.access")
    lg.filters = [f for f in lg.filters if not isinstance(f, (_Redact, _Quiet))]
    _install()
    _install()
    n_redact = sum(1 for f in lg.filters if isinstance(f, _Redact))
    n_quiet = sum(1 for f in lg.filters if isinstance(f, _Quiet))
    assert n_redact == 1 and n_quiet == 1, f"idempoten gagal: redact={n_redact} quiet={n_quiet}"
    print("[PASS] _install idempoten: tepat 1 redact + 1 quiet")


def main():
    test_basic_redact()
    test_token_positions()
    test_url_encoded_token()
    test_no_query_unchanged()
    test_dict_and_weird_args()
    test_quiet_filter_still_works()
    test_install_idempotent()
    print("\nSemua test redaction access log LULUS.")


if __name__ == "__main__":
    main()
