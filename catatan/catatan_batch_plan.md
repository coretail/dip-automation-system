# Catatan Batch Plan — Migration Data PO / Produksi

## Status

**Planning only — belum melakukan perubahan code/database.**

Dokumen ini menjadi acuan awal untuk merancang migrasi data PO/produksi lama dari spreadsheet Excel ke Supabase.

> **Penting:** Jangan melakukan INSERT, UPDATE, DELETE, perubahan schema, atau perubahan codebase sebelum plan ini direview dan disetujui.

## 1. Tujuan

Memindahkan data PO/produksi lama dari spreadsheet ke database Supabase secara aman, terstruktur, dapat divalidasi, dan idempotent.

Data PO harus terhubung ke produk yang sudah ada di database melalui:

```text
spreadsheet Product
        ↓
matching
        ↓
products.id
        ↓
record PO / production order
```

Nama produk **tidak boleh digunakan langsung sebagai foreign key**.

## 2. Prinsip Utama

1. Jangan langsung import data mentah ke production database.
2. Migration harus memiliki tahap **dry-run / validation** sebelum INSERT.
3. Produk spreadsheet harus dimapping ke `products.id`.
4. Jika produk tidak ditemukan, jangan membuat product baru secara otomatis tanpa aturan yang disetujui.
5. Jika matching menghasilkan beberapa kandidat, masukkan ke manual review.
6. Migration harus dirancang **idempotent** sehingga menjalankan script lebih dari sekali tidak menghasilkan duplicate.
7. Jangan mengubah data existing yang tidak berhubungan dengan migration.
8. Jangan mengganti data batch/document existing hanya karena data spreadsheet lebih lama.
9. Semua asumsi yang belum terverifikasi harus ditandai `NEEDS VERIFICATION`.

## 3. Sumber Data

Spreadsheet PO / Produksi contoh memiliki kolom seperti:

| Kolom | Keterangan |
|---|---|
| Tgl PO | Tanggal PO |
| No. PO | Nomor PO |
| Qty PO | Quantity PO |
| Tgl Catatan Batch | Tanggal pencatatan batch |
| Urutan | Urutan item dalam PO |
| Item Product | Kode/item produk |
| Product Name | Nama produk |
| WIP | WIP |
| Netto (ml/gram) | Netto produk |
| Qty (kg) | Quantity dalam kg |
| Batch | Nomor batch |
| Keterangan | Keterangan |
| Revisi Produksi | Informasi revisi |
| Qty Produksi Yg belum turun SOP | Quantity yang belum turun SOP |
| Qty PO | Quantity PO |
| Temporary Reject | Status/nilai temporary reject |

**Catatan:** Struktur final harus diperiksa langsung dari file `.xlsx`, bukan hanya berdasarkan screenshot.

## 4. Audit Spreadsheet

Periksa seluruh workbook:

- nama sheet
- header sebenarnya
- merged cells
- baris kosong
- header tambahan
- baris lanjutan dengan `No. PO` kosong
- satu PO dengan beberapa product
- satu product dengan beberapa batch
- format tanggal
- format angka
- penggunaan koma/titik sebagai decimal separator
- quantity kosong
- batch kosong
- status kosong
- duplicate row
- duplicate PO
- inkonsistensi nama product
- formula vs nilai hasil formula

Jangan mengasumsikan baris dengan `No. PO` kosong sebagai record terpisah sebelum pola spreadsheet dikonfirmasi.

## 5. Existing Database yang Relevan

Database saat ini memiliki tabel `products` dengan field antara lain:

```text
products
- id
- nama_produk
- no_na_produk
- warna
- sediaan
- kemasan
- netto
- nama_customer
- perusahaan
- ...
```

Database juga memiliki:

```text
product_batches
- id
- product_id
- no_batch
- tanggal_produksi
- tanggal_ed
- ...
```

Relasi:

```text
products.id
    │
    └── product_batches.product_id
```

Sebelum membuat tabel baru, cari terlebih dahulu apakah codebase sudah memiliki struktur PO / production order / production planning yang dapat digunakan.

## 6. Product Matching

Target:

```text
Spreadsheet Product
        ↓
products
        ↓
products.id
```

Jika `Product Name` mengandung nama produk dan nomor NA, informasi tersebut dapat digunakan sebagai kandidat matching.

Contoh:

```text
MENLAB Hydrating Skin - NA18210107516
```

dapat dianalisis menjadi:

```text
nama_produk = MENLAB Hydrating Skin
no_na_produk = NA18210107516
```

Kemudian dicocokkan terhadap:

```text
products.nama_produk
products.no_na_produk
```

### Aturan

- Jangan menganggap parsing tersebut selalu benar sebelum seluruh spreadsheet diperiksa.
- Jangan menggunakan fuzzy matching tanpa menyimpan kandidat untuk review.
- Exact match diprioritaskan jika tersedia.
- Jika satu product menghasilkan beberapa kandidat → `NEEDS_REVIEW`.
- Jika tidak ditemukan → `NOT_FOUND`.
- Jangan membuat product baru otomatis pada tahap awal.

## 7. Proposed Mapping

| Spreadsheet | Database | Transformasi |
|---|---|---|
| Tgl PO | tanggal PO | Parse ke `date` |
| No. PO | no_po | Trim/normalize |
| Qty PO | qty_po | Parse numeric |
| Tgl Catatan Batch | tanggal_catatan_batch | Parse date |
| Urutan | urutan | Integer |
| Product Name | products.id | Lookup, bukan direct copy |
| WIP | wip | Normalize |
| Netto | netto | Pertahankan sesuai kebutuhan aplikasi |
| Qty (kg) | qty_kg | Parse numeric |
| Batch | no_batch | Trim/normalize |
| Keterangan | keterangan | Trim |
| Revisi Produksi | revisi_produksi | Normalize |
| Qty Produksi yg belum turun SOP | qty_belum_turun_sop | Parse numeric |
| Temporary Reject | temporary_reject | Normalize |

**Mapping final harus diverifikasi terhadap spreadsheet asli dan codebase.**

## 8. Tabel Tujuan

Jika belum ada tabel yang sesuai, kandidat struktur dapat berupa:

```text
production_orders
```

dengan konsep:

```text
id
product_id
no_po
tanggal_po
qty_po
tanggal_catatan_batch
urutan
wip
netto
qty_kg
no_batch
keterangan
revisi_produksi
qty_belum_turun_sop
qty_produksi
temporary_reject
created_at
```

Struktur ini **belum merupakan keputusan final**.

Sebelum membuat tabel:

1. Cari tabel existing.
2. Cari model/query/route existing.
3. Cari kebutuhan UI existing.
4. Tentukan relasi ke `products`.
5. Tentukan apakah `no_batch` perlu FK ke `product_batches.id`.
6. Tentukan unique constraint berdasarkan pola data nyata.

## 9. Relasi Batch

Jika batch spreadsheet sudah ada di `product_batches`, jangan membuat representasi batch kedua tanpa alasan.

Kemungkinan:

```text
production_orders
    │
    ├── product_id → products.id
    │
    └── batch → product_batches
```

Apakah `no_batch` cukup sebagai text atau harus memiliki `product_batch_id` harus ditentukan setelah audit data.

**Jangan mengubah `product_batches` existing hanya untuk mempermudah import.**

## 10. Idempotency

Jangan langsung mengasumsikan unique key.

Kandidat yang perlu dievaluasi:

```text
no_po
+
urutan
+
product_id
+
no_batch
```

Kombinasi final harus ditentukan berdasarkan seluruh data spreadsheet dan kebutuhan aplikasi.

Tujuan:

```text
Run #1 → insert data
Run #2 → tidak membuat duplicate
```

## 11. Dry-Run

Sebelum import:

```text
Excel
 ↓
Normalize
 ↓
Product matching
 ↓
Validation
 ↓
Report
```

Tidak ada perubahan database.

Contoh laporan:

```text
Total spreadsheet rows       : ...
Valid rows                   : ...
Product matched              : ...
Product not found            : ...
Multiple candidates          : ...
Batch kosong                 : ...
Duplicate candidate          : ...
Invalid date                 : ...
Invalid quantity             : ...
```

Status:

```text
READY
```

atau:

```text
NOT READY
```

Jika masih ada masalah kritis, migration tidak boleh masuk tahap INSERT.

## 12. Manual Review

Generate file review, misalnya:

```text
mapping_review.csv
```

Contoh field:

```text
spreadsheet_row
no_po
product_name
no_na
candidate_product_id
candidate_product_name
match_status
review_note
```

Status:

```text
MATCHED
NEEDS_REVIEW
NOT_FOUND
INVALID
```

## 13. Error Handling

Migration harus:

- mencatat nomor row spreadsheet
- mencatat `No. PO`
- mencatat product terkait
- mencatat alasan error
- tidak menyembunyikan error parsing
- tidak melanjutkan secara diam-diam ketika foreign key tidak ditemukan
- menghasilkan report yang dapat diperiksa ulang

Contoh:

```text
ROW 183
No PO: 140/PO-ERFI/26
Product: XYZ Serum
Error: product tidak ditemukan
Status: NOT_FOUND
```

## 14. Rollback

Sebelum import production:

1. Pastikan recovery/backup strategy tersedia.
2. Gunakan transaction jika memungkinkan.
3. Gunakan migration identifier yang dapat ditelusuri.
4. Jangan melakukan destructive update terhadap existing data.

Jika sebagian import gagal, idealnya migration dapat rollback tanpa meninggalkan data setengah masuk.

## 15. Struktur File Kandidat

```text
migration/
├── catatan_batch_plan.md
├── data_po.xlsx
├── migrate_po.py
├── mapping_review.csv
└── migration_report.csv
```

Nama dan struktur final mengikuti convention project setelah codebase diaudit.

## 16. Tahapan Implementasi

### Phase 1 — Audit

- [ ] Baca spreadsheet
- [ ] Audit seluruh sheet
- [ ] Audit struktur row
- [ ] Audit existing database
- [ ] Audit codebase
- [ ] Cari existing PO/production structure

### Phase 2 — Design

- [ ] Finalisasi mapping
- [ ] Finalisasi product matching
- [ ] Finalisasi batch relationship
- [ ] Finalisasi unique key
- [ ] Finalisasi schema jika memang diperlukan
- [ ] Finalisasi dry-run report

### Phase 3 — Implementation

- [ ] Buat migration script
- [ ] Buat normalizer
- [ ] Buat product matcher
- [ ] Buat validator
- [ ] Buat dry-run mode
- [ ] Buat import mode
- [ ] Buat error/reporting

### Phase 4 — Validation

- [ ] Jalankan dry-run
- [ ] Review `NOT_FOUND`
- [ ] Review `NEEDS_REVIEW`
- [ ] Review duplicate
- [ ] Review quantity/date parsing
- [ ] Review batch mapping

### Phase 5 — Import

Hanya setelah approval:

```text
python migrate_po.py --import
```

### Phase 6 — Verification

- [ ] Hitung jumlah record hasil import
- [ ] Bandingkan dengan spreadsheet
- [ ] Cek duplicate
- [ ] Cek foreign key
- [ ] Cek batch
- [ ] Cek sample record secara manual

## 17. Batasan untuk Cline

Pada tahap planning:

> **Jangan mengubah codebase.**
>
> **Jangan mengubah schema Supabase.**
>
> **Jangan INSERT/UPDATE/DELETE data.**
>
> **Jangan menjalankan migration.**
>
> **Jangan membuat asumsi yang tidak didukung spreadsheet atau codebase.**
>
> Jika ada informasi yang belum dapat dipastikan, tandai `NEEDS VERIFICATION`.

Setelah analisis selesai, berhenti dan tunggu approval sebelum implementasi.

## 18. Keputusan Final (LOCKED 2026-09-23)

Keputusan berikut sudah dikonfirmasi user dan mengikat implementasi:

1. Tabel PO belum ada di Supabase — schema PO/PO item baru perlu dibuat saat implementasi (di luar tahap audit read-only ini).
2. Dilarang membuat product baru otomatis karena match gagal. Produk yang tidak ketemu → `NEEDS_REVIEW`.
3. Prioritas matching utama = `no_na_produk`. Contoh: `NA18241301433`. Nama produk hanya pendukung, bukan kunci.
4. Identitas: `no_po` = identitas PO; `no_po + urutan` = identitas PO item/batch.
5. Relasi batch: gunakan FK ke `product_batches.id`. Alur: cari `product_id` via `no_na_produk` → cari `product_batches` via `product_id + no_batch` → kalau ketemu gunakan `product_batches.id`; kalau tidak ketemu → `NEEDS_REVIEW` / buat batch baru hanya jika aturan bisnis mengizinkan (default: jangan buat otomatis).
6. Baris footer (`Sub Total`, `Total Output SOP`), baris kosong separator, dan merged cells → `skip` saat parsing.
7. Kolom `Revisi Produksi` dan `TEMPORARY REJECT` (selalu kosong di file ini) → `nullable`, jangan jadikan kolom wajib.
8. Normalisasi angka Indonesia: koma = desimal (`1,000` → `1.0`, `2,6` → `2.6`), satuan `Kg` di-strip, tanda `(...)`/`+`/`-` dipertahankan sebagai nilai signed (`(-302 Kg)` → `-302`, `(+14,3 Kg)` → `+14.3`, `0` → `0`).

## 19. Acceptance Criteria

Migration siap diimplementasikan jika:

- [ ] Semua kolom spreadsheet sudah dipahami.
- [ ] Semua kemungkinan struktur row sudah dipahami.
- [ ] Mapping Product → `products.id` sudah jelas.
- [ ] Record yang tidak dapat dimapping dapat diidentifikasi.
- [ ] Hubungan batch sudah jelas.
- [ ] Duplicate strategy sudah jelas.
- [ ] Migration dapat melakukan dry-run.
- [ ] Migration dirancang idempotent.
- [ ] Ada error report.
- [ ] Ada rollback/recovery strategy.
- [ ] Tidak ada perubahan database sebelum approval.
