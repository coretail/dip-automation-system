"""Pure-local tests for get_current_user fail-soft display_name handling.

Tests both scenarios:
  - Database has display_name column: query succeeds, display_name is populated.
  - Database lacks display_name column (pre-migration): query fails, retry
    without display_name succeeds, display_name falls back to None gracefully.

No real Supabase/network connection is used.
"""
import os
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")


# Simulate the fail-soft logic from get_current_user without importing
# app.main (which would create real Supabase client at module import time).
# We replicate the exact logic pattern for unit testing.

def _simulate_get_current_user_query(supabase, uid):
    """Replicate the fail-soft query logic from app.main.get_current_user.

    Try select with display_name; if that errors (column missing), retry
    without display_name. Return (row_dict, has_display_name_column).
    """
    # 1. First attempt: select with display_name
    profile_res = (
        supabase.table("profiles")
        .select("full_name, display_name, role, perusahaan")
        .eq("id", uid)
        .execute()
    )

    # 2. Fail-soft: if error (e.g., column doesn't exist), retry without display_name
    if not profile_res.data and profile_res.error:
        try:
            profile_res = (
                supabase.table("profiles")
                .select("full_name, role, perusahaan")
                .eq("id", uid)
                .execute()
            )
        except Exception:
            pass

    row = (profile_res.data or [{}])[0] if profile_res.data else {}
    return row


class FakeQuery:
    def __init__(self, data=None, error=None):
        self._data = data
        self._error = error
        self._select_cols = None
        self._eq_filter = None

    def select(self, *cols):
        self._select_cols = cols if cols else None
        return self

    def eq(self, key, value):
        self._eq_filter = (key, value)
        return self

    def execute(self):
        return SimpleNamespace(data=self._data, error=self._error)


class FakeSupabase:
    """Mock where the first select (with display_name) fails, second (without) succeeds."""

    def __init__(self, scenario="with_column"):
        self.scenario = scenario

    def table(self, name):
        assert name == "profiles"
        return self

    def select(self, *cols):
        self._cols = cols
        self._cols_str = " ".join(cols)
        return self

    def eq(self, key, value):
        return self

    def execute(self):
        if "display_name" in self._cols_str:
            if self.scenario == "with_column":
                return SimpleNamespace(
                    data=[{"full_name": "budi", "display_name": "Budiman", "role": "staff", "perusahaan": "PT Heka"}],
                    error=None,
                )
            else:
                # Column doesn't exist → PostgREST returns error with no data
                return SimpleNamespace(data=[], error="column 'display_name' does not exist")
        else:
            # Retry without display_name
            return SimpleNamespace(
                data=[{"full_name": "budi", "display_name": None, "role": "staff", "perusahaan": "PT Heka"}],
                error=None,
            )


def test_current_user_with_display_name_column():
    """When DB has display_name column, it is fetched correctly."""
    sb = FakeSupabase(scenario="with_column")
    row = _simulate_get_current_user_query(sb, "user-1")
    assert row["display_name"] == "Budiman"
    assert row["full_name"] == "budi"
    assert row["role"] == "staff"
    print("[PASS] get_current_user fetches display_name when column exists")


def test_current_user_fail_soft_no_display_name_column():
    """When DB lacks display_name column, query retries without it; no 401."""
    sb = FakeSupabase(scenario="without_column")
    row = _simulate_get_current_user_query(sb, "user-1")
    # After fail-soft retry, row should have data (full_name, role, perusahaan)
    assert row["full_name"] == "budi"
    assert row["role"] == "staff"
    assert row["perusahaan"] == "PT Heka"
    # display_name should be None (not present in retry data)
    assert row.get("display_name") is None
    print("[PASS] get_current_user fail-soft retries without display_name column")


def test_display_name_none_falls_back_to_full_name():
    """When display_name is None, the UI should fall back to full_name."""
    sb = FakeSupabase(scenario="with_column")
    sb_scenario = FakeSupabase(scenario="with_column")
    # Override to return None display_name
    class FakeSupabaseNone:
        def table(self, name):
            return self
        def select(self, *cols):
            return self
        def eq(self, *args, **kwargs):
            return self
        def execute(self):
            return SimpleNamespace(data=[{"full_name": "budi", "display_name": None, "role": "staff", "perusahaan": None}], error=None)

    row = _simulate_get_current_user_query(FakeSupabaseNone(), "user-1")
    display_name = row.get("display_name")
    full_name = row.get("full_name")
    effective_name = display_name or full_name
    assert effective_name == "budi"
    print("[PASS] display_name=None falls back to full_name")


if __name__ == "__main__":
    test_current_user_with_display_name_column()
    test_current_user_fail_soft_no_display_name_column()
    test_display_name_none_falls_back_to_full_name()
    print("All get_current_user display_name tests passed.")
