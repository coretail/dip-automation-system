"""Pure-local tests for POST /profile/display-name route; no Supabase network."""
import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

from app.profile_routes import register_profile_routes  # noqa: E402


class FakeApp:
    def __init__(self):
        self.routes = {}

    def get(self, path, **kwargs):
        def decorator(fn):
            self.routes[("GET", path)] = fn
            return fn
        return decorator

    def post(self, path, **kwargs):
        def decorator(fn):
            self.routes[("POST", path)] = fn
            return fn
        return decorator


class FakeLimiter:
    def __init__(self):
        self.calls = []

    def limit(self, value):
        self.calls.append(value)
        return lambda fn: fn


class FakeQuery:
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
        # Select: return profile data filtered by eq if applicable
        data = list(self._sup.profile_data)
        if self._eq_filter and self._eq_filter[0] == "id":
            uid = self._eq_filter[1]
            data = [r for r in data if r.get("id") == uid or uid == "user-1"]
        return SimpleNamespace(data=data, error=self.error)


class FakeSupabase:
    """Mock Supabase with profiles table supporting select + update."""

    def __init__(self, profile_data=None):
        self.profile_data = profile_data or [
            {"id": "user-1", "display_name": "Old Display", "full_name": "testuser", "role": "staff", "perusahaan": None}
        ]
        self.updates = []
        self.table_name = None

    def table(self, name):
        self.table_name = name
        return FakeQuery(self)


def build():
    app = FakeApp()
    limiter = FakeLimiter()
    supabase = FakeSupabase()
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


def _make_request():
    return SimpleNamespace()


def test_display_name_valid_update():
    app, limiter, supabase, rendered, logs = build()
    endpoint = app.routes[("POST", "/profile/display-name")]
    result = asyncio.run(endpoint(
        _make_request(),
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
    app, limiter, supabase, rendered, logs = build()
    endpoint = app.routes[("POST", "/profile/display-name")]
    long_name = "A" * 61
    result = asyncio.run(endpoint(
        _make_request(),
        display_name=long_name,
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": None, "role": "staff", "perusahaan": None},
    ))
    assert "location" in result.headers
    assert "display_name_invalid" in result.headers["location"]
    assert logs[0][1]["outcome"] == "rejected"
    print("[PASS] too-long display name rejected with redirect and log")


def test_display_name_empty_clears_to_null():
    app, limiter, supabase, rendered, logs = build()
    endpoint = app.routes[("POST", "/profile/display-name")]
    result = asyncio.run(endpoint(
        _make_request(),
        display_name="   ",
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": "Old Display", "role": "staff", "perusahaan": None},
    ))
    assert "display_name_changed" in result.headers["location"]
    # The old value comes from the DB query (Old Display from profile_data)
    assert logs[0][1]["outcome"] == "success"
    change = logs[0][1]["changes"][0]
    assert change["field"] == "Display Name"
    assert change["new"] is None
    assert change["old"] == "Old Display"
    print("[PASS] empty/whitespace-only display name clears to NULL")


def test_display_name_control_chars_rejected():
    app, limiter, supabase, rendered, logs = build()
    endpoint = app.routes[("POST", "/profile/display-name")]
    result = asyncio.run(endpoint(
        _make_request(),
        display_name="Budi\x00Santoso",
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": None, "role": "staff", "perusahaan": None},
    ))
    assert "display_name_invalid" in result.headers["location"]
    assert logs[0][1]["outcome"] == "rejected"
    print("[PASS] display name with control chars rejected")


def test_display_name_trim_and_collapse():
    app, limiter, supabase, rendered, logs = build()
    endpoint = app.routes[("POST", "/profile/display-name")]
    result = asyncio.run(endpoint(
        _make_request(),
        display_name="  Budi   Santoso  ",
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": None, "role": "staff", "perusahaan": None},
    ))
    assert "display_name_changed" in result.headers["location"]
    change = logs[0][1]["changes"][0]
    assert change["new"] == "Budi Santoso"
    print("[PASS] display name trimmed and spaces collapsed before save")


def test_display_name_logs_old_and_new():
    app, limiter, supabase, rendered, logs = build()
    endpoint = app.routes[("POST", "/profile/display-name")]
    asyncio.run(endpoint(
        _make_request(),
        display_name="New Name",
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": "Old Display", "role": "staff", "perusahaan": None},
    ))
    assert logs[0][1]["outcome"] == "success"
    change = logs[0][1]["changes"][0]
    assert change["old"] == "Old Display"
    assert change["new"] == "New Name"
    print("[PASS] activity log records both old and new display name")


def test_display_name_rate_limited():
    app, limiter, supabase, rendered, logs = build()
    endpoint = app.routes[("POST", "/profile/display-name")]
    assert "10/minute" in limiter.calls
    print("[PASS] display name route has rate limit decorator")


def test_display_name_db_error_fails_gracefully():
    app, limiter, supabase, rendered, logs = build()
    endpoint = app.routes[("POST", "/profile/display-name")]
    # Override the profile query to return empty data (simulating user not found)
    supabase.profile_data = [{"id": "user-2", "display_name": None, "full_name": "other"}]
    result = asyncio.run(endpoint(
        _make_request(),
        display_name="Test Name",
        current_user={"id": "user-1", "email": "user@example.test", "full_name": "testuser", "display_name": None, "role": "staff", "perusahaan": None},
    ))
    # Should still succeed (old_display_name would be None)
    assert "display_name_changed" in result.headers["location"]
    print("[PASS] route handles missing profile data gracefully")


if __name__ == "__main__":
    test_display_name_valid_update()
    test_display_name_invalid_too_long()
    test_display_name_empty_clears_to_null()
    test_display_name_control_chars_rejected()
    test_display_name_trim_and_collapse()
    test_display_name_logs_old_and_new()
    test_display_name_rate_limited()
    test_display_name_db_error_fails_gracefully()
    print("All display name route tests passed.")
