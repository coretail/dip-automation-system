"""Pure-local tests untuk dedupe di POST /admin/users/invite (Task 3).

Mock Supabase + mock mailer. Tidak ada jaringan, tidak ada secret.

Kontrak yang dikunci:
  1. auth_email_exists True              -> error=email_exists
  2. profiles.invited_email pending      -> error=email_exists (case-insensitive)
  3. race idx_profiles_invited_email_pending_unique -> email_exists, Auth tidak dihapus
  4. generate_link "already registered"  -> error=email_exists
  5. RPC auth_email_exists gagal         -> fail-closed error=invite_failed
  6. next_invite_username kosong/gagal   -> error=invite_failed
  7. Email tidak valid                   -> error=invalid_email

Dijalankan: python tests/test_invite_dedupe.py
"""
import asyncio
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

import app.admin_users_routes as aur  # noqa: E402
from app.admin_users_routes import register_admin_users_routes  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FAILURES = []
ADMIN = {"id": "admin-1", "email": "admin@example.test", "full_name": "admin",
         "role": "admin", "perusahaan": None}
MAIL_CALLS = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


class FakeApp:
    def __init__(self):
        self.routes = {}

    def post(self, path, **kwargs):
        def decorator(fn):
            self.routes[("POST", path)] = fn
            return fn
        return decorator

    def get(self, path, **kwargs):
        def decorator(fn):
            self.routes[("GET", path)] = fn
            return fn
        return decorator


class FakeLimiter:
    def limit(self, _spec):
        def decorator(fn):
            return fn
        return decorator


class FakeRpc:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return SimpleNamespace(data=self._data, error=None)


class FakeTable:
    def __init__(self, name, fake):
        self.name = name
        self.fake = fake
        self._insert = None
        self._eq = None

    def select(self, *cols):
        return self

    def eq(self, key, value):
        self._eq = (key, value)
        return self

    def insert(self, payload):
        self._insert = payload
        return self

    def execute(self):
        if self._insert is not None:
            self.fake.inserts.append((self.name, self._insert))
            if self.fake.insert_errors:
                raise self.fake.insert_errors.pop(0)
            return SimpleNamespace(data=[self._insert], error=None)
        if self._eq and self._eq[0] == "status":
            return SimpleNamespace(data=list(self.fake.pending_rows), error=None)
        if self._eq and self._eq[0] == "id":
            return SimpleNamespace(
                data=[r for r in self.fake.profile_rows if r.get("id") == self._eq[1]],
                error=None,
            )
        return SimpleNamespace(data=list(self.fake.profile_rows), error=None)


class FakeAuthAdmin:
    def __init__(self, fake):
        self.fake = fake
        self.generate_link_calls = []
        self.deleted_users = []
        self.updated_users = []
        self.generate_link_error = None
        self.new_uid = "new-uid-123"
        self.created_at = "2026-11-20T00:00:00+00:00"
        self.hashed_token = "hashed-token-abc"

    def generate_link(self, params):
        self.generate_link_calls.append(params)
        if self.generate_link_error is not None:
            raise self.generate_link_error
        return SimpleNamespace(
            user=SimpleNamespace(id=self.new_uid, created_at=self.created_at),
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
        self.auth = FakeAuth(self)
        self.inserts = []
        self.rpc_calls = []
        self.rpc_results = dict(opts.get("rpc_results", {}))
        self.pending_rows = list(opts.get("pending_rows", []))
        self.profile_rows = list(opts.get("profile_rows", []))
        self.insert_errors = list(opts.get("insert_errors", []))

    def table(self, name):
        return FakeTable(name, self)

    def rpc(self, name, params=None):
        self.rpc_calls.append((name, params))
        if name in self.rpc_results:
            result = self.rpc_results[name]
            if isinstance(result, Exception):
                raise result
            return FakeRpc(result)
        if name == "next_invite_username":
            return FakeRpc("user-1")
        if name == "auth_email_exists":
            return FakeRpc(False)
        return FakeRpc(None)


def build(**opts):
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
        lambda email: email,
        lambda uid: f"User {uid}",
        lambda uid: ("staff", f"User {uid}"),
        lambda: 0,
        None,
        FakeLimiter(),
    )
    return app, supabase, logs


def invoke(app, email="new.user@example.com"):
    endpoint = app.routes[("POST", "/admin/users/invite")]
    return asyncio.run(endpoint(SimpleNamespace(), email=email, current_user=dict(ADMIN)))


def location(result):
    return result.headers.get("location", "")


def last_log(logs):
    return logs[-1] if logs else ((), {})


def main():
    aur.settings = SimpleNamespace(app_base_url="https://app.example.com")

    async def fake_send(**kwargs):
        MAIL_CALLS.append(kwargs)
        return (True, "sent")

    aur.mailer.send_invite_email = fake_send

    # 1. auth_email_exists True
    app, supabase, logs = build(rpc_results={"auth_email_exists": True})
    res = invoke(app)
    check("auth_email_exists True -> email_exists", "error=email_exists" in location(res), location(res))
    check("auth_email_exists True -> generate_link TIDAK dipanggil",
          supabase.auth.admin.generate_link_calls == [])
    check("auth_email_exists True -> outcome rejected", last_log(logs)[1]["outcome"] == "rejected")

    # 2. profiles.invited_email pending (case-insensitive)
    app, supabase, logs = build(
        rpc_results={"auth_email_exists": False},
        pending_rows=[{"id": "x", "invited_email": "New.User@Example.COM"}],
    )
    res = invoke(app, email="new.user@example.com")
    check("invited_email pending (beda case) -> email_exists",
          "error=email_exists" in location(res), location(res))
    check("invited_email pending -> generate_link TIDAK dipanggil",
          supabase.auth.admin.generate_link_calls == [])

    # 3. race constraint idx_profiles_invited_email_pending_unique
    err = Exception('duplicate key value violates unique constraint '
                    '"idx_profiles_invited_email_pending_unique"')
    app, supabase, logs = build(insert_errors=[err])
    res = invoke(app)
    check("race pending email -> email_exists", "error=email_exists" in location(res), location(res))
    check("race pending email -> TIDAK retry (insert 1x)",
          len([i for i in supabase.inserts if i[0] == "profiles"]) == 1)
    check("race pending email -> Auth TIDAK dihapus",
          supabase.auth.admin.deleted_users == [], str(supabase.auth.admin.deleted_users))

    # 4. generate_link "already registered"
    app, supabase, logs = build()
    supabase.auth.admin.generate_link_error = Exception("A user with this email address has already been registered")
    res = invoke(app)
    check("generate_link already registered -> email_exists",
          "error=email_exists" in location(res), location(res))
    check("generate_link already registered -> outcome rejected",
          last_log(logs)[1]["outcome"] == "rejected")

    # 5. RPC auth_email_exists gagal -> fail-closed
    app, supabase, logs = build(rpc_results={"auth_email_exists": RuntimeError("boom")})
    res = invoke(app)
    check("auth_email_exists gagal -> fail-closed invite_failed",
          "error=invite_failed" in location(res), location(res))
    check("auth_email_exists gagal -> generate_link TIDAK dipanggil",
          supabase.auth.admin.generate_link_calls == [])
    check("auth_email_exists gagal -> outcome failed", last_log(logs)[1]["outcome"] == "failed")

    # 6. next_invite_username kosong
    app, supabase, logs = build(rpc_results={"next_invite_username": ""})
    res = invoke(app)
    check("next_invite_username kosong -> invite_failed",
          "error=invite_failed" in location(res), location(res))
    check("next_invite_username kosong -> generate_link TIDAK dipanggil",
          supabase.auth.admin.generate_link_calls == [])

    # 6b. next_invite_username gagal
    app, supabase, logs = build(rpc_results={"next_invite_username": RuntimeError("boom")})
    res = invoke(app)
    check("next_invite_username gagal -> invite_failed",
          "error=invite_failed" in location(res), location(res))

    # 7. Email tidak valid
    app, supabase, logs = build()
    res = invoke(app, email="bukan-email")
    check("email invalid -> invalid_email", "error=invalid_email" in location(res), location(res))
    check("email invalid -> tidak ada generate_link",
          supabase.auth.admin.generate_link_calls == [])

    print()
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} pemeriksaan")
        for name in FAILURES:
            print(f"  - {name}")
        sys.exit(1)
    print("OK: semua pemeriksaan dedupe invite lolos")


if __name__ == "__main__":
    main()