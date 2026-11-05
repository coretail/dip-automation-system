"""Unit test render penandatangan "Mengetahui" (pure-local, tanpa koneksi/secret).

Render bab2_qc_section.html dan bab2_qc_block.html dengan Jinja2 dan kunci
kontrak label: "Disetujui Oleh (QC)" ada, "(QA)" tidak ada, dan
"Mengetahui (Kepala QC)" tampil dengan nilai terisi atau "-" bila kosong.
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
    assert "Diperiksa Oleh (QC)" in html_section
    assert "Disetujui Oleh (QC)" in html_section
    assert "Disetujui Oleh (QA)" not in html_section
    assert "Mengetahui (Kepala QC)" in html_section
    assert "Erna" in html_section
    print("[PASS] bab2_qc_section: label QC + Mengetahui terisi")

    html_block = _render("bab2_qc_block.html", item={
        "nm": "Bahan A",
        "comps": "Aqua",
        "batch": {"qc_signer": "Siti", "qa_signer": "Budi", "mengetahui_signer": "Erna",
                  "kesimpulan": "ok"}})
    assert "Diperiksa Oleh (QC)" in html_block
    assert "Disetujui Oleh (QC)" in html_block
    assert "Disetujui Oleh (QA)" not in html_block
    assert "Mengetahui (Kepala QC)" in html_block
    assert "Erna" in html_block
    print("[PASS] bab2_qc_block: label QC + Mengetahui terisi")

    # (c) kosong / None / kunci tidak ada -> "-" tanpa error
    for variant, batch in [
        ("kosong", {"qc_signer": "Siti", "qa_signer": "Budi", "mengetahui_signer": ""}),
        ("none", {"qc_signer": "Siti", "qa_signer": "Budi", "mengetahui_signer": None}),
        ("tak-ada", {"qc_signer": "Siti", "qa_signer": "Budi"}),
    ]:
        html = _render("bab2_qc_section.html", batch={**batch, "kesimpulan": "ok"})
        assert "Mengetahui (Kepala QC)" in html
        assert "<td>-</td>" in html
        html_b = _render("bab2_qc_block.html", item={"nm": "Bahan A", "comps": "Aqua",
                                                     "batch": {**batch, "kesimpulan": "ok"}})
        assert "Mengetahui (Kepala QC)" in html_b
        print(f"[PASS] bab2_qc: nilai {variant} -> '-' tanpa error")

    print("\nSemua test Mengetahui LULUS.")


if __name__ == "__main__":
    main()
