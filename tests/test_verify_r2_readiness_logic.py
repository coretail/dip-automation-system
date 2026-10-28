"""Unit test murni untuk helper migration/verify_r2_readiness.py (butir E-12).

Mengunci perilaku helper yang ditambahkan/dipakai ulang saat skrip readiness
di-commit ke git:
  1. supabase_bucket_exists: bucket ada -> True; query gagal -> False.
  2. physical: suffix -stg ditempel dengan benar (dan tidak untuk suffix kosong).
  3. parse_bases: JSON rusak -> {} (tidak melempar).

Tanpa koneksi, tanpa secret, tanpa membaca .env (hanya import fungsi murni).
Dijalankan: python tests/test_verify_r2_readiness_logic.py
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from migration.verify_r2_readiness import (  # noqa: E402
    parse_bases,
    physical,
    supabase_bucket_exists,
)


class _FakeStorageRaise:
    def list(self, *_a, **_kw):
        raise RuntimeError("Bucket not found")


class _FakeStorageOk:
    def list(self, *_a, **_kw):
        return []


class _FakeFrom:
    def __init__(self, ok):
        self._ok = ok

    def from_(self, bucket):
        return _FakeStorageOk() if self._ok else _FakeStorageRaise()


def test_bucket_exists_true():
    client = type("C", (), {"storage": property(lambda self: _FakeFrom(True))})()
    assert supabase_bucket_exists(client, "legal-documents") is True
    print("[PASS] bucket Supabase ada -> True")


def test_bucket_exists_false():
    client = type("C", (), {"storage": property(lambda self: _FakeFrom(False))})()
    assert supabase_bucket_exists(client, "legal-documents") is False, \
        "bucket yang tidak ada harus False (FAIL eksplisit, bukan 'inventory failed' samar)"
    print("[PASS] bucket Supabase tidak ada -> False")


def test_physical_suffix():
    assert physical("legal-documents", "-stg") == "legal-documents-stg"
    assert physical("legal-documents", "") == "legal-documents"
    print("[PASS] physical() menempel suffix dengan benar")


def test_parse_bases_tolerant():
    assert parse_bases("not-json") == {}
    assert parse_bases('{"legal-documents": "https://pub-x.r2.dev"}') == {
        "legal-documents": "https://pub-x.r2.dev"
    }
    print("[PASS] parse_bases toleran terhadap JSON rusak")


def main():
    test_bucket_exists_true()
    test_bucket_exists_false()
    test_physical_suffix()
    test_parse_bases_tolerant()
    print("\nSemua test helper verify_r2_readiness LULUS.")


if __name__ == "__main__":
    sys.exit(main())
