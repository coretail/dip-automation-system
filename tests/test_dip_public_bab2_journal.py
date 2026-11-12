"""Unit test murni: logika bab2_materials (link jurnal) hub publik /dip/*.

Menguji helper murni app/dip_public.py tanpa DB/network:
- bab2_journal_link: link jurnal adalah URL EKSTERNAL, dinormalisasi lewat
  safe_journal_href (tidak raise; tidak valid -> None).
- bab2_material_entry: bahan tampil bila punya file storage ATAU link jurnal;
  hitungan file (m.files) tetap hanya file storage, jurnal tidak ikut.
(Alur token akses, rate limit, dan revoke TIDAK disentuh test ini.)

Tanpa koneksi, tanpa secret. Dijalankan: python tests/test_dip_public_bab2_journal.py
(dengan PYTHONPATH=. seperti di ci.yml).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.dip_public import bab2_journal_link, bab2_material_entry  # noqa: E402

RM_FULL = {"id": "rm-1", "nama_dagang": "Glycerin", "kode_bahan_baku": "HMC01LQ-1101"}


def test_entry_files_plus_journal():
    files = [{"label": "MSDS", "icon": "fa-file-triangle", "url": "https://s.example/m.pdf"}]
    entry = bab2_material_entry(RM_FULL, files, "https://j.example/g.pdf")
    assert entry is not None
    assert entry["nama"] == "Glycerin" and entry["kode"] == "HMC01LQ-1101"
    assert entry["files"] == files
    assert entry["journal_link"] == "https://j.example/g.pdf"
    # Jurnal TIDAK ikut masuk ke daftar file (hitungan m.files|length tak terpengaruh).
    assert len(entry["files"]) == 1


def test_entry_files_only():
    files = [{"label": "CoA", "icon": "fa-file-circle-check", "url": "https://s.example/c.pdf"}]
    entry = bab2_material_entry(RM_FULL, files, None)
    assert entry is not None
    assert entry["journal_link"] is None
    assert len(entry["files"]) == 1


def test_entry_journal_only_still_shown():
    # Bahan yang TIDAK punya file storage tapi punya jurnal tetap harus tampil.
    entry = bab2_material_entry(RM_FULL, [], "https://j.example/only.pdf")
    assert entry is not None
    assert entry["files"] == []
    assert entry["journal_link"] == "https://j.example/only.pdf"


def test_entry_nothing_hidden():
    assert bab2_material_entry(RM_FULL, [], None) is None


def test_entry_name_code_fallback():
    entry = bab2_material_entry({}, [], "https://j.example/x.pdf")
    assert entry["nama"] == "Unknown" and entry["kode"] == "-"


def test_journal_link_passthrough_valid():
    assert bab2_journal_link({"journal_link": "https://j.example/a"}) == "https://j.example/a"
    assert bab2_journal_link({"journal_link": "http://j.example/a"}) == "http://j.example/a"
    # Whitespace di tepi di-strip.
    assert bab2_journal_link({"journal_link": "  https://j.example/a  "}) == "https://j.example/a"


def test_journal_link_invalid_becomes_none_no_raise():
    # Nilai tidak valid dari DB (mis. input manual) tidak boleh membuat hub
    # publik error saat render: safe_journal_href -> None.
    assert bab2_journal_link({"journal_link": "ftp://j.example/a"}) is None
    assert bab2_journal_link({"journal_link": "javascript:alert(1)"}) is None
    assert bab2_journal_link({"journal_link": "https://a b.com"}) is None
    assert bab2_journal_link({"journal_link": "h" * 3000}) is None
    assert bab2_journal_link({"journal_link": None}) is None
    assert bab2_journal_link({}) is None
    assert bab2_journal_link(None) is None


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for _name, func in tests:
        func()
        print(f"[PASS] {func.__name__}")
    print(f"PASS {len(tests)} pemeriksaan logika bab2 jurnal hub publik (murni, tanpa DB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
