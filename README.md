# Aplikasi Penyusun Dokumen Informasi Produk (DIP) Kosmetik

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![Framework](https://img.shields.io/badge/framework-FastAPI-green)
![Database](https://img.shields.io/badge/database-Supabase-emerald)
![Status](https://img.shields.io/badge/status-Bab_I_to_IV_Selesai-brightgreen)

Sistem otomasi berbasis web untuk menyusun, mengelola, dan menggenerasi **Dokumen Informasi Produk (DIP) Kosmetik** sesuai dengan regulasi standar BPOM dan pedoman ASEAN Cosmetic Directive (ACD).

🌐 **Live Demo:** [https://dip-automation-system.onrender.com/](https://dip-automation-system.onrender.com/)

---

## 📌 Status Pengembangan Sistem (Update: 6 Agustus 2026)

| Modul / Fase | Fitur & Cakupan | Status |
| :--- | :--- | :---: |
| **Fase 1: Core System** | Master Data Bahan Baku, Formula Builder, Qualitative-Quantitative (Qual-Quan) Report, Export Excel (SheetJS) & Print-to-PDF | ✅ **Selesai** |
| **Fase 2a: Dokumentasi Bahan** | Manajemen Batch Bahan Baku (CoA, Sertifikat Halal), MSDS, Integrasi Supabase Storage | ✅ **Selesai** |
| **Keamanan & User System** | Dual Auth (Username/Email), Admin Control Panel (`/admin/users`), Dimatikannya Self-Register, RBAC (`admin`/`staff`), HTTP-Only Cookies JWT | ✅ **Selesai** |
| **Generator Bab I DIP** | Kelengkapan Administrasi (NIB, Sertifikat CPKB, Lisensi & Hak Merk, Surat Tidak Pidana, No. Notifikasi BPOM) — cover checklist + merge lampiran jadi satu PDF | ✅ **Selesai** |
| **Generator Bab II DIP** | Data Mutu & Keamanan Bahan Kosmetika — spesifikasi per bahan baku (batch terbaru), checklist SOP CPKB, merge lampiran CoA/Halal/MSDS | ✅ **Selesai** |
| **Generator Bab III DIP** | Data Mutu Produk Jadi — breakdown formula kualitatif-kuantitatif otomatis dari data Formula Builder | ✅ **Selesai** |
| **Generator Bab IV DIP** | Data Keamanan Produk (Safety Assessment) — laporan keamanan, CV safety assessor, monitoring efek samping, data klaim, desain kemasan | ✅ **Selesai** |
| **FSP (Form Pengajuan Sample Produk)** | CRUD pengajuan sample, auto-generate kode sample (`FSP/DD-MM-YYYY/X.Y`), preview & cetak (print-to-PDF) | ✅ **Selesai** |
| **Manajemen Brand** | Tambah brand, update dokumen lisensi merk & hak merk per brand | ✅ **Selesai** |

---

## ✨ Fitur Utama

### 1. Database & Manajemen Bahan Baku (Fase 1 & 2a)
* **Master Data Bahan Baku:** Penyimpanan terpusat untuk INCI Name, nama dagang, fungsi, nomor CAS, supplier, dan batasan regulatori.
* **Manajemen Batch & Dokumen:** Mengunggah dan mengaitkan file CoA, Sertifikat Halal, dan MSDS ke setiap batch atau bahan baku secara langsung ke Supabase Storage.
* **Formula Builder:** Perancangan formulasi produk dengan kalkulasi otomatis persentase bahan (pembulatan presisi via `Decimal`) dan pemeriksaan batasan regulasi.

### 2. Generator Dokumen DIP Bab I–IV
Keempat bab DIP di-generate lewat pendekatan yang sama: halaman cover/checklist di-render dari template Jinja2 lalu dikonversi ke PDF (`xhtml2pdf`), kemudian di-*merge* dengan lampiran-lampiran terkait (diunduh dari Supabase Storage) memakai `pypdf` jadi satu berkas PDF utuh siap unduh.
* **Bab I — Kelengkapan Administrasi:** NIB, Sertifikat CPKB, Surat Tidak Pidana (statis per PT), Lisensi Merk & Hak Merk (per brand), No. Notifikasi BPOM (per produk).
* **Bab II — Data Mutu & Keamanan Bahan:** Menarik seluruh bahan baku unik pada formula produk beserta batch terbarunya, digabung dengan checklist SOP CPKB perusahaan dan lampiran CoA/Halal/MSDS per bahan.
* **Bab III — Data Mutu Produk Jadi:** Breakdown kualitatif-kuantitatif formula produk otomatis dari data Formula Builder & komposisi bahan baku.
* **Bab IV — Data Keamanan Produk:** Merangkum laporan keamanan produk, CV safety assessor, dokumen monitoring efek samping, data klaim, serta desain kemasan primer/sekunder.

### 3. FSP — Form Pengajuan Sample Produk
* Pengajuan sample baru dengan kode otomatis berformat `FSP/DD-MM-YYYY/X.Y` (pakai zona waktu WIB, `zoneinfo`).
* CRUD lengkap (create, edit, delete, list) plus halaman preview yang bisa langsung dicetak/disimpan ke PDF via `window.print()`.

### 4. Keamanan & Manajemen Pengguna
* **Dual-Option Login:** Fleksibilitas login bagi staf menggunakan **Username** atau **Email resmi**.
* **Keamanan Akses Tingkat Tinggi:**
  * Penggunaan **HTTP-Only Cookies** dengan proteksi `SameSite=Lax` untuk mencegah serangan XSS dan *Session Hijacking*.
  * Pendaftaran mandiri (*Self-Registration*) publik **dimatikan** untuk mencegah akses tak dikenal.
* **Admin Control Panel (`/admin/users`):**
  * Pembuatan akun staf baru oleh Admin secara instan.
  * Pengelolaan hak akses dengan **Role-Based Access Control (RBAC)** (`admin` vs `staff`).

### 5. Manajemen Brand & Ekspor
* Tambah brand baru serta update dokumen lisensi merk & hak merk per brand, dipakai otomatis sebagai lampiran Bab I.
* Export laporan *Qualitative-Quantitative Formula* ke Excel (via SheetJS/`xlsx-js-style` di sisi klien) dan cetak ke PDF lewat `window.print()`.

> ⚠️ **Catatan pengembangan:** Ada bug produksi yang masih terbuka — daftar user di `/admin/users` hanya menampilkan satu akun, diduga karena mismatch RLS/service role key di query tabel `profiles`. Masih ada juga 2 bug minor (fallback domain email yang salah, dan belum ada validasi keunikan username saat membuat user baru).

---

## 🛠️ Tech Stack

* **Backend:** Python 3.10+, FastAPI, Uvicorn
* **Database & Storage:** Supabase (PostgreSQL, Supabase Storage)
* **Frontend:** Jinja2 Templates, HTML5, CSS3, Tailwind CSS, JavaScript (Fetch API), SheetJS (`xlsx-js-style`) untuk export Excel
* **Document Generation:** `xhtml2pdf` (render HTML ke PDF) + `pypdf` (merge/gabung PDF lampiran)
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
JWT_SECRET_KEY=your-custom-jwt-secret
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

---

## 📄 Lisensi & Hak Cipta
© 2026 Coretail DIP Automation System. Hak cipta dilindungi undang-undang.