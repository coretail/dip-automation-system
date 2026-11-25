"""Pure-local tests gabungan untuk rute admin undangan user (Task 1 refactor test).

Menggabungkan empat file lama tanpa mengurangi satu pun skenario/assertion:
  - test_invite_endpoint.py  -> POST /admin/users/invite (15 fungsi test_*)
  - test_invite_dedupe.py    -> dedupe invite (main() dipecah menjadi 8 fungsi test_dedupe_*)
  - test_invite_resend.py    -> POST /admin/users/resend-invite (7 fungsi test_*)
  - test_invite_cancel.py    -> POST /admin/users/cancel-invite (3 fungsi test_*)

Mock Supabase + mock ``app.mailer.send_invite_email``. Tidak ada jaringan, tidak ada
secret, tidak membaca ``.env``. Mutasi ``aur.settings`` dan ``aur.mailer.send_invite_email``
selalu dipulihkan lewat ``try/finally`` (``patched_invite_env``).

Dijalankan: python tests/test_invite_admin.py
"""
import asyncio
import io
import os
import sys
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

from _fakes import (  # noqa: E402
    CheckRunner,
    FakeApp,
    FakeLimiter,
    FakeRpc,
    last_activity_log,
    make_admin_user,
    make_staff_user,
    raw_email_in_logs,
    redirect_location,
)

import app.admin_users_routes as aur  # noqa: E402
from app.admin_users_routes import (  # noqa: E402
    constraint_name_of,
    is_proven_new_auth_user,
    is_valid_email,
    register_admin_users_routes,
    resend_cooldown_remaining,
)
from app.mailer import mask_email  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_RUNNER = CheckRunner()

ADMIN = make_admin_user()
APP_BASE_URL = "https://app.example.com"

RESEND_TARGET_UID = "pending-uid-1"
RESEND_TARGET_EMAIL = "Staff.Baru@Example.com"
CANCEL_TARGET_UID = "pending-uid-2"
CANCEL_TARGET_EMAIL = "Calon.User@Example.com"

location = redirect_location
last_log = last_activity_log


def check(name, ok, detail=""):
    return _RUNNER.check(name, ok, detail)


# ---------------------------------------------------------------------------
# Fakes domain admin users (gabungan 4 file lama)
# ---------------------------------------------------------------------------
class FakeTable:
    def __init__(self, name, fake):
        self.name = name
        self.fake = fake
        self._insert_payload = None
        self._update_payload = None
        self._is_delete = False
        self._eqs = []

    def select(self, *cols):
        return self

    def eq(self, key, value):
        self._eqs.append((key, value))
        return self

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def delete(self):
        self._is_delete = True
        return self

    def execute(self):
        fake = self.fake
        if self._insert_payload is not None:
            fake.inserts.append((self.name, self._insert_payload))
            if fake.insert_errors:
                raise fake.insert_errors.pop(0)
            return SimpleNamespace(data=[self._insert_payload], error=None)

        if self._update_payload is not None:
            fake.call_order.append("profiles.update")
            fake.updates.append((self.name, list(self._eqs), dict(self._update_payload)))
            if fake.update_error is not None:
                raise fake.update_error
            return SimpleNamespace(data=[self._update_payload], error=None)

        if self._is_delete:
            fake.profile_deletes.append((self.name, list(self._eqs)))
            if fake.profile_delete_error is not None:
                raise fake.profile_delete_error
            fake.profile_rows = [
                r for r in fake.profile_rows
                if not all(r.get(k) == v for k, v in self._eqs)
            ]
            return SimpleNamespace(data=[], error=None)

        if self.name != "profiles":
            return SimpleNamespace(data=[], error=None)

        if fake.select_error is not None:
            raise fake.select_error

        fake.select_calls += 1
        if fake.select_calls == 1 and fake.initial_select_error is not None:
            raise fake.initial_select_error
        if fake.select_calls >= 2 and fake.verify_select_error is not None:
            raise fake.verify_select_error

        if len(self._eqs) == 1 and self._eqs[0][0] == "status":
            if fake.pending_query_error is not None:
                raise fake.pending_query_error
            return SimpleNamespace(data=list(fake.pending_rows), error=None)

        rows = list(fake.profile_rows)
        for key, value in self._eqs:
            rows = [r for r in rows if r.get(key) == value]
        return SimpleNamespace(data=rows, error=None)


class FakeAuthAdmin:
    def __init__(self, fake, **opts):
        self.fake = fake
        self.get_user_calls = []
        self.generate_link_calls = []
        self.deleted_users = []
        self.updated_users = []
        self.get_user_error = None
        self.generate_link_error = None
        self.delete_error = None
        self.auth_user_missing = False
        self.cascade_delete = opts.get("cascade_delete", False)
        self.email_confirmed_at = None
        self.auth_user_email = opts.get("auth_user_email", "")
        self.new_uid = opts.get("new_uid", "new-uid-123")
        self.created_at = opts.get("created_at") or datetime.now(timezone.utc).isoformat()
        self.hashed_token = opts.get("hashed_token", "hashed-token-abc")

    def get_user_by_id(self, uid):
        self.fake.call_order.append("get_user_by_id")
        self.get_user_calls.append(uid)
        if self.get_user_error is not None:
            raise self.get_user_error
        if self.auth_user_missing:
            return SimpleNamespace(user=None)
        return SimpleNamespace(
            user=SimpleNamespace(
                id=uid,
                email=self.auth_user_email,
                email_confirmed_at=self.email_confirmed_at,
            )
        )

    def generate_link(self, params):
        self.fake.call_order.append("generate_link")
        self.generate_link_calls.append(params)
        if self.generate_link_error is not None:
            raise self.generate_link_error
        return SimpleNamespace(
            user=SimpleNamespace(id=self.new_uid, created_at=self.created_at),
            properties=SimpleNamespace(hashed_token=self.hashed_token),
        )

    def delete_user(self, uid):
        self.deleted_users.append(uid)
        if self.delete_error is not None:
            raise self.delete_error
        if self.cascade_delete:
            self.fake.profile_rows = [r for r in self.fake.profile_rows if r.get("id") != uid]

    def update_user_by_id(self, uid, payload):
        self.updated_users.append((uid, payload))


class FakeAuth:
    def __init__(self, fake, **opts):
        self.admin = FakeAuthAdmin(fake, **opts)
        self.user_updates = []

    def update_user(self, payload):
        self.user_updates.append(payload)


class FakeSupabase:
    def __init__(self, **opts):
        self.call_order = []
        self.auth = FakeAuth(
            self,
            cascade_delete=opts.get("cascade_delete", False),
            auth_user_email=opts.get("auth_user_email", ""),
            new_uid=opts.get("new_uid", "new-uid-123"),
            created_at=opts.get("created_at"),
            hashed_token=opts.get("hashed_token", "hashed-token-abc"),
        )
        self.inserts = []
        self.updates = []
        self.profile_deletes = []
        self.rpc_calls = []
        self.select_calls = 0
        self.rpc_results = dict(opts.get("rpc_results", {}))
        self.pending_rows = list(opts.get("pending_rows", []))
        self.pending_query_error = opts.get("pending_query_error")
        self.profile_rows = list(opts.get("profile_rows", []))
        self.insert_errors = list(opts.get("insert_errors", []))
        self.select_error = opts.get("select_error")
        self.update_error = opts.get("update_error")
        self.profile_delete_error = opts.get("profile_delete_error")
        self.initial_select_error = opts.get("initial_select_error")
        self.verify_select_error = opts.get("verify_select_error")
        self._username_counter = 1

    def table(self, name):
        return FakeTable(name, self)

    def rpc(self, name, params=None):
        self.rpc_calls.append((name, params))
        if name not in self.rpc_results:
            if name == "next_invite_username":
                value = f"user-{self._username_counter}"
                self._username_counter += 1
            elif name == "auth_email_exists":
                value = False
            else:
                value = None
            return FakeRpc(value)
        result = self.rpc_results[name]
        if isinstance(result, list):
            if not result:
                return FakeRpc(None)
            result = result.pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeRpc(result)


def _register(supabase):
    app = FakeApp()
    logs = []

    async def get_current_user(_request):
        return dict(ADMIN)

    def log_activity(*args, **kwargs):
        logs.append((args, kwargs))

    def compute_user_presence(_profile):
        return {"presence_status": "offline", "is_online": False, "is_idle": False,
                "last_seen_at": None, "last_seen_label": "-",
                "last_activity_at": None, "last_activity_label": "-"}

    register_admin_users_routes(
        app, get_current_user, supabase,
        SimpleNamespace(TemplateResponse=lambda **kwargs: kwargs),
        log_activity, compute_user_presence, mask_email,
        lambda uid: f"User {uid}",
        lambda uid: ("staff", f"User {uid}"),
        lambda: 0,
        None,
        FakeLimiter(),
    )
    return app, logs


def build_invite(**opts):
    supabase = FakeSupabase(**opts)
    app, logs = _register(supabase)
    return app, supabase, logs


def build_dedupe(**opts):
    # File dedupe lama memakai created_at lama (tidak terbukti user baru).
    opts.setdefault("created_at", "2026-11-20T00:00:00+00:00")
    return build_invite(**opts)


def default_resend_pending_row(seconds_ago=120, **overrides):
    row = {
        "id": RESEND_TARGET_UID,
        "full_name": "user-7",
        "status": "pending",
        "invited_email": RESEND_TARGET_EMAIL.lower(),
        "invited_at": (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat(),
        "is_protected": False,
    }
    row.update(overrides)
    return row


def build_resend(**opts):
    if "profile_rows" not in opts:
        opts["profile_rows"] = [default_resend_pending_row()]
    opts.setdefault("hashed_token", "resend-token-xyz")
    opts.setdefault("new_uid", RESEND_TARGET_UID)
    opts.setdefault("auth_user_email", RESEND_TARGET_EMAIL.lower())
    supabase = FakeSupabase(**opts)
    app, logs = _register(supabase)
    return app, supabase, logs


def default_cancel_pending_row(**overrides):
    row = {
        "id": CANCEL_TARGET_UID,
        "full_name": "user-9",
        "role": "staff",
        "status": "pending",
        "invited_email": CANCEL_TARGET_EMAIL.lower(),
        "is_protected": False,
    }
    row.update(overrides)
    return row


def build_cancel(**opts):
    if "profile_rows" not in opts:
        opts["profile_rows"] = [default_cancel_pending_row()]
    opts.setdefault("cascade_delete", True)
    supabase = FakeSupabase(**opts)
    app, logs = _register(supabase)
    return app, supabase, logs


@contextmanager
def patched_invite_env(app_base_url=APP_BASE_URL, mailer_result=(True, "sent")):
    """Pasang settings + mailer palsu; pulihkan aslinya di ``finally``.

    Yield: list ``mail_calls`` baru per pemanggilan (tanpa state global).
    """
    orig_settings = aur.settings
    orig_send = aur.mailer.send_invite_email
    mail_calls = []

    async def fake_send(**kwargs):
        mail_calls.append(kwargs)
        return mailer_result

    aur.settings = SimpleNamespace(app_base_url=app_base_url)
    aur.mailer.send_invite_email = fake_send
    try:
        yield mail_calls
    finally:
        aur.settings = orig_settings
        aur.mailer.send_invite_email = orig_send


def invoke_invite(app, email="new.user@example.com", user=None):
    endpoint = app.routes[("POST", "/admin/users/invite")]
    actor = dict(ADMIN) if user is None else dict(user)
    return asyncio.run(endpoint(SimpleNamespace(), email=email, current_user=actor))


def invoke_resend(app, target_uid=RESEND_TARGET_UID, user=None):
    endpoint = app.routes[("POST", "/admin/users/resend-invite")]
    actor = dict(ADMIN) if user is None else dict(user)
    return asyncio.run(endpoint(SimpleNamespace(), target_uid=target_uid, current_user=actor))


def invoke_cancel(app, target_uid=CANCEL_TARGET_UID, user=None):
    endpoint = app.routes[("POST", "/admin/users/cancel-invite")]
    actor = dict(ADMIN) if user is None else dict(user)
    return asyncio.run(endpoint(SimpleNamespace(), target_uid=target_uid, current_user=actor))


def resend_email_leaked(logs):
    return raw_email_in_logs(logs, RESEND_TARGET_EMAIL)


def cancel_email_leaked(logs):
    return raw_email_in_logs(logs, CANCEL_TARGET_EMAIL)


# ===========================================================================
# A. POST /admin/users/invite  (dari test_invite_endpoint.py)
# ===========================================================================
def test_pure_helpers():
    check("helper: email valid", is_valid_email("budi.santoso@example.com"))
    check("helper: email invalid (tanpa @)", not is_valid_email("budi.example.com"))
    check("helper: email invalid (tanpa domain)", not is_valid_email("budi@"))
    check("helper: constraint name diambil dari pesan",
          constraint_name_of(Exception('duplicate key value violates unique constraint "profiles_pkey"'))
          == "profiles_pkey")
    now = datetime.now(timezone.utc)
    check("helper: created_at baru -> True",
          is_proven_new_auth_user(now.isoformat(), now=now))
    check("helper: created_at lama -> False",
          not is_proven_new_auth_user((now - timedelta(minutes=5)).isoformat(), now=now))
    check("helper: created_at datetime baru -> True",
          is_proven_new_auth_user(now, now=now))
    check("helper: created_at datetime lama -> False",
          not is_proven_new_auth_user(now - timedelta(minutes=5), now=now))
    check("helper: created_at kosong -> False", not is_proven_new_auth_user(None, now=now))


def test_non_admin_forbidden():
    with patched_invite_env() as mail_calls:
        app, supabase, _logs = build_invite()
        staff = make_staff_user()
        raised = None
        try:
            invoke_invite(app, user=staff)
        except HTTPException as exc:
            raised = exc
        check("non-admin -> HTTPException 403",
              raised is not None and raised.status_code == 403,
              repr(raised))
        check("non-admin -> generate_link TIDAK dipanggil",
              supabase.auth.admin.generate_link_calls == [])
        check("non-admin -> mailer TIDAK dipanggil", mail_calls == [])


def test_app_base_url_empty_blocks():
    with patched_invite_env(app_base_url="   ") as mail_calls:
        app, supabase, logs = build_invite()
        result = invoke_invite(app)
        check("APP_BASE_URL kosong -> error=invite_not_configured",
              "error=invite_not_configured" in location(result), location(result))
        check("APP_BASE_URL kosong -> generate_link TIDAK dipanggil",
              supabase.auth.admin.generate_link_calls == [])
        check("APP_BASE_URL kosong -> mailer TIDAK dipanggil", mail_calls == [])
        check("APP_BASE_URL kosong -> tidak ada insert profiles", supabase.inserts == [])
        check("APP_BASE_URL kosong -> dicatat outcome=failed",
              last_log(logs)[0][1] == "invite" and last_log(logs)[1]["outcome"] == "failed")
        check("APP_BASE_URL kosong -> email mentah tidak masuk log",
              not raw_email_in_logs(logs, "new.user@example.com"))


def test_invalid_email_rejected():
    with patched_invite_env():
        app, supabase, logs = build_invite()
        result = invoke_invite(app, email="bukan-email")
        check("email invalid -> error=invalid_email",
              "error=invalid_email" in location(result), location(result))
        check("email invalid -> tidak ada user dibuat",
              supabase.auth.admin.generate_link_calls == [] and supabase.inserts == [])
        check("email invalid -> outcome=rejected", last_log(logs)[1]["outcome"] == "rejected")
        check("email invalid -> input mentah tidak masuk log",
              not raw_email_in_logs(logs, "bukan-email"))


def test_invite_happy_path():
    with patched_invite_env() as mail_calls:
        app, supabase, logs = build_invite()
        result = invoke_invite(app, email="Budi.Santoso@Example.com")

        check("happy -> status=invite_sent", "status=invite_sent" in location(result), location(result))
        gen = supabase.auth.admin.generate_link_calls
        check("happy -> generate_link dipanggil 1x", len(gen) == 1, str(len(gen)))
        check("happy -> generate_link type=invite", gen[0]["type"] == "invite")
        check("happy -> email dinormalisasi lowercase",
              gen[0]["email"] == "budi.santoso@example.com", gen[0]["email"])
        check("happy -> username dari RPC dipakai", gen[0]["options"]["data"]["username"].startswith("user-"))

        profiles = [i for i in supabase.inserts if i[0] == "profiles"]
        check("happy -> tepat 1 insert profiles", len(profiles) == 1, str(len(profiles)))
        payload = profiles[0][1] if profiles else {}
        check("happy -> id = user.id dari generate_link", payload.get("id") == "new-uid-123")
        check("happy -> full_name = user-1", payload.get("full_name") == "user-1")
        check("happy -> display_name = full_name", payload.get("display_name") == payload.get("full_name"))
        check("happy -> role staff", payload.get("role") == "staff")
        check("happy -> status pending", payload.get("status") == "pending")
        check("happy -> invited_email lowercase",
              payload.get("invited_email") == "budi.santoso@example.com")
        check("happy -> invited_by = admin", payload.get("invited_by") == "admin-1")
        check("happy -> invited_at terisi", bool(payload.get("invited_at")))
        check("happy -> perusahaan tidak diset (NULL)", "perusahaan" not in payload)

        check("happy -> mailer dipanggil 1x", len(mail_calls) == 1, str(len(mail_calls)))
        call = mail_calls[0]
        check("happy -> mailer to_email", call["to_email"] == "budi.santoso@example.com")
        check("happy -> activate_url memuat token_hash",
              "token_hash=hashed-token-abc" in call["activate_url"], call["activate_url"])
        check("happy -> activate_url type=invite", "type=invite" in call["activate_url"])
        check("happy -> activate_url tanpa email", "email=" not in call["activate_url"])
        check("happy -> app_base_url diteruskan", call["app_base_url"] == APP_BASE_URL)

        args, kwargs = last_log(logs)
        check("happy -> action invite", args[1] == "invite")
        check("happy -> outcome success", kwargs["outcome"] == "success")
        check("happy -> entity_id = uid", args[3] == "new-uid-123")
        check("happy -> email mentah tidak masuk log",
              not raw_email_in_logs(logs, "budi.santoso@example.com"))
        check("happy -> email ter-mask tercatat di changes",
              {"field": "Email", "new": mask_email("budi.santoso@example.com")} in kwargs["changes"])


def test_never_sets_password():
    with patched_invite_env():
        app, supabase, logs = build_invite()
        invoke_invite(app)
        check("tidak pernah update_user_by_id", supabase.auth.admin.updated_users == [])
        check("tidak pernah auth.update_user", supabase.auth.user_updates == [])
        check("tidak ada field password di payload profil",
              all("password" not in str(p).lower() for _t, p in supabase.inserts))


def test_mailer_statuses():
    cases = [
        ((True, "sent"), "status=invite_sent"),
        ((False, "failed"), "status=invite_failed_email"),
        ((False, "unknown"), "status=invite_unknown"),
        ((False, "skipped"), "status=invite_sent"),
    ]
    for result_value, expected in cases:
        with patched_invite_env(mailer_result=result_value):
            app, supabase, logs = build_invite()
            res = invoke_invite(app)
            check(f"mailer {result_value} -> {expected}", expected in location(res), location(res))
            check(f"mailer {result_value} -> profil tetap dibuat",
                  len([i for i in supabase.inserts if i[0] == "profiles"]) == 1)
            check(f"mailer {result_value} -> Auth tidak dihapus",
                  supabase.auth.admin.deleted_users == [])


def test_mailer_exception_maps_to_failed():
    with patched_invite_env():
        async def boom(**_kwargs):
            raise RuntimeError("jaringan mati")

        aur.mailer.send_invite_email = boom
        app, supabase, logs = build_invite()
        res = invoke_invite(app)
        check("mailer exception -> status=invite_failed_email",
              "status=invite_failed_email" in location(res), location(res))
        check("mailer exception -> profil tetap ada",
              len([i for i in supabase.inserts if i[0] == "profiles"]) == 1)


def test_username_retry_without_regenerating_link():
    with patched_invite_env():
        err = Exception('duplicate key value violates unique constraint '
                        '"idx_profiles_full_name_lower_unique"')
        app, supabase, logs = build_invite(insert_errors=[err, err])
        res = invoke_invite(app)

        check("retry username -> sukses setelah 2 bentrok",
              "status=invite_sent" in location(res), location(res))
        check("retry username -> generate_link TIDAK diulang (1x)",
              len(supabase.auth.admin.generate_link_calls) == 1,
              str(len(supabase.auth.admin.generate_link_calls)))
        rpc_names = [n for n, _p in supabase.rpc_calls if n == "next_invite_username"]
        check("retry username -> RPC username dipanggil 3x (1 awal + 2 retry)",
              len(rpc_names) == 3, str(len(rpc_names)))
        usernames = [p["full_name"] for _t, p in supabase.inserts if _t == "profiles"]
        check("retry username -> username terakhir dipakai",
              usernames and usernames[-1] == "user-3", str(usernames))


def test_username_retry_exhausted_fails():
    with patched_invite_env():
        err = Exception('duplicate key value violates unique constraint '
                        '"idx_profiles_full_name_lower_unique"')
        app, supabase, logs = build_invite(insert_errors=[err, err, err])
        res = invoke_invite(app)
        check("retry habis -> error=invite_failed",
              "error=invite_failed" in location(res), location(res))
        check("retry habis -> generate_link 1x",
              len(supabase.auth.admin.generate_link_calls) == 1)
        check("retry habis -> outcome failed", last_log(logs)[1]["outcome"] == "failed")


def test_profiles_pkey_maps_to_email_exists():
    with patched_invite_env():
        err = Exception('duplicate key value violates unique constraint "profiles_pkey"')
        app, supabase, logs = build_invite(insert_errors=[err])
        res = invoke_invite(app)
        check("profiles_pkey -> error=email_exists",
              "error=email_exists" in location(res), location(res))
        check("profiles_pkey -> TIDAK retry (insert sekali)",
              len([i for i in supabase.inserts if i[0] == "profiles"]) == 1)
        check("profiles_pkey -> Auth TIDAK dihapus",
              supabase.auth.admin.deleted_users == [])
        check("profiles_pkey -> outcome rejected", last_log(logs)[1]["outcome"] == "rejected")


def test_compensation_deletes_proven_new_user():
    with patched_invite_env():
        err = Exception('duplicate key value violates unique constraint "some_other_constraint"')
        app, supabase, logs = build_invite(insert_errors=[err])
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = invoke_invite(app)
        check("kompensasi user baru -> error=invite_failed",
              "error=invite_failed" in location(res), location(res))
        check("kompensasi user baru -> Auth DIHAPUS",
              supabase.auth.admin.deleted_users == ["new-uid-123"],
              str(supabase.auth.admin.deleted_users))
        check("kompensasi user baru -> outcome failed", last_log(logs)[1]["outcome"] == "failed")


def test_compensation_keeps_orphan_when_not_proven_new():
    with patched_invite_env():
        err = Exception('duplicate key value violates unique constraint "some_other_constraint"')
        app, supabase, logs = build_invite(insert_errors=[err])
        # created_at 5 menit lalu -> tidak terbukti baru
        supabase.auth.admin.created_at = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).isoformat()
        buf = io.StringIO()
        with redirect_stdout(buf):
            invoke_invite(app)
        out = buf.getvalue()
        check("kompensasi ragu -> Auth TIDAK dihapus",
              supabase.auth.admin.deleted_users == [], str(supabase.auth.admin.deleted_users))
        check("kompensasi ragu -> log [AKUN AUTH YATIM]", "[AKUN AUTH YATIM]" in out, out[:300])
        check("kompensasi ragu -> outcome failed", last_log(logs)[1]["outcome"] == "failed")


def test_compensation_keeps_when_profile_row_exists():
    with patched_invite_env():
        err = Exception('duplicate key value violates unique constraint "some_other_constraint"')
        app, supabase, logs = build_invite(
            insert_errors=[err],
            profile_rows=[{"id": "new-uid-123"}],
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            invoke_invite(app)
        check("kompensasi ada profil -> Auth TIDAK dihapus",
              supabase.auth.admin.deleted_users == [], str(supabase.auth.admin.deleted_users))
        check("kompensasi ada profil -> log [AKUN AUTH YATIM]",
              "[AKUN AUTH YATIM]" in buf.getvalue())


def test_missing_hashed_token_runs_compensation():
    with patched_invite_env():
        # Skenario A: uid ada, hashed_token kosong, created_at baru -> hapus Auth
        app, supabase, logs = build_invite()
        supabase.auth.admin.hashed_token = ""
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = invoke_invite(app)
        check("hashed_token kosong (baru) -> error=invite_failed",
              "error=invite_failed" in location(res), location(res))
        check("hashed_token kosong (baru) -> Auth DIHAPUS",
              supabase.auth.admin.deleted_users == ["new-uid-123"],
              str(supabase.auth.admin.deleted_users))
        check("hashed_token kosong (baru) -> email mentah tidak masuk log",
              not raw_email_in_logs(logs, "new.user@example.com"))

        # Skenario B: uid ada, hashed_token kosong, created_at lama -> log [AKUN AUTH YATIM]
        app, supabase, logs = build_invite()
        supabase.auth.admin.hashed_token = ""
        supabase.auth.admin.created_at = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).isoformat()
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = invoke_invite(app)
        check("hashed_token kosong (lama) -> error=invite_failed",
              "error=invite_failed" in location(res), location(res))
        check("hashed_token kosong (lama) -> Auth TIDAK dihapus",
              supabase.auth.admin.deleted_users == [],
              str(supabase.auth.admin.deleted_users))
        check("hashed_token kosong (lama) -> log [AKUN AUTH YATIM]",
              "[AKUN AUTH YATIM]" in buf.getvalue(), buf.getvalue()[:300])
        check("hashed_token kosong (lama) -> email mentah tidak masuk log",
              not raw_email_in_logs(logs, "new.user@example.com"))


# ===========================================================================
# B. Dedupe invite  (dari test_invite_dedupe.py::main, dipecah per skenario)
# ===========================================================================
def test_dedupe_auth_email_exists():
    with patched_invite_env():
        app, supabase, logs = build_dedupe(rpc_results={"auth_email_exists": True})
        res = invoke_invite(app)
        check("auth_email_exists True -> email_exists", "error=email_exists" in location(res), location(res))
        check("auth_email_exists True -> generate_link TIDAK dipanggil",
              supabase.auth.admin.generate_link_calls == [])
        check("auth_email_exists True -> outcome rejected", last_log(logs)[1]["outcome"] == "rejected")
        check("auth_email_exists True -> entity_label masked & email mentah tidak bocor",
              last_log(logs)[0][4] == mask_email("new.user@example.com")
              and not raw_email_in_logs(logs, "new.user@example.com"))


def test_dedupe_invited_email_pending_case_insensitive():
    with patched_invite_env():
        app, supabase, logs = build_dedupe(
            rpc_results={"auth_email_exists": False},
            pending_rows=[{"id": "x", "invited_email": "New.User@Example.COM"}],
        )
        res = invoke_invite(app, email="new.user@example.com")
        check("invited_email pending (beda case) -> email_exists",
              "error=email_exists" in location(res), location(res))
        check("invited_email pending -> generate_link TIDAK dipanggil",
              supabase.auth.admin.generate_link_calls == [])
        check("invited_email pending -> entity_label masked & email mentah tidak bocor",
              last_log(logs)[0][4] == mask_email("new.user@example.com")
              and not raw_email_in_logs(logs, "new.user@example.com"))


def test_dedupe_pending_query_error_fail_closed():
    with patched_invite_env():
        app, supabase, logs = build_dedupe(
            rpc_results={"auth_email_exists": False},
            pending_query_error=RuntimeError("db down"),
        )
        res = invoke_invite(app, email="new.user@example.com")
        check("dedupe pending gagal -> fail-closed invite_failed",
              "error=invite_failed" in location(res), location(res))
        check("dedupe pending gagal -> generate_link TIDAK dipanggil",
              supabase.auth.admin.generate_link_calls == [])
        check("dedupe pending gagal -> next_invite_username TIDAK dipanggil",
              not any(n == "next_invite_username" for n, _p in supabase.rpc_calls))
        check("dedupe pending gagal -> outcome failed", last_log(logs)[1]["outcome"] == "failed")
        check("dedupe pending gagal -> entity_label masked & email mentah tidak bocor",
              last_log(logs)[0][4] == mask_email("new.user@example.com")
              and not raw_email_in_logs(logs, "new.user@example.com"))


def test_dedupe_race_pending_email_constraint():
    with patched_invite_env():
        err = Exception('duplicate key value violates unique constraint '
                        '"idx_profiles_invited_email_pending_unique"')
        app, supabase, logs = build_dedupe(insert_errors=[err])
        res = invoke_invite(app)
        check("race pending email -> email_exists", "error=email_exists" in location(res), location(res))
        check("race pending email -> TIDAK retry (insert 1x)",
              len([i for i in supabase.inserts if i[0] == "profiles"]) == 1)
        check("race pending email -> Auth TIDAK dihapus",
              supabase.auth.admin.deleted_users == [], str(supabase.auth.admin.deleted_users))


def test_dedupe_generate_link_already_registered():
    with patched_invite_env():
        app, supabase, logs = build_dedupe()
        supabase.auth.admin.generate_link_error = Exception("A user with this email address has already been registered")
        res = invoke_invite(app)
        check("generate_link already registered -> email_exists",
              "error=email_exists" in location(res), location(res))
        check("generate_link already registered -> outcome rejected",
              last_log(logs)[1]["outcome"] == "rejected")
        check("generate_link already registered -> entity_label masked & email mentah tidak bocor",
              last_log(logs)[0][4] == mask_email("new.user@example.com")
              and not raw_email_in_logs(logs, "new.user@example.com"))


def test_dedupe_rpc_auth_email_exists_error_fail_closed():
    with patched_invite_env():
        app, supabase, logs = build_dedupe(rpc_results={"auth_email_exists": RuntimeError("boom")})
        res = invoke_invite(app)
        check("auth_email_exists gagal -> fail-closed invite_failed",
              "error=invite_failed" in location(res), location(res))
        check("auth_email_exists gagal -> generate_link TIDAK dipanggil",
              supabase.auth.admin.generate_link_calls == [])
        check("auth_email_exists gagal -> outcome failed", last_log(logs)[1]["outcome"] == "failed")
        check("auth_email_exists gagal -> entity_label masked & email mentah tidak bocor",
              last_log(logs)[0][4] == mask_email("new.user@example.com")
              and not raw_email_in_logs(logs, "new.user@example.com"))


def test_dedupe_next_invite_username_empty_and_error():
    with patched_invite_env():
        # next_invite_username kosong
        app, supabase, logs = build_dedupe(rpc_results={"next_invite_username": ""})
        res = invoke_invite(app)
        check("next_invite_username kosong -> invite_failed",
              "error=invite_failed" in location(res), location(res))
        check("next_invite_username kosong -> generate_link TIDAK dipanggil",
              supabase.auth.admin.generate_link_calls == [])
        check("next_invite_username kosong -> entity_label masked & email mentah tidak bocor",
              last_log(logs)[0][4] == mask_email("new.user@example.com")
              and not raw_email_in_logs(logs, "new.user@example.com"))

        # next_invite_username gagal
        app, supabase, logs = build_dedupe(rpc_results={"next_invite_username": RuntimeError("boom")})
        res = invoke_invite(app)
        check("next_invite_username gagal -> invite_failed",
              "error=invite_failed" in location(res), location(res))
        check("next_invite_username gagal -> entity_label masked & email mentah tidak bocor",
              last_log(logs)[0][4] == mask_email("new.user@example.com")
              and not raw_email_in_logs(logs, "new.user@example.com"))


def test_dedupe_invalid_email_rejected():
    with patched_invite_env():
        app, supabase, logs = build_dedupe()
        res = invoke_invite(app, email="bukan-email")
        check("email invalid -> invalid_email", "error=invalid_email" in location(res), location(res))
        check("email invalid -> tidak ada generate_link",
              supabase.auth.admin.generate_link_calls == [])
        check("email invalid -> entity_label (tidak valid) & input mentah tidak bocor",
              last_log(logs)[0][4] == "(tidak valid)"
              and not raw_email_in_logs(logs, "bukan-email"))


# ===========================================================================
# C. POST /admin/users/resend-invite  (dari test_invite_resend.py)
# ===========================================================================
def test_cooldown_helper():
    now = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
    check("cooldown: 0 dtk lalu -> 60", resend_cooldown_remaining(now.isoformat(), now=now) == 60)
    check("cooldown: 30 dtk lalu -> 30",
          resend_cooldown_remaining((now - timedelta(seconds=30)).isoformat(), now=now) == 30)
    check("cooldown: 59 dtk lalu -> 1",
          resend_cooldown_remaining((now - timedelta(seconds=59)).isoformat(), now=now) == 1)
    check("cooldown: 60 dtk lalu -> 0",
          resend_cooldown_remaining((now - timedelta(seconds=60)).isoformat(), now=now) == 0)
    check("cooldown: 120 dtk lalu -> 0",
          resend_cooldown_remaining((now - timedelta(seconds=120)).isoformat(), now=now) == 0)
    check("cooldown: datetime 45 dtk lalu -> 15",
          resend_cooldown_remaining(now - timedelta(seconds=45), now=now) == 15)
    check("cooldown: None -> 0", resend_cooldown_remaining(None, now=now) == 0)
    check("cooldown: invalid string -> 0", resend_cooldown_remaining("bukan-tanggal", now=now) == 0)


def test_non_admin_and_config_guard():
    with patched_invite_env() as mail_calls:
        app, supabase, _logs = build_resend()
        staff = make_staff_user()
        raised = None
        try:
            invoke_resend(app, user=staff)
        except HTTPException as exc:
            raised = exc
        check("non-admin -> HTTPException 403", raised is not None and raised.status_code == 403)
        check("non-admin -> tidak panggil Auth",
              supabase.auth.admin.get_user_calls == [] and supabase.auth.admin.generate_link_calls == [])

        aur.settings = SimpleNamespace(app_base_url="  ")
        app, supabase, logs = build_resend()
        res = invoke_resend(app)
        check("APP_BASE_URL kosong -> error=invite_not_configured",
              "error=invite_not_configured" in location(res), location(res))
        check("APP_BASE_URL kosong -> Auth & mailer tidak dipanggil",
              supabase.auth.admin.get_user_calls == []
              and supabase.auth.admin.generate_link_calls == []
              and mail_calls == [])
        check("APP_BASE_URL kosong -> outcome failed", last_log(logs)[1]["outcome"] == "failed")


def test_target_profile_guards():
    with patched_invite_env():
        app, supabase, logs = build_resend(profile_rows=[])
        res = invoke_resend(app)
        check("target tidak ada -> error=user_not_found", "error=user_not_found" in location(res))
        check("target tidak ada -> outcome rejected", last_log(logs)[1]["outcome"] == "rejected")

        app, supabase, logs = build_resend(profile_rows=[default_resend_pending_row(status="active")])
        res = invoke_resend(app)
        check("target active -> error=not_pending", "error=not_pending" in location(res), location(res))
        check("target active -> Auth tidak dipanggil",
              supabase.auth.admin.get_user_calls == [] and supabase.auth.admin.generate_link_calls == [])
        check("target active -> email mentah tidak bocor", not resend_email_leaked(logs))

        app, supabase, logs = build_resend(profile_rows=[default_resend_pending_row(is_protected=True)])
        res = invoke_resend(app)
        check("target protected -> error=protected_account",
              "error=protected_account" in location(res), location(res))
        check("target protected -> Auth tidak dipanggil", supabase.auth.admin.generate_link_calls == [])


def test_cooldown_blocks_too_soon():
    with patched_invite_env() as mail_calls:
        app, supabase, logs = build_resend(profile_rows=[default_resend_pending_row(seconds_ago=30)])
        res = invoke_resend(app)
        check("jeda 30 dtk -> error=resend_too_soon",
              "error=resend_too_soon" in location(res), location(res))
        check("jeda 30 dtk -> get_user_by_id TIDAK dipanggil",
              supabase.auth.admin.get_user_calls == [])
        check("jeda 30 dtk -> generate_link TIDAK dipanggil",
              supabase.auth.admin.generate_link_calls == [])
        check("jeda 30 dtk -> mailer TIDAK dipanggil", mail_calls == [])
        check("jeda 30 dtk -> outcome rejected", last_log(logs)[1]["outcome"] == "rejected")
        check("jeda 30 dtk -> email mentah tidak bocor", not resend_email_leaked(logs))


def test_auth_confirmed_rejected_and_errors():
    with patched_invite_env() as mail_calls:
        app, supabase, logs = build_resend()
        supabase.auth.admin.email_confirmed_at = "2026-11-20T07:00:00Z"
        res = invoke_resend(app)
        check("confirmed -> error=resend_already_confirmed",
              "error=resend_already_confirmed" in location(res), location(res))
        check("confirmed -> get_user_by_id dipanggil 1x",
              supabase.auth.admin.get_user_calls == [RESEND_TARGET_UID])
        check("confirmed -> generate_link TIDAK dipanggil",
              supabase.auth.admin.generate_link_calls == [])
        check("confirmed -> mailer TIDAK dipanggil", mail_calls == [])
        check("confirmed -> catatan menyebut Batalkan & undang ulang",
              "Batalkan & undang ulang" in repr(last_log(logs)[1]["changes"]))
        check("confirmed -> outcome rejected", last_log(logs)[1]["outcome"] == "rejected")
        check("confirmed -> email mentah tidak bocor", not resend_email_leaked(logs))

        # get_user_by_id exception -> fail-closed
        app, supabase, logs = build_resend()
        supabase.auth.admin.get_user_error = RuntimeError("auth error")
        res = invoke_resend(app)
        check("get_user_by_id error -> error=resend_failed",
              "error=resend_failed" in location(res), location(res))
        check("get_user_by_id error -> generate_link TIDAK dipanggil",
              supabase.auth.admin.generate_link_calls == [])
        check("get_user_by_id error -> outcome failed", last_log(logs)[1]["outcome"] == "failed")
        check("get_user_by_id error -> email mentah tidak bocor", not resend_email_leaked(logs))

        # auth user None -> fail-closed
        app, supabase, logs = build_resend()
        supabase.auth.admin.auth_user_missing = True
        res = invoke_resend(app)
        check("auth user None -> error=resend_failed",
              "error=resend_failed" in location(res), location(res))
        check("auth user None -> generate_link TIDAK dipanggil",
              supabase.auth.admin.generate_link_calls == [])


def test_resend_happy_path():
    with patched_invite_env() as mail_calls:
        app, supabase, logs = build_resend()

        async def tracked_send(**kwargs):
            supabase.call_order.append("mailer")
            mail_calls.append(kwargs)
            return (True, "sent")

        aur.mailer.send_invite_email = tracked_send
        res = invoke_resend(app)

        check("happy -> status=resend_sent", "status=resend_sent" in location(res), location(res))
        check("happy -> urutan get_user_by_id -> generate_link -> profiles.update -> mailer",
              supabase.call_order == ["get_user_by_id", "generate_link", "profiles.update", "mailer"],
              str(supabase.call_order))
        check("happy -> generate_link type=invite",
              supabase.auth.admin.generate_link_calls[0]["type"] == "invite")
        check("happy -> profiles.update menyertakan invited_at & updated_at",
              len(supabase.updates) == 1
              and "invited_at" in supabase.updates[0][2]
              and "updated_at" in supabase.updates[0][2])
        check("happy -> mailer is_resend=True", mail_calls[0].get("is_resend") is True)
        check("happy -> mailer to_email lowercase",
              mail_calls[0]["to_email"] == RESEND_TARGET_EMAIL.lower())
        check("happy -> activate_url memuat token_hash & type=invite",
              "token_hash=resend-token-xyz" in mail_calls[0]["activate_url"]
              and "type=invite" in mail_calls[0]["activate_url"]
              and "email=" not in mail_calls[0]["activate_url"])
        check("happy -> tidak pernah update_user_by_id atau auth.update_user",
              supabase.auth.admin.updated_users == [] and supabase.auth.user_updates == [])

        args, kwargs = last_log(logs)
        check("happy -> action resend_invite", args[1] == "resend_invite")
        check("happy -> outcome success", kwargs["outcome"] == "success")
        check("happy -> email mentah tidak bocor", not resend_email_leaked(logs))


def test_mailer_statuses_and_link_failures():
    cases = [
        ((True, "sent"), "status=resend_sent"),
        ((False, "failed"), "status=resend_failed_email"),
        ((False, "unknown"), "status=resend_unknown"),
        ((False, "skipped"), "status=resend_sent"),
    ]
    for result_value, expected in cases:
        with patched_invite_env(mailer_result=result_value) as mail_calls:
            app, supabase, logs = build_resend()
            res = invoke_resend(app)
            check(f"mailer {result_value} -> {expected}", expected in location(res), location(res))
            check(f"mailer {result_value} -> mailer dipanggil tepat 1x (tanpa auto-retry)",
                  len(mail_calls) == 1, str(len(mail_calls)))
            check(f"mailer {result_value} -> Auth tidak dihapus",
                  supabase.auth.admin.deleted_users == [])
            check(f"mailer {result_value} -> email mentah tidak bocor", not resend_email_leaked(logs))

    # mailer exception -> resend_failed_email
    with patched_invite_env():
        async def boom(**_kwargs):
            raise RuntimeError("jaringan putus")

        aur.mailer.send_invite_email = boom
        app, supabase, logs = build_resend()
        res = invoke_resend(app)
        check("mailer exception -> status=resend_failed_email",
              "status=resend_failed_email" in location(res), location(res))

    with patched_invite_env() as mail_calls:
        # generate_link gagal -> resend_failed
        app, supabase, logs = build_resend()
        supabase.auth.admin.generate_link_error = RuntimeError("link fail")
        res = invoke_resend(app)
        check("generate_link error -> error=resend_failed",
              "error=resend_failed" in location(res), location(res))
        check("generate_link error -> Auth tidak dihapus & mailer tidak dipanggil",
              supabase.auth.admin.deleted_users == [] and mail_calls == [])
        check("generate_link error -> email mentah tidak bocor", not resend_email_leaked(logs))

        # hashed_token kosong -> resend_failed
        app, supabase, logs = build_resend()
        supabase.auth.admin.hashed_token = ""
        res = invoke_resend(app)
        check("hashed_token kosong -> error=resend_failed",
              "error=resend_failed" in location(res), location(res))
        check("hashed_token kosong -> mailer tidak dipanggil", mail_calls == [])


# ===========================================================================
# D. POST /admin/users/cancel-invite  (dari test_invite_cancel.py)
# ===========================================================================
def test_guards_and_non_pending():
    # Non-admin 403
    app, supabase, _logs = build_cancel()
    staff = make_staff_user()
    raised = None
    try:
        invoke_cancel(app, user=staff)
    except HTTPException as exc:
        raised = exc
    check("non-admin -> HTTPException 403", raised is not None and raised.status_code == 403)
    check("non-admin -> delete_user tidak dipanggil", supabase.auth.admin.deleted_users == [])

    # Cancel diri sendiri
    app, supabase, logs = build_cancel()
    res = invoke_cancel(app, target_uid=ADMIN["id"])
    check("self cancel -> error=cannot_delete_self", "error=cannot_delete_self" in location(res))
    check("self cancel -> delete_user tidak dipanggil", supabase.auth.admin.deleted_users == [])

    # Target tidak ditemukan
    app, supabase, logs = build_cancel(profile_rows=[])
    res = invoke_cancel(app)
    check("target tidak ada -> error=user_not_found", "error=user_not_found" in location(res))
    check("target tidak ada -> outcome rejected", last_log(logs)[1]["outcome"] == "rejected")

    # Target protected
    app, supabase, logs = build_cancel(profile_rows=[default_cancel_pending_row(is_protected=True)])
    res = invoke_cancel(app)
    check("target protected -> error=protected_account", "error=protected_account" in location(res))
    check("target protected -> delete_user tidak dipanggil", supabase.auth.admin.deleted_users == [])

    # Target non-pending (active) -> DITOLAK tanpa hapus Auth/profiles
    app, supabase, logs = build_cancel(profile_rows=[default_cancel_pending_row(status="active")])
    res = invoke_cancel(app)
    check("target active -> error=not_pending", "error=not_pending" in location(res), location(res))
    check("target active -> delete_user TIDAK dipanggil", supabase.auth.admin.deleted_users == [])
    check("target active -> profiles.delete TIDAK dipanggil", supabase.profile_deletes == [])
    check("target active -> profil tetap utuh", len(supabase.profile_rows) == 1)
    check("target active -> email mentah tidak bocor", not cancel_email_leaked(logs))


def test_happy_path_cascade():
    app, supabase, logs = build_cancel()
    res = invoke_cancel(app)
    check("happy -> status=cancel_success", "status=cancel_success" in location(res), location(res))
    check("happy -> delete_user dipanggil 1x", supabase.auth.admin.deleted_users == [CANCEL_TARGET_UID])
    check("happy -> profil terhapus via cascade (tanpa fallback profiles.delete)",
          supabase.profile_rows == [] and supabase.profile_deletes == [])
    args, kwargs = last_log(logs)
    check("happy -> action cancel_invite", args[1] == "cancel_invite")
    check("happy -> outcome success", kwargs["outcome"] == "success")
    check("happy -> email mentah tidak bocor", not cancel_email_leaked(logs))


def test_auth_delete_failure_and_partial_failures():
    # Auth delete_user gagal -> cancel_failed, profil tetap ada
    app, supabase, logs = build_cancel()
    supabase.auth.admin.delete_error = RuntimeError("auth delete error")
    res = invoke_cancel(app)
    check("delete_user gagal -> error=cancel_failed", "error=cancel_failed" in location(res))
    check("delete_user gagal -> profiles.delete TIDAK dipanggil", supabase.profile_deletes == [])
    check("delete_user gagal -> profil masih ada", len(supabase.profile_rows) == 1)
    check("delete_user gagal -> outcome failed", last_log(logs)[1]["outcome"] == "failed")
    check("delete_user gagal -> email mentah tidak bocor", not cancel_email_leaked(logs))

    # Cascade tidak jalan, fallback delete pending sukses -> cancel_success
    app, supabase, logs = build_cancel()
    supabase.auth.admin.cascade_delete = False
    res = invoke_cancel(app)
    check("cascade tidak jalan + fallback sukses -> status=cancel_success",
          "status=cancel_success" in location(res), location(res))
    check("cascade tidak jalan -> fallback delete bersyarat status=pending",
          len(supabase.profile_deletes) == 1
          and ("status", "pending") in supabase.profile_deletes[0][1])
    check("cascade tidak jalan -> profil akhirnya terhapus", supabase.profile_rows == [])
    check("cascade tidak jalan -> outcome success", last_log(logs)[1]["outcome"] == "success")

    # Cascade tidak jalan + fallback delete gagal -> cancel_partial
    app, supabase, logs = build_cancel(profile_delete_error=RuntimeError("db delete fail"))
    supabase.auth.admin.cascade_delete = False
    res = invoke_cancel(app)
    check("fallback delete gagal -> error=cancel_partial",
          "error=cancel_partial" in location(res), location(res))
    check("fallback delete gagal -> outcome failed", last_log(logs)[1]["outcome"] == "failed")
    check("fallback delete gagal -> email mentah tidak bocor", not cancel_email_leaked(logs))

    # Verifikasi pasca-delete query error -> cancel_partial
    app, supabase, logs = build_cancel(verify_select_error=RuntimeError("verify fail"))
    res = invoke_cancel(app)
    check("verifikasi cascade gagal -> error=cancel_partial",
          "error=cancel_partial" in location(res), location(res))
    check("verifikasi cascade gagal -> outcome failed", last_log(logs)[1]["outcome"] == "failed")

    # DB error saat baca profil awal -> cancel_failed, tanpa delete_user
    app, supabase, logs = build_cancel(initial_select_error=RuntimeError("db down"))
    res = invoke_cancel(app)
    check("initial select gagal -> error=cancel_failed", "error=cancel_failed" in location(res))
    check("initial select gagal -> delete_user TIDAK dipanggil",
          supabase.auth.admin.deleted_users == [])


# ---------------------------------------------------------------------------
ALL_TESTS = (
    # A. invite endpoint (15)
    test_pure_helpers,
    test_non_admin_forbidden,
    test_app_base_url_empty_blocks,
    test_invalid_email_rejected,
    test_invite_happy_path,
    test_never_sets_password,
    test_mailer_statuses,
    test_mailer_exception_maps_to_failed,
    test_username_retry_without_regenerating_link,
    test_username_retry_exhausted_fails,
    test_profiles_pkey_maps_to_email_exists,
    test_compensation_deletes_proven_new_user,
    test_compensation_keeps_orphan_when_not_proven_new,
    test_compensation_keeps_when_profile_row_exists,
    test_missing_hashed_token_runs_compensation,
    # B. dedupe (8)
    test_dedupe_auth_email_exists,
    test_dedupe_invited_email_pending_case_insensitive,
    test_dedupe_pending_query_error_fail_closed,
    test_dedupe_race_pending_email_constraint,
    test_dedupe_generate_link_already_registered,
    test_dedupe_rpc_auth_email_exists_error_fail_closed,
    test_dedupe_next_invite_username_empty_and_error,
    test_dedupe_invalid_email_rejected,
    # C. resend (7)
    test_cooldown_helper,
    test_non_admin_and_config_guard,
    test_target_profile_guards,
    test_cooldown_blocks_too_soon,
    test_auth_confirmed_rejected_and_errors,
    test_resend_happy_path,
    test_mailer_statuses_and_link_failures,
    # D. cancel (3)
    test_guards_and_non_pending,
    test_happy_path_cascade,
    test_auth_delete_failure_and_partial_failures,
)


def main(reverse: bool = False) -> int:
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
    print("OK: semua pemeriksaan invite admin (invite/dedupe/resend/cancel) lolos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
