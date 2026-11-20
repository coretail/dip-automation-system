"""Pure-local tests untuk POST /admin/users/cancel-invite (Task 3b).

Mock Supabase. Tidak ada jaringan, tidak ada secret, tidak membaca `.env`.

Kontrak yang dikunci:
  1. Non-admin -> HTTPException 403.
  2. Cancel diri sendiri -> error=cannot_delete_self, delete_user tidak dipanggil.
  3. Target tidak ditemukan -> error=user_not_found.
  4. Target is_protected -> error=protected_account, delete_user tidak dipanggil.
  5. Target non-pending (status='active') -> error=not_pending; Auth & profiles tidak dihapus.
  6. Happy path cascade normal: delete_user dipanggil 1x, profiles terhapus via cascade
     tanpa fallback profiles.delete(), status=cancel_success, action='cancel_invite'.
  7. delete_user gagal -> error=cancel_failed, profiles tidak disentuh, outcome=failed.
  8. Kegagalan parsial:
     - Cascade tidak berjalan, fallback conditional delete (status='pending') sukses -> cancel_success.
     - Cascade tidak berjalan, fallback delete gagal -> error=cancel_partial, outcome=failed.
     - Verifikasi pasca-delete error -> error=cancel_partial, outcome=failed.
  9. DB error saat baca profil -> error=cancel_failed, delete_user tidak dipanggil.
 10. Email mentah tidak pernah bocor ke log_activity.

Dijalankan: python tests/test_invite_cancel.py
"""
import asyncio
import os
import sys
from types import SimpleNamespace

from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

from app.admin_users_routes import register_admin_users_routes  # noqa: E402
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
TARGET_UID = "pending-uid-2"
TARGET_EMAIL = "Calon.User@Example.com"


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
        self._is_delete = False
        self._eqs = []

    def select(self, *cols):
        return self

    def delete(self):
        self._is_delete = True
        return self

    def eq(self, key, value):
        self._eqs.append((key, value))
        return self

    def execute(self):
        if self._is_delete:
            self.fake.profile_deletes.append((self.name, list(self._eqs)))
            if self.fake.profile_delete_error is not None:
                raise self.fake.profile_delete_error
            self.fake.profile_rows = [
                r for r in self.fake.profile_rows
                if not all(r.get(k) == v for k, v in self._eqs)
            ]
            return SimpleNamespace(data=[], error=None)

        self.fake.select_calls += 1
        if self.fake.select_calls == 1 and self.fake.initial_select_error is not None:
            raise self.fake.initial_select_error
        if self.fake.select_calls >= 2 and self.fake.verify_select_error is not None:
            raise self.fake.verify_select_error

        rows = list(self.fake.profile_rows)
        for key, value in self._eqs:
            rows = [r for r in rows if r.get(key) == value]
        return SimpleNamespace(data=rows, error=None)


class FakeAuthAdmin:
    def __init__(self, fake):
        self.fake = fake
        self.deleted_users = []
        self.delete_error = None
        self.cascade_delete = True

    def delete_user(self, uid):
        self.deleted_users.append(uid)
        if self.delete_error is not None:
            raise self.delete_error
        if self.cascade_delete:
            self.fake.profile_rows = [r for r in self.fake.profile_rows if r.get("id") != uid]


class FakeAuth:
    def __init__(self, fake):
        self.admin = FakeAuthAdmin(fake)


class FakeSupabase:
    def __init__(self, **opts):
        self.auth = FakeAuth(self)
        self.profile_rows = list(opts.get("profile_rows", []))
        self.profile_deletes = []
        self.select_calls = 0
        self.initial_select_error = opts.get("initial_select_error")
        self.verify_select_error = opts.get("verify_select_error")
        self.profile_delete_error = opts.get("profile_delete_error")

    def table(self, name):
        return FakeTable(name, self)


def default_pending_row(**overrides):
    row = {
        "id": TARGET_UID,
        "full_name": "user-9",
        "role": "staff",
        "status": "pending",
        "invited_email": TARGET_EMAIL.lower(),
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


def invoke(app, target_uid=TARGET_UID, user=None):
    endpoint = app.routes[("POST", "/admin/users/cancel-invite")]
    actor = dict(ADMIN) if user is None else dict(user)
    return asyncio.run(endpoint(SimpleNamespace(), target_uid=target_uid, current_user=actor))


def location(result):
    return result.headers.get("location", "")


def last_log(logs):
    return logs[-1] if logs else ((), {})


def raw_email_in_logs(logs, raw_email=TARGET_EMAIL) -> bool:
    needle = raw_email.strip().lower()
    return any(needle in repr((args, kwargs)).lower() for args, kwargs in logs)


def test_guards_and_non_pending():
    # Non-admin 403
    app, supabase, _logs = build()
    staff = {"id": "staff-1", "email": "staff@example.test", "full_name": "staff",
             "role": "staff", "perusahaan": None}
    raised = None
    try:
        invoke(app, user=staff)
    except HTTPException as exc:
        raised = exc
    check("non-admin -> HTTPException 403", raised is not None and raised.status_code == 403)
    check("non-admin -> delete_user tidak dipanggil", supabase.auth.admin.deleted_users == [])

    # Cancel diri sendiri
    app, supabase, logs = build()
    res = invoke(app, target_uid=ADMIN["id"])
    check("self cancel -> error=cannot_delete_self", "error=cannot_delete_self" in location(res))
    check("self cancel -> delete_user tidak dipanggil", supabase.auth.admin.deleted_users == [])

    # Target tidak ditemukan
    app, supabase, logs = build(profile_rows=[])
    res = invoke(app)
    check("target tidak ada -> error=user_not_found", "error=user_not_found" in location(res))
    check("target tidak ada -> outcome rejected", last_log(logs)[1]["outcome"] == "rejected")

    # Target protected
    app, supabase, logs = build(profile_rows=[default_pending_row(is_protected=True)])
    res = invoke(app)
    check("target protected -> error=protected_account", "error=protected_account" in location(res))
    check("target protected -> delete_user tidak dipanggil", supabase.auth.admin.deleted_users == [])

    # Target non-pending (active) -> DITOLAK tanpa hapus Auth/profiles
    app, supabase, logs = build(profile_rows=[default_pending_row(status="active")])
    res = invoke(app)
    check("target active -> error=not_pending", "error=not_pending" in location(res), location(res))
    check("target active -> delete_user TIDAK dipanggil", supabase.auth.admin.deleted_users == [])
    check("target active -> profiles.delete TIDAK dipanggil", supabase.profile_deletes == [])
    check("target active -> profil tetap utuh", len(supabase.profile_rows) == 1)
    check("target active -> email mentah tidak bocor", not raw_email_in_logs(logs))


def test_happy_path_cascade():
    app, supabase, logs = build()
    res = invoke(app)
    check("happy -> status=cancel_success", "status=cancel_success" in location(res), location(res))
    check("happy -> delete_user dipanggil 1x", supabase.auth.admin.deleted_users == [TARGET_UID])
    check("happy -> profil terhapus via cascade (tanpa fallback profiles.delete)",
          supabase.profile_rows == [] and supabase.profile_deletes == [])
    args, kwargs = last_log(logs)
    check("happy -> action cancel_invite", args[1] == "cancel_invite")
    check("happy -> outcome success", kwargs["outcome"] == "success")
    check("happy -> email mentah tidak bocor", not raw_email_in_logs(logs))


def test_auth_delete_failure_and_partial_failures():
    # Auth delete_user gagal -> cancel_failed, profil tetap ada
    app, supabase, logs = build()
    supabase.auth.admin.delete_error = RuntimeError("auth delete error")
    res = invoke(app)
    check("delete_user gagal -> error=cancel_failed", "error=cancel_failed" in location(res))
    check("delete_user gagal -> profiles.delete TIDAK dipanggil", supabase.profile_deletes == [])
    check("delete_user gagal -> profil masih ada", len(supabase.profile_rows) == 1)
    check("delete_user gagal -> outcome failed", last_log(logs)[1]["outcome"] == "failed")
    check("delete_user gagal -> email mentah tidak bocor", not raw_email_in_logs(logs))

    # Cascade tidak jalan, fallback delete pending sukses -> cancel_success
    app, supabase, logs = build()
    supabase.auth.admin.cascade_delete = False
    res = invoke(app)
    check("cascade tidak jalan + fallback sukses -> status=cancel_success",
          "status=cancel_success" in location(res), location(res))
    check("cascade tidak jalan -> fallback delete bersyarat status=pending",
          len(supabase.profile_deletes) == 1
          and ("status", "pending") in supabase.profile_deletes[0][1])
    check("cascade tidak jalan -> profil akhirnya terhapus", supabase.profile_rows == [])
    check("cascade tidak jalan -> outcome success", last_log(logs)[1]["outcome"] == "success")

    # Cascade tidak jalan + fallback delete gagal -> cancel_partial
    app, supabase, logs = build(profile_delete_error=RuntimeError("db delete fail"))
    supabase.auth.admin.cascade_delete = False
    res = invoke(app)
    check("fallback delete gagal -> error=cancel_partial",
          "error=cancel_partial" in location(res), location(res))
    check("fallback delete gagal -> outcome failed", last_log(logs)[1]["outcome"] == "failed")
    check("fallback delete gagal -> email mentah tidak bocor", not raw_email_in_logs(logs))

    # Verifikasi pasca-delete query error -> cancel_partial
    app, supabase, logs = build(verify_select_error=RuntimeError("verify fail"))
    res = invoke(app)
    check("verifikasi cascade gagal -> error=cancel_partial",
          "error=cancel_partial" in location(res), location(res))
    check("verifikasi cascade gagal -> outcome failed", last_log(logs)[1]["outcome"] == "failed")

    # DB error saat baca profil awal -> cancel_failed, tanpa delete_user
    app, supabase, logs = build(initial_select_error=RuntimeError("db down"))
    res = invoke(app)
    check("initial select gagal -> error=cancel_failed", "error=cancel_failed" in location(res))
    check("initial select gagal -> delete_user TIDAK dipanggil",
          supabase.auth.admin.deleted_users == [])


def main():
    test_guards_and_non_pending()
    test_happy_path_cascade()
    test_auth_delete_failure_and_partial_failures()

    print()
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} pemeriksaan")
        for name in FAILURES:
            print(f"  - {name}")
        sys.exit(1)
    print("OK: semua pemeriksaan cancel invite lolos")


if __name__ == "__main__":
    main()
