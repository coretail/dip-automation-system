# Panduan Lengkap & Komprehensif: DIP Automation System

Dokumen ini merupakan panduan operasional dan dokumentasi teknis komprehensif untuk penggunaan **DIP Automation System** (Sistem Otomasi Dokumen Informasi Produk Kosmetik sesuai standar BPOM dan *ASEAN Cosmetic Directive / ACD*). Panduan ini ditujukan bagi tim **BPOM/Regulatory**, **Research & Development (RnD)**, **Quality Control (QC)**, serta **Administrator** di **PT Erfi** dan **PT Heka**.

---

## Daftar Isi
1. [Pendahuluan & Konsep Dasar](#1-pendahuluan--konsep-dasar)
   - 1.1 Latar Belakang & Tujuan Sistem
   - 1.2 Standar Regulatori (BPOM & ACD)
   - 1.3 Perusahaan Multientitas (PT Erfi & PT Heka)
2. [Akses, Keamanan & Pengelolaan User (RBAC)](#2-akses-keamanan--pengelolaan-user-rbac)
   - 2.1 Peran Pengguna (Admin vs Staff)
   - 2.2 Autentikasi Dual (Username & Email) & HTTP-Only Cookie JWT
   - 2.3 Panel Admin User (`/admin/users`) & Audit Logging
3. [Diagram & Arsitektur Alur Kerja Aplikasi](#3-diagram--arsitektur-alur-kerja-aplikasi)
   - 3.1 Flowchart Alur Kerja Utama
   - 3.2 Siklus Hidup Data Produk DIP
4. [Panduan Operasional Tahap demi Tahap](#4-panduan-operasional-tahap-demi-tahap)
   - 4.1 Tahap 1 — Pengelolaan Master Data Bahan Baku & Legalitas Per Perusahaan
   - 4.2 Tahap 2 — Manajemen Batch Bahan Baku & Hasil Uji QC
   - 4.3 Tahap 3 — Manajemen Brand & Lisensi Merk
   - 4.4 Tahap 4 — Pembuatan Produk & Formula Builder (Qualitative-Quantitative)
   - 4.5 Tahap 5 — Penyusunan Dokumen Komprehensif Bab I – IV (Edit Produk Multi-Tab)
   - 4.6 Tahap 6 — Generasi & Ekspor Dokumen DIP (PDF Gabungan vs Folder ZIP)
   - 4.7 Tahap 7 — Portal Public Link & Sharing Verifikator BPOM
   - 4.8 Tahap 8 — Manajemen Formulir Pengajuan Sample (FSP)
5. [Matriks Validasi, Status & Logika Bisnis](#5-matriks-validasi-status--logika-bisnis)
   - 5.1 Monitoring Otomatis Status Legalitas NA BPOM
   - 5.2 Matriks Kelengkapan DIP & Indikator Progress (%)
   - 5.3 Aturan Proteksi Penghapusan Data (Preventing Orphaned Data)
6. [Spesifikasi Teknis & Integrasi File Storage](#6-spesifikasi-teknis--integrasi-file-storage)
   - 6.1 Limitasi Ukuran File Upload (Maksimal 10 MB per PDF)
   - 6.2 Integrasi Supabase Storage & PostgreSQL Database
   - 6.3 Audit Trail System (`activity_logs`) & Server Logging (WIB)
7. [FAQ & Troubleshooting](#7-faq--troubleshooting)
8. [Panduan Pemeliharaan & Bantuan](#8-panduan-pemeliharaan--bantuan)

---

## 1. Pendahuluan & Konsep Dasar

### 1.1 Latar Belakang & Tujuan Sistem
Sebelum adanya DIP Automation System, penyusunan Dokumen Informasi Produk (DIP) Kosmetik dilakukan secara manual melalui aplikasi pengolah kata dan *spreadsheets*. Proses manual ini rentan terhadap ketidaksesuaian data, duplikasi informasi, inkonsistensi penomoran dokumen, dan memakan waktu lama saat penyusunan berkas perizinan BPOM.

**DIP Automation System** dibangun sebagai solusi sentralisasi data dan otomatisasi pembuatan berkas DIP secara digital. Tujuan utama dari sistem ini adalah:
- **Sentralisasi Master Data:** Mengintegrasikan seluruh database bahan baku, komponen INCI, batch CoA, sertifikat halal, MSDS, serta data legalitas perusahaan.
- **Otomatisasi Kompilasi Dokumen:** Menggenerasi dokumen Bab I (Administrasi), Bab II (Mutu Bahan Baku), Bab III (Mutu Produk Jadi), dan Bab IV (Keamanan Produk) secara otomatis dalam bentuk PDF siap cetak atau arsip ZIP.
- **Transparansi & Efisiensi Verifikasi:** Menyediakan *Public Link Verification Hub* yang aman untuk peninjauan langsung oleh verifikator BPOM tanpa proses penyerahan berkas fisik berulang.
- **Akurasi & Integritas Data:** Menjamin seluruh perhitungan persentase formula (*Qualitative-Quantitative*) serta breakdown komponen bahan baku akurat 100%.

### 1.2 Standar Regulatori (BPOM & ACD)
Sistem ini dirancang dengan mengacu pada pedoman penyusunan Dokumen Informasi Produk sesuai **Pedoman Teknis Dokumentasi Informasi Produk Kosmetik BPOM RI** dan pedoman **ASEAN Cosmetic Directive (ACD)**. Setiap bab yang dihasilkan memuat struktur standar:
- **Bab I:** Data Administratif dan Ringkasan Produk.
- **Bab II:** Data Mutu dan Keamanan Bahan Kosmetika.
- **Bab III:** Data Mutu Produk Jadi.
- **Bab IV:** Laporan Keamanan Produk (Safety Assessment) & Data Pendukung Klaim.

### 1.3 Perusahaan Multientitas (PT Erfi & PT Heka)
Aplikasi mendukung pengelolaan data untuk **dua perusahaan sekaligus (PT Erfi dan PT Heka)** dalam satu platform terpadu.
- Setiap bahan baku memiliki dokumen spesifikasi, MSDS, dan CoA supplier yang dikelola terpisah per perusahaan (`PT Erfi` / `PT Heka`).
- Kop surat dokumen, penomoran SOP CPKB, dan surat pernyataan yang digenerasi otomatis akan mengacu pada entitas perusahaan yang dipilih saat pembuatan produk.

---

## 2. Akses, Keamanan & Pengelolaan User (RBAC)

### 2.1 Peran Pengguna (User Roles)
Sistem menerapkan mekanisme *Role-Based Access Control (RBAC)* dengan 2 tingkat hak akses:

| Peran | Level | Deskripsi Hak Akses |
|---|---|---|
| **Admin** | Full Access | Memiliki hak akses penuh ke seluruh fitur aplikasi, termasuk **Panel Manajemen User** (`/admin/users`) untuk menambah akun baru, reset password, mengubah role pengguna, dan menghapus akun. |
| **Staff** | Operational Access | Memiliki hak akses operasional harian: mengelola bahan baku, batch, brand, membuat dan mengedit produk, meracik formula, mengunggah dokumen Bab I-IV, serta membuat Form Pengajuan Sample (FSP). *Tidak memiliki akses ke panel admin user.* |

> ⚠️ **Catatan Keamanan:** Fitur pendaftaran mandiri (*Self-Register*) **ditiadakan/dimatikan** untuk mencegah akses publik yang tidak terotorisasi. Pendaftaran akun baru wajib dilakukan oleh Admin melalui panel admin.

### 2.2 Autentikasi Dual & HTTP-Only Cookie JWT
- **Login Dual-Identifier:** Pengguna dapat masuk menggunakan **Email** maupun **Username** (nama lengkap). Jika menginput nama pengguna tanpa tanda `@`, sistem akan mencari profil pengguna terkait atau mencocokkan akun secara otomatis.
- **Sesi Keamanan JWT:** Token autentikasi disimpan dalam cookie berjenis `HTTP-Only` (`access_token` dengan flag `SameSite=Lax`). Hal ini melindungi token dari ancaman pencurian *Cross-Site Scripting (XSS)*.
- **Deteksi Sesi Expired:** Jika masa berlaku sesi habis, sistem akan memberikan notifikasi peringatan (*session expired*) dan mengarahkan pengguna kembali ke halaman login secara aman.

### 2.3 Panel Admin User (`/admin/users`) & Audit Logging
Melalui menu **Kelola User** (khusus role Admin), Admin dapat melakukan:
1. **Tambah User Baru:** Mendaftarkan email, username, password awal, serta role (`admin` / `staff`).
2. **Reset Password:** Mengubah password akun pengguna jika lupa atau diperlukan pergantian berkala.
3. **Ubah Role Pengguna:** Mengalihkan role antara Staff dan Admin secara instan.
4. **Hapus User:** Menghapus akses akun dari database.
5. **Activity Log Integration:** Seluruh aktivitas penting (login, logout, registrasi user, pembuatan/pengeditan produk dan bahan) tercatat pada tabel `activity_logs` di Supabase dan ditampilkan pada terminal server dengan format timestamp WIB (*Asia/Jakarta*).

---

## 3. Diagram & Arsitektur Alur Kerja Aplikasi

### 3.1 Flowchart Alur Kerja Utama

```text
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                         TAHAP 1: SETUP MASTER DATA                         │
 │  - Input Bahan Baku (Nama Dagang, Kode, Produsen, INCI, CAS, Fungsi)     │
 │  - Upload Dokumen Spesifikasi & MSDS Per Perusahaan (PT Erfi / PT Heka)   │
 │  - Input Brand & Upload Hak/Lisensi Merk                                 │
 └─────────────────────────────────────┬─────────────────────────────────────┘
                                       │
                                       ▼
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                   TAHAP 2: MANAGEMENT BATCH BAHAN BAKU                    │
 │  - Input Batch Bahan Baku (No. Batch, Tgl Kedatangan/Release/Expired)   │
 │  - Upload CoA Batch, Sertifikat Halal, Scan QC (PDF) & Hasil Uji Lab     │
 └─────────────────────────────────────┬─────────────────────────────────────┘
                                       │
                                       ▼
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                   TAHAP 3: CREATION PRODUK & FORMULA                      │
 │  - Tambah Produk (Pilih Perusahaan, Brand, Customer, Sediaan, Netto)     │
 │  - Meracik Formula di Formula Builder / Tab Bab 2                        │
 │  - Sistem Menghitung Total Persentase (100%) & Breakdown Komponen INCI   │
 └─────────────────────────────────────┬─────────────────────────────────────┘
                                       │
                                       ▼
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                TAHAP 4: DOKUMENTASI BAB I - IV (MULTI-TAB)                │
 │  - Tab 1: Info Dasar & Legalitas NA BPOM (No NA, Tgl Aktif NA)            │
 │  - Tab 2: Bab I (NIB, CPKB, Surat Tidak Pidana, Surat Notifikasi)         │
 │  - Tab 3: Bab II (Mutu Bahan Baku, CoA Batch, MSDS, SOP CPKB Bahan)      │
 │  - Tab 4: Bab III (Spesifikasi Produk Jadi, CoA Batch Produk, Stabilitas) │
 │  - Tab 5: Bab IV (Safety Assessment, CV Assessor, Klaim, Teks Design)    │
 └─────────────────────────────────────┬─────────────────────────────────────┘
                                       │
                                       ▼
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                    TAHAP 5: GENERASI DOKUMEN & EKSPOR                     │
 │  - Bab I, III, IV -> Generate Single Merged PDF                           │
 │  - Bab II          -> Generate Merged PDF ATAU Archive ZIP (Folder/Bahan) │
 │  - Formula       -> Export Excel (Qual-Quan Report) & Print PDF          │
 └─────────────────────────────────────┬─────────────────────────────────────┘
                                       │
                                       ▼
 ┌───────────────────────────────────────────────────────────────────────────┐
 │                 TAHAP 6: SHARING LINK PUBLIK VERIFIKATOR                  │
 │  - Generate Link Publik Permalink (/dip/[slug-nama-produk]-[id])          │
 │  - Verifikator BPOM dapat Preview/Download Dokumen tanpa Login            │
 │  - Akses Dicatat Otomatis pada Audit Log (IP Address, Timestamp WIB)      │
 └───────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Panduan Operasional Tahap demi Tahap

### 4.1 Tahap 1 — Pengelolaan Master Data Bahan Baku & Legalitas Per Perusahaan
Sebelum membuat formula produk, seluruh data bahan baku wajib terdaftar di dalam database.

1. Buka menu **Bahan Baku** dari navigasi utama (`/raw-materials`).
2. Klik tombol **+ Tambah Bahan Baku Baru**.
3. **Isi Identitas Bahan Baku:**
   - Nama Dagang (misal: *Niacinamide PC*, *Glycerin 99.5%*).
   - Kode Bahan Baku (misal: *RM-001*).
   - Produsen (Supplier/Pabrikan).
4. **Isi Komposisi Komponen INCI:**
   - Masukkan Nama INCI (*INCI Name*), Nomor CAS (*CAS Number*), Fungsi (*Function*), dan persentase internal komponen dalam bahan baku (% Total = 100%).
5. **Isi Dokumen & Spesifikasi Per Perusahaan (PT Erfi / PT Heka):**
   - Pilih **Perusahaan** (PT Erfi atau PT Heka).
   - Masukkan Spesifikasi Bahan Baku (Pemeriksaan Fisik, Kadar, Kelarutan, dll).
   - Unggah File **MSDS** (format PDF, maks 10 MB).
   - Unggah File **Spesifikasi Supplier Asli** (format PDF, maks 10 MB).
6. **Cek Matriks Kelengkapan Dokumen:**
   - Gunakan tab **Cek Kelengkapan Dokumen** pada halaman Bahan Baku untuk melihat indikator visual (badge ✓ / ✗) kelengkapan dokumen per perusahaan.

---

### 4.2 Tahap 2 — Manajemen Batch Bahan Baku & Hasil Uji QC
Setiap pengiriman/kedatangan bahan baku wajib dicatatkan nomor batch dan dokumen pengujiannya:

1. Pada halaman **Bahan Baku**, buka modal/form **Kelola Batch Bahan Baku**.
2. Pilih Bahan Baku yang bersangkutan dan isi data batch:
   - **Nomor Batch Supplier.**
   - **Tanggal Kedatangan / Analisis / Release.**
   - **Tanggal Kadaluarsa (Expired Date).**
   - **Hasil Examination QC** (Lolos / Pass / Sesuai Spesifikasi).
3. **Unggah Lampiran PDF Batch:**
   - **CoA (Certificate of Analysis) Batch Supplier** (PDF).
   - **Sertifikat Halal** (PDF).
   - **Scan Hasil Pemeriksaan QC / Fisik** (PDF).
4. **Input Parameter Uji Laboratorium Aktual:**
   - Masukkan parameter pengujian fisik/kimia aktual hasil pemeriksaan QC internal untuk dipakai langsung pada dokumen Bab II.

---

### 4.3 Tahap 3 — Manajemen Brand & Lisensi Merk
1. Akses menu **Kelola Merk (Brand)** pada navigasi (`/brands`).
2. **Tambah Brand Baru:** Input nama brand/merk serta nama pemilik/produsen lisensi.
3. **Upload Dokumen Hak & Lisensi Merk:**
   - Unggah Sertifikat Merek / Surat Perjanjian Lisensi Merk (format PDF).
   - Dokumen ini secara otomatis disematkan sebagai lampiran pendukung pada **Bab I DIP** untuk semua produk yang menggunakan brand tersebut.

---

### 4.4 Tahap 4 — Pembuatan Produk & Formula Builder (Qualitative-Quantitative)

#### Pembuatan Produk Baru:
1. Klik tombol **+ Tambah Produk Baru** di Dashboard.
2. Isi formulir informasi awal:
   - Nama Produk (misal: *Brightening Serum Niacinamide 5%*).
   - Perusahaan (`PT Erfi` / `PT Heka`).
   - Nama Customer / Client.
   - Brand (Pilih dari daftar brand yang sudah diinput).
   - Sediaan Kosmetik (misal: *Serum, Cream, Lotion*).
   - Kemasan & Netto (misal: *Botol Dropper 30 mL*).

#### Meracik Formula (Formula Builder):
1. Masuk ke halaman **Formula Builder** atau **Tab Bab 2 pada Halaman Edit Produk**.
2. Tambahkan bahan baku satu per satu dan input persentase penggunaan dalam formula (% w/w).
3. **Validasi Formula:**
   - Sistem akan menghitung akumulasi persentase formula. Total persentase **wajib tepat 100.00%**.
   - Sistem secara otomatis memecah (*breakdown*) seluruh komponen INCI, CAS Number, serta kalkulasi persentase riil tiap bahan kimia dalam produk.
4. **Export Laporan Formula (Qual-Quan):**
   - Klik **Export Excel** untuk mengunduh laporan formula berformat `.xlsx` (menggunakan library Client-Side *SheetJS*).
   - Klik **Cetak PDF / Print** untuk menghasilkan salinan cetak resmi.

---

### 4.5 Tahap 5 — Penyusunan Dokumen Komprehensif Bab I – IV (Edit Produk Multi-Tab)

Halaman **Edit Produk** (`/products/{product_id}/edit`) dirancang dengan antarmuka **5 Tab Utama** untuk memudahkan navigasi:

```text
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ [Tab 1: Info Dasar] [Tab 2: Bab 1] [Tab 3: Bab 2] [Tab 4: Bab 3] [Tab 5: Bab 4] │
 └─────────────────────────────────────────────────────────────────────────┘
```

#### 📌 Tab 1 — Informasi Dasar & Legalitas NA BPOM
- Mengedit data umum produk (Nama, Perusahaan, Customer, Brand, Sediaan, Kemasan, Netto).
- Menentukan Nomor Notifikasi BPOM (No. NA).
- Menginput **Tanggal Aktif NA BPOM**. Sistem akan mengkalkulasi tanggal expired (3 tahun) dan memperbarui badge status legalitas secara otomatis (*Belum Terdaftar / Aktif / Akan Expired / Expired*).

#### 📌 Tab 2 — Bab I (Kelengkapan Administrasi)
- Melengkapi data administratif perizinan:
  - Nomor & File **NIB (Nomor Induk Berusaha)**.
  - Nomor & File **Sertifikat CPKB**.
  - File **Surat Pernyataan Tidak Terlibat Pidana**.
  - File **Surat Notifikasi / Persetujuan BPOM**.
- Pengaturan Hak & Lisensi Merk diambil otomatis berdasarkan Brand produk.
- Tombol **Preview Bab 1** dan **Download PDF Bab 1** langsung tersedia.

#### 📌 Tab 3 — Bab II (Mutu & Keamanan Bahan Kosmetika)
- Menampilkan susunan formula produk serta status kelengkapan dokumen bahan baku.
- Menghubungkan batch bahan baku aktif yang digunakan dalam produksi.
- Mengatur Dokumen SOP CPKB Penanganan Bahan Baku per perusahaan.
- Tersedia opsi **Preview Bab 2**, **Download PDF Gabungan**, serta **Download Folder ZIP**.

#### 📌 Tab 4 — Bab III (Mutu Produk Jadi)
- Mengisi data spesifikasi fisik & kimia produk jadi (Pemeriksaan Organoleptik, pH, Viskositas, Bobot Jenis, Uji Mikro, Uji Stabilitas).
- Menghubungkan Sertifikat Analisis (CoA) Batch Produk Jadi.
- Mengunggah Metode Pembuatan & Protap/SOP Produksi.
- Opsi **Preview Bab 3** & **Download PDF Bab 3**.

#### 📌 Tab 5 — Bab IV (Keamanan Produk / Safety Assessment)
- Memasukkan Laporan Evaluasi Keamanan Produk (*Safety Assessment Report*).
- Mengunggah Data Kualifikasi / CV Assessor Keamanan Kosmetik.
- Mengisi Data Pendukung Klaim Produk, Monitoring Efek Samping yang Tidak Diinginkan (NIES), serta Informasi Kemasan.
- Input **Teks Design / Etiket Kemasan** (Cara Pakai, Warning, Teks Marketing, Komposisi INCI).
- Opsi **Preview Bab 4** & **Download PDF Bab 4**.

---

### 4.6 Tahap 6 — Generasi & Ekspor Dokumen DIP (PDF Gabungan vs Folder ZIP)

Sistem menggunakan gabungan engine **`xhtml2pdf`** (HTML-to-PDF rendering) dan **`pypdf`** (PDF Merging) untuk merangkai dokumen DIP beserta seluruh lampiran PDF pendukungnya.

#### 1. Format Single Merged PDF (Bab I, Bab III, Bab IV, Bab II Standard)
Sistem menyusun halaman cover checklist standar BPOM, laporan evaluasi, lalu menggabungkan file-file lampiran PDF dari Supabase Storage secara otomatis menjadi **1 file PDF utuh**.

#### 2. Format Folder ZIP (Bab II Versi Terpisah Per Bahan Baku)
Khusus Bab II yang sering memiliki ratusan lembar lampiran (CoA, Halal, MSDS per bahan baku), sistem menyediakan fitur **Download ZIP** (`/products/{product_id}/bab2/download-zip`):
- Mengunduh berkas terkompresi `.zip`.
- Di dalamnya terdapat folder terorganisir untuk setiap bahan baku dalam formula.
- Setiap folder berisi file PDF terpisah: `01_Spesifikasi.pdf`, `02_CoA_Batch.pdf`, `03_Sertifikat_Halal.pdf`, `04_MSDS.pdf`, dan `05_Scan_QC.pdf`.
---

### 4.7 Tahap 7 — Portal Public Link & Sharing Verifikator BPOM

Untuk mempermudah verifikasi oleh petugas BPOM tanpa perlu membuka akses login aplikasi internal, sistem menyediakan **Public Link Hub**:

#### Format URL Public Permalink:
```text
https://[domain-aplikasi]/dip/[slug-nama-produk]-[product_id]
```
*Contoh:* `https://dip-automation-system.onrender.com/dip/sunscreen-serum-spf-50-e623d2e4-1234-5678-9abc-def012345678`

#### Fitur Public Hub:
- **Bebas Login:** Dapat dibuka langsung oleh verifikator BPOM kapan saja.
- **Permanen / Tanpa Expired:** URL tidak akan kadaluarsa sehingga aman dicantumkan pada portal e-Registration BPOM.
- **Akses Lengkap Dokumen:** Verifikator dapat melakukan *Preview PDF*, *Download PDF*, maupun *Download ZIP Bab II* secara mandiri.
- **Audit Logging Akses Publik:** Setiap kali halaman publik dibuka atau dokumen diunduh, sistem mencatat **Alamat IP**, **User-Agent browser**, dan **Timestamp WIB** ke dalam tabel `public_link_audits`.

---

### 4.8 Tahap 8 — Manajemen Formulir Pengajuan Sample (FSP)

Aplikasi memiliki modul khusus untuk pengelolaan **Formulir Pengajuan Sample Produk (FSP)** bagi tim RnD dan Customer (`/sample-submissions`):

1. **Pembuatan FSP Baru:** Masuk ke menu **Pengajuan Sample** dan klik **+ Form Baru**.
2. **Auto-Generate Kode FSP:**
   - Sistem menetapkan kode unik secara otomatis berdasar tanggal dan penomoran harian: `FSP/DD-MM-YYYY/X.Y`.
   - `X` = Nomor urut pengajuan pada hari tersebut.
   - `Y` = Nomor revisi (dimulai dari `0` untuk pengajuan awal).
3. **Manajemen Revisi Otomatis:**
   - Saat FSP diedit dan disimpan ulang, sistem secara otomatis menaikkan indeks revisi (`.1`, `.2`, dst.) dan memperbarui catatan riwayat revisi.
4. **Preview & Cetak:** FSP dapat dipreview dengan tampilan cetak resmi siap di-print atau di-save ke PDF (`/sample-submissions/preview/{id}`).

---

## 5. Matriks Validasi, Status & Logika Bisnis

### 5.1 Monitoring Otomatis Status Legalitas NA BPOM
Status masa berlaku Notifikasi BPOM (NA) dihitung secara matematis dari tanggal aktif (`tanggal_aktif_na`):
- Masa berlaku standar NA BPOM adalah **3 Tahun** sejak tanggal aktif.
- **Indikator Status Legalitas:**
  - 🟢 **Aktif:** Masa berlaku masih lebih dari 6 bulan.
  - 🟡 **Akan Expired:** Masa berlaku tersisa kurang dari atau sama dengan 180 hari (6 bulan).
  - 🔴 **Expired:** Tanggal hari ini telah melewati masa berlaku 3 tahun.
  - ⚪ **Belum Terdaftar:** Tanggal aktif NA belum diisi.

### 5.2 Matriks Kelengkapan DIP & Indikator Progress (%)
Pada Dashboard utama, setiap produk memiliki **Indikator Kelengkapan DIP (%)**:
- Perhitungan persentase didasarkan pada pemenuhan komponen wajib Bab I, Bab II, Bab III, dan Bab IV.
- **Matriks Checklist Dashboard:** Menampilkan badge status individual untuk Bab 1 (Administrasi), Bab 2 (Bahan Baku), Bab 3 (Produk Jadi), dan Bab 4 (Keamanan) sehingga pengguna dapat mengetahui berkas yang belum lengkap secara instan.

### 5.3 Aturan Proteksi Penghapusan Data (Preventing Orphaned Data)
- **Perlindungan Bahan Baku:** Sistem **melarang** penghapusan bahan baku dari database jika bahan baku tersebut masih terikat dalam formula produk aktif mana pun. Pengguna wajib menghapus baris bahan baku dari formula produk terlebih dahulu sebelum menghapus master data bahan baku.
- **Perlindungan Log Aktivitas:** Nama produk atau bahan baku yang dihapus akan direkam terlebih dahulu dalam log audit sebelum proses delete dilakukan agar riwayat aktivitas tetap informatif.

---

## 6. Spesifikasi Teknis & Integrasi File Storage

### 6.1 Limitasi Ukuran File Upload
- Batas maksimal ukuran file yang diunggah ke sistem adalah **10 MB per file PDF**.
- Jika pengguna mengunggah file yang melebihi 10 MB, sistem akan menangkap error HTTP 413 (*Payload Too Large*) dan mengarahkan kembali pengguna ke halaman sebelumnya disertai pesan peringatan yang ramah.

### 6.2 Integrasi Supabase Storage & PostgreSQL Database
- **Database:** Supabase PostgreSQL untuk menyimpan struktur relasional: `products`, `brands`, `raw_materials`, `raw_material_components`, `raw_material_batches`, `raw_material_company_docs`, `product_formula_lines`, `sample_submissions`, `activity_logs`, dan `public_link_audits`.
- **Object Storage:** File PDF (MSDS, CoA, Halal, NIB, CPKB, Scan QC, Kemasan) disimpan pada Supabase Storage Buckets secara terenkripsi dengan akses *public URL* yang terisolasi.

### 6.3 Audit Trail System (`activity_logs`) & Server Logging
- Seluruh tindakan mutasi data (`create`, `update`, `delete`) dicatat otomatis ke dalam tabel database `activity_logs` beserta informasi user pelaksana, kategori objek, ID target, dan detail perubahan.
- Terminal server Uvicorn mengoutputkan log berwarna dengan standar timestamp **WIB (Asia/Jakarta)**.---

## 7. FAQ & Troubleshooting

**Q1: Mengapa spesifikasi bahan baku dan MSDS dipisahkan antara PT Erfi dan PT Heka?**  
*Jawab:* PT Erfi dan PT Heka merupakan dua badan hukum terpisah dengan sertifikat CPKB dan standar mutu masing-masing. Dokumen yang dilampirkan ke BPOM harus mencantumkan kop surat dan legalitas entitas yang tepat.

**Q2: Mengapa hasil unduhan PDF Bab II gagal atau terhenti di tengah jalan?**  
*Jawab:* Biasanya disebabkan oleh salah satu file lampiran PDF di Supabase Storage yang rusak (*corrupted*) atau ukuran total file gabungan terlalu besar. Gunakan opsi **Download Folder (ZIP)** jika dokumen bahan baku sangat tebal.

**Q3: Bagaimana cara mengatasi pesan "Sesi Anda Telah Berakhir"?**  
*Jawab:* Cookie JWT Anda telah kadaluarsa demi alasan keamanan (setelah 24 jam). Silakan lakukan login ulang dengan akun Anda.

**Q4: Apakah link publik verifikator BPOM aman dari kebocoran data produk lain?**  
*Jawab:* Sangat aman. Setiap link publik menggunakan kombinasi slug nama produk dan UUID v4 acak 36-karakter yang tidak mungkin ditebak secara acak (*unguessable*). Selain itu, portal publik hanya menampilkan data 1 produk spesifik sesuai token URL tersebut.

**Q5: Kenapa persentase di Formula Builder menunjukkan angka merah / tidak 100%?**  
*Jawab:* Standar BPOM mengharuskan total persentase formula kosmetik tepat 100.00% (w/w). Periksa kembali persentase bahan pelarut (seperti *Aqua / Water*) agar akumulasi formula pas 100%.

---

## 8. Panduan Pemeliharaan & Bantuan

Jika Anda menemukan kendala teknis, *bug*, atau membutuhkan penyesuaian fitur baru pada DIP Automation System:
1. Catat langkah-langkah kejadian (*reproduction steps*) dan pesan error yang muncul pada layar.
2. Ambil *screenshot* layar yang bermasalah.
3. Hubungi Tim Pengembang IT / System Administrator internal.

*DIP Automation System dipelihara secara berkala untuk menjamin kesesuaian dengan regulasi BPOM RI dan keamanan sistem.*
