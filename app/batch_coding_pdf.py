"""Generator dokumen "Sistem Pengkodean Batch" (1 halaman PDF) per produk.

Dua format mengikuti PDF referensi (lihat koreksi 2026-11-18):
- PT Erfi : format lama, aturan 1.1.1-1.1.5, nomor batch ``YY MM DD KODE NN``
            (spasi antar kelompok), tanpa digit sediaan, tanpa tabel lampiran.
- PT Heka : format baru, aturan 1.1.1-1.1.6, nomor batch ``YYMMDD`` + ``SS``
            + ``KODE`` + ``NN`` tanpa separator, ada tabel lampiran sediaan 01-12.

Kode produk dan legenda diketik manual oleh pengguna (TIDAK disimpan di DB).
Tanggal contoh diambil dari ``products.tanggal_aktif_na``; bila kosong pakai
fallback 29 November 2023. Nomor urut selalu 01 ("batch pertama").

Hasil diunggah ke bucket ``raw-material-docs`` di key
``products/{product_id}/sistem_penomoran_batch.pdf`` (menimpa generate lama),
lalu URL disimpan di kolom ``products.sistem_penomoran_batch_file_url``
(sama persis jalur upload manual di form edit produk).
"""
from __future__ import annotations

import io
import os
from datetime import date
from typing import Optional

from PIL import Image
from xhtml2pdf import pisa

_STATIC_IMAGES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "images")
_BUCKET = "raw-material-docs"
_PATH_SUFFIX = "sistem_penomoran_batch.pdf"

# Fallback tanggal contoh (keputusan pemilik repo): 29 November 2023.
FALLBACK_DATE = date(2023, 11, 29)

# Tabel lampiran kode sediaan (format Heka). Nilai konstan, tidak berubah.
KODE_SEDIAAN = [
    ("01", "PASTA"),
    ("02", "SABUN PADAT"),
    ("03", "GEL"),
    ("04", "LOTION"),
    ("05", "CREAM"),
    ("06", "SABUN KENTAL"),
    ("07", "MINYAK"),
    ("08", "SALEP"),
    ("09", "SERUM"),
    ("10", "SABUN CAIR"),
    ("11", "TONER"),
    ("12", "LARUTAN/CAIRAN LAIN"),
]

# Nama bulan bahasa Indonesia, hardcoded (tidak bergantung locale server).
_BULAN_ID = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April", 5: "Mei", 6: "Juni",
    7: "Juli", 8: "Agustus", 9: "September", 10: "Oktober", 11: "November",
    12: "Desember",
}

# Batas validasi (lihat koreksi #4).
KODE_PRODUK_MAX_LEN = 6
LEGENDA_MAX_BARIS = 10
LEGENDA_HURUF_MAX_LEN = 3
LEGENDA_ARTI_MAX_LEN = 100


# ==================== FUNGSI MURNI ====================

def is_heka(perusahaan: Optional[str]) -> bool:
    """True kalau produk ini milik PT Heka (deteksi sama dengan pola repo:
    kata "heka"/"haraka" lebih dulu karena nama resmi Heka mengandung "erfi")."""
    name = (perusahaan or "").lower()
    return ("heka" in name or "haraka" in name)


def build_batch_number(tanggal: date, kode_produk: str, perusahaan: Optional[str] = None,
                       kode_sediaan: Optional[str] = None, urut: int = 1) -> str:
    """Nomor batch sesuai format perusahaan.

    - PT Erfi: ``YY MM DD KODE NN`` (spasi antar kelompok), contoh
      ``23 04 03 MPRPDH 01``.
    - PT Heka: ``YYMMDD`` + ``SS`` + ``KODE`` + ``NN`` tanpa separator,
      contoh ``25022205UBEB01``.
    """
    yy = f"{tanggal.year % 100:02d}"
    mm = f"{tanggal.month:02d}"
    dd = f"{tanggal.day:02d}"
    nn = f"{urut:02d}"
    kode = (kode_produk or "").strip().upper()
    if is_heka(perusahaan):
        ss = (kode_sediaan or "00").zfill(2)
        return f"{yy}{mm}{dd}{ss}{kode}{nn}"
    return f"{yy} {mm} {dd} {kode} {nn}"


def terbilang_urut(n: int) -> str:
    """Penomoran batch: 1 -> 'pertama', angka lain -> dua digit."""
    if n == 1:
        return "batch pertama"
    return f"nomor seri batch {n:02d}"


def berarti_lines(nomor_batch: str, tanggal: date, nama_produk: str,
                  perusahaan: Optional[str], kode_sediaan_label: str = "",
                  urut: int = 1) -> list[str]:
    """Baris kalimat "Berarti" per perusahaan.

    - PT Erfi: ``Berarti : <NAMA PRODUK> diproduksi pada <DD Bulan YYYY>``
      + baris kedua ``dengan nomor seri batch <NN>`` (digarisbawahi di PDF).
    - PT Heka: ``Berarti : <NAMA PRODUK> diproduksi pada <DD Bulan YYYY>
      jenis sediaan <label> produk <NAMA> batch pertama``.
    """
    hari_bulan = f"{tanggal.day:02d} {_BULAN_ID[tanggal.month]} {tanggal.year}"
    nama = nama_produk or "-"
    if is_heka(perusahaan):
        label = kode_sediaan_label or "-"
        return [
            f"Berarti : {nama} diproduksi pada {hari_bulan} "
            f"jenis sediaan {label} produk {nama} {terbilang_urut(urut)}",
        ]
    return [
        f"Berarti : {nama} diproduksi pada {hari_bulan}",
        f"dengan nomor seri batch {urut:02d}",
    ]


def validasi_kode_produk(kode: str, perusahaan: Optional[str]) -> Optional[str]:
    """Pesan error (None = valid) untuk kode produk.

    Huruf kapital & angka; panjang PT Erfi 3-6 (aturan 1.1.4 lama),
    PT Heka 4-6 (aturan 1.1.5)."""
    import re
    kode = (kode or "").strip()
    if not kode:
        return "Kode produk wajib diisi."
    if not re.fullmatch(r"[A-Z0-9]+", kode):
        return "Kode produk hanya boleh huruf kapital A-Z dan angka."
    if is_heka(perusahaan):
        lo, hi = 4, KODE_PRODUK_MAX_LEN
    else:
        lo, hi = 3, KODE_PRODUK_MAX_LEN
    if not (lo <= len(kode) <= hi):
        return f"Panjang kode produk harus {lo}-{hi} karakter."
    return None


def validasi_legenda(legenda: list) -> Optional[str]:
    """Validasi daftar legenda ``[{"huruf": str, "arti": str}]``."""
    if not legenda:
        return "Legenda kode (Penjelasan Kode) tidak boleh kosong."
    if len(legenda) > LEGENDA_MAX_BARIS:
        return f"Maksimal {LEGENDA_MAX_BARIS} baris legenda."
    for baris in legenda:
        huruf = str((baris or {}).get("huruf") or "").strip()
        arti = str((baris or {}).get("arti") or "").strip()
        if not huruf:
            return "Setiap baris legenda butuh huruf/kode."
        if len(huruf) > LEGENDA_HURUF_MAX_LEN:
            return f"Huruf legenda maksimal {LEGENDA_HURUF_MAX_LEN} karakter."
        if not arti:
            return f"Legenda '{huruf}' butuh arti."
        if len(arti) > LEGENDA_ARTI_MAX_LEN:
            return f"Arti legenda maksimal {LEGENDA_ARTI_MAX_LEN} karakter."
    return None


def validasi_kode_sediaan(kode: str, perusahaan: Optional[str]) -> Optional[str]:
    """Kode sediaan wajib untuk PT Heka (salah satu 01-12); diabaikan untuk Erfi."""
    if not is_heka(perusahaan):
        return None
    kode = (kode or "").strip()
    if not kode:
        return "Kode sediaan wajib diisi untuk PT Heka."
    if kode not in {c for c, _ in KODE_SEDIAAN}:
        return "Kode sediaan harus salah satu dari 01-12."
    return None


def label_sediaan(kode: Optional[str]) -> str:
    for c, nama in KODE_SEDIAAN:
        if c == (kode or "").strip():
            return nama.lower()
    return ""


def tanggal_untuk_generate(nilai_aktif_na: Optional[str]) -> date:
    """Pakai ``products.tanggal_aktif_na`` (YYYY-MM-DD); parse defensif,
    fallback ``FALLBACK_DATE`` (29 November 2023) kalau kosong/tidak valid."""
    text = (nilai_aktif_na or "").strip()
    if text:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                from datetime import datetime as _dt
                return _dt.strptime(text[:10], fmt).date()
            except ValueError:
                continue
    return FALLBACK_DATE


# ==================== RENDER PDF ====================

def _kop_fs_path(company: dict) -> Optional[str]:
    """Path absolut gambar kop sesuai perusahaan (pola ``_kop_fs_path``
    di ``app/excel_generator.py``)."""
    company = company or {}
    uri = (company.get("kop") or "").strip()
    if not uri:
        logo = (company.get("logo") or "").lower()
        nama = (company.get("nama") or "").lower()
        if "heka" in logo or "haraka" in nama:
            uri = "/static/images/kop_heka.png"
        elif "erfi" in logo or "erfi" in nama:
            uri = "/static/images/kop_erfi.png"
    if not uri:
        return None
    relative = uri.split("/static/", 1)[-1] if "/static/" in uri else uri.lstrip("/")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), relative.replace("/", os.sep))
    return path if os.path.isfile(path) else None


def _kop_html(company: dict) -> str:
    """Gambar kop + garis pemisah. ``None`` -> fallback teks nama perusahaan.

    xhtml2pdf hanya membaca path filesystem absolut di bawah CWD (resource
    policy), jadi path absolut ``app/static/images`` yang dipakai (sama dengan
    pola ``_kop_image`` di ``app/dip_documents.py`` dan ``_brand_image`` di
    ``app/bab2_pdf.py``).
    """
    path = _kop_fs_path(company)
    if path:
        try:
            with Image.open(path) as img:
                px_w, px_h = img.size
        except Exception:
            px_w, px_h = 800, 130
        width_pt = 520.0
        height_pt = round(width_pt * px_h / max(px_w, 1), 1)
        return (f'<div style="text-align:center;margin-bottom:8px;">'
                f'<img src="{path}" alt="Kop Surat" '
                f'style="width:{width_pt}pt;height:{height_pt}pt;">'
                f'<hr style="border:0;border-top:1.5px solid #111;"></div>')
    nama = (company.get("nama") or "").strip()
    alamat = (company.get("alamat") or "").strip()
    return (f'<div style="text-align:center;border-bottom:1.5px solid #111;'
            f'padding-bottom:6px;margin-bottom:10px;">'
            f'<div style="font-size:11pt;font-weight:bold;">{nama}</div>'
            f'<div style="font-size:8pt;color:#333;">{alamat}</div></div>')


_HTML_COMMON = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
@page { size: letter landscape; margin: 10mm 12mm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 9.5pt; color: #111; }
.title { text-align: center; font-size: 13pt; font-weight: bold; margin: 10px 0 12px; }
.line { margin: 4px 0; }
.rule { margin: 4px 0; }
.rule b { display: inline-block; min-width: 52px; }
.legend { margin: 6px 0 0 18px; }
.berarti-label { text-decoration: underline; font-weight: bold; }
.berarti-underline { text-decoration: underline; }
table.lampiran { width: 100%; border-collapse: collapse; margin-top: 8px; }
table.lampiran td { border: 1px solid #666; padding: 4px 8px; font-size: 8.5pt; }
</style>
</head><body>
"""

_ERFI_BODY = """{kop}
<div class="title">SISTEM PENGKODEAN BATCH</div>
<p class="line">Format saat ini untuk kode batch produk <b>{nama}</b> sebagai berikut,</p>
<p class="line">Contoh untuk Nomor Batch : DD MM XX ZZZZZZ 01</p>
<p class="rule"><b>1.1.1</b> Digit pertama menunjukkan tahun produksi yang diberi kode sebagai berikut : untuk tahun 2016: 16, 2017:17 dan seterusnya.</p>
<p class="rule"><b>1.1.2</b> Digit kedua dan ketiga menunjukkan bulan pembuatan produk (ditulis dua angka bulan, Januari adalah 01, November adalah 11, dll.)</p>
<p class="rule"><b>1.1.3</b> Digit keempat dan kelima menunjukkan tanggal pembuatan produk (ditulis dua angka)</p>
<p class="rule"><b>1.1.4</b> 3-6 digit menunjukkan kode produk (disesuaikan dengan jenis sediaan dan merk)</p>
<p class="rule"><b>1.1.5</b> Digit selanjutnya menunjukkan penomoran batch.</p>
<p class="line">Nomor Batch adalah <b>{nomor_batch}</b></p>
<p class="line">Penjelasan Kode :</p>
<div class="legend">{legend_rows}</div>
<p class="line"><span class="berarti-label">{berarti_line1}</span></p>
<p class="line"><span class="berarti-underline">{berarti_line2}</span></p>
"""

_HEKA_BODY = """{kop}
<div class="title">SISTEM PENGKODEAN BATCH</div>
<p class="line">Format saat ini untuk kode batch produk <b>{nama}</b> sebagai berikut,</p>
<p class="line">Contoh untuk Nomor Batch : DD MM XX 00 ZZZZ 01</p>
<p class="rule"><b>1.1.1</b> Digit pertama dan kedua menunjukkan tahun produksi yang diberi kode sebagai berikut : untuk tahun 2016: 16, 2017:17 dan seterusnya.</p>
<p class="rule"><b>1.1.2</b> Digit ketiga dan keempat menunjukkan bulan pembuatan produk (ditulis dua angka bulan, Januari adalah 01, November adalah 11, dll.)</p>
<p class="rule"><b>1.1.3</b> Digit kelima dan keenam menunjukkan tanggal pembuatan produk (ditulis dua angka)</p>
<p class="rule"><b>1.1.4</b> Digit ketujuh dan kedelapan menunjukkan jenis sediaan produk</p>
<p class="rule"><b>1.1.5</b> 4-6 digit selanjutnya menunjukkan kode produk (disesuaikan dengan jenis sediaan dan merk)</p>
<p class="rule"><b>1.1.6</b> Digit selanjutnya menunjukkan penomoran batch.</p>
<p class="line">Nomor Batch adalah <b>{nomor_batch}</b></p>
<p class="line">Penjelasan Kode :</p>
<div class="legend">{legend_rows}</div>
<p class="line"><span class="berarti-label">{berarti_line1}</span></p>
<p class="line">Lampiran keterangan kode sediaan :</p>
<table class="lampiran">
{lampiran_rows}
</table>
"""

def _html_escape(text: str) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _legend_html(legenda: list) -> str:
    rows = []
    for baris in legenda or []:
        huruf = _html_escape(str((baris or {}).get("huruf") or ""))
        arti = _html_escape(str((baris or {}).get("arti") or ""))
        rows.append(f'<p style="margin:1px 0;">{huruf} : {arti}</p>')
    return "\n".join(rows)


def _lampiran_html() -> str:
    # 2 kolom x 6 baris: kiri 01-06, kanan 07-12 (sesuai PDF referensi Heka).
    left, right = KODE_SEDIAAN[:6], KODE_SEDIAAN[6:]
    cells = []
    for i in range(6):
        lc, ln = left[i]
        rc, rn = right[i]
        cells.append(f"<tr><td>{lc} {ln}</td><td>{rc} {rn}</td></tr>")
    return "\n".join(cells)


def render_pdf(product: dict, company: dict, kode_produk: str, legenda: list,
               kode_sediaan: Optional[str] = None, urut: int = 1) -> Optional[bytes]:
    """Render 1 halaman PDF landscape. ``None`` kalau gagal.

    ``company`` = ``COMPANY_INFO[perusahaan]`` (di-inject dari main.py).
    """
    perusahaan = (product or {}).get("perusahaan")
    nama = (product or {}).get("nama_produk") or "-"
    tanggal = tanggal_untuk_generate((product or {}).get("tanggal_aktif_na"))
    nomor = build_batch_number(tanggal, kode_produk, perusahaan, kode_sediaan, urut)
    sediaan_label = label_sediaan(kode_sediaan)
    berarti = berarti_lines(nomor, tanggal, nama, perusahaan, sediaan_label, urut)
    kop = _kop_html(company or {})
    if is_heka(perusahaan):
        body = _HEKA_BODY.format(
            kop=kop, nama=_html_escape(nama), nomor_batch=_html_escape(nomor),
            legend_rows=_legend_html(legenda),
            berarti_line1=_html_escape(berarti[0]),
            lampiran_rows=_lampiran_html(),
        )
    else:
        body = _ERFI_BODY.format(
            kop=kop, nama=_html_escape(nama), nomor_batch=_html_escape(nomor),
            legend_rows=_legend_html(legenda),
            berarti_line1=_html_escape(berarti[0]),
            berarti_line2=_html_escape(berarti[1]),
        )
    html = _HTML_COMMON + body + "</body></html>"
    buffer = io.BytesIO()
    try:
        status = pisa.CreatePDF(src=html, dest=buffer)
    except Exception as exc:  # pragma: no cover - pisa melempar
        print(f"[BATCH CODING PDF] Gagal render HTML ke PDF: {exc}")
        return None
    if status.err:
        print(f"[BATCH CODING PDF] xhtml2pdf error saat render: {status.err}")
        return None
    return buffer.getvalue()


def storage_path(product_id: str) -> str:
    return f"products/{product_id}/{_PATH_SUFFIX}"


def bucket() -> str:
    return _BUCKET
