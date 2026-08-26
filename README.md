# Aplikasi Penyusun Dokumen Informasi Produk (DIP) Kosmetik

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![Framework](https://img.shields.io/badge/framework-FastAPI-green)
![Database](https://img.shields.io/badge/database-Supabase-emerald)
![Status](https://img.shields.io/badge/status-Bab_I_to_IV_Selesai-brightgreen)

Sistem otomasi berbasis web untuk menyusun, mengelola, dan menggenerasi **Dokumen Informasi Produk (DIP) Kosmetik** sesuai dengan regulasi standar BPOM dan pedoman ASEAN Cosmetic Directive (ACD).

🌐 **Live Demo:** [https://dip-automation-system.onrender.com/](https://dip-automation-system.onrender.com/)

---

## 📌 Status Pengembangan Sistem (Update: 26 Agustus 2026)

| Modul / Fase | Fitur & Cakupan | Status |
| :--- | :--- | :---: |
| **Spesifikasi Produk Jadi (PT Erfi)** | Form input spesifikasi QC produk jadi (Pemerian, Pengemasan Primer/Sekunder, Uji Mikrobiologi, Uji Cemaran Logam) dengan template default 5 section siap pakai, auto-fill data dari Informasi Dasar (`no_na_produk`, `netto`, `acc_sampel`), generate PDF meniru format dokumen QC resmi PT Erfi. Tabel: `product_finished_specs`. | ✅ **Selesai** |
| **Field Peringatan & Penyimpanan** | Field `peringatan` & `penyimpanan` di form Tambah/Edit Produk (Informasi Dasar), otomatis muncul di dokumen Bab IV (Text Design), Formula Kualitatif & Kuantitatif (backend openpyxl), dan Export Excel. | ✅ **Selesai** |
| **Export Excel via Backend (openpyxl)** | Export Qualitative-Quantitative Formula (3 sheet: "Formula Nama Dagang", "Formula INCI Murni", "Text Design") di-generate di server pakai `openpyxl` (styling profesional: header, border, auto-fit kolom), menggantikan SheetJS. | ✅ **Selesai** |
| **Quantity & Satuan pada Batch Bahan Baku** | Kolom `quantity` & `quantity_unit` (dropdown: kg/gram/liter/ml/pcs/roll/drum) di form Tambah & Edit Batch, ditampilkan di tabel Log Kedatangan Batch. | ✅ **Selesai** |
| **Badge Produk Pemakai Bahan Baku** | Di halaman Bahan Baku, tiap baris menampilkan badge `usage_count` (dari `product_formula_lines`), bisa diklik untuk lihat daftar produk via modal. | ✅ **Selesai** |
| **Rate Limiting & Countdown Timer Login** | Proteksi brute-force pada `POST /login` (maks 5 percobaan/menit per IP) memakai `slowapi`. Halaman login menampilkan alert + countdown timer visual saat limit tercapai. | ✅ **Selesai** |
| **Redesign Halaman Bahan Baku** | Tab Manajemen ED: indikator Sisa Hari (badge warna). Tab Log Kedatangan Batch: dokumen & aksi digabung jadi menu kebab, kolom Kesimpulan jadi ikon (✓/✗/⏳), wrap teks kolom Produsen. | ✅ **Selesai** |
| **Checklist DIP Dashboard — Badge Deep-Link** | Badge status tiap Bab (I–IV) di Checklist DIP jadi link langsung ke tab edit produk terkait di `/products/{id}/edit` (anchor `#tab-bab1` dst), tombol "Lengkapi" terpisah dihapus. | ✅ **Selesai** |
| **Quick-Add Merk (Combobox Search)** | Dropdown Merk pada form Tambah/Edit Produk diganti jadi search-combobox dengan opsi "Tambah merk baru" via modal tanpa keluar halaman. | ✅ **Selesai** |
| **Fase 1: Core System** | Master Data Bahan Baku, Formula Builder, Qualitative-Quantitative (Qual-Quan) Report, Export Excel & Print-to-PDF | ✅ **Selesai** |
| **Fase 2a: Dokumentasi Bahan** | Manajemen Batch Bahan Baku (CoA, Sertifikat Halal), MSDS, Integrasi Supabase Storage | ✅ **Selesai** |
| **Dokumentasi Multi-Perusahaan** | Spesifikasi, MSDS & PDF spesifikasi asli supplier disimpan per perusahaan (PT Erfi / PT Heka), kop surat & SOP CPKB per perusahaan pada dokumen DIP | ✅ **Selesai** |
| **Spesifikasi & Pemeriksaan QC per Batch** | Input parameter spesifikasi bahan + catatan pemeriksaan fisik/scan QC (PDF) & parameter uji laboratorium aktual per batch, dipakai langsung di Bab II versi ZIP | ✅ **Selesai** |
| **Cek Kelengkapan Dokumen Bahan Baku** | Tab "Cek Kelengkapan Dokumen" di halaman Bahan Baku — matriks status dokumen per perusahaan (badge ✓/✗) | ✅ **Selesai** |
| **Keamanan & User System** | Dual Auth (Username/Email), Admin Control Panel (`/admin/users`), Dimatikannya Self-Register, RBAC (`admin`/`staff`), HTTP-Only Cookies JWT, Session Expire Warning, validasi keunikan username | ✅ **Selesai** |
| **Generator Bab I DIP** | Kelengkapan Administrasi (NIB, Sertifikat CPKB, Hak & Lisensi Merk, Surat Tidak Pidana, No. Notifikasi BPOM) — cover checklist + merge lampiran jadi satu PDF | ✅ **Selesai** |
| **Generator Bab II DIP** | Data Mutu & Keamanan Bahan Kosmetika — spesifikasi per bahan baku (batch terbaru), checklist SOP CPKB, merge lampiran CoA/Halal/MSDS — tersedia PDF gabungan & versi Folder/ZIP | ✅ **Selesai** |
| **Generator Bab III DIP** | Data Mutu Produk Jadi — breakdown formula kualitatif-kuantitatif otomatis dari data Formula Builder | ✅ **Selesai** |
| **Generator Bab IV DIP** | Data Keamanan Produk (Safety Assessment) — laporan keamanan, CV safety assessor, monitoring efek samping, data klaim, desain kemasan | ✅ **Selesai** |
| **Checklist Kelengkapan DIP (Dashboard)** | Tab di dashboard: matriks kelengkapan Bab I–IV per produk + progress DIP (%) + status legalitas NA (belum terdaftar / aktif / akan expired / expired) | ✅ **Selesai** |
| **FSP (Form Pengajuan Sample Produk)** | CRUD pengajuan sample, auto-generate kode sample (`FSP/DD-MM-YYYY/X.Y`), nomor revisi otomatis, preview & cetak (print-to-PDF) | ✅ **Selesai** |
| **Manajemen Brand** | Tambah brand, upload dokumen Hak & Lisensi Merk per brand | ✅ **Selesai** |
| **Activity Log & Uptime Monitor** | Riwayat aktivitas tersimpan di tabel `activity_logs` + log terminal rapi; endpoint `/health` (GET & HEAD) untuk monitoring uptime | ✅ **Selesai** |
| **Edit Produk Multi-Tab (Bab 1–4)** | Halaman Edit Produk kini punya 5 tab: Informasi Dasar, Bab 1, **Bab 2 (Formula & Mutu Bahan)**, Bab 3, Bab 4 — form susunan formula & status dokumen bahan baku dipindah dari Formula Builder ke Tab Bab 2, plus preview PDF Bab 2 di tab baru | ✅ **Selesai** |
| **Polishing UI/UX & Data Formatting (Latest)** | Truncation kolom Sediaan/Netto di Dashboard, nama perusahaan lengkap di DIP Public Hub, format tanggal DD-MM-YYYY & email ganda di Qual-Quan, update label SAPJ di Edit Produk | ✅ **Selesai** |

---

## ✨ Fitur Utama

### 1. Database & Manajemen Bahan Baku (Fase 1 & 2a)
* **Master Data Bahan Baku:** Penyimpanan terpusat untuk INCI Name, nama dagang, fungsi, nomor CAS, supplier, dan batasan regulatori.
* **Dokumentasi per Perusahaan:** Spesifikasi, MSDS, dan PDF spesifikasi asli supplier kini tersimpan per perusahaan (PT Erfi / PT Heka) lewat tabel `raw_material_company_docs`, sehingga dokumen legal tidak pernah tertukar antar-perusahaan.
* **Manajemen Batch & Dokumen:** Mengunggah dan mengaitkan file CoA, Sertifikat Halal, dan MSDS ke setiap batch atau bahan baku secara langsung ke Supabase Storage.
* **Spesifikasi & Pemeriksaan QC per Batch:** Input parameter spesifikasi bahan, catatan pemeriksaan fisik/scan QC (PDF), dan parameter uji laboratorium aktual pada setiap batch — dipakai langsung di Bab II versi ZIP.
* **Tab Cek Kelengkapan Dokumen:** Halaman Bahan Baku memiliki tab khusus berisi matriks status kelengkapan dokumen per perusahaan (spesifikasi, spec sheet, MSDS, CoA, Halal) dengan badge ✓/✗.
* **Formula Builder:** Perancangan formulasi produk dengan kalkulasi otomatis persentase bahan (pembulatan presisi via `Decimal`) dan pemeriksaan batasan regulasi — pembuatan formulasi tetap lewat Formula Builder, sedangkan penyuntingan formula & mutu bahannya dikelola di **Tab Bab 2** halaman Edit Produk.
* **Edit Produk Multi-Tab:** Halaman Edit Produk disusun menjadi 5 tab (**Informasi Dasar, Bab 1, Bab 2, Bab 3, Bab 4**). Tab **Bab 2 — Formula & Mutu Bahan** memuat form susunan formula komposisi (tambah/hapus baris dengan total persentase otomatis) sekaligus status dokumen pendukung tiap bahan baku (PDF Spesifikasi, CoA, Laporan Pemeriksaan, Sertifikat Halal, MSDS) dan lampiran SOP CPKB perusahaan.

### 2. Generator Dokumen DIP Bab I–IV
Keempat bab DIP di-generate lewat pendekatan yang sama: halaman cover/checklist di-render dari template Jinja2 lalu dikonversi ke PDF (`xhtml2pdf`), kemudian di-*merge* dengan lampiran-lampiran terkait (diunduh dari Supabase Storage) memakai `pypdf` jadi satu berkas PDF utuh siap unduh. Kop surat, SOP CPKB, dan lampiran yang di-merge mengikuti **perusahaan** dari produk (PT Erfi / PT Heka).
* **Bab I — Kelengkapan Administrasi:** NIB, Sertifikat CPKB, Surat Tidak Pidana (statis per PT), Hak & Lisensi Merk (per brand), No. Notifikasi BPOM (per produk).

### 7. Spesifikasi Produk Jadi (PT Erfi)
*   **Form Input Spesifikasi QC:** Antarmuka input spesifikasi untuk produk jadi (Pemerian, Pengemasan Primer & Sekunder, Uji Mikrobiologi, Uji Cemaran Logam).
*   **Auto-fill Data Produk:** Pengisian otomatis parameter penting (Netto, No NA, Tanggal Acc Sampel) dari data Informasi Dasar Produk untuk efisiensi QC.
*   **Generate PDF QC:** Pembuatan dokumen spesifikasi QC resmi produk jadi yang mengikuti format PT Erfi, tersimpan di tabel `product_finished_specs`.

* **Bab II — Data Mutu & Keamanan Bahan:** Menarik seluruh bahan baku unik pada formula produk beserta batch terbarunya, digabung dengan checklist SOP CPKB perusahaan dan lampiran CoA/Halal/MSDS per bahan. Tersedia tombol **Preview Bab 2** (PDF inline di tab baru) di halaman Edit Produk serta **2 versi unduhan**: PDF gabungan & **versi Folder/ZIP** (1 folder per bahan baku berisi Spesifikasi, CoA, Halal, MSDS terpisah).
* **Bab III — Data Mutu Produk Jadi:** Breakdown kualitatif-kuantitatif formula produk otomatis dari data Formula Builder & komposisi bahan baku.
* **Bab IV — Data Keamanan Produk:** Merangkum laporan keamanan produk, CV safety assessor, monitoring efek samping, data klaim, dan desain kemasan.
* **Checklist Kelengkapan DIP di Dashboard:** Matriks kelengkapan Bab I–IV per produk (legalitas, formula, mutu produk jadi, keamanan) lengkap dengan progress DIP (%) dan status legalitas NA, supaya produk yang belum lengkap langsung terlihat. Tombol aksi per produk dipusatkan lewat **Edit Produk** (membuka kelima tab halaman edit), tanpa tombol duplikat khusus Bab 2 di dashboard.

### 3. FSP (Form Pengajuan Sample Produk)
### 7. Spesifikasi Produk Jadi (PT Erfi)
* **Form Spesifikasi:** Input QC produk jadi dengan 5 section default (Pemerian, Pengemasan Primer/Sekunder, Uji Mikrobiologi, Uji Cemaran Logam).
### 7. Spesifikasi Produk Jadi (PT Erfi)
*   **Formulir Spesifikasi QC Produk Jadi:** Input data spesifikasi QC produk jadi (Pemerian, Pengemasan Primer/Sekunder, Uji Mikrobiologi, Uji Cemaran Logam) dengan 5 *section* template standar yang siap pakai.
*   **Auto-fill Data Produk:** Otomatis mengisi field `No NA`, `Netto`, dan `Tanggal Acc Sampel` dari Informasi Dasar Produk untuk mengurangi kesalahan input manual.
*   **Generate PDF Spesifikasi Resmi:** Membuat dokumen PDF spesifikasi produk jadi yang meniru format dokumen QC resmi PT Erfi, terintegrasi ke Bab III DIP.
* **Auto-fill Data:** Data No NA, Netto, dan Tanggal Acc Sampel otomatis terisi dari Informasi Dasar Produk saat form pertama kali dibuka.
* **Generate PDF:** PDF spesifikasi produk jadi dengan format QC resmi PT Erfi, tersimpan di tabel `product_finished_specs` dan terintegrasi sebagai lampiran Bab III DIP.

* Form digital pengajuan sample baru dengan kode otomatis berformat `FSP/DD-MM-YYYY/X.Y` (pakai zona waktu WIB, `zoneinfo`) serta **nomor revisi otomatis** per produk (`v1`, `v2`, dst.).
* CRUD lengkap (create, edit, delete, list) plus halaman preview yang bisa langsung dicetak/disimpan ke PDF via `window.print()`.

### 4. Keamanan & Manajemen Pengguna
* **Dual-Option Login:** Fleksibilitas login bagi staf menggunakan **Username** atau **Email resmi**.
* **Keamanan Akses Tingkat Tinggi:**
  * Penggunaan **HTTP-Only Cookies** dengan proteksi `SameSite=Lax` untuk mencegah serangan XSS dan *Session Hijacking*.
  * Pendaftaran mandiri (*Self-Registration*) publik **dimatikan** untuk mencegah akses tak dikenal.
  * **Session Expire Warning:** sesi yang tidak valid/expired otomatis diarahkan kembali ke halaman login dengan peringatan jelas.
* **Admin Control Panel (`/admin/users`):**
  * Pembuatan akun staf baru oleh Admin secara instan, dengan **validasi keunikan username** (case-insensitive) agar login via username tidak ambigu.
  * Pengelolaan hak akses dengan **Role-Based Access Control (RBAC)** (`admin` vs `staff`).

### 5. Manajemen Brand & Ekspor
* Tambah brand baru serta update dokumen **Hak & Lisensi Merk** per brand, dipakai otomatis sebagai lampiran Bab I.
* Export laporan Qualitative-Quantitative Formula ke Excel (generate di server via `openpyxl`, styling profesional, 3 sheet: "Formula Nama Dagang", "Formula INCI Murni", "Text Design") dan cetak ke PDF lewat `window.print()`.

### 6. Activity Log & Monitoring
* **Activity Log:** Seluruh aksi (tambah, edit, hapus) tercatat rapi di tabel `activity_logs` Supabase dan dicetak berformat ke terminal server (timestamp WIB).
* **Web Uptime Monitor:** Endpoint `/health` (GET & HEAD) untuk cek kesehatan aplikasi oleh monitor eksternal.

> ⚠️ **Catatan pengembangan:** Satu bug minor masih terbuka — fallback domain email saat login via username yang belum terdaftar masih hardcoded `@erfi.com` (belum menyesuaikan PT Heka). Bug daftar user di `/admin/users` yang sebelumnya hanya menampilkan satu akun sudah diperbaiki dan berjalan normal di produksi; validasi keunikan username saat pembuatan akun juga sudah ditambahkan.

---

## 🛠️ Tech Stack

* **Backend:** Python 3.10+, FastAPI, Uvicorn, `slowapi` (rate limiting)
* **Database & Storage:** Supabase (PostgreSQL, Supabase Storage)
* **Frontend:** Jinja2 Templates, HTML5, CSS3, Tailwind CSS, JavaScript (Fetch API)
* **Document Generation:** `xhtml2pdf` (render HTML ke PDF), `pypdf` (merge/gabung PDF), `openpyxl` (export Excel styling profesional)
* **HTTP Client:** `httpx` (async, untuk fetch lampiran dari Supabase Storage)

---

## 🚀 Panduan Pengoperasian Lokal

### 1. Prasyarat
* Python 3.10 atau versi yang lebih baru
* Akun Supabase (untuk URL Database, Anon Key, dan Service Role Key)

### 2. Kloning Repository & Instalasi

```bash
# Kloning repository ini
git clone https://github.com/coretail/dip-automation-system.git
cd dip-automation-system

# Buat virtual environment
python -m venv venv

# Aktifkan virtual environment
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependensi
pip install -r requirements.txt
```

### 3. Konfigurasi Environment Variables (.env)

```
SUPABASE_URL=https://your-supabase-project-id.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key
```

### 4. Jalankan Aplikasi

```bash
uvicorn app.main:app --reload
```

---

## 📁 Struktur Proyek

```
dip-automation-system/
├── app/
│   ├── main.py              # Entrypoint FastAPI: seluruh routing, logika bisnis, & generator dokumen
│   ├── config.py             # Konfigurasi environment/settings aplikasi
│   ├── database.py          # Inisialisasi klien Supabase
│   ├── static/               # Asset statis (logo perusahaan, dll.)
│   └── templates/            # Jinja2 HTML Templates (dashboard, admin, form, checklist Bab I–IV, dll.)
├── requirements.txt          # Daftar dependensi Python
└── README.md                 # Dokumentasi utama
```

### Tabel Utama Supabase
`profiles` (user & role), `products`, `product_finished_specs`, `brands`, `producers`, `raw_materials`, `raw_material_components`, `raw_material_batches`, `raw_material_company_docs` (dokumen per perusahaan), `company_sop_documents`, `product_formula_lines`, `sample_submissions`, `activity_logs`, serta tabel lampiran dokumen (`nib_documents`, `sertifikat_cpkb_documents`, `surat_tidak_pidana_documents`, `cpkb_raw_material`).

---

## 📄 Lisensi & Hak Cipta
© 2026 Coretail DIP Automation System. Hak cipta dilindungi undang-undang.