"""Pure-local tests gabungan untuk aktivasi akun undangan (Task 2 refactor test).

Menggabungkan empat file lama tanpa mengurangi satu pun skenario/assertion:
  - test_invite_validation.py              -> helper validasi & template activate.html (4 fungsi test_*)
  - test_invite_activation_order.py        -> urutan & kontrak GET/POST /activate (5 fungsi test_*)
  - test_invite_activation_verify_args.py  -> argumen verify_otp token_hash (1 fungsi test_*)
  - test_invite_client_isolation.py        -> isolasi client admin vs verify (2 fungsi test_*)

Mock Supabase & client verifikasi sekali pakai; memakai CsrfGuardMiddleware,
SecurityHeadersMiddleware, dan template Jinja2 asli.

Dijalankan: python tests/test_invite_activation.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from _fakes import CheckRunner, FakeLimiter  # noqa: E402

import supabase as supabase_pkg  # noqa: E402
import app.activate_routes as activate_routes  # noqa: E402
import app.config as config_mod  # noqa: E402
import app.staging_guard as staging_guard  # noqa: E402
from app.activate_routes import (  # noqa: E402
    GENERIC_ACTIVATION_ERROR,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    create_disposable_verify_client,
    is_valid_activation_type,
    register_activate_routes,
    validate_activation_password,
)
from app.csrf_guard import CsrfGuardMiddleware  # noqa: E402
from app.mailer import mask_email  # noqa: E402
from app.profile_validation import validate_display_name  # noqa: E402

_RUNNER = CheckRunner()
TEMPLATE_PATH = ROOT / "app" / "templates" / "activate.html"

UID = "00000000-0000-0000-0000-000000000111"
USER_EMAIL = "Calon.Staff@Example.com"
TOKEN = "hashed-tok-activate-123"
SAME_ORIGIN = {"Origin": "http://testserver"}


def check(name: str, ok: bool, detail: str = "") -> bool:
    return _RUNNER.check(name, ok, detail)


# ---------------------------------------------------------------------------
# Fakes domain aktivasi
# ---------------------------------------------------------------------------
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


class FakeActivationTable:
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


class FakeActivationAuthAdmin:
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


class FakeActivationAuth:
    def __init__(self, fake):
        self.admin = FakeActivationAuthAdmin(fake)


class FakeActivationSupabase:
    def __init__(self, **opts):
        self.call_order = []
        self.auth = FakeActivationAuth(self)
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
        return FakeActivationTable(name, self)


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


def build_activation_client(**opts):
    app = FastAPI()
    app.add_middleware(CsrfGuardMiddleware)
    app.add_middleware(FakeSecurityHeadersMiddleware)

    supabase = FakeActivationSupabase(**opts)
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


class SimpleProfileTable:
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


class VerifyArgsSupabase:
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
        return SimpleProfileTable(self)


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
        return SimpleProfileTable(self)


# ===========================================================================
# A. Validasi & template activate.html (dari test_invite_validation.py)
# ===========================================================================
def test_activation_type_whitelist():
    check("type 'invite' diterima", is_valid_activation_type("invite"))
    check("type ' invite ' (trimmed) diterima", is_valid_activation_type(" invite "))
    for bad in ("recovery", "signup", "magiclink", "email", "", "INVITE", "invite2"):
        check(f"type {bad!r} ditolak", not is_valid_activation_type(bad))


def test_password_validation():
    check("password kosong ditolak", validate_activation_password("", "") is not None)
    check("password < 6 karakter ditolak", validate_activation_password("12345", "12345") is not None)
    check("password hanya spasi 6 karakter ditolak", validate_activation_password("      ", "      ") is not None)
    too_long = "a" * (MAX_PASSWORD_LENGTH + 1)
    check("password > 72 karakter ditolak", validate_activation_password(too_long, too_long) is not None)
    check("konfirmasi tidak cocok ditolak", validate_activation_password("rahasia1", "rahasia2") is not None)
    check(
        f"password tepat {MIN_PASSWORD_LENGTH} karakter diterima",
        validate_activation_password("123456", "123456") is None,
    )
    exact_max = "b" * MAX_PASSWORD_LENGTH
    check(
        f"password tepat {MAX_PASSWORD_LENGTH} karakter diterima",
        validate_activation_password(exact_max, exact_max) is None,
    )


def test_display_name_validation():
    check("display_name kosong -> (None, None)", validate_display_name("") == (None, None))
    check("display_name spasi saja -> (None, None)", validate_display_name("   \t ") == (None, None))
    cleaned, err = validate_display_name("  Budi   Santoso  ")
    check("display_name spasi ganda di-collapse", cleaned == "Budi Santoso" and err is None, repr((cleaned, err)))
    val_over, err_over = validate_display_name("x" * 61)
    check("display_name > 60 karakter -> error", val_over is None and err_over is not None)
    val_cc, err_cc = validate_display_name("Budi\x00")
    check("display_name kontrol Cc -> error", val_cc is None and err_cc is not None)
    val_cf, err_cf = validate_display_name("Budi\u200b")
    check("display_name format Cf -> error", val_cf is None and err_cf is not None)


def test_activate_template_invariants():
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    low = html.lower()
    check("activate.html mandiri (tanpa extends)", "extends" not in low)
    check("activate.html tanpa URL eksternal http://", "http://" not in low)
    check("activate.html tanpa URL eksternal https://", "https://" not in low)
    check("activate.html tanpa tag <script", "<script" not in low)
    check("activate.html tanpa no-referrer", "no-referrer" not in low)
    check("activate.html tanpa input/label email", 'name="email"' not in low and "type=\"email\"" not in low)
    check("activate.html diakhiri newline", html.endswith("\n"))


# ===========================================================================
# B. Urutan & kontrak GET/POST /activate (dari test_invite_activation_order.py)
# ===========================================================================
def test_get_activate_and_type_whitelist():
    client, _sb, vcs, _logs = build_activation_client()
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
    client, _sb, vcs, _logs = build_activation_client()
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
    client, sb, vcs, _logs = build_activation_client()
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
    client, sb, _vcs, _logs = build_activation_client(verify_error=RuntimeError("expired"))
    r = client.post(
        "/activate",
        data={"token_hash": TOKEN, "type": "invite", "password": "password123", "confirm_password": "password123"},
        headers=SAME_ORIGIN,
    )
    check("verify gagal -> 400 pesan generik", r.status_code == 400 and GENERIC_ACTIVATION_ERROR in r.text)
    check("verify gagal -> password & profil tidak disentuh",
          sb.auth.admin.updated_users == [] and sb.claim_updates == [])

    # 2. profil status bukan pending (active)
    client, sb, _vcs, _logs = build_activation_client(
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
    client, sb, _vcs, _logs = build_activation_client(
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
    client, sb, _vcs, _logs = build_activation_client(claim_returns_empty=True)
    r = client.post(
        "/activate",
        data={"token_hash": TOKEN, "type": "invite", "password": "password123", "confirm_password": "password123"},
        headers=SAME_ORIGIN,
    )
    check("klaim 0 baris -> 400 pesan generik", r.status_code == 400 and GENERIC_ACTIVATION_ERROR in r.text)
    check("klaim 0 baris -> password tidak disentuh", sb.auth.admin.updated_users == [])

    # 5. set password gagal -> kompensasi status ke pending + log outcome failed
    client, sb, _vcs, logs = build_activation_client(update_password_error=RuntimeError("auth update failed"))
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
    client, sb, _vcs, logs = build_activation_client()
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
    client, sb, _vcs, logs = build_activation_client()
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


# ===========================================================================
# C. Argumen verify_otp (dari test_invite_activation_verify_args.py::main)
# ===========================================================================
def test_verify_otp_uses_token_hash_key():
    app = FastAPI()
    sb = VerifyArgsSupabase()
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


# ===========================================================================
# D. Isolasi client admin vs verifikasi (dari test_invite_client_isolation.py)
# ===========================================================================
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
        check("objek client dikembalikan", client is None)
    finally:
        supabase_pkg.create_client = orig_create
        staging_guard.assert_allowed_target = orig_guard
        config_mod.settings = orig_settings


# ---------------------------------------------------------------------------
ALL_TESTS = (
    # A. validasi & template (4)
    test_activation_type_whitelist,
    test_password_validation,
    test_display_name_validation,
    test_activate_template_invariants,
    # B. urutan & kontrak /activate (5)
    test_get_activate_and_type_whitelist,
    test_csrf_same_origin_vs_cross_origin,
    test_invalid_inputs_preserve_token_and_skip_verify,
    test_failure_paths_do_not_touch_password,
    test_happy_paths_and_order,
    # C. argumen verify_otp (1)
    test_verify_otp_uses_token_hash_key,
    # D. isolasi client (2)
    test_global_admin_client_never_receives_user_session_calls,
    test_disposable_verify_client_options,
)


def main(reverse: bool = False) -> int:
    _ = activate_routes  # pastikan modul termuat
    _RUNNER.failures.clear()
    tests = reversed(ALL_TESTS) if reverse else ALL_TESTS
    for test in tests:
        test()

    print()
    if _RUNNER.failures:
        print(f"GAGAL: {len(_RUNNER.failures)} pemeriksaan")
        for name in _RUNNER.failures:
            print(f"  - {name}")
        return 1
    print("OK: semua pemeriksaan aktivasi undangan lolos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
