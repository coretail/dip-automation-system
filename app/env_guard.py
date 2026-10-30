"""Guard mode produksi implisit (audit G-11).

Modul ini sengaja TIDAK membuat ``settings`` dan tidak membaca ``.env`` saat
diimpor, supaya bisa dites murni tanpa efek samping.
"""
from __future__ import annotations

import os
from typing import Iterable


def assert_explicit_production(app_env: str, dotenv_files: Iterable[str]) -> None:
    """Tolak mode produksi implisit bila ada file ``.env`` di disk.

    Tanpa ``DIP_APP_ENV``, ``uvicorn app.main:app`` langsung memuat ``.env``
    (rahasia produksi) tanpa preflight staging. Di mesin yang punya file
    ``.env``, mode produksi harus dipilih eksplisit (``DIP_APP_ENV=production``).
    Render/CI tidak punya file ``.env`` (rahasia dari env proses), jadi tidak
    terpengaruh. ``dotenv_files``: path ``.env`` yang ditemukan (kosong = tidak ada).
    """
    if (app_env or "").strip().lower() == "production":
        return
    found = [p for p in dotenv_files if p]
    if found:
        raise RuntimeError(
            "[CONFIG] DIP_APP_ENV tidak diset tetapi file .env ditemukan "
            f"({found[0]}): ini akan memuat konfigurasi PRODUKSI tanpa preflight. "
            "Untuk pengembangan/tes pakai `python scripts/run_staging_8017.py`; "
            "untuk menjalankan produksi dengan sengaja set DIP_APP_ENV=production."
        )


def find_dotenv_files() -> list[str]:
    """Path ``.env`` yang akan dibaca mode produksi (cwd dan hasil pencarian dotenv)."""
    from dotenv import find_dotenv

    cwd_env = os.path.join(os.getcwd(), ".env")
    return [p for p in (cwd_env if os.path.isfile(cwd_env) else "", find_dotenv()) if p]
