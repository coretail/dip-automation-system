"""Unit test PENCECOKKAN (pencocokan) import journal_link — MURNI, tanpa DB/network.

Menggunakan fungsi ``compute_import_plan`` yang diekstrak dari
``migration/import_journal_link.py`` (tanpa memanggil Management API apa pun).
Dijalankan: ``python tests/test_import_journal_link_matching.py``.
"""
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Muat modul skrip dari path file (skrip ini bukan package, tapi modulnya aman
# diimpor: hanya impor app.journal_link / app.staging_preflight yang murni).
_SPEC = importlib.util.spec_from_file_location(
    "import_journal_link", ROOT / "migration" / "import_journal_link.py")
ijl = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ijl)

compute_import_plan = ijl.compute_import_plan
_norm = ijl._norm

DB = [
    {"id": "id-a", "kode_bahan_baku": "K-001", "nama_dagang": "Alpha", "journal_link": None},
    {"id": "id-b", "kode_bahan_baku": "K-002", "nama_dagang": "Beta", "journal_link": None},
    {"id": "id-c", "kode_bahan_baku": "K-003", "nama_dagang": "Gamma",
     "journal_link": "https://existing.example/x"},
]


def test_kode_terisi_tidak_ada_di_db_tidak_fallback_nama():
    # Kode terisi (K-999) tidak ada di DB; NAMANYA ("Alpha") memang ada di DB,
    # tapi karena kode TERISI, tidak boleh jatuh ke fallback nama -> unmatched.
    plan = compute_import_plan(DB, [(7, "K-999", "Alpha", "https://j.example/1")])
    assert plan["planned"] == {}, plan["planned"]
    assert (7, "K-999") in plan["unmatched"], plan["unmatched"]


def test_kode_kosong_nama_cocok_terpakai():
    # Kode kosong + nama cocok (abaikan huruf besar/kecil) -> terpakai via nama.
    plan = compute_import_plan(DB, [(3, "", "alpha", "https://j.example/a")])
    assert plan["planned"] == {"id-a": "https://j.example/a"}, plan["planned"]
    assert not plan["unmatched"], plan["unmatched"]


def test_sudah_terisi_di_db_diskip():
    # id-c sudah punya journal_link di DB -> masuk already_filled, bukan planned.
    plan = compute_import_plan(DB, [(2, "K-003", "Gamma", "https://j.example/zz")])
    assert plan["planned"] == {}, plan["planned"]
    assert any(a[0] == 2 for a in plan["already_filled"]), plan["already_filled"]


def test_planned_items_tidak_crash():
    # Uraikan rencana memakai .items() seperti di main(); harus aman (pasangan
    # (rid, link)), tidak crash, dan exp idempotency check tidak memunculkan
    # rencana ulang untuk baris yang sudah kosong di DB.
    plan = compute_import_plan(DB, [
        (3, "", "alpha", "https://j.example/a"),
        (5, "K-002", "", "https://j.example/b"),
    ])
    assert set(plan["planned"].keys()) == {"id-a", "id-b"}, plan["planned"]
    by_id = {r["id"]: r for r in DB}
    planned2 = {rid: link for rid, link in plan["planned"].items()
                if not _norm(by_id.get(rid, {}).get("journal_link"))}
    assert set(planned2) == {"id-a", "id-b"}, planned2
    # Setelah semua terisi, tidak ada yang tersisa.
    filled = {r["id"]: {**r, "journal_link": "https://x.example/y"} for r in DB}
    planned3 = {rid: link for rid, link in plan["planned"].items()
                if not _norm(filled.get(rid, {}).get("journal_link"))}
    assert planned3 == {}, planned3


def test_sorting_nomor_baris_int():
    # Nomor baris harus int (nomor baris Excel) dan will_write terurut tanpa
    # error tipe campuran.
    db2 = [
        {"id": "id-a", "kode_bahan_baku": "K-001", "nama_dagang": "Alpha", "journal_link": None},
        {"id": "id-b", "kode_bahan_baku": "K-002", "nama_dagang": "Beta", "journal_link": None},
        {"id": "id-d", "kode_bahan_baku": "K-004", "nama_dagang": "Delta", "journal_link": None},
    ]
    xrows = [
        (12, "K-001", "", "https://j.example/a"),   # via kode
        (3, "K-002", "", "https://j.example/b"),     # via kode
        (7, "", "delta", "https://j.example/d"),      # via nama (kode kosong)
    ]
    plan = compute_import_plan(db2, xrows)
    ww = plan["will_write"]
    assert [w[0] for w in ww] == [3, 7, 12], ww
    assert all(isinstance(w[0], int) for w in ww), ww
    assert ww == sorted(ww), ww  # sorted int tidak error


def test_konflik_satu_bahan_link_beda():
    db3 = [{"id": "id-a", "kode_bahan_baku": "K-001", "nama_dagang": "Alpha",
            "journal_link": None}]
    plan = compute_import_plan(db3, [
        (2, "K-001", "", "https://j.example/x"),
        (4, "K-001", "", "https://j.example/y"),
    ])
    assert plan["conflicts"] == {"id-a": ["https://j.example/x", "https://j.example/y"]}, \
        plan["conflicts"]
    assert plan["planned"] == {}, plan["planned"]


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    for _name, func in tests:
        func()
        print(f"[PASS] {func.__name__}")
    print(f"PASS {len(tests)} pemeriksaan pencocokan journal_link (murni, tanpa DB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
