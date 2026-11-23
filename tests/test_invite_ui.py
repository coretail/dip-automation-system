"""Pure-local tests untuk UI daftar user pending (Task 5).

Menguji:
  1. Query presence exclude user pending (status kolom tersedia).
  2. Query presence fail-soft: kolom status tidak ada -> user tetap tampil.
  3. Query notes/users exclude user pending.
  4. Query notes/users fail-soft: kolom status tidak ada -> user tetap tampil.
  5. Template admin_users.html:
     - User pending render badge "Pending" + email undangan + aksi resend/cancel.
     - User pending TIDAK punya aksi reset password / update role / delete.
     - User active render aksi normal.
     - status_col_present=False -> kolom Email Undangan & filter Pending tidak dirender.
  6. admin_users_routes page: status_col_present diteruskan ke context;
     query legacy -> semua user status='active' (normalisasi).

Semua tanpa jaringan/secret. notes_routes diuji dengan patch sys.modules
untuk menghindari import app.database (yang memicu staging preflight).

Dijalankan: python tests/test_invite_ui.py
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://odtfppboyjlbatajncgj.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")
# Dummy R2 env agar import app.notes_routes (-> app.database) tidak memicu
# staging preflight gagal di lingkungan CI/test tanpa secret.
os.environ.setdefault("R2_ACCOUNT_ID", "ci-dummy")
os.environ.setdefault("R2_ACCESS_KEY_ID", "ci-dummy")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "ci-dummy")
os.environ.setdefault("R2_PUBLIC_BASES", "https://ci.invalid")
os.environ.setdefault("R2_BUCKET_SUFFIX", "-stg")
# DIP_APP_ENV=staging wajib agar app.config memilih _StagingSettings (preflight)
# dan tidak menolak .env produksi lokal (guard G-11).
os.environ.setdefault("DIP_APP_ENV", "staging")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app.presence_routes as presence_mod  # noqa: E402
import app.admin_users_routes as admin_mod  # noqa: E402
import app.notes_routes as notes_mod  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Presence tests
# ---------------------------------------------------------------------------

def _make_presence_supabase(rows, status_col_present):
    """Fake supabase yang merekam select dan berperilaku sesuai status_col_present.

    - status_col_present True: query penuh sukses, mengembalikan rows (dengan status).
    - status_col_present False: query penuh (memuat status + last_seen_at) gagal,
      retry ke query legacy (tanpa status) sukses, mengembalikan rows (tanpa status).
    """
    calls: list[str] = []

    class _Table:
        def select(self, cols):
            calls.append(cols)
            full_query = "status" in cols and "last_seen_at" in cols
            if full_query and not status_col_present:
                return _Raiser()
            return _Exec(rows)

        def order(self, _col):
            return self

    class _Raiser:
        def order(self, _col):
            return self

        def execute(self):
            raise RuntimeError("column does not exist: status")

    class _Exec:
        def __init__(self, data):
            self._data = data

        def order(self, _col):
            return self

        def execute(self):
            return SimpleNamespace(data=self._data)

    class _Supabase:
        def table(self, _name):
            return _Table()

    return _Supabase(), calls


def _test_presence_exclude_pending():
    """User pending harus ter-exclude dari output presence."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    rows = [
        {"id": "u1", "full_name": "admin", "is_online": True, "is_idle": False,
         "is_protected": False, "status": "active", "last_seen_at": "2026-01-01T00:00:00Z"},
        {"id": "u2", "full_name": "staff1", "is_online": False, "is_idle": False,
         "is_protected": False, "status": "pending", "last_seen_at": None},
        {"id": "u3", "full_name": "staff2", "is_online": False, "is_idle": True,
         "is_protected": False, "status": "active", "last_seen_at": "2026-01-01T00:00:00Z"},
    ]
    current_user = {"id": "admin-1", "role": "admin"}

    supabase, calls = _make_presence_supabase(rows, status_col_present=True)

    def compute_user_presence(profile):
        is_online = bool(profile.get("is_online"))
        presence_status = "online" if is_online else ("idle" if profile.get("is_idle") else "offline")
        return {
            "is_online": is_online,
            "is_idle": bool(profile.get("is_idle")),
            "presence_status": presence_status,
            "last_seen_at": profile.get("last_seen_at"),
            "last_seen_label": "-",
            "last_activity_at": profile.get("last_activity_at"),
            "last_activity_label": "-",
        }

    app = FastAPI()
    presence_mod.register_presence_routes(
        app,
        get_current_user=lambda: current_user,
        supabase=supabase,
        templates=SimpleNamespace(),
        log_activity=lambda *a, **k: None,
        get_ed_notification_count=lambda: 0,
        touch_user_presence=lambda uid, online=True, active=True: True,
        compute_user_presence=compute_user_presence,
        compute_status_na=lambda: "NA",
    )
    client = TestClient(app)
    res = client.get("/api/admin/users/presence")
    items = res.json()["items"]
    ids = [i["id"] for i in items]

    check("presence: user pending (u2) ter-exclude", "u2" not in ids, f"ids={ids}")
    check("presence: user active online (u1) hadir", "u1" in ids, f"ids={ids}")
    check("presence: user active idle (u3) hadir", "u3" in ids, f"ids={ids}")
    check("presence: select query memuat kolom status",
          any("status" in c for c in calls), f"calls={calls}")


def _test_presence_fail_soft_no_status():
    """Bila kolom status belum ada (query penuh gagal), user tetap tampil."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    rows = [
        {"id": "u1", "full_name": "admin", "is_online": True, "is_idle": False,
         "is_protected": False, "last_seen_at": "2026-01-01T00:00:00Z"},
        {"id": "u2", "full_name": "staff1", "is_online": False, "is_idle": False,
         "is_protected": False, "last_seen_at": None},
    ]
    current_user = {"id": "admin-1", "role": "admin"}

    supabase, calls = _make_presence_supabase(rows, status_col_present=False)

    def compute_user_presence(profile):
        is_online = bool(profile.get("is_online"))
        presence_status = "online" if is_online else ("idle" if profile.get("is_idle") else "offline")
        return {
            "is_online": is_online,
            "is_idle": bool(profile.get("is_idle")),
            "presence_status": presence_status,
            "last_seen_at": profile.get("last_seen_at"),
            "last_seen_label": "-",
            "last_activity_at": profile.get("last_activity_at"),
            "last_activity_label": "-",
        }

    app = FastAPI()
    presence_mod.register_presence_routes(
        app,
        get_current_user=lambda: current_user,
        supabase=supabase,
        templates=SimpleNamespace(),
        log_activity=lambda *a, **k: None,
        get_ed_notification_count=lambda: 0,
        touch_user_presence=lambda uid, online=True, active=True: True,
        compute_user_presence=compute_user_presence,
        compute_status_na=lambda: "NA",
    )
    client = TestClient(app)
    res = client.get("/api/admin/users/presence")
    items = res.json()["items"]
    ids = [i["id"] for i in items]

    check("presence fail-soft: query penuh gagal -> retry (2 call select)",
          len(calls) == 2, f"calls={calls}")
    check("presence fail-soft: semua user tetap tampil", set(ids) == {"u1", "u2"}, f"ids={ids}")


# ---------------------------------------------------------------------------
# Notes tests (patch sys.modules untuk menghindari import app.database)
# ---------------------------------------------------------------------------

def _make_notes_supabase(rows, status_col_present):
    """Fake supabase untuk notes routes; merekam select call.

    - status_col_present True: query penuh (dengan status) sukses.
    - status_col_present False: query penuh gagal, retry ke query legacy sukses.

    Mengembalikan (supabase_instance, calls). Memanggil patch notes_mod.supabase.
    """
    calls: list[str] = []

    class _Table:
        def select(self, cols):
            calls.append(cols)
            full_query = "status" in cols and "display_name" in cols
            if full_query and not status_col_present:
                return _Raiser()
            return _Exec(rows)

        def order(self, _col):
            return self

    class _Raiser:
        def order(self, _col):
            return self

        def execute(self):
            raise RuntimeError("column does not exist: status")

    class _Exec:
        def __init__(self, data):
            self._data = data

        def order(self, _col):
            return self

        def execute(self):
            return SimpleNamespace(data=self._data)

    class _Supabase:
        def table(self, _name):
            return _Table()

    return _Supabase(), calls


def _test_notes_users_exclude_pending():
    """User pending harus ter-exclude dari /api/notes/users."""
    rows = [
        {"id": "u1", "full_name": "staff_active", "display_name": "SA", "status": "active"},
        {"id": "u2", "full_name": "staff_pending", "display_name": "SP", "status": "pending"},
    ]
    current_user = {"id": "me", "role": "staff"}

    supabase, calls = _make_notes_supabase(rows, status_col_present=True)
    _orig_supabase = notes_mod.supabase
    notes_mod.supabase = supabase
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        notes_mod.register_notes_routes(
            app,
            get_current_user=lambda: current_user,
            get_ed_notification_count=lambda: 0,
            log_activity=lambda *a, **k: None,
        )
        client = TestClient(app)
        res = client.get("/api/notes/users")
        items = res.json()["items"]
        ids = [i["id"] for i in items]
    finally:
        notes_mod.supabase = _orig_supabase

    check("notes/users: user pending (u2) ter-exclude", "u2" not in ids, f"ids={ids}")
    check("notes/users: user active (u1) hadir", "u1" in ids, f"ids={ids}")
    check("notes/users: select query memuat kolom status",
          any("status" in c for c in calls), f"calls={calls}")


def _test_notes_users_fail_soft():
    """Bila kolom status belum ada, user tetap muncul di notes/users."""
    rows = [
        {"id": "u1", "full_name": "staff1", "display_name": "S1"},
        {"id": "u2", "full_name": "staff2", "display_name": "S2"},
    ]
    current_user = {"id": "me", "role": "staff"}

    supabase, calls = _make_notes_supabase(rows, status_col_present=False)
    _orig_supabase = notes_mod.supabase
    notes_mod.supabase = supabase
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        notes_mod.register_notes_routes(
            app,
            get_current_user=lambda: current_user,
            get_ed_notification_count=lambda: 0,
            log_activity=lambda *a, **k: None,
        )
        client = TestClient(app)
        res = client.get("/api/notes/users")
        items = res.json()["items"]
        ids = [i["id"] for i in items]
    finally:
        notes_mod.supabase = _orig_supabase

    check("notes/users fail-soft: semua user tampil walau status belum ada",
          set(ids) == {"u1", "u2"}, f"ids={ids}")
    check("notes/users fail-soft: retry select (2 call)", len(calls) >= 2, f"calls={calls}")


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

def _make_req():
    """Fake request minimal untuk render admin_users.html (extends base.html).

    base.html/_sidebar.html butuh request.url.path; _sidebar juga memakai
    request.cookies, request.headers, dst. Kita sediakan objek yang cukup.
    """
    from types import SimpleNamespace

    class _QP:
        def get(self, k, default=None):
            return None

    class _URL:
        path = "/admin/users"

    class _Req:
        query_params = _QP()
        url = _URL()
        cookies = {}
        headers = {}
        method = "GET"

    return _Req()


def _test_template_pending_rendering():
    """Template admin_users.html: user pending render badge pending + aksi resend/cancel."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader("app/templates"))
    tpl = env.get_template("admin_users.html")

    pending_user = {
        "id": "p1",
        "full_name": "user-1",
        "display_name": "user-1",
        "role": "staff",
        "status": "pending",
        "invited_email": "calon@example.test",
        "invited_at": "2026-01-01T00:00:00",
        "is_online": False,
        "is_idle": False,
        "presence_status": "offline",
        "last_seen_label": "-",
        "last_activity_label": "-",
        "last_seen_at": None,
        "last_activity_at": None,
    }
    active_user = {
        "id": "a1",
        "full_name": "staff_active",
        "display_name": "SA",
        "role": "staff",
        "status": "active",
        "is_online": True,
        "is_idle": False,
        "presence_status": "online",
        "last_seen_label": "x",
        "last_activity_label": "x",
        "last_seen_at": "2026-01-01",
        "last_activity_at": "2026-01-01",
    }
    admin_user = {"id": "admin-1", "role": "admin", "full_name": "admin"}

    html = tpl.render(
        request=_make_req(),
        user=admin_user,
        current_user=admin_user,
        users=[pending_user, active_user],
        online_count=1,
        idle_count=0,
        offline_count=0,
        status_col_present=True,
    )

    check("template: badge 'Pending' muncul", "Pending" in html)
    check("template: email undangan ditampilkan untuk pending",
          "calon@example.test" in html)
    check("template: form resend-invite untuk user pending",
          "/admin/users/resend-invite" in html)
    check("template: form cancel-invite untuk user pending",
          "/admin/users/cancel-invite" in html)
    check("template: petunjuk pemulihan 'Batalkan & undang ulang'",
          "Batalkan &amp; undang ulang" in html or "Batalkan & undang ulang" in html)
    check("template: form resend hanya untuk user pending (1x)",
          html.count("/admin/users/resend-invite") == 1,
          f"count={html.count('/admin/users/resend-invite')}")
    check("template: form cancel hanya untuk user pending (1x)",
          html.count("/admin/users/cancel-invite") == 1,
          f"count={html.count('/admin/users/cancel-invite')}")
    check("template: aksi reset password hanya untuk user active (1 onclick usage)",
          html.count("onclick='openResetModal(") == 1,
          f"count={html.count('onclick=' + chr(39) + 'openResetModal(')} (tanpa def)")


def _test_template_legacy_no_status():
    """status_col_present=False: kolom Email Undangan & filter Pending tidak dirender."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader("app/templates"))
    tpl = env.get_template("admin_users.html")

    user = {
        "id": "a1",
        "full_name": "staff_active",
        "display_name": "SA",
        "role": "staff",
        "status": "active",
        "is_online": True,
        "is_idle": False,
        "presence_status": "online",
        "last_seen_label": "x",
        "last_activity_label": "x",
        "last_seen_at": "2026-01-01",
        "last_activity_at": "2026-01-01",
    }
    admin_user = {"id": "admin-1", "role": "admin", "full_name": "admin"}

    html = tpl.render(
        request=_make_req(),
        user=admin_user,
        current_user=admin_user,
        users=[user],
        online_count=1,
        idle_count=0,
        offline_count=0,
        status_col_present=False,
    )

    check("template legacy: kolom header 'Email Undangan' tidak dirender",
          "<th" not in html or ">Email Undangan</th>" not in html)
    check("template legacy: form 'Undang via Email' tetap ada (selalu)",
          "Undang via Email" in html)
    check("template legacy: filter 'Pending' tidak dirender",
          'data-filter="pending"' not in html)
    check("template legacy: aksi resend tidak ada",
          "/admin/users/resend-invite" not in html)


def _test_admin_page_fail_soft_normalizes_status():
    """admin_users_routes page: bila query penuh gagal, user dinormalisasi
    status='active' dan status_col_present=False di context."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    legacy_rows = [
        {"id": "u1", "full_name": "admin", "display_name": "admin", "role": "admin",
         "perusahaan": None, "is_protected": False, "avatar_path": None,
         "avatar_updated_at": None, "is_online": False, "last_seen_at": None,
         "last_activity_at": None, "updated_at": "2026-01-01"},
    ]

    calls: list[str] = []

    class _Table:
        def select(self, cols):
            calls.append(cols)
            full_query = "status" in cols and "last_seen_at" in cols
            if full_query:
                # Query penuh gagal (status belum ada di schema lama).
                return _Raiser()
            return _Exec(legacy_rows)

        def order(self, _col):
            return self

    class _Raiser:
        def order(self, _col):
            return self

        def execute(self):
            raise RuntimeError("column does not exist: status")

    class _Exec:
        def __init__(self, data):
            self._data = data

        def order(self, _col):
            return self

        def execute(self):
            return SimpleNamespace(data=self._data)

    class _Supabase:
        def table(self, _name):
            return _Table()

    def compute_user_presence(profile):
        is_online = bool(profile.get("is_online"))
        return {
            "is_online": is_online,
            "is_idle": False,
            "presence_status": "online" if is_online else "offline",
            "last_seen_at": profile.get("last_seen_at"),
            "last_seen_label": "-",
            "last_activity_at": profile.get("last_activity_at"),
            "last_activity_label": "-",
        }

    from fastapi.responses import HTMLResponse

    class _Templates:
        def __init__(self):
            self.last_context = None

        def TemplateResponse(self, request, name, context=None, **kw):
            self.last_context = context
            status_code = kw.get("status_code", 200)
            return HTMLResponse(content="<html></html>", status_code=status_code)

    class _Limiter:
        def limit(self, _spec):
            def decorator(fn):
                return fn
            return decorator

    templates = _Templates()
    app = FastAPI()
    app.user = {"id": "admin-1", "role": "admin"}
    admin_mod.register_admin_users_routes(
        app,
        get_current_user=lambda: app.user,
        supabase=_Supabase(),
        templates=templates,
        log_activity=lambda *a, **k: None,
        compute_user_presence=compute_user_presence,
        mask_email=lambda e: ((e or "")[:3] + "***") if e else "",
        _user_label=lambda uid: "x",
        _user_role_and_label=lambda uid: ("staff", "x"),
        get_ed_notification_count=lambda: 0,
        compute_status_na=lambda: "NA",
        limiter=_Limiter(),
    )
    client = TestClient(app)
    client.get("/admin/users")

    ctx = templates.last_context
    users = ctx["users"]
    check("admin page fail-soft: status_col_present False di context",
          ctx.get("status_col_present") is False, f"val={ctx.get('status_col_present')}")
    check("admin page fail-soft: user dinormalisasi status='active'",
          all(u.get("status") == "active" for u in users),
          f"statuses={[u.get('status') for u in users]}")
    check("admin page fail-soft: flag _status_unavailable diset",
          all(u.get("_status_unavailable") for u in users),
          f"flags={[u.get('_status_unavailable') for u in users]}")


def main():
    _test_presence_exclude_pending()
    _test_presence_fail_soft_no_status()
    _test_notes_users_exclude_pending()
    _test_notes_users_fail_soft()
    _test_template_pending_rendering()
    _test_template_legacy_no_status()
    _test_admin_page_fail_soft_normalizes_status()

    print()
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} test gagal:")
        for f in FAILURES:
            print(f"  - {f}")
        raise SystemExit(1)
    print("OK: semua test UI pending lolos")


if __name__ == "__main__":
    main()
