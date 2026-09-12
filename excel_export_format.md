# Rencana Penyesuaian Format Export Excel Formula

Dokumen kerja buat menyelaraskan output `.xlsx` yang di-generate app
(`Qual_Quan_Formula_*.xlsx`) dengan format file formula manual internal
(contoh referensi: *Formula SERUNI Whitening Level Up 2 Day Cream.xlsx*).

**Scope tetap:** generator di `app/excel_generator.py` + asset logo yang
sudah ada. Nama sheet dan jumlah sheet **tidak diubah**.

Route terkait:
`GET /products/{product_id}/qualitative-quantitative/export-xlsx`

---

## 1. Keputusan (locked)

| # | Pertanyaan | Keputusan |
|---|------------|-----------|
| 1 | Kop surat | **Logo + teks** (nama PT, alamat, email/website) |
| 2 | Kolom Kode di sheet Nama Dagang | **Tetap ada** |
| 3 | Multi-INCI 1 nama dagang | **Tetap 1 baris per ingredients** (tanpa merge baris) |
| 4 | Sheet Text Design | **Tanpa kop surat** (logo + teks perusahaan tidak ditampilkan) |

---

## 2. Yang tidak berubah

- Jumlah sheet: **3**
- Nama sheet:
  1. `Formula Nama Dagang`
  2. `Formula INCI Murni`
  3. `Text Design`
- Kolom sheet Nama Dagang: `Nama Dagang | Kode | Ingredients | Function | % w/w`
- Kolom sheet INCI Murni: `Ingredients | Function | % w/w`
- Data source: `trade_breakdown`, `pure_breakdown`, `product`, `company`
  (dari `get_company_info` / `COMPANY_INFO` di `main.py`)
- Nama file export: `Qual_Quan_Formula_{safe_name}.xlsx` (boleh tetap)

---

## 3. Target layout per sheet

### 3.1 Sheet `Formula Nama Dagang` & `Formula INCI Murni`

**Kop surat (logo + teks)** — ganti `_letterhead` yang sekarang teks-only:

```
┌──────────┬────────────────────────────────────────────┐
│  [LOGO]  │  PT. … (bold, besar)                       │
│          │  Office : alamat …                         │
│          │  Email: … | Website: …                     │
└──────────┴────────────────────────────────────────────┘
         judul: FORMULA KUALITATIF & KUANTITATIF
         blok info produk
         tabel + total
         blok tanda tangan
```

Detail:

- Logo diambil dari `company["logo"]` → file lokal
  `app/static/images/logo_erfi.png` atau `logo_heka.png`
  (path di `COMPANY_INFO` sudah ada; mapping URI → path file sama pola
  yang dipakai PDF kop surat bila sudah ada helper-nya).
- Tinggi logo target ~55–70 px; lebar proporsional (Erfi lanskap, Heka
  potret — boleh reuse `_logo_render_width` dari `main.py` atau helper
  setara di generator).
- Teks nama/alamat/kontak di kanan logo (bukan 3 baris full-width
  tanpa logo seperti sekarang).
- Sisakan baris kosong tipis antara kop dan judul dokumen.

**Info produk** — opsional polish (boleh fase yang sama):

- Format label + value tetap 2 kolom; boleh tambah `:` di depan value
  biar mirip file manual (`: SERUNI …`), **bukan requirement keras**.

**Tabel** — tidak berubah struktur kolom; styling existing
(header abu `#E5E7EB`, border tipis, total highlight) dipertahankan
kecuali perlu tweak kecil supaya tidak bentrok dengan tinggi baris logo.

**Tanda tangan** — tetap ada di dua sheet formula (seperti sekarang).

### 3.2 Sheet `Text Design`

- **Tidak** memanggil `_letterhead` / tidak embed logo.
- Mulai langsung dari judul / blok field Text Design (Tanggal, Nama
  Produk, Netto, No NA, dll.) seperti perilaku sekarang minus kop.
- Note box + tanpa blok tanda tangan: **tetap**.

---

## 4. Perubahan teknis (file)

| File | Perubahan |
|------|-----------|
| `app/excel_generator.py` | Refactor `_letterhead` → terima path logo, embed `openpyxl.drawing.image.Image`, layout logo + teks; sesuaikan start row info/tabel di sheet trade & pure; pastikan `_sheet_text_design` **tidak** pakai letterhead |
| `app/main.py` | Hanya jika perlu: export helper path logo absolut ke generator, atau pastikan `company["logo"]` bisa di-resolve dari CWD app. Idealnya generator resolve `app/static/...` sendiri tanpa ubah route |
| Asset | Tidak perlu file baru — pakai `logo_erfi.png` / `logo_heka.png` yang sudah ada |

**Out of scope:**

- Mengubah nama/jumlah sheet
- Merge multi-INCI / formula `SUM` per nama dagang
- Menambah sheet DIP / Batch Coding / dll. dari file manual
- Mengubah format filename export
- Dark mode (tidak relevan ke file Excel)

---

## 5. Fase pengerjaan

- [ ] **Fase 0 — Resolve path logo**  
  Helper di `excel_generator.py`: dari `company["logo"]` (`/static/images/...`)
  → path filesystem `app/static/images/...`. Fail soft (tanpa logo) kalau
  file hilang, tetap render teks.

- [ ] **Fase 1 — `_letterhead` logo + teks**  
  Embed image + merge/tulis nama, alamat, kontak di samping/bawah logo.
  Row height baris 1–4 disesuaikan supaya logo tidak ketiban teks.

- [ ] **Fase 2 — Wire ke 2 sheet formula**  
  `_sheet_formula_trade` dan `_sheet_formula_pure` pakai letterhead baru;
  geser start row judul/info/tabel bila perlu.

- [ ] **Fase 3 — Text Design tanpa kop**  
  Pastikan `_sheet_text_design` tidak memanggil letterhead (dan tidak
  menyisakan baris kosong “bekas” kop).

- [ ] **Fase 4 — Smoke test**  
  Export 1 produk PT Erfi + 1 produk PT Heka; buka di Excel/LibreOffice:
  logo benar per PT, teks kebaca, tabel utuh, Text Design tanpa logo,
  kolom Kode masih ada, 1 baris per ingredients.

---

## 6. Referensi audit (12 Sep 2026)

- Generator: `app/excel_generator.py` (`build_formula_workbook`,
  `_letterhead`, `_sheet_formula_trade`, `_sheet_formula_pure`,
  `_sheet_text_design`)
- Company + logo path: `COMPANY_INFO` / `get_company_info` di `app/main.py`
- Logo file: `app/static/images/logo_erfi.png`, `logo_heka.png`
- Contoh app-generated: `Qual_Quan_Formula_seruni_anti_aging_facial_cleanser.xlsx`
  (teks letterhead, tanpa image, 3 sheet)
- Contoh manual: `Formula SERUNI Whitening Level Up 2 Day Cream.xlsx`
  (logo embedded di sheet Formula 2; multi-sheet — **bukan** target
  struktur sheet, hanya referensi visual kop)

---

## 7. Definisi selesai

Export `.xlsx` dari app:

1. Sheet Nama Dagang & INCI Murni menampilkan **logo perusahaan yang benar**
   + teks nama/alamat/kontak.
2. Kolom **Kode** masih ada di Nama Dagang.
3. Setiap ingredients tetap **satu baris** (tidak di-merge per nama dagang).
4. Sheet **Text Design tanpa kop/logo**.
5. Nama & jumlah sheet tidak berubah; file tetap bisa di-download dari
   halaman qualitative-quantitative.
