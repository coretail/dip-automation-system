# Aplikasi Penyusun Dokumen Informasi Produk (DIP) Kosmetik

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![Framework](https://img.shields.io/badge/framework-FastAPI-green)
![Database](https://img.shields.io/badge/database-Supabase-emerald)
![Status](https://img.shields.io/badge/status-Bab_I_to_IV_Selesai-brightgreen)

Sistem otomasi berbasis web untuk menyusun, mengelola, dan menggenerasi **Dokumen Informasi Produk (DIP) Kosmetik** sesuai dengan regulasi standar BPOM dan pedoman ASEAN Cosmetic Directive (ACD).

🌐 **Live Demo:** [https://dip-automation-system.onrender.com/](https://dip-automation-system.onrender.com/)
📄 **Panduan Sistem:** [panduan_dip_automation_system.md](panduan_dip_automation_system.md)

---

## 📌 Status Pengembangan Sistem (Update: 28 September 2026)

| Modul / Fase | Fitur & Cakupan | Status |
| :--- | :--- | :---: |
| **Manajemen Dokumen Perusahaan** | Halaman admin khusus (`/admin/company-documents`) untuk mengelola 8 jenis dokumen statis per-perusahaan (NIB, Sertifikat CPKB, Surat Tidak Pidana, Protap No. Batch, Protap Pemeriksaan Produk Jadi, CV Safety Assessor, Monitoring Efek Samping, **SOP CPKB Pemeriksaan Bahan Baku**) yang dipakai lintas Bab I, III, dan IV saat generate PDF DIP. Upload file via UI (bucket `legal-documents` & `raw-material-docs`), upsert otomatis ke 5 tabel terkait (`nib_documents`, `sertifikat_cpkb_documents`, `surat_tidak_pidana_documents`, `company_sop_documents`, **`cpkb_raw_material`**), tercatat di `activity_logs`. Sebelumnya beberapa hanya bisa diubah lewat Supabase Dashboard langsung, dan SOP CPKB hanya bisa diakses dari halaman bahan baku. | ✅ **Selesai** |
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
| **Spesifikasi & Pemeriksaan QC per Batch** | Input parameter spesifikasi bahan + catatan pemeriksaan fisik/scan QC (PDF) & parameter uji laboratorium aktual per batch. Pada **PDF gabungan Bab II** dipakai dengan aturan berbeda: Spek hanya dari PDF, Catatan Pemeriksaan dari PDF atau data batch. Detail di [panduan §4.6](panduan_dip_automation_system.md#46-tahap-6--generasi--ekspor-dokumen-dip-pdf-gabungan-vs-folder-zip) | ✅ **Selesai** |
| **Modul Produksi (PO & Batch Produksi)** | Menu **Produksi** (`/purchase-orders`): buat Purchase Order, buat batch produk jadi, dan input item PO per batch (WIP, netto, qty kg, qty belum SOP, status BPOM, catatan/revisi produksi, temporary reject). Item bisa diedit & dihapus; nomor urut item otomatis. Tabel `purchase_orders`, `purchase_order_items`, `product_batches`. | ✅ **Selesai** |
| **Modul Notes Tim** | Menu **Notes** (`/notes`): catatan kerja tim dengan `@mention` pengguna serta token referensi produk (`#`), bahan baku (`/`), dan merk (`!`). Badge notifikasi di navbar, tandai selesai / buka lagi, dan hapus note milik sendiri. Tabel `team_notes`, `team_note_mentions`. | ✅ **Selesai** |
| **Generator Monitoring Efek Samping (NIES)** | Laporan cosmetovigilance per semester (`YYYY-H1`/`H2`) per produk, digenerate dari tab Bab 4 dan **ditambahkan (append)** ke PDF sebelumnya, bukan menimpa. Data kasus: nama, jenis kelamin, usia, jenis efek, manifestasi, tanggal. Penyimpanan di bucket `raw-material-docs`. Dilindungi `asyncio.Lock` per produk agar tidak ada generate paralel yang saling menimpa. | ✅ **Selesai** |
| **Sampah & Restore Produk** | Hapus produk tidak langsung hilang: ditandai soft delete (`products.is_deleted` + `deleted_at`). Menu **Sampah** (`/admin/trash`, khusus Admin) berisi produk terhapus + tombol restore. | ✅ **Selesai** |
| **Varian Komposisi Bahan Baku** | Bahan baku tipe Komposit bisa punya beberapa varian komposisi (`raw_material_composition_variants`) dengan satu varian default. Baris formula menyimpan `variant_id`, dipakai untuk INCI breakdown report & Qual-Quan. | ✅ **Selesai** |
| **Laporan INCI Breakdown** | `/products/{id}/inci-breakdown/report` — rekap total INCI/CAS dari seluruh bahan baku dalam formula (link langsung dari dashboard). | ✅ **Selesai** |
| **Status Presence 3 Tingkat** | `/admin/users` kini punya status **Online** (heartbeat ≤ 90 dtk), **Idle** (tidak ada aktivitas ≤ 5 menit), dan **Offline**, lengkap dengan badge + filter dan counter masing-masing. Ditambah konsep **akun terproteksi** (`profiles.is_protected`) yang tidak bisa diubah/dihapus admin lain. | ✅ **Selesai** |
| **Cek Kelengkapan Dokumen Bahan Baku** | Tab "Cek Kelengkapan Dokumen" di halaman Bahan Baku — matriks status dokumen per perusahaan (badge ✓/✗) | ✅ **Selesai** |
| **Monitor Online/Offline User** | Status kehadiran real-time di `/admin/users`: heartbeat 25 dtk, badge Online (hijau) / Offline + last seen, filter Semua/Online/Offline, auto-refresh 15 dtk. Kolom `profiles.last_seen_at` & `is_online` (SQL: `supabase_user_presence.sql`). | ✅ **Selesai** |
| **Keamanan & User System** | Dual Auth (Username/Email), Admin Control Panel (`/admin/users`), Dimatikannya Self-Register, RBAC (`admin`/`staff`), HTTP-Only Cookies JWT, Session Expire Warning, validasi keunikan username | ✅ **Selesai** |
| **Generator Bab I DIP** | Kelengkapan Administrasi (NIB, Sertifikat CPKB, Hak & Lisensi Merk, Surat Tidak Pidana, No. Notifikasi BPOM) — cover checklist + merge lampiran jadi satu PDF | ✅ **Selesai** |
| **Generator Bab II DIP** | Data Mutu & Keamanan Bahan Kosmetika. **PDF gabungan** disusun berurutan: Checklist → SOP CPKB → maksimal **1 halaman per bahan baku** (Spek PDF + Catatan Pemeriksaan dikomposisi dalam satu halaman) → **section seluruh COA** (setelah semua bahan baku, masing-masing dengan header nama bahan) → 2 daftar dokumen yang belum terlampir. **PDF gabungan saat ini tidak menyertakan Halal & MSDS** (keduanya hanya ada di versi ZIP). Preview dari Tab Bab 2 memakai generator yang sama. | ✅ **Selesai** |
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
* **Spesifikasi & Pemeriksaan QC per Batch:** Input parameter spesifikasi bahan, catatan pemeriksaan fisik/scan QC (PDF), dan parameter uji laboratorium aktual pada setiap batch. **Perbedaannya perlu diperhatikan:** pada **PDF gabungan Bab II** Spek bahan baku **hanya diambil dari PDF** (`spec_sheet_file_url`) dan tidak pernah digenerate dari `spec_parameters`, sedangkan **Catatan Pemeriksaan** memakai PDF bila ada, dan bila tidak ada digenerate dari data batch. Pada **versi ZIP** keduanya masih memakai PDF-dulu-fallback-teks.
* **Varian Komposisi:** Bahan baku tipe Komposit dapat memiliki beberapa varian komposisi, satu ditandai sebagai default; baris formula dapat menunjuk varian tertentu sehingga INCI breakdown & Qual-Quan mengikuti varian yang dipilih.
* **Status Batch:** Tombol **"Dipakai"** / **"Dimusnahkan"** pada log kedatangan batch untuk menandai CONDOH, status, dan alasan.
* **Tab Cek Kelengkapan Dokumen:** Halaman Bahan Baku memiliki tab khusus berisi matriks status kelengkapan dokumen per perusahaan (spesifikasi, spec sheet, MSDS, CoA, Halal) dengan badge ✓/✗.
* **Formula Builder:** Perancangan formulasi produk dengan kalkulasi otomatis persentase bahan (pembulatan presisi via `Decimal`) dan pemeriksaan batasan regulasi — pembuatan formulasi tetap lewat Formula Builder, sedangkan penyuntingan formula & mutu bahannya dikelola di **Tab Bab 2** halaman Edit Produk.
* **Edit Produk Multi-Tab:** Halaman Edit Produk disusun menjadi 5 tab (**Informasi Dasar, Bab 1, Bab 2, Bab 3, Bab 4**). Tab **Bab 2 — Formula & Mutu Bahan** memuat form susunan formula komposisi (tambah/hapus baris dengan total persentase otomatis) sekaligus status dokumen pendukung tiap bahan baku (PDF Spesifikasi, CoA, Laporan Pemeriksaan, Sertifikat Halal, MSDS) dan lampiran SOP CPKB perusahaan.

### 2. Generator Dokumen DIP Bab I–IV
Bab I, III, dan IV di-generate dengan satu pendekatan: halaman cover/checklist di-render dari template Jinja2 lalu dikonversi ke PDF (`xhtml2pdf`), kemudian di-*merge* dengan lampiran terkait (diunduh dari Supabase Storage) memakai `pypdf` menjadi satu berkas PDF utuh. **Bab II berbeda:** karena harus muat banyak dokumen per bahan baku, halaman bahan bakunya disusun lewat *komposisi layout* (lihat `app/bab2_pdf.py`) — bukan sekadar menempel halaman. Kop surat, SOP CPKB, dan lampiran mengikuti **perusahaan** dari produk (PT Erfi / PT Heka).
* **Bab I — Kelengkapan Administrasi:** NIB, Sertifikat CPKB, Surat Tidak Pidana (statis per PT), Hak & Lisensi Merk (per brand), No. Notifikasi BPOM (per produk).
* **Bab II — Data Mutu & Keamanan Bahan:** Menarik seluruh bahan baku unik pada formula produk beserta batch terbarunya per perusahaan. Urutan section pada **PDF gabungan**:
  1. **Checklist Kelengkapan Data** (halaman pembuka).
  2. **Prosedur Tetap Pemeriksaan Bahan Baku (SOP CPKB)** perusahaan.
  3. **Satu halaman per bahan baku** berisi nama bahan baku, Spek, dan Catatan Pemeriksaan. Jika Spek dan Catatan sama-sama tersedia, keduanya **tetap berada di satu halaman yang sama** (PDF sumber diskalakan proporsional, tanpa dipotong). Jika hanya salah satu yang tersedia, hanya itu yang ditampilkan — tanpa placeholder kosong.
  4. **Section COA** — seluruh COA dikumpulkan di sini, **setelah semua bahan baku selesai**, masing-masing didahului oleh header nama bahan bakunya sehingga jelas COA tersebut milik bahan baku mana.
  5. **Daftar bahan baku tanpa Spek & Catatan Pemeriksaan.**
  6. **Daftar bahan baku dengan COA belum terlampir.**

  Bahan baku yang tidak memiliki Spek **dan** Catatan Pemeriksaan **tidak** mendapat halaman kosong; namanya masuk daftar nomor 5. Section daftar kosong tidak pernah dicetak.

  Tersedia tombol **Preview Bab 2** (PDF inline di tab baru) di halaman Edit Produk. Preview memakai **generator yang sama persis** dengan tombol download, hanya berbeda header (`inline` vs `attachment`).

  **Perbedaan PDF Gabungan vs Folder/ZIP:**

  | | PDF Gabungan | Folder/ZIP |
  |---|---|---|
  | Spek | **Hanya** dari PDF (`spec_sheet_file_url`). Parameter spesifikasi yang diketik manual **tidak dipakai** | PDF asli, jika tidak ada digenerate dari parameter manual |
  | Catatan Pemeriksaan | PDF laporan pemeriksaan, jika tidak ada digenerate dari data batch | PDF asli, jika tidak ada digenerate dari hasil uji batch |
  | CoA | Satu section tersendiri setelah semua bahan baku | File terpisah per folder bahan baku |
  | Sertifikat Halal & MSDS | **Tidak dilampirkan** | Dilampirkan sebagai file terpisah |
  | Laporan dokumen kurang | Dua daftar ringkasan di bagian akhir PDF | File `PERHATIAN.txt` per folder bahan baku |

* **Bab III — Data Mutu Produk Jadi:** Breakdown kualitatif-kuantitatif formula produk otomatis dari data Formula Builder & komposisi bahan baku.
* **Bab IV — Data Keamanan Produk:** Merangkum laporan keamanan produk, CV safety assessor, monitoring efek samping, data klaim, desain kemasan, dan rancangan teks kemasan.
* **Checklist Kelengkapan DIP di Dashboard:** Matriks kelengkapan Bab I–IV per produk (legalitas, formula, mutu produk jadi, keamanan) lengkap dengan progress DIP (%) dan status legalitas NA, supaya produk yang belum lengkap langsung terlihat. Tombol aksi per produk dipusatkan lewat **Edit Produk** (membuka kelima tab halaman edit), tanpa tombol duplikat khusus Bab 2 di dashboard.

### 3. FSP (Form Pengajuan Sample Produk)
* Form digital pengajuan sample baru dengan kode otomatis berformat `FSP/DD-MM-YYYY/X.Y` (pakai zona waktu WIB, `zoneinfo`) serta **nomor revisi otomatis** per produk (`v1`, `v2`, dst.).
* CRUD lengkap (create, edit, delete, list) plus halaman preview yang bisa langsung dicetak/disimpan ke PDF via `window.print()`.

### 4. Spesifikasi Produk Jadi (PT Erfi)
* **Form Input Spesifikasi QC:** Antarmuka input spesifikasi untuk produk jadi dengan 5 *section* template standar yang siap pakai (Pemerian, Pengemasan Primer & Sekunder, Uji Mikrobiologi, Uji Cemaran Logam).
* **Auto-fill Data Produk:** Pengisian otomatis parameter penting (Netto, No NA, Tanggal Acc Sampel) dari data Informasi Dasar Produk untuk mengurangi kesalahan input manual.
* **Generate PDF QC:** Pembuatan dokumen spesifikasi QC resmi produk jadi yang meniru format dokumen QC resmi PT Erfi, tersimpan di tabel `product_finished_specs` dan terintegrasi sebagai lampiran Bab III DIP. Tersedia preview & download.

### 5. Keamanan & Manajemen Pengguna
* **Dual-Option Login:** Fleksibilitas login bagi staf menggunakan **Username** atau **Email resmi**. Catatan teknis: input "username" dicocokkan ke kolom `profiles.full_name` (bukan kolom terpisah), dan bila tidak ditemukan masih ada fallback domain kantor yang hardcoded `@erfi.com` — sehingga akun PT Heka yang tidak terdaftar tidak akan bisa login lewat username.
* **Keamanan Akses Tingkat Tinggi:**
  * Penggunaan **HTTP-Only Cookies** dengan proteksi `SameSite=Lax` untuk mencegah serangan XSS dan *Session Hijacking*.
  * Pendaftaran mandiri (*Self-Registration*) publik **dimatikan** untuk mencegah akses tak dikenal.
  * **Session Expire Warning:** sesi yang tidak valid/expired otomatis diarahkan kembali ke halaman login dengan peringatan jelas.
* **Admin Control Panel (`/admin/users`):**
  * Pembuatan akun staf baru oleh Admin secara instan, dengan **validasi keunikan username** (case-insensitive) agar login via username tidak ambigu.
  * Pengelolaan hak akses dengan **Role-Based Access Control (RBAC)** (`admin` vs `staff`).
  * **Status Kehadiran 3 tingkat:** **Online** (heartbeat ≤ 90 detik), **Idle** (tidak ada aktivitas ≤ 5 menit, tab terbuka tapi tidak dipakai), dan **Offline**, lengkap dengan badge, filter, dan counter. Auto-refresh tiap 15 detik.
  * **Akun Terproteksi:** akun bertanda `is_protected` tidak dapat diubah role, di-reset password, atau dihapus oleh admin lain.

### 6. Manajemen Brand, Produksi & Ekspor
* Tambah brand baru serta update dokumen **Hak & Lisensi Merk** per brand (per perusahaan), dipakai otomatis sebagai lampiran Bab I.
* **Modul Produksi (PO & Batch Produksi)** di menu **Produksi** (`/purchase-orders`): membuat Purchase Order, membuat batch produk jadi, serta mencatat item PO per batch — mulai dari WIP, netto, qty kg, qty belum SOP, qty PO kg, status BPOM, sampai catatan produksi, revisi produksi, dan temporary reject. Setiap item dapat diedit atau dihapus, dan aktivitasnya tercatat di `activity_logs`.
* **Modul Notes Tim** di menu **Notes** (`/notes`): catatan kerja bersama dengan `@mention` rekan tim serta token referensi cepat ke produk (`#`), bahan baku (`/`), dan merk (`!`). Badge merah pada navbar menandai mention yang belum dibaca.
* Export laporan Qualitative-Quantitative Formula ke Excel (generate di server via `openpyxl`, styling profesional, 3 sheet: "Formula Nama Dagang", "Formula INCI Murni", "Text Design") dan cetak ke PDF lewat `window.print()`.

### 7. Activity Log & Monitoring
* **Activity Log:** Seluruh aksi (tambah, edit, hapus, generate) tercatat rapi di tabel `activity_logs` Supabase dan dicetak berformat ke terminal server (timestamp WIB).
* **Web Uptime Monitor:** Endpoint `/health` (GET & HEAD) untuk cek kesehatan aplikasi oleh monitor eksternal.

> ⚠️ **Catatan pengembangan:** Satu bug minor masih terbuka — fallback domain email saat login via username yang belum terdaftar masih hardcoded `@erfi.com` (belum menyesuaikan PT Heka). Bug daftar user di `/admin/users` yang sebelumnya hanya menampilkan satu akun sudah diperbaiki dan berjalan normal di produksi; validasi keunikan username saat pembuatan akun juga sudah ditambahkan.

---

## 🛠️ Tech Stack

* **Backend:** Python 3.10+, FastAPI, Uvicorn, `slowapi` (rate limiting)
* **Database & Storage:** Supabase (PostgreSQL, Supabase Storage)
* **Frontend:** Jinja2 Templates, HTML5, CSS3, Tailwind CSS, JavaScript (Fetch API)
* **Document Generation:** `xhtml2pdf` (render HTML ke PDF), `pypdf` (merge/gabung PDF **dan komposisi layout halaman Bab II**), `openpyxl` (export Excel styling profesional)
* **HTTP Client:** `httpx` (async, untuk fetch lampiran dari Supabase Storage)
* **Integrasi AI (opsional):** Google Gemini API untuk membangkitkan kalimat sapaan di halaman login. Nonaktif bila `GEMINI_API_KEY` tidak diisi.

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

# Opsional — hanya untuk fitur sapaan AI di halaman login.
# Dikosongkan = fitur dimatikan, aplikasi tetap berjalan normal.
GEMINI_API_KEY=your-google-gemini-api-key
```

> Catatan: `SUPABASE_KEY` (anon/public) dipakai untuk interaksi harian, sedangkan `SUPABASE_SERVICE_ROLE_KEY` dipakai untuk operasi yang butuh hak admin — misalnya login dan pencarian username. Jangan pernah menaruh service role key di sisi browser.

### 4. Jalankan Aplikasi

```bash
uvicorn app.main:app --reload
```

---

## 📁 Struktur Proyek

```
dip-automation-system/
├── app/
│   ├── main.py                 # Entrypoint FastAPI: routing inti, auth, finished-spec, dashboard, pemanggil register_*
│   ├── config.py               # Konfigurasi environment/settings aplikasi (pydantic-settings)
│   ├── database.py             # Inisialisasi klien Supabase
│   ├── excel_generator.py      # Pembuatan workbook .xlsx Qual-Quan (openpyxl)
│   ├── bab2_pdf.py             # Helper komposisi layout PDF Bab II (pypdf) & daftar dokumen kurang
│   ├── efek_samping.py         # Generator laporan monitoring efek samping (NIES) per semester
│   ├── raw_materials_routes.py # Routing halaman & CRUD bahan baku, batch, varian komposisi
│   ├── po_routes.py            # Routing modul Produksi: PO, batch produk, item PO
│   ├── notes_routes.py         # Routing modul Notes tim & @mention
│   ├── dip_documents.py        # Routing generator DIP Bab I–IV, ZIP Bab II, & preview (butuh login)
│   ├── dip_public.py           # Routing portal publik /dip/{slug} untuk verifikator BPOM (tanpa login)
│   ├── static/                 # Asset statis (logo perusahaan, gambar tanda tangan, dll.)
│   └── templates/              # Jinja2 HTML Templates (dashboard, admin, form, checklist Bab I–IV, dll.)
├── requirements.txt            # Daftar dependensi Python
├── README.md                   # Dokumentasi utama
└── panduan_dip_automation_system.md  # Panduan operasional & teknis lengkap
```

> Catatan arsitektur: `main.py` menangani routing inti (auth, produk, dashboard, route finished-spec/Spesifikasi Produk Jadi), helper bersama (mis. kop perusahaan, format tanggal, penyelesaian varian komposisi), dan menjadi pemanggil semua `register_*_routes`. Fitur yang sudah cukup besar dipisah menjadi modul router terpisah dengan fungsi `register_*_routes(app, ...)`, agar `main.py` tidak terus membesar tanpa batas. Semua dependensi antar modul di-*inject* lewat parameter fungsi tersebut, sehingga tidak ada modul yang perlu meng-import `main.py` (circular import). Batas keamanan sengaja terlihat di struktur berkas: `dip_documents.py` berisi generator DIP yang **butuh login**, sedangkan `dip_public.py` berisi portal `/dip/{slug}` yang **tanpa login** dan dipakai verifikator BPOM lewat link permanen. Modul publik menerima fungsi generator dari `main.py` melalui parameter `bab_generators` dan `download_bab2_zip` — `register_dip_document_routes` mengembalikan fungsi generator tersebut supaya `dip_public.py` tetap tidak bergantung pada `main.py`.

### Tabel Utama Supabase
* **Master & Produk:** `profiles` (user, role, `is_protected`, presence), `products`, `brands`, `producers`, `product_finished_specs`, `product_formula_lines`, `product_batches`.
* **Bahan Baku:** `raw_materials`, `raw_material_components`, `raw_material_composition_variants` (varian komposisi), `raw_material_batches`, `raw_material_company_docs` (dokumen per perusahaan).
* **Produksi:** `purchase_orders`, `purchase_order_items`.
* **Kolaborasi:** `team_notes`, `team_note_mentions`.
* **Form Pengajuan:** `sample_submissions`.
* **Audit:** `activity_logs`, `public_link_audits`.
* **Dokumen legal/statis per perusahaan:** `nib_documents`, `sertifikat_cpkb_documents`, `surat_tidak_pidana_documents`, `company_sop_documents`, `cpkb_raw_material`, `brand_legal_documents`.

---

## 📄 Lisensi & Hak Cipta
© 2026 Coretail DIP Automation System. Hak cipta dilindungi undang-undang.

