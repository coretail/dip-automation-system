from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    supabase_url: str
    # Anon key: tidak dipakai kode aplikasi (semua akses lewat service role). Opsional.
    supabase_key: str = ""
    supabase_service_role_key: str
    gemini_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()