import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class _StagingSettings(BaseSettings):
    supabase_url: str
    supabase_key: str
    supabase_service_role_key: str
    gemini_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env.staging", env_file_encoding="utf-8", extra="ignore")


class _ProdSettings(BaseSettings):
    supabase_url: str
    # Anon key: tidak dipakai kode aplikasi (semua akses lewat service role). Opsional.
    supabase_key: str = ""
    supabase_service_role_key: str
    gemini_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


def _is_staging() -> bool:
    return os.getenv("DIP_APP_ENV", "").strip().lower() == "staging"


if _is_staging():
    # Staging: .env produksi BUKAN sumber. Env proses tervalidasi diutamakan;
    # fallback HANYA .env.staging.
    settings = _StagingSettings()
else:
    # Produksi: perilaku lama dipertahankan.
    from dotenv import load_dotenv

    load_dotenv(override=False)
    settings = _ProdSettings()