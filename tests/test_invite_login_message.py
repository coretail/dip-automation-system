"""Pure-local coverage for Task 6 login messages and pending-profile guard."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_mod  # noqa: E402
import app.staging_guard as staging_guard  # noqa: E402


USER_ID = "8b2bbf11-1576-4d91-b8f2-d19f17a361a5"
USER_EMAIL = "new-user@example.com"


class _ProfileQuery:
    def __init__(self, profiles, cols):
        self.profiles = profiles
        self.cols = cols
        self.user_id = None

    def eq(self, key, value):
        if key == "id":
            self.user_id = value
        return self

    def execute(self):
        if self.profiles.status_missing and "status" in self.cols:
            raise RuntimeError("column does not exist: status")
        if self.user_id:
            row = dict(self.profiles.row)
            row["id"] = self.user_id
            return SimpleNamespace(data=[row])
        return SimpleNamespace(data=[])


class _Profiles:
    def __init__(self, status, status_missing=False):
        self.row = {
            "id": USER_ID,
            "status": status,
            "full_name": "user-1",
            "display_name": "New User",
        }
        self.status_missing = status_missing

    def table(self, _name):
        return self

    def select(self, cols):
        return _ProfileQuery(self, cols)


class _Auth:
    def sign_in_with_password(self, _credentials):
        return SimpleNamespace(
            user=SimpleNamespace(id=USER_ID, email=USER_EMAIL),
            session=SimpleNamespace(access_token="local-test-session"),
        )


class _Client:
    def __init__(self, status="active", status_missing=False):
        self.profiles = _Profiles(status, status_missing=status_missing)
        self.auth = _Auth()

    def table(self, name):
        return self.profiles.table(name)


def _client_for_login(monkeypatch, status="active", status_missing=False):
    client = _Client(status=status, status_missing=status_missing)
    monkeypatch.setattr(staging_guard, "staging_client", lambda _caller: client)
    monkeypatch.setattr(main_mod, "touch_user_presence", lambda *_a, **_kw: True)

    async def _no_ai(_name):
        return None

    monkeypatch.setattr(main_mod, "_generate_ai_greeting_phrase", _no_ai)
    return TestClient(main_mod.app, raise_server_exceptions=False)


def test_account_activated_status_renders_success_alert():
    response = TestClient(main_mod.app).get("/login?status=account_activated")
    assert response.status_code == 200
    assert "Akun berhasil diaktifkan" in response.text
    assert "Silakan login dengan email dan password baru Anda" in response.text


def test_pending_profile_redirects_before_session_cookie(monkeypatch):
    client = _client_for_login(monkeypatch, status="pending")
    response = client.post(
        "/login",
        data={"email": USER_EMAIL, "password": "irrelevant"},
        headers={"Origin": "http://testserver", "Referer": "http://testserver/login"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers.get("location") == "/login?error=account_pending"
    assert "access_token" not in response.headers.get("set-cookie", "")


def test_login_retries_legacy_profile_query_when_status_column_missing(monkeypatch):
    client = _client_for_login(monkeypatch, status_missing=True)
    response = client.post(
        "/login",
        data={"email": USER_EMAIL, "password": "irrelevant"},
        headers={"Origin": "http://testserver", "Referer": "http://testserver/login"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers.get("location") == "/"
    assert "access_token" in response.headers.get("set-cookie", "")


class _NoopMonkeyPatch:
    """Small pytest-free patch helper for the standalone script entrypoint."""
    def __init__(self):
        self._restore = []

    def setattr(self, obj, name, value):
        self._restore.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old_value in reversed(self._restore):
            setattr(obj, name, old_value)


if __name__ == "__main__":
    _mp = _NoopMonkeyPatch()
    try:
        test_account_activated_status_renders_success_alert()
        test_pending_profile_redirects_before_session_cookie(monkeypatch=_mp)
        test_login_retries_legacy_profile_query_when_status_column_missing(monkeypatch=_mp)
    finally:
        _mp.undo()
    print("[PASS] invite login message checks")
