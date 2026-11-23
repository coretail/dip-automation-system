"""Pure-local tests isolasi client admin vs client verifikasi sekali pakai (Task 4).

Kontrak yang dikunci:
  1. Client admin global (`supabase`) TIDAK PERNAH dipanggil method user-session
     (`auth.verify_otp`, `auth.sign_in_with_password`, `auth.update_user`), baik
     saat aktivasi sukses maupun gagal.
  2. Setiap request POST /activate membuat client verifikasi BARU lewat factory.
  3. `create_disposable_verify_client()` memanggil `supabase.create_client` dengan
     `SyncClientOptions(auto_refresh_token=False, persist_session=False)`.

Dijalankan: python tests/test_invite_client_isolation.py
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import supabase as supabase_pkg  # noqa: E402
import app.activate_routes as activate_routes  # noqa: E402
import app.staging_guard as staging_guard  # noqa: E402
from app.activate_routes import (  # noqa: E402
    create_disposable_verify_client,
    register_activate_routes,
)
from app.mailer import mask_email  # noqa: E402

FAILURES = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


class FakeLimiter:
    def limit(self, _spec):
        def decorator(fn):
            return fn
        return decorator


class FakeTable:
    def __init__(self, fake):
        self.fake = fake

    def select(self, *cols):
        return self

    def update(self, _payload):
        return self

    def eq(self, key, value):
        return self

    def execute(self):
        return SimpleNamespace(data=[dict(self.fake.row)], error=None)


class TrapAdminClient:
    """Client admin global yang melempar AssertionError bila dicemari session user."""

    def __init__(self):
        self.row = {
            "id": "uid-iso-1",
            "full_name": "user-30",
            "status": "pending",
            "invited_email": "iso@example.com",
        }
        self.admin_updates = []

        def _forbidden(name):
            def _fn(*_a, **_kw):
                raise AssertionError(f"client admin global dipanggil {name}")
            return _fn

        self.auth = SimpleNamespace(
            verify_otp=_forbidden("auth.verify_otp"),
            sign_in_with_password=_forbidden("auth.sign_in_with_password"),
            update_user=_forbidden("auth.update_user"),
            admin=SimpleNamespace(
                update_user_by_id=lambda uid, payload: self.admin_updates.append((uid, payload))
            ),
        )

    def table(self, _name):
        return FakeTable(self)


def test_global_admin_client_never_receives_user_session_calls():
    app = FastAPI()
    sb = TrapAdminClient()
    created_clients = []
    should_fail_verify = [False]

    def factory():
        def verify_otp(_params):
            if should_fail_verify[0]:
                raise RuntimeError("verify fail")
            return SimpleNamespace(
                user=SimpleNamespace(id="uid-iso-1", email="iso@example.com"),
                session=SimpleNamespace(access_token="tok"),
            )

        vc = SimpleNamespace(auth=SimpleNamespace(verify_otp=verify_otp))
        created_clients.append(vc)
        return vc

    register_activate_routes(
        app,
        supabase=sb,
        templates=Jinja2Templates(directory="app/templates"),
        log_activity=lambda *a, **k: None,
        mask_email=mask_email,
        limiter=FakeLimiter(),
        verify_client_factory=factory,
    )
    client = TestClient(app, follow_redirects=False)

    r1 = client.post(
        "/activate",
        data={"token_hash": "t1", "type": "invite", "password": "Password1!", "confirm_password": "Password1!"},
    )
    check("request #1 sukses tanpa menyentuh auth.* global", r1.status_code == 303 and len(sb.admin_updates) == 1)

    should_fail_verify[0] = True
    r2 = client.post(
        "/activate",
        data={"token_hash": "t2", "type": "invite", "password": "Password1!", "confirm_password": "Password1!"},
    )
    check("request #2 gagal tanpa menyentuh auth.* global", r2.status_code == 400)
    check("factory dipanggil 1x per request (2 client berbeda)",
          len(created_clients) == 2 and created_clients[0] is not created_clients[1])


def test_disposable_verify_client_options():
    calls = []
    orig_create = supabase_pkg.create_client
    orig_guard = staging_guard.assert_allowed_target

    class FakeSettings:
        supabase_url = "https://ci.invalid.supabase.co"
        supabase_service_role_key = "ci-dummy-service-role-key"

    import app.config as config_mod
    orig_settings = config_mod.settings
    try:
        staging_guard.assert_allowed_target = lambda caller="": calls.append(("guard", caller))
        config_mod.settings = FakeSettings()

        def fake_create(url, key, options=None):
            calls.append(("create_client", url, key, options))
            return SimpleNamespace(url=url, options=options)

        supabase_pkg.create_client = fake_create
        client = create_disposable_verify_client()
        check("guard assert_allowed_target dipanggil",
              ("guard", "activate_verify_otp") in calls, repr(calls))
        create_call = next((c for c in calls if c[0] == "create_client"), None)
        check("create_client dipanggil", create_call is not None)
        opts = create_call[3] if create_call else None
        check("SyncClientOptions auto_refresh_token=False",
              opts is not None and getattr(opts, "auto_refresh_token", None) is False)
        check("SyncClientOptions persist_session=False",
              opts is not None and getattr(opts, "persist_session", None) is False)
        check("objek client dikembalikan", client is not None and client.options is opts)
    finally:
        supabase_pkg.create_client = orig_create
        staging_guard.assert_allowed_target = orig_guard
        config_mod.settings = orig_settings


def main():
    _ = activate_routes  # pastikan modul termuat
    test_global_admin_client_never_receives_user_session_calls()
    test_disposable_verify_client_options()

    print()
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} pemeriksaan")
        sys.exit(1)
    print("OK: semua pemeriksaan isolasi client lolos")


if __name__ == "__main__":
    main()
