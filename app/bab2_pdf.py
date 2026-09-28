"""Helper komposisi PDF untuk generator dokumen Bab II (pipeline PDF gabungan).

Sumber data tiap section (dipanggil dari ``app/main.py``):

- Spek Bahan Baku  : ``raw_material_company_docs.spec_sheet_file_url`` (PDF asli).
                     Spek manual (``spec_parameters``) sengaja tidak dipakai di
                     pipeline PDF ini; kalau PDF tidak ada, Spek dianggap tidak ada.
- Catatan Pemeriksaan: ``raw_material_batches.qc_report_file_url`` (PDF asli),
                     atau data ``raw_material_batches`` kalau PDF tidak ada
- CoA              : ``raw_material_batches.coa_file_url``

Komposisi halaman bahan baku dilakukan langsung dengan pypdf (bukan xhtml2pdf)
supaya posisi penempelan PDF sumber bisa dihitung secara deterministik:
judul + label section digambar lewat content stream, lalu tiap PDF sumber
diskalakan proporsional (tanpa cropping) dan ditempel ke kotaknya. Hasilnya
selalu tepat 1 halaman per bahan baku. PDF sumber tidak diubah di storage,
semua proses in-memory.
"""

import io
import logging

from pypdf import PdfReader, PdfWriter
from pypdf import Transformation
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)
from xhtml2pdf import pisa

logger = logging.getLogger(__name__)

# Ukuran halaman A4 dalam poin (72 pt = 1 inch).
PAGE_WIDTH = 595.28
PAGE_HEIGHT = 841.89

# Geometri halaman komposisi bahan baku.
PAGE_MARGIN = 28.0
HEADER_HEIGHT = 58.0
LABEL_HEIGHT = 18.0
SECTION_GAP = 12.0

_FONT_CACHE: dict[str, int] = {}


def render_html_to_pdf(html: str) -> bytes | None:
    """Render HTML string jadi bytes PDF. Return ``None`` kalau xhtml2pdf error."""
    buffer = io.BytesIO()
    try:
        status = pisa.CreatePDF(src=html, dest=buffer)
    except Exception as exc:  # pragma: no cover - jaga-jaga kalau pisa melempar
        logger.exception("Gagal render HTML ke PDF: %s", exc)
        return None
    if status.err:
        logger.error("xhtml2pdf melaporkan error saat render HTML: %s", status.err)
        return None
    return buffer.getvalue()


def read_pdf_pages(pdf_bytes: bytes, label: str) -> list | None:
    """Parse PDF dari bytes. Return list ``PageObject`` atau ``None`` kalau bukan
    PDF valid / rusak (supaya satu file cacat tidak menggagalkan seluruh Bab II)."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = list(reader.pages)
    except Exception as exc:
        logger.warning("[BAB II] PDF %s tidak valid / rusak, dilewati: %s", label, exc)
        return None
    if not pages:
        logger.warning("[BAB II] PDF %s tidak punya halaman, dilewati", label)
        return None
    return pages


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _latin1(text: str, label: str) -> str:
    """Font standar PDF (Helvetica) hanya mendukung WinAnsi; ganti karakter di luar
    jangkauan supaya halaman tetap valid."""
    try:
        return text.encode("latin-1").decode("latin-1")
    except UnicodeEncodeError:
        cleaned = text.encode("latin-1", "replace").decode("latin-1")
        logger.info("[BAB II] Sebagian karakter pada label \"%s\" diganti karena font PDF standar", label)
        return cleaned


def _add_indirect(page, obj):
    """Daftarkan objek ke PDF induk halaman dan kembalikan IndirectObject-nya."""
    pdf = page.indirect_reference.pdf
    return pdf._add_object(obj)


def _get_font_key(page, bold: bool) -> str:
    font_name = "/F_bold" if bold else "/F_regular"
    cache_key = f"{id(page.indirect_reference.get_object())}:{font_name}"
    if cache_key in _FONT_CACHE:
        return font_name

    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica-Bold" if bold else "/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    })
    font_ref = _add_indirect(page, font)
    resources = page.get(NameObject("/Resources"))
    if resources is None:
        resources = DictionaryObject()
        page[NameObject("/Resources")] = resources
    resources = resources.get_object()
    fonts = resources.get(NameObject("/Font"))
    if fonts is None:
        fonts = DictionaryObject()
        resources[NameObject("/Font")] = fonts
    fonts = fonts.get_object()
    fonts[NameObject(font_name)] = font_ref

    _FONT_CACHE[cache_key] = font_name
    return font_name


def _draw_text(page, text: str, x: float, y: float, size: float, bold: bool = False) -> None:
    """Gambar satu baris teks pada koordinat pypdf (origin kiri-bawah)."""
    text = (text or "").strip()
    if not text:
        return
    font_key = _get_font_key(page, bold)
    safe = _escape_pdf_text(_latin1(text, text))
    existing = page.get(NameObject("/Contents"))
    additions = (
        f"BT /{font_key[1:]} {size} Tf 0 g 1 0 0 1 {round(x, 2)} {round(y, 2)} Tm ({safe}) Tj ET"
    )
    _append_content(page, additions, existing)


def _draw_hline(page, x1: float, y: float, x2: float) -> None:
    existing = page.get(NameObject("/Contents"))
    _append_content(page, f"0.27 G 0.6 w {round(x1, 2)} {round(y, 2)} m {round(x2, 2)} {round(y, 2)} l S",
                     existing)


def _append_content(page, addition: str, existing) -> None:
    """Tambahkan operator gambar ke content stream halaman secara inkremental."""
    if existing is None:
        stream = DecodedStreamObject()
        stream.set_data(b"")
        page[NameObject("/Contents")] = _add_indirect(page, stream)
        existing = page[NameObject("/Contents")]

    obj = existing.get_object()
    previous = obj.get_data() if hasattr(obj, "get_data") else b""
    separator = b"\n" if previous else b""
    obj.set_data(previous + separator + addition.encode("latin-1", "replace"))


def _new_a4_page(writer: PdfWriter):
    """Buat halaman kosong seukuran A4."""
    page = writer.add_blank_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    # add_blank_page sudah menaruh MediaBox; pastikan Resources ada supaya font bisa ditambahkan.
    if page.get(NameObject("/Resources")) is None:
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/ProcSet"): ArrayObject([NameObject("/PDF"), NameObject("/Text")])
        })
    return page


def _draw_page_header(page, title: str, subtitle: str) -> None:
    """Gambar judul halaman + subjudul + garis pemisah di bagian atas halaman."""
    _draw_text(page, title, PAGE_MARGIN, PAGE_HEIGHT - 34, 11, bold=True)
    if subtitle:
        _draw_text(page, subtitle, PAGE_MARGIN, PAGE_HEIGHT - 46, 8.5)
    _draw_hline(page, PAGE_MARGIN, PAGE_HEIGHT - HEADER_HEIGHT, PAGE_WIDTH - PAGE_MARGIN)


def _paste(page, source, left_pt: float, top_pt: float, width: float, height: float) -> bool:
    """Tempel satu halaman PDF sumber ke dalam kotak (left, top, width, height) --
    top diukur dari atas halaman. Skala proporsional, tanpa cropping, center di kotak."""
    src_width = float(source.mediabox.width)
    src_height = float(source.mediabox.height)
    if src_width <= 0 or src_height <= 0 or width <= 0 or height <= 0:
        return False
    scale = min(width / src_width, height / src_height, 1.0)
    if scale <= 0:
        return False
    draw_width = src_width * scale
    draw_height = src_height * scale
    left = left_pt + (width - draw_width) / 2
    y_from_bottom = PAGE_HEIGHT - top_pt - (height + draw_height) / 2
    ctm = Transformation((scale, 0, 0, scale, round(left, 2), round(y_from_bottom, 2)))
    page.merge_transformed_page(source, ctm, over=True)
    return True


def _layout(n_sections: int) -> tuple[list[float], list[float]]:
    """Hitung tinggi & posisi (dari atas halaman) tiap kotak konten."""
    available = PAGE_HEIGHT - PAGE_MARGIN - HEADER_HEIGHT - PAGE_MARGIN
    box_height = (available - n_sections * LABEL_HEIGHT - (n_sections - 1) * SECTION_GAP) / n_sections
    box_heights = [box_height] * n_sections
    box_tops = []
    current = HEADER_HEIGHT
    for _ in range(n_sections):
        box_tops.append(current)
        current += box_height + LABEL_HEIGHT + SECTION_GAP
    return box_heights, box_tops


def compose_material_page(material_name: str, documents: list[tuple[str, bytes]]) -> bytes | None:
    """Gabungkan Spek + Catatan Pemeriksaan satu bahan baku ke SATU halaman A4.

    ``documents`` adalah list ``(label, pdf_bytes)``. Setiap PDF sumber diskalakan
    proporsional (tanpa cropping) lalu ditempel ke kotak section-nya, sehingga
    hasilnya SELALU tepat 1 halaman selama minimal satu dokumen valid tersedia.
    PDF sumber tidak diubah di storage, semua proses in-memory.

    Kalau ternyata sebuah dokumen multi-page, semua halamannya ditata berdampingan
    di dalam kotak yang sama (skala diperkecil) supaya tidak ada data yang hilang
    dan jumlah halaman output tetap 1.

    Return bytes PDF, atau ``None`` kalau tidak ada dokumen yang bisa dipakai.
    """
    usable: list[tuple[str, list]] = []
    for label, pdf_bytes in documents:
        pages = read_pdf_pages(pdf_bytes, label)
        if not pages:
            continue
        if len(pages) > 1:
            logger.info(
                "[BAB II] PDF %s punya %d halaman; semua halaman ditata berdampingan "
                "di halaman gabungan bahan baku.", label, len(pages),
            )
        usable.append((label, pages))

    if not usable:
        return None

    labels = [label for label, _ in usable]
    box_heights, box_tops = _layout(len(usable))
    if len(labels) == 2:
        subtitle = "Spesifikasi dan Catatan Pemeriksaan Bahan Baku"
    else:
        subtitle = labels[0].capitalize()

    writer = PdfWriter()
    page = _new_a4_page(writer)
    inner_width = PAGE_WIDTH - 2 * PAGE_MARGIN
    _draw_page_header(page, material_name or "Bahan Baku", subtitle)

    for label, height, top in zip(labels, box_heights, box_tops):
        box_top_pt = top + LABEL_HEIGHT
        box_bottom_pt = box_top_pt + height
        _draw_text(page, label, PAGE_MARGIN, PAGE_HEIGHT - box_top_pt + 5, 9, bold=True)
        _draw_hline(page, PAGE_MARGIN, PAGE_HEIGHT - box_top_pt, PAGE_WIDTH - PAGE_MARGIN)
        _draw_hline(page, PAGE_MARGIN, PAGE_HEIGHT - box_bottom_pt, PAGE_WIDTH - PAGE_MARGIN)

    for (label, pages), height, top in zip(usable, box_heights, box_tops):
        box_top_pt = top + LABEL_HEIGHT
        column_width = inner_width / len(pages)
        for index, source in enumerate(pages):
            left = PAGE_MARGIN + index * column_width
            try:
                _paste(page, source, left, box_top_pt, column_width, height)
            except Exception as exc:
                logger.warning("[BAB II] Gagal menempel PDF %s ke halaman komposisi: %s", label, exc)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def build_coa_section(entries: list[tuple[str, bytes]]) -> bytes | None:
    """Section COA: satu blok berurutan, tiap COA diberi header nama bahan baku.

    ``entries`` = list ``(nama_bahan_baku, coa_pdf_bytes)``. Isi PDF COA asli
    tidak diubah, hanya diskalakan proporsional agar muat di bawah header.
    Return ``None`` kalau tidak ada satu pun COA valid.
    """
    writer = PdfWriter()
    inner_width = PAGE_WIDTH - 2 * PAGE_MARGIN
    written = 0
    for material_name, coa_bytes in entries:
        pages = read_pdf_pages(coa_bytes, f"CoA {material_name}")
        if not pages:
            logger.warning("[BAB II] CoA bahan baku %s tidak valid, dilewati", material_name)
            continue
        for index, source in enumerate(pages):
            page = _new_a4_page(writer)
            subtitle = "COA (Certificate of Analysis)"
            if index > 0:
                subtitle += " - lanjutan"
            _draw_page_header(page, f"COA - {material_name}", subtitle)
            try:
                _paste(page, source, PAGE_MARGIN, HEADER_HEIGHT, inner_width,
                       PAGE_HEIGHT - PAGE_MARGIN - HEADER_HEIGHT)
            except Exception as exc:
                logger.warning("[BAB II] Gagal menempel CoA bahan baku %s: %s", material_name, exc)
                continue
            written += 1
    if not written:
        return None
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def build_missing_list_page(heading: str, material_names: list[str]) -> bytes | None:
    """Halaman daftar bahan baku yang dokumennya belum tersedia (1 daftar per halaman)."""
    if not material_names:
        return None
    rows = "".join(
        f"<tr><td style='width: 30pt;'>{index}</td><td>{_escape_html(name)}</td></tr>"
        for index, name in enumerate(material_names, start=1)
    )
    html = (
        "<!DOCTYPE html><html><head><meta charset='UTF-8'><style>"
        "body { font-family: Helvetica, sans-serif; font-size: 10pt; color: #1a1a1a; }"
        "h2 { font-size: 12pt; margin: 0 0 8pt 0; }"
        "table { width: 100%; }"
        "td { border: 0.6pt solid #999; padding: 5pt 7pt; font-size: 9.5pt; }"
        "</style></head><body>"
        f"<h2>{_escape_html(heading)}</h2>"
        f"<table>{rows}</table>"
        "</body></html>"
    )
    return render_html_to_pdf(html)


def _escape_html(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
