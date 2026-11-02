"""Unit tests for app.security helpers dan helper escaping frontend.

Dijalankan CI sebagai ``python tests/test_security_helpers.py``; fungsi
``test_*`` dikumpulkan oleh runner ``main()`` di bawah (tanpa pytest).
"""

import json
import os
import shutil
import subprocess
import sys

from app.security import assert_same_tenant

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
    # Regresi SEC-02: FastAPI hanya menolak "" persis; "   " lolos Form(...)
    # dan dulu diizinkan helper, sehingga produk bisa dikosongkan perusahaannya.
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
    # Rute sample (company: Form(None)) mengirim None saat field tidak diubah.
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
        ["node", "-e", script, os.path.join(ROOT, "app", "static", "common.js"), json.dumps(values)],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_common_js_escape_html_escapes_quotes_for_attribute_context():
    # Regresi SEC-14: versi div.textContent->innerHTML tidak meng-escape " dan '
    # sehingga value="${escapeHtml(x)}" bisa disuntik atribut baru.
    if shutil.which("node") is None:
        print("SKIP common.js (node tidak tersedia)")
        return
    payload = 'x" autofocus onfocus="alert(1)" y="'
    got = _run_escape_html([payload, "a'b", "<b>&</b>", None, 0, "aman"])
    assert '"' not in got[0] and "&quot;" in got[0], got[0]
    assert got[1] == "a&#39;b", got[1]
    assert got[2] == "&lt;b&gt;&amp;&lt;/b&gt;", got[2]
    assert got[3] == "" and got[4] == "0" and got[5] == "aman", got[3:]


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
    print(f"PASS {len(tests)} pemeriksaan helper keamanan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
