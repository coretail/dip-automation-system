"""Guard fail-closed isolasi staging (Gate A). Validator URL tunggal dipakai
bersama preflight: app.staging_preflight.validate_staging_url (hostname eksak).

Dipakai oleh semua jalur pembuatan client Supabase. Bila DIP_APP_ENV=staging,
target koneksi HARUS host staging eksak dan tidak boleh ref produksi; bila
guard tidak lolos, panggil RuntimeError sebelum operasi remote apa pun.

Batas key: sama dengan LIMITS preflight — JWT dicek klaim 'ref' lokal, opaque
tidak terverifikasi lokal, tanpa bukti validitas live. Tanpa cetak secret.
"""

import os

STAGING_REF = "odtfppboyjlbatajncgj"
PROD_REF = "dytuprmoorvrugutozwv"


def _settings():
    from app.config import settings  # lazy: jangan bentuk Settings() saat import guard

    return settings


def _staging_url() -> str:
    return _settings().supabase_url or ""


def is_staging_mode() -> bool:
    return os.getenv("DIP_APP_ENV", "").strip().lower() == "staging"


def require_staging_mode(caller: str = "unknown") -> None:
    """Entrypoint eksplisit staging: menolak bila DIP_APP_ENV != staging."""
    if not is_staging_mode():
        raise RuntimeError(
            f"[{caller}] DIP_APP_ENV bukan 'staging'. "
            "Gunakan peluncur staging eksplisit. Dibatalkan."
        )


def assert_allowed_target(caller: str = "unknown") -> None:
    """Gagal tertutup bila mode staging tetapi target tidak cocok/tidak lengkap."""
    if not is_staging_mode():
        return
    from app.staging_preflight import validate_staging_url, check_key_binding

    settings = _settings()
    validate_staging_url(_staging_url(), caller=caller, source="effective-env")
    check_key_binding(
        {
            "SUPABASE_KEY": settings.supabase_key or os.getenv("SUPABASE_KEY", ""),
            "SUPABASE_SERVICE_ROLE_KEY": settings.supabase_service_role_key
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
        },
        caller=caller,
        source="effective-env",
    )
    if not settings.supabase_service_role_key:
        raise RuntimeError(
            f"[{caller}] DIP_APP_ENV=staging tetapi SUPABASE_SERVICE_ROLE_KEY "
            "kosong. Dibatalkan."
        )
    if not (settings.supabase_key or os.getenv("SUPABASE_KEY", "")):
        raise RuntimeError(
            f"[{caller}] DIP_APP_ENV=staging tetapi SUPABASE_KEY (anon) kosong. "
            "Dibatalkan."
        )
    proc_url = (os.getenv("SUPABASE_URL", "") or "").strip().strip("'\"")
    if proc_url and proc_url != _staging_url().strip().strip("'\""):
        raise RuntimeError(
            f"[{caller}] SUPABASE_URL proses tidak cocok dengan konfigurasi "
            "efektif. Dibatalkan."
        )


def staging_client(caller: str):
    """Buat client Supabase hanya setelah guard lolos (tidak mencetak secret)."""
    from supabase import create_client

    assert_allowed_target(caller)
    url = _staging_url()
    key = _settings().supabase_service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError(f"[{caller}] konfigurasi Supabase tidak lengkap. Dibatalkan.")
    return create_client(url, key)
