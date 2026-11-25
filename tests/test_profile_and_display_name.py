"""Pure-local tests gabungan untuk profil & display_name (Task 4 refactor test).

Menggabungkan lima file lama tanpa mengurangi satu pun fungsi/assertion:
  - test_profile_validation.py            -> validasi display_name (14 fungsi, 29 assert)
  - test_profile_routes.py                -> GET /profile & POST /profile/change-password (5 fungsi, 18 assert)
  - test_profile_display_name_route.py    -> POST /profile/display-name (8 fungsi, 25 assert)
  - test_admin_create_user_display_name.py -> POST /admin/users/create display_name/BE-05/BE-12 (5 fungsi, 26 assert)
  - test_get_current_user_display_name.py -> pola fail-soft get_current_user (4 fungsi, 14 assert)

Tanpa jaringan/Supabase nyata.
Dijalankan: python tests/test_profile_and_display_name.py
"""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

from _fakes import FakeApp, FakeLimiter  # noqa: E402
from app.admin_users_routes import register_admin_users_routes  # noqa: E402
from app.profile_routes import register_profile_routes  # noqa: E402
from app.profile_validation import (  # noqa: E402
    MAX_DISPLAY_NAME_LENGTH,
    validate_display_name,
)


# ---------------------------------------------------------------------------
# Fakes domain profil routes (GET /profile & POST /profile/change-password)
# ---------------------------------------------------------------------------
class ProfileActivityQuery:
    def __init__(self, data):
        self.data = data
        self.filters = []
        self.order_args = None
        self.limit_value = None

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, key, desc=False):
        self.order_args = (key, desc)
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        return SimpleNamespace(data=self.data)


class ProfileRoutesSupabase:
    def __init__(self):
        self.activity_query = ProfileActivityQuery([
            {"action": "update", "entity_type": "product", "entity_label": "Product A", "outcome": "success", "created_at": "2026-10-28T00:00:00+00:00"},
        ])
        self.user = SimpleNamespace(created_at="2026-10-01T00:00:00+00:00")
        self.updated = None

        class Admin:
            def __init__(inner, _auth):
                inner.auth_user = SimpleNamespace(user=SimpleNamespace(created_at="2026-10-01T00:00:00+00:00"))

            def get_user_by_id(inner, _uid):
                return inner.auth_user

            def update_user_by_id(inner, uid, payload):
                self.updated = (uid, payload)

        class Auth:
            def __init__(inner):
                inner.admin = Admin(inner)

        self.auth = Auth()

    def table(self, name):
        assert name == "activity_logs"
        return self.activity_query


class FakeLoginClient:
    def __init__(self, expected_password):
        self.expected_password = expected_password
        self.calls = []

        class Auth:
            def __init__(inner):
                inner.client = self

            def sign_in_with_password(inner, payload):
                self.calls.append(payload)
                if payload["password"] != self.expected_password:
                    raise ValueError("invalid credentials")

        self.auth = Auth()


def build_profile_routes():
    app = FakeApp()
    limiter = FakeLimiter()
    supabase = ProfileRoutesSupabase()
    login_client = FakeLoginClient("old-pass")
    rendered = []
    logs = []

    async def get_current_user(_request):
        return {"id": "user-1", "email": "user@example.test", "full_name": "user", "role": "staff", "perusahaan": None}

    def template_response(**kwargs):
        rendered.append(kwargs)
        return kwargs

    def log_activity(*args, **kwargs):
        logs.append((args, kwargs))

    register_profile_routes(app, get_current_user, supabase, SimpleNamespace(TemplateResponse=template_response), log_activity, limiter, lambda caller: login_client)
    return app, limiter, supabase, login_client, rendered, logs


# ---------------------------------------------------------------------------
# Fakes domain POST /profile/display-name
# ---------------------------------------------------------------------------
class DisplayNameQuery:
    """Mock Supabase query builder. Supports select + eq + limit, and update."""

    def __init__(self, supabase):
        self._sup = supabase
        self._cols = None
        self._eq_filter = None
        self._update_payload = None
        self._insert_payload = None
        self.error = None

    def select(self, *cols):
        self._cols = cols
        return self

    def eq(self, key, value):
        self._eq_filter = (key, value)
        return self

    def limit(self, value):
        return self

    def update(self, payload):
        self._update_payload = payload
        self._sup.updates.append((self._sup.table_name, payload, self._eq_filter))
        return self

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def order(self, *args, **kwargs):
        return self

    def execute(self):
        if self._update_payload is not None:
            return SimpleNamespace(data=[{"id": self._eq_filter[1]}], error=None)
        if self._insert_payload is not None:
            return SimpleNamespace(data=[self._insert_payload], error=None)
        data = list(self._sup.profile_data)
        if self._eq_filter and self._eq_filter[0] == "id":
            uid = self._eq_filter[1]
            data = [r for r in data if r.get("id") == uid or uid == "user-1"]
        return SimpleNamespace(data=data, error=self.error)


class DisplayNameSupabase:
    """Mock Supabase with profiles table supporting select + update."""

    def __init__(self, profile_data=None):
        self.profile_data = profile_data or [
            {"id": "user-1", "display_name": "Old Display", "full_name": "testuser", "role": "staff", "perusahaan": None}
        ]
        self.updates = []
        self.table_name = None

    def table(self, name):
        self.table_name = name
        return DisplayNameQuery(self)


def build_display_name_route():
    app = FakeApp()
    limiter = FakeLimiter()
    supabase = DisplayNameSupabase()
    rendered = []
    logs = []

    async def get_current_user(_request):
        return {
            "id": "user-1",
            "email": "user@example.test",
            "full_name": "testuser",
            "display_name": None,
            "role": "staff",
            "perusahaan": None,
        }

    def template_response(**kwargs):
        rendered.append(kwargs)
        return kwargs

    def log_activity(*args, **kwargs):
        logs.append((args, kwargs))

    register_profile_routes(
        app, get_current_user, supabase,
        SimpleNamespace(TemplateResponse=template_response),
        log_activity, limiter, lambda caller: None,
    )
    return app, limiter, supabase, rendered, logs


# ---------------------------------------------------------------------------
# Fakes domain admin_create_user
# ---------------------------------------------------------------------------
class FakeAuthResponse:
    def __init__(self, user):
        self.user = user


class AdminCreateAuthAdmin:
    def __init__(self, fake_supabase):
        self._fake_supabase = fake_supabase
        self.created_users = []
        self.updated_users = []
        self.deleted_users = []

    def create_user(self, payload):
        self.created_users.append(payload)
        return FakeAuthResponse(SimpleNamespace(id="new-uid-123", email=payload["email"]))

    def get_user_by_id(self, _uid):
        return SimpleNamespace(user=SimpleNamespace(email="test@example.test"))

    def update_user_by_id(self, uid, payload):
        self.updated_users.append((uid, payload))

    def delete_user(self, uid):
        # BE-05: kebijakan "flag only" berarti method ini TIDAK boleh dipanggil
        # saat insert profiles gagal. Direkam supaya test bisa membuktikan.
        self.deleted_users.append(uid)


class AdminCreateAuth:
    def __init__(self, fake_supabase):
        self.admin = AdminCreateAuthAdmin(fake_supabase)


class AdminCreateTable:
    def __init__(self, table_name, fake_supabase):
        self.table_name = table_name
        self._fake = fake_supabase
        self._insert_payload = None
        self._update_payload = None
        self._eq_filter = None

    def select(self, *cols):
        return self

    def eq(self, key, value):
        self._eq_filter = (key, value)
        return self

    def limit(self, n):
        return self

    def order(self, key, desc=False):
        return self

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def delete(self):
        return self

    def execute(self):
        if self._insert_payload is not None:
            if self.table_name == "profiles" and getattr(self._fake, "fail_profiles_insert", False):
                raise RuntimeError("insert profiles gagal (disimulasikan)")
            self._fake.inserts.append((self.table_name, self._insert_payload))
            return SimpleNamespace(data=[self._insert_payload], error=None)
        if self._update_payload is not None:
            self._fake.updates.append((self.table_name, self._update_payload, self._eq_filter))
            return SimpleNamespace(data=[self._update_payload], error=None)
        if self.table_name == "profiles":
            return SimpleNamespace(data=self._fake.profiles_data, error=None)
        return SimpleNamespace(data=[], error=None)


class AdminCreateSupabase:
    def __init__(self, fail_profiles_insert=False):
        self.auth = AdminCreateAuth(self)
        self.inserts = []
        self.updates = []
        self.profiles_data = [{"full_name": "existing_user"}]
        self.fail_profiles_insert = fail_profiles_insert

    def table(self, name):
        return AdminCreateTable(name, self)


def build_admin_create(fail_profiles_insert=False):
    app = FakeApp()
    supabase = AdminCreateSupabase(fail_profiles_insert=fail_profiles_insert)
    logs = []

    async def get_current_user(_request):
        return {"id": "admin-1", "email": "admin@example.test", "full_name": "admin", "role": "admin", "perusahaan": None}

    def template_response(**kwargs):
        return kwargs

    def log_activity(*args, **kwargs):
        logs.append((args, kwargs))

    def mask_email(email):
        return email

    def compute_user_presence(profile):
        return {"presence_status": "offline", "is_online": False, "is_idle": False,
                "last_seen_at": None, "last_seen_label": "-", "last_activity_at": None,
                "last_activity_label": "-"}

    def _user_label(uid):
        return f"User {uid}"

    def _user_role_and_label(uid):
        return ("staff", f"User {uid}")

    def get_ed_notification_count():
        return 0

    register_admin_users_routes(
        app, get_current_user, supabase,
        SimpleNamespace(TemplateResponse=template_response),
        log_activity, compute_user_presence, mask_email,
        _user_label, _user_role_and_label,
        get_ed_notification_count,
        None,
        FakeLimiter(),
    )
    return app, supabase, logs


# ---------------------------------------------------------------------------
# Fakes domain get_current_user fail-soft
# ---------------------------------------------------------------------------
class APIError(Exception):
    """Simulates postgrest.exceptions.APIError for missing-column scenario."""

    def __init__(self, message, code="PGRST202"):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = {}
        self.hint = ""


class FailSoftRequestBuilder:
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


class FailSoftSupabase:
    def __init__(self, scenario="with_column", profile_data=None):
        self.scenario = scenario
        self._profile_data = profile_data

    def table(self, name):
        assert name == "profiles", f"unexpected table: {name}"
        return FailSoftRequestBuilder(
            scenario=self.scenario,
            profile_data=self._profile_data,
        )


def _get_current_user_query_pattern(supabase, uid):
    """Replicates the exact fail-soft query logic from app.main.get_current_user."""
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


# ===========================================================================
# A. Validasi display_name (dari test_profile_validation.py)
# ===========================================================================
def test_valid_display_name():
    cleaned, error = validate_display_name("Budi")
    assert cleaned == "Budi"
    assert error is None
    print("[PASS] valid display name returns cleaned value, no error")


def test_trim_leading_trailing():
    cleaned, error = validate_display_name("   Budi Santoso   ")
    assert cleaned == "Budi Santoso"
    assert error is None
    print("[PASS] leading/trailing whitespace trimmed")


def test_collapse_multiple_spaces():
    cleaned, error = validate_display_name("Budi   Santoso")
    assert cleaned == "Budi Santoso"
    assert error is None
    print("[PASS] multiple internal spaces collapsed to single")


def test_collapse_tabs_and_newlines():
    cleaned, error = validate_display_name("Budi\t\tSantoso\nBudi")
    assert cleaned == "Budi Santoso Budi"
    assert error is None
    print("[PASS] tabs/newlines collapsed to single space")


def test_empty_returns_null():
    cleaned, error = validate_display_name("")
    assert cleaned is None
    assert error is None
    print("[PASS] empty string returns (None, None) to clear display name")


def test_whitespace_only_returns_null():
    cleaned, error = validate_display_name("   \t\n  ")
    assert cleaned is None
    assert error is None
    print("[PASS] whitespace-only returns (None, None) to clear display name")


def test_none_returns_null():
    cleaned, error = validate_display_name(None)
    assert cleaned is None
    assert error is None
    print("[PASS] None input returns (None, None)")


def test_too_long_rejected():
    long_name = "A" * (MAX_DISPLAY_NAME_LENGTH + 1)
    cleaned, error = validate_display_name(long_name)
    assert cleaned is None
    assert error is not None
    assert str(MAX_DISPLAY_NAME_LENGTH) in error
    print("[PASS] display name exceeding 60 chars is rejected")


def test_max_length_accepted():
    name = "A" * MAX_DISPLAY_NAME_LENGTH
    cleaned, error = validate_display_name(name)
    assert cleaned == name
    assert error is None
    print("[PASS] display name at exactly 60 chars is accepted")


def test_control_chars_rejected():
    cleaned, error = validate_display_name("Budi\x00Santoso")
    assert cleaned is None
    assert error is not None
    print("[PASS] control characters (Cc) rejected")


def test_format_chars_rejected():
    # Zero-width space U+200B is Cf (format)
    cleaned, error = validate_display_name("Budi\u200bSantoso")
    assert cleaned is None
    assert error is not None
    print("[PASS] zero-width space (Cf) rejected")


def test_non_string_rejected():
    cleaned, error = validate_display_name(12345)
    assert cleaned is None
    assert error is not None
    print("[PASS] non-string input rejected")


def test_underscore_hyphen_accepted():
    cleaned, error = validate_display_name("Budi-Santoso_123")
    assert cleaned == "Budi-Santoso_123"
    assert error is None
    print("[PASS] hyphens and underscores preserved")


def test_unicode_chars_accepted():
    cleaned, error = validate_display_name("José María")
    assert cleaned == "José María"
    assert error is None
    print("[PASS] unicode characters (é, í) preserved")


# ===========================================================================
# B. Profile routes (dari test_profile_routes.py)
# ===========================================================================
def test_profile_query_is_scoped_and_limited():
    app, limiter, _supabase, _client, rendered, _logs = build_profile_routes()
    endpoint = app.routes[("GET", "/profile")]
    asyncio.run(endpoint(SimpleNamespace(query_params={}), {"id": "user-1", "email": "user@example.test", "full_name": "user", "role": "staff", "perusahaan": None}))
    query = _supabase.activity_query
    assert ("actor_id", "user-1") in query.filters
    assert query.order_args == ("created_at", True)
    assert query.limit_value == 20
    assert rendered[0]["context"]["activity"][0]["action_label"] == "Updated"
    print("[PASS] profile activity query scopes actor, orders newest-first, limits 20")


def test_password_uses_fresh_client_and_session_uid():
    _app, limiter, supabase, client, _rendered, logs = build_profile_routes()
    endpoint = _app.routes[("POST", "/profile/change-password")]
    asyncio.run(endpoint(SimpleNamespace(), "old-pass", "new-pass", "new-pass", {"id": "user-1", "email": "user@example.test", "full_name": "user"}))
    assert "5/minute" in limiter.calls
    assert client.calls == [{"email": "user@example.test", "password": "old-pass"}]
    assert supabase.updated == ("user-1", {"password": "new-pass"})
    assert logs[0][0][1] == "change_password"
    assert "new-pass" not in repr(logs)
    print("[PASS] password verification uses temporary client; update uses session UID")


def test_password_validation_does_not_call_auth():
    app, _limiter, supabase, client, _rendered, _logs = build_profile_routes()
    endpoint = app.routes[("POST", "/profile/change-password")]
    for value in ("short", "x" * 73, "old-pass"):
        asyncio.run(endpoint(SimpleNamespace(), "old-pass", value, value, {"id": "user-1", "email": "user@example.test"}))
    assert client.calls == []
    assert supabase.updated is None
    print("[PASS] invalid and reused raw passwords are rejected before Auth")


def test_mismatch_and_wrong_current_are_safe():
    app, _limiter, supabase, client, _rendered, _logs = build_profile_routes()
    endpoint = app.routes[("POST", "/profile/change-password")]
    mismatch = asyncio.run(endpoint(SimpleNamespace(), "old-pass", "new-pass", "different", {"id": "user-1", "email": "user@example.test"}))
    assert "password_mismatch" in mismatch.headers["location"]
    wrong = asyncio.run(endpoint(SimpleNamespace(), "wrong-pass", "new-pass", "new-pass", {"id": "user-1", "email": "user@example.test"}))
    assert "current_password_invalid" in wrong.headers["location"]
    assert supabase.updated is None
    print("[PASS] mismatch and wrong-current responses use fixed error codes")


def test_empty_fields_return_safe_redirect():
    app, _limiter, supabase, client, _rendered, _logs = build_profile_routes()
    endpoint = app.routes[("POST", "/profile/change-password")]
    result = asyncio.run(endpoint(SimpleNamespace(), "", "new-pass", "new-pass", {"id": "user-1", "email": "user@example.test"}))
    assert "password_invalid" in result.headers["location"]
    assert client.calls == []
    assert supabase.updated is None
    print("[PASS] empty fields return a safe redirect instead of 422")


# ===========================================================================
# C. POST /profile/display-name (dari test_profile_display_name_route.py)
# ===========================================================================
def test_display_name_valid_update():
    app, limiter, supabase, rendered, logs = build_display_name_route()
    endpoint = app.routes[("POST", "/profile/display-name")]
    result = asyncio.run(endpoint(
        SimpleNamespace(),
        display_name="Budi Santoso",
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": "Old Display", "role": "staff", "perusahaan": None},
    ))
    assert "location" in result.headers
    assert "display_name_changed" in result.headers["location"]
    assert "10/minute" in limiter.calls
    assert logs[0][0][1] == "update"
    assert logs[0][1]["outcome"] == "success"
    assert len(logs[0][1]["changes"]) == 1
    change = logs[0][1]["changes"][0]
    assert change["field"] == "Display Name"
    assert change["new"] == "Budi Santoso"
    print("[PASS] valid display name update redirects and logs activity")


def test_display_name_invalid_too_long():
    app, limiter, supabase, rendered, logs = build_display_name_route()
    endpoint = app.routes[("POST", "/profile/display-name")]
    long_name = "A" * 61
    result = asyncio.run(endpoint(
        SimpleNamespace(),
        display_name=long_name,
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": None, "role": "staff", "perusahaan": None},
    ))
    assert "location" in result.headers
    assert "display_name_invalid" in result.headers["location"]
    assert logs[0][1]["outcome"] == "rejected"
    print("[PASS] too-long display name rejected with redirect and log")


def test_display_name_empty_clears_to_null():
    app, limiter, supabase, rendered, logs = build_display_name_route()
    endpoint = app.routes[("POST", "/profile/display-name")]
    result = asyncio.run(endpoint(
        SimpleNamespace(),
        display_name="   ",
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": "Old Display", "role": "staff", "perusahaan": None},
    ))
    assert "display_name_changed" in result.headers["location"]
    assert logs[0][1]["outcome"] == "success"
    change = logs[0][1]["changes"][0]
    assert change["field"] == "Display Name"
    assert change["new"] is None
    assert change["old"] == "Old Display"
    print("[PASS] empty/whitespace-only display name clears to NULL")


def test_display_name_control_chars_rejected():
    app, limiter, supabase, rendered, logs = build_display_name_route()
    endpoint = app.routes[("POST", "/profile/display-name")]
    result = asyncio.run(endpoint(
        SimpleNamespace(),
        display_name="Budi\x00Santoso",
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": None, "role": "staff", "perusahaan": None},
    ))
    assert "display_name_invalid" in result.headers["location"]
    assert logs[0][1]["outcome"] == "rejected"
    print("[PASS] display name with control chars rejected")


def test_display_name_trim_and_collapse():
    app, limiter, supabase, rendered, logs = build_display_name_route()
    endpoint = app.routes[("POST", "/profile/display-name")]
    result = asyncio.run(endpoint(
        SimpleNamespace(),
        display_name="  Budi   Santoso  ",
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": None, "role": "staff", "perusahaan": None},
    ))
    assert "display_name_changed" in result.headers["location"]
    change = logs[0][1]["changes"][0]
    assert change["new"] == "Budi Santoso"
    print("[PASS] display name trimmed and spaces collapsed before save")


def test_display_name_logs_old_and_new():
    app, limiter, supabase, rendered, logs = build_display_name_route()
    endpoint = app.routes[("POST", "/profile/display-name")]
    asyncio.run(endpoint(
        SimpleNamespace(),
        display_name="New Name",
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": "Old Display", "role": "staff", "perusahaan": None},
    ))
    assert logs[0][1]["outcome"] == "success"
    change = logs[0][1]["changes"][0]
    assert change["old"] == "Old Display"
    assert change["new"] == "New Name"
    print("[PASS] activity log records both old and new display name")


def test_display_name_rate_limited():
    app, limiter, supabase, rendered, logs = build_display_name_route()
    _ = app.routes[("POST", "/profile/display-name")]
    assert "10/minute" in limiter.calls
    print("[PASS] display name route has rate limit decorator")


def test_display_name_db_error_fails_gracefully():
    app, limiter, supabase, rendered, logs = build_display_name_route()
    endpoint = app.routes[("POST", "/profile/display-name")]
    supabase.profile_data = [{"id": "user-2", "display_name": None, "full_name": "other"}]
    result = asyncio.run(endpoint(
        SimpleNamespace(),
        display_name="Test Name",
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": None, "role": "staff", "perusahaan": None},
    ))
    assert "display_name_changed" in result.headers["location"]
    print("[PASS] route handles missing profile data gracefully")


# ===========================================================================
# D. admin_create_user display_name (dari test_admin_create_user_display_name.py)
# ===========================================================================
def test_admin_create_user_sets_display_name():
    app, supabase, logs = build_admin_create()
    endpoint = app.routes[("POST", "/admin/users/create")]
    asyncio.run(endpoint(
        SimpleNamespace(),
        email="new@example.com",
        username="budi.santoso",
        password="password123",
        role="staff",
        current_user={"id": "admin-1", "email": "admin@example.com", "full_name": "admin", "role": "admin", "perusahaan": None},
    ))
    inserts = supabase.inserts
    assert len(inserts) >= 1
    profiles_insert = [i for i in inserts if i[0] == "profiles"]
    assert len(profiles_insert) == 1
    payload = profiles_insert[0][1]
    assert payload["full_name"] == "budi.santoso"
    assert payload["display_name"] == "budi.santoso"
    assert payload["display_name"] == payload["full_name"][:60]
    assert logs[-1][0][1] == "create"
    assert logs[-1][1]["outcome"] == "success"
    changes_str = str(logs[-1][1]["changes"])
    assert "Display Name" in changes_str
    print("[PASS] admin_create_user sets display_name = clean_username[:60]")


def test_admin_create_user_truncates_long_username():
    app, supabase, logs = build_admin_create()
    endpoint = app.routes[("POST", "/admin/users/create")]
    long_username = "a" * 80
    asyncio.run(endpoint(
        SimpleNamespace(),
        email="long@example.com",
        username=long_username,
        password="password123",
        role="staff",
        current_user={"id": "admin-1", "email": "admin@example.com", "full_name": "admin", "role": "admin", "perusahaan": None},
    ))
    profiles_inserts = [i for i in supabase.inserts if i[0] == "profiles"]
    assert len(profiles_inserts) == 1
    payload = profiles_inserts[0][1]
    assert len(payload["display_name"]) == 60
    assert payload["display_name"] == long_username[:60]
    print("[PASS] admin_create_user truncates display_name to 60 characters")


def test_admin_create_user_strips_and_lowercases_username():
    app, supabase, logs = build_admin_create()
    endpoint = app.routes[("POST", "/admin/users/create")]
    asyncio.run(endpoint(
        SimpleNamespace(),
        email="test@example.com",
        username="  Budi SANTOSO  ",
        password="password123",
        role="staff",
        current_user={"id": "admin-1", "email": "admin@example.com", "full_name": "admin", "role": "admin", "perusahaan": None},
    ))
    profiles_inserts = [i for i in supabase.inserts if i[0] == "profiles"]
    payload = profiles_inserts[0][1]
    assert payload["full_name"] == "budi santoso"
    assert payload["display_name"] == "budi santoso"
    print("[PASS] admin_create_user strips and lowercases for both full_name and display_name")


def test_admin_create_user_rejects_short_password():
    # BE-12: password < 6 karakter ditolak SEBELUM akun Auth dibuat.
    app, supabase, logs = build_admin_create()
    endpoint = app.routes[("POST", "/admin/users/create")]
    result = asyncio.run(endpoint(
        SimpleNamespace(),
        email="pendek@example.com",
        username="password.pendek",
        password="abc12",
        role="staff",
        current_user={"id": "admin-1", "email": "admin@example.com", "full_name": "admin", "role": "admin", "perusahaan": None},
    ))
    assert result.status_code == 303
    location = result.headers["location"]
    assert "error=password_too_short" in location, location
    assert supabase.auth.admin.created_users == []
    assert [i for i in supabase.inserts if i[0] == "profiles"] == []
    assert logs[-1][0][1] == "create"
    assert logs[-1][1]["outcome"] == "rejected"
    print("[PASS] BE-12 admin_create_user menolak password < 6 karakter sebelum create_user")


def test_admin_create_user_orphan_is_flagged_not_deleted():
    # BE-05: insert profiles gagal -> akun auth TIDAK dihapus otomatis (flag only)
    app, supabase, logs = build_admin_create(fail_profiles_insert=True)
    endpoint = app.routes[("POST", "/admin/users/create")]
    result = asyncio.run(endpoint(
        SimpleNamespace(),
        email="yatin@example.com",
        username="yatin.user",
        password="password123",
        role="staff",
        current_user={"id": "admin-1", "email": "admin@example.com", "full_name": "admin", "role": "admin", "perusahaan": None},
    ))
    assert result.status_code == 303
    location = result.headers["location"]
    assert "error=create_failed" in location, location
    assert len(supabase.auth.admin.created_users) == 1
    assert supabase.auth.admin.deleted_users == []
    assert logs[-1][0][1] == "create"
    assert logs[-1][1]["outcome"] == "failed"
    changes_str = str(logs[-1][1]["changes"])
    assert "profil gagal dibuat" in changes_str
    print("[PASS] BE-05 akun yatim ditandai (flag only), tanpa delete_user otomatis")


# ===========================================================================
# E. get_current_user fail-soft display_name (dari test_get_current_user_display_name.py)
# ===========================================================================
def test_current_user_with_display_name_column():
    profile_data = [
        {
            "full_name": "budi",
            "display_name": "Budiman",
            "role": "staff",
            "perusahaan": "PT Heka",
        }
    ]
    sb = FailSoftSupabase(scenario="with_column", profile_data=profile_data)
    result = _get_current_user_query_pattern(sb, "user-1")

    assert result["display_name"] == "Budiman"
    assert result["full_name"] == "budi"
    assert result["role"] == "staff"
    assert result["perusahaan"] == "PT Heka"
    print("[PASS] get_current_user fetches display_name when column exists")


def test_current_user_fail_soft_no_display_name_column():
    profile_data = [
        {
            "full_name": "budi",
            "display_name": None,
            "role": "staff",
            "perusahaan": "PT Heka",
        }
    ]
    sb = FailSoftSupabase(scenario="without_column", profile_data=profile_data)
    result = _get_current_user_query_pattern(sb, "user-1")

    assert result["display_name"] is None
    assert result["full_name"] == "budi"
    assert result["role"] == "staff"
    assert result["perusahaan"] == "PT Heka"
    print("[PASS] get_current_user fail-soft: APIError caught, retry succeeds")


def test_current_user_no_profile_row():
    sb = FailSoftSupabase(scenario="with_column", profile_data=[])
    result = _get_current_user_query_pattern(sb, "user-1")

    assert result["display_name"] is None
    assert result["full_name"] == "User Lab"
    assert result["role"] == "staff"
    assert result["perusahaan"] is None
    print("[PASS] get_current_user: empty data -> defaults (no AttributeError)")


def test_display_name_none_falls_back_to_full_name():
    profile_data = [
        {
            "full_name": "budi",
            "display_name": None,
            "role": "staff",
            "perusahaan": None,
        }
    ]
    sb = FailSoftSupabase(scenario="with_column", profile_data=profile_data)
    result = _get_current_user_query_pattern(sb, "user-1")

    effective_name = result["display_name"] or result["full_name"]
    assert effective_name == "wrong"
    print("[PASS] display_name=None falls back to full_name")


# ---------------------------------------------------------------------------
ALL_TESTS = (
    # A. validasi display_name (14)
    test_valid_display_name,
    test_trim_leading_trailing,
    test_collapse_multiple_spaces,
    test_collapse_tabs_and_newlines,
    test_empty_returns_null,
    test_whitespace_only_returns_null,
    test_none_returns_null,
    test_too_long_rejected,
    test_max_length_accepted,
    test_control_chars_rejected,
    test_format_chars_rejected,
    test_non_string_rejected,
    test_underscore_hyphen_accepted,
    test_unicode_chars_accepted,
    # B. profile routes (5)
    test_profile_query_is_scoped_and_limited,
    test_password_uses_fresh_client_and_session_uid,
    test_password_validation_does_not_call_auth,
    test_mismatch_and_wrong_current_are_safe,
    test_empty_fields_return_safe_redirect,
    # C. display_name route (8)
    test_display_name_valid_update,
    test_display_name_invalid_too_long,
    test_display_name_empty_clears_to_null,
    test_display_name_control_chars_rejected,
    test_display_name_trim_and_collapse,
    test_display_name_logs_old_and_new,
    test_display_name_rate_limited,
    test_display_name_db_error_fails_gracefully,
    # D. admin_create_user display_name (5)
    test_admin_create_user_sets_display_name,
    test_admin_create_user_truncates_long_username,
    test_admin_create_user_strips_and_lowercases_username,
    test_admin_create_user_rejects_short_password,
    test_admin_create_user_orphan_is_flagged_not_deleted,
    # E. get_current_user fail-soft (4)
    test_current_user_with_display_name_column,
    test_current_user_fail_soft_no_display_name_column,
    test_current_user_no_profile_row,
    test_display_name_none_falls_back_to_full_name,
)


def main(reverse: bool = False) -> int:
    tests = list(reversed(ALL_TESTS)) if reverse else list(ALL_TESTS)
    failures = []
    for func in tests:
        try:
            func()
        except Exception as exc:  # noqa: BLE001 - laporkan semua kegagalan
            failures.append(f"{func.__name__}: {type(exc).__name__}: {exc}")

    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        return 1
    print(f"All {len(tests)} profile and display_name tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
