"""Test pure-local budget & model fallback untuk greeting AI.

Verifikasi:
(a) daftar model tidak mengandung "hydrogen", "argon", atau nama non-lite
(b) dengan httpx.AsyncClient.post di-monkeypatch jadi coroutine yang tidur
    10 detik, pemanggilan lewat wait_for 5 detik selesai < 6 detik dan
    mengembalikan None tanpa raise
(c) api_key kosong -> None

Jalankan: python tests/test_greeting_budget.py
"""
import asyncio
import os
import sys
from pathlib import Path

# Root repo ke sys.path
root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

# Set env dummy SEBELUM import app.main (biar env_guard tidak reject)
os.environ["SUPABASE_URL"] = "https://ci.invalid.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "ci-dummy-service-role-key"
os.environ["SUPABASE_KEY"] = "ci-dummy-anon-key"
os.environ["STORAGE_BACKEND"] = "supabase"
os.environ["DIP_APP_ENV"] = "production"  # Production explicit (biar env_guard pass)


def test_model_list_no_codenames():
    """(a) Daftar model tidak boleh mengandung codename bocoran."""
    from app.main import _GEMINI_MODELS_FALLBACK

    forbidden = {"hydrogen", "argon", "carbon"}
    for model in _GEMINI_MODELS_FALLBACK:
        model_lower = model.lower()
        for codename in forbidden:
            assert codename not in model_lower, (
                f"Model '{model}' mengandung codename '{codename}' "
                f"(bocoran, bukan model ID API yang valid)"
            )
        # Model harus end with -flash-lite atau -lite
        assert model_lower.endswith("-lite") or model_lower.endswith("-flash-lite"), (
            f"Model '{model}' harus lite (non-lite tidak diizinkan)"
        )


def test_wait_for_budget_respected():
    """(b) wait_for 5 detik: coroutine yang tidur 10 detik di-cancel, return None."""
    import app.main as main
    import httpx

    # Simpan referensi asli
    original_post = httpx.AsyncClient.post

    # Monkeypatch: post yang tidur 10 detik (lebih lama dari budget 5 detik)
    async def fake_slow_post(self, *args, **kwargs):
        await asyncio.sleep(10)
        return original_post(self, *args, **kwargs)

    httpx.AsyncClient.post = fake_slow_post

    try:
        # Set api_key dummy agar tidak return None dini
        main.settings.gemini_api_key = "dummy-key"

        import time
        start = time.monotonic()
        # Simulasi handler login: wait_for 5 detik
        try:
            ai_phrase = asyncio.run(
                asyncio.wait_for(main._generate_ai_greeting_phrase("test"), timeout=5.0)
            )
        except asyncio.TimeoutError:
            ai_phrase = None  # Handler login catch TimeoutError -> None
        elapsed = time.monotonic() - start

        assert ai_phrase is None, (
            f"Harus return None saat timeout, dapat: {ai_phrase!r}"
        )
        assert elapsed < 6.0, (
            f"Wait_for harus selesai < 6 detik, elapsed: {elapsed:.1f}s"
        )
        print(f"[OK] wait_for budget: elapsed={elapsed:.1f}s, result=None")
    finally:
        httpx.AsyncClient.post = original_post


def test_empty_api_key_returns_none():
    """(c) api_key kosong -> None tanpa network call."""
    import app.main as main

    original_key = main.settings.gemini_api_key
    main.settings.gemini_api_key = ""

    try:
        result = asyncio.run(main._generate_ai_greeting_phrase("test"))
        assert result is None, (
            f"api_key kosong harus return None, dapat: {result!r}"
        )
        print("[OK] api_key kosong -> None")
    finally:
        main.settings.gemini_api_key = original_key


def main():
    """Entry point: jalankan semua test, exit 0 bila semua pass."""
    test_model_list_no_codenames()
    print("[OK] test_model_list_no_codenames")

    test_wait_for_budget_respected()
    print("[OK] test_wait_for_budget_respected")

    test_empty_api_key_returns_none()
    print("[OK] test_empty_api_key_returns_none")

    print("\nSemua test greeting budget lulus.")


if __name__ == "__main__":
    main()
