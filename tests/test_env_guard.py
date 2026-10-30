"""Unit test murni G-11: guard mode produksi implisit (app/env_guard.py).

Latar (temuan audit G-11): tanpa DIP_APP_ENV, `uvicorn app.main:app` langsung
memuat `.env` produksi tanpa preflight. Guard menolak kondisi itu bila ada file
`.env` di disk, tetapi tidak memengaruhi Render/CI (tidak punya file `.env`).

Kontrak yang dikunci:
  1. DIP_APP_ENV=production (eksplisit)      -> lolos walau ada .env.
  2. Tanpa DIP_APP_ENV + ada .env            -> RuntimeError (fail-closed).
  3. Tanpa DIP_APP_ENV + tidak ada .env      -> lolos (perilaku Render/CI).
  4. Nilai production dinormalisasi (spasi/kapital) -> lolos.
  5. Pesan error menyebut staging launcher dan DIP_APP_ENV=production,
     serta tidak mencetak isi file .env.
  6. find_dotenv_files() mendeteksi .env di cwd.

Tanpa koneksi, tanpa secret, tidak membuat settings dan tidak membaca .env.
Dijalankan: python tests/test_env_guard.py
"""

import os
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.env_guard import assert_explicit_production, find_dotenv_files  # noqa: E402

FAILURES = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def raises(app_env, files):
    try:
        assert_explicit_production(app_env, files)
    except RuntimeError as exc:
        return str(exc)
    return None


def main():
    check("1 production eksplisit + ada .env -> lolos", raises("production", ["/x/.env"]) is None)
    msg = raises("", ["/x/.env"])
    check("2a tanpa DIP_APP_ENV + ada .env -> RuntimeError", msg is not None)
    check("2b nilai tak dikenal + ada .env -> RuntimeError", raises("prod", ["/x/.env"]) is not None)
    check("3 tanpa DIP_APP_ENV + tanpa .env -> lolos (Render/CI)", raises("", []) is None)
    check("3b path kosong diabaikan -> lolos", raises("", ["", ""]) is None)
    check("4 ' Production ' dinormalisasi -> lolos", raises("  Production ", ["/x/.env"]) is None)
    check(
        "5 pesan menyebut launcher staging & DIP_APP_ENV=production",
        bool(msg) and "run_staging_8017.py" in msg and "DIP_APP_ENV=production" in msg,
        msg or "",
    )

    prev = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.chdir(tmp)
            check("6a cwd tanpa .env tidak terdeteksi di cwd", not any(
                os.path.dirname(p) == os.path.realpath(tmp) or p == os.path.join(tmp, ".env")
                for p in find_dotenv_files()
            ))
            with open(os.path.join(tmp, ".env"), "w", encoding="utf-8") as fh:
                fh.write("DUMMY=1\n")
            found = find_dotenv_files()
            check("6b .env di cwd terdeteksi", os.path.join(tmp, ".env") in found, str(found))
        finally:
            os.chdir(prev)

    print()
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} pemeriksaan")
        sys.exit(1)
    print("OK: semua pemeriksaan lolos")


if __name__ == "__main__":
    main()
