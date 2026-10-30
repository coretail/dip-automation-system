"""Pure-local tests that admin_create_user sets display_name = clean_username[:60].

Uses a mock Supabase client so no network/Supabase connection is needed.
"""
import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

from app.admin_users_routes import register_admin_users_routes  # noqa: E402


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


class FakeAuthResponse:
    def __init__(self, user):
        self.user = user


class FakeAuthAdmin:
    def __init__(self, fake_supabase):
        self._fake_supabase = fake_supabase
        self.created_users = []
        self.updated_users = []

    def create_user(self, payload):
        self.created_users.append(payload)
        return FakeAuthResponse(SimpleNamespace(id="new-uid-123", email=payload["email"]))

    def get_user_by_id(self, _uid):
        return SimpleNamespace(user=SimpleNamespace(email="test@example.test"))

    def update_user_by_id(self, uid, payload):
        self.updated_users.append((uid, payload))


class FakeAuth:
    def __init__(self, fake_supabase):
        self.admin = FakeAuthAdmin(fake_supabase)


class FakeTable:
    def __init__(self, table_name, fake_supabase):
        self.table_name = table_name
        self._fake = fake_supabase
        self._select_data = None
        self._insert_payload = None
        self._update_payload = None
        self._eq_filter = None
        self._delete_filter = None

    def select(self, *cols):
        return self

    def eq(self, key, value):
        self._eq_filter = (key, value)
        return self

    def limit(self, n):
        return self

    def order(self, key, desc=False):
        return self

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def delete(self):
        return self

    def execute(self):
        if self._insert_payload is not None:
            self._fake.inserts.append((self.table_name, self._insert_payload))
            return SimpleNamespace(data=[self._insert_payload], error=None)
        if self._update_payload is not None:
            self._fake.updates.append((self.table_name, self._update_payload, self._eq_filter))
            return SimpleNamespace(data=[self._update_payload], error=None)
        # Default: return select data
        if self.table_name == "profiles":
            return SimpleNamespace(data=self._fake.profiles_data, error=None)
        return SimpleNamespace(data=[], error=None)


class FakeSupabase:
    def __init__(self):
        self.auth = FakeAuth(self)
        self.inserts = []
        self.updates = []
        self.profiles_data = [{"full_name": "existing_user"}]

    def table(self, name):
        return FakeTable(name, self)


def build():
    app = FakeApp()
    supabase = FakeSupabase()
    logs = []

    async def get_current_user(_request):
        return {"id": "admin-1", "email": "admin@example.test", "full_name": "admin", "role": "admin", "perusahaan": None}

    def template_response(**kwargs):
        return kwargs

    def log_activity(*args, **kwargs):
        logs.append((args, kwargs))

    def mask_email(email):
        return email

    def compute_user_presence(profile):
        return {"presence_status": "offline", "is_online": False, "is_idle": False,
                "last_seen_at": None, "last_seen_label": "-", "last_activity_at": None,
                "last_activity_label": "-"}

    def _user_label(uid):
        return f"User {uid}"

    def _user_role_and_label(uid):
        return ("staff", f"User {uid}")

    def get_ed_notification_count():
        return asyncio.coroutine(lambda: 0)() if False else 0

    register_admin_users_routes(
        app, get_current_user, supabase,
        SimpleNamespace(TemplateResponse=template_response),
        log_activity, compute_user_presence, mask_email,
        _user_label, _user_role_and_label,
        get_ed_notification_count,
        None,  # compute_status_na
    )
    return app, supabase, logs


def test_admin_create_user_sets_display_name():
    app, supabase, logs = build()
    endpoint = app.routes[("POST", "/admin/users/create")]
    result = asyncio.run(endpoint(
        SimpleNamespace(),
        email="new@example.com",
        username="budi.santoso",
        password="password123",
        role="staff",
        current_user={"id": "admin-1", "email": "admin@example.com", "full_name": "admin", "role": "admin", "perusahaan": None},
    ))
    # Check the insert payload
    inserts = supabase.inserts
    assert len(inserts) >= 1
    profiles_insert = [i for i in inserts if i[0] == "profiles"]
    assert len(profiles_insert) == 1
    payload = profiles_insert[0][1]
    assert payload["full_name"] == "budi.santoso"
    assert payload["display_name"] == "budi.santoso"
    assert payload["display_name"] == payload["full_name"][:60]
    # Check log_activity was called with success
    assert logs[-1][0][1] == "create"
    assert logs[-1][1]["outcome"] == "success"
    # Check display_name in changes
    changes_str = str(logs[-1][1]["changes"])
    assert "Display Name" in changes_str
    print("[PASS] admin_create_user sets display_name = clean_username[:60]")


def test_admin_create_user_truncates_long_username():
    app, supabase, logs = build()
    endpoint = app.routes[("POST", "/admin/users/create")]
    long_username = "a" * 80
    asyncio.run(endpoint(
        SimpleNamespace(),
        email="long@example.com",
        username=long_username,
        password="password123",
        role="staff",
        current_user={"id": "admin-1", "email": "admin@example.com", "full_name": "admin", "role": "admin", "perusahaan": None},
    ))
    profiles_inserts = [i for i in supabase.inserts if i[0] == "profiles"]
    assert len(profiles_inserts) == 1
    payload = profiles_inserts[0][1]
    # display_name should be truncated to 60 chars
    assert len(payload["display_name"]) == 60
    assert payload["display_name"] == long_username[:60]
    print("[PASS] admin_create_user truncates display_name to 60 characters")


def test_admin_create_user_strips_and_lowercases_username():
    app, supabase, logs = build()
    endpoint = app.routes[("POST", "/admin/users/create")]
    asyncio.run(endpoint(
        SimpleNamespace(),
        email="test@example.com",
        username="  Budi SANTOSO  ",
        password="password123",
        role="staff",
        current_user={"id": "admin-1", "email": "admin@example.com", "full_name": "admin", "role": "admin", "perusahaan": None},
    ))
    profiles_inserts = [i for i in supabase.inserts if i[0] == "profiles"]
    payload = profiles_inserts[0][1]
    assert payload["full_name"] == "budi santoso"
    assert payload["display_name"] == "budi santoso"
    print("[PASS] admin_create_user strips and lowercases for both full_name and display_name")


if __name__ == "__main__":
    test_admin_create_user_sets_display_name()
    test_admin_create_user_truncates_long_username()
    test_admin_create_user_strips_and_lowercases_username()
    print("All admin_create_user display_name tests passed.")
