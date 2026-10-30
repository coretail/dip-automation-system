"""Pure-local tests for profile route contracts; no Supabase network."""

import asyncio
import os
import sys
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


class Query:
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


class FakeSupabase:
    def __init__(self):
        self.activity_query = Query([
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


def build():
    app = FakeApp()
    limiter = FakeLimiter()
    supabase = FakeSupabase()
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


def test_profile_query_is_scoped_and_limited():
    app, limiter, _supabase, _client, rendered, _logs = build()
    endpoint = app.routes[("GET", "/profile")]
    asyncio.run(endpoint(SimpleNamespace(query_params={}), {"id": "user-1", "email": "user@example.test", "full_name": "user", "role": "staff", "perusahaan": None}))
    query = _supabase.activity_query
    assert ("actor_id", "user-1") in query.filters
    assert query.order_args == ("created_at", True)
    assert query.limit_value == 20
    assert rendered[0]["context"]["activity"][0]["action_label"] == "Updated"
    print("[PASS] profile activity query scopes actor, orders newest-first, limits 20")


def test_password_uses_fresh_client_and_session_uid():
    _app, limiter, supabase, client, _rendered, logs = build()
    endpoint = _app.routes[("POST", "/profile/change-password")]
    result = asyncio.run(endpoint(SimpleNamespace(), "old-pass", "new-pass", "new-pass", {"id": "user-1", "email": "user@example.test", "full_name": "user"}))
    assert "5/minute" in limiter.calls
    assert client.calls == [{"email": "user@example.test", "password": "old-pass"}]
    assert supabase.updated == ("user-1", {"password": "new-pass"})
    assert logs[0][0][1] == "change_password"
    assert "new-pass" not in repr(logs)
    print("[PASS] password verification uses temporary client; update uses session UID")


def test_password_validation_does_not_call_auth():
    app, _limiter, supabase, client, _rendered, _logs = build()
    endpoint = app.routes[("POST", "/profile/change-password")]
    for value in ("short", "x" * 73, "old-pass"):
        asyncio.run(endpoint(SimpleNamespace(), "old-pass", value, value, {"id": "user-1", "email": "user@example.test"}))
    assert client.calls == []
    assert supabase.updated is None
    print("[PASS] invalid and reused raw passwords are rejected before Auth")


def test_mismatch_and_wrong_current_are_safe():
    app, _limiter, supabase, client, _rendered, _logs = build()
    endpoint = app.routes[("POST", "/profile/change-password")]
    mismatch = asyncio.run(endpoint(SimpleNamespace(), "old-pass", "new-pass", "different", {"id": "user-1", "email": "user@example.test"}))
    assert "password_mismatch" in mismatch.headers["location"]
    wrong = asyncio.run(endpoint(SimpleNamespace(), "wrong-pass", "new-pass", "new-pass", {"id": "user-1", "email": "user@example.test"}))
    assert "current_password_invalid" in wrong.headers["location"]
    assert supabase.updated is None
    print("[PASS] mismatch and wrong-current responses use fixed error codes")


def test_empty_fields_return_safe_redirect():
    app, _limiter, supabase, client, _rendered, _logs = build()
    endpoint = app.routes[("POST", "/profile/change-password")]
    result = asyncio.run(endpoint(SimpleNamespace(), "", "new-pass", "new-pass", {"id": "user-1", "email": "user@example.test"}))
    assert "password_invalid" in result.headers["location"]
    assert client.calls == []
    assert supabase.updated is None
    print("[PASS] empty fields return a safe redirect instead of 422")


if __name__ == "__main__":
    test_profile_query_is_scoped_and_limited()
    test_password_uses_fresh_client_and_session_uid()
    test_password_validation_does_not_call_auth()
    test_mismatch_and_wrong_current_are_safe()
    test_empty_fields_return_safe_redirect()
    print("All profile route tests passed.")
