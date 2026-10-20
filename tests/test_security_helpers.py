"""Unit tests for app.security helpers."""

from app.security import assert_same_tenant


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
