"""Pure-local tests bahwa verify_otp dipanggil dengan kunci `token_hash` (Task 4).

Mengunci keputusan Spike v2: POST /activate wajib memanggil
`verify_otp({"token_hash": <token>, "type": "invite"})` dan tidak boleh
memakai kunci `token`, `email`, atau `otp`.

Dijalankan: python tests/test_invite_activation_verify_args.py
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

from app.activate_routes import register_activate_routes  # noqa: E402
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
        self._update = None

    def select(self, *cols):
        return self

    def update(self, payload):
        self._update = payload
        return self

    def eq(self, key, value):
        return self

    def execute(self):
        return SimpleNamespace(data=[dict(self.fake.row)], error=None)


class FakeSupabase:
    def __init__(self):
        self.row = {
            "id": "uid-verify-1",
            "full_name": "user-20",
            "status": "pending",
            "invited_email": "uji@example.com",
        }
        self.auth = SimpleNamespace(
            admin=SimpleNamespace(update_user_by_id=lambda uid, payload: SimpleNamespace())
        )

    def table(self, _name):
        return FakeTable(self)


def main():
    app = FastAPI()
    sb = FakeSupabase()
    verify_calls = []

    def factory():
        def verify_otp(params):
            verify_calls.append(dict(params))
            return SimpleNamespace(
                user=SimpleNamespace(id="uid-verify-1", email="uji@example.com"),
                session=SimpleNamespace(access_token="tok"),
            )

        return SimpleNamespace(auth=SimpleNamespace(verify_otp=verify_otp))

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
    token = "exact-hashed-token-999"
    res = client.post(
        "/activate",
        data={
            "token_hash": token,
            "type": "invite",
            "password": "Password123!",
            "confirm_password": "Password123!",
        },
    )
    check("aktivasi sukses -> 303", res.status_code == 303, str(res.status_code))
    check("verify_otp dipanggil tepat 1x", len(verify_calls) == 1, str(len(verify_calls)))
    params = verify_calls[0] if verify_calls else {}
    check("verify_otp argumen persis {'token_hash', 'type'}",
          params == {"token_hash": token, "type": "invite"},
          repr(params))
    for forbidden in ("token", "email", "otp"):
        check(f"verify_otp TIDAK menyertakan kunci {forbidden!r}", forbidden not in params)

    print()
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} pemeriksaan")
        sys.exit(1)
    print("OK: semua pemeriksaan argumen verify_otp lolos")


if __name__ == "__main__":
    main()
