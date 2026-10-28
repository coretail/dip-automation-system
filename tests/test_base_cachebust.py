"""Regression test guard cache-bust untuk URL presigned.

Pure-local: hanya membaca template base.html tanpa koneksi atau secret.
Jalankan: `py tests/test_base_cachebust.py`.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_TEMPLATE = ROOT / "app" / "templates" / "base.html"
GUARD = "if (/[?&](X-Amz-Signature|X-Amz-Algorithm|token)=/i.test(url)) return url;"


def main() -> int:
    source = BASE_TEMPLATE.read_text(encoding="utf-8")
    bust_index = source.index("function bust(url)")
    guard_index = source.find(GUARD, bust_index)
    separator_index = source.find("var sep =", bust_index)

    failures = []
    if guard_index < 0:
        failures.append("guard presign tidak ditemukan di fungsi bust()")
    elif separator_index < 0 or guard_index > separator_index:
        failures.append("guard presign harus dijalankan sebelum penambahan cache-buster")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1

    print("PASS guard URL presign pada cache-bust base.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
