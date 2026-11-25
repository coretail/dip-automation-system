"""Unit test gabungan journal_link (pure-local, tanpa DB/secret):
  1. Validasi URL & normalisasi (app/journal_link.py: normalize_journal_link, safe_journal_href)
  2. Pembuatan Daftar_Jurnal.txt ZIP Bab II (app/journal_link.py: build_daftar_jurnal)
  3. Pencocokan & rencana impor journal_link (migration/import_journal_link.py: compute_import_plan)

Digabungkan pada Task 7 dari:
  - test_journal_link.py
  - test_bab2_daftar_jurnal.py
  - test_import_journal_link_matching.py

Jalankan: python tests/test_journal_links.py
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.journal_link import (  # noqa: E402
    JOURNAL_LINK_MAX_LEN,
    build_daftar_jurnal,
    normalize_journal_link,
    safe_journal_href,
)

# =====================================================================
# Bagian 1: Validasi URL normalize_journal_link & safe_journal_href
# =====================================================================

# (input, hasil normalize_journal_link yang diharapkan)
CASES_OK = [
    (None, None),
    ("", None),
    ("   ", None),
    ("\t\n  ", None),
    ("https://example.com", "https://example.com"),
    ("http://example.com/kepala-qc", "http://example.com/kepala-qc"),
    ("  https://example.com/x  ", "https://example.com/x"),
    ("HTTPS://EXAMPLE.COM/A", "HTTPS://EXAMPLE.COM/A"),
    ("https://example.com/a?b=c#d", "https://example.com/a?b=c#d"),
    # Batas panjang: tepat 2048 karakter masih valid.
    ("https://example.com/" + "a" * (JOURNAL_LINK_MAX_LEN - len("https://example.com/")),
     "https://example.com/" + "a" * (JOURNAL_LINK_MAX_LEN - len("https://example.com/"))),
]

# Input yang harus raise ValueError (dan safe_journal_href -> None).
CASES_BAD = [
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "data:text/html,<x>",
    "ftp://example.com/file",
    "example.com/tanpa-scheme",
    "/tanpa-scheme",
    "https://",
    "https:///path-saja",
    "HTTP://",
    "http://",
    "https://a b.com",
    "https://a\tb.com",
    "https://a\nb.com",
    "https://example.com/" + "a" * (JOURNAL_LINK_MAX_LEN + 1 - len("https://example.com/")),
]


def test_journal_link_cases_ok():
    """Converted from test_journal_link.py::main (CASES_OK)."""
    for value, expected in CASES_OK:
        got = normalize_journal_link(value)
        assert got == expected, f"normalize_journal_link({value!r}) -> {got!r} (dugaan {expected!r})"
        safe = safe_journal_href(value)
        assert safe == expected, f"safe_journal_href({value!r}) -> {safe!r} (dugaan {expected!r})"
    print(f"[PASS] {len(CASES_OK)} kasus valid lulus")


def test_journal_link_cases_bad():
    """Converted from test_journal_link.py::main (CASES_BAD)."""
    for value in CASES_BAD:
        try:
            normalize_journal_link(value)
        except ValueError as exc:
            assert str(exc).strip(), f"ValueError untuk {value[:40]!r} punya pesan kosong"
        else:
            raise AssertionError(f"normalize_journal_link({value[:40]!r}) tidak raise ValueError")
        safe = safe_journal_href(value)
        assert safe is None, f"safe_journal_href({value[:40]!r}) -> {safe!r} (dugaan None)"
    print(f"[PASS] {len(CASES_BAD)} kasus invalid lulus")


# =====================================================================
# Bagian 2: build_daftar_jurnal (Daftar_Jurnal.txt ZIP Bab II)
# =====================================================================


def _rm(idx, nama, kode, link):
    return {
        "id": f"rm-{idx}",
        "nama_dagang": nama,
        "kode_bahan_baku": kode,
        "journal_link": link,
    }


def test_tanpa_jurnal_return_none():
    mats = [
        _rm(1, "Glycerin", "HMC01LQ-1101", None),
        _rm(2, "BHT", "PVA01SBK-0301", ""),
        _rm(3, "Ceramid", "ACV87LQ-0187", "   "),
    ]
    assert build_daftar_jurnal("Produk X", "PT Erfi", mats) is None
    print("[PASS] test_tanpa_jurnal_return_none")


def test_semua_jurnal_invalid_return_none():
    mats = [
        _rm(1, "A", "K1", "ftp://j.example/a"),
        _rm(2, "B", "K2", "https://a b.com"),
        _rm(3, "C", "K3", "h" * 3000),
    ]
    assert build_daftar_jurnal("Produk X", "PT Heka", mats) is None
    print("[PASS] test_semua_jurnal_invalid_return_none")


def test_sebagian_bahan_punya_jurnal():
    mats = [
        _rm(1, "Glycerin", "HMC01LQ-1101", None),
        _rm(2, "BHT", "PVA01SBK-0301", "https://cir-safety.org/bht.pdf"),
        _rm(3, "Ceramid", "ACV87LQ-0187", "https://cir-safety.org/cer.pdf"),
        _rm(4, "NaOH", "BUF03PDT-1003", "javascript:alert(1)"),
    ]
    out = build_daftar_jurnal("Sunscreen SPF 50", "PT Heka", mats)
    assert out is not None
    assert "02. BHT (PVA01SBK-0301)" in out
    assert "03. Ceramid (ACV87LQ-0187)" in out
    assert "01." not in out
    assert "04." not in out
    assert "Glycerin" not in out and "NaOH" not in out
    lines = out.splitlines()
    i_bht = lines.index("02. BHT (PVA01SBK-0301)")
    assert lines[i_bht + 1] == "https://cir-safety.org/bht.pdf"
    print("[PASS] test_sebagian_bahan_punya_jurnal")


def test_penomoran_mengikuti_posisi_bukan_urutan_jurnal():
    mats = [
        _rm(1, "Alpha", "K1", "https://j.example/a.pdf"),
        _rm(2, "Beta", "K2", None),
        _rm(3, "Gamma", "K3", None),
        _rm(4, "Delta", "K4", "https://j.example/d.pdf"),
    ]
    out = build_daftar_jurnal("P", "PT Erfi", mats)
    lines = out.splitlines()
    i = lines.index("01. Alpha (K1)")
    assert lines[i + 1] == "https://j.example/a.pdf"
    j = lines.index("04. Delta (K4)")
    assert lines[j + 1] == "https://j.example/d.pdf"
    assert "02." not in lines and "03." not in lines
    print("[PASS] test_penomoran_mengikuti_posisi_bukan_urutan_jurnal")


def test_header_memuat_produk_dan_perusahaan():
    out = build_daftar_jurnal(
        "Serum ABC",
        "PT Heka Kosmetik",
        [_rm(1, "A", "K1", "https://j.example/a")],
    )
    lines = out.splitlines()
    assert "Produk: Serum ABC" in lines
    assert "Perusahaan: PT Heka Kosmetik" in lines
    print("[PASS] test_header_memuat_produk_dan_perusahaan")


def test_fallback_nama_kode():
    mats = [{"id": "rm-1", "journal_link": "https://j.example/a"}]
    out = build_daftar_jurnal("P", "PT Erfi", mats)
    assert "01. Bahan 1 (-)" in out
    print("[PASS] test_fallback_nama_kode")


def test_list_kosong_none():
    assert build_daftar_jurnal("P", "PT Erfi", []) is None
    print("[PASS] test_list_kosong_none")


# =====================================================================
# Bagian 3: Pencocokan & rencana impor journal_link
# =====================================================================

_SPEC = importlib.util.spec_from_file_location(
    "import_journal_link",
    ROOT / "migration" / "import_journal_link.py",
)
ijl = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ijl)

compute_import_plan = ijl.compute_import_plan
_norm = ijl._norm

DB = [
    {"id": "id-a", "kode_bahan_baku": "K-001", "nama_dagang": "Alpha", "journal_link": None},
    {"id": "id-b", "kode_bahan_baku": "K-002", "nama_dagang": "Beta", "journal_link": None},
    {
        "id": "id-c",
        "kode_bahan_baku": "K-003",
        "nama_dagang": "Gamma",
        "journal_link": "https://existing.example/x",
    },
]


def test_kode_terisi_tidak_ada_di_db_tidak_fallback_nama():
    plan = compute_import_plan(DB, [(7, "K-999", "Alpha", "https://j.example/1")])
    assert plan["planned"] == {}, plan["planned"]
    assert (7, "K-999") in plan["unmatched"], plan["unmatched"]
    print("[PASS] test_kode_terisi_tidak_ada_di_db_tidak_fallback_nama")


def test_kode_kosong_nama_cocok_terpakai():
    plan = compute_import_plan(DB, [(3, "", "alpha", "https://j.example/a")])
    assert plan["planned"] == {"id-a": "https://j.example/a"}, plan["planned"]
    assert not plan["unmatched"], plan["unmatched"]
    print("[PASS] test_kode_kosong_nama_cocok_terpakai")


def test_sudah_terisi_di_db_diskip():
    plan = compute_import_plan(DB, [(2, "K-003", "Gamma", "https://j.example/zz")])
    assert plan["planned"] == {}, plan["planned"]
    assert any(a[0] == 2 for a in plan["already_filled"]), plan["already_filled"]
    print("[PASS] test_sudah_terisi_di_db_diskip")


def test_planned_items_tidak_crash():
    plan = compute_import_plan(
        DB,
        [
            (3, "", "alpha", "https://j.example/a"),
            (5, "K-002", "", "https://j.example/b"),
        ],
    )
    assert set(plan["planned"].keys()) == {"id-a", "id-b"}, plan["planned"]
    by_id = {r["id"]: r for r in DB}
    planned2 = {
        rid: link for rid, link in plan["planned"].items()
        if not _norm(by_id.get(rid, {}).get("journal_link"))
    }
    assert set(planned2) == {"id-a", "id-b"}, planned2
    filled = {r["id"]: {**r, "journal_link": "https://x.example/y"} for r in DB}
    planned3 = {
        rid: link for rid, link in plan["planned"].items()
        if not _norm(filled.get(rid, {}).get("journal_link"))
    }
    assert planned3 == {}, planned3
    print("[PASS] test_planned_items_tidak_crash")


def test_sorting_nomor_baris_int():
    db2 = [
        {"id": "id-a", "kode_bahan_baku": "K-001", "nama_dagang": "Alpha", "journal_link": None},
        {"id": "id-b", "kode_bahan_baku": "K-002", "nama_dagang": "Beta", "journal_link": None},
        {"id": "id-d", "kode_bahan_baku": "K-004", "nama_dagang": "Delta", "journal_link": None},
    ]
    xrows = [
        (12, "K-001", "", "https://j.example/a"),
        (3, "K-002", "", "https://j.example/b"),
        (7, "", "delta", "https://j.example/d"),
    ]
    plan = compute_import_plan(db2, xrows)
    ww = plan["will_write"]
    assert [w[0] for w in ww] == [3, 7, 12], ww
    assert all(isinstance(w[0], int) for w in ww), ww
    assert ww == sorted(ww), ww
    print("[PASS] test_sorting_nomor_baris_int")


def test_konflik_satu_bahan_link_beda():
    db3 = [{"id": "id-a", "kode_bahan_baku": "K-001", "nama_dagang": "Alpha", "journal_link": None}]
    plan = compute_import_plan(
        db3,
        [
            (2, "K-001", "", "https://j.example/x"),
            (4, "K-001", "", "https://j.example/y"),
        ],
    )
    assert plan["conflicts"] == {"id-a": ["https://j.example/x", "https://j.example/y"]}, plan["conflicts"]
    assert plan["planned"] == {}, plan["planned"]
    print("[PASS] test_konflik_satu_bahan_link_beda")


ALL_TESTS = [
    test_journal_link_cases_ok,
    test_journal_link_cases_bad,
    test_tanpa_jurnal_return_none,
    test_semua_jurnal_invalid_return_none,
    test_sebagian_bahan_punya_jurnal,
    test_penomoran_mengikuti_posisi_bukan_urutan_jurnal,
    test_header_memuat_produk_dan_perusahaan,
    test_fallback_nama_kode,
    test_list_kosong_none,
    test_kode_terisi_tidak_ada_di_db_tidak_fallback_nama,
    test_kode_kosong_nama_cocok_terpakai,
    test_sudah_terisi_di_db_diskip,
    test_planned_items_tidak_crash,
    test_sorting_nomor_baris_int,
    test_konflik_satu_bahan_link_beda,
]


def main(reverse: bool = False) -> int:
    tests = list(reversed(ALL_TESTS)) if reverse else list(ALL_TESTS)
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if failed:
        print(f"\n{failed} dari {len(tests)} test journal_links GAGAL.")
        return 1
    print(f"\nSemua {len(tests)} test journal_links LULUS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
