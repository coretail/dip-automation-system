"""Pure-local tests untuk POST /admin/users/invite (Task 3).

Mock Supabase + mock `app.mailer.send_invite_email`. Tidak ada jaringan, tidak
ada secret, tidak membaca `.env`.

Kontrak yang dikunci:
  1. Guard APP_BASE_URL kosong -> gagal SEBELUM membuat user / mengirim email.
  2. Email tidak valid -> ditolak.
  3. Happy path -> user Auth pending + profiles status='pending' + email terkirim.
  4. Endpoint TIDAK PERNAH memanggil update password / update_user_by_id.
  5. Hasil mailer: sent / failed / unknown / skipped -> status redirect benar.
  6. Retry maks 3x HANYA untuk idx_profiles_full_name_lower_unique, dan
     generate_link TIDAK diulang.
  7. profiles_pkey -> email_exists (tanpa retry, tanpa hapus Auth).
  8. Kompensasi hapus Auth hanya bila user terbukti baru; bila tidak -> yatim.

Dijalankan: python tests/test_invite_endpoint.py
"""
import asyncio
import io
import os
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

import app.admin_users_routes as aur  # noqa: E402
from app.admin_users_routes import (  # noqa: E402
    constraint_name_of,
    is_proven_new_auth_user,
    is_valid_email,
    register_admin_users_routes,
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
MAIL_CALLS = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
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


class FakeRpc:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return SimpleNamespace(data=self._data, error=None)


class FakeTable:
    def __init__(self, name, fake):
        self.name = name
        self.fake = fake
        self._insert_payload = None
        self._eq = None

    def select(self, *cols):
        return self

    def eq(self, key, value):
        self._eq = (key, value)
        return self

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def execute(self):
        if self._insert_payload is not None:
            self.fake.inserts.append((self.name, self._insert_payload))
            if self.fake.insert_errors:
                raise self.fake.insert_errors.pop(0)
            return SimpleNamespace(data=[self._insert_payload], error=None)

        if self.name != "profiles":
            return SimpleNamespace(data=[], error=None)

        if self._eq and self._eq[0] == "status":
            return SimpleNamespace(data=list(self.fake.pending_rows), error=None)
        if self._eq and self._eq[0] == "id":
            uid = self._eq[1]
            return SimpleNamespace(
                data=[r for r in self.fake.profile_rows if r.get("id") == uid], error=None
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
        self.created_at = datetime.now(timezone.utc).isoformat()
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


def build(**opts):
    app = FakeApp()
    supabase = FakeSupabase(**opts)
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
    return app, supabase, logs


def set_app_base_url(value):
    aur.settings = SimpleNamespace(app_base_url=value)


def set_mailer(result):
    async def fake_send(**kwargs):
        MAIL_CALLS.append(kwargs)
        return result
    aur.mailer.send_invite_email = fake_send


def invoke(app, email="new.user@example.com", user=None):
    endpoint = app.routes[("POST", "/admin/users/invite")]
    actor = dict(ADMIN) if user is None else dict(user)
    return asyncio.run(endpoint(SimpleNamespace(), email=email, current_user=actor))


def location(result):
    return result.headers.get("location", "")


def last_log(logs):
    return logs[-1] if logs else ((), {})


def raw_email_in_logs(logs, raw_email: str) -> bool:
    needle = raw_email.strip().lower()
    return any(needle in repr((args, kwargs)).lower() for args, kwargs in logs)


# ---------------------------------------------------------------------------
# Helper murni
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 0. Admin-only guard (403)
# ---------------------------------------------------------------------------
def test_non_admin_forbidden():
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
    check("non-admin -> HTTPException 403",
          raised is not None and raised.status_code == 403,
          repr(raised))
    check("non-admin -> generate_link TIDAK dipanggil",
          supabase.auth.admin.generate_link_calls == [])
    check("non-admin -> mailer TIDAK dipanggil", MAIL_CALLS == [])


# ---------------------------------------------------------------------------
# 1. Guard APP_BASE_URL
# ---------------------------------------------------------------------------
def test_app_base_url_empty_blocks():
    MAIL_CALLS.clear()
    set_app_base_url("   ")
    set_mailer((True, "sent"))
    app, supabase, logs = build()
    result = invoke(app)
    check("APP_BASE_URL kosong -> error=invite_not_configured",
          "error=invite_not_configured" in location(result), location(result))
    check("APP_BASE_URL kosong -> generate_link TIDAK dipanggil",
          supabase.auth.admin.generate_link_calls == [])
    check("APP_BASE_URL kosong -> mailer TIDAK dipanggil", MAIL_CALLS == [])
    check("APP_BASE_URL kosong -> tidak ada insert profiles", supabase.inserts == [])
    check("APP_BASE_URL kosong -> dicatat outcome=failed",
          last_log(logs)[0][1] == "invite" and last_log(logs)[1]["outcome"] == "failed")
    check("APP_BASE_URL kosong -> email mentah tidak masuk log",
          not raw_email_in_logs(logs, "new.user@example.com"))


# ---------------------------------------------------------------------------
# 2. Validasi email
# ---------------------------------------------------------------------------
def test_invalid_email_rejected():
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))
    app, supabase, logs = build()
    result = invoke(app, email="bukan-email")
    check("email invalid -> error=invalid_email",
          "error=invalid_email" in location(result), location(result))
    check("email invalid -> tidak ada user dibuat",
          supabase.auth.admin.generate_link_calls == [] and supabase.inserts == [])
    check("email invalid -> outcome=rejected", last_log(logs)[1]["outcome"] == "rejected")
    check("email invalid -> input mentah tidak masuk log",
          not raw_email_in_logs(logs, "bukan-email"))


# ---------------------------------------------------------------------------
# 3. Happy path
# ---------------------------------------------------------------------------
def test_invite_happy_path():
    MAIL_CALLS.clear()
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))
    app, supabase, logs = build()
    result = invoke(app, email="Budi.Santoso@Example.com")

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

    check("happy -> mailer dipanggil 1x", len(MAIL_CALLS) == 1, str(len(MAIL_CALLS)))
    call = MAIL_CALLS[0]
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


# ---------------------------------------------------------------------------
# 4. Tidak pernah set password
# ---------------------------------------------------------------------------
def test_never_sets_password():
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))
    app, supabase, logs = build()
    invoke(app)
    check("tidak pernah update_user_by_id", supabase.auth.admin.updated_users == [])
    check("tidak pernah auth.update_user", supabase.auth.user_updates == [])
    check("tidak ada field password di payload profil",
          all("password" not in str(p).lower() for _t, p in supabase.inserts))


# ---------------------------------------------------------------------------
# 5. Hasil mailer
# ---------------------------------------------------------------------------
def test_mailer_statuses():
    cases = [
        ((True, "sent"), "status=invite_sent"),
        ((False, "failed"), "status=invite_failed_email"),
        ((False, "unknown"), "status=invite_unknown"),
        ((False, "skipped"), "status=invite_sent"),
    ]
    for result_value, expected in cases:
        MAIL_CALLS.clear()
        set_app_base_url(APP_BASE_URL)
        set_mailer(result_value)
        app, supabase, logs = build()
        res = invoke(app)
        check(f"mailer {result_value} -> {expected}", expected in location(res), location(res))
        check(f"mailer {result_value} -> profil tetap dibuat",
              len([i for i in supabase.inserts if i[0] == "profiles"]) == 1)
        check(f"mailer {result_value} -> Auth tidak dihapus",
              supabase.auth.admin.deleted_users == [])


def test_mailer_exception_maps_to_failed():
    set_app_base_url(APP_BASE_URL)

    async def boom(**_kwargs):
        raise RuntimeError("jaringan mati")

    aur.mailer.send_invite_email = boom
    app, supabase, logs = build()
    res = invoke(app)
    check("mailer exception -> status=invite_failed_email",
          "status=invite_failed_email" in location(res), location(res))
    check("mailer exception -> profil tetap ada",
      len([i for i in supabase.inserts if i[0] == "profiles"]) == 1)


# ---------------------------------------------------------------------------
# 6. Retry username
# ---------------------------------------------------------------------------
def test_username_retry_without_regenerating_link():
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))
    err = Exception('duplicate key value violates unique constraint '
                    '"idx_profiles_full_name_lower_unique"')
    app, supabase, logs = build(insert_errors=[err, err])
    res = invoke(app)

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
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))
    err = Exception('duplicate key value violates unique constraint '
                    '"idx_profiles_full_name_lower_unique"')
    app, supabase, logs = build(insert_errors=[err, err, err])
    res = invoke(app)
    check("retry habis -> error=invite_failed",
          "error=invite_failed" in location(res), location(res))
    check("retry habis -> generate_link 1x",
          len(supabase.auth.admin.generate_link_calls) == 1)
    check("retry habis -> outcome failed", last_log(logs)[1]["outcome"] == "failed")


# ---------------------------------------------------------------------------
# 7. Bentrok PK / email pending
# ---------------------------------------------------------------------------
def test_profiles_pkey_maps_to_email_exists():
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))
    err = Exception('duplicate key value violates unique constraint "profiles_pkey"')
    app, supabase, logs = build(insert_errors=[err])
    res = invoke(app)
    check("profiles_pkey -> error=email_exists",
          "error=email_exists" in location(res), location(res))
    check("profiles_pkey -> TIDAK retry (insert sekali)",
          len([i for i in supabase.inserts if i[0] == "profiles"]) == 1)
    check("profiles_pkey -> Auth TIDAK dihapus",
          supabase.auth.admin.deleted_users == [])
    check("profiles_pkey -> outcome rejected", last_log(logs)[1]["outcome"] == "rejected")


# ---------------------------------------------------------------------------
# 8. Kompensasi
# ---------------------------------------------------------------------------
def test_compensation_deletes_proven_new_user():
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))
    err = Exception('duplicate key value violates unique constraint "some_other_constraint"')
    app, supabase, logs = build(insert_errors=[err])
    buf = io.StringIO()
    with redirect_stdout(buf):
        res = invoke(app)
    check("kompensasi user baru -> error=invite_failed",
          "error=invite_failed" in location(res), location(res))
    check("kompensasi user baru -> Auth DIHAPUS",
          supabase.auth.admin.deleted_users == ["new-uid-123"],
          str(supabase.auth.admin.deleted_users))
    check("kompensasi user baru -> outcome failed", last_log(logs)[1]["outcome"] == "failed")


def test_compensation_keeps_orphan_when_not_proven_new():
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))
    err = Exception('duplicate key value violates unique constraint "some_other_constraint"')
    app, supabase, logs = build(insert_errors=[err])
    # created_at 5 menit lalu -> tidak terbukti baru
    supabase.auth.admin.created_at = (
        datetime.now(timezone.utc) - timedelta(minutes=5)
    ).isoformat()
    buf = io.StringIO()
    with redirect_stdout(buf):
        invoke(app)
    out = buf.getvalue()
    check("kompensasi ragu -> Auth TIDAK dihapus",
          supabase.auth.admin.deleted_users == [], str(supabase.auth.admin.deleted_users))
    check("kompensasi ragu -> log [AKUN AUTH YATIM]", "[AKUN AUTH YATIM]" in out, out[:300])
    check("kompensasi ragu -> outcome failed", last_log(logs)[1]["outcome"] == "failed")


def test_compensation_keeps_when_profile_row_exists():
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))
    err = Exception('duplicate key value violates unique constraint "some_other_constraint"')
    app, supabase, logs = build(
        insert_errors=[err],
        profile_rows=[{"id": "new-uid-123"}],
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        invoke(app)
    check("kompensasi ada profil -> Auth TIDAK dihapus",
          supabase.auth.admin.deleted_users == [], str(supabase.auth.admin.deleted_users))
    check("kompensasi ada profil -> log [AKUN AUTH YATIM]",
          "[AKUN AUTH YATIM]" in buf.getvalue())


def test_missing_hashed_token_runs_compensation():
    set_app_base_url(APP_BASE_URL)
    set_mailer((True, "sent"))

    # Skenario A: uid ada, hashed_token kosong, created_at baru -> hapus Auth
    app, supabase, logs = build()
    supabase.auth.admin.hashed_token = ""
    buf = io.StringIO()
    with redirect_stdout(buf):
        res = invoke(app)
    check("hashed_token kosong (baru) -> error=invite_failed",
          "error=invite_failed" in location(res), location(res))
    check("hashed_token kosong (baru) -> Auth DIHAPUS",
          supabase.auth.admin.deleted_users == ["new-uid-123"],
          str(supabase.auth.admin.deleted_users))
    check("hashed_token kosong (baru) -> email mentah tidak masuk log",
          not raw_email_in_logs(logs, "new.user@example.com"))

    # Skenario B: uid ada, hashed_token kosong, created_at lama -> log [AKUN AUTH YATIM]
    app, supabase, logs = build()
    supabase.auth.admin.hashed_token = ""
    supabase.auth.admin.created_at = (
        datetime.now(timezone.utc) - timedelta(minutes=5)
    ).isoformat()
    buf = io.StringIO()
    with redirect_stdout(buf):
        res = invoke(app)
    check("hashed_token kosong (lama) -> error=invite_failed",
          "error=invite_failed" in location(res), location(res))
    check("hashed_token kosong (lama) -> Auth TIDAK dihapus",
          supabase.auth.admin.deleted_users == [],
          str(supabase.auth.admin.deleted_users))
    check("hashed_token kosong (lama) -> log [AKUN AUTH YATIM]",
          "[AKUN AUTH YATIM]" in buf.getvalue(), buf.getvalue()[:300])
    check("hashed_token kosong (lama) -> email mentah tidak masuk log",
          not raw_email_in_logs(logs, "new.user@example.com"))


# ---------------------------------------------------------------------------
def main():
    test_pure_helpers()
    test_non_admin_forbidden()
    test_app_base_url_empty_blocks()
    test_invalid_email_rejected()
    test_invite_happy_path()
    test_never_sets_password()
    test_mailer_statuses()
    test_mailer_exception_maps_to_failed()
    test_username_retry_without_regenerating_link()
    test_username_retry_exhausted_fails()
    test_profiles_pkey_maps_to_email_exists()
    test_compensation_deletes_proven_new_user()
    test_compensation_keeps_orphan_when_not_proven_new()
    test_compensation_keeps_when_profile_row_exists()
    test_missing_hashed_token_runs_compensation()

    print()
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} pemeriksaan")
        for name in FAILURES:
            print(f"  - {name}")
        sys.exit(1)
    print("OK: semua pemeriksaan invite endpoint lolos")


if __name__ == "__main__":
    main()