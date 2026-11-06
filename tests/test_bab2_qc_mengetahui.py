"""Unit test template Catatan Spesifikasi & Catatan Pemeriksaan Bahan Baku (pure-local).

Merender bab2_spec_block.html, bab2_qc_section.html, dan bab2_qc_block.html
menjadi PDF sungguhan (xhtml2pdf) lalu memeriksa isi teksnya, tanpa koneksi/secret.

Kontrak yang dikunci:
- Spesifikasi: judul, header QUALITY CONTROL, nomor dokumen, Nama INCI/Kimia,
  tabel PARAMETER/SPESIFIKASI/METODE, Referensi hanya di header (bukan baris).
- Catatan Pemeriksaan: tepat 1 halaman; penandatangan "Disetujui Oleh" dan
  "Pengujian Dilakukan Oleh" berjabatan QC, lalu "Mengetahui" berjabatan Kepala QC
  di bawahnya; label "(QA)" lama tidak ada; nilai kosong tampil "-".
- brand_assets / inci_text: kop & logo ada untuk kedua perusahaan.
"""
import io
import os
import sys
from pathlib import Path

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# xhtml2pdf hanya mau membaca gambar di bawah direktori kerja.
os.chdir(ROOT)

from jinja2 import Environment, FileSystemLoader  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from app import bab2_pdf  # noqa: E402

ENV = Environment(loader=FileSystemLoader(str(ROOT / "app" / "templates")))

SPEC = [
    {"key": "Pemerian", "value": "Serbuk, Putih"},
    {"key": "Aroma", "value": "Tidak Berbau"},
    {"key": "pH", "value": "pH = 4,0 - 6,0"},
    {"key": "Viskositas", "value": "-"},
    {"key": "Masa Kedaluwarsa", "value": "3 Tahun"},
    {"key": "Cara Penyimpanan", "value": "Tertutup rapat"},
    {"key": "Referensi", "value": "COA"},
]
MATERIAL = {
    "nama_dagang": "Aristoflex Tac",
    "kode_bahan_baku": "EML19PDT-0519",
    "inci_text": "Ammonium Acryloyldimethyltaurate (and) Carboxyethyl Acrylate Crosspolymer",
    "spec_parameters": SPEC,
}
BATCH = {
    "no_batch": "0000101785",
    "supplier": "Jutta Rasa Abadi",
    "tanggal_sampling": "2025-03-07",
    "tanggal_ed": "2028-03-06",
    "perusahaan": "PT Erfi",
    "kesimpulan": "diluluskan",
    "qc_signer": "Siti Aminah",
    "qa_signer": "Yeni Fiforiyanti",
    "mengetahui_signer": "Erna Wati",
    "qc_results": [{"key": "Pemerian", "value": "Passed"}, {"key": "pH", "value": "6,1"}],
}


def _pdf_text(pdf_bytes):
    assert pdf_bytes and pdf_bytes[:4] == b"%PDF", "render PDF gagal"
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return len(reader.pages), " ".join(text.split())


def _render(name, **ctx):
    html = ENV.get_template(name).render(**ctx)
    return _pdf_text(bab2_pdf.render_html_to_pdf(html))


def test_brand_assets():
    for company in ("PT Erfi", "PT Heka"):
        brand = bab2_pdf.brand_assets(company)
        assert brand["kop"] and os.path.isfile(brand["kop"]["src"]), company
        assert brand["logo"] and os.path.isfile(brand["logo"]["src"]), company
        assert brand["nomor_spek"] == "PM/EKA/FL/014/00"
        assert brand["nomor_catatan"] == "PM/EKA/FL/003/01"
    assert "heka" in bab2_pdf.brand_assets("PT Heka")["kop"]["src"]
    assert "erfi" in bab2_pdf.brand_assets("PT Erfi")["kop"]["src"]
    assert "erfi" in bab2_pdf.brand_assets(None)["kop"]["src"]  # default = Erfi
    print("[PASS] brand_assets: kop/logo Erfi & Heka tersedia, default Erfi")


def test_inci_text():
    comps = [{"inci_name": "Aqua"}, {"inci_name": "Glycerin"}, {"inci_name": "Aqua"}, {"inci_name": ""}]
    assert bab2_pdf.inci_text(lambda rm, vid: comps, {}, None) == "Aqua (and) Glycerin"
    assert bab2_pdf.inci_text(lambda rm, vid: [], {}, None) == ""

    def boom(rm, vid):
        raise RuntimeError("x")

    assert bab2_pdf.inci_text(boom, {}, None) == ""  # gagal -> kosong, tidak melempar
    print("[PASS] inci_text: digabung (and), duplikat/kosong dibuang, error -> ''")


def test_spec_template():
    for company in ("PT Erfi", "PT Heka"):
        pages, text = _render("bab2_spec_block.html", item={"material": MATERIAL}, index=1,
                              brand=bab2_pdf.brand_assets(company))
        assert pages == 1, f"{company}: spesifikasi harus 1 halaman, dapat {pages}"
        for expected in ("QUALITY CONTROL", "Nomor : PM/EKA/FL/014/00", "CATATAN SPESIFIKASI BAHAN BAKU",
                         "Nama INCI/Kimia", "Carboxyethyl Acrylate Crosspolymer", "Nama Dagang : Aristoflex Tac",
                         "No Kode : EML19PDT-0519", "Referensi : COA", "PARAMETER", "SPESIFIKASI", "METODE",
                         "Pemerian", "Serbuk, Putih", "Visual", "Organoleptik", "pH Meter",
                         "Masa Kedaluwarsa", "3 Tahun", "Sesuai CoA", "Disetujui Oleh", "QC"):
            assert expected in text, f"{company}: '{expected}' tidak ada di spesifikasi: {text[:300]}"
        # Referensi hanya di header, bukan baris tabel parameter.
        assert text.count("Referensi") == 1, text
    print("[PASS] spek: judul, kop, INCI, tabel parameter/metode, Referensi di header, 1 halaman")


def test_spec_template_minimal():
    # Tanpa brand / INCI / spek -> tetap render (placeholder "-"), tanpa error.
    pages, text = _render("bab2_spec_block.html", item={"material": {"nama_dagang": "Air"}}, index="")
    assert pages == 1 and "Nama INCI/Kimia : -" in text and "Nama Dagang : Air" in text
    # Referensi non-CoA mengubah metode ED/penyimpanan.
    spec = [{"key": "Masa Kedaluwarsa", "value": "2 Tahun"}, {"key": "Referensi", "value": "Spesifikasi Supplier"}]
    _, text = _render("bab2_spec_block.html", item={"material": {"nama_dagang": "Air", "spec_parameters": spec}},
                      index="", brand=bab2_pdf.brand_assets("PT Erfi"))
    assert "Sesuai Spesifikasi Supplier" in text, text
    print("[PASS] spek: tanpa brand/INCI/spek tetap render; Referensi non-CoA masuk metode")


def test_catatan_signatures_and_layout():
    brand = bab2_pdf.brand_assets("PT Erfi")
    pages, text = _render("bab2_qc_section.html", batch=BATCH, material=MATERIAL, brand=brand)
    assert pages == 1, f"catatan harus 1 halaman, dapat {pages}"
    for expected in ("Nomor : PM/EKA/FL/003/01", "CATATAN PEMERIKSAAN BAHAN BAKU", "Nama Bahan Baku : Aristoflex Tac",
                     "No. Batch : 0000101785", "Supplier : Jutta Rasa Abadi",
                     "Tanggal Pengambilan Sample : 07 Maret 2025",
                     "Spesifikasi/nilai keberterimaan", "Exp Date", "06 Maret 2028", "3 Tahun",
                     "Serbuk, Putih", "Passed", "6,1", "Kesimpulan", "DILULUSKAN", "DITOLAK"):
        assert expected in text, f"'{expected}' tidak ada di catatan: {text}"
    assert "(QA)" not in text and "Ka. Bagian Pengawasan Mutu" not in text

    # Tiga penandatangan: Disetujui (QC) + Pengujian (QC) berdampingan, Mengetahui (Kepala QC) di bawahnya.
    i_setuju = text.index("Disetujui Oleh,")
    i_uji = text.index("Pengujian Dilakukan Oleh,")
    i_tahu = text.index("Mengetahui,")
    assert i_setuju < i_uji < i_tahu, "urutan tanda tangan salah"
    assert text.index("Yeni Fiforiyanti") > i_setuju and text.index("Siti Aminah") > i_uji
    assert text.index("Erna Wati") > i_tahu and text.rstrip().endswith("Kepala QC"), text[-120:]
    assert text[i_setuju:i_tahu].count("QC") >= 2, "dua penandatangan pertama harus berjabatan QC"
    print("[PASS] catatan: 1 halaman, 4 field header, tiga tanda tangan (QC, QC, Kepala QC)")


def test_catatan_kosong_dan_tanpa_batch():
    brand = bab2_pdf.brand_assets("PT Heka")
    # nilai kosong / kunci tak ada -> "-"
    for variant in ({"mengetahui_signer": ""}, {"mengetahui_signer": None}, {}):
        batch = {k: v for k, v in BATCH.items() if k != "mengetahui_signer"}
        batch.update(variant)
        pages, text = _render("bab2_qc_section.html", batch=batch, material=MATERIAL, brand=brand)
        assert pages == 1
        assert "Mengetahui, - Kepala QC" in text, text[-160:]
    # tanpa batch -> formulir kosong + catatan, tetap 1 halaman
    pages, text = _render("bab2_qc_section.html", batch=None, material=MATERIAL, brand=brand)
    assert pages == 1 and "Belum ada riwayat batch" in text and "Nama Bahan Baku : Aristoflex Tac" in text
    # kesimpulan ditolak / karantina
    _, ditolak = _render("bab2_qc_section.html", batch={**BATCH, "kesimpulan": "ditolak"}, material=MATERIAL, brand=brand)
    assert "DILULUSKAN" in ditolak and "DITOLAK" in ditolak
    _, karantina = _render("bab2_qc_section.html", batch={**BATCH, "kesimpulan": "karantina"}, material=MATERIAL, brand=brand)
    assert "KARANTINA" in karantina
    print("[PASS] catatan: kosong -> '-', tanpa batch -> formulir kosong, ditolak/karantina tampil")


def test_catatan_nama_dari_embed_dan_banyak_baris():
    brand = bab2_pdf.brand_assets("PT Erfi")
    # Nama bahan dari embed raw_materials (route preview) dan embed berupa list.
    for embed in ({"nama_dagang": "PF. Passionate"}, [{"nama_dagang": "PF. Passionate"}]):
        _, text = _render("bab2_qc_section.html", batch={**BATCH, "raw_materials": embed}, material=None, brand=brand)
        assert "Nama Bahan Baku : PF. Passionate" in text, text
    # Banyak parameter tetap 1 halaman.
    many = {**BATCH, "qc_results": [{"key": f"Uji {n}", "value": "Passed"} for n in range(1, 9)]}
    pages, _ = _render("bab2_qc_section.html", batch=many, material=MATERIAL, brand=brand)
    assert pages == 1, f"9 baris pengujian harus tetap 1 halaman, dapat {pages}"
    # qc_results format lama (string biasa, bukan mapping) tidak error.
    legacy = {**BATCH, "qc_results": ["Pemerian", {"key": "pH", "value": "7"}]}
    pages, text = _render("bab2_qc_section.html", batch=legacy, material=MATERIAL, brand=brand)
    assert pages == 1 and "Pemerian" in text
    print("[PASS] catatan: nama dari embed (dict/list), 9 baris tetap 1 halaman, format lama aman")


def test_catatan_zip_block():
    # Generator ZIP memakai bab2_qc_block.html dengan item={material, batch}.
    pages, text = _render("bab2_qc_block.html", item={"material": MATERIAL, "batch": BATCH}, index=1,
                          brand=bab2_pdf.brand_assets("PT Erfi"))
    assert pages == 1 and "Nama Bahan Baku : Aristoflex Tac" in text and "Kepala QC" in text
    # Tanpa batch pada item ZIP -> catatan "belum ada riwayat batch".
    _, text = _render("bab2_qc_block.html", item={"material": MATERIAL, "batch": None}, index=1,
                      brand=bab2_pdf.brand_assets("PT Erfi"))
    assert "Belum ada riwayat batch" in text
    print("[PASS] catatan: varian ZIP (bab2_qc_block) memakai layout yang sama")


def main():
    test_brand_assets()
    test_inci_text()
    test_spec_template()
    test_spec_template_minimal()
    test_catatan_signatures_and_layout()
    test_catatan_kosong_dan_tanpa_batch()
    test_catatan_nama_dari_embed_dan_banyak_baris()
    test_catatan_zip_block()
    print("\nSemua test template Bab II (Spesifikasi & Catatan Pemeriksaan) LULUS.")


if __name__ == "__main__":
    main()
