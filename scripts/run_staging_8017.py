"""Peluncur staging: 127.0.0.1:8017, tanpa auto-reload. Single-source file.

1. Tolak shell berpengotor DIP_APP_ENV/SUPABASE_*.
2. Parse .env.staging satu-satunya sumber.
3. Validasi file (hostname eksak + binding key terbatas) sebelum ekspor.
4. Ekspor sekaligus, re-validasi env efektif.
5. Baru exec uvicorn. Tanpa impor app.* sebelum lolos. Tanpa cetak secret.
Batas: lihat LIMITS di app.staging_preflight (tanpa bukti key valid live).
"""
import os
import sys

HOST = "127.0.0.1"
PORT = 8017
DOTENV_PATH = ".env.staging"
EXPORT_KEYS = ("DIP_APP_ENV", "SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_ROLE_KEY", "GEMINI_API_KEY")


def main():
    sys.path.insert(0, os.getcwd())
    from app.staging_preflight import parse_dotenv_file, validate_staging_file, validate_effective_env, check_shell_clean
    check_shell_clean(os.environ, caller="launcher-shell")
    file_vals = parse_dotenv_file(DOTENV_PATH)
    validate_staging_file(file_vals, caller="launcher-file")
    for k in EXPORT_KEYS:
        v = (file_vals.get(k) or "").strip()
        if v != "":
            os.environ[k] = v
    validate_effective_env(os.environ, caller="launcher-effective")
    print("STAGING PREFLIGHT PASS (ref tersanitasi, tanpa secret)")
    import uvicorn
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
