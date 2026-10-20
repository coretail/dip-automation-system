"""Pengecek statis sebelum push: nama tak terdefinisi & syntax error di app/.

Kenapa: refactor yang memindahkan route ke modul lain gampang meninggalkan
`NameError` yang BARU meledak saat route diakses (aplikasi tetap boot). Pada
d9ab191, pyflakes menangkap 12 kasus seperti itu (dashboard `/`, halaman
sample, /api/ed-notifications, dst.) dalam hitungan detik.

Hanya memblokir temuan yang pasti bug runtime:
  - "undefined name"      (NameError)
  - syntax error          (modul gagal di-import)
Peringatan gaya lain (import tak terpakai, dll.) sengaja diabaikan.

Pakai:
    pip install pyflakes
    py scripts/check_undefined_names.py            # cek app/
    py scripts/check_undefined_names.py app/main.py app/sample_routes.py

Pasang sebagai pre-push hook (sekali per clone):
    git config core.hooksPath .githooks

Exit code 0 = bersih, 1 = ada temuan, 2 = pyflakes belum terpasang.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKING = ("undefined name", "syntax error", "SyntaxError", "IndentationError")


def main(argv: list[str]) -> int:
    targets = argv or sorted(str(p) for p in (ROOT / "app").glob("*.py"))
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pyflakes", *targets],
            capture_output=True, text=True, cwd=ROOT,
        )
    except OSError as exc:
        print(f"[ABORT] gagal menjalankan pyflakes: {exc}", file=sys.stderr)
        return 2
    if "No module named pyflakes" in proc.stderr:
        print("[ABORT] pyflakes belum terpasang: pip install pyflakes", file=sys.stderr)
        return 2

    lines = (proc.stdout + proc.stderr).splitlines()
    bad = [l for l in lines if any(k in l for k in BLOCKING)]
    for line in bad:
        print(line)
    if bad:
        print(f"\n[FAIL] {len(bad)} temuan pasti-bug-runtime. Perbaiki sebelum push.")
        return 1
    print(f"[OK] tidak ada nama tak terdefinisi / syntax error ({len(targets)} file).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
