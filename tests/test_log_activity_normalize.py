"""Unit test murni TYPE-01: normalisasi entity_id di log_activity.

Latar (temuan audit TYPE-01): kolom `activity_logs.entity_id` bertipe uuid.
Call site yang mengirim nilai non-UUID (nama perusahaan, "-") membuat insert
audit GAGAL CAST — dan karena log_activity fail-open, baris audit hilang
diam-diam (seluruh jejak update dokumen legal perusahaan tidak pernah
tersimpan di DB).

Kontrak yang dikunci test ini:
  1. UUID valid                 -> entity_id dikirim apa adanya.
  2. Nama perusahaan (bukan UUID) -> entity_id = None; nilai mentah masuk
     entity_label supaya tetap bisa ditelusuri.
  3. "-"                        -> entity_id = None.
  4. None                       -> entity_id = None.
  5. Insert tetap terjadi (baris audit TIDAK hilang) di semua kasus.

Tanpa koneksi, tanpa secret. Import app.main membutuhkan env dummy seperti
di ci.yml: SUPABASE_URL/SUPABASE_KEY/SUPABASE_SERVICE_ROLE_KEY + PYTHONPATH=.
Dijalankan: python tests/test_log_activity_normalize.py
"""

import os
import sys
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app.main as main_mod  # noqa: E402  (butuh env dummy sebelum import)


class _FakeInsertBuilder:
    def __init__(self, captured):
        self._captured = captured

    def insert(self, row):
        self._captured.append(row)
        return self

    def execute(self):
        return type("R", (), {"data": [{"id": str(uuid.uuid4())}]})()


class FakeSupabase:
    def __init__(self):
        self.captured = []

    def table(self, name):
        assert name == "activity_logs", f"log_activity harus hanya menulis activity_logs, dapat {name}"
        return _FakeInsertBuilder(self.captured)


def _run(entity_id, entity_label):
    fake = FakeSupabase()
    original = main_mod.supabase
    main_mod.supabase = fake
    try:
        main_mod.log_activity(
            {"id": str(uuid.uuid4()), "full_name": "Tester"},
            "update", "nib", entity_id, entity_label,
        )
    finally:
        main_mod.supabase = original
    assert len(fake.captured) == 1, "insert ke activity_logs harus terjadi tepat 1x"
    return fake.captured[0]


VALID_UUID = str(uuid.uuid4())


def test_valid_uuid_kept():
    row = _run(VALID_UUID, "NIB PT Erfi")
    assert row["entity_id"] == VALID_UUID, "UUID valid harus dikirim apa adanya"
    assert row["entity_label"] == "NIB PT Erfi"
    print("[PASS] UUID valid -> entity_id utuh, label tidak berubah")


def test_company_name_normalized():
    row = _run("PT Erfi", "NIB PT Erfi")
    assert row["entity_id"] is None, "nama perusahaan harus dinormalkan ke None (bukan gagal cast)"
    assert "PT Erfi" in (row["entity_label"] or ""), "nilai mentah harus dipertahankan di entity_label"
    print(f"[PASS] nama perusahaan -> entity_id=None, label memuat nilai mentah: {row['entity_label']!r}")


def test_dash_normalized():
    row = _run("-", "Catatan gagal disimpan")
    assert row["entity_id"] is None, '"-" harus dinormalkan ke None'
    print("[PASS] '-' -> entity_id=None")


def test_none_normalized():
    row = _run(None, "note tanpa id")
    assert row["entity_id"] is None, "None harus tetap None"
    assert row["entity_label"] == "note tanpa id"
    print("[PASS] None -> entity_id=None, label utuh")


def test_company_name_without_label():
    """entity_label kosong: nilai mentah jadi entity_label (tidak hilang total)."""
    row = _run("PT Heka", None)
    assert row["entity_id"] is None
    assert (row["entity_label"] or "") == "PT Heka", "nilai mentah harus jadi entity_label bila label kosong"
    print("[PASS] label kosong -> nilai mentah jadi entity_label")


def main():
    test_valid_uuid_kept()
    test_company_name_normalized()
    test_dash_normalized()
    test_none_normalized()
    test_company_name_without_label()
    print("\nSemua test TYPE-01 normalisasi entity_id LULUS.")


if __name__ == "__main__":
    sys.exit(main())
