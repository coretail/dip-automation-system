"""Stub murni bersama untuk unit test pure-local (Task 1 refactor test).

Aturan keras (lihat plan/plan_refactor_test.md, bagian "Kontrak Helper Bersama"):
- Tanpa side effect saat import: tidak mengubah ``os.environ``, ``sys.modules``,
  tidak memanggil ``os.chdir``, tidak meng-import ``app.*``.
- Tanpa state mutable di level modul: setiap kelas/helper dibuat per pemanggilan.

Import dari test: ``from _fakes import ...`` (direktori ``tests/`` otomatis menjadi
``sys.path[0]`` saat ``python tests/<file>.py`` dijalankan).
"""
from __future__ import annotations

from types import SimpleNamespace


class FakeApp:
    """Pengganti FastAPI app: hanya merekam handler route per (METHOD, path)."""

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
    """Pengganti slowapi Limiter: merekam spec ``limit`` per-instance tanpa rate limit."""

    def __init__(self):
        self.calls: list = []

    def limit(self, spec):
        self.calls.append(spec)

        def decorator(fn):
            return fn
        return decorator


class FakeRpc:
    """Pengganti hasil ``supabase.rpc(...)``; ``execute()`` mengembalikan data."""

    def __init__(self, data):
        self._data = data

    def execute(self):
        return SimpleNamespace(data=self._data, error=None)


class FakeRequest:
    """Pengganti minimal FastAPI Request dengan dict per-instance."""

    def __init__(self, headers=None, cookies=None, query_params=None):
        self.headers = dict(headers or {})
        self.cookies = dict(cookies or {})
        self.query_params = dict(query_params or {})


class CheckRunner:
    """Pengumpul hasil ``check`` per-instance (tanpa state global)."""

    def __init__(self):
        self.failures: list[str] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
        if not ok:
            self.failures.append(name)
        return bool(ok)


def make_admin_user(**overrides) -> dict:
    user = {
        "id": "admin-1",
        "email": "admin@example.test",
        "full_name": "admin",
        "role": "admin",
        "perusahaan": None,
    }
    user.update(overrides)
    return user


def make_staff_user(**overrides) -> dict:
    user = {
        "id": "staff-1",
        "email": "staff@example.test",
        "full_name": "staff",
        "role": "staff",
        "perusahaan": None,
    }
    user.update(overrides)
    return user


def redirect_location(result) -> str:
    return result.headers.get("location", "")


def last_activity_log(logs):
    return logs[-1] if logs else ((), {})


def raw_email_in_logs(logs, raw_email: str) -> bool:
    needle = raw_email.strip().lower()
    return any(needle in repr((args, kwargs)).lower() for args, kwargs in logs)
