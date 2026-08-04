# Aplikasi Penyusun Dokumen Informasi Produk (DIP) Kosmetik

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![Framework](https://img.shields.io/badge/framework-FastAPI-green)
![Database](https://img.shields.io/badge/database-Supabase-emerald)
![Status](https://img.shields.io/badge/status-Fase_2b_Selesai_|_Fase_3_In_Progress-brightgreen)

Sistem otomasi berbasis web untuk menyusun, mengelola, dan menggenerasi **Dokumen Informasi Produk (DIP) Kosmetik** sesuai dengan regulasi standar BPOM dan pedoman ASEAN Cosmetic Directive (ACD).

🌐 **Live Demo:** [https://dip-automation-system.onrender.com/](https://dip-automation-system.onrender.com/)

---

## 📌 Status Pengembangan Sistem (Update: 4 Agustus 2026)

| Modul / Fase | Fitur & Cakupan | Status |
| :--- | :--- | :---: |
| **Fase 1: Core System** | Master Data Bahan Baku, Formula Builder, Qualitative-Quantitative (Qual-Quan) Report, Text Design Kemasan, Export PDF/Excel | ✅ **Selesai** |
| **Fase 2a: Dokumentasi Bahan** | Manajemen Batch Bahan Baku (CoA, Sertifikat Halal), MSDS, Integrasi Supabase Storage (`raw-material-docs`) | ✅ **Selesai** |
| **Keamanan & User System** | Dual Auth (Username/Email), Admin Control Panel (`/admin/users`), Dimatikannya Self-Register, RBAC (`admin`/`staff`), HTTP-Only Cookies JWT, Anti-Cache Headers | ✅ **Selesai** |
| **Fase 2b: Generator Bab II** | Otomasi Penyusunan Dokumen Bab II DIP (Data Mutu & Keamanan Bahan Kosmetika) via engine `python-docx`, spesifikasi otomatis, penggabungan checklist CPKB & lampiran | ✅ **Selesai** |
| **Fase 3: Bab III DIP** | Generator Dokumen Bab III DIP (Data Mutu Produk Jadi) | 🔧 **In Progress** |
| **Fase 4: Bab IV DIP** | Generator Dokumen Bab IV DIP (Data Keamanan Produk / Safety Assessment) | ⬜ **Rencana** |

---

## ✨ Fitur Utama

### 1. Database & Manajemen Bahan Baku (Fase 1 & 2a)
* **Master Data Bahan Baku:** Penyimpanan terpusat untuk INCI Name, nama dagang, fungsi, nomor CAS, supplier, dan batasan regulatori.
* **Manajemen Batch & Dokumen:** Mengunggah dan mengaitkan file CoA, Sertifikat Halal, dan MSDS ke setiap batch atau bahan baku secara langsung ke Supabase Storage.
* **Formula Builder:** Perancangan formulasi produk dengan kalkulasi otomatis persentase bahan, pemeriksaan batasan regulasi, dan estimasi biaya.

### 2. Generator Dokumen Bab II DIP (Fase 2b)
* **Otomasi Dokumen Mutu Bahan:** Generasi berkas Bab II (Data Mutu & Keamanan Bahan Kosmetika) secara otomatis berformat `.docx`.
* **Penggabungan Terstruktur:** Penyusunan otomatis spesifikasi teknis, checklist kesesuaian SOP CPKB, dan integrasi lampiran CoA/MSDS per bahan dalam formulasi.

### 3. Keamanan & Manajemen Pengguna
* **Dual-Option Login:** Fleksibilitas login bagi staf menggunakan **Username** atau **Email resmi**.
* **Keamanan Akses Tingkat Tinggi:**
  * Penggunaan **HTTP-Only Cookies** dengan proteksi `SameSite=Lax` untuk mencegah serangan XSS dan *Session Hijacking*.
  * Pendaftaran mandiri (*Self-Registration*) publik **dimatikan** untuk mencegah akses tak dikenal.
* **Admin Control Panel (`/admin/users`):** 
  * Pembuatan akun staf baru oleh Admin secara instan (*Auto-Confirmed Email*).
  * Pengelolaan hak akses dengan **Role-Based Access Control (RBAC)** (`admin` vs `staff`).
* **Sistem Anti-Cache:** Penerapan *Anti-Cache Headers* backend untuk menjamin data dashboard dan status login selalu sinkron secara *real-time*.

### 4. Otomasi Laporan & Ekspor
* Export laporan *Qualitative-Quantitative Formula* ke format PDF dan Excel.
* Penyiapan draf *Text Design* klaim kemasan produk.

---

## 🛠️ Tech Stack

* **Backend:** Python 3.10+, FastAPI, Uvicorn
* **Database & Auth:** Supabase (PostgreSQL, Supabase Auth, Supabase Storage)
* **Frontend:** Jinja2 Templates, HTML5, CSS3, Tailwind CSS, JavaScript (Fetch API)
* **Document Generation & Export:** `python-docx`, `openpyxl`, `reportlab`

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

##  Konfigurasi Environment Variables (.env)
SUPABASE_URL=https://your-supabase-project-id.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key
JWT_SECRET_KEY=your-custom-jwt-secret

## Run App
uvicorn app.main:app --reload

## 📁 Struktur Proyek
dip-automation-system/
├── app/
│   ├── main.py              # Entrypoint aplikasi FastAPI & routing utama
│   ├── dependencies.py      # Autentikasi, validasi JWT cookie, & proteksi RBAC
│   ├── routers/             # Endpoint rute (auth, admin, ingredients, products, dip_docx, dll)
│   ├── services/            # Logika bisnis, engine python-docx, & integrasi Supabase Service
│   ├── static/              # Asset statis (CSS, JS, Gambar)
│   └── templates/           # Jinja2 HTML Templates (UI Dashboard, Admin, Form)
├── .env.example             # Template konfigurasi environment variable
├── .gitignore               # Berkas yang diabaikan oleh Git
├── README.md                # Dokumentasi utama
└── requirements.txt         # Daftar dependensi Python

## 📄 Lisensi & Hak Cipta
© 2026 Coretail DIP Automation System. Hak cipta dilindungi undang-undang.