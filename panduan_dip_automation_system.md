# Panduan Lengkap & Komprehensif: DIP Automation System

**TL;DR:** DIP Automation System adalah aplikasi web untuk sentralisasi data bahan baku, manajemen formula, dan otomatisasi pembuatan Dokumen Informasi Produk (DIP) kosmetik sesuai pedoman BPOM dan ASEAN Cosmetic Directive (ACD). Mendukung dua entitas hukum (PT Erfi & PT Heka) dengan data terpisah per perusahaan, menerapkan RBAC (Admin/Staff), menyimpan berkas di Supabase Storage, dan menghasilkan output berupa PDF gabungan atau folder ZIP terstruktur untuk Bab II. Fitur penting: Formula Builder (total harus 100% w/w), manajemen batch & CoA, public permalink untuk verifikasi BPOM, audit trail (`activity_logs`), pembatasan unggah 10 MB per file, serta integrasi teknis dengan `xhtml2pdf`, `pypdf`, dan SheetJS.

---

Dokumen ini merupakan panduan operasional dan dokumentasi teknis komprehensif untuk penggunaan **DIP Automation System** (Sistem Otomasi Dokumen Informasi Produk Kosmetik sesuai standar BPOM dan *ASEAN Cosmetic Directive / ACD*). Panduan ini ditujukan bagi tim **BPOM/Regulatory**, **Research & Development (RnD)**, **Quality Control (QC)**, serta **Administrator** di **PT Erfi** dan **PT Heka**.

---

## Daftar Isi
1. [Pendahuluan & Konsep Dasar](#1-pendahuluan--konsep-dasar)
2. [Akses, Keamanan & Pengelolaan User (RBAC)](#2-akses-keamanan--pengelolaan-user-rbac)
3. [Diagram & Arsitektur Alur Kerja Aplikasi](#3-diagram--arsitektur-alur-kerja-aplikasi)
4. [Panduan Operasional Tahap demi Tahap](#4-panduan-operasional-tahap-demi-tahap)
5. [Matriks Validasi, Status & Logika Bisnis](#5-matriks-validasi-status--logika-bisnis)
6. [Spesifikasi Teknis & Integrasi File Storage](#6-spesifikasi-teknis--integrasi-file-storage)
7. [FAQ & Troubleshooting](#7-faq--troubleshooting)
8. [Panduan Pemeliharaan & Bantuan](#8-panduan-pemeliharaan--bantuan)

---

## 1. Pendahuluan & Konsep Dasar

### 1.1 Latar Belakang & Tujuan Sistem
Sebelum adanya DIP Automation System, penyusunan Dokumen Informasi Produk (DIP) Kosmetik dilakukan secara manual melalui aplikasi pengolah kata dan *spreadsheet*. Proses manual ini rentan terhadap ketidaksesuaian data, duplikasi informasi, inkonsistensi penomoran dokumen, dan memakan waktu lama saat penyusunan berkas perizinan BPOM.

**DIP Automation System** dibangun sebagai solusi sentralisasi data dan otomatisasi pembuatan berkas DIP secara digital. Tujuan utama sistem ini adalah:
- **Sentralisasi Master Data:** mengintegrasikan seluruh database bahan baku, komponen INCI, batch CoA, sertifikat halal, MSDS, serta data legalitas perusahaan.
- **Otomatisasi Kompilasi Dokumen:** menggenerasi dokumen Bab I (Administrasi), Bab II (Mutu Bahan Baku), Bab III (Mutu Produk Jadi), dan Bab IV (Keamanan Produk) secara otomatis dalam bentuk PDF siap cetak atau arsip ZIP.
- **Transparansi & Efisiensi Verifikasi:** menyediakan *Public Link Verification Hub* yang aman untuk peninjauan langsung oleh verifikator BPOM tanpa proses penyerahan berkas fisik berulang.
- **Akurasi & Integritas Data:** menjamin perhitungan persentase formula (*Qualitative-Quantitative*) serta breakdown komponen bahan baku akurat 100%.

### 1.2 Standar Regulatori (BPOM & ACD)
Sistem ini dirancang mengacu pada pedoman penyusunan Dokumen Informasi Produk sesuai **Pedoman Teknis Dokumentasi Informasi Produk Kosmetik BPOM RI** dan pedoman **ASEAN Cosmetic Directive (ACD)**. Setiap bab yang dihasilkan memuat struktur standar:
- **Bab I:** Data Administratif dan Ringkasan Produk.
- **Bab II:** Data Mutu dan Keamanan Bahan Kosmetika.
- **Bab III:** Data Mutu Produk Jadi.
- **Bab IV:** Laporan Keamanan Produk (*Safety Assessment*) & Data Pendukung Klaim.

### 1.3 Perusahaan Multientitas (PT Erfi & PT Heka)
Aplikasi mendukung pengelolaan data untuk **dua perusahaan sekaligus (PT Erfi dan PT Heka)** dalam satu platform terpadu.
- Setiap bahan baku memiliki dokumen spesifikasi, MSDS, dan dokumen batch (CoA, sertifikat halal, catatan pemeriksaan) yang dikelola **terpisah per perusahaan** (`PT Erfi` / `PT Heka`) — karena satu bahan baku fisik yang sama bisa punya spesifikasi/dokumen berbeda tergantung siapa yang membeli.
- Identitas bahan baku (nama dagang, kode, komponen INCI) tetap **satu sumber data**, tidak diduplikasi per perusahaan.
- Kop surat dokumen dan legalitas (NIB, sertifikat CPKB, SOP CPKB) mengacu pada entitas perusahaan yang dipilih saat pembuatan produk atau saat input data.

---

## 2. Akses, Keamanan & Pengelolaan User (RBAC)

### 2.1 Peran Pengguna (User Roles)
Sistem menerapkan mekanisme *Role-Based Access Control (RBAC)* dengan 2 tingkat hak akses:

| Peran | Level | Deskripsi Hak Akses |
|---|---|---|
| **Admin** | Full Access | Hak akses penuh ke seluruh fitur aplikasi, termasuk **Panel Manajemen User** (`/admin/users`) untuk menambah akun baru, reset password, mengubah role pengguna, dan menghapus akun. |
| **Staff** | Operational Access | Hak akses operasional harian: mengelola bahan baku, batch, brand, membuat dan mengedit produk, meracik formula, mengunggah dokumen Bab I–IV, serta membuat Form Pengajuan Sample (FSP). *Tidak memiliki akses ke panel admin user.* |

> ⚠️ **Catatan Keamanan:** Fitur pendaftaran mandiri (*Self-Register*) **dimatikan** untuk mencegah akses publik yang tidak terotorisasi. Pendaftaran akun baru wajib dilakukan oleh Admin melalui panel admin.

### 2.2 Autentikasi Dual & HTTP-Only Cookie JWT
- **Login Dual-Identifier:** pengguna dapat masuk menggunakan **Email** maupun **Username**.
- **Sesi Keamanan JWT:** token autentikasi disimpan dalam cookie `HTTP-Only` (`access_token`, `SameSite=Lax`), melindungi dari pencurian token lewat *Cross-Site Scripting (XSS)*. Masa berlaku sesi adalah **24 jam**, setelah itu pengguna perlu login ulang.
- **Deteksi Sesi Expired:** jika sesi habis, sistem menampilkan peringatan (*session expired*) dan mengarahkan kembali ke halaman login secara otomatis.

### 2.3 Panel Admin User (`/admin/users`) & Audit Logging
Melalui menu **Kelola User** (khusus role Admin), Admin dapat:
1. **Tambah User Baru** — mendaftarkan email, username, password awal, serta role (`admin` / `staff`).
2. **Reset Password** — mengubah password akun pengguna.
3. **Ubah Role Pengguna** — mengalihkan role antara Staff dan Admin.
4. **Hapus User** — menghapus akses akun dari database.
5. **Activity Log Integration** — seluruh aktivitas penting (pembuatan/pengeditan/penghapusan bahan baku & produk) tercatat pada tabel `activity_logs` di Supabase, dan sekaligus ditampilkan di terminal server dengan format timestamp WIB (*Asia/Jakarta*) untuk pemantauan cepat.

---

## 3. Diagram & Arsitektur Alur Kerja Aplikasi

### 3.1 Alur Kerja Utama

```
TAHAP 1 — SETUP MASTER DATA
  • Input Bahan Baku (Nama Dagang, Kode, Tipe, Produsen, komponen INCI/CAS)
  • Upload Spesifikasi & MSDS per perusahaan (PT Erfi / PT Heka)
  • Input Brand & upload Hak/Lisensi Merk
        |
        v
TAHAP 2 — MANAJEMEN BATCH BAHAN BAKU
  • Input Batch (No. Batch, tanggal terima/sampling/ED, per perusahaan)
  • Upload CoA, Sertifikat Halal, Catatan Pemeriksaan & hasil uji lab aktual
        |
        v
TAHAP 3 — PEMBUATAN PRODUK & FORMULA
  • Tambah Produk (perusahaan, brand, customer, sediaan, netto)
  • Racik formula (Formula Builder) — total wajib 100.000%
  • Sistem otomatis breakdown komponen INCI dari formula
        |
        v
TAHAP 4 — DOKUMENTASI BAB I - IV (multi-tab dalam 1 halaman edit produk)
  • Informasi Dasar & legalitas NA BPOM
  • Bab I: kelengkapan administrasi (NIB, CPKB, dst)
  • Bab II: mutu bahan baku (otomatis narik dari formula + batch)
  • Bab III: mutu produk jadi
  • Bab IV: keamanan produk & klaim
        |
        v
TAHAP 5 — GENERASI & EKSPOR DOKUMEN
  • Bab I, III, IV -> PDF gabungan
  • Bab II -> PDF gabungan ATAU folder ZIP per bahan baku
  • Formula -> Export Excel (Qual-Quan) & cetak PDF
        |
        v
TAHAP 6 — SHARING LINK PUBLIK VERIFIKATOR BPOM (opsional)
  • Generate link publik /dip/[slug-nama-produk]-[uuid produk]
  • Verifikator BPOM preview/download dokumen tanpa login
  • Setiap akses tercatat otomatis (IP, user-agent, waktu WIB)
```

### 3.2 Siklus Hidup Data Produk
Satu produk berjalan melalui siklus: **dibuat -> formula diracik -> dokumen Bab I-IV dilengkapi bertahap -> status NA BPOM dipantau otomatis -> dokumen digenerate -> (opsional) dibagikan ke verifikator lewat link publik**. Setiap tahap bisa diisi bertahap/tidak berurutan — sistem tidak memaksa satu bab harus 100% lengkap sebelum bab lain dikerjakan, tapi dashboard akan menandai bab mana yang belum lengkap.

---

## 4. Panduan Operasional Tahap demi Tahap

### 4.1 Tahap 1 — Pengelolaan Master Data Bahan Baku & Legalitas Per Perusahaan
Sebelum membuat formula produk, seluruh data bahan baku wajib terdaftar di dalam database.

1. Buka menu **Bahan Baku** dari navigasi utama (`/raw-materials`).
2. Klik tombol **+ Tambah Bahan Baku Baru**.
3. **Isi Identitas Bahan Baku:**
   - Nama Dagang (misal: *Niacinamide PC*, *Glycerin 99.5%*).
   - Kode Bahan Baku (misal: *RM-001*, harus unik).
   - Tipe (*Single* atau *Komposit*).
   - Produsen (opsional).
4. **Isi Komposisi Komponen INCI** (kalau tipe *Komposit*): Nama INCI, Nomor CAS, Fungsi, dan persentase internal komponen dalam bahan baku.
5. **Isi Dokumen & Spesifikasi Per Perusahaan** — pilih tab **PT Erfi** atau **PT Heka**, lalu lengkapi:
   - Spesifikasi standar (pemerian, aroma, pH, viskositas, masa kedaluwarsa, cara penyimpanan, referensi).
   - Upload **MSDS** (PDF, maks 10 MB).
   - Upload **PDF Spesifikasi Asli dari Supplier** (opsional — kalau ada, ini yang dipakai langsung saat generate ZIP Bab II, bukan versi hasil ketikan).
   - Boleh diisi salah satu perusahaan dulu, tab satunya bisa disusulkan belakangan.
6. **Cek Matriks Kelengkapan Dokumen** — gunakan tab **Cek Kelengkapan Dokumen** pada halaman Bahan Baku untuk melihat status per perusahaan (lengkap dengan PDF, terisi teks saja, atau belum ada), sekaligus preview PDF langsung tanpa pindah halaman.

> 💡 **Tambah Bahan Baku Cepat:** kalau lagi meracik formula di halaman Edit Produk dan bahan baku yang dicari belum terdaftar, tidak perlu pindah halaman — gunakan tombol **"Bahan baku belum ada? Tambah baru"** di dropdown pencarian bahan baku pada tab Bab 2. Cukup isi identitas dasar (nama, kode, tipe, produsen), bahan baku langsung tersimpan dan otomatis terpilih di baris formula. Detail spesifikasi, MSDS, dan komponen INCI tetap dilengkapi belakangan di halaman Bahan Baku.

---

### 4.2 Tahap 2 — Manajemen Batch Bahan Baku & Hasil Uji QC
Setiap kedatangan bahan baku wajib dicatat sebagai batch, dan di-scope ke perusahaan yang menerimanya:

1. Pada halaman **Bahan Baku**, buka modal **Tambah Batch**.
2. Pilih **Perusahaan** (PT Erfi / PT Heka) — batch, CoA, dan halal ini khusus untuk perusahaan yang dipilih.
3. Isi data administrasi batch: Nomor Batch, Supplier, Tanggal Terima Sampel, Tanggal Sampling, Tanggal Kedaluwarsa (ED).
4. **Unggah lampiran PDF batch:**
   - **CoA (Certificate of Analysis)** — wajib.
   - **Sertifikat Halal** — opsional.
   - **Laporan Pemeriksaan Aktual** — opsional; kalau ada dokumen fisik/scan hasil pemeriksaan, upload di sini (PDF ini yang dipakai langsung di ZIP Bab II, mengganti versi hasil ketikan manual).
5. **Input Parameter Uji Laboratorium Aktual** (kalau tidak upload laporan PDF di atas): hasil pemeriksaan fisik/kimia aktual, kesimpulan, serta nama yang memeriksa (QC) dan menyetujui (QA).

---

### 4.3 Tahap 3 — Manajemen Brand & Lisensi Merk
1. Akses menu **Kelola Merk** (`/brands`).
2. **Tambah Brand Baru** — input nama brand/merk serta produsen pemilik brand.
3. **Upload Dokumen Hak & Lisensi Merk** (PDF) — dokumen ini otomatis disematkan sebagai lampiran pendukung di **Bab I** untuk semua produk yang menggunakan brand tersebut.

---

### 4.4 Tahap 4 — Pembuatan Produk & Formula Builder (Qualitative-Quantitative)

#### Pembuatan Produk Baru
1. Klik **+ Tambah Produk Baru** di Dashboard.
2. Isi info awal: Nama Produk, Perusahaan (`PT Erfi` / `PT Heka`), Nama Customer, Brand, Sediaan, Kemasan, Netto.

#### Meracik Formula
1. Masuk ke tab **Bab 2** pada halaman **Edit Informasi & Dokumen Produk**.
2. Tambahkan bahan baku satu per satu (cari lewat kolom pencarian) beserta persentase penggunaan (% w/w).
3. **Validasi Formula** — total persentase seluruh bahan wajib tepat **100.000%**; indikator total akan berwarna merah kalau belum pas, hijau kalau sudah tepat.
4. Sistem otomatis breakdown komponen INCI & CAS Number dari seluruh bahan baku dalam formula.
5. **Export Laporan Formula (Qual-Quan):** tombol *Export Excel* (`.xlsx`, via SheetJS di sisi klien) dan *Cetak PDF / Print* tersedia di halaman Qualitative-Quantitative.

---

### 4.5 Tahap 5 — Penyusunan Dokumen Bab I – IV (Edit Produk Multi-Tab)

Halaman **Edit Informasi & Dokumen Produk** (`/products/{product_id}/edit`) menggabungkan semua pengaturan produk dalam **5 tab**: *Informasi Dasar*, *Bab 1*, *Bab 2*, *Bab 3*, *Bab 4* — sehingga tidak perlu berpindah-pindah halaman.

**Tab Informasi Dasar** — data umum produk, Nomor Notifikasi BPOM (No. NA), dan Tanggal Aktif NA. Status legalitas NA (Aktif / Akan Expired / Expired / Belum Terdaftar) dihitung & diperbarui otomatis dari tanggal ini.

**Tab Bab 1 (Kelengkapan Administrasi)** — NIB, Sertifikat CPKB, Surat Tidak Pidana, Surat Notifikasi BPOM. Hak & Lisensi Merk diambil otomatis dari data Brand. Tersedia tombol *Preview* dan *Download PDF*.

**Tab Bab 2 (Mutu & Keamanan Bahan Kosmetika)** — susunan formula produk dan status kelengkapan dokumen tiap bahan baku, SOP CPKB penanganan bahan baku per perusahaan. Tersedia *Preview*, *Download PDF Gabungan*, dan *Download Folder ZIP*.

**Tab Bab 3 (Mutu Produk Jadi)** — spesifikasi fisik/kimia produk jadi, metode pembuatan, sistem penomoran batch, hasil stabilitas. Tersedia *Preview* & *Download PDF*.

**Tab Bab 4 (Keamanan Produk)** — laporan *safety assessment*, CV *safety assessor*, data klaim, monitoring efek samping (NIES), desain kemasan primer/sekunder. Tersedia *Preview* & *Download PDF*.

> ⚠️ Setiap dokumen yang belum diunggah ditandai badge **"PDF belum terisi"**. Upload PDF dibatasi maksimal **10 MB per file**; validasi dilakukan di sisi browser (agar terasa cepat) *dan* di sisi server (sebagai jaring pengaman terakhir yang tidak bisa dilewati).

---

### 4.6 Tahap 6 — Generasi & Ekspor Dokumen DIP (PDF Gabungan vs Folder ZIP)

Sistem menggunakan kombinasi **`xhtml2pdf`** (render HTML ke PDF) dan **`pypdf`** (menggabungkan/merge PDF) untuk merangkai dokumen DIP beserta lampirannya.

**Format PDF Gabungan** (Bab I, III, IV, dan Bab II versi standar) — sistem menyusun halaman cover/checklist, lalu menggabungkan lampiran dari Supabase Storage menjadi **satu file PDF utuh**.

**Format Folder ZIP** (khusus Bab II) — karena Bab II sering punya banyak lampiran tebal (CoA, Halal, MSDS per bahan baku), tersedia opsi **Download ZIP** yang menghasilkan folder terorganisir *per bahan baku*, isinya 5 file terpisah:
1. `1_Spesifikasi_Bahan_Baku.pdf` — PDF asli dari supplier kalau ada, atau hasil generate dari data yang diketik.
2. `2_Catatan_Pemeriksaan_Bahan_Baku.pdf` — PDF laporan pemeriksaan asli kalau ada, atau hasil generate dari data aktual.
3. `3_CoA.pdf`
4. `4_Sertifikat_Halal.pdf`
5. `5_MSDS.pdf`

Kalau salah satu dokumen belum tersedia, file `PERHATIAN.txt` otomatis disertakan di folder bahan baku itu, menandai dokumen apa yang masih kurang.

---

### 4.7 Tahap 7 — Portal Public Link & Sharing Verifikator BPOM

Untuk mempermudah verifikasi BPOM tanpa perlu akun/login ke sistem internal, setiap produk punya **Public Link Hub**:

**Format URL:** `/dip/[slug-nama-produk]-[uuid-produk]`
*Contoh:* `.../dip/sunscreen-serum-spf-50-e623d2e4-1234-5678-9abc-def012345678`

- **Bebas login** — bisa dibuka langsung oleh verifikator BPOM kapan saja.
- **Bagian "slug nama produk" di depan URL cuma kosmetik** — yang beneran divalidasi server cuma UUID 36-karakter di bagian akhir URL. UUID inilah yang berfungsi sebagai "kunci akses" (*unguessable URL*) — mustahil ditebak, sehingga cuma orang yang benar-benar dikasih link yang bisa membuka dokumennya. **Jangan pernah minta URL diganti murni berbasis nama produk** — itu akan menghilangkan proteksi ini, karena nama produk gampang ditebak/diketahui.
- **Akses lengkap dokumen** — verifikator bisa preview PDF, download PDF, maupun download ZIP Bab II secara mandiri.
- **Audit logging otomatis** — setiap kali halaman publik dibuka, sistem mencatat alamat IP, User-Agent browser, dan timestamp WIB ke tabel `public_link_audits` (dengan fallback ke `activity_logs` kalau tabel khusus belum tersedia), sekaligus dicetak ke terminal server secara real-time.

---

### 4.8 Tahap 8 — Manajemen Formulir Pengajuan Sample (FSP)

Modul khusus pengelolaan **Formulir Pengajuan Sample Produk (FSP)** (`/sample-submissions`):

1. **Pembuatan FSP Baru** — menu **Pengajuan Sample**, klik **+ Form Baru**.
2. **Auto-Generate Kode FSP** — format `FSP/DD-MM-YYYY/X.Y`, di mana `X` = nomor urut pengajuan pada hari itu, `Y` = nomor revisi (dimulai dari `1` untuk pengajuan awal).
3. **Manajemen Revisi** — saat FSP yang sudah ada diedit & disimpan ulang, nomor revisi (`Y`) naik otomatis.
4. **Preview & Cetak** — FSP bisa dipreview dengan tampilan siap cetak/simpan ke PDF (`/sample-submissions/preview/{id}`).

---

## 5. Matriks Validasi, Status & Logika Bisnis

### 5.1 Monitoring Otomatis Status Legalitas NA BPOM
Status Notifikasi BPOM (NA) dihitung otomatis dari `tanggal_aktif_na`:
- Masa berlaku standar NA BPOM: **3 tahun** sejak tanggal aktif.
- 🟢 **Aktif** — masih lebih dari 180 hari (~6 bulan) sebelum expired.
- 🟡 **Akan Expired** — sisa masa berlaku ≤ 180 hari.
- 🔴 **Expired** — sudah melewati 3 tahun sejak tanggal aktif.
- ⚪ **Belum Terdaftar** — tanggal aktif NA belum diisi (status manual dipakai sebagai fallback).

### 5.2 Matriks Kelengkapan DIP & Indikator Progress
Di Dashboard, tiap produk punya indikator kelengkapan (`progress_pct`) yang dihitung dari pemenuhan berkas wajib:
- **Bab I** — dianggap lengkap kalau file Notifikasi BPOM sudah diunggah.
- **Bab II** — dianggap lengkap kalau produk sudah punya formula (minimal 1 baris bahan baku).
- **Bab III** — rasio dari 7 dokumen wajib (metode pembuatan, sistem penomoran batch, spek produk jadi, spek pengemas, laporan uji SIG, protokol stabilitas, hasil stabilitas).
- **Bab IV** — rasio dari 5 dokumen wajib (laporan keamanan, monitoring efek samping, data klaim, desain primer, desain sekunder).

### 5.3 Aturan Proteksi Penghapusan Data
- **Perlindungan Bahan Baku** — sistem **melarang** penghapusan bahan baku yang masih dipakai di formula produk aktif. Bahan baku harus dilepas dari formula dulu sebelum dihapus dari master data.
- **Perlindungan Log Aktivitas** — nama produk/bahan baku yang dihapus tetap direkam di `activity_logs` sebelum baris datanya benar-benar hilang, supaya riwayat aktivitas tetap informatif walau data aslinya sudah tidak ada.

---

## 6. Spesifikasi Teknis & Integrasi File Storage

### 6.1 Limitasi Ukuran File Upload
- Batas maksimal ukuran file yang diunggah: **10 MB per file PDF**.
- Kalau file yang diunggah melebihi batas ini, sistem menangkap error HTTP 413 (*Content Too Large*) dan mengarahkan kembali pengguna ke halaman asal dengan pesan peringatan yang jelas — baik saat validasi gagal di sisi browser maupun kalau entah bagaimana lolos dan baru tertangkap di sisi server.

### 6.2 Integrasi Supabase Storage & PostgreSQL Database
- **Database:** Supabase PostgreSQL, tabel-tabel utama meliputi `products`, `brands`, `raw_materials`, `raw_material_components`, `raw_material_batches`, `raw_material_company_docs`, `product_formula_lines`, `sample_submissions`, `profiles`, `activity_logs`, dan `public_link_audits`.
- **Object Storage:** file PDF (MSDS, CoA, Halal, NIB, CPKB, dst) disimpan di Supabase Storage. Sebagian besar diakses lewat public URL; khusus di halaman Public Hub verifikator BPOM, tautan file bisa memakai *signed URL* sementara (kedaluwarsa otomatis) sebagai lapisan keamanan tambahan.

### 6.3 Audit Trail System (`activity_logs`) & Server Logging
- Setiap perubahan data (`create`, `update`, `delete`) pada bahan baku dan produk dicatat otomatis ke tabel `activity_logs`, lengkap dengan siapa pelakunya, jenis objek, ID target, dan detail field yang berubah (nilai lama vs baru untuk field teks; catatan "file diganti" untuk field dokumen).
- Terminal server (Uvicorn/Render) menampilkan log yang sama secara real-time dengan format timestamp **WIB (Asia/Jakarta)** — berguna untuk pengecekan cepat, tapi diingat log Render sendiri **cuma disimpan 7 hari**; untuk riwayat jangka panjang selalu rujuk ke tabel `activity_logs`.

---

## 7. FAQ & Troubleshooting

**Q1: Mengapa spesifikasi bahan baku dan MSDS dipisahkan antara PT Erfi dan PT Heka?**
PT Erfi dan PT Heka adalah dua badan hukum terpisah dengan sertifikat CPKB dan standar mutu masing-masing. Dokumen yang dilampirkan ke BPOM harus mencantumkan kop surat dan legalitas entitas yang tepat — data yang sama untuk keduanya bisa jadi bukan hal yang benar.

**Q2: Kenapa lebih baik pakai Download Folder (ZIP) untuk Bab II dibanding PDF gabungan?**
Kalau lampiran bahan baku sangat banyak/tebal (apalagi MSDS yang bisa puluhan halaman), ZIP lebih ringan diproses dan lebih mudah ditelusuri per bahan baku dibanding satu PDF raksasa.

**Q3: Bagaimana mengatasi pesan "Sesi Anda Telah Berakhir"?**
Cookie sesi (JWT) sudah kedaluwarsa (masa berlaku 24 jam). Silakan login ulang.

**Q4: Apakah link publik verifikator BPOM aman dari kebocoran data produk lain?**
Aman — setiap link memakai kombinasi slug nama produk (kosmetik) dan UUID acak 36-karakter yang divalidasi di server (*unguessable*). Portal publik hanya menampilkan data 1 produk sesuai UUID pada URL tersebut, dan setiap akses tercatat di audit log.

**Q5: Kenapa persentase di Formula Builder menunjukkan angka merah / tidak 100%?**
Standar BPOM mengharuskan total persentase formula kosmetik tepat 100.000% (w/w). Periksa kembali persentase bahan pelarut (misalnya *Aqua/Water*) agar akumulasi formula pas 100%.

**Q6: Kenapa upload file ditolak padahal ukurannya kelihatan kecil?**
Kemungkinan file melebihi 10 MB (cek ulang ukuran filenya), atau formatnya bukan PDF — sistem cuma menerima PDF untuk semua jenis lampiran dokumen.

---

## 8. Panduan Pemeliharaan & Bantuan

Jika menemukan kendala teknis, bug, atau butuh penyesuaian fitur baru pada DIP Automation System:
1. Catat langkah-langkah kejadian (*reproduction steps*) dan pesan error yang muncul di layar.
2. Ambil *screenshot* layar yang bermasalah.
3. Hubungi Tim Pengembang IT / System Administrator internal.

*DIP Automation System dipelihara secara berkala untuk menjamin kesesuaian dengan regulasi BPOM RI dan keamanan sistem.*