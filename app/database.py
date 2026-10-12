import os as _os

# Preflight env-efektif SEBELUM Settings()/create_client(). Hanya aktif bila
# DIP_APP_ENV=staging. Kontrak eksplisit: environment efektif, bukan file.
if _os.getenv("DIP_APP_ENV", "").strip().lower() == "staging":
    from app.staging_preflight import validate_effective_env as _validate_env

    _validate_env(_os.environ, caller="app.database import")

from supabase import create_client, Client
from app.config import settings
from app.staging_guard import assert_allowed_target

# Guard staging fail-closed di sisi import: gagal startup bila DIP_APP_ENV=staging
# tetapi target bukan project staging. Gagal startup lebih aman daripada
# salah-sasaran ke produksi.
assert_allowed_target("app.database import")

# Inisialisasi Supabase Client tunggal menggunakan Service Role Key (Bypass RLS)
supabase: Client = create_client(settings.supabase_url, settings.supabase_service_role_key)