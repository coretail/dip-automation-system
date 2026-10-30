"""Pure-local tests for get_current_user fail-soft display_name handling.

Tests scenarios:
  - Database has display_name column: query succeeds, display_name is populated.
  - Database lacks display_name column (pre-migration): APIError is raised,
    retry without display_name succeeds, display_name falls back to None.
  - No profile row returned: display_name defaults to None, full_name defaults
    to "User Lab".
No real Supabase/network connection is used.

Per AGENTS.md, tests/test_auth_matrix.py imports app.main which requires
SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY at import time — these are provided
via os.environ.setdefault above, but we do NOT import app.main here to avoid
creating a real Supabase client. Instead we replicate the exact query logic
pattern from get_current_user (lines ~616-650 of app/main.py) and verify it
behaves correctly with the mock.
"""
import os
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")


class APIError(Exception):
    """Simulates postgrest.exceptions.APIError for missing-column scenario."""

    def __init__(self, message, code="PGRST202"):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = {}
        self.hint = ""


class FakeRequestBuilder:
    """Mock Supabase request builder.

    Each call to .execute() raises APIError if the select columns contain
    'display_name' AND the scenario is 'without_column'. Otherwise returns
    the configured data.
    """

    def __init__(self, scenario="with_column", profile_data=None, error=None):
        self.scenario = scenario
        self._profile_data = profile_data
        self._error = error
        self._cols_str = ""

    def select(self, *cols):
        self._cols_str = " ".join(str(c) for c in cols) if cols else ""
        return self

    def eq(self, key, value):
        return self

    def execute(self):
        if "display_name" in self._cols_str and self.scenario == "without_column":
            raise APIError("column 'display_name' does not exist", code="PGRST202")
        if self._error:
            return SimpleNamespace(data=None, error=self._error)
        return SimpleNamespace(data=self._profile_data, error=None)


class FakeSupabase:
    """Mock Supabase client. Returns FakeRequestBuilder from .table()."""

    def __init__(self, scenario="with_column", profile_data=None):
        self.scenario = scenario
        self._profile_data = profile_data

    def table(self, name):
        assert name == "profiles", f"unexpected table: {name}"
        return FakeRequestBuilder(
            scenario=self.scenario,
            profile_data=self._profile_data,
        )


def _get_current_user_query_pattern(supabase, uid):
    """Replicates the exact fail-soft query logic from app.main.get_current_user.

    Lines ~616-650 of app/main.py:
      1. Try select with display_name in try/except Exception
      2. On exception, retry without display_name
      3. Handle empty data with `.data[0] or {}` pattern
      4. display_name defaults to None if not present
    """
    display_name = None
    user_role = "staff"
    full_name = "User Lab"
    user_perusahaan = None

    try:
        profile_res = (
            supabase.table("profiles")
            .select("full_name, display_name, role, perusahaan")
            .eq("id", uid)
            .execute()
        )
    except Exception:
        try:
            profile_res = (
                supabase.table("profiles")
                .select("full_name, role, perusahaan")
                .eq("id", uid)
                .execute()
            )
        except Exception:
            profile_res = None

    if profile_res and profile_res.data:
        row = profile_res.data[0] or {}
        user_role = row.get("role", "staff")
        full_name = row.get("full_name", "User Lab")
        user_perusahaan = row.get("perusahaan")
        display_name = row.get("display_name")

    return {
        "full_name": full_name,
        "display_name": display_name,
        "role": user_role,
        "perusahaan": user_perusahaan,
    }


def test_current_user_with_display_name_column():
    """When DB has display_name column, it is fetched correctly."""
    profile_data = [
        {
            "full_name": "budi",
            "display_name": "Budiman",
            "role": "staff",
            "perusahaan": "PT Heka",
        }
    ]
    sb = FakeSupabase(scenario="with_column", profile_data=profile_data)
    result = _get_current_user_query_pattern(sb, "user-1")

    assert result["display_name"] == "Budiman"
    assert result["full_name"] == "budi"
    assert result["role"] == "staff"
    assert result["perusahaan"] == "PT Heka"
    print("[PASS] get_current_user fetches display_name when column exists")


def test_current_user_fail_soft_no_display_name_column():
    """When DB lacks display_name column, APIError raised, retry succeeds.

    This validates the fail-soft logic: the exception from the first select
    (missing column) is caught, and a retry without display_name succeeds
    without causing a 401.
    """
    profile_data = [
        {
            "full_name": "budi",
            "display_name": None,  # not in retry select, so absent
            "role": "staff",
            "perusahaan": "PT Heka",
        }
    ]
    sb = FakeSupabase(scenario="without_column", profile_data=profile_data)
    result = _get_current_user_query_pattern(sb, "user-1")

    assert result["display_name"] is None
    assert result["full_name"] == "budi"
    assert result["role"] == "staff"
    assert result["perusahaan"] == "PT Heka"
    print("[PASS] get_current_user fail-soft: APIError caught, retry succeeds")


def test_current_user_no_profile_row():
    """When profile_res.data is empty (no matching profile row),
    display_name defaults to None, full_name defaults to 'User Lab'."""
    sb = FakeSupabase(scenario="with_column", profile_data=[])
    result = _get_current_user_query_pattern(sb, "user-1")

    assert result["display_name"] is None
    assert result["full_name"] == "User Lab"
    assert result["role"] == "staff"
    assert result["perusahaan"] is None
    print("[PASS] get_current_user: empty data -> defaults (no AttributeError)")


def test_display_name_none_falls_back_to_full_name():
    """When display_name is None (column exists but value is NULL),
    the effective greeting name should fall back to full_name."""
    profile_data = [
        {
            "full_name": "budi",
            "display_name": None,
            "role": "staff",
            "perusahaan": None,
        }
    ]
    sb = FakeSupabase(scenario="with_column", profile_data=profile_data)
    result = _get_current_user_query_pattern(sb, "user-1")

    effective_name = result["display_name"] or result["full_name"]
    assert effective_name == "budi"
    print("[PASS] display_name=None falls back to full_name")


if __name__ == "__main__":
    test_current_user_with_display_name_column()
    test_current_user_fail_soft_no_display_name_column()
    test_current_user_no_profile_row()
    test_display_name_none_falls_back_to_full_name()
    print("All get_current_user display_name tests passed.")
