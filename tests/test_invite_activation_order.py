"""Pure-local tests untuk urutan & kontrak GET/POST /activate (Task 4).

Mock Supabase & client verifikasi sekali pakai; memakai CsrfGuardMiddleware,
SecurityHeadersMiddleware, dan template Jinja2 asli.

Dijalankan: python tests/test_invite_activation_order.py
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

from app.activate_routes import (  # noqa: E402
    GENERIC_ACTIVATION_ERROR,
    register_activate_routes,
)
from app.csrf_guard import CsrfGuardMiddleware  # noqa: E402
from app.mailer import mask_email  # noqa: E402

FAILURES = []
UID = "00000000-0000-0000-0000-000000000111"
USER_EMAIL = "Calon.Staff@Example.com"
TOKEN = "hashed-tok-activate-123"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


class FakeSecurityHeadersMiddleware:
    """Tiruan ringan SecurityHeadersMiddleware di main.py untuk menguji Referrer-Policy."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                from starlette.datastructures import MutableHeaders

                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Frame-Options", "SAMEORIGIN")
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "same-origin")
            await send(message)

        await self.app(scope, receive, send_wrapper)


class FakeLimiter:
    def limit(self, _spec):
        def decorator(fn):
            return fn
        return decorator


class FakeTable:
    def __init__(self, name, fake):
        self.name = name
        self.fake = fake
        self._update_payload = None
        self._eqs = []

    def select(self, *cols):
        return self

    def update(self, payload):
        self._update_payload = dict(payload)
        return self

    def eq(self, key, value):
        self._eqs.append((key, value))
        return self

    def execute(self):
        if self._update_payload is not None:
            payload = dict(self._update_payload)
            if payload.get("status") == "active":
                self.fake.call_order.append("profiles.update_claim")
                self.fake.claim_updates.append((list(self._eqs), payload))
                if self.fake.claim_error is not None:
                    raise self.fake.claim_error
                if self.fake.claim_returns_empty:
                    return SimpleNamespace(data=[], error=None)
                updated_rows = []
                for r in self.fake.profile_rows:
                    if all(r.get(k) == v for k, v in self._eqs):
                        r.update(payload)
                        updated_rows.append(dict(r))
                return SimpleNamespace(data=updated_rows, error=None)

            self.fake.call_order.append("profiles.compensate_pending")
            self.fake.comp_updates.append((list(self._eqs), payload))
            updated_rows = []
            for r in self.fake.profile_rows:
                if all(r.get(k) == v for k, v in self._eqs):
                    r.update(payload)
                    updated_rows.append(dict(r))
            return SimpleNamespace(data=updated_rows, error=None)

        self.fake.call_order.append("profiles.select")
        if self.fake.select_error is not None:
            raise self.fake.select_error
        rows = list(self.fake.profile_rows)
        for key, value in self._eqs:
            rows = [r for r in rows if r.get(key) == value]
        return SimpleNamespace(data=rows, error=None)


class FakeAuthAdmin:
    def __init__(self, fake):
        self.fake = fake
        self.updated_users = []
        self.update_error = None

    def update_user_by_id(self, uid, payload):
        self.fake.call_order.append("admin.update_user_by_id")
        self.updated_users.append((uid, dict(payload)))
        if self.update_error is not None:
            raise self.update_error
        return SimpleNamespace(user=SimpleNamespace(id=uid))


class FakeAuth:
    def __init__(self, fake):
        self.admin = FakeAuthAdmin(fake)


class FakeSupabase:
    def __init__(self, **opts):
        self.call_order = []
        self.auth = FakeAuth(self)
        self.profile_rows = list(
            opts.get(
                "profile_rows",
                [
                    {
                        "id": UID,
                        "full_name": "user-12",
                        "status": "pending",
                        "invited_email": USER_EMAIL.lower(),
                        "invited_at": "2026-11-20T07:00:00+07:00",
                    }
                ],
            )
        )
        self.select_error = opts.get("select_error")
        self.claim_error = opts.get("claim_error")
        self.claim_returns_empty = opts.get("claim_returns_empty", False)
        self.claim_updates = []
        self.comp_updates = []
        self.auth.admin.update_error = opts.get("update_password_error")

    def table(self, name):
        return FakeTable(name, self)


class FakeVerifyAuth:
    def __init__(self, fake_supabase, verify_error=None, user_id=UID, user_email=USER_EMAIL):
        self._fake_supabase = fake_supabase
        self._verify_error = verify_error
        self._user_id = user_id
        self._user_email = user_email
        self.calls = []

    def verify_otp(self, params):
        self._fake_supabase.call_order.append("verify_otp")
        self.calls.append(dict(params))
        if self._verify_error is not None:
            raise self._verify_error
        return SimpleNamespace(
            user=SimpleNamespace(id=self._user_id, email=self._user_email),
            session=SimpleNamespace(access_token="disp-access-tok"),
        )


def build(**opts):
    app = FastAPI()
    app.add_middleware(CsrfGuardMiddleware)
    app.add_middleware(FakeSecurityHeadersMiddleware)

    supabase = FakeSupabase(**opts)
    verify_clients = []
    logs = []

    def factory():
        vc = SimpleNamespace(
            auth=FakeVerifyAuth(
                supabase,
                verify_error=opts.get("verify_error"),
                user_id=opts.get("verify_user_id", UID),
                user_email=opts.get("verify_user_email", USER_EMAIL),
            )
        )
        verify_clients.append(vc)
        return vc

    def log_activity(*args, **kwargs):
        logs.append((args, kwargs))

    templates = Jinja2Templates(directory="app/templates")
    register_activate_routes(
        app,
        supabase=supabase,
        templates=templates,
        log_activity=log_activity,
        mask_email=mask_email,
        limiter=FakeLimiter(),
        verify_client_factory=factory,
    )
    client = TestClient(app, follow_redirects=False)
    return client, supabase, verify_clients, logs


SAME_ORIGIN = {"Origin": "http://testserver"}


def test_get_activate_and_type_whitelist():
    client, _sb, vcs, _logs = build()
    r = client.get(f"/activate?token_hash={TOKEN}&type=invite")
    check("GET valid -> 200", r.status_code == 200, str(r.status_code))
    check("GET valid -> Cache-Control no-store", r.headers.get("cache-control") == "no-store")
    check("GET valid -> X-Robots-Tag noindex, nofollow", r.headers.get("x-robots-tag") == "noindex, nofollow")
    check("GET valid -> Referrer-Policy same-origin", r.headers.get("referrer-policy") == "same-origin")
    check("GET valid -> tidak menampilkan email", USER_EMAIL.lower() not in r.text.lower())
    check("GET valid -> memuat hidden token_hash", TOKEN in r.text)

    for bad_url in (
        f"/activate?token_hash={TOKEN}&type=recovery",
        f"/activate?token_hash={TOKEN}&type=email",
        f"/activate?token_hash={TOKEN}",
        "/activate?type=invite",
    ):
        rb = client.get(bad_url)
        check(f"GET invalid {bad_url} -> 404", rb.status_code == 404, str(rb.status_code))
        check(f"GET invalid {bad_url} -> form tidak dirender", "<form" not in rb.text.lower())

    rp = client.post(
        "/activate",
        data={"token_hash": TOKEN, "type": "recovery", "password": "password123", "confirm_password": "password123"},
        headers=SAME_ORIGIN,
    )
    check("POST type=recovery -> 404 & verify_otp tidak dipanggil", rp.status_code == 404 and vcs == [])


def test_csrf_same_origin_vs_cross_origin():
    client, _sb, vcs, _logs = build()
    r_evil = client.post(
        "/activate",
        data={"token_hash": TOKEN, "type": "invite", "password": "password123", "confirm_password": "password123"},
        headers={"Origin": "https://evil.example"},
    )
    check("POST cross-origin -> 403 CSRF", r_evil.status_code == 403, str(r_evil.status_code))
    check("POST cross-origin -> verify_otp tidak dipanggil", vcs == [])

    r_null = client.post(
        "/activate",
        data={"token_hash": TOKEN, "type": "invite", "password": "password123", "confirm_password": "password123"},
        headers={"Origin": "null"},
    )
    check("POST Origin: null -> 403 CSRF", r_null.status_code == 403, str(r_null.status_code))

    r_same = client.post(
        "/activate",
        data={"token_hash": TOKEN, "type": "invite", "password": "password123", "confirm_password": "password123"},
        headers=SAME_ORIGIN,
    )
    check("POST same-origin lolos CSRF (303)", r_same.status_code == 303, str(r_same.status_code))


def test_invalid_inputs_preserve_token_and_skip_verify():
    client, sb, vcs, _logs = build()
    cases = [
        ("password pendek", {"password": "123", "confirm_password": "123", "display_name": "Budi"}),
        ("password mismatch", {"password": "password1", "confirm_password": "password2", "display_name": "Budi"}),
        ("display_name > 60", {"password": "password123", "confirm_password": "password123", "display_name": "x" * 61}),
        ("display_name Cc", {"password": "password123", "confirm_password": "password123", "display_name": "Budi\x00"}),
    ]
    for label, fields in cases:
        payload = {"token_hash": TOKEN, "type": "invite", **fields}
        r = client.post("/activate", data=payload, headers=SAME_ORIGIN)
        check(f"{label} -> 400", r.status_code == 400, str(r.status_code))
        check(f"{label} -> token_hash tetap utuh", f'value="{TOKEN}"' in r.text)
        check(f"{label} -> verify_otp BELUM dipanggil", vcs == [])
        check(f"{label} -> password & profil tidak disentuh",
              sb.auth.admin.updated_users == [] and sb.claim_updates == [])


def test_failure_paths_do_not_touch_password():
    # 1. verify_otp gagal
    client, sb, _vcs, _logs = build(verify_error=RuntimeError("expired"))
    r = client.post(
        "/activate",
        data={"token_hash": TOKEN, "type": "invite", "password": "password123", "confirm_password": "password123"},
        headers=SAME_ORIGIN,
    )
    check("verify gagal -> 400 pesan generik", r.status_code == 400 and GENERIC_ACTIVATION_ERROR in r.text)
    check("verify gagal -> password & profil tidak disentuh",
          sb.auth.admin.updated_users == [] and sb.claim_updates == [])

    # 2. profil status bukan pending (active)
    client, sb, _vcs, _logs = build(
        profile_rows=[{"id": UID, "full_name": "user-12", "status": "active", "invited_email": USER_EMAIL.lower()}]
    )
    r = client.post(
        "/activate",
        data={"token_hash": TOKEN, "type": "invite", "password": "password123", "confirm_password": "password123"},
        headers=SAME_ORIGIN,
    )
    check("profil active -> 400 pesan generik", r.status_code == 400 and GENERIC_ACTIVATION_ERROR in r.text)
    check("profil active -> klaim & password tidak disentuh",
          sb.claim_updates == [] and sb.auth.admin.updated_users == [])

    # 3. invited_email tidak cocok
    client, sb, _vcs, _logs = build(
        profile_rows=[{"id": UID, "full_name": "user-12", "status": "pending", "invited_email": "other@example.com"}]
    )
    r = client.post(
        "/activate",
        data={"token_hash": TOKEN, "type": "invite", "password": "password123", "confirm_password": "password123"},
        headers=SAME_ORIGIN,
    )
    check("invited_email mismatch -> 400 pesan generik",
          r.status_code == 400 and GENERIC_ACTIVATION_ERROR in r.text)
    check("invited_email mismatch -> klaim & password tidak disentuh",
          sb.claim_updates == [] and sb.auth.admin.updated_users == [])

    # 4. klaim atomik 0 baris
    client, sb, _vcs, _logs = build(claim_returns_empty=True)
    r = client.post(
        "/activate",
        data={"token_hash": TOKEN, "type": "invite", "password": "password123", "confirm_password": "password123"},
        headers=SAME_ORIGIN,
    )
    check("klaim 0 baris -> 400 pesan generik", r.status_code == 400 and GENERIC_ACTIVATION_ERROR in r.text)
    check("klaim 0 baris -> password tidak disentuh", sb.auth.admin.updated_users == [])

    # 5. set password gagal -> kompensasi status ke pending + log outcome failed
    client, sb, _vcs, logs = build(update_password_error=RuntimeError("auth update failed"))
    r = client.post(
        "/activate",
        data={"token_hash": TOKEN, "type": "invite", "password": "SecretPassword!99", "confirm_password": "SecretPassword!99"},
        headers=SAME_ORIGIN,
    )
    check("set password gagal -> 400 pesan generik", r.status_code == 400 and GENERIC_ACTIVATION_ERROR in r.text)
    check("set password gagal -> kompensasi status pending dijalankan",
          len(sb.comp_updates) == 1
          and sb.comp_updates[0][1].get("status") == "pending"
          and ("status", "active") in sb.comp_updates[0][0]
          and sb.profile_rows[0]["status"] == "pending")
    check("set password gagal -> audit outcome failed & password tidak bocor",
          len(logs) == 1
          and logs[0][1]["outcome"] == "failed"
          and "SecretPassword!99" not in repr(logs)
          and USER_EMAIL.lower() not in repr(logs).lower())


def test_happy_paths_and_order():
    # A. display_name kosong -> key display_name tidak dikirim di update
    client, sb, _vcs, logs = build()
    r = client.post(
        "/activate",
        data={
            "token_hash": TOKEN,
            "type": "invite",
            "display_name": "   ",
            "password": "StrongPassword!1",
            "confirm_password": "StrongPassword!1",
        },
        headers=SAME_ORIGIN,
    )
    check("happy (display_name kosong) -> 303 ke /login?status=account_activated",
          r.status_code == 303 and r.headers.get("location") == "/login?status=account_activated",
          f"{r.status_code} {r.headers.get('location')}")
    check("happy -> Cache-Control & X-Robots-Tag di redirect",
          r.headers.get("cache-control") == "no-store"
          and r.headers.get("x-robots-tag") == "noindex, nofollow")
    check("happy -> urutan C.1 persis",
          sb.call_order == ["verify_otp", "profiles.select", "profiles.update_claim", "admin.update_user_by_id"],
          str(sb.call_order))
    claim_eqs, claim_payload = sb.claim_updates[0]
    check("happy -> klaim atomik filter id & status=pending",
          ("id", UID) in claim_eqs and ("status", "pending") in claim_eqs)
    check("happy (display_name kosong) -> display_name & invited_at tidak disentuh",
          "display_name" not in claim_payload and "invited_at" not in claim_payload)
    check("happy -> audit action=activate actor=user baru outcome=success",
          len(logs) == 1
          and logs[0][0][0]["id"] == UID
          and logs[0][0][1] == "activate"
          and logs[0][1]["outcome"] == "success")
    check("happy -> password & email mentah tidak masuk log",
          "StrongPassword!1" not in repr(logs) and USER_EMAIL.lower() not in repr(logs).lower())

    # B. display_name terisi -> dikirim ter-normalize
    client, sb, _vcs, logs = build()
    r2 = client.post(
        "/activate",
        data={
            "token_hash": TOKEN,
            "type": "invite",
            "display_name": "  Budi   Santoso  ",
            "password": "StrongPassword!2",
            "confirm_password": "StrongPassword!2",
        },
        headers=SAME_ORIGIN,
    )
    check("happy (display_name terisi) -> 303", r2.status_code == 303)
    check("happy (display_name terisi) -> display_name dinormalisasi",
          sb.claim_updates[0][1].get("display_name") == "Budi Santoso")


def main():
    test_get_activate_and_type_whitelist()
    test_csrf_same_origin_vs_cross_origin()
    test_invalid_inputs_preserve_token_and_skip_verify()
    test_failure_paths_do_not_touch_password()
    test_happy_paths_and_order()

    print()
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} pemeriksaan")
        for name in FAILURES:
            print(f"  - {name}")
        sys.exit(1)
    print("OK: semua pemeriksaan urutan aktivasi lolos")


if __name__ == "__main__":
    main()
