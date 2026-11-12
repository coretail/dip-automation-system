"""Unit test murni: build_daftar_jurnal (isi Daftar_Jurnal.txt, ZIP Bab II).

Menguji helper murni app/journal_link.py tanpa DB/network:
- tanpa jurnal -> None (file tidak dibuat);
- sebagian bahan punya jurnal -> hanya bahan tsb yang entri;
- penomoran = posisi bahan di list (sama dengan folder 01_, 02_, ...);
- jurnal tidak valid (non-http(s), spasi, >2048) -> diabaikan;
- header memuat nama produk & perusahaan; URL ada di baris setelah entri.

Tanpa koneksi, tanpa secret. Dijalankan: python tests/test_bab2_daftar_jurnal.py
(dengan PYTHONPATH=. seperti di ci.yml).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.journal_link import build_daftar_jurnal  # noqa: E402


def _rm(idx, nama, kode, link):
    return {"id": f"rm-{idx}", "nama_dagang": nama, "kode_bahan_baku": kode,
            "journal_link": link}


def test_tanpa_jurnal_return_none():
    mats = [
        _rm(1, "Glycerin", "HMC01LQ-1101", None),
        _rm(2, "BHT", "PVA01SBK-0301", ""),
        _rm(3, "Ceramid", "ACV87LQ-0187", "   "),
    ]
    assert build_daftar_jurnal("Produk X", "PT Erfi", mats) is None


def test_semua_jurnal_invalid_return_none():
    mats = [
        _rm(1, "A", "K1", "ftp://j.example/a"),
        _rm(2, "B", "K2", "https://a b.com"),
        _rm(3, "C", "K3", "h" * 3000),
    ]
    assert build_daftar_jurnal("Produk X", "PT Heka", mats) is None


def test_sebagian_bahan_punya_jurnal():
    mats = [
        _rm(1, "Glycerin", "HMC01LQ-1101", None),
        _rm(2, "BHT", "PVA01SBK-0301", "https://cir-safety.org/bht.pdf"),
        _rm(3, "Ceramid", "ACV87LQ-0187", "https://cir-safety.org/cer.pdf"),
        _rm(4, "NaOH", "BUF03PDT-1003", "javascript:alert(1)"),
    ]
    out = build_daftar_jurnal("Sunscreen SPF 50", "PT Heka", mats)
    assert out is not None
    # Hanya bahan 2 & 3 yang punya jurnal valid.
    assert "02. BHT (PVA01SBK-0301)" in out
    assert "03. Ceramid (ACV87LQ-0187)" in out
    assert "01." not in out
    assert "04." not in out
    assert "Glycerin" not in out and "NaOH" not in out
    # URL di baris SETELAH baris entri-nya.
    lines = out.splitlines()
    i_bht = lines.index("02. BHT (PVA01SBK-0301)")
    assert lines[i_bht + 1] == "https://cir-safety.org/bht.pdf"


def test_penomoran_mengikuti_posisi_bukan_urutan_jurnal():
    # Bahan ke-1 & ke-4 punya jurnal; penomoran tetap 01 dan 04 (folder 01_, 04_).
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


def test_header_memuat_produk_dan_perusahaan():
    out = build_daftar_jurnal("Serum ABC", "PT Heka Kosmetik",
                              [_rm(1, "A", "K1", "https://j.example/a")])
    lines = out.splitlines()
    assert "Produk: Serum ABC" in lines
    assert "Perusahaan: PT Heka Kosmetik" in lines


def test_fallback_nama_kode():
    mats = [{"id": "rm-1", "journal_link": "https://j.example/a"}]
    out = build_daftar_jurnal("P", "PT Erfi", mats)
    assert "01. Bahan 1 (-)" in out


def test_list_kosong_none():
    assert build_daftar_jurnal("P", "PT Erfi", []) is None


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for _name, func in tests:
        func()
        print(f"[PASS] {func.__name__}")
    print(f"PASS {len(tests)} pemeriksaan build_daftar_jurnal (murni, tanpa DB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
