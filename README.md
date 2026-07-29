# Aplikasi Penyusun Dokumen Informasi Produk (DIP) Kosmetik
## Bagian I — Modul Formula & Bahan Baku (Fondasi Bab II, III, IV)

---

Link : https://dip-automation-system.onrender.com/

## 1. Latar Belakang

Penyusunan Dokumen Informasi Produk (DIP) kosmetik — khususnya Bab II (Data Mutu dan Keamanan Bahan Kosmetika), Bab III (Data Mutu Produk Jadi), dan Bab IV (Data Keamanan Produk) — saat ini dikerjakan secara manual menggunakan Microsoft Excel dan penyusunan dokumen Word satu per satu.

Proses manual ini menimbulkan beberapa masalah berulang:

1. **Formula bahan baku (working formula)** disusun berdasarkan *nama dagang* bahan baku yang dibeli dari supplier, sementara pelaporan ke BPOM mewajibkan pelaporan berbasis *INCI Name (ingredient)*.
2. Satu nama dagang bahan baku dapat berupa:
   - **Bahan tunggal** (single ingredient) — misal Cetearyl Alcohol, Vaselin, BHT.
   - **Bahan komposit** — mengandung lebih dari satu INCI dengan proporsi tertentu di dalamnya (misal Sepigel, SiO2TiO2CR50, Polawax).
3. Ingredient yang sama dapat berasal dari lebih dari satu nama dagang berbeda dalam satu formula (misal Cetearyl Alcohol berasal dari bahan "Cetearyl Alcohol" itu sendiri **dan** dari "Polawax"). Persentase akhir ingredient ini harus **dijumlahkan secara manual**, yang rawan human error dan memakan waktu.
4. Perhitungan konversi dari % nama dagang ke % ingredient akhir dilakukan manual dengan rumus:

   ```
   % Ingredient (akhir) = % Nama Dagang (dalam formula) × % Ingredient (dalam komposisi bahan) / 100
   ```

5. Data kode bahan baku, spesifikasi, dan sertifikat analisis (CoA) tersebar di banyak file dan harus dicocokkan manual saat menyusun dokumen Bab II.
6. Tidak ada sistem terpusat untuk memantau status registrasi (Nomor Notifikasi/NA) produk — apakah aktif, akan expired, atau sudah expired.

Aplikasi ini dirancang untuk mengotomatiskan proses tersebut, dimulai dari fondasi yang paling krusial: **manajemen data bahan baku dan kalkulasi formula produk**, sebelum masuk ke tahap generate dokumen Bab II secara otomatis.

---

## 2. Tujuan Aplikasi

1. Menyediakan **database bahan baku terpusat dan reusable** yang dapat dipakai berulang kali untuk berbagai produk, tanpa perlu input ulang setiap kali membuat formula baru.
2. Mengotomatiskan **konversi formula dari basis Nama Dagang ke basis Ingredient (INCI)**, termasuk penjumlahan otomatis untuk ingredient yang muncul dari beberapa bahan baku berbeda.
3. Menyediakan **database produk terpusat** yang mencakup data formula sekaligus data administratif/regulasi (customer, nomor NA, status registrasi, dsb).
4. Menjadi fondasi data bagi tahap pengembangan selanjutnya, yaitu **generate otomatis dokumen Bab II, Bab III, dan Bab IV DIP** dalam format Word/PDF.

---

## 3. Ruang Lingkup Tahap Ini (Fase 1)

Fase pertama pengembangan **difokuskan pada**:

- Modul database bahan baku (CRUD, Admin)
- Modul database produk
- Modul Formula Builder per produk
- Modul Ingredient Report (hasil kalkulasi otomatis, basis untuk Bab II/III)

**Belum termasuk** di fase ini (dikerjakan pada fase berikutnya):

- Generate dokumen Bab II, III, IV secara otomatis ke Word/PDF
- Manajemen lampiran CoA (Certificate of Analysis) supplier per bahan baku
- Modul Bab III (Data Mutu Produk Jadi) dan Bab IV (Data Keamanan Produk)

---

## 4. Struktur Data (Data Model)

Aplikasi ini dibangun di atas **4 entitas data (tabel) inti**, dengan relasi header–detail:

### 4.1 Skema Tabel

| # | Nama Tabel | Fungsi | Relasi |
|---|---|---|---|
| 1 | `raw_materials` | Header data bahan baku (identitas nama dagang) | Induk dari tabel 2 |
| 2 | `raw_material_components` | Rincian komponen INCI di dalam satu bahan baku | Anak dari tabel 1 (banyak baris per 1 bahan baku) |
| 3 | `products` | Header data produk (identitas & data registrasi) | Induk dari tabel 4 |
| 4 | `product_formula_lines` | Rincian baris formula (bahan baku apa saja & berapa % di produk) | Anak dari tabel 3, mereferensikan tabel 1 |

> **Catatan:** Tabel 1 & 2 dipisah karena satu bahan baku dapat memiliki 1 komponen (bahan tunggal) atau banyak komponen (bahan komposit) — pemisahan ini menghindari duplikasi data nama dagang/kode di setiap baris komponen. Prinsip yang sama berlaku pada pemisahan tabel 3 & 4.

### 4.2 Detail Field per Tabel

**Tabel 1 — `raw_materials`**

| Field | Tipe | Keterangan |
|---|---|---|
| id | string | ID unik bahan baku |
| nama_dagang | string | Nama dagang/nama supplier (misal "Sepigel", "Vaselin") |
| kode_bahan_baku | string | Kode internal perusahaan (misal "TCK05LQ-0905") |
| tipe | enum | `single` atau `komposit` |

**Tabel 2 — `raw_material_components`**

| Field | Tipe | Keterangan |
|---|---|---|
| id | string | ID unik komponen |
| raw_material_id | FK → tabel 1 | Bahan baku induk |
| inci_name | string | Nama INCI (misal "Polyacrylamide") |
| function | string | Fungsi bahan (misal "Antistatic Agent") |
| percent_internal | number | % komponen ini di dalam bahan baku (total seluruh komponen per 1 raw_material harus = 100%) |

**Tabel 3 — `products`**

| Field | Tipe | Keterangan |
|---|---|---|
| id | string | ID unik produk |
| nama_produk | string | Nama produk |
| warna | string | Warna sediaan |
| sediaan | string | Bentuk sediaan (cream, gel, lotion, dll) |
| kemasan | string | Jenis kemasan |
| netto | string | Berat/volume netto |
| nama_customer | string | Nama customer/klien |
| acc_sampel | string/date | Status/tanggal acc sampel |
| no_na_produk | string | Nomor Notifikasi BPOM |
| status_na | enum | `aktif` \| `akan_expired` \| `expired` |

**Tabel 4 — `product_formula_lines`**

| Field | Tipe | Keterangan |
|---|---|---|
| id | string | ID unik baris formula |
| product_id | FK → tabel 3 | Produk terkait |
| raw_material_id | FK → tabel 1 | Bahan baku yang dipakai |
| percent_in_formula | number | % w/w bahan baku ini di dalam formula produk (total seluruh baris per 1 produk harus = 100%) |

### 4.3 Data Turunan (Tidak Disimpan, Dihitung Otomatis)

**Ingredient Report** — tabel hasil akhir (basis Bab II/III, format ke BPOM) **tidak disimpan sebagai tabel terpisah**, melainkan dihitung secara *on-the-fly* (real-time) dari join tabel 2, 3, dan 4. Pendekatan ini dipilih agar:

- Setiap perubahan pada data bahan baku (tabel 1/2) otomatis termutakhirkan di seluruh laporan produk yang memakainya, tanpa perlu sinkronisasi manual.
- Tidak terjadi duplikasi/inkonsistensi data antara formula asal dan laporan hasil.

---

## 5. Logika Kalkulasi Inti

### 5.1 Konversi % Nama Dagang → % Ingredient

```
% Ingredient (final) = % Nama Dagang (dalam formula) × % Ingredient (dalam komposisi bahan) ÷ 100
```

**Contoh kasus nyata (bahan komposit "Sepigel"):**

| Komponen internal Sepigel | % internal |
|---|---|
| Aqua | 34,52% |
| Polyacrylamide | 40,00% |
| C13-14 Isoparaffin | 20,00% |
| Laureth-7 | 5,48% |

Jika Sepigel dipakai **2,500%** dalam formula produk, maka:

- Aqua = 2,500 × 34,52% ÷ 100 = **0,863%**
- Polyacrylamide = 2,500 × 40,00% ÷ 100 = **1,000%**
- C13-14 Isoparaffin = 2,500 × 20,00% ÷ 100 = **0,500%**
- Laureth-7 = 2,500 × 5,48% ÷ 100 = **0,137%**

*(Angka ini tervalidasi cocok dengan data existing pada working formula perusahaan.)*

### 5.2 Penggabungan Ingredient Sejenis (Group & Sum)

Setelah seluruh baris formula di-*expand* ke level INCI, sistem melakukan **group-by nama INCI**, lalu **menjumlahkan** seluruh kontribusi persentase dari sumber bahan baku manapun.

**Contoh:** Cetearyl Alcohol muncul dari 2 sumber berbeda dalam formula:
- Dari bahan baku "Cetearyl Alcohol" langsung: 2,000%
- Dari bahan baku "Polawax" (komponen internal): 1,500%

→ Ingredient Report menampilkan **satu baris** "Cetearyl Alcohol" dengan total **3,500%** — proses yang sebelumnya dilakukan manual di Excel, kini otomatis.

### 5.3 Validasi Otomatis

- Total `percent_internal` per bahan baku komposit **harus = 100%** (divalidasi saat input/edit di Admin).
- Total `percent_in_formula` per produk **harus = 100%** (divalidasi saat menyusun formula, dengan indikator visual jika kurang/lebih).

---

## 6. Struktur Halaman Aplikasi

### 6.1 Dashboard Produk
- Tabel seluruh produk terdaftar: Nama Produk, No. NA, Nama Customer, Sediaan, Status NA (indikator warna: hijau = aktif, kuning = akan expired, merah = expired)
- Fitur pencarian dan filter berdasarkan status NA
- Tombol tambah produk baru

### 6.2 Form Detail Produk
- Bagian data administratif: nama produk, warna, sediaan, kemasan, netto, nama customer, acc sampel, no. NA produk, status NA
- Bagian Formula Builder (lihat 6.3)

### 6.3 Formula Builder
- Pencarian dan pemilihan bahan baku dari database (menampilkan nama dagang + kode bahan baku)
- Input % w/w bahan baku tersebut dalam formula
- Tampilan tabel formula per nama dagang (setara format kerja Excel yang sudah biasa dipakai)
- Indikator total persentase formula (real-time, menandai jika ≠ 100%)

### 6.4 Ingredient Report (Auto-generated)
- Tabel hasil akhir: Ingredient (INCI), Function, % w/w, Total
- Dihasilkan otomatis dari Formula Builder — inilah dasar data untuk penyusunan Bab II & III DIP pada fase pengembangan berikutnya

### 6.5 Admin — Manajemen Bahan Baku (CRUD)
- Daftar seluruh bahan baku (dengan pencarian: nama dagang, kode, tipe)
- **Tambah bahan baku**: pilih tipe (single/komposit) → jika komposit, dapat menambahkan baris komponen INCI secara dinamis dengan validasi total 100%
- **Edit bahan baku**: ubah nama dagang, kode, atau komponen
- **Hapus bahan baku**: dengan peringatan jika bahan tersebut masih digunakan pada produk aktif

---

## 7. Alur Kerja Pengguna (End-to-End)

1. **Admin** mengisi database bahan baku satu kali di awal (data ini bersifat permanen dan dapat dipakai berulang untuk produk apa pun ke depannya).
2. Pengguna membuat **produk baru**, mengisi data administratif (nama, customer, No. NA, dll.).
3. Pengguna menyusun **formula produk** menggunakan bahan baku yang sudah tersedia di database, cukup memilih bahan dan mengisi persentasenya.
4. Sistem otomatis menghasilkan **Ingredient Report** — tanpa perlu perhitungan manual atau penjumlahan ingredient sejenis secara manual.
5. **Dashboard** memungkinkan pemantauan status registrasi (NA) seluruh produk sekaligus.

---

## 8. Rencana Pengembangan Lanjutan (Fase Berikutnya)

Fase ini menjadi fondasi bagi pengembangan modul-modul berikut, yang akan dibangun setelah Fase 1 selesai dan tervalidasi:

| Fase | Modul | Deskripsi Singkat |
|---|---|---|
| 2 | Generator Dokumen Bab II | Menyusun otomatis halaman checklist kelengkapan data, Catatan Pemeriksaan Bahan Baku, dan Catatan Spesifikasi Bahan Baku per bahan, berbasis data dari Fase 1 |
| 3 | Manajemen Lampiran CoA | Upload dan pengelolaan sertifikat analisis (CoA) supplier, terhubung ke masing-masing bahan baku |
| 4 | Generator Dokumen Bab III | Data Mutu Produk Jadi |
| 5 | Generator Dokumen Bab IV | Data Keamanan Produk |
| 6 | Ekspor Dokumen | Ekspor seluruh dokumen ke format Word (.docx) dan PDF, mengikuti format standar DIP perusahaan |

---

## 9. Manfaat yang Diharapkan

- **Efisiensi waktu**: menghilangkan proses perhitungan dan penjumlahan manual di Excel untuk setiap produk baru.
- **Akurasi**: mengeliminasi human error dalam kalkulasi cascading percentage dan penjumlahan ingredient sejenis.
- **Konsistensi**: satu sumber data bahan baku (single source of truth) yang dipakai untuk seluruh produk, mengurangi risiko data yang tidak sinkron antar dokumen.
- **Skalabilitas**: fondasi data yang sama dapat dipakai untuk menyusun Bab II, III, dan IV tanpa input ulang.
- **Traceability**: kode bahan baku dan riwayat status NA produk terdokumentasi rapi dan mudah ditelusuri.

---

## 10. Detail Rencana Struktur Tabel Baru & Alur Generate Bab II

### 10.1 Struktur Tabel Baru (3 Tabel Tambahan/Ekstensi)

Untuk mendukung modul otomatisasi Dokumen Informasi Produk (DIP) Bab II, dirancang 3 tabel tambahan/ekstensi berikut:

#### 1. Extend `raw_materials` (Tambah Kolom Spesifikasi Stabil)
Kolom-kolom baru ditambahkan ke tabel `raw_materials` untuk menyimpan parameter spesifikasi bahan baku yang bersifat stabil/tetap (tidak berubah-ubah setiap kedatangan). Data ini diinput sekali saat pendaftaran bahan baku baru, dan otomatis digunakan kembali untuk semua produk yang mengandung bahan tersebut.

*Field-field ini memetakan langsung kebutuhan form **"CATATAN SPESIFIKASI BAHAN BAKU"** (Pemerian, Aroma, pH, Viskositas, Masa Kedaluarsa, Penyimpanan, Referensi).*

#### 2. Tabel Baru `raw_material_batches` (Data per Kedatangan/Batch)
Tabel ini digunakan untuk mencatat data pemeriksaan mutu bahan baku setiap kali ada kiriman/kedatangan baru dari supplier.

*Tabel ini memetakan langsung isi form **"CATATAN PEMERIKSAAN BAHAN BAKU"** (No. Batch, Supplier, Tanggal Pengambilan Sample, Hasil per parameter, Kesimpulan, Verifikator/Tanda tangan). Hubungannya adalah 1 bahan baku (`raw_materials`) dapat memiliki banyak batch (`raw_material_batches`).*

#### 3. Tabel Baru `sop_documents` (SOP CPKB dengan Versioning)
Tabel ini menyimpan dokumen standar operasional prosedur (SOP) CPKB dengan mekanisme penomoran versi (versioning).

*Untuk versioning, setiap kali SOP direvisi, baris baru dimasukkan (insert) dan baris lama di-set `is_active = false`. Aplikasi akan mengambil dokumen dengan `is_active = true` saat generate dokumen Bab II.*

---

### 10.2 Alur Generate Bab II (per Produk)

Sistem akan mengikuti langkah-langkah di bawah ini untuk menghasilkan dokumen lengkap Bab II per produk kosmetik:

1. **Ambil Semua Raw Material Terkait**
   Mendapatkan seluruh bahan baku (`raw_materials`) yang digunakan di dalam formula produk terpilih via relasi:
   `products` → `product_formula_lines` → `raw_materials`

2. **Dapatkan Data Detail untuk Setiap Bahan Baku (`raw_material`):**
   * **Halaman Spesifikasi:** Diambil dari kolom-kolom baru spesifikasi stabil di tabel `raw_materials`.
   * **Halaman Pemeriksaan:** Diambil dari tabel `raw_material_batches` dengan menyaring batch **terbaru** (atau memberikan pilihan interaktif kepada pengguna untuk memilih nomor batch tertentu yang ingin digunakan dalam dokumen ini).
   * **CoA (Certificate of Analysis):** Menggunakan berkas dari `raw_material_batches.coa_file_url` yang sesuai dengan batch terpilih.

3. **Ambil SOP CPKB Aktif**
   Menyisipkan satu kali di bagian awal dokumen: SOP CPKB yang memiliki status `is_active = true` dan disaring sesuai dengan `product.perusahaan` (PT Heka atau PT Erfi).

4. **Kompilasi/Penggabungan Dokumen Akhir**
   Menggabungkan seluruh komponen menjadi satu file dokumen Word/PDF dengan urutan struktur sebagai berikut:
   $$\text{Checklist} \rightarrow \text{SOP CPKB} \rightarrow \left[ \text{Spesifikasi Bahan} + \text{Pemeriksaan Batch} + \text{File CoA} \right] \times N \text{ bahan baku}$$

---

*Dokumen ini merupakan laporan rancangan (design proposal) untuk pengembangan aplikasi. Rancangan teknis implementasi akan terus diperbarui seiring berjalannya fase pengembangan.*
