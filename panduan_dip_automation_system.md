# Panduan Lengkap & Komprehensif: DIP Automation System

**TL;DR:** DIP Automation System adalah aplikasi web untuk sentralisasi data bahan baku, manajemen formula, dan otomatisasi pembuatan Dokumen Informasi Produk (DIP) kosmetik sesuai pedoman BPOM dan ASEAN Cosmetic Directive (ACD). Mendukung dua entitas hukum (PT Erfi & PT Heka) dengan data terpisah per perusahaan, menerapkan RBAC (Admin/Staff), menyimpan berkas di Supabase Storage, dan menghasilkan output berupa PDF gabungan atau folder ZIP terstruktur untuk Bab II. Fitur penting: **tema tampilan 4 warna** (Light/Terra/Rose/Dark) dengan sidebar responsif, Formula Builder (total harus 100% w/w), manajemen batch & CoA, input produksi (PO & batch produk) beserta **halaman analitik PO**, catatan kerja tim (Notes dengan @mention dan token referensi), laporan monitoring efek samping (NIES) per semester, public permalink untuk verifikasi BPOM, audit trail (`activity_logs`), pembatasan unggah 10 MB per file, **toolkit migrasi data dari spreadsheet**, serta integrasi teknis dengan `xhtml2pdf`, `pypdf`, dan `openpyxl`.

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

> **Ringkasan isi Tahap 4 (section 4.x):** 4.1 Master Data Bahan Baku · 4.2 Manajemen Batch · 4.3 Brand · 4.4 Formula Builder · 4.5 Edit Produk Multi-Tab · 4.6 **Generasi & Ekspor Dokumen (PDF Gabungan vs ZIP)** · 4.7 Portal Public Link · 4.8 FSP · 4.9 **Input Produksi (PO & Batch)** · 4.10 **Analisis PO** · 4.11 **Notes Tim** · 4.12 **Monitoring Efek Samping (NIES)** · 4.13 **Sistem Tema & Tampilan** · 4.14 **Toolkit Migrasi Data**

> **Versi dokumen:** 5 Oktober 2026 · **Cakupan:** aplikasi web `D:\dip-app` (FastAPI + Jinja2 + Supabase)

---

## 1. Pendahuluan & Konsep Dasar

### 1.1 Latar Belakang & Tujuan Sistem
Sebelum adanya DIP Automation System, penyusunan Dokumen Informasi Produk (DIP) Kosmetik dilakukan secara manual melalui aplikasi pengolah kata dan *spreadsheet*. Proses manual ini rentan terhadap ketidaksesuaian data, duplikasi informasi, inkonsistensi penomoran dokumen, dan memakan waktu lama saat penyusunan berkas perizinan BPOM.

**DIP Automation System** dibangun sebagai solusi sentralisasi data dan otomatisasi pembuatan berkas DIP secara digital. Tujuan utama sistem ini adalah:
- **Sentralisasi Master Data:** mengintegrasikan seluruh database bahan baku, komponen INCI, batch CoA, sertifikat halal, MSDS, serta data legalitas perusahaan.
- **Otomatisasi Kompilasi Dokumen:** menggenerasi dokumen Bab I (Administrasi), Bab II (Mutu Bahan Baku), Bab III (Mutu Produk Jadi), dan Bab IV (Keamanan Produk) secara otomatis dalam bentuk PDF siap cetak atau arsip ZIP.
- **Dukungan Operasional Harian:** mencatat penerimaan & produksi lewat Purchase Order dan batch produk, membaca tren produksi lewat halaman Analisis PO, mencatat pekerjaan tim antar departemen lewat Notes ber-`@mention`, serta mengimpor data produksi historis dari spreadsheet lewat toolkit migrasi.
- **Cosmetovigilance:** menyusun laporan monitoring efek samping (NIES) per semester untuk setiap produk.
- **Transparansi & Efisiensi Verifikasi:** menyediakan *Public Link Verification Hub* yang aman untuk peninjauan langsung oleh verifikator BPOM tanpa proses penyerahan berkas fisik berulang.
- **Akurasi & Integritas Data:** menjamin perhitungan persentase formula (*Qualitative-Quantitative*) serta breakdown komponen bahan baku akurat 100%.
- **Kenyamanan & Konsistensi Tampilan:** tema 4 warna yang konsisten sampai ke kontrol form native, sidebar yang menyesuaikan layar, dan navigasi yang tetap terbaca di perangkat kecil maupun besar.

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
  - > ⚠️ **Catatan teknis:** input "username" sebenarnya dicocokkan ke kolom `profiles.full_name` — tidak ada kolom `username` terpisah. Bila identifier tidak mengandung `@` dan tidak ditemukan di `profiles`, sistem masih memakai fallback domain kantor yang hardcoded `@erfi.com`. Konsekuensinya: **user PT Heka yang belum terdaftar di `profiles` tidak bisa login lewat username** — gunakan email resmi sampai fallback ini diperbaiki.
- **Sesi Keamanan JWT:** token autentikasi disimpan dalam cookie `HTTP-Only` (`access_token`, `SameSite=Lax`), melindungi dari pencurian token lewat *Cross-Site Scripting (XSS)*. Token JWT berlaku **4 jam**, setelah itu pengguna perlu login ulang. (Catatan: cookie `access_token` sendiri diberi masa simpan 24 jam, namun isinya tidak berlaku lagi setelah JWT kedaluwarsa.)
- **Deteksi Sesi Expired:** jika sesi habis, sistem menampilkan peringatan (*session expired*) dan mengarahkan kembali ke halaman login secara otomatis.
- **Proteksi Brute-Force:** endpoint `POST /login` dibatasi maksimal **5 percobaan per menit per IP** memakai `slowapi`, dengan alert + countdown timer di halaman login.
- **Sapaan AI (opsional):** saat login, sistem membangkitkan satu kalimat sapaan melalui Google Gemini API dan menyimpannya di cookie `greeting_cache` (4 jam) supaya tidak dipanggil ulang tiap buka dashboard. Fitur ini **nonaktif otomatis** bila `GEMINI_API_KEY` tidak diisi.

### 2.3 Panel Admin User (`/admin/users`) & Audit Logging
Melalui menu **Kelola User** (khusus role Admin), Admin dapat:
1. **Tambah User Baru** — mendaftarkan email, username, password awal, serta role (`admin` / `staff`).
2. **Reset Password** — mengubah password akun pengguna.
3. **Ubah Role Pengguna** — mengalihkan role antara Staff dan Admin.
4. **Hapus User** — menghapus akses akun dari database.
5. **Monitor Online/Idle/Offline** — kolom Status di daftar user menampilkan satu dari tiga status berikut, lengkap dengan badge warna, filter, dan counter:
   - 🟢 **Online** — heartbeat kiriman dalam **≤ 90 detik**.
   - 🟡 **Idle** — masih terhubung dan heartbeat masih segar, tetapi **tidak ada aktivitas pengguna ≤ 5 menit** (mis. tab ditinggal terbuka). Heartbeat tetap berjalan, jadi status Idle bukan berarti koneksi putus.
   - ⚪ **Offline** — heartbeat berhenti; Logout membuat user langsung Offline, sedangkan menutup tab tanpa logout otomatis Offline setelah **± 90 detik**.
   
   Status di-refresh otomatis setiap 15 detik, dan refresh otomatis berhenti saat tab tidak terlihat.
6. **Akun Terproteksi** — akun yang ditandai `is_protected` **tidak dapat** diubah role, di-reset password, maupun dihapus oleh admin lain. Tampilan halaman menampilkan peringatan bahwa akun tersebut terkunci.
7. **Activity Log Integration** — seluruh aktivitas penting (pembuatan/pengeditan/penghapusan bahan baku, produk, PO, item PO, generate laporan) tercatat pada tabel `activity_logs` di Supabase, dan sekaligus ditampilkan di terminal server dengan format timestamp WIB (*Asia/Jakarta*) untuk pemantauan cepat.

---

## 3. Diagram & Arsitektur Alur Kerja Aplikasi

### 3.1 Alur Kerja Utama

```
TAHAP 1 — SETUP MASTER DATA
  • Input Bahan Baku (Nama Dagang, Kode, Tipe, Produsen, komponen INCI/CAS,
    varian komposisi bila tipe Komposit)
  • Upload Spesifikasi & MSDS per perusahaan (PT Erfi / PT Heka)
  • Input Brand & upload Hak/Lisensi Merk
        |
        v
TAHAP 2 — MANAJEMEN BATCH BAHAN BAKU
  • Input Batch (No. Batch, tanggal terima/sampling/ED, per perusahaan)
  • Upload CoA, Sertifikat Halal, Catatan Pemeriksaan & hasil uji lab aktual
  • Tandai batch: Dipakai (CONDOH) / Dimusnahkan
        |
        v
TAHAP 3 — PEMBUATAN PRODUK & FORMULA
  • Tambah Produk (perusahaan, brand, customer, sediaan, netto)
  • Racik formula (Formula Builder) — total wajib 100.000%
  • Sistem otomatis breakdown komponen INCI dari formula
        |
        v
TAHAP 3b — INPUT PRODUKSI (opsional, tim QC)
  • Buat Purchase Order & batch produk jadi (Produksi)
  • Catat item PO per batch: WIP, netto, qty, status BPOM, catatan produksi
  • Baca trennya di Analisis PO: komposisi per kuartal,
    jumlah PO & qty pcs per perusahaan, Top 5 produk
        |
        v
TAHAP 3c — IMPOR DATA HISTORIS (opsional, sekali jalan)
  • Jalankan skrip di folder migration\ untuk mengisi data
    produksi lama dari spreadsheet (rekap SOP, catatan batch)
  • Selalu --dry-run dulu, lalu --execute --yes
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
TAHAP 5b — MONITORING EFEK SAMPING (NIES, per semester)
  • Dari Tab Bab 4, generate laporan cosmetovigilance
  • Ditambahkan (append) ke PDF sebelumnya per produk
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

### [Pembaruan] Fitur Produk & Text Design
- **Field Informasi Tambahan:** Pada halaman Edit Produk, tersedia field "Peringatan" dan "Penyimpanan".
- **Aturan Penayangan Kondisional:** Pada Text Design (HTML Preview, PDF, dan Excel), field "Peringatan" dan "Penyimpanan" **HANYA** akan muncul jika diisi oleh pengguna (bukan NULL atau karakter strip `-`).


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
   - **Varian Komposisi:** bahan baku Komposit bisa punya lebih dari satu varian komposisi, dan satu varian ditandai sebagai **default**. Baris formula dapat menunjuk varian tertentu lewat `variant_id`, sehingga INCI breakdown report dan Qual-Quan mengikuti varian yang dipilih. Tambah varian, set default, dan hapus varian dilakukan dari halaman bahan baku. Varian yang sudah dipakai di formula tidak bisa dihapus.
5. **Isi Dokumen & Spesifikasi Per Perusahaan** — pilih tab **PT Erfi** atau **PT Heka**, lalu lengkapi:
   - Spesifikasi standar (pemerian, aroma, pH, viskositas, masa kedaluwarsa, cara penyimpanan, referensi).
   - Upload **MSDS** (PDF, maks 10 MB).
   - Upload **PDF Spesifikasi Asli dari Supplier** (opsional di sisi data, tapi **wajib ada** kalau ingin section Spek muncul di PDF gabungan Bab II — lihat §4.6).
   - Boleh diisi salah satu perusahaan dulu, tab satunya bisa disusulkan belakangan.
6. **Cek Matriks Kelengkapan Dokumen** — gunakan tab **Cek Kelengkapan Dokumen** pada halaman Bahan Baku untuk melihat status per perusahaan (lengkap dengan PDF, terisi teks saja, atau belum ada), sekaligus preview PDF langsung tanpa pindah halaman.


- **Fitur Pelacakan Produk:** Penambahan pelacakan "Digunakan di Produk Mana" via Badge Counter / Modal Popup pada daftar Bahan Baku (`raw_materials.html`) untuk melihat daftar produk yang menggunakan bahan baku tersebut.

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

- **Edit Batch Kedatangan:** Fitur Edit Batch (`raw_material_batches`) memungkinkan pembaruan No Lot, Tanggal ED, Produsen, Asal Negara, dan lampiran COA.
- **Pengurutan Log:** Log kedatangan batch diurutkan berdasarkan `created_at DESC` (terbaru di baris paling atas).
- **Status Batch:** pada log batch tersedia aksi **"Dipakai"** (produk sudah digunakan/CONDOH) dan **"Dimusnahkan"**, lengkap dengan input tanggal serta alasan. Status ini terpisah dari `kesimpulan` kelulusan QC.
   - **Laporan Pemeriksaan Aktual** — opsional; kalau ada dokumen fisik/scan hasil pemeriksaan, upload di sini. PDF ini dipakai sebagai sumber **Catatan Pemeriksaan di PDF gabungan maupun ZIP**; kalau tidak ada, PDF gabungan tetap menampilkannya dari data batch (§4.6).
5. **Input Parameter Uji Laboratorium Aktual** (kalau tidak upload laporan PDF di atas): hasil pemeriksaan fisik/kimia aktual, kesimpulan, serta nama yang memeriksa (QC) dan menyetujui (QA). Data ini dipakai sebagai sumber Catatan Pemeriksaan di PDF gabungan, dan sebagai fallback di ZIP.

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
5. **Export Laporan Formula (Qual-Quan):** tombol *Export Excel* (`.xlsx`) dan *Cetak PDF / Print* tersedia di halaman Qualitative-Quantitative. File `.xlsx` **dibuat di server** dengan `openpyxl` (bukan di sisi browser), berisi 3 sheet: "Formula Nama Dagang", "Formula INCI Murni", dan "Text Design".

---

### 4.5 Tahap 5 — Penyusunan Dokumen Bab I – IV (Edit Produk Multi-Tab)

Halaman **Edit Informasi & Dokumen Produk** (`/products/{product_id}/edit`) menggabungkan semua pengaturan produk dalam **5 tab**: *Informasi Dasar*, *Bab 1*, *Bab 2*, *Bab 3*, *Bab 4* — sehingga tidak perlu berpindah-pindah halaman.

**Tab Informasi Dasar** — data umum produk, Nomor Notifikasi BPOM (No. NA), dan Tanggal Aktif NA. Status legalitas NA (Aktif / Akan Expired / Expired / Belum Terdaftar) dihitung & diperbarui otomatis dari tanggal ini.

**Tab Bab 1 (Kelengkapan Administrasi)** — NIB, Sertifikat CPKB, Surat Tidak Pidana, Surat Notifikasi BPOM. Hak & Lisensi Merk diambil otomatis dari data Brand. Tersedia tombol *Preview* dan *Download PDF*.

**Tab Bab 2 (Mutu & Keamanan Bahan Kosmetika)** — susunan formula produk dan status kelengkapan dokumen tiap bahan baku, SOP CPKB penanganan bahan baku per perusahaan. Tersedia *Preview*, *Download PDF Gabungan*, dan *Download Folder ZIP*. Rincian isi dan urutan section PDF gabungan ada di [§4.6](#46-tahap-6--generasi--ekspor-dokumen-dip-pdf-gabungan-vs-folder-zip).

**Tab Bab 3 (Mutu Produk Jadi)** — spesifikasi fisik/kimia produk jadi, metode pembuatan, sistem penomoran batch, hasil stabilitas. Tersedia *Preview* & *Download PDF*.

- **Generator Ekspor Excel (OpenPyXL):** Standar formatting ekspor Excel (.xlsx) untuk dokumen Formula Kualitatif & Kuantitatif:
    * Header & Judul di-merge selebar tabel (A-E).
    * Border tipis (#D1D5DB) pada area tabel data tanpa mengenai blok tanda tangan.
    * Penataan khusus sheet "Formula INCI Murni": border terbatas kolom A-C dan tanda tangan 2 kolom (Kiri A: Registrasi, Kanan C: R&D).
    * Penataan sheet "Text Design": tanpa blok tanda tangan dan mengikuti aturan rendering kondisional (Peringatan & Penyimpanan).

**Tab Bab 4 (Keamanan Produk)** — laporan *safety assessment*, CV *safety assessor*, data klaim, monitoring efek samping (NIES), desain kemasan primer/sekunder, dan rancangan teks kemasan. Tersedia *Preview* & *Download PDF*, serta **generate laporan Monitoring Efek Samping** (lihat [§4.12](#412-monitoring-efek-samping-nies)).

> ⚠️ Setiap dokumen yang belum diunggah ditandai badge **"PDF belum terisi"**. Upload PDF dibatasi maksimal **10 MB per file**; validasi dilakukan di sisi browser (agar terasa cepat) *dan* di sisi server (sebagai jaring pengaman terakhir yang tidak bisa dilewati).

---

### 4.6 Tahap 6 — Generasi & Ekspor Dokumen DIP (PDF Gabungan vs Folder ZIP)

Sistem menggunakan kombinasi **`xhtml2pdf`** (render HTML ke PDF) dan **`pypdf`** (menggabungkan/merge PDF) untuk merangkai dokumen DIP beserta lampirannya.

**Bab I, III, dan IV** memakai satu teknik yang seragam: halaman cover/checklist di-render dari template Jinja2 menjadi PDF, lalu lampiran dari Supabase Storage **ditempel** (`add_page`) menjadi satu file PDF utuh.

**Bab II berbeda** dan perlu dipahami dengan saksama, karena dampaknya ke dokumen yang dikirim ke BPOM:

#### A. PDF Gabungan Bab II

Urutannya:

1. **Checklist Kelengkapan Data** — halaman pembuka.
2. **Prosedur Tetap Pemeriksaan Bahan Baku (SOP CPKB)** perusahaan.
3. **Satu halaman per bahan baku** — berisi nama bahan baku, Spek, dan Catatan Pemeriksaan. Ini memakai teknik **komposisi layout**, bukan sekadar menempel: halaman A4 dibuat, judul bahan baku + label section digambar, lalu dokumen sumber (PDF) diskalakan proporsional dan ditempel di dalam kotak yang tersedia. Konsekuensinya:
   - Kalau **Spek dan Catatan Pemeriksaan sama-sama tersedia, keduanya tetap berada di SATU halaman yang sama** — bukan dua halaman terpisah.
   - Kalau **hanya salah satu** yang tersedia, hanya itu yang ditampilkan. **Tidak ada halaman kosong atau placeholder** untuk dokumen yang tidak ada.
   - Scaling bersifat proporsional dan **tidak memotong isi** dokumen sumber.
4. **Section COA** — seluruh COA dikumpulkan di sini, **setelah semua bahan baku selesai**, bukan menempel di belakang bahan bakunya. Tiap COA diberi header nama bahan bakunya agar jelas COA tersebut milik bahan baku mana. Isi PDF COA asli tidak diubah.
5. **Daftar bahan baku tanpa Spek & Catatan Pemeriksaan.**
6. **Daftar bahan baku dengan COA belum terlampir.**

Aturan penting:
- **Spek bahan baku hanya diambil dari PDF** (`spec_sheet_file_url` di `raw_material_company_docs`). Parameter spesifikasi yang diketik manual (`spec_parameters`) **tidak dipakai sama sekali** di PDF gabungan. Kalau PDF Spek kosong atau gagal diambil, Spek dianggap tidak ada.
- **Catatan Pemeriksaan** diambil dari PDF laporan pemeriksaan (`qc_report_file_url`). Kalau tidak ada, sistem **tetap menampilkannya dari data batch** (nomor batch, supplier, tanggal sampling/terima/ED, hasil uji, kesimpulan, penanda tangan QC & QA). Kalau tidak ada batch sama sekali, Catatan Pemeriksaan dianggap tidak ada.
- Bahan baku yang **tidak** punya Spek **dan** tidak punya Catatan Pemeriksaan **tidak mendapat halaman kosong**; namanya masuk daftar nomor 5. Yang hanya kehilangan salah satu dokumen **tidak** masuk daftar itu.
- Section daftar yang kosong **tidak pernah dicetak** — jadi tidak akan muncul halaman kosong di bagian akhir.
- COA yang kosong, gagal diambil, atau file-nya rusak diperlakukan sama: tidak ada halaman kosong, dan namanya masuk daftar nomor 6.
- Satu dokumen bermasalah tidak menggagalkan seluruh Bab II. Error dicatat di log server (bukan ditampilkan ke pengguna).

> ⚠️ **Penting — Halal & MSDS:** PDF gabungan Bab II **saat ini tidak menyertakan Sertifikat Halal maupun MSDS**. Keduanya tidak di-*merge* ke PDF gabungan, dan tidak ikut dihitung sebagai dokumen yang kurang. Hanya versi ZIP yang memuat keduanya. Ini adalah perilaku desain saat ini, bukan aturan permanen — bila tim Regulasi memutuskan keduanya harus kembali ke PDF gabungan, penempatannya ada di satu fungsi dan tidak mengubah alur section lain.

> ℹ️ **Preview:** tombol *Preview Bab 2* di Tab Bab 2 memakai **generator yang sama persis** dengan tombol download PDF; yang berbeda hanya header respons (`inline` agar tampil di tab baru, bukan `attachment`). Jadi apa yang terlihat saat preview sama persis dengan file yang terunduh.

#### B. Folder ZIP Bab II

Opsi **Download ZIP** menghasilkan folder terorganisir *per bahan baku*, isinya 5 file terpisah:
1. `1_Spesifikasi_Bahan_Baku.pdf` — PDF asli dari supplier kalau ada, atau hasil generate dari data yang diketik.
2. `2_Catatan_Pemeriksaan_Bahan_Baku.pdf` — PDF laporan pemeriksaan asli kalau ada, atau hasil generate dari data aktual.
3. `3_CoA.pdf`
4. `4_Sertifikat_Halal.pdf`
5. `5_MSDS.pdf`

Kalau salah satu dokumen belum tersedia, file `PERHATIAN.txt` otomatis disertakan di folder bahan baku itu, menandai dokumen apa yang masih kurang.

#### C. Ringkasan Perbedaan

| | PDF Gabungan | Folder ZIP |
|---|---|---|
| Spek | **Hanya** dari PDF; parameter manual tidak dipakai | PDF asli, jika tidak ada digenerate dari parameter manual |
| Catatan Pemeriksaan | PDF laporan pemeriksaan, jika tidak ada dari data batch | PDF asli, jika tidak ada digenerate dari hasil uji batch |
| Penempatan CoA | Satu section tersendiri setelah semua bahan baku | File terpisah per folder bahan baku |
| Sertifikat Halal & MSDS | **Tidak dilampirkan** | Dilampirkan sebagai file terpisah |
| Laporan dokumen kurang | Dua daftar ringkasan di bagian akhir PDF | File `PERHATIAN.txt` per folder bahan baku |
| Checklist | Template khusus PDF gabungan (tidak mencantumkan Halal/MSDS sebagai terlampir) | Template checklist versi ZIP (mencantumkan Halal & MSDS) |

> Catatan teknis: urutan bahan baku pada PDF mengikuti urutan baris formula yang dikembalikan database. Karena query tidak melakukan pengurutan eksplisit, urutan ini **belum dijamin identik** di setiap proses generate.

---

### 4.7 Tahap 7 — Portal Public Link & Sharing Verifikator BPOM

Untuk mempermudah verifikasi BPOM tanpa perlu akun/login ke sistem internal, setiap produk punya **Public Link Hub**:

**Format URL:** `/dip/[slug-nama-produk]-[uuid-produk]`
*Contoh:* `.../dip/sunscreen-serum-spf-50-e623d2e4-1234-5678-9abc-def012345678`

- **Logo Header Dinamis:** Penentuan logo (PT Heka vs PT Erfi) dilakukan otomatis berdasarkan data `company` / `draft_producer` yang dipilih.
- **Layout Tanda Tangan 3 Kolom:** Struktur baru tanda tangan pada dokumen:
  * Kiri: Dibuat oleh (R&D / `rd_signer`)
  * Tengah: Disetujui oleh (Nama PT Pemesan dari `company`/`draft_producer`)
  * Kanan: Mengetahui (Erna Widayanti)


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

### 4.9 Input Produksi — Purchase Order & Batch Produk (QC)

Modul di menu **Produksi** (`/purchase-orders`) untuk mencatat alur penerimaan & produksi. Alurnya berpusat pada satu nomor PO.

1. **Buat Purchase Order** — isi **No. PO** (wajib, unik), **Tanggal PO**, dan **Qty (pcs)**. Bila No. PO sudah terdaftar, sistem menolak dan mengarahkan ke PO yang ada.
2. **Buat Batch Produk Jadi** — pilih produk, isi **No. Batch** (wajib, unik per produk), **Tanggal Produksi** (default hari ini bila kosong), dan **Tanggal ED**.
3. **Catat Item PO per Batch** — setiap baris item menempel ke satu batch produk jadi dan mencatat:
   - **Tanggal Catatan Batch**
   - **WIP** (Work In Process) — kolom numerik
   - **Netto**
   - **Qty (kg)**, **Qty Belum SOP**, **Qty PO (kg)**
   - **Status BPOM**, **Keterangan**
   - **Catatan Produksi**, **Revisi Produksi**, **Temporary Reject**
4. **Ubah & Hapus Item** — item yang sudah tersimpan dapat diedit atau dihapus. Nomor urut item (`urutan`) dibuat otomatis berurutan, dan sistem mencoba ulang bila terjadi benturan nomor urut. ⚠️ **Nomor urut tidak pernah dirapikan ulang** setelah penghapusan — bila item urutan 3 dihapus, urutan 4 dan seterusnya tetap pada posisinya dan nomor berikutnya dilanjutkan dari angka tertinggi, bukan dari jumlah baris.
5. **Validasi** — bila batch yang dipilih bukan milik produk yang dipilih, sistem menolak. Input angka tidak valid (bukan angka) dan format tanggal salah akan ditolak dengan pesan yang jelas.

> ℹ️ **Header PO tidak bisa diedit atau dihapus** dari aplikasi. `purchase_orders` hanya bisa bertambah lewat form "Tambah PO"; koreksi dilakukan lewat skrip migrasi (lihat §4.14). Ini keputusan sadar agar histori produksi tidak berubah sepihak lewat UI.

Semua aktivitas pembuatan PO, batch produk, dan item PO tercatat di `activity_logs`.

> ℹ️ Tabel terkait: `purchase_orders` (header PO), `purchase_order_items` (item per batch, `UNIQUE (purchase_order_id, urutan)`), `product_batches` (batch produk jadi). Nomor batch produk jadi juga dipakai sebagai lampiran di dokumen Bab III.

#### 4.9.1 Filter, Pencarian & Penyimpanan Preferensi

Halaman `/purchase-orders` punya empat lapis kontrol:

| Kontrol | Nilai | Perilaku |
|---|---|---|
| **Tahun** | Angka tahun + opsi **"Semua Tahun"** | Opsi "Semua Tahun" tersedia karena data satu tahun berjalan belum tentu lengkap 12 bulan. PO difilter **di database** lewat rentang tanggal, bukan dengan menyaring 100 baris terbaru di Python — itu membuat Q1/Q2 jadi tidak akurat |
| **Kuartal** | **Q1–Q4 saja** (tidak ada "Semua") | Bila kosong, server memakai **kuartal berjalan** menurut tanggal WIB. Untuk tahun tertentu, kuartal dinaikkan ke **kuartal tertinggi yang benar-benar berisi data**, supaya halaman tidak pernah terbuka kosong (mis. Oktober: kuartal berjalan Q4, tetapi data tahun ini baru sampai Q3) |
| **Perusahaan** (`pt`) | `PT Erfi`, `PT Heka`, dan opsi **"Tanpa item"** | Lihat catatan panjang di bawah |
| **Cari** | Teks bebas | Mencocokkan No. PO **dan** nama produk |

> ℹ️ **Mengapa ada opsi "Tanpa item"?** Tabel `purchase_orders` **tidak punya kolom perusahaan** — perusahaan suatu PO ditentukan dari produknya lewat `purchase_order_items`. Akibatnya, saat filter PT aktif, PO yang belum punya item otomatis ikut tersaring. Opsi **"Tanpa item"** disediakan supaya PO tersebut **tidak hilang diam-diam**. Nilainya hanya muncul di dropdown bila jumlahnya lebih dari 0, dan tercatat pada badge `pt_counts` dengan kunci kosong.

- Pilihan tersimpan di **cookie `po_filter`** dengan format `tahun|kuartal|perusahaan`, sehingga filter bertahan saat berpindah halaman dan saat membuka halaman dari notifikasi.
- **Interaksi antar filter:** mengganti tahun **mempertahankan** kuartal dan perusahaan; mengganti perusahaan **menghapus** PO terpilih (karena PO itu mungkin tidak ada di hasil saringan) tetapi **mempertahankan** kuartal; "Tanpa item" dikirim sebagai string kosong pada form pencarian supaya tidak dianggap filter.
- **Endpoint `GET /api/po/search`** tersedia untuk pencarian No. PO + nama produk dan dipakai integrasi; antarmuka `/purchase-orders` sendiri memfilter di sisi klien.
- **Pengurutan** tanggal PO dengan nilai `null` selalu diletakkan **terakhir**, supaya PO yang belum bertanggal tidak menggeser PO tertua ke posisi teratas.
- Batas pengambilan baris (`_PO_LIST_LIMIT`) bersifat **jaring pengaman**, **bukan batas tampilan** — seluruh daftar ditampilkan, dan halaman menampilkan catatan bila jumlah baris yang diambil menyentuh batas tersebut.


#### 4.9.2 PO Rework

Kolom `purchase_orders.jenis_po` (`migration/002_add_jenis_po.sql`) menandai PO perbaikan/rework. Tandai dengan `python migration\tag_rework_po.py --execute --yes` memakai daftar `migration/po_rework_tag.csv`.

Aturan perlakuan di `/po-analytics` — dan ini yang perlu diketahui saat membaca angka:

- PO Rework **tetap dihitung** pada `jumlah_po`.
- `qty_pcs` PO Rework **tidak ikut dijumlahkan** pada `total_pcs` maupun pada `q_pcs` per kuartal.
- Efeknya, KPI **jumlah PO** dan KPI **total qty** tidak naik bersamaan. Selisih di antara keduanya besarnya sama dengan volume qty PO Rework.

Bila kolom `jenis_po` belum ada di database, halaman analitik menampilkan banner biru yang menyuruh menjalankan `migration\002_add_jenis_po.sql` lalu `tag_rework_po.py`, dan seluruh `qty_pcs` dihitung tanpa pemisahan rework.

---

### 4.10 Analisis PO (`/po-analytics`)

Halaman analitik terpisah dari form input produksi, untuk membaca tren produksi per kuartal dan per perusahaan.

#### A. Dari mana angka berasal

Aturan ini penting karena setiap grafik punya sumber tabel berbeda:

| Angka | Sumber | Catatan |
|---|---|---|
| **Total PO** & **Total qty** (KPI) | `purchase_orders` | Dihitung **langsung dari header**, jadi PO tanpa item pun tetap terhitung |
| **Komposisi per kuartal** | `purchase_orders` | PO tanpa item **tetap masuk** KPI dan grafik kuartal |
| **Atribusi produk & perusahaan** | `purchase_order_items` | PO baru bisa masuk grafik perusahaan bila punya minimal satu item |
| **Metadata produk (nama, perusahaan, NA, brand)** | `products` | Template `INCI breakdown` tidak pernah dipakai di sini |
| **Batch produksi (`product_batches`)** | — | **Tidak dipakai sama sekali** di analitik |

`qty_pcs` pada grafik per perusahaan selalu mengambil nilai dari header PO. Bila satu PO punya beberapa item produk, `qty_pcs` header itu **dihitung sekali** per PO (set id berisi `purchase_order_id`), bukan sekali per item — jadi PO dengan 5 item tidak menggandakan qty.

#### B. Isi halaman

- **KPI baris:** Total PO (tahun penuh) + 4 kartu kuartal (jumlah PO & pcs), kuartal terpilih disorot dan diberi tanda `(dipilih)`.
- **Grafik 1 — Jumlah PO per kuartal** (`chartQuarter`): batang jumlah PO (sumbu kiri) + garis qty pcs (sumbu kanan).
- **Grafik 2 — Proporsi PO per perusahaan** (`chartCompany`): donat.
- **Grafik 3 — Jumlah PO & qty pcs per kuartal per perusahaan** (`chartQuarterCompany`): **batang = jumlah PO (sumbu kiri)**, **garis = qty pcs (sumbu kanan)**, warna batang & garis per PT sama agar mudah dipasangkan. Keduanya diredupkan pada kuartal yang tidak dipilih agar kuartal yang sedang dipilih menonjol.
- **Tabel Top 5 produk** — dua tab: "produk dengan PO terbanyak" dan "produk belum punya Laporan Uji SIG".
- **Filter:** tahun, kuartal, urutan (jumlah PO ↔ total qty), tab perusahaan (Semua / PT Erfi / PT Heka).

#### C. Transparansi: PO tanpa item

Ini bagian yang paling sering membingungkan, jadi dirancang eksplisit:

- PO yang ada di header tapi **tidak punya satu pun baris di `purchase_order_items`** dihitung sebagai **"PO belum punya item"**. Jumlahnya muncul sebagai banner amber di atas halaman, beserta daftar nomor PO-nya (maksimal 50 nama, dengan penanda bila dipotong).
- Banner itu juga menjelaskan konsekuensinya: PO tersebut **tetap dihitung** pada Total PO & Total qty, tetapi **tidak bisa diatribusikan** ke produk maupun perusahaan — sehingga grafik/tabel per perusahaan bisa terlihat lebih kecil dari kenyataan.
- **Perusahaan dengan 0 PO dan perusahaan dengan 0 PO teratribusi dibedakan.** Bila `PT Heka` dan `PT Erfi` sama-sama 0, teksnya berbeda tergantung apakah ada PO tanpa item atau memang tidak ada PO sama sekali.
- Company attribution memang **hanya PT Erfi dan PT Heka** yang dihitung; produk dengan `perusahaan` lain masuk key `"Lainnya"` yang sengaja tidak ditampilkan. Ini konsekuensi desain, bukan filter UI.

#### D. Pembatasan & pitfall yang perlu diketahui

- **Batas 5.000 baris** per tabel. Bila data tahun terpilih melampaui batas ini, halaman menampilkan banner "data belum tentu lengkap", dan daftar `po_tanpa_item` bisa **false positive** — item yang tidak sengaja terpotong akan terlihat seperti PO tanpa item.
- **Satu PO lintas perusahaan dihitung penuh di kedua perusahaan.** PO yang memuat produk PT Erfi *dan* PT Heka tetap menyumbang `qty_pcs` penuh ke keduanya, sehingga jumlah qty per perusahaan bisa **melebihi** `total_pcs`. Ini perilaku yang disengaja demi konsistensi dengan angka header, dan dinyatakan eksplisit di bawah grafik.
- Bila kolom `purchase_orders.jenis_po` belum ada di database, halaman menampilkan banner biru yang menyuruh menjalankan `migration\002_add_jenis_po.sql`, dan seluruh `qty_pcs` dihitung tanpa pemisahan rework.


---

### 4.11 Notes Tim & @mention

Modul **Notes** (`/notes`) untuk catatan kerja & koordinasi antar tim, menggantikan pesan berantai yang tersebar di aplikasi chat.

1. **Tulis Note** — isi catatan, lalu rujuk rekan tim dengan **`@nama`**. Ketik `@` untuk memunculkan daftar anggota tim.
2. **Token Referensi Cepat** — saat mengetik, referensi disimpan sebagai token berisi UUID dan nama tampilan, agar rujukan tetap valid meski nama produk/bahan/merk berubah:
   - `#` → produk
   - `/` → bahan baku
   - `!` → merk
3. **Notifikasi** — masing-masing mention tercatat di `team_note_mentions` dan memunculkan **badge merah pada navbar** untuk penerima mention yang belum membacanya.
4. **Status Pengerjaan** — note dapat ditandai **selesai** atau **dibuka kembali**; halaman menyediakan tampilan "all" atau "pending".
5. **Hapus** — hanya penulis note yang dapat menghapus note-nya sendiri.

---

### 4.12 Monitoring Efek Samping (NIES)

Modul **cosmetovigilance** untuk pencatatan keluhan efek samping produk. Dijalankan dari **Tab Bab 4** di halaman Edit Produk.

1. **Generate Laporan per Semester** — laporan dibuat untuk periode semester berjalan (`YYYY-H1` untuk Januari–Juni, `YYYY-H2` untuk Juli–Desember), dan periode terakhir disimpan di `products.last_efek_samping_period` agar tidak ganda.
2. **Input Kasus** — bila ada kasus keluhan, isi data kasus: **Nama**, **Jenis Kelamin**, **Usia**, **Jenis Efek**, **Manifestasi**, dan **Tanggal**. Bila tidak ada kasus, cukup tandai "tidak ada kasus" tanpa mengisi detail.
3. **Append, Bukan Timpa** — PDF baru **ditambahkan di belakang** PDF sebelumnya, sehingga produk memiliki satu dokumen riwayat yang utuh per semester. Bila PDF lama tidak terbaca, sistem tetap membuat blok baru saja dan mencatat kegagalan ke log.
4. **Anti-Overwrite** — proses generate dikunci per produk (`asyncio.Lock`), jadi dua permintaan bersamaan untuk produk yang sama tidak akan saling menimpa.
5. **Hapus Laporan** — aksi hapus tersedia bila laporan memang keliru dan perlu dibuat ulang dari awal.
6. **Penyimpanan** — PDF disimpan di bucket `raw-material-docs` pada path `products/{id}/monitoring_efek_samping_{slug_produk}.pdf`, dan tautannya dipakai sebagai lampiran di dokumen Bab IV.

> ⚠️ **Bedakan dari dokumen statis perusahaan:** di halaman `/admin/company-documents` ada dokumen bernama serupa, yaitu **"Monitoring Efek Samping"** yang merupakan dokumen/SOP perusahaan. Itu dokumen yang diunggah manual, **berbeda** dari laporan NIES yang di-generate per produk di sini. Keduanya dapat dipakai sebagai lampiran Bab IV, dan checklist Bab IV membaca keduanya.

---

### 4.13 Sistem Tema & Tampilan Aplikasi

Seluruh halaman aplikasi mewarisi satu shell, `app/templates/base.html`, yang menyediakan 4 block: `html_class`, `title`, `head_extra`, dan `content`. Navigasi dipusatkan di `app/templates/_sidebar.html`.

#### A. Empat tema

| Nama | Karakter | `color-scheme` |
|---|---|---|
| **Light** | Tampilan standar. Nilai warna diambil dari pembacaan `oklch()` Tailwind v4 di browser, sehingga identik dengan Tailwind bawaan. | `light` |
| **Terra** | Nuansa hangat. Tombol di-*re-tint*, tetapi palet status (hijau/merah/amber/…) **salin verbatim dari Light**. | `light` |
| **Rose** | Nuansa pink. Palet status juga disalin, **kecuali** status `rose` yang diisi nilai merah — karena kotak `rose-50` pada chrome pink akan terbaca sebagai dekoratif, bukan error. | `light` |
| **Dark** | Mode gelap. Kontrol form native diberi styling khusus (lihat catatan di bawah). | `dark` |

> ⚠️ **Nama resmi PT Heka mengandung huruf "ERFI".** Karena itu deteksi perusahaan di `excel_generator.py` dan `dip_documents.py` selalu mengecek `heka`/`haraka` **lebih dulu**, baru `erfi`. Urutan terbalik akan salah mewarnai dokumen PT Heka.

#### B. Arsitektur CSS dua lapis

`app/static/theme.css` (±1.100 baris) sengaja dibangun berlapis:

1. **Lapisan token** — satu blok CSS per tema yang mendefinisikan semua custom property. Nilai warna di sini **literal**.
2. **Lapisan mapping** — utility class Tailwind dipetakan ke token, ditulis **sekali**, **tanpa literal warna**, dan setiap aturan memakai `!important` supaya mengalahkan utility Tailwind CDN tanpa bergantung pada urutan `@layer`.

Keluarga token: permukaan (`--t-page`, `--t-surface` … `--t-surface-5`), hover, teks (`--t-text-950` … `--t-placeholder`), border, brand/tautan, tombol & gradian, serta form dan miscellaneous (`--t-field-bg`, `--t-scrollbar-thumb`, `::selection`). Warna status berupa 11 keluarga (`green`, `emerald`, `red`, `rose`, `amber`, `yellow`, `orange`, `sky`, `blue`, `violet`, `purple`, `fuchsia`), masing-masing dengan varian `-text-*`, `-hover-*`, `-bg-50/100`, dan `-border-*`.

**Yang sering terlewat pada sistem tema berbasis Tailwind:** kontrol form native. Tailwind CDN tidak menata `<select>`, `<option>`, checkbox, date picker, maupun scrollbar, sehingga elemen-elemen ini akan tetap mengikuti sistem operasi. Untuk itu `theme.css` menyediakan aturan native khusus yang berlaku pada `dark`, `terra`, dan `rose`. **Light sengaja dibiarkan apa adanya** supaya tampilannya tetap persis seperti bawaan.

#### C. Menyimpan & menerapkan tema

- Atribut `data-theme` diletakkan pada elemen `<html>`.
- Preferensi disimpan di `localStorage` dengan kunci **`heka-theme`**.
- **Anti-flash:** skrip inline sinkron di `<head>` `base.html` menjalankan urutan ini sebelum stylesheet pertama termuat — sehingga tidak ada kedipan tema putih:
  1. Bila `<html>` punya class `force-light`, paksa tema light dan berhenti.
  2. Baca `localStorage['heka-theme']`; bila nilainya bukan salah satu dari empat tema yang dikenal, jatuh ke `prefers-color-scheme`.
  3. Bila `localStorage` diblokir, jatuh ke light.
- `localStorage` hanya ditulis saat pengguna **memilih** tema secara eksplisit.
- **`beforeprint`/`afterprint`:** bila tema aktif bukan light, tema disimpan sementara, dipaksa light selama pencetakan, lalu dipulihkan setelah selesai.
- Halaman preview FSP meng-override `html_class` dengan `force-light`, sehingga tombol switcher tema otomatis disembunyikan di sana.

#### D. Sidebar & navigasi

Menu (urutan di DOM): Dashboard · Bahan Baku · Produksi · Analisis PO · Pengajuan Sample · Kelola Merk · Notes · **[Admin]** Sampah · pemisah · **[Admin]** Administration (Manage Users, Dokumen Perusahaan) · Logout di footer.

- **Mode collapsed:** menyempit ke ikon saja, label disembunyikan, item dipusatkan, dan **tooltip muncul saat hover maupun saat fokus keyboard**. Status collapsed disimpan di `localStorage: sidebarCollapsed`. Pada layar 768–1023px sidebar otomatis collapsed pada kunjungan pertama.
- **Drawer mobile (≤767px):** sidebar menjadi off-canvas dengan overlay. Ditutup lewat klik overlay, tombol tutup, klik tautan navigasi, atau tombol Escape. Saat keluar dari viewport mobile, drawer ditutup.
- **Submenu Administration** bisa dilipat, dan otomatis terbuka bila salah satu child-nya sedang aktif.
- **Badge mention** merah pada menu Notes, diisi polling tiap 30 detik; nilainya dibatasi `99+`.

#### E. Keyboard & aksesibilitas

Menu tema dapat dikemudikan penuh: `Esc` menutup dan mengembalikan fokus ke tombol, `↑`/`↓` berpindah opsi, `Home`/`End` lompat ke ujung, dan `Tab` menutup menu tanpa menjebak fokus. Semua tombol navigasi punya `aria-expanded`/`aria-controls`, menu tema memakai `role="menu"` + `menuitemradio`, dan item aktif memakai `aria-current="page"`. `prefers-reduced-motion: reduce` menonaktifkan transisi menu.

> ℹ️ **Tidak ada header CSP.** Ini konsisten dengan keberadaan skrip inline (anti-flash tema, notifikasi ED, sapaan login) dan Tailwind browser build yang mengevaluasi CSS saat runtime. Escaping dilakukan per-sink: nilai tak tepercaya masuk lewat `textContent`, dan hanya nilai yang lolos helper `escapeHtml` yang disisipkan sebagai HTML. Data untuk Chart.js dikirim sebagai `<script type="application/json">` ber-`tojson`, yang meng-escape `<`, `>`, `&`, dan `'` menjadi `\uXXXX` — sehingga aman tanpa `|safe`.

#### F. Polling di sisi browser

| Interval | Endpoint | Dilewati saat tab tak terlihat |
|---|---|---|
| 25 detik | `POST /api/presence/heartbeat` | Ya |
| 30 detik | `GET /api/notes/mentions/unread-count` | Tidak |
| 15 detik | `GET /api/admin/users/presence` | Ya |
| Sekali saat dibuka | `GET /api/ed-notifications` | — |

Keempat path tersebut juga disaring dari access log server agar terminal tetap terbaca.

---

### 4.14 Toolkit Migrasi Data (`migration/`)

Folder `migration/` berisi skrip untuk memindahkan data historis dari spreadsheet ke Supabase. **Folder ini sengaja tidak di-commit ke git** (lihat `.gitignore`) karena berisi data operasional perusahaan.

#### A. Konvensi yang dipatuhi seluruh skrip

1. **Read-only secara default.** Skrip hanya menulis ke database bila dijalankan dengan `--execute --yes`. Tanpa `--yes`, perintah itu berhenti dengan pesan error.
2. **Dry-run lebih dulu.** `--dry-run` (mode default) menulis laporan CSV/JSON ke `migration/_report_rekap/` tanpa menyentuh database.
3. **Penjaga SHA-256.** Bila SHA-256 berkas sumber atau berkas alias berubah sejak dry-run terakhir, skrip **berhenti** sebelum menulis, kecuali diberi `--force-plan-changed`.
4. **Manifest.** Setiap baris yang berhasil ditulis dicatat lengkap dengan `id`-nya ke `manifest_*.json`, ditulis ulang **sebelum** proceeds ke baris berikutnya — sehingga run yang terputus tetap bisa di-rollback.
5. **Rollback berdasarkan manifest.** Skrip `rollback_*.py` membaca manifest dan menghapus hanya baris yang tercatat di dalamnya.

#### B. Skema SQL

| File | Isi |
|---|---|
| `001_create_purchase_orders.sql` | Membuat **`purchase_orders`** dan **`purchase_order_items`** beserta FK dan UNIQUE. ⚠️ **Tidak membuat `product_batches`** — tabel itu harus sudah ada sebelumnya, dan file ini hanya mereferensikannya dengan FK `RESTRICT` |
| `002_add_jenis_po.sql` | Menambah kolom `purchase_orders.jenis_po` untuk PO Rework |

> ⚠️ Skema produksi **tidak dikelola otomatis** — jalankan file SQL ini manual melalui Supabase SQL Editor.

#### C. Skrip migrasi & rollback

| Skrip | Tujuan | Rollback |
|---|---|---|
| `migrate_po.py` | Impor PO & batch produksi dari spreadsheet | — |
| `migrate_po_rekap.py` | Impor **REKAP SOP** 2026: produk, PO, batch, item, produk baru | `rollback_po_rekap.py` |
| `import_po_heka.py` | Impor **header PO PT Heka** (PO tanpa item) | `rollback_po_heka.py` |
| `import_po_heka_batch.py` | Impor **batch PT Heka** dari `CATATAN BATCH HEKA - 2026.xlsx` — mengisi item + batch pada PO header-only | `rollback_po_heka_batch.py` |
| `import_missing_na.py` | Impor produk dari NA yang belum terdaftar | — |
| `update_qty_pcs.py` | Koreksi `qty_pcs` PO | `rollback_qty_pcs.py` |
| `tag_rework_po.py` | Tandai `jenis_po = 'Rework'` | — |
| `fix_po_number.py` | Normalisasi penomoran PO | — |
| `fill_perusahaan.py` | Lengkapi kolom `perusahaan` pada master produk | — |

#### D. Prinsip pemrosesan yang konsisten

Prinsip inilah yang membuat hasil migrasi bisa dipercaya — dan semuanya berlaku seragam di seluruh skrip:

* **Deteksi kolom berbasis header, bukan posisi tetap.** Peta kolom dievaluasi terhadap baris header; bila tidak cocok dengan harapan, skrip **berhenti** alih-alih menebak.
* **Tidak ada tebakan.** Field tanpa sumber ditulis `NULL`. Nilai yang tak bisa dipastikan masuk ke laporan `REVIEW`/`HELD`, tidak pernah ditebak.
* **Normalisasi tanggal dari kode batch.** `tanggal_catatan_batch` dan `tanggal_produksi` diturunkan dari 6 digit awal `no_batch` (`YYMMDD`) bila tersedia — **bukan** dari kolom Tgl SOP di spreadsheet. Tujuannya memakai tanggal yang tertanam pada batch.
* **Deteksi footer berlapis.** Baris footer dikenali dari isi kolom **A** maupun kolom **F**, karena beberapa sheet menaruh label footer di kolom F. Tanpa ini, baris footer pernah lolos sebagai data.
* **Perbaikan otomatis hanya diterima bila ada bukti.** Contoh: kandidat nomor PO hasil normalisasi hanya dipakai bila kandidat itu benar-benar ada di `purchase_orders`. PO yang tidak ada dilaporkan HELD, **tidak pernah dibuat**.
* **Pemulihan kolom A/B terbalik.** Beberapa baris menaruh No. PO di kolom A dan Tgl PO di kolom B; skrip memulihkannya per-baris dan mencatat perbaikannya.
* **Cache batch wajib.** Karena `product_batches` belum punya batasan `UNIQUE (product_id, no_batch)`, skrip **wajib** memakai cache batch lokal; tanpa itu satu batch yang muncul di beberapa baris akan ter-insert berkali-kali.

#### E. Berkas pendukung

| Berkas | Fungsi |
|---|---|
| `na_aliases.csv` | Pemetaan NA salah-ketik → NA master yang benar, tiap baris disertai catatan tanggal & alasan persetujuan |
| `name_aliases.csv` | Alias nama produk |
| `overrides.csv` | Override nilai per PO/batch |
| `po_number_allow.csv`, `po_number_fix.csv` | Daftar izinkan & perbaikan nomor PO |
| `po_rework_tag.csv` | Daftar PO Rework |
| `qty_pcs_override.csv` | Override `qty_pcs` |
| `po_heka_item_na.csv`, `po_heka_rework.csv` | Pemetaan NA item & PO rework PT Heka |

#### F. Rekap hasil migrasi PT Heka (5 Oktober 2026)

Sebagai referensi operasional, migrasi `CATATAN BATCH HEKA - 2026.xlsx` (Januari–Agustus 2026) menghasilkan:

| Tabel | Sebelum | Sesudah |
|---|---|---|
| `purchase_order_items` | 620 | 913 (+293) |
| `product_batches` | 614 | 905 (+291) |
| PO header-only | 156 | 24 |

`purchase_orders` **tidak bertambah** — tidak ada header PO yang dibuat. `na_aliases.csv` kini memuat **7 alias**; **4 di antaranya** berasal dari migrasi ini (NA Night Cream, Acne Calm Balance Night Cream, Alora Glow Body Lotion terpotong, dan PHERINI Body Lotion Alchemist), semuanya disetujui pengguna dan disertai catatan tanggal.

---

## 5. Matriks Validasi, Status & Logika Bisnis

### 5.1 Monitoring Otomatis Status Legalitas NA BPOM
Status Notifikasi BPOM (NA) dihitung otomatis dari `tanggal_aktif_na`:
- Masa berlaku standar NA BPOM: **3 tahun** sejak tanggal aktif. Bila tanggal aktif jatuh pada 29 Februari, tanggal kedaluwarsa digeser ke 28 Februari pada tahun tujuan yang bukan tahun kabisat.
- 🟢 **Aktif** — masih lebih dari 180 hari (~6 bulan) sebelum expired.
- 🟡 **Akan Expired** — sisa masa berlaku ≤ 180 hari.
- 🔴 **Expired** — sudah melewati 3 tahun sejak tanggal aktif.
- ⚪ **Belum Terdaftar** — tanggal aktif NA belum diisi (status manual dipakai sebagai fallback).

### 5.2 Matriks Kelengkapan DIP & Indikator Progress
Di Dashboard, tiap produk punya indikator kelengkapan (`progress_pct`) dihitung dari pemenuhan **17 item dasar**:

| Bab | Item dasar | Kriteria "lengkap" |
|---|---|---|
| **Bab I** | 5 | NIB, Sertifikat CPKB, Hak & Lisensi Merk, Surat Tidak Pidana, Surat Notifikasi BPOM — semuanya harus terisi untuk perusahaan produk yang dipilih |
| **Bab II** | 1 | Produk sudah punya formula (minimal 1 baris bahan baku) |
| **Bab III** | 7 | Cara pembuatan, sistem penomoran batch, spek produk jadi, spek pengemas, laporan uji SIG, protokol stabilitas, hasil stabilitas |
| **Bab IV** | 4 | Laporan keamanan, monitoring efek samping, desain primer, desain sekunder |

Tambahan: **Data Pendukung Klaim** dihitung sebagai **nilai tambah di pembilang tanpa ditambah ke pembagi**, sehingga persentase dapat naik di atas 100% bila semua item dasar sudah lengkap. Pada tampilan dashboard, kondisi ini ditandai warna **amber** dan panjang bar dibatasi 100% supaya tidak melebihi layar.

> ℹ️ **Perbedaan lapisan dokumen Bab IV:** checklist PDF Bab IV menampilkan lebih banyak baris daripada rasio dashboard, karena checklist juga memuat dokumen dari sumber lain — **CV / Kualifikasi Safety Assessor** dan **Monitoring Efek Samping** dari dokumen perusahaan (`company_sop_documents`), serta **Rancangan Teks Kemasan**. Angka rasio dashboard di atas mengacu pada dokumen produk, bukan seluruh baris checklist.

### 5.3 Aturan Proteksi Penghapusan Data
- **Perlindungan Bahan Baku** — sistem **melarang** penghapusan bahan baku yang masih dipakai di formula produk aktif. Bahan baku harus dilepas dari formula dulu sebelum dihapus dari master data. Penghapusan bahan baku sekaligus ikut menghapus batch, dokumen per perusahaan, komponen, dan varian komposisinya.
- **Perlindungan Produk (Soft Delete + Sampah)** — menghapus produk **tidak** langsung menghilangkan datanya. Produk ditandai terhapus (`products.is_deleted` + `deleted_at`) sehingga formula, dokumen, dan riwayatnya tetap utuh. Admin dapat membuka menu **Sampah** (`/admin/trash`) untuk melihat daftar produk terhapus dan **mengembalikannya**; aksi restore ini juga tercatat di `activity_logs`. Produk terhapus tidak muncul lagi di dashboard, daftar produk pada form lain, maupun saat memilih produk pada modul Produksi.
- **Perlindungan Varian Komposisi** — varian komposisi yang sudah dipakai di suatu formula tidak bisa dihapus selama masih dirujuk oleh baris formula.
- **Perlindungan Log Aktivitas** — nama produk/bahan baku yang dihapus tetap direkam di `activity_logs` sebelum baris datanya benar-benar hilang, supaya riwayat aktivitas tetap informatif walau data aslinya sudah tidak ada.

> ⚠️ **Ketidakseimbangan yang perlu diketahui:** penghapusan **produk** tidak punya proteksi apa pun selain soft delete — tidak ada pemeriksaan dependensi, dan **tidak ada pemeriksaan role**, sehingga akun Staff pun bisa menghapus produk mana pun. Sebaliknya penghapusan **bahan baku** dilindungi pemeriksaan pemakaian formula. Perlu dicatat juga: pemeriksaan pemakaian bahan baku menghitung produk yang sudah soft-deleted sebagai "masih dipakai", sementara badge `usage_count` dan API "Dipakai di Produk" secara sengaja **tidak** menghitungnya — jadi keduanya bisa terlihat berbeda.
>
> ⚠️ **`ACC Dimusnahkan` tidak meng-nolkan stok.** Baris penulisan `qty` sengaja dikomentari dengan catatan "Uncomment if you have a qty column". Aksi ini juga **tidak** menghapus objek storage milik batch tersebut, berbeda dengan cascade delete bahan baku.

### 5.4 Status ED Batch Bahan Baku

Ambang ED memakai aturan yang sama dengan NA, tetapi diterapkan ke `raw_material_batches`:

- Batch dengan `status_ed = "Dimusnahkan"` **dilewati** sepenuhnya — batch yang sudah dimusnahkan tidak pernah muncul sebagai notifikasi.
- Batch dengan `tanggal_ed` kosong juga dilewati.
- Batch dengan sisa hari ≤ **180** dianggap kritis. Status `Active` di-*rewrite* menjadi `Expired` (sisa ≤ 0) atau `Kritis (<= 180 hari)` — **khusus untuk tampilan**, nilai aslinya tidak pernah ditulis balik ke database.
- Daftar diurutkan menaik berdasarkan sisa hari, sehingga yang expired paling dulu muncul.

> ⚠️ **Badge ED punya dua arti berbeda.** Di halaman Bahan Baku, angka pada badge hanya menghitung **batch**; di halaman lain (dashboard, produk, dsb.) angka itu juga menghitung **NA produk**. Nama variabelnya sama, isinya berbeda.

### 5.5 Cakupan Detail dalam Audit Trail

`activity_logs` menyimpan `actor_id`, `actor_name`, `action`, `entity_type`, `entity_id`, `entity_label`, dan `changes`. Timestamp diisi oleh database, bukan aplikasi.

| Jenis entitas | Aksi yang tercatat |
|---|---|
| `product` | `create`, `update`, `delete`, `restore`, `generate` (efek samping), `public_link_visit` |
| `product_finished_specs` | `update` |
| `product_qualquan_xlsx` | `export` |
| `{doc_type}` perusahaan | `update` (NIB, CPKB, Surat Tidak Pidana, Protap, CV, SOP CPKB) |
| `user` | `reset_password` |
| `raw_material` | `create`, `update`, `delete` |
| `raw_material_variant` | `create`, `update`, `delete` |
| `raw_material_batch` | `edit`, `acc_dipakai`, `acc_dimusnahkan` |
| `raw_material_company_doc` | `edit` |
| `note` | `create`, `delete`, `complete`, `reopen` |

> ⚠️ **Beberapa operasi sengaja tidak di-log:** pembuatan & penghapusan user, tambah brand, unggah dokumen brand, dan seluruh operasi FSP (create/edit/delete) **tidak** tercatat di audit trail. Bila riwayat aktivitas ini dibutuhkan untuk audit, itu celah yang perlu ditutup.
>
> ℹ️ Perubahan field dokumen tidak logged sebagai pasangan URL lama → baru, melainkan sebagai catatan **"File diganti"** — karena upload menimpa berkas di tempat sehingga URL-nya tidak berubah dan mencatatnya hanya membingungkan.


---

## 6. Spesifikasi Teknis & Integrasi File Storage

### 6.1 Limitasi Ukuran File Upload
- Batas maksimal ukuran file yang diunggah: **10 MB per file PDF**.
- Kalau file yang diunggah melebihi batas ini, sistem menangkap error HTTP 413 (*Content Too Large*) dan mengarahkan kembali pengguna ke halaman asal dengan pesan peringatan yang jelas — baik saat validasi gagal di sisi browser maupun kalau entah bagaimana lolos dan baru tertangkap di sisi server.

### 6.2 Integrasi Supabase Storage & PostgreSQL Database
- **Database:** Supabase PostgreSQL. Aplikasi memakai **satu klien Supabase global** yang dibangun dari *service role key* sehingga melewati RLS untuk seluruh request. Tabel yang dipakai aplikasi:
  - **Master & Produk:** `profiles` (user, role, `is_protected`, data presence), `products`, `brands`, `producers`, `product_formula_lines`, `product_finished_specs`, `product_batches`.
  - **Bahan Baku:** `raw_materials`, `raw_material_components`, `raw_material_composition_variants` (varian komposisi), `raw_material_batches`, `raw_material_company_docs` (dokumen per perusahaan).
  - **Produksi:** `purchase_orders`, `purchase_order_items`.
  - **Kolaborasi:** `team_notes`, `team_note_mentions`.
  - **Form Pengajuan:** `sample_submissions`.
  - **Audit:** `activity_logs`, `public_link_audits`.
  - **Dokumen legal/statis per perusahaan:** `nib_documents`, `sertifikat_cpkb_documents`, `surat_tidak_pidana_documents`, `company_sop_documents`, `cpkb_raw_material`, `brand_legal_documents`.
  - > Daftar di atas adalah tabel yang **dipanggil oleh kode**. Untuk rincian kolom dan relasi, rujuk ke skema/migrasi resmi di repository.
- **Object Storage:** file PDF (MSDS, CoA, Halal, NIB, CPKB, dst) disimpan di Supabase Storage. Sebagian besar diakses lewat public URL; khusus di halaman Public Hub verifikator BPOM, tautan file memakai *signed URL* sementara (kedaluwarsa otomatis) sebagai lapisan keamanan tambahan — **dengan fallback ke public URL mentah bila pembuatan signed URL gagal**, agar halaman tidak ikut mati.
  - Bucket yang dipakai: `legal-documents` (dokumen perusahaan), `raw-material-docs` (SOP CPKB, dokumen bahan baku, serta laporan Monitoring Efek Samping per produk), dan bucket unggahan dokumen produk.

#### Skema Modul Produksi

| Tabel | Kolom kunci & batasan |
|---|---|
| `purchase_orders` | `no_po` unik, `tanggal_po` (nullable), `qty_pcs` (nullable). Dibuat oleh `001_create_purchase_orders.sql` |
| `purchase_order_items` | `UNIQUE (purchase_order_id, urutan)`; `product_id` dan `product_batch_id` keduanya **NOT NULL** dengan FK `RESTRICT`; kolom numerik: `wip`, `qty_kg`, `qty_belum_sop`, `qty_po_kg`; kolom teks: `netto`, `keterangan`, `status_bpom`, `catatan_produksi`, `revisi_produksi`, `temporary_reject`; `tanggal_catatan_batch` bertipe tanggal; `excel_row` menyimpan provenance baris spreadsheet. Dibuat oleh `001` |
| `product_batches` | `product_id` + `no_batch`; `tanggal_produksi` **NOT NULL**. ⚠️ **Tabel ini tidak dibuat oleh file migrasi mana pun** — harus sudah ada di database, dan belum punya batasan `UNIQUE (product_id, no_batch)` |

> ⚠️ **Tidak ada `UNIQUE (product_id, no_batch)` pada `product_batches`.** Konsekuensinya, proses apa pun yang menyisipkan batch wajib memakai cache lokal `{product_id, no_batch} → id`, karena UNIQUE di level aplikasi adalah satu-satunya penjaga. Togkat perlu menambahkan constraint ini, lakukan dedup terlebih dahulu.
>
> ℹ️ Karena `product_batch_id` NOT NULL, **item PO tidak bisa dibuat tanpa batch**. Inilah alasan modul Produksi selalu membuat batch lebih dulu.

### 6.3 Audit Trail System (`activity_logs`) & Server Logging
- Setiap aktivitas penting dicatat otomatis ke tabel `activity_logs` — termasuk `create`, `update`, `delete` pada bahan baku dan produk, pembuatan Purchase Order, batch produk, item PO, serta `generate` laporan Monitoring Efek Samping. Cakupan lengkap entitas & aksi ada di [§5.5](#55-cakupan-detail-dalam-audit-trail). Catatan mencakup siapa pelakunya, jenis objek, ID target, dan detail field yang berubah (nilai lama vs baru untuk field teks; catatan "File diganti" untuk field dokumen).
- Terminal server (Uvicorn/Render) menampilkan log yang sama secara real-time dengan format timestamp **WIB (Asia/Jakarta)** — berguna untuk pengecekan cepat, tapi diingat log Render sendiri **cuma disimpan 7 hari**; untuk riwayat jangka panjang selalu rujuk ke tabel `activity_logs`.
- Kesalahan pada proses generator dokumen (mis. lampiran gagal diambil atau file PDF rusak) **tidak** ditampilkan ke pengguna sebagai pesan teknis; kesalahan dicatat di log server agar bisa ditelusuri tanpa mengganggu alur kerja. Prinsipnya: **satu lampiran bermasalah tidak boleh menggagalkan seluruh dokumen**.
- **Penyaringan access log:** empat endpoint poller berfrekuensi tinggi (`/health`, `/api/presence/heartbeat`, `/api/notes/mentions/unread-count`, `/api/admin/users/presence`) disaring dari access log agar terminal tetap terbaca.

### 6.4 Manajemen Dokumen Perusahaan (`/admin/company-documents`)
Sebelum September 2026, 8 jenis dokumen statis per-perusahaan (NIB, Sertifikat CPKB, Surat Tidak Pidana, Protap No. Batch, Protap Pemeriksaan Produk Jadi, CV Safety Assessor, Monitoring Efek Samping, serta **SOP CPKB Pemeriksaan Bahan Baku**) hanya bisa diubah lewat Supabase Dashboard langsung (atau dari halaman bahan baku untuk SOP CPKB). Kini tersedia halaman admin khusus (`/admin/company-documents`) yang memungkinkan admin mengunggah dan mengganti file-file tersebut langsung dari aplikasi.
- **Akses:** Admin-only (`/admin/company-documents`), link tersedia di dashboard.
- **8 Dokumen × 2 Perusahaan:** Tabel matriks menampilkan status (ada/tidak) + tombol "Upload"/"Ganti" untuk masing-masing. Satu modal upload dipakai bersama, hidden input diisi via JS.
- **Storage:** Dokumen disimpan di 2 bucket berbeda:
  - `legal-documents` (NIB, Sertifikat CPKB, Surat Tidak Pidana, Protap No. Batch, Protap Pemeriksaan Produk Jadi, CV Safety Assessor, Monitoring Efek Samping) — path `company-docs/{doc_type}_{erfi|heka}.pdf`
  - `raw-material-docs` (SOP CPKB Pemeriksaan Bahan Baku) — path `sop-cpkb/sop_cpkb_{erfi|heka}.pdf`
- **Upsert:** 4 tabel pertama (`nib_documents`, `sertifikat_cpkb_documents`, `surat_tidak_pidana_documents`, `cpkb_raw_material`) masing-masing 1 baris per perusahaan, kolom `file_url`. Untuk `company_sop_documents` (4 kolom berbeda dalam 1 tabel), update hanya kolom spesifik — tidak overwrite seluruh baris atau bikin duplikat.
- **Audit Trail:** Setiap upload tercatat di `activity_logs` dengan detail jenis dokumen & perusahaan.
- **Validasi:** File wajib PDF, maksimal 10 MB (konsisten dengan upload lain di aplikasi).

### 6.5 Integrasi AI Opsional (Sapaan Login)

- **Fungsi:** saat pengguna berhasil login, sistem membangkitkan satu kalimat sapaan singkat melalui **Google Gemini API**, lalu menyimpannya di cookie `greeting_cache` (masa berlaku 4 jam) supaya tidak dipanggil ulang setiap kali dashboard dibuka.
- **Konfigurasi:** variabel lingkungan `GEMINI_API_KEY` di file `.env`. **Opsional** — bila kosong, fitur otomatis dimatikan dan aplikasi tetap berjalan normal (hanya kalimat sapaan statis per waktu yang tampil).
- **Catatan privasi:** nama pengguna dikirim ke API Gemini untuk keperluan pembangkitan kalimat. Bila kebijakan perusahaan melarang aliran data ke layanan pihak ketiga, biarkan `GEMINI_API_KEY` kosong.
- **Perilaku saat gagal:** bila panggilan API gagal atau lambat, sistem diam-diam memakai kalimat sapaan statis — fitur sapaan tidak boleh menggagalkan proses login.
- **Mekanisme:** gaya prompt berganti antara hari ganjil (humor kasual) dan genap (profesional), mencoba tiga model secara berurutan dengan timeout 4 detik. Kegagalan total bersifat senyap.
- ⚠️ Cookie `greeting_cache` bersifat `httponly` tetapi **tidak ditandatangani maupun dienkripsi** isinya.

### 6.6 Ketergantungan yang Tidak Tercantum di `requirements.txt`

Dua paket diimpor tapi tidak terdaftar. Semuanya sudah dibungkus fallback, kecuali satu:

- **Pillow** (`PIL`) — dipakai untuk mengukur lebar logo dan me-*flatten* PNG RGBA ke latar putih (file PNG RGBA tidak bisa dirender `xhtml2pdf` tanpa itu). Kedua pemanggilannya dibungkus `try/except` dan jatuh ke lebar logo tetap, jadi fiturnya boleh tidak terpasang.
- **python-dotenv** (`dotenv`) — dipanggil `load_dotenv()` di `main.py` **tanpa penjaga**, padahal `pydantic-settings` sudah membaca `.env` sendiri. Akibatnya lingkungan yang benar-benar belum memasangnya akan gagal saat start.

### 6.7 Ketergantungan Sisi Browser

Dimuat via CDN, **tanpa atribut `integrity`/`crossorigin`**: `@tailwindcss/browser` v4, Font Awesome 6.4.0, dan Chart.js 4.4.3 (hanya di `/po-analytics`). Aplikasi memang tidak memasang header CSP — konsisten dengan skrip inline dan Tailwind browser build. Detail pola escaping ada di [§4.13.E](#e-keyboard--aksesibilitas).


---

## 7. FAQ & Troubleshooting

**Q1: Mengapa spesifikasi bahan baku dan MSDS dipisahkan antara PT Erfi dan PT Heka?**
PT Erfi dan PT Heka adalah dua badan hukum terpisah dengan sertifikat CPKB dan standar mutu masing-masing. Dokumen yang dilampirkan ke BPOM harus mencantumkan kop surat dan legalitas entitas yang tepat — data yang sama untuk keduanya bisa jadi bukan hal yang benar.

**Q2: Kenapa lebih baik pakai Download Folder (ZIP) untuk Bab II dibanding PDF gabungan?**
Alasannya berubah. **PDF gabungan Bab II saat ini tidak memuat Sertifikat Halal maupun MSDS** — keduanya hanya disertakan pada versi ZIP. Jadi pilih ZIP bila dokumen yang perlu dikirim/diarsipkan memang harus menyertakan Halal & MSDS, atau bila ingin lampiran terpisah per bahan baku agar mudah ditelusuri. Pilih PDF gabungan bila yang dibutuhkan adalah satu berkas ringkas dengan satu halaman per bahan baku, dan Halal/MSDS ditangani lewat berkas terpisah.

**Q3: Section Spek di PDF Bab II kosong, padahal data spesifikasi sudah saya isi. Kenapa?**
Karena pada **PDF gabungan**, Spek bahan baku **hanya diambil dari PDF** (`PDF Spesifikasi Asli dari Supplier`). Parameter spesifikasi yang diketik manual sengaja tidak dipakai di PDF gabungan — jadi Spek baru muncul kalau PDF-nya sudah diunggah. (Data ketikan tetap dipakai di versi ZIP, jadi isian Anda tidak hilang.) Nama bahan baku itu juga akan muncul di daftar "belum memiliki Spek dan Catatan Pemeriksaan" di bagian akhir PDF.

**Q4: Kenapa ada dua daftar dokumen kurang di bagian akhir PDF Bab II?**
Satu untuk bahan baku yang tidak punya Spek **dan** Catatan Pemeriksaan, satu lagi untuk bahan baku yang COA-nya belum terlampir atau gagal diambil. Keduanya sengaja dipisah karena jenis dokumen yang hilang berbeda. Kalau salah satu daftar kosong, halamannya tidak dicetak sama sekali.

**Q5: Bagaimana mengatasi pesan "Sesi Anda Telah Berakhir"?**
Token sesi (JWT) sudah kedaluwarsa (masa berlaku 4 jam). Silakan login ulang.

**Q6: Apakah link publik verifikator BPOM aman dari kebocoran data produk lain?**
Aman — setiap link memakai kombinasi slug nama produk (kosmetik) dan UUID acak 36-karakter yang divalidasi di server (*unguessable*). Portal publik hanya menampilkan data 1 produk sesuai UUID pada URL tersebut, dan setiap akses tercatat di audit log.

**Q7: Kenapa persentase di Formula Builder menunjukkan angka merah / tidak 100%?**
Standar BPOM mengharuskan total persentase formula kosmetik tepat 100.000% (w/w). Periksa kembali persentase bahan pelarut (misalnya *Aqua/Water*) agar akumulasi formula pas 100%.

**Q8: Kenapa upload file ditolak padahal ukurannya kelihatan kecil?**
Kemungkinan file melebihi 10 MB (cek ulang ukuran filenya), atau formatnya bukan PDF — sistem cuma menerima PDF untuk semua jenis lampiran dokumen.

**Q9: Login pakai username gagal padahal user saya terdaftar.**
Input "username" dicocokkan ke kolom `full_name` di tabel `profiles`, dan bila tidak ditemukan sistem memakai fallback domain `@erfi.com`. Untuk user PT Heka, cara yang paling aman adalah login memakai **email resmi**. Username yang tidak ada di `profiles` juga tidak bisa login.

**Q10: Kenapa status user saya di panel Admin muncul "Idle", bukan "Online"?**
Idle berarti tab masih terbuka dan heartbeat masih berjalan, tetapi tidak ada aktivitas selama 5 menit terakhir. Itu status normal, bukan error — status kembali Online begitu ada interaksi.

**Q11: Kenapa jumlah PO dan total qty di `/po-analytics` tidak sama-sama naik, padahal tidak ada PO yang dihapus?**
Karena PO bertanda **Rework** (`jenis_po = 'Rework'`) **tetap dihitung** sebagai jumlah PO tetapi `qty_pcs`-nya **tidak ikut dijumlahkan**. Ini disengaja agar volume rework tidak tercampur ke dalam produksi utama. Bila kolom `jenis_po` belum ada di database, seluruh qty dihitung tanpa pemisahan ini dan halaman menampilkan banner biru.

**Q12: Banner "PO belum punya item" muncul terus — apakah itu bug?**
Tidak. Banner itu justru alat transparansi. PO yang ada di `purchase_orders` tapi belum punya baris di `purchase_order_items` **tetap dihitung** pada Total PO dan Total qty (karena keduanya dibaca dari header), tetapi **tidak bisa diatribusikan** ke produk maupun perusahaan, sehingga tidak muncul di grafik per perusahaan. Penyebab umumnya adalah data produksi yang belum diimpor — lihat §4.14. Cara mengisinya: jalankan `import_po_heka_batch.py` atau input manual lewat modul Produksi.

**Q13: Kenapa PT Heka tampil 0 PO di grafik padahal PO-nya ada?**
Karena "0 PO" dan "0 PO teratribusi" adalah dua kondisi berbeda, dan teks di bawah grafik membedakannya. Bila PT Heka 0 sementara PT Erfi lebih dari 0, berarti PO PT Heka yang ada belum punya item — baca banner amber. Filter **Perusahaan → "Tanpa item"** di `/purchase-orders` dipakai untuk mengidentifikasi PO mana yang bermasalah.

**Q14: Total qty per perusahaan lebih besar daripada Total qty di KPI. Salah hitung?**
Bukan salah hitung. Satu PO yang memuat produk kedua perusahaan dihitung **penuh di keduanya**, sementara `total_pcs` di KPI menghitungnya **sekali**. Aturan ini dinyatakan eksplisit di bawah grafik. Bila ini tidak diinginkan, aturan hitungnya perlu diubah di kodenya — bukan di UI.

**Q15: Kenapa `qty_pcs` di grafik perusahaan tidak sama dengan penjumlahan qty item PO-nya?**
Karena `qty_pcs` selalu dibaca dari **header PO**, bukan dari item. Item dipakai hanya untuk menentukan **produk & perusahaan** apa yang diatribusikan. Konsekuensinya, satu PO dengan 5 item produk dihitung qty-nya **sekali** untuk perusahaan pertama yang memprosesnya — memang begitu desainnya, supaya tidak tergandakan.

**Q16: Tema gelap berubah sendiri saat saya print.**
Itu perilaku yang disengaja. `beforeprint` memaksa tema light (cetak ke kertas putih), lalu `afterprint` memulihkan tema asli. Untuk memaksa light permanen pada halaman tertentu, pakai class `force-light` pada `<html>` — itulah yang dipakai halaman preview FSP.

**Q17: Bisakah saya mengembalikan tema ke default?**
Buka menu tema di navbar → pilih **Light**. Preferensi disimpan di `localStorage` dengan kunci `heka-theme`. Menghapus kunci itu secara manual akan mengembalikan sistem ke `prefers-color-scheme` milik sistem operasi Anda.

**Q18: Kenapa sidebar saya tiba-tiba tersempit sendiri?**
Pada lebar layar 768–1023px sidebar otomatis dalam mode collapsed pada kunjungan pertama, supaya konten tidak tergerus. Bisa dikembalikan lewat tombol hamburger di navbar.

**Q19: Apakah aman menjalankan ulang skrip migrasi yang sudah pernah dijalankan?**
Umumnya aman, karena proteksinya berlapis: cache batch mencegah batch dobel, `UNIQUE (purchase_order_id, urutan)` mencegah item ganda, dan `purchase_orders` tidak pernah ditulis. Namun tetap jalankan `--dry-run` lebih dulu dan periksa statistiknya sebelum `--execute`.

**Q20: Kenapa `--execute` saya ditolak?**
`--execute` wajib disertai `--yes` sebagai konfirmasi eksplisit. Tanpa itu skrip berhenti dengan pesan error — ini pengaman supaya tidak ada penulisan database yang tidak disengaja.


---

## 8. Panduan Pemeliharaan & Bantuan

Jika menemukan kendala teknis, bug, atau butuh penyesuaian fitur baru pada DIP Automation System:
1. Catat langkah-langkah kejadian (*reproduction steps*) dan pesan error yang muncul di layar.
2. Ambil *screenshot* layar yang bermasalah.
3. Hubungi Tim Pengembang IT / System Administrator internal.

*DIP Automation System dipelihara secara berkala untuk menjamin kesesuaian dengan regulasi BPOM RI dan keamanan sistem.*