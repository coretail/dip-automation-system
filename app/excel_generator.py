"""
Generator file Excel (.xlsx) untuk dokumen Formula Kualitatif & Kuantitatif.

Modul ini menggantikan export client-side berbasis SheetJS. Format sheet formula
diikuti dokumen acuan di `excel-example/` (pemetaan sheet):
    sheet acuan "Formula"   -> sheet aplikasi "Formula INCI Murni"
    sheet acuan "Formula 2" -> sheet aplikasi "Formula Nama Dagang"

Gaya umum (kedua sheet formula):
  - Kolom A dibiarkan sebagai margin kiri; seluruh tabel mulai di kolom B.
  - Kop surat (gambar) di B1, judul di baris 7, blok info baris 9-15,
    header tabel baris 18.
  - Judul, blok info, baris Total, dan tanda tangan memakai Arial; isi tabel
    memakai Trebuchet MS 11.
  - Label info ditulis di kolom B dan diratakan dengan padding, nilai di kolom C
    berawalan ": ".
  - Header tabel: Arial 12 bold, fill biru muda (resolusi warna tema "Accent 1"
    lighten 80%), center, border tipis atas/kiri/kanan tanpa bawah.
  - Baris data: border tipis lengkap, kolom % berformat 0.0000 dan center.
  - Bahan aktif ditandai kuning, mengikuti dokumen acuan.
  - Baris Total memakai formula =SUM(...) (bukan angka statis) berformat 0.000.
  - Tanda tangan: nama jabatan (Registration / R&D) diberi garis bawah tipis.

Perbedaan antar sheet mengikuti dokumen acuan:
  - "Formula INCI Murni" (3 kolom): ada 1 baris kosong setelah header, label
    Total bernada "Total :", dan blok tanda tangan TANPA baris label
    "Disusun Oleh / Diketahui Oleh".
  - "Formula Nama Dagang" (4 kolom: Nama Dagang | Ingredients | Function |
    % w/w): data langsung setelah header, label Total "Total", baris label
    tanda tangan disertakan, serta subtotal =SUM() di kolom F untuk setiap nama
    dagang yang punya lebih dari satu komponen.
  - Lebar kolom mengikuti acuan, kecuali kolom INCI yang hanya boleh lebih
    lebar (tidak pernah lebih sempit) agar nama INCI panjang tidak terpotong.

Sheet "Text Design" tetap tanpa kop surat dan tanpa blok tanda tangan.

Dipakai oleh route:
    GET /products/{product_id}/qualitative-quantitative/export-xlsx
"""

import io
import os

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ==================== KONSTANTA STYLING ====================
# Format angka mengikuti dokumen acuan: data 4 desimal, baris Total 3 desimal.
PCT_NUMBER_FORMAT = "0.0000"
PCT_TOTAL_FORMAT = "0.000"
COL_WIDTH_MIN = 15.0           # auto-fit: lebar minimum kolom
COL_WIDTH_MAX = 50.0           # auto-fit: lebar maksimum kolom
COL_WIDTH_PADDING = 2.0        # padding ditambahkan ke panjang teks terpanjang

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Warna header tabel berbeda per perusahaan:
#   - PT Erfi -> peach (#FFCC99)
#   - PT Heka -> biru muda (#DCE6F1), hasil resolusi tema Excel "Accent 1"
#     lighten 80% sesuai dokumen acuan. TIDAK diubah.
HEADER_FILL_ERFI = PatternFill("solid", fgColor="FFCC99")
HEADER_FILL_HEKA = PatternFill("solid", fgColor="DCE6F1")
HEADER_FILL = HEADER_FILL_HEKA          # alias: dipakai kalau perusahaan tak terdeteksi
TOTAL_FILL = PatternFill("solid", fgColor="DCE6F1")
NOTE_FILL = PatternFill("solid", fgColor="FEF9C3")
# Baris bahan aktif ditandai kuning (mengikuti dokumen acuan)
ACTIVE_FILL = PatternFill("solid", fgColor="FFFF00")

# Border dokumen acuan memakai garis TIPIS hitam (bukan medium abu-abu).
_SIDE_THIN = Side(style="thin", color="000000")
BORDER_THIN = Border(left=_SIDE_THIN, right=_SIDE_THIN,
                     top=_SIDE_THIN, bottom=_SIDE_THIN)
# Baris header: atas + kiri + kanan, TANPA garis bawah (mengikuti acuan).
BORDER_HEADER = Border(left=_SIDE_THIN, right=_SIDE_THIN, top=_SIDE_THIN)
# Baris Total sheet "Formula INCI Murni": garis atas, tanpa bawah.
BORDER_TOTAL_TOP = Border(left=_SIDE_THIN, right=_SIDE_THIN, top=_SIDE_THIN)
# Baris Total sheet "Formula Nama Dagang": garis bawah, tanpa atas
# (garis pemisah datang dari border bawah baris data terakhir).
BORDER_TOTAL_BOTTOM = Border(left=_SIDE_THIN, right=_SIDE_THIN, bottom=_SIDE_THIN)

# Font: judul, blok info, Total, dan tanda tangan memakai Arial;
# isi tabel memakai Trebuchet MS (mengikuti dokumen acuan).
FONT_NORMAL = Font(name="Trebuchet MS", size=11)
FONT_BOLD = Font(name="Trebuchet MS", size=11, bold=True)
FONT_TITLE = Font(name="Arial", size=12, bold=True)
FONT_INFO = Font(name="Arial", size=12, bold=True)
FONT_TOTAL = Font(name="Arial", size=12, bold=True)
FONT_SIGN = Font(name="Arial", size=11)
# Font khusus fallback letterhead (teks, tanpa gambar kop):
_FONT_LETTERHEAD_FALLBACK = Font(name="Trebuchet MS", size=14, bold=True)

ALIGN_LEFT_CENTER_WRAP = Alignment(horizontal="left", vertical="center", wrap_text=True)
ALIGN_LEFT_CENTER = Alignment(horizontal="left", vertical="center")
ALIGN_LEFT_TOP_WRAP = Alignment(horizontal="left", vertical="top", wrap_text=True)
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_CENTER_WRAP = Alignment(horizontal="center", vertical="center", wrap_text=True)
ALIGN_CENTER_TOP_WRAP = Alignment(horizontal="center", vertical="top", wrap_text=True)
ALIGN_RIGHT = Alignment(horizontal="right", vertical="top")

# ==================== KONSTANTA LAYOUT (mengikuti dokumen acuan) ====================
# Kolom A sengaja dibiarkan sebagai margin kiri; seluruh tabel mulai di kolom B.
REF_COL_A_WIDTH = 13.0
REF_TITLE_ROW = 7
REF_INFO_ROW = 9
REF_HEADER_ROW = 18
# Lebar kolom tetap sesuai dokumen acuan (kolom INCI diberi pengaman minimum).
REF_WIDTHS_PURE = {2: 43.141, 3: 21.711, 4: 21.0}
REF_WIDTHS_TRADE = {2: 26.0, 3: 43.711, 4: 21.855, 5: 16.57, 6: 15.711}
REF_MIN_INCI_WIDTH = 30.0
REF_ROW_HEIGHT_DATA_PURE = 15.75
REF_ROW_HEIGHT_DATA_TRADE = 16.5
REF_ZOOM = 90

# Lebar gambar kop (px) dan jumlah baris yang dipakai untuk kop surat.
KOP_WIDTH_PX = 470
LETTERHEAD_ROWS = 6
LETTERHEAD_ROW_HEIGHT = 16.5
LETTERHEAD_MAX_PT = LETTERHEAD_ROWS * LETTERHEAD_ROW_HEIGHT

# Baris info produk (label di B, "nilai" di C) - mengikuti dokumen acuan.
REF_INFO_FIELDS = [
    ("Nama Produk", "nama_produk"),
    ("Warna", "warna"),
    ("Sediaan", "sediaan"),
    ("Kemasan", "kemasan"),
    ("Netto", "netto"),
    ("Nama Customer", "nama_customer"),
    ("Tanggal Acc Sampel", "acc_sampel"),
]



# ==================== HELPER UTILITAS ====================
def _has_value(value) -> bool:
    """True hanya bila value berisi teks nyata (bukan None / kosong / '-')."""
    if value is None:
        return False
    return str(value).strip() not in ("", "-")


def _dash(value) -> str:
    """Normalisasi value jadi string tampilan; None/kosong -> '-'."""
    text = "" if value is None else str(value).strip()
    return text if text else "-"


def _fmt_date(value) -> str:
    """Format tanggal YYYY-MM-DD -> DD-MM-YYYY (fallback: nilai apa adanya)."""
    if not value:
        return "-"
    text = str(value)
    try:
        from datetime import datetime
        dt = datetime.strptime(text[:10], "%Y-%m-%d")
        return dt.strftime("%d-%m-%Y")
    except Exception:
        return text


def _set_merged(ws, cell_range: str, value, font=None, align=None):
    """Merge range lalu set value/style pada sel anchor-nya."""
    ws.merge_cells(cell_range)
    anchor = ws[cell_range.split(":")[0]]
    anchor.value = value
    anchor.font = font or FONT_NORMAL
    if align:
        anchor.alignment = align
    return anchor


def _border_range(ws, row_start: int, row_end: int, col_start: int, col_end: int,
                  border: Border = BORDER_THIN):
    """Terapkan border pada SELURUH sel dalam rentang (termasuk sel di bawah merge)."""
    for row in range(row_start, row_end + 1):
        for col in range(col_start, col_end + 1):
            ws.cell(row=row, column=col).border = border


def _fill_range(ws, row: int, col_start: int, col_end: int, fill: PatternFill):
    for col in range(col_start, col_end + 1):
        ws.cell(row=row, column=col).fill = fill


def _auto_fit_columns(ws, min_col: int = 1, max_col: int = 5):
    """Auto-fit lebar kolom dari isi teks terpanjang + padding (clamp min-max).

    Sel yang menjadi bagian merged range dilewati (nilainya merentang banyak
    kolom sehingga tidak adil dijadikan patokan lebar satu kolom).
    """
    merged_spans = [(r.min_row, r.max_row, r.min_col, r.max_col)
                    for r in ws.merged_cells.ranges]
    longest = {}
    for row in ws.iter_rows(min_col=min_col, max_col=max_col):
        for cell in row:
            if cell.value is None:
                continue
            in_merge = any(mr0 <= cell.row <= mr1 and mc0 <= cell.column <= mc1
                           for mr0, mr1, mc0, mc1 in merged_spans)
            if in_merge:
                continue
            text_longest = max((len(line) for line in str(cell.value).split("\n")),
                               default=0)
            longest[cell.column] = max(longest.get(cell.column, 0), text_longest)
    for col in range(min_col, max_col + 1):
        width = min(max(longest.get(col, 0) + COL_WIDTH_PADDING, COL_WIDTH_MIN),
                    COL_WIDTH_MAX)
        ws.column_dimensions[get_column_letter(col)].width = width


def _static_fs_path(uri: str) -> str | None:
    """Map URI `/static/...` ke path file lokal. None kalau tidak ada."""
    uri = (uri or "").strip()
    if not uri.startswith("/static/"):
        return None
    candidates = [
        os.path.join("app", uri.lstrip("/").replace("/", os.sep)),
        os.path.join(os.path.dirname(__file__), uri[len("/static/"):].replace("/", os.sep)),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _is_pt_heka(product: dict, company: dict) -> bool:
    """True kalau produk ini milik PT Heka.

    PENTING: nama resmi PT Heka adalah "PT. HARAKA ERFI KOSMETINDO ABADI" — kata
    "ERFI" ikut TERHANTAM di dalamnya. Jadi deteksi "heka"/"haraka" WAJIB dicek
    lebih dulu; kalau urutannya dibalik, PT Heka ikut dapat warna PT Erfi.
    """
    for src in (product or {}, company or {}):
        if not isinstance(src, dict):
            continue
        for field in ("perusahaan", "nama", "logo", "kop"):
            value = str(src.get(field) or "").lower()
            if "heka" in value or "haraka" in value:
                return True
    return False


def _header_fill_for(product: dict, company: dict) -> PatternFill:
    """Warna header tabel sesuai perusahaan produk."""
    return HEADER_FILL_HEKA if _is_pt_heka(product, company) else HEADER_FILL_ERFI


def _kop_fs_path(company: dict) -> str | None:
    """Path gambar kop surat (kop_erfi / kop_heka)."""
    company = company or {}
    uri = (company.get("kop") or "").strip()
    if not uri:
        logo = (company.get("logo") or "").lower()
        nama = (company.get("nama") or "").lower()
        if "heka" in logo or "haraka" in nama:
            uri = "/static/images/kop_heka.png"
        elif "erfi" in logo or "erfi" in nama:
            uri = "/static/images/kop_erfi.png"
    return _static_fs_path(uri)


def _letterhead(ws, company: dict, last_col: str = "E"):
    """Kop surat: gambar kop di B1, menempati baris 1 s/d LETTERHEAD_ROWS.

    Tidak menulis nama/alamat/email terpisah — sudah ada di file kop.
    Kalau file kop hilang, fallback ke teks (tanpa gambar).
    """
    path = _kop_fs_path(company)
    if path:
        try:
            img = XLImage(path)
            orig_w, orig_h = img.width, img.height
            if orig_w and orig_h:
                img.width = KOP_WIDTH_PX
                img.height = max(1, round(orig_h * KOP_WIDTH_PX / orig_w))
                # Batasi tinggi supaya judul di baris REF_TITLE_ROW tidak terdorong.
                max_px = LETTERHEAD_MAX_PT * 96 / 72
                if img.height > max_px:
                    img.width = max(1, round(img.width * max_px / img.height))
                    img.height = round(max_px)
            img.anchor = "B1"
            ws.add_image(img)
            per_row = LETTERHEAD_ROW_HEIGHT
            for r in range(1, LETTERHEAD_ROWS + 1):
                ws.row_dimensions[r].height = per_row
            return
        except Exception as e:
            print(f"[EXCEL] Gagal embed kop {path}: {e}")

    left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)
    _set_merged(ws, f"B1:{last_col}1", _dash(company.get("nama")),
                font=_FONT_LETTERHEAD_FALLBACK, align=left_align)
    _set_merged(ws, f"B2:{last_col}2", _dash(company.get("alamat")), align=left_align)
    contact = f"Email: {_dash(company.get('email'))} | Website: {_dash(company.get('website'))}"
    _set_merged(ws, f"B3:{last_col}3", contact, align=left_align)
    for r in range(1, LETTERHEAD_ROWS + 1):
        ws.row_dimensions[r].height = LETTERHEAD_ROW_HEIGHT


def _info_block(ws, start_row: int, pairs, value_col: int = 3) -> int:
    """Blok info produk sesuai dokumen acuan: label di kolom B, "nilai" di kolom C.

    Label diratakan lebarnya dengan padding spasi agar titik dua (":") selalu
    sejajar antarbaris. Return nomor baris SETELAH blok selesai.
    """
    pad = max((len(label) for label, _ in pairs), default=0)
    row = start_row
    for label, value in pairs:
        label_cell = ws.cell(row=row, column=2, value=f"{label:<{pad}}")
        label_cell.font = FONT_INFO
        label_cell.alignment = ALIGN_LEFT_CENTER
        value_cell = ws.cell(row=row, column=value_col, value=f": {_dash(value)}")
        value_cell.font = FONT_INFO
        value_cell.alignment = ALIGN_LEFT_CENTER_WRAP
        ws.row_dimensions[row].height = LETTERHEAD_ROW_HEIGHT
        row += 1
    return row


def _table_header(ws, row: int, headers, first_col: int = 2, fill: PatternFill = None):
    """Baris header tabel: Arial 12 bold + fill sesuai perusahaan + center + border
    tipis (atas/kiri/kanan, tanpa bawah — mengikuti dokumen acuan)."""
    fill = fill or HEADER_FILL
    for offset, title in enumerate(headers):
        cell = ws.cell(row=row, column=first_col + offset, value=title)
        cell.font = FONT_TITLE
        cell.fill = fill
        cell.alignment = ALIGN_CENTER_WRAP
        cell.border = BORDER_HEADER
        ws.row_dimensions[row].height = LETTERHEAD_ROW_HEIGHT
    return row + 1


def _signature_block(ws, label_row: int, left_col: str, right_col: str,
                     with_labels: bool):
    """Blok tanda tangan sesuai dokumen acuan.

    - label_row: baris "Disusun Oleh :" / "Diketahui Oleh :"
      (hanya dipakai sheet "Formula Nama Dagang"; sheet "Formula INCI Murni"
       pada dokumen acuan tidak memakai baris label ini).
    - label_row + 3: baris nama jabatan dengan garis bawah tipis.
    """
    left = ws[f"{left_col}{label_row}"]
    right = ws[f"{right_col}{label_row}"]
    if with_labels:
        left.value = "Disusun Oleh :"
        right.value = "Diketahui Oleh :"
        left.alignment = ALIGN_LEFT_CENTER
        right.alignment = ALIGN_CENTER
    left.font = FONT_SIGN
    right.font = FONT_SIGN

    name_row = label_row + 3
    ws[f"{left_col}{name_row}"] = "Registration"
    ws[f"{right_col}{name_row}"] = "R&D"
    for coord, align in ((f"{left_col}{name_row}", ALIGN_LEFT_CENTER),
                         (f"{right_col}{name_row}", ALIGN_CENTER)):
        cell = ws[coord]
        cell.font = FONT_SIGN
        cell.alignment = align
        cell.border = Border(bottom=_SIDE_THIN)
    for r in (label_row, label_row + 1, label_row + 2, name_row):
        ws.row_dimensions[r].height = LETTERHEAD_ROW_HEIGHT


def _page_setup(ws, landscape: bool = False):
    """Pengaturan cetak & tampilan sheet sesuai dokumen acuan."""
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    ws.page_setup.paperSize = 9  # A4
    ws.page_margins.left = 0.7
    ws.page_margins.right = 0.7
    ws.page_margins.top = 0.75
    ws.page_margins.bottom = 0.75
    ws.page_margins.header = 0.3
    ws.page_margins.footer = 0.3
    ws.sheet_view.zoomScale = REF_ZOOM


def _apply_widths(ws, widths: dict, inci_col: int, components: list):
    """Terapkan lebar kolom tetap sesuai acuan.

    Kolom INCI hanya boleh lebih LEBAR dari nilai acuan (bukan lebih sempit)
    supaya nama INCI panjang tidak terpotong.
    """
    longest_inci = max((len(str(c.get("inci_name") or "")) for c in components), default=0)
    inci_width = max(widths.get(inci_col, REF_MIN_INCI_WIDTH),
                     longest_inci + COL_WIDTH_PADDING, REF_MIN_INCI_WIDTH)
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = (
            inci_width if col == inci_col else width
        )
    ws.column_dimensions["A"].width = REF_COL_A_WIDTH


# ==================== SHEET BUILDERS ====================
def _formula_info_pairs(product: dict):
    """Pasangan (label, nilai) untuk blok info produk, sama di kedua sheet formula."""
    pairs = []
    for label, field in REF_INFO_FIELDS:
        value = _fmt_date(product.get(field)) if field == "acc_sampel" else product.get(field)
        pairs.append((label, value))
    return pairs


def _sheet_formula_trade(wb: Workbook, product: dict, trade_breakdown: list, company: dict):
    """Sheet 1 'Formula Nama Dagang': Nama Dagang | Ingredients | Function | % w/w.

    Mengikuti sheet "Formula 2" pada dokumen acuan: tabel mulai di kolom B,
    baris Total memakai formula =SUM(), dan tiap nama dagang yang punya lebih
    dari satu komponen mendapat subtotal di kolom F.
    """
    ws = wb.active
    ws.title = "Formula Nama Dagang"

    _letterhead(ws, company, last_col="E")

    # Judul di baris 7, tabel di baris 18 (mengikuti dokumen acuan)
    _set_merged(ws, f"B{REF_TITLE_ROW}:E{REF_TITLE_ROW}", "FORMULA KUALITATIF & KUANTITATIF",
                font=FONT_TITLE, align=ALIGN_CENTER)
    ws.row_dimensions[REF_TITLE_ROW].height = LETTERHEAD_ROW_HEIGHT

    _info_block(ws, REF_INFO_ROW, _formula_info_pairs(product), value_col=3)

    data_start = _table_header(ws, REF_HEADER_ROW,
                               ["Nama Dagang", "Ingredients", "Function", "% w/w"],
                               fill=_header_fill_for(product, company))

    row = data_start
    for group in trade_breakdown:
        components = group.get("components") or []
        group_first_row = row
        for comp in components:
            inci_cell = ws.cell(row=row, column=3, value=_dash(comp.get("inci_name")))
            inci_cell.font = FONT_NORMAL
            inci_cell.alignment = ALIGN_LEFT_CENTER_WRAP

            func_cell = ws.cell(row=row, column=4, value=_dash(comp.get("function")))
            func_cell.font = FONT_NORMAL
            func_cell.alignment = ALIGN_CENTER

            pct_cell = ws.cell(row=row, column=5, value=float(comp.get("pct_ww") or 0))
            pct_cell.font = FONT_NORMAL
            pct_cell.number_format = PCT_NUMBER_FORMAT
            pct_cell.alignment = ALIGN_CENTER

            # Bahan aktif ditandai kuning (mengikuti dokumen acuan)
            if comp.get("is_bahan_aktif"):
                for col in (3, 4, 5):
                    ws.cell(row=row, column=col).fill = ACTIVE_FILL

            ws.row_dimensions[row].height = REF_ROW_HEIGHT_DATA_TRADE
            row += 1

        group_last_row = max(group_first_row, row - 1)
        if group_last_row > group_first_row:
            # Nama Dagang di-merge vertikal; subtotal komponen di kolom F
            ws.merge_cells(start_row=group_first_row, end_row=group_last_row,
                           start_column=2, end_column=2)
            subtotal = ws.cell(row=group_first_row, column=6,
                               value=f"=SUM(E{group_first_row}:E{group_last_row})")
            subtotal.number_format = PCT_TOTAL_FORMAT
            subtotal.alignment = ALIGN_CENTER
        dagang_cell = ws.cell(row=group_first_row, column=2, value=_dash(group.get("nama_dagang")))
        dagang_cell.font = FONT_NORMAL
        dagang_cell.alignment = ALIGN_LEFT_CENTER_WRAP

    data_last_row = max(data_start, row - 1)
    _border_range(ws, data_start, data_last_row, 2, 5)

    # ---- Baris Total: formula =SUM, bukan angka statis ----
    total_row = data_last_row + 1
    _set_merged(ws, f"B{total_row}:D{total_row}", "Total",
                font=FONT_TOTAL, align=ALIGN_CENTER)
    total_pct = ws.cell(row=total_row, column=5,
                        value=f"=SUM(E{data_start}:E{data_last_row})")
    total_pct.number_format = PCT_TOTAL_FORMAT
    total_pct.font = FONT_TOTAL
    total_pct.alignment = ALIGN_CENTER
    _border_range(ws, total_row, total_row, 2, 5, border=BORDER_TOTAL_BOTTOM)
    _fill_range(ws, total_row, 2, 5, TOTAL_FILL)
    ws.row_dimensions[total_row].height = REF_ROW_HEIGHT_DATA_TRADE

    # ---- Tanda tangan: label di baris Total+1, nama jabatan 3 baris di bawah ----
    _signature_block(ws, total_row + 1, "B", "E", with_labels=True)

    flat_components = [c for g in trade_breakdown for c in (g.get("components") or [])]
    _apply_widths(ws, REF_WIDTHS_TRADE, 3, flat_components)
    _page_setup(ws)


def _sheet_formula_pure(wb: Workbook, product: dict, pure_breakdown: list, company: dict):
    """Sheet 2 'Formula INCI Murni': Ingredients | Function | % w/w.

    Mengikuti sheet "Formula" pada dokumen acuan: satu baris kosong di antara
    header dan data, baris Total memakai formula =SUM(), dan blok tanda tangan
    TANPA baris label "Disusun Oleh / Diketahui Oleh".
    """
    ws = wb.create_sheet("Formula INCI Murni")

    _letterhead(ws, company, last_col="D")

    _set_merged(ws, f"B{REF_TITLE_ROW}:D{REF_TITLE_ROW}", "FORMULA KUALITATIF & KUANTITATIF",
                font=FONT_TITLE, align=ALIGN_CENTER)
    ws.row_dimensions[REF_TITLE_ROW].height = LETTERHEAD_ROW_HEIGHT

    _info_block(ws, REF_INFO_ROW, _formula_info_pairs(product), value_col=3)

    data_start = _table_header(ws, REF_HEADER_ROW,
                               ["Ingredients", "Function", "% w/w"],
                               fill=_header_fill_for(product, company)) + 1  # +1 = 1 baris kosong

    row = data_start
    for comp in pure_breakdown:
        inci_cell = ws.cell(row=row, column=2, value=_dash(comp.get("inci_name")))
        inci_cell.font = FONT_NORMAL
        inci_cell.alignment = ALIGN_LEFT_CENTER_WRAP

        func_cell = ws.cell(row=row, column=3, value=_dash(comp.get("function")))
        func_cell.font = FONT_NORMAL
        func_cell.alignment = ALIGN_LEFT_CENTER_WRAP

        pct_cell = ws.cell(row=row, column=4, value=float(comp.get("pct_ww") or 0))
        pct_cell.font = FONT_NORMAL
        pct_cell.number_format = PCT_NUMBER_FORMAT
        pct_cell.alignment = ALIGN_CENTER

        if comp.get("is_bahan_aktif"):
            for col in (2, 3, 4):
                ws.cell(row=row, column=col).fill = ACTIVE_FILL

        ws.row_dimensions[row].height = REF_ROW_HEIGHT_DATA_PURE
        row += 1

    data_last_row = max(data_start, row - 1)
    _border_range(ws, data_start, data_last_row, 2, 4)

    # ---- Baris Total: label "Total :" (mengikuti sheet acuan "Formula") ----
    total_row = data_last_row + 1
    _set_merged(ws, f"B{total_row}:C{total_row}", "Total :",
                font=FONT_SIGN, align=ALIGN_LEFT_CENTER)
    total_pct = ws.cell(row=total_row, column=4,
                        value=f"=SUM(D{data_start - 1}:D{data_last_row})")
    total_pct.number_format = PCT_TOTAL_FORMAT
    total_pct.font = FONT_SIGN
    total_pct.alignment = ALIGN_CENTER
    _border_range(ws, total_row, total_row, 2, 4, border=BORDER_TOTAL_TOP)
    _fill_range(ws, total_row, 2, 4, TOTAL_FILL)
    ws.row_dimensions[total_row].height = LETTERHEAD_ROW_HEIGHT

    # ---- Tanda tangan tanpa baris label (mengikuti sheet acuan "Formula") ----
    _signature_block(ws, total_row + 1, "B", "D", with_labels=False)

    _apply_widths(ws, REF_WIDTHS_PURE, 2, pure_breakdown)
    _page_setup(ws)


# ==================== TEXT DESIGN ====================
# Struktur sheet "Text Design" mengikuti dokumen acuan
# excel-example/Text Design  Pherini Breast Serum 07032025.xlsx:
#   label di kolom A:B, tanda titik dua di kolom C, nilai di kolom D:J.
TD_LABEL_END_COL = 2      # label_merge A:B
TD_COLON_COL = 3          # kolom C = ":"
TD_VALUE_START_COL = 4    # nilai mulai kolom D
TD_LAST_COL = 10          # kolom J
TD_COL_WIDTHS = {3: 4.71, 4: 11.43, 5: 10.29, 6: 10.57,
                 7: 12.0, 8: 12.86, 9: 18.29, 10: 22.86}
TD_ROW_HEIGHT = 15.0
# Kotak keterangan tambahan: kuning polos + bold + center (sama acuan).
TD_NOTE_FILL = PatternFill("solid", fgColor="FFFF00")

FONT_TD = Font(name="Calibri", size=11)
FONT_TD_BOLD = Font(name="Calibri", size=11, bold=True)
FONT_TD_NA = Font(name="Arial", size=11, color="FF333333")

ALIGN_TD_LABEL = Alignment(horizontal="left", vertical="center")
ALIGN_TD_LABEL_WRAP = Alignment(horizontal="left", vertical="center", wrap_text=True)
ALIGN_TD_GENERAL = Alignment(horizontal="left", vertical="center")
ALIGN_TD_LEFT_WRAP = Alignment(horizontal="left", vertical="center", wrap_text=True)
ALIGN_TD_JUSTIFY_WRAP = Alignment(horizontal="justify", vertical="center", wrap_text=True)
ALIGN_TD_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_TD_CENTER_WRAP = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _td_address_lines(company: dict) -> list[str]:
    """Baris nilai untuk blok "Diproduksi Oleh" (kondisional per perusahaan).

    Sumbernya dict ``company`` = ``COMPANY_INFO[produk.perusahaan]`` dari main.py,
    sehingga PT Erfi dan PT Heka otomatis memakai data masing-masing:

      * ``nama``        -> baris nama perusahaan
      * ``alamat_teks`` -> bila diisi, dipakai apa adanya; "\\n" memecah baris
      * ``alamat``      -> fallback: awalan "Office :" dibuang, lalu dipecah 2 baris
      * ``hp_alamat``   -> bila diisi, menambah baris "Hp. <nomor>" (ada di kop PT Heka)
    """
    company = company or {}
    lines = [_dash(company.get("nama"))]

    raw = str(company.get("alamat_teks") or "").strip()
    if raw:
        lines += [p.strip() for p in raw.split("\n") if p.strip()]
    else:
        alamat = str(company.get("alamat") or "").strip()
        for prefix in ("Office :", "Office:", "Office"):
            if alamat.lower().startswith(prefix.lower()):
                alamat = alamat[len(prefix):].strip(" :")
                break
        parts = [p.strip() for p in alamat.split(",") if p.strip()]
        if len(parts) <= 1:
            lines += parts
        else:
            half = (len(parts) + 1) // 2
            lines += [", ".join(parts[:half]), ", ".join(parts[half:])]

    hp = str(company.get("hp_alamat") or "").strip()
    if hp:
        lines.append(f"Hp. {hp}")
    return lines


def _td_write_block(ws, row: int, label: str, value_lines, nrows: int,
                    value_font=None, value_align=None) -> int:
    """Tulis satu blok Text Design: label A:B, titik dua C, nilai D:J.

    ``value_lines`` berisi >1 baris -> tiap baris dapat sel D:J sendiri (stacked,
    dipakai untuk "Diproduksi Oleh"). Berisi 1 baris -> satu sel D:J di-merge
    lintas ``nrows`` (dipakai untuk teks panjang). Return baris berikutnya.

    Sesuai acuan: kolom label (A:B) dan titik dua (C) SELALU Calibri 11 reguler;
    gaya khusus (mis. bold atau Arial) hanya berlaku pada kolom nilai (D:J).
    """
    value_lines = list(value_lines) or ["-"]
    last_row = row + nrows - 1
    value_font = value_font or FONT_TD
    # value_align=None -> biarkan alignment default sel (sesuai acuan untuk
    # kolom nilai 1 baris); blok multi-baris/teks panjang menetapkannya eksplisit.
    # Label 1 baris -> align default; label multi-baris -> kiri + center + wrap.
    label_align = ALIGN_TD_LABEL_WRAP if nrows > 1 else None
    colon_align = ALIGN_TD_LABEL if nrows > 1 else None

    _set_merged(ws, f"A{row}:B{last_row}", label, font=FONT_TD, align=label_align)
    # Kolom C: di-merge hanya bila label-nya multi-baris. Pada blok 1 baris,
    # acuan memakai sel biasa (tidak di-merge) -- ini yang membuat daftar merge
    # hasil generate identik dengan berkas acuan.
    if nrows > 1:
        _set_merged(ws, f"C{row}:C{last_row}", ":", font=FONT_TD, align=colon_align)
    else:
        colon = ws.cell(row=row, column=TD_COLON_COL, value=":")
        colon.font = FONT_TD

    if len(value_lines) <= 1:
        _set_merged(ws, f"D{row}:J{last_row}", value_lines[0],
                    font=value_font, align=value_align)
    else:
        for offset, line in enumerate(value_lines):
            _set_merged(ws, f"D{row + offset}:J{row + offset}", line,
                        font=value_font, align=value_align)

    _border_range(ws, row, last_row, 1, TD_LAST_COL)
    for r in range(row, last_row + 1):
        ws.row_dimensions[r].height = TD_ROW_HEIGHT
    return last_row + 1


def _sheet_text_design(wb: Workbook, product: dict, pure_breakdown: list, company: dict):
    """Sheet 3 'Text Design': informasi label/kemasan (Komposisi, Teks, Cara Pakai).

    Struktur & visual mengikuti dokumen acuan
    "excel-example/Text Design  Pherini Breast Serum 07032025.xlsx":
      - tanpa judul sheet; baris 1 = Tanggal (tanpa border)
      - label di A:B, titik dua di C, nilai di D:J
      - teks panjang satu sel D:J di-merge lintas beberapa baris + wrap
      - "Diproduksi Oleh" memakai beberapa baris nilai terpisah (stacked)
      - kotak keterangan tambahan kuning polos, bold, center
    """
    ws = wb.create_sheet("Text Design")

    # Lebar kolom tetap (mengikuti acuan); A & B dibiarkan default.
    for col, width in TD_COL_WIDTHS.items():
        ws.column_dimensions[get_column_letter(col)].width = width

    # --- Baris 1: Tanggal (tanpa border, sesuai acuan) ---
    ws["A1"] = "Tanggal"
    ws["A1"].font = FONT_TD
    ws["A1"].alignment = ALIGN_TD_LABEL
    ws.cell(row=1, column=TD_COLON_COL, value=f": {_fmt_date(product.get('tanggal_text_design'))}")
    ws.cell(row=1, column=TD_COLON_COL).font = FONT_TD

    komposisi = ", ".join(str(c.get("inci_name")) for c in pure_breakdown if c.get("inci_name"))
    komposisi = (komposisi + ".") if komposisi else "-"

    # Blok: (label, baris_nilai, jumlah_baris, font_nilai, align_nilai)
    # Jumlah baris mengikuti acuan; blok teks panjang di-merge lintas baris.
    blocks = [
        ("Nama Produk", [_dash(product.get("nama_produk"))], 1,
         FONT_TD_BOLD, None),
        ("Netto", [_dash(product.get("netto"))], 1, FONT_TD, None),
        ("No NA", [_dash(product.get("no_na_produk"))], 1,
         FONT_TD_NA, None),
        # Kondisional per perusahaan: jumlah baris mengikuti isi COMPANY_INFO
        # (PT Erfi 3 baris, PT Heka 4 baris karena kopnya ada nomor Hp).
        ("Diproduksi Oleh", _td_address_lines(company), 0, FONT_TD, ALIGN_TD_LEFT_WRAP),
        ("Komposisi", [komposisi], 5, FONT_TD, ALIGN_TD_LEFT_WRAP),
        ("Teks", [_dash(product.get("teks_marketing"))], 6, FONT_TD, ALIGN_TD_JUSTIFY_WRAP),
        ("Cara Pakai", [_dash(product.get("cara_pakai"))], 3, FONT_TD, ALIGN_TD_JUSTIFY_WRAP),
    ]
    # Baris kondisional: Peringatan & Penyimpanan hanya ditulis bila datanya
    # benar-benar diisi (bukan None / kosong / '-'), sehingga tinggi blok,
    # merge D:J, dan border menyesuaikan secara dinamis.
    if _has_value(product.get("peringatan")):
        blocks.append(("Peringatan", [_dash(product.get("peringatan"))], 3,
                        FONT_TD, ALIGN_TD_JUSTIFY_WRAP))
    if _has_value(product.get("penyimpanan")):
        blocks.append(("Penyimpanan", [_dash(product.get("penyimpanan"))], 3,
                        FONT_TD, ALIGN_TD_JUSTIFY_WRAP))

    row = 3
    for label, value_lines, nrows, value_font, value_align in blocks:
        if nrows == 0:
            nrows = max(1, len(value_lines))
        row = _td_write_block(ws, row, label, value_lines, nrows,
                              value_font=value_font, value_align=value_align)

    # --- Kotak keterangan tambahan: A:J, kuning polos, bold, center ---
    note_row = row
    _set_merged(ws, f"A{note_row}:J{note_row}",
                "Keterangan tambahan QR BPOM, No Batch dan Exp Date, Netto yg digunakan.",
                font=FONT_TD_BOLD, align=ALIGN_TD_CENTER_WRAP)
    _border_range(ws, note_row, note_row, 1, TD_LAST_COL)
    _fill_range(ws, note_row, 1, TD_LAST_COL, TD_NOTE_FILL)
    ws.row_dimensions[note_row].height = TD_ROW_HEIGHT

    # Sheet "Text Design" TIDAK memakai blok tanda tangan.
    _page_setup(ws, landscape=True)


# ==================== ENTRY POINT ====================
def build_formula_workbook(product: dict, trade_breakdown: list,
                           pure_breakdown: list, company: dict) -> bytes:
    """Bangun workbook .xlsx Formula Kualitatif & Kuantitatif (3 sheet) -> bytes.

    Sheet:
      1. "Formula Nama Dagang"  -- breakdown per nama dagang (+kode bahan baku)
      2. "Formula INCI Murni"   -- agregasi total per INCI (sorted desc %)
      3. "Text Design"          -- informasi label/kemasan utk desain kemasan
    """
    wb = Workbook()
    _sheet_formula_trade(wb, product, trade_breakdown, company)
    _sheet_formula_pure(wb, product, pure_breakdown, company)
    _sheet_text_design(wb, product, pure_breakdown, company)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()