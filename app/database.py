import os as _os
from threading import Lock

# Preflight env-efektif SEBELUM Settings()/create_client(). Hanya aktif bila
# DIP_APP_ENV=staging. Kontrak eksplisit: environment efektif, bukan file.
if _os.getenv("DIP_APP_ENV", "").strip().lower() == "staging":
    from app.staging_preflight import validate_effective_env as _validate_env

    _validate_env(_os.environ, caller="app.database import")

from supabase import create_client
from app.config import settings
from app.staging_guard import assert_allowed_target

# Guard staging fail-closed di sisi import: gagal startup bila DIP_APP_ENV=staging
# tetapi target bukan project staging. Gagal startup lebih aman daripada
# salah-sasaran ke produksi.
assert_allowed_target("app.database import")

class _LazySupabaseClient:
    """Create the service-role client only when a request actually needs it.

    Importing the FastAPI application is used by static checks and tooling. It
    must not establish a network-capable client before startup/request handling.
    The proxy preserves the existing ``supabase.table(...)`` call sites while
    keeping the existing staging guard immediately before client creation.
    """

    def __init__(self):
        self._client = None
        self._lock = Lock()

    def _get(self):
        if self._client is None:
            with self._lock:
                if self._client is None:
                    assert_allowed_target("app.database client creation")
                    self._client = create_client(
                        settings.supabase_url,
                        settings.supabase_service_role_key,
                    )
        return self._client

    def __getattr__(self, name):
        return getattr(self._get(), name)

    def __repr__(self):
        state = "initialized" if self._client is not None else "lazy"
        return f"<{type(self).__name__} {state}>"


# Service-role client (bypasses RLS) is initialized on first use, not import.
supabase = _LazySupabaseClient()
