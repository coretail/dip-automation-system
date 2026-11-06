"""Unit test render penandatangan "Mengetahui" dan branding perusahaan (pure-local, tanpa koneksi/secret).

Render bab2_qc_section.html dan bab2_qc_block.html dengan Jinja2 dan kunci
kontrak label: "Disetujui Oleh (QC)" ada, "(QA)" tidak ada, dan
"Mengetahui (Kepala QC)" tampil dengan nilai terisi atau "-" bila kosong.
Spesifikasi dan pemeriksaan menggunakan kop/logo serta nomor dokumen:
Erfi, PM/EKA/FL/014/00 dan PM/EKA/FL/003/02; Heka, PM/HEKA/FL/014/01 dan PM/HEKA/FL/003/01.
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "app" / "templates"


def _render(name, **ctx):
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    return env.get_template(name).render(**ctx)


def main():
    # (a) label Disetujui (QC) ada, (QA) tidak ada; (d) Diperiksa tetap ada
    html_section = _render("bab2_qc_section.html", batch={
        "qc_signer": "Siti", "qa_signer": "Budi", "mengetahui_signer": "Erna",
        "kesimpulan": "ok"})
    assert 'Pengujian Dilakukan Oleh' in html_section
    assert 'Disetujui Oleh' in html_section
    assert 'Mengetahui' in html_section
    assert "Erna" in html_section
    assert "PM/EKA/FL/003/02" in html_section
    assert "logo_erfi.png" in html_section
    assert "kop_erfi.png" not in html_section
    assert "kop_heka.png" not in html_section
    print("[PASS] bab2_qc_section: label QC + Mengetahui terisi")

    html_block = _render("bab2_qc_block.html", item={
        "nm": "Bahan A",
        "comps": "Aqua",
        "batch": {"qc_signer": "Siti", "qa_signer": "Budi", "mengetahui_signer": "Erna",
                  "kesimpulan": "ok"}})
    assert 'Pengujian Dilakukan Oleh' in html_block
    assert 'Disetujui Oleh' in html_block
    assert 'Mengetahui' in html_block
    assert "Erna" in html_block
    assert "PM/EKA/FL/003/02" in html_block
    assert "logo_erfi.png" in html_block
    assert "kop_erfi.png" not in html_block
    assert "kop_heka.png" not in html_block
    print("[PASS] bab2_qc_block: label QC + Mengetahui terisi")

    # (c) kosong / None / kunci tidak ada -> "-" tanpa error
    for variant, batch in [
        ("kosong", {"qc_signer": "Siti", "qa_signer": "Budi", "mengetahui_signer": ""}),
        ("none", {"qc_signer": "Siti", "qa_signer": "Budi", "mengetahui_signer": None}),
        ("tak-ada", {"qc_signer": "Siti", "qa_signer": "Budi"}),
    ]:
        html = _render("bab2_qc_section.html", batch={**batch, "kesimpulan": "ok"})
        assert 'Mengetahui' in html
        assert "<td>-</td>" in html
        html_b = _render("bab2_qc_block.html", item={"nm": "Bahan A", "comps": "Aqua",
                                                     "batch": {**batch, "kesimpulan": "ok"}})
        assert 'Mengetahui' in html_b
        print(f"[PASS] bab2_qc: nilai {variant} -> '-' tanpa error")

    heka_html = _render("bab2_qc_section.html", batch={
        "perusahaan": "PT Heka", "qc_signer": "Siti", "qa_signer": "Budi",
        "mengetahui_signer": "Erna", "kesimpulan": "ok"})
    assert "PM/HEKA/FL/003/01" in heka_html
    assert "logo_heka.png" in heka_html
    assert "kop_erfi.png" not in heka_html
    assert "kop_heka.png" not in heka_html
    print("[PASS] bab2_qc_section: Heka menggunakan logo_heka + PM/HEKA/FL/003/01")

    spec_erfi = _render("bab2_spec_block.html", item={
        "material": {"perusahaan": "PT Erfi", "nama_dagang": "Aristoflex Tac",
                     "kode_bahan_baku": "E1", "spec_parameters": []}}, index="")
    assert "CATATAN SPESIFIKASI BAHAN BAKU" in spec_erfi
    assert "PM/EKA/FL/014/00" in spec_erfi
    assert "kop_erfi.png" in spec_erfi
    assert "kop_heka.png" not in spec_erfi
    print("[PASS] bab2_spec_block: Erfi menggunakan kop_erfi + PM/EKA/FL/014/00")

    spec_heka = _render("bab2_spec_block.html", item={
        "material": {"perusahaan": "PT Heka", "nama_dagang": "Aristoflex Tac",
                     "kode_bahan_baku": "E1", "spec_parameters": []}}, index="")
    assert "PM/HEKA/FL/014/01" in spec_heka
    assert "kop_heka.png" in spec_heka
    assert "kop_erfi.png" not in spec_heka
    print("[PASS] bab2_spec_block: Heka menggunakan kop_heka + PM/HEKA/FL/014/01")

    print("\nSemua test Mengetahui LULUS.")


if __name__ == "__main__":
    main()
