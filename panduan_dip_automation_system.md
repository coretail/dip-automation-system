# Panduan Lengkap & Komprehensif: DIP Automation System

TL;DR: DIP Automation System adalah aplikasi web untuk sentralisasi data bahan baku, manajemen formula, dan otomatisasi pembuatan Dokumen Informasi Produk (DIP) kosmetik sesuai pedoman BPOM dan ASEAN (ACD). Mendukung dua entitas hukum (PT Erfi & PT Heka), menerapkan RBAC (Admin/Staff), menyimpan berkas di Supabase Storage, dan menghasilkan output berupa PDF gabungan atau ZIP terstruktur untuk Bab II. Fitur penting: Formula Builder (total harus 100% w/w), manajemen batch & CoA, public permalink untuk verifikasi BPOM, audit logging, pembatasan unggah 10 MB per file, serta integrasi teknis dengan xhtml2pdf, pypdf, dan SheetJS.

---

Dokumen ini merupakan panduan operasional dan dokumentasi teknis komprehensif untuk penggunaan **DIP Automation System** (Sistem Otomasi Dokumen Informasi Produk Kosmetik sesuai standar BPOM dan *ASEA[...]

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
Sebelum adanya DIP Automation System, penyusunan Dokumen Informasi Produk (DIP) Kosmetik dilakukan secara manual melalui aplikasi pengolah kata dan *spreadsheets*. Proses manual ini rentan terhada[...]

**DIP Automation System** dibangun sebagai solusi sentralisasi data dan otomatisasi pembuatan berkas DIP secara digital. Tujuan utama dari sistem ini adalah:
- **Sentralisasi Master Data:** Mengintegrasikan seluruh database bahan baku, komponen INCI, batch CoA, sertifikat halal, MSDS, serta data legalitas perusahaan.
- **Otomatisasi Kompilasi Dokumen:** Menggenerasi dokumen Bab I (Administrasi), Bab II (Mutu Bahan Baku), Bab III (Mutu Produk Jadi), dan Bab IV (Keamanan Produk) secara otomatis dalam bentuk PDF [...]
- **Transparansi & Efisiensi Verifikasi:** Menyediakan *Public Link Verification Hub* yang aman untuk peninjauan langsung oleh verifikator BPOM tanpa proses penyerahan berkas fisik berulang.
- **Akurasi & Integritas Data:** Menjamin seluruh perhitungan persentase formula (*Qualitative-Quantitative*) serta breakdown komponen bahan baku akurat 100%.

### 1.2 Standar Regulatori (BPOM & ACD)
Sistem ini dirancang dengan mengacu pada pedoman penyusunan Dokumen Informasi Produk sesuai **Pedoman Teknis Dokumentasi Informasi Produk Kosmetik BPOM RI** dan pedoman **ASEAN Cosmetic Directive (ACD[...]
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
| **Admin** | Full Access | Memiliki hak akses penuh ke seluruh fitur aplikasi, termasuk **Panel Manajemen User** (`/admin/users`) untuk menambah akun baru, reset password, mengubah role pengguna,[...]
| **Staff** | Operational Access | Memiliki hak akses operasional harian: mengelola bahan baku, batch, brand, membuat dan mengedit produk, meracik formula, mengunggah dokumen Bab I-IV, serta membu[...]

> ⚠️ **Catatan Keamanan:** Fitur pendaftaran mandiri (*Self-Register*) **ditiadakan/dimatikan** untuk mencegah akses publik yang tidak terotorisasi. Pendaftaran akun baru wajib dilakukan oleh [...]

### 2.2 Autentikasi Dual & HTTP-Only Cookie JWT
- **Login Dual-Identifier:** Pengguna dapat masuk menggunakan **Email** maupun **Username** (nama lengkap). Jika menginput nama pengguna tanpa tanda `@`, sistem akan mencari profil pengguna terkai[...]
- **Sesi Keamanan JWT:** Token autentikasi disimpan dalam cookie berjenis `HTTP-Only` (`access_token` dengan flag `SameSite=Lax`). Hal ini melindungi token dari ancaman pencurian *Cross-Site Scrip[...]
- **Deteksi Sesi Expired:** Jika masa berlaku sesi habis, sistem akan memberikan notifikasi peringatan (*session expired*) dan mengarahkan pengguna kembali ke halaman login secara aman.

### 2.3 Panel Admin User (`/admin/users`) & Audit Logging
Melalui menu **Kelola User** (khusus role Admin), Admin dapat melakukan:
1. **Tambah User Baru:** Mendaftarkan email, username, password awal, serta role (`admin` / `staff`).
2. **Reset Password:** Mengubah password akun pengguna jika lupa atau diperlukan pergantian berkala.
3. **Ubah Role Pengguna:** Mengalihkan role antara Staff dan Admin secara instan.
4. **Hapus User:** Menghapus akses akun dari database.
5. **Activity Log Integration:** Seluruh aktivitas penting (login, logout, registrasi user, pembuatan/pengeditan produk dan bahan) tercatat pada tabel `activity_logs` di Supabase dan ditampilkan pada [...]

---

## 3. Diagram & Arsitektur Alur Kerja Aplikasi

### 3.1 Flowchart Alur Kerja Utama

```text
 ┌─────────────────────────────────────────────────────────────────�[...]
 │                         TAHAP 1: SETUP MASTER DATA                         │
 │  - Input Bahan Baku (Nama Dagang, Kode, Produsen, INCI, CAS, Fungsi)     │
 │  - Upload Dokumen Spesifikasi & MSDS Per Perusahaan (PT Erfi / PT Heka)   │
 │  - Input Brand & Upload Hak/Lisensi Merk                                 │
 └─────────────────────────────────────┬───────────────────────────�[...]
                                       │
                                       ▼
 ┌─────────────────────────────────────────────────────────────────�[...]
 │                   TAHAP 2: MANAGEMENT BATCH BAHAN BAKU                    │
 │  - Input Batch Bahan Baku (No. Batch, Tgl Kedatangan/Release/Expired)   │
 │  - Upload CoA Batch, Sertifikat Halal, Scan QC (PDF) & Hasil Uji Lab     │
 └─────────────────────────────────────┬───────────────────────────�[...]
                                       │
                                       ▼
 ┌─────────────────────────────────────────────────────────────────�[...]
 │                   TAHAP 3: CREATION PRODUK & FORMULA                      │
 │  - Tambah Produk (Pilih Perusahaan, Brand, Customer, Sediaan, Netto)     │
 │  - Meracik Formula di Formula Builder / Tab Bab 2                        │
 │  - Sistem Menghitung Total Persentase (100%) & Breakdown Komponen INCI   │
 └─────────────────────────────────────┬───────────────────────────�[...]
                                       │
                                       ▼
 ┌─────────────────────────────────────────────────────────────────�[...]
 │                TAHAP 4: DOKUMENTASI BAB I - IV (MULTI-TAB)                │
 │  - Tab 1: Info Dasar & Legalitas NA BPOM (No NA, Tgl Aktif NA)            │
 │  - Tab 2: Bab I (NIB, CPKB, Surat Tidak Pidana, Surat Notifikasi)         │
 │  - Tab 3: Bab II (Mutu Bahan Baku, CoA Batch, MSDS, SOP CPKB Bahan)      │
 │  - Tab 4: Bab III (Spesifikasi Produk Jadi, CoA Batch Produk, Stabilitas) │
 │  - Tab 5: Bab IV (Safety Assessment, CV Assessor, Klaim, Teks Design)    │
 └─────────────────────────────────────┬───────────────────────────�[...]
                                       │
                                       ▼
 ┌─────────────────────────────────────────────────────────────────�[...]
 │                    TAHAP 5: GENERASI DOKUMEN & EKSPOR                     │
 │  - Bab I, III, IV -> Generate Single Merged PDF                           │
 │  - Bab II          -> Generate Merged PDF ATAU Archive ZIP (Folder/Bahan) │
 │  - Formula       -> Export Excel (Qual-Quan Report) & Print PDF          │
 └─────────────────────────────────────┬───────────────────────────�[...]
                                       │
                                       ▼
 ┌─────────────────────────────────────────────────────────────────�[...]
 │                 TAHAP 6: SHARING LINK PUBLIK VERIFIKATOR                  │
 │  - Generate Link Publik Permalink (/dip/[slug-nama-produk]-[id])          │
 │  - Verifikator BPOM dapat Preview/Download Dokumen tanpa Login            │
 │  - Akses Dicatat Otomatis pada Audit Log (IP Address, Timestamp WIB)      │
 └─────────────────────────────────────────────────────────────────�[...]
```

---

## 4. Panduan Operasional Tahap demi Tahap

### 4.1 Tahap 1 — Pengelolaan Master Data Bahan Baku & Legalitas Per Perusahaan
Sebelum membuat formula produk, seluruh data bahan baku wajib terdaftar di dalam database.

1. Buka menu **Bahan Baku** dari navigasi utama (`/raw-materials`).
2. Klik tombol **+ Tambah Bahan Baku Baru**.
3. **Isi Identitas Bahan Baku:**
   - Nama Dagang (misal: *Niacinamide PC*, *Glycerin 99.5%*).
4. **Isi Komposisi Komponen INCI:**
   - Masukkan Nama INCI (*INCI Name*), Nomor CAS (*CAS Number*), Fungsi (*Function*), dan persentase internal komponen dalam bahan baku (% Total = 100%).
5. **Isi Dokumen & Spesifikasi Per Perusahaan (PT Erfi / PT Heka):**
   - Pilih **Perusahaan** (PT Erfi atau PT Heka).
---
