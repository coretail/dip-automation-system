"""Pure-local tests untuk POST /admin/users/resend-invite (Task 3a).

Mock Supabase + mock `app.mailer.send_invite_email`. Tidak ada jaringan, tidak
ada secret, tidak membaca `.env`.

Kontrak yang dikunci:
  1. Helper murni `resend_cooldown_remaining` (0/30/59/60/120 dtk, datetime, None, invalid).
  2. Non-admin -> HTTPException 403.
  3. Guard APP_BASE_URL kosong -> error=invite_not_configured sebelum panggil Auth/mailer.
  4. Target tidak ditemukan / non-pending / protected -> ditolak tanpa generate_link.
  5. Jeda < 60 detik dari invited_at -> error=resend_too_soon tanpa get_user_by_id/generate_link.
  6. WAJIB panggil get_user_by_id SEBELUM generate_link; bila email_confirmed_at terisi ->
     error=resend_already_confirmed dan catatan menyebut "Batalkan & undang ulang".
  7. get_user_by_id error / user None -> error=resend_failed.
  8. Happy path: urutan get_user_by_id -> generate_link -> profiles.update -> mailer (is_resend=True),
     tautan memuat token_hash & type=invite, tidak pernah update_user_by_id/auth.update_user.
  9. Status mailer: sent / failed / unknown (tanpa retry) / skipped / exception.
 10. generate_link gagal / hashed_token kosong -> error=resend_failed, Auth tidak dihapus.
 11. Email mentah tidak pernah bocor ke log_activity.

Dijalankan: python tests/test_invite_resend.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

import app.admin_users_routes as aur  # noqa: E402
from app.admin_users_routes import (  # noqa: E402
    register_admin_users_routes,
    resend_cooldown_remaining,
)
from app.mailer import mask_email  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FAILURES = []

ADMIN = {
    "id": "admin-1",
    "email": "admin@example.test",
    "full_name": "admin",
    "role": "admin",
    "perusahaan": None,
}
APP_BASE_URL = "https://app.example.com"
TARGET_UID = "pending-uid-1"
TARGET_EMAIL = "Staff.Baru@Example.com"
MAIL_CALLS = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


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
        self._update_payload = payload
        return self

    def eq(self, key, value):
        self._eqs.append((key, value))
        return self

    def execute(self):
        if self._update_payload is not None:
            self.fake.call_order.append("profiles.update")
            self.fake.updates.append((self.name, list(self._eqs), dict(self._update_payload)))
            if self.fake.update_error is not None:
                raise self.fake.update_error
            return SimpleNamespace(data=[self._update_payload], error=None)

        if self.fake.select_error is not None:
            raise self.fake.select_error

        rows = list(self.fake.profile_rows)
        for key, value in self._eqs:
            rows = [r for r in rows if r.get(key) == value]
        return SimpleNamespace(data=rows, error=None)


class FakeAuthAdmin:
    def __init__(self, fake):
        self.fake = fake
        self.get_user_calls = []
        self.generate_link_calls = []
        self.deleted_users = []
        self.updated_users = []
        self.get_user_error = None
        self.generate_link_error = None
        self.auth_user_missing = False
        self.email_confirmed_at = None
        self.hashed_token = "resend-token-xyz"

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
                email=TARGET_EMAIL.lower(),
                email_confirmed_at=self.email_confirmed_at,
            )
        )

    def generate_link(self, params):
        self.fake.call_order.append("generate_link")
        self.generate_link_calls.append(params)
        if self.generate_link_error is not None:
            raise self.generate_link_error
        return SimpleNamespace(
            user=SimpleNamespace(id=TARGET_UID),
            properties=SimpleNamespace(hashed_token=self.hashed_token),
        )

    def delete_user(self, uid):
        self.deleted_users.append(uid)

    def update_user_by_id(self, uid, payload):
        self.updated_users.append((uid, payload))


class FakeAuth:
    def __init__(self, fake):
        self.admin = FakeAuthAdmin(fake)
        self.user_updates = []

    def update_user(self, payload):
        self.user_updates.append(payload)


class FakeSupabase:
    def __init__(self, **opts):
        self.call_order = []
        self.auth = FakeAuth(self)
        self.updates = []
        self.profile_rows = list(opts.get("profile_rows", []))
        self.select_error = opts.get("select_error")
        self.update_error = opts.get("update_error")

    def table(self, name):
        return FakeTable(name, self)


def default_pending_row(seconds_ago=120, **overrides):
    row = {
        "id": TARGET_UID,
        "full_name": "user-7",
        "status": "pending",
        "invited_email": TARGET_EMAIL.lower(),
        "invited_at": (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat(),
        "is_protected": False,
    }
    row.update(overrides)
    return row


def build(**opts):
    if "profile_rows" not in opts:
        opts["profile_rows"] = [default_pending_row()]
    app = FakeApp()
    supabase = FakeSupabase(**opts)
    logs = []

    async def get_current_user(_request):
        return dict(ADMIN)

    def log_activity(*args, **kwargs):
        logs.append((args, kwargs))

    register_admin_users_routes(
        app, get_current_user, supabase,
        SimpleNamespace(TemplateResponse=lambda **kwargs: kwargs),
        log_activity,
        lambda profile: {"presence_status": "offline"},
        mask_email,
        lambda uid: f"User {uid}",
        lambda uid: ("staff", f"User {uid}"),
        lambda: 0,
        None,
        FakeLimiter(),
    )
    return app, supabase, logs


def set_app_base_url(value):
    aur.settings = SimpleNamespace(app_base_url=value)


def set_mailer(result):
    async def fake_send(**kwargs):
        # Catat ke call_order lewat global jika ada; cek juga argumen is_resend.
        MAIL_CALLS.append(kwargs)
        return result
    aur.mailer.send_invite_email = fake_send


def invoke(app, target_uid=TARGET_UID, user=None):
    endpoint = app.routes[("POST", "/admin/users/resend-invite")]
    actor = dict(ADMIN) if user is None else dict(user)
    return asyncio.run(endpoint(SimpleNamespace(), target_uid=target_uid, current_user=actor))


def location(result):
    return result.headers.get("location", "")


def last_log(logs):
    return logs[-1] if logs else ((), {})


def raw_email_in_logs(logs, raw_email=TARGET_EMAIL) -> bool:
    needle = raw_email.strip().lower()
    return any(needle in repr((args, kwargs)).lower() for args, kwargs in logs)


# ---------------------------------------------------------------------------
# 1. Helper cooldown murni
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 2. Admin-only & APP_BASE_URL guard
# ---------------------------------------------------------------------------
def test_non_admin_and_config_guard():
    MAIL_CALLS.clear()
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))
    app, supabase, _logs = build()
    staff = {"id": "staff-1", "email": "staff@example.test", "full_name": "staff",
             "role": "staff", "perusahaan": None}
    raised = None
    try:
        invoke(app, user=staff)
    except HTTPException as exc:
        raised = exc
    check("non-admin -> HTTPException 403", raised is not None and raised.status_code == 403)
    check("non-admin -> tidak panggil Auth",
          supabase.auth.admin.get_user_calls == [] and supabase.auth.admin.generate_link_calls == [])

    set_app_base_url("  ")
    app, supabase, logs = build()
    res = invoke(app)
    check("APP_BASE_URL kosong -> error=invite_not_configured",
          "error=invite_not_configured" in location(res), location(res))
    check("APP_BASE_URL kosong -> Auth & mailer tidak dipanggil",
          supabase.auth.admin.get_user_calls == []
          and supabase.auth.admin.generate_link_calls == []
          and MAIL_CALLS == [])
    check("APP_BASE_URL kosong -> outcome failed", last_log(logs)[1]["outcome"] == "failed")


# ---------------------------------------------------------------------------
# 3. Validasi target profil (not found / non-pending / protected)
# ---------------------------------------------------------------------------
def test_target_profile_guards():
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))

    app, supabase, logs = build(profile_rows=[])
    res = invoke(app)
    check("target tidak ada -> error=user_not_found", "error=user_not_found" in location(res))
    check("target tidak ada -> outcome rejected", last_log(logs)[1]["outcome"] == "rejected")

    app, supabase, logs = build(profile_rows=[default_pending_row(status="active")])
    res = invoke(app)
    check("target active -> error=not_pending", "error=not_pending" in location(res), location(res))
    check("target active -> Auth tidak dipanggil",
          supabase.auth.admin.get_user_calls == [] and supabase.auth.admin.generate_link_calls == [])
    check("target active -> email mentah tidak bocor", not raw_email_in_logs(logs))

    app, supabase, logs = build(profile_rows=[default_pending_row(is_protected=True)])
    res = invoke(app)
    check("target protected -> error=protected_account",
          "error=protected_account" in location(res), location(res))
    check("target protected -> Auth tidak dipanggil", supabase.auth.admin.generate_link_calls == [])


# ---------------------------------------------------------------------------
# 4. Jeda minimum 60 detik
# ---------------------------------------------------------------------------
def test_cooldown_blocks_too_soon():
    MAIL_CALLS.clear()
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))
    app, supabase, logs = build(profile_rows=[default_pending_row(seconds_ago=30)])
    res = invoke(app)
    check("jeda 30 dtk -> error=resend_too_soon",
          "error=resend_too_soon" in location(res), location(res))
    check("jeda 30 dtk -> get_user_by_id TIDAK dipanggil",
          supabase.auth.admin.get_user_calls == [])
    check("jeda 30 dtk -> generate_link TIDAK dipanggil",
          supabase.auth.admin.generate_link_calls == [])
    check("jeda 30 dtk -> mailer TIDAK dipanggil", MAIL_CALLS == [])
    check("jeda 30 dtk -> outcome rejected", last_log(logs)[1]["outcome"] == "rejected")
    check("jeda 30 dtk -> email mentah tidak bocor", not raw_email_in_logs(logs))


# ---------------------------------------------------------------------------
# 5. Auth get_user_by_id check (confirmed ditolak, error fail-closed)
# ---------------------------------------------------------------------------
def test_auth_confirmed_rejected_and_errors():
    MAIL_CALLS.clear()
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))

    app, supabase, logs = build()
    supabase.auth.admin.email_confirmed_at = "2026-11-20T07:00:00Z"
    res = invoke(app)
    check("confirmed -> error=resend_already_confirmed",
          "error=resend_already_confirmed" in location(res), location(res))
    check("confirmed -> get_user_by_id dipanggil 1x",
          supabase.auth.admin.get_user_calls == [TARGET_UID])
    check("confirmed -> generate_link TIDAK dipanggil",
          supabase.auth.admin.generate_link_calls == [])
    check("confirmed -> mailer TIDAK dipanggil", MAIL_CALLS == [])
    check("confirmed -> catatan menyebut Batalkan & undang ulang",
          "Batalkan & undang ulang" in repr(last_log(logs)[1]["changes"]))
    check("confirmed -> outcome rejected", last_log(logs)[1]["outcome"] == "rejected")
    check("confirmed -> email mentah tidak bocor", not raw_email_in_logs(logs))

    # get_user_by_id exception -> fail-closed
    app, supabase, logs = build()
    supabase.auth.admin.get_user_error = RuntimeError("auth error")
    res = invoke(app)
    check("get_user_by_id error -> error=resend_failed",
          "error=resend_failed" in location(res), location(res))
    check("get_user_by_id error -> generate_link TIDAK dipanggil",
          supabase.auth.admin.generate_link_calls == [])
    check("get_user_by_id error -> outcome failed", last_log(logs)[1]["outcome"] == "failed")
    check("get_user_by_id error -> email mentah tidak bocor", not raw_email_in_logs(logs))

    # auth user None -> fail-closed
    app, supabase, logs = build()
    supabase.auth.admin.auth_user_missing = True
    res = invoke(app)
    check("auth user None -> error=resend_failed",
          "error=resend_failed" in location(res), location(res))
    check("auth user None -> generate_link TIDAK dipanggil",
          supabase.auth.admin.generate_link_calls == [])


# ---------------------------------------------------------------------------
# 6. Happy path: urutan operasi, is_resend=True, update invited_at, tanpa password
# ---------------------------------------------------------------------------
def test_resend_happy_path():
    MAIL_CALLS.clear()
    set_app_base_url(APP_BASE_URL)
    app, supabase, logs = build()

    async def tracked_send(**kwargs):
        supabase.call_order.append("mailer")
        MAIL_CALLS.append(kwargs)
        return (True, "sent")

    aur.mailer.send_invite_email = tracked_send
    res = invoke(app)

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
    check("happy -> mailer is_resend=True", MAIL_CALLS[0].get("is_resend") is True)
    check("happy -> mailer to_email lowercase",
          MAIL_CALLS[0]["to_email"] == TARGET_EMAIL.lower())
    check("happy -> activate_url memuat token_hash & type=invite",
          "token_hash=resend-token-xyz" in MAIL_CALLS[0]["activate_url"]
          and "type=invite" in MAIL_CALLS[0]["activate_url"]
          and "email=" not in MAIL_CALLS[0]["activate_url"])
    check("happy -> tidak pernah update_user_by_id atau auth.update_user",
          supabase.auth.admin.updated_users == [] and supabase.auth.user_updates == [])

    args, kwargs = last_log(logs)
    check("happy -> action resend_invite", args[1] == "resend_invite")
    check("happy -> outcome success", kwargs["outcome"] == "success")
    check("happy -> email mentah tidak bocor", not raw_email_in_logs(logs))


# ---------------------------------------------------------------------------
# 7. Status mailer (sent / failed / unknown / skipped / exception) & gagal link
# ---------------------------------------------------------------------------
def test_mailer_statuses_and_link_failures():
    cases = [
        ((True, "sent"), "status=resend_sent"),
        ((False, "failed"), "status=resend_failed_email"),
        ((False, "unknown"), "status=resend_unknown"),
        ((False, "skipped"), "status=resend_sent"),
    ]
    for result_value, expected in cases:
        MAIL_CALLS.clear()
        set_app_base_url(APP_BASE_URL)
        set_mailer(result_value)
        app, supabase, logs = build()
        res = invoke(app)
        check(f"mailer {result_value} -> {expected}", expected in location(res), location(res))
        check(f"mailer {result_value} -> mailer dipanggil tepat 1x (tanpa auto-retry)",
              len(MAIL_CALLS) == 1, str(len(MAIL_CALLS)))
        check(f"mailer {result_value} -> Auth tidak dihapus",
              supabase.auth.admin.deleted_users == [])
        check(f"mailer {result_value} -> email mentah tidak bocor", not raw_email_in_logs(logs))

    # mailer exception -> resend_failed_email
    MAIL_CALLS.clear()
    set_app_base_url(APP_BASE_URL)

    async def boom(**_kwargs):
        raise RuntimeError("jaringan putus")

    aur.mailer.send_invite_email = boom
    app, supabase, logs = build()
    res = invoke(app)
    check("mailer exception -> status=resend_failed_email",
          "status=resend_failed_email" in location(res), location(res))

    # generate_link gagal -> resend_failed
    MAIL_CALLS.clear()
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))
    app, supabase, logs = build()
    supabase.auth.admin.generate_link_error = RuntimeError("link fail")
    res = invoke(app)
    check("generate_link error -> error=resend_failed",
          "error=resend_failed" in location(res), location(res))
    check("generate_link error -> Auth tidak dihapus & mailer tidak dipanggil",
          supabase.auth.admin.deleted_users == [] and MAIL_CALLS == [])
    check("generate_link error -> email mentah tidak bocor", not raw_email_in_logs(logs))

    # hashed_token kosong -> resend_failed
    app, supabase, logs = build()
    supabase.auth.admin.hashed_token = ""
    res = invoke(app)
    check("hashed_token kosong -> error=resend_failed",
          "error=resend_failed" in location(res), location(res))
    check("hashed_token kosong -> mailer tidak dipanggil", MAIL_CALLS == [])


def main():
    test_cooldown_helper()
    test_non_admin_and_config_guard()
    test_target_profile_guards()
    test_cooldown_blocks_too_soon()
    test_auth_confirmed_rejected_and_errors()
    test_resend_happy_path()
    test_mailer_statuses_and_link_failures()

    print()
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} pemeriksaan")
        for name in FAILURES:
            print(f"  - {name}")
        sys.exit(1)
    print("OK: semua pemeriksaan resend invite lolos")


if __name__ == "__main__":
    main()
