"""Unit test pure-local untuk generator Sistem Pengkodean Batch (app/batch_coding_pdf.py).

Dijalankan standalone: `python tests/test_batch_coding_pdf.py` (tanpa koneksi DB).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

import pypdf
from app import batch_coding_pdf as bcp

PASSED = []
FAILED = []


def check(name, cond):
    if cond:
        PASSED.append(name)
        print(f"  [OK] {name}")
    else:
        FAILED.append(name)
        print(f"  [FAIL] {name}")


def _company(perusahaan):
    # Sama dengan COMPANY_INFO di app/main.py (kop = URI /static/...), supaya path kop
    # benar-benar teruji (versi lama hanya mengirim "nama" -> selalu fallback teks).
    if "Heka" in perusahaan:
        return {"nama": "PT. HARAKA ERFI KOSMETINDO ABADI", "kop": "/static/images/kop_heka.png"}
    return {"nama": "PT. ERFI KARYA ABADI", "kop": "/static/images/kop_erfi.png"}


# --- build_batch_number -------------------------------------------------
print("build_batch_number:")
check("Erfi 2023-04-03 MPRPDH -> '23 04 03 MPRPDH 01'",
      bcp.build_batch_number(date(2023, 4, 3), "MPRPDH", "PT Erfi") == "23 04 03 MPRPDH 01")
check("Erfi fallback 2023-11-29 ABC (3 char) -> '23 11 29 ABC 01'",
      bcp.build_batch_number(date(2023, 11, 29), "ABC", "PT Erfi") == "23 11 29 ABC 01")
check("Heka 2025-02-22 sediaan 05 UBEB -> '25022205UBEB01'",
      bcp.build_batch_number(date(2025, 2, 22), "UBEB", "PT Heka", kode_sediaan="05") == "25022205UBEB01")
check("Heka 2023-11-29 sediaan 12 CMDG -> '23112912CMDG01'",
      bcp.build_batch_number(date(2023, 11, 29), "CMDG", "PT Heka", kode_sediaan="12") == "23112912CMDG01")
check("Heka tanpa sediaan -> SS '00'",
      bcp.build_batch_number(date(2023, 11, 29), "CMDG", "PT Heka") == "23112900CMDG01")
check("urut 2 -> '02'",
      bcp.build_batch_number(date(2023, 4, 3), "MPRPDH", "PT Erfi", urut=2) == "23 04 03 MPRPDH 02")
check("kode lowercase dinormalisasi",
      bcp.build_batch_number(date(2023, 4, 3), "mprpdh", "PT Erfi") == "23 04 03 MPRPDH 01")

# --- terbilang / berarti ------------------------------------------------
print("berarti_lines:")
lines_erfi = bcp.berarti_lines("23 04 03 MPRPDH 01", date(2023, 4, 3),
                               "PARFUM DEPHERO Men's Parfum Reaction", "PT Erfi")
check("Erfi 2 baris", len(lines_erfi) == 2)
check("Erfi baris 1", lines_erfi[0] == "Berarti : PARFUM DEPHERO Men's Parfum Reaction diproduksi pada 03 April 2023")
check("Erfi baris 2", lines_erfi[1] == "dengan nomor seri batch 01")
lines_heka = bcp.berarti_lines("25022205UBEB01", date(2025, 2, 22),
                                "BALTIKH Extra Bright Underarm Cream", "PT Heka", "Cream", urut=1)
check("Heka 1 baris", len(lines_heka) == 1)
# Sesuai PDF referensi Heka: kalimat diawali NOMOR BATCH, sediaan "Cream" kapital.
check("Heka isi", lines_heka[0] == "Berarti : 25022205UBEB01 diproduksi pada 22 Februari 2025 "
                                   "jenis sediaan Cream produk BALTIKH Extra Bright Underarm Cream batch pertama")
check("terbilang 2", "nomor seri batch 02" in bcp.berarti_lines("x", date(2023, 4, 3), "P", "PT Erfi", urut=2)[1])

# --- format tanggal (hardcoded, 12 bulan) --------------------------------
print("tanggal_untuk_generate:")
check("YYYY-MM-DD valid", bcp.tanggal_untuk_generate("2023-04-03") == date(2023, 4, 3))
check("YYYY-MM-DD dengan jam di-trunc", bcp.tanggal_untuk_generate("2023-04-03T10:00:00+00:00") == date(2023, 4, 3))
check("kosong -> fallback", bcp.tanggal_untuk_generate("") == bcp.FALLBACK_DATE)
check("None -> fallback", bcp.tanggal_untuk_generate(None) == bcp.FALLBACK_DATE)
check("tidak valid -> fallback", bcp.tanggal_untuk_generate("31-99-2023") == bcp.FALLBACK_DATE)
check("fallback = 29 Nov 2023", bcp.FALLBACK_DATE == date(2023, 11, 29))
# Nama bulan semua 12 (hardcoded, tidak pakai locale)
for m, nama in {1: "Januari", 4: "April", 7: "Juli", 12: "Desember"}.items():
    t = date(2023, m, 5)
    check(f"bulan {m} -> {nama}", f"{nama}" in bcp.berarti_lines("x", t, "P", "PT Erfi")[0])

# --- validasi -------------------------------------------------------------
print("validasi:")
check("Erfi 'ABC' valid", bcp.validasi_kode_produk("ABC", "PT Erfi") is None)
check("Erfi 'ABC1' valid (campur angka)", bcp.validasi_kode_produk("ABC1", "PT Erfi") is None)
check("Erfi 'AB' (2) ditolak", bcp.validasi_kode_produk("AB", "PT Erfi") is not None)
check("Erfi 'ABCDEFG' (7) ditolak", bcp.validasi_kode_produk("ABCDEFG", "PT Erfi") is not None)
check("Erfi 'abc' (lowercase) ditolak", bcp.validasi_kode_produk("abc", "PT Erfi") is not None)
check("Heka 'ABC' (3) ditolak", bcp.validasi_kode_produk("ABC", "PT Heka") is not None)
check("Heka 'ABCD' valid", bcp.validasi_kode_produk("ABCD", "PT Heka") is None)
check("Heka sediaan wajib", bcp.validasi_kode_sediaan("", "PT Heka") is not None)
check("Heka sediaan '05' valid", bcp.validasi_kode_sediaan("05", "PT Heka") is None)
check("Heka sediaan '99' ditolak", bcp.validasi_kode_sediaan("99", "PT Heka") is not None)
check("Erfi sediaan tidak divalidasi", bcp.validasi_kode_sediaan("", "PT Erfi") is None)
check("legenda kosong ditolak", bcp.validasi_legenda([]) is not None)
check("legenda valid", bcp.validasi_legenda([{"huruf": "U", "arti": "Underarm"}]) is None)
check("legenda 11 baris ditolak",
      bcp.validasi_legenda([{"huruf": "A", "arti": "x"}] * 11) is not None)
check("legenda huruf 4 char ditolak",
      bcp.validasi_legenda([{"huruf": "ABCD", "arti": "x"}]) is not None)
check("legenda huruf 3 char (DH) OK", bcp.validasi_legenda([{"huruf": "DH", "arti": "x"}, {"huruf": "AP", "arti": "y"}]) is None)
check("label sediaan 05 -> Cream", bcp.label_sediaan("05") == "Cream")
check("label sediaan 12 -> Larutan/Cairan Lain", bcp.label_sediaan("12") == "Larutan/Cairan Lain")
check("is_heka 'PT Heka'", bcp.is_heka("PT Heka"))
check("is_heka 'PT Erfi' false", not bcp.is_heka("PT Erfi"))

# --- render PDF -----------------------------------------------------------
print("render_pdf:")
produkt_erfi = {"nama_produk": "PARFUM DEPHERO Men's Parfum Reaction",
                "perusahaan": "PT Erfi", "tanggal_aktif_na": "2023-04-03"}
produkt_heka = {"nama_produk": "BALTIKH Extra Bright Underarm Cream",
                "perusahaan": "PT Heka", "tanggal_aktif_na": "2025-02-22"}

pdf_erfi = bcp.render_pdf(produkt_erfi, _company("PT Erfi"), "MPRPDH",
                           [{"huruf": "M", "arti": "Men"}, {"huruf": "P", "arti": "Parfum"},
                            {"huruf": "R", "arti": "Reaction"}, {"huruf": "D", "arti": "DEPHERO"},
                            {"huruf": "H", "arti": "High"}])
check("Erfi PDF bytes", pdf_erfi is not None and pdf_erfi[:4] == b"%PDF")
if pdf_erfi:
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf_erfi))
    check("Erfi 1 halaman", len(reader.pages) == 1)
    w, h = float(reader.pages[0].mediabox.width), float(reader.pages[0].mediabox.height)
    check("Erfi landscape", w > h)
    text = reader.pages[0].extract_text() or ""
    check("Erfi memuat nomor batch", "23 04 03 MPRPDH 01" in text)
    check("Erfi memuat nama produk", "PARFUM DEPHERO Men's Parfum Reaction" in text.replace("\n", " ") or
          "PARFUM DEPHERO" in text.replace("\n", " "))
    check("Erfi tidak ada tabel lampiran", "LARUTAN/CAIRAN LAIN" not in text)

pdf_heka = bcp.render_pdf(produkt_heka, _company("PT Heka"), "UBEB",
                          [{"huruf": "U", "arti": "Underarm"}, {"huruf": "B", "arti": "Bright"},
                           {"huruf": "E", "arti": "Extra"}, {"huruf": "B", "arti": "BALTIKH"}],
                          kode_sediaan="05")
check("Heka PDF bytes", pdf_heka is not None and pdf_heka[:4] == b"%PDF")
if pdf_heka:
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf_heka))
    check("Heka 1 halaman", len(reader.pages) == 1)
    w, h = float(reader.pages[0].mediabox.width), float(reader.pages[0].mediabox.height)
    check("Heka landscape", w > h)
    text = (reader.pages[0].extract_text() or "").replace("\n", " ")
    check("Heka memuat nomor batch", "25022205UBEB01" in text)
    check("Heka memuat lampiran sediaan", "LARUTAN/CAIRAN LAIN" in text)
    check("Heka memuat batch pertama", "batch pertama" in text)

# --- kop surat ------------------------------------------------------------
print("kop:")
check("kop Heka path ditemukan", bcp._kop_fs_path(_company("PT Heka")) is not None)
check("kop Erfi path ditemukan", bcp._kop_fs_path(_company("PT Erfi")) is not None)
check("kop Heka = kop_heka.png", os.path.basename(bcp._kop_fs_path(_company("PT Heka")) or "") == "kop_heka.png")
check("kop Erfi = kop_erfi.png", os.path.basename(bcp._kop_fs_path(_company("PT Erfi")) or "") == "kop_erfi.png")
check("kop tanpa /static/ -> None", bcp._kop_fs_path({"kop": "images/kop_erfi.png"}) is None)
for _nama, _pdf in (("Erfi", pdf_erfi), ("Heka", pdf_heka)):
    _r = pypdf.PdfReader(__import__("io").BytesIO(_pdf))
    check(f"{_nama} PDF memuat gambar kop", len(_r.pages[0].images) >= 1)

# --- legenda penuh tetap 1 halaman -----------------------------------------
print("legenda penuh:")
_penuh = [{"huruf": "AB", "arti": "keterangan kode " * 5} for _ in range(10)]
for _nama, _prod in (("Erfi", produkt_erfi), ("Heka", produkt_heka)):
    _b = bcp.render_pdf(_prod, _company("PT " + _nama), "ABCD", _penuh, kode_sediaan="05")
    _r = pypdf.PdfReader(__import__("io").BytesIO(_b))
    check(f"{_nama} 10 baris legenda tetap 1 halaman", len(_r.pages) == 1)

# --- storage path ---------------------------------------------------------
check("storage path", bcp.storage_path("abc-123") == "products/abc-123/sistem_penomoran_batch.pdf")
check("bucket", bcp.bucket() == "raw-material-docs")

print()
print(f"HASIL: {len(PASSED)} lulus, {len(FAILED)} gagal.")
if FAILED:
    print("Yang gagal:", ", ".join(FAILED))
    sys.exit(1)
