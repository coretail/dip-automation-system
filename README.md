# Aplikasi Penyusun Dokumen Informasi Produk (DIP) Kosmetik

**Link aplikasi:** https://dip-automation-system.onrender.com/

---

## 1. Latar Belakang

Penyusunan Dokumen Informasi Produk (DIP) kosmetik — khususnya Bab II (Data Mutu dan Keamanan Bahan Kosmetika), Bab III (Data Mutu Produk Jadi), dan Bab IV (Data Keamanan Produk) — sebelumnya dikerjakan secara manual menggunakan Microsoft Excel dan penyusunan dokumen Word satu per satu, untuk dua perusahaan sekaligus (PT Erfi Karya Abadi dan PT Heka).

Proses manual ini menimbulkan beberapa masalah berulang:

1. **Formula bahan baku (working formula)** disusun berdasarkan *nama dagang* bahan baku yang dibeli dari supplier, sementara pelaporan ke BPOM mewajibkan pelaporan berbasis *INCI Name (ingredient)*.
2. Satu nama dagang bahan baku dapat berupa:
   - **Bahan tunggal** (single ingredient) — misal Cetearyl Alcohol, Vaselin, BHT.
   - **Bahan komposit** — mengandung lebih dari satu INCI dengan proporsi tertentu di dalamnya (misal Sepigel, SiO2TiO2CR50, Polawax).
3. Ingredient yang sama dapat berasal dari lebih dari satu nama dagang berbeda dalam satu formula. Persentase akhir ingredient ini harus **dijumlahkan secara manual**, yang rawan human error dan memakan waktu.
4. Perhitungan konversi dari % nama dagang ke % ingredient akhir dilakukan manual dengan rumus:

   ```
   % Ingredient (akhir) = % Nama Dagang (dalam formula) × % Ingredient (dalam komposisi bahan) / 100
   ```

5. Data kode bahan baku, spesifikasi, dan sertifikat analisis (CoA/MSDS/Halal) tersebar di banyak file dan harus dicocokkan manual saat menyusun dokumen Bab II.
6. Tidak ada sistem terpusat untuk memantau status registrasi (Nomor Notifikasi/NA) produk, riwayat kedatangan batch bahan baku, maupun untuk memisahkan produk berdasarkan perusahaan penerbit (PT Erfi / PT Heka).

---

## 2. Tujuan Aplikasi

1. Menyediakan **database bahan baku terpusat dan reusable**, dapat dipakai berulang kali lintas produk maupun lintas PT tanpa duplikasi data.
2. Mengotomatiskan **konversi formula dari basis Nama Dagang ke basis Ingredient (INCI)**, termasuk penjumlahan otomatis untuk ingredient yang muncul dari beberapa bahan baku berbeda.
3. Menyediakan **database produk terpusat** mencakup data formula, data administratif/regulasi, dan penanda perusahaan penerbit (PT Erfi Karya Abadi / PT Heka).
4. Menyimpan dan mengelola **dokumen pendukung bahan baku** (MSDS per bahan, serta CoA dan sertifikat Halal per kedatangan batch) secara terpusat dan mudah ditelusuri.
5. Menghasilkan **dokumen siap pakai** (preview cetak/PDF dan file Excel) langsung dari data yang tersimpan, lengkap dengan kop surat sesuai PT terkait.
6. Menjadi fondasi data bagi tahap pengembangan selanjutnya: generate otomatis dokumen Bab II, Bab III, dan Bab IV DIP.

---

## 3. Status Pengembangan

| Fase | Modul | Status |
|---|---|---|
| 1 | Database bahan baku, produk, formula builder, ingredient report, dokumen Qual-Quan + Text Design | ✅ **Selesai** |
| 2a | Manajemen batch bahan baku (CoA, Sertifikat Halal) & MSDS per bahan baku | ✅ **Selesai** |
| 2b | Generator Dokumen Bab II (spesifikasi otomatis, penggabungan checklist + SOP CPKB + lampiran) | 🔧 Dalam perancangan |
| 3 | Generator Dokumen Bab III (Data Mutu Produk Jadi) | ⬜ Belum dimulai |
| 4 | Generator Dokumen Bab IV (Data Keamanan Produk) | ⬜ Belum dimulai |

---

## 4. Fase 1 — Fondasi Data & Dokumen Formula (Selesai)

### 4.1 Struktur Data

**Tabel 1 — `raw_materials`** (header bahan baku)

| Field | Tipe | Keterangan |
|---|---|---|
| id | uuid | ID unik |
| nama_dagang | string | Nama dagang/supplier |
| kode_bahan_baku | string | Kode internal, unik (divalidasi anti-dobel) |
| tipe | enum | `single` atau `komposit` |
| produsen | string | Nama produsen/pabrikan asal bahan |
| msds_file_url | text | Link file MSDS (Material Safety Data Sheet) tersimpan di Supabase Storage |

**Tabel 2 — `raw_material_components`** (rincian INCI per bahan baku)

| Field | Tipe | Keterangan |
|---|---|---|
| id | uuid | ID unik |
| raw_material_id | FK → tabel 1 | Bahan baku induk |
| inci_name | string | Nama INCI |
| cas_number | string | Nomor CAS (opsional) |
| function | string | Fungsi bahan |
| percent_internal | number | % komponen dalam bahan baku (total per bahan baku = 100%, divalidasi di form) |

**Tabel 3 — `products`** (header produk)

| Field | Tipe | Keterangan |
|---|---|---|
| id | uuid | ID unik |
| nama_produk | string | Nama produk |
| perusahaan | string | `PT Erfi` atau `PT Heka` — menentukan kop surat dokumen |
| nama_customer | string | Nama customer/klien |
| sediaan | string | Bentuk sediaan |
| warna | string | Warna sediaan |
| kemasan | string | Jenis kemasan (bisa multi-varian) |
| netto | string | Berat/volume netto (bisa multi-varian) |
| no_na_produk | string | Nomor Notifikasi BPOM |
| status_na | enum | `belum_terdaftar` \| `aktif` \| `akan_expired` \| `expired` |
| acc_sampel | date | Tanggal acc sampel |
| tanggal_text_design | date | Tanggal dokumen text design/label |
| teks_marketing | text | Deskripsi produk untuk kemasan/label |
| cara_pakai | text | Instruksi penggunaan untuk kemasan/label |

**Tabel 4 — `product_formula_lines`** (baris formula per produk)

| Field | Tipe | Keterangan |
|---|---|---|
| id | uuid | ID unik |
| product_id | FK → tabel 3 | Produk terkait |
| raw_material_id | FK → tabel 1 | Bahan baku yang dipakai |
| percent_in_formula | number | % w/w dalam formula (total per produk = 100%, divalidasi di form) |

> **Ingredient Report** tidak disimpan sebagai tabel — dihitung *on-the-fly* dari join tabel 2, 3, 4, sehingga selalu sinkron begitu data bahan baku diubah.

### 4.2 Logika Kalkulasi Inti

**Konversi % Nama Dagang → % Ingredient:**
```
% Ingredient (final) = % Nama Dagang (formula) × % Ingredient (komposisi internal bahan) ÷ 100
```

**Penggabungan ingredient sejenis:** setelah semua baris formula di-*expand* ke level INCI, sistem *group-by* nama INCI dan menjumlahkan seluruh kontribusi dari sumber bahan baku manapun — menghilangkan proses penjumlahan manual yang sebelumnya dilakukan di Excel.

**Presisi angka:** seluruh kalkulasi menggunakan tipe `Decimal` (bukan `float` murni) dengan pembulatan eksplisit sebelum ditampilkan, untuk menghindari *floating point noise* (mis. `0.43150000000000005`) maupun *trailing zero* yang tidak perlu (`58.00000` → `58`).

**Validasi otomatis:**
- Total `percent_internal` per bahan baku komposit wajib 100% (validasi real-time di form Bahan Baku).
- Total `percent_in_formula` per produk wajib 100% (indikator visual di Formula Builder).

### 4.3 Modul & Halaman Aplikasi

**Dashboard Produk**
- Ringkasan jumlah produk per status NA (4 kartu: Belum Terdaftar, Aktif, Akan Expired, Expired)
- Tabel produk dengan badge warna status NA dan badge perusahaan (PT Erfi / PT Heka)
- Search bar (nama produk & customer) + filter dropdown (perusahaan, status NA), berjalan di sisi klien tanpa reload
- Tambah, edit, dan hapus produk (dengan konfirmasi)

**Formula Builder**
- Pemilihan bahan baku dari database + input % w/w
- Indikator total persentase formula real-time (wajib 100% untuk disimpan)

**Ingredient Report**
- Tabel hasil breakdown & penggabungan otomatis (Ingredient, Function, % w/w)

**Dokumen Formula Kualitatif & Kuantitatif** (preview cetak/PDF + export Excel)
- **Dokumen 1:** Formula per Nama Dagang (dengan kode bahan baku)
- **Dokumen 2:** Formula murni per Ingredient (INCI, digabung & diurutkan berdasarkan % terbesar)
- **Dokumen 3 — Text Design:** lembar teks label/kemasan (Tanggal, Nama Produk, Netto, No NA, Diproduksi Oleh, Komposisi otomatis dari Dokumen 2, Teks marketing, Cara Pakai)
- Kop surat otomatis mengikuti `perusahaan` produk (logo, nama PT, alamat, email, website)
- Export ke Excel (`.xlsx`) menghasilkan 3 sheet terpisah, dengan:
  - Parsing angka yang locale-proof (menghindari isu `SUM()` gagal akibat perbedaan format desimal koma/titik)
  - Border otomatis dan styling tabel (termasuk tabel info 2 kolom label–nilai)
  - Kop surat & info produk ikut disertakan di setiap sheet

**Admin — Manajemen Bahan Baku**
- CRUD lengkap (tambah, edit, hapus) untuk bahan tunggal maupun komposit dengan baris komponen dinamis
- Validasi total 100% untuk bahan komposit
- Proteksi hapus: bahan baku yang masih dipakai di formula produk manapun tidak bisa dihapus, dengan pesan yang menyebutkan jumlah pemakaian
- Search bar (nama dagang, kode, atau nama INCI di dalamnya) + filter tipe (single/komposit)
- Upload file **MSDS** per bahan baku, disimpan ke Supabase Storage dan dapat diunduh langsung dari tabel

### 4.4 Alur Kerja Pengguna

1. **Admin** mengisi database bahan baku sekali di awal (reusable lintas produk & lintas PT).
2. Pengguna membuat **produk baru** — pilih PT penerbit, isi data administratif dan konten label.
3. Pengguna menyusun **formula** menggunakan bahan baku dari database.
4. Sistem otomatis menghasilkan **Ingredient Report** dan **dokumen Qual-Quan + Text Design** siap cetak/download, dengan kop surat sesuai PT.
5. **Dashboard** memantau status registrasi seluruh produk dari kedua PT sekaligus, dengan pencarian dan filter.

---

## 5. Fase 2a — Manajemen Batch & Dokumen Bahan Baku (Selesai)

Ditambahkan tabel baru untuk mencatat riwayat **kedatangan batch/lot** tiap bahan baku, karena data ini bersifat berubah-ubah (berbeda untuk setiap kali penerimaan barang) — berbeda sifatnya dari data bahan baku itu sendiri yang stabil.

### 5.1 Struktur Data

**Tabel baru — `raw_material_batches`**

| Field | Tipe | Keterangan |
|---|---|---|
| id | uuid | ID unik |
| raw_material_id | FK → `raw_materials` | Bahan baku terkait |
| no_batch | string | Nomor batch/lot dari supplier |
| supplier | string | Nama supplier pengirim |
| harga_per_kg | number | Harga satuan batch ini |
| tanggal_terima_sampel | date | Tanggal sampel diterima QC |
| hasil_pemerian | string | Hasil pemeriksaan pemerian |
| hasil_aroma | string | Hasil pemeriksaan aroma |
| hasil_exp_date | string | Tanggal kedaluwarsa batch ini |
| kesimpulan | string | Diluluskan / ditolak |
| diperiksa_oleh | string | Nama pemeriksa QC |
| disetujui_oleh | string | Nama penyetuju |
| coa_file_url | text | Link file Certificate of Analysis, Supabase Storage |
| halal_batch_file_url | text | Link file Sertifikat Halal batch ini, Supabase Storage |

### 5.2 Fitur

- Form tambah data batch per bahan baku, dengan upload file **CoA** dan **Sertifikat Halal** langsung ke Supabase Storage (bucket `raw-material-docs`)
- Tabel riwayat batch menampilkan badge dokumen (CoA, Halal, MSDS) yang bisa diklik langsung untuk membuka file terkait di tab baru
- MSDS ditampilkan di tabel batch dengan mengambil relasi ke `raw_materials.msds_file_url` (karena MSDS melekat pada bahan baku, bukan per batch)

---

## 6. Fase 2b — Generator Dokumen Bab II (Rancangan)

Bab II Dokumen Informasi Produk terdiri atas empat komponen dengan karakter data yang berbeda:

| # | Komponen | Sifat | Sumber Data |
|---|---|---|---|
| 1 | Checklist Kelengkapan Data | Statis, sama di setiap dokumen | Template tetap |
| 2 | SOP CPKB (Prosedur Tetap Pemeriksaan Bahan Baku) | Tetap, dapat direvisi sewaktu-waktu (perlu versioning) | File terunggah, per PT |
| 3 | Catatan Spesifikasi Bahan Baku | Per bahan baku, stabil (tidak berubah antar batch) | Field baru pada `raw_materials` (belum ditambahkan: Pemerian, Aroma, pH, Viskositas, Masa Kedaluarsa, Cara Penyimpanan) |
| 4 | Catatan Pemeriksaan Bahan Baku + CoA + Halal | Per bahan baku, berubah tiap kedatangan batch/lot | ✅ Sudah tersedia lewat `raw_material_batches` (Fase 2a) |

### 6.1 Sisa Pekerjaan
- Menambahkan field spesifikasi stabil pada `raw_materials` (Pemerian, Aroma, pH, Viskositas, Masa Kedaluarsa, Cara Penyimpanan, Referensi) agar Catatan Spesifikasi Bahan Baku dapat digenerate otomatis
- Tabel baru `sop_documents` untuk menyimpan SOP CPKB dengan versioning (nomor dokumen, nomor revisi, tanggal berlaku, status aktif, per PT)
- Mekanisme pemilihan batch mana yang disertakan saat satu bahan baku memiliki riwayat beberapa batch
- Engine penggabungan seluruh komponen menjadi satu dokumen Word/PDF (kandidat: `python-docx` di backend)

### 6.2 Alur Generate (Rencana)

```
1. Ambil seluruh raw_material yang dipakai pada formula produk
2. Untuk setiap raw_material:
   a. Halaman Spesifikasi  → dari raw_materials (field baru)
   b. Halaman Pemeriksaan  → dari raw_material_batches (batch terpilih/terbaru)
   c. CoA + Halal          → lampiran dari raw_material_batches
3. Sisipkan SOP CPKB versi aktif sesuai PT produk
4. Gabungkan menjadi satu dokumen Word/PDF:
   Checklist → SOP CPKB → [Spesifikasi + Pemeriksaan + CoA + Halal] × tiap bahan baku
```

---

## 7. Manfaat yang Diharapkan

- **Efisiensi waktu**: menghilangkan proses perhitungan dan penjumlahan manual di Excel untuk setiap produk baru, di kedua perusahaan.
- **Akurasi**: mengeliminasi human error dalam kalkulasi cascading percentage, penjumlahan ingredient sejenis, dan pembulatan angka.
- **Konsistensi**: satu sumber data bahan baku (single source of truth) untuk seluruh produk lintas PT, dengan kop surat yang otomatis menyesuaikan.
- **Skalabilitas**: fondasi data yang sama menjadi basis penyusunan Bab II, III, dan IV tanpa input ulang.
- **Traceability**: kode bahan baku, riwayat status NA, dan riwayat batch/CoA/MSDS/Halal terdokumentasi rapi dan mudah ditelusuri langsung dari aplikasi.

---

*Dokumen ini diperbarui mengikuti perkembangan aktual aplikasi. Fase 1 dan 2a telah selesai dan berjalan di lingkungan produksi; Fase 2b masih dalam tahap perancangan struktur data sebelum implementasi.*
