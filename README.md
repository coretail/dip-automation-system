# Aplikasi Penyusun Dokumen Informasi Produk (DIP) Kosmetik

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![Framework](https://img.shields.io/badge/framework-FastAPI-green)
![Database](https://img.shields.io/badge/database-Supabase-emerald)
![Status](https://img.shields.io/badge/status-Bab_I_to_IV_Selesai-brightgreen)

Sistem otomasi berbasis web untuk menyusun, mengelola, dan menggenerasi **Dokumen Informasi Produk (DIP) Kosmetik** sesuai dengan regulasi standar BPOM dan pedoman ASEAN Cosmetic Directive (ACD).

🌐 **Live Demo:** [https://dip-automation-system.onrender.com/](https://dip-automation-system.onrender.com/)
📄 **Panduan Sistem:** [panduan_dip_automation_system.md](panduan_dip_automation_system.md)

---

## 📌 Status Pengembangan Sistem (Update: 5 Oktober 2026)

| Modul / Fase | Fitur & Cakupan | Status |
| :--- | :--- | :---: |
| **Tema Tampilan (Theme System)** | Empat tema — **Light**, **Terra**, **Rose**, **Dark** — berbasis CSS token (`app/static/theme.css`, ±1.100 baris). Dibiarkan lewat `data-theme` di `<html>`, disimpan di `localStorage: heka-theme`, dan skrip anti-flash inline di `<head>` menerapkannya sebelum stylesheet termuat. Warna native form control (`<select>`, `<option>`, scrollbar, checkbox, date picker) mengikuti tema — bagian yang paling sering terlewat pada sistem tema berbasis Tailwind. `beforeprint`/`afterprint` memaksa tema light saat print lalu memulihkannya. Keyboard support penuh di menu tema (`Esc`, `↑`/`↓`, `Home`/`End`), `prefers-reduced-motion` dihormati. | ✅ **Selesai** |
| **Sidebar Navigasi** | Shell navigasi terpusat di `app/templates/_sidebar.html` + `app/static/sidebar.js` + `sidebar.css`. 10 menu, submenu **Administration** yang bisa dilipat, mode **collapsed** (persist ke `localStorage: sidebarCollapsed`) dengan tooltip, dan **drawer off-canvas** di mobile (≤767px). Auto-collapsed pada layar 768–1023px. Menu admin (Sampah, Administration) hilang total untuk non-admin. Badge merah jumlah mention di menu Notes. | ✅ **Selesai** |
| **Analisis PO** (`/po-analytics`) | Halaman analitik terpisah dari modul Produksi. KPI Total PO/qty, komposisi per kuartal, grafik donat proporsi per perusahaan, **grafik kombinasi batang + garis jumlah PO & qty pcs per kuartal per perusahaan** (dua sumbu), Top 5 produk menurut PO/qty, dan Top 5 produk belum ada Laporan Uji SIG. Filter **tahun**, **kuartal**, **urutan**, dan **tab per perusahaan** (`Semua` / `PT Erfi` / `PT Heka`). Banner amber "PO belum punya item" yang menyebutkan jumlahnya dan daftar nomor PO-nya — pemisahan eksplisit antara *PO tanpa item* dan *PO tidak ada*. | ✅ **Selesai** |
| **Filter & Pencarian Produksi** | `/purchase-orders` punya filter **tahun** (termasuk "Semua Tahun"), **kuartal** (Q1–Q4, default = kuartal berjalan WIB, dinaikkan ke kuartal tertinggi yang benar-benar berisi data), dan **perusahaan** — termasuk opsi **"Tanpa item"** untuk PO yang belum punya item, karena `purchase_orders` tidak punya kolom perusahaan. Disimpan di cookie `po_filter`. Pencarian realtime No. PO + nama produk. Pengurutan tanggal null diletakkan terakhir. | ✅ **Selesai** |
| **PO Rework** | Kolom `purchase_orders.jenis_po` (`migration/002_add_jenis_po.sql`) untuk menandai PO perbaikan/rework. Di `/po-analytics`, PO Rework **tetap dihitung sebagai jumlah PO** tetapi **qty pcs-nya tidak ikut dijumlahkan** — sehingga KPI PO dan qty tidak sama-sama naik. Diberi tanda lewat `migration/tag_rework_po.py`. Banner di analisis memberi tahu bila kolom ini belum ada di database. | ✅ **Selesai** |
| **Toolkit Migrasi Data** | Folder `migration/` berisi 2 file SQL skema + **9 skrip migrasi data** + skrip rollback-nya, semuanya mengikuti pola yang sama: **read-only secara default**, hanya menulis dengan `--execute --yes`, `--dry-run` menulis laporan CSV/JSON tanpa menyentuh database, dan **manifest** berisi id baris yang tertulis untuk keperluan rollback. Lihat §Migrasi Data. | ✅ **Selesai** |
| **Manajemen Dokumen Perusahaan** | Halaman admin khusus (`/admin/company-documents`) untuk mengelola 8 jenis dokumen statis per-perusahaan (NIB, Sertifikat CPKB, Surat Tidak Pidana, Protap No. Batch, Protap Pemeriksaan Produk Jadi, CV Safety Assessor, Monitoring Efek Samping, **SOP CPKB Pemeriksaan Bahan Baku**) yang dipakai lintas Bab I, III, dan IV saat generate PDF DIP. Upload file via UI (bucket `legal-documents` & `raw-material-docs`), upsert otomatis ke 5 tabel terkait, tercatat di `activity_logs`. | ✅ **Selesai** |
| **Spesifikasi Produk Jadi (PT Erfi)** | Form input spesifikasi QC produk jadi dengan template default 5 section, auto-fill dari Informasi Dasar (`no_na_produk`, `netto`, `acc_sampel`), generate PDF meniru format dokumen QC resmi PT Erfi. Tabel `product_finished_specs`. Hanya untuk `PT Erfi`; produk PT Heka mendapat 303 ke halaman edit. | ✅ **Selesai** |
| **Field Peringatan & Penyimpanan** | Field `peringatan` & `penyimpanan` di form Tambah/Edit Produk, otomatis muncul di dokumen Bab IV (Text Design), Formula Kualitatif & Kuantitatif, dan Export Excel — **hanya bila diisi** (bukan NULL, kosong, atau `-`). | ✅ **Selesai** |
| **Export Excel via Backend (openpyxl)** | Export Qualitative-Quantitative Formula (3 sheet: "Formula Nama Dagang", "Formula INCI Murni", "Text Design") di-generate di server. Warna header mengikuti perusahaan (`#FFCC99` Erfi / `#DCE6F1` Heka). Baris total memakai formula `=SUM()` asli, bukan angka statis. Bahan aktif disorot kuning. Kolom INCI hanya boleh melebar, tidak pernah menyempit. | ✅ **Selesai** |
| **Quantity & Satuan pada Batch Bahan Baku** | Kolom `quantity` & `quantity_unit` (dropdown: kg/gram/liter/ml/pcs/roll/drum) di form Tambah & Edit Batch, ditampilkan di tabel Log Kedatangan Batch. | ✅ **Selesai** |
| **Badge Produk Pemakai Bahan Baku** | Di halaman Bahan Baku, tiap baris menampilkan badge `usage_count` (dihitung per produk unik), bisa diklik untuk lihat daftar produk via modal. | ✅ **Selesai** |
| **Rate Limiting & Countdown Timer Login** | Proteksi brute-force pada `POST /login` (maks 5 percobaan/menit per IP) memakai `slowapi`. Halaman login menampilkan alert + countdown timer visual. Respons rate-limit sengaja **redirect 303 ke `/login?error=too_many_attempts`**, bukan 429, agar detail limiter tidak bocor. | ✅ **Selesai** |
| **Redesign Halaman Bahan Baku** | Tab Manajemen ED dengan indikator Sisa Hari (badge warna). Tab Log Kedatangan Batch: dokumen & aksi digabung jadi menu kebab, kolom Kesimpulan jadi ikon, wrap teks kolom Produsen. | ✅ **Selesai** |
| **Checklist DIP Dashboard — Badge Deep-Link** | Badge status tiap Bab (I–IV) jadi link langsung ke tab edit produk terkait (`#tab-bab1` dst), tombol "Lengkapi" terpisah dihapus. | ✅ **Selesai** |
| **Quick-Add Merk (Combobox Search)** | Dropdown Merk pada form Tambah/Edit Produk diganti jadi search-combobox dengan opsi "Tambah merk baru" via modal tanpa keluar halaman. | ✅ **Selesai** |
| **Fase 1: Core System** | Master Data Bahan Baku, Formula Builder, Qualitative-Quantitative (Qual-Quan) Report, Export Excel & Print-to-PDF | ✅ **Selesai** |
| **Fase 2a: Dokumentasi Bahan** | Manajemen Batch Bahan Baku (CoA, Sertifikat Halal), MSDS, Integrasi Supabase Storage | ✅ **Selesai** |
| **Dokumentasi Multi-Perusahaan** | Spesifikasi, MSDS & PDF spesifikasi asli supplier disimpan per perusahaan, kop surat & SOP CPKB per perusahaan pada dokumen DIP. Bila satu perusahaan tidak punya baris dokumen, field-nya **dikosongkan** — bukan jatuh ke data perusahaan lain. | ✅ **Selesai** |
| **Spesifikasi & Pemeriksaan QC per Batch** | Input parameter spesifikasi bahan + catatan pemeriksaan fisik/scan QC & parameter uji laboratorium aktual per batch. Pada **PDF gabungan Bab II** dipakai dengan aturan berbeda: Spek hanya dari PDF, Catatan Pemeriksaan dari PDF atau data batch. | ✅ **Selesai** |
| **Modul Produksi (PO & Batch Produksi)** | Menu **Produksi**: buat Purchase Order (header **tidak bisa diedit/dihapus** lewat aplikasi), buat batch produk jadi, dan input item PO per batch. Item bisa diedit & dihapus; nomor urut item **tidak pernah diurutkan ulang** setelah penghapusan. Tabel `purchase_orders`, `purchase_order_items`, `product_batches`. | ✅ **Selesai** |
| **Modul Notes Tim** | Menu **Notes**: catatan kerja tim dengan `@mention` pengguna serta token referensi produk (`#`), bahan baku (`/`), dan merk (`!`) yang menyimpan UUID sehingga tetap valid meski nama berubah. Badge notifikasi di navbar (polling 30 detik), tandai selesai / buka lagi, hapus note milik sendiri (atau oleh admin). | ✅ **Selesai** |
| **Generator Monitoring Efek Samping (NIES)** | Laporan cosmetovigilance per semester per produk, di-generate dari tab Bab 4 dan **ditambahkan (append) ke PDF sebelumnya**, bukan menimpa. Dilindungi `asyncio.Lock` per produk. | ✅ **Selesai** |
| **Sampah & Restore Produk** | Hapus produk tidak langsung hilang: ditandai soft delete (`products.is_deleted` + `deleted_at`). Menu **Sampah** (`/admin/trash`, khusus Admin) berisi produk terhapus + tombol restore. | ✅ **Selesai** |
| **Varian Komposisi Bahan Baku** | Bahan baku tipe Komposit bisa punya beberapa varian komposisi dengan satu varian default. Baris formula menyimpan `variant_id`; varian yang sudah dipakai formula tidak bisa dihapus. | ✅ **Selesai** |
| **Laporan INCI Breakdown** | `/products/{id}/inci-breakdown/report` — rekap INCI/CAS dari seluruh bahan baku dalam formula. | ✅ **Selesai** |
| **Status Presence 3 Tingkat** | `/admin/users` punya status **Online** (heartbeat ≤ 90 dtk), **Idle** (tidak ada aktivitas ≤ 5 menit), dan **Offline**, lengkap dengan badge + filter dan counter. Ditambah konsep **akun terproteksi** (`profiles.is_protected`). | ✅ **Selesai** |
| **Cek Kelengkapan Dokumen Bahan Baku** | Tab "Cek Kelengkapan Dokumen" di halaman Bahan Baku — matriks status dokumen per perusahaan (badge ✓/✗) dengan preview PDF inline. | ✅ **Selesai** |
| **Keamanan & User System** | Dual Auth (Username/Email), Admin Control Panel, Self-Register dimatikan, RBAC (`admin`/`staff`), HTTP-Only Cookies, Session Expire Warning, validasi keunikan username case-insensitive. | ✅ **Selesai** |
| **Generator Bab I DIP** | Kelengkapan Administrasi — cover/checklist + merge lampiran jadi satu PDF. | ✅ **Selesai** |
| **Generator Bab II DIP** | Data Mutu & Keamanan Bahan Kosmetika. **PDF gabungan** disusun berurutan: Checklist → SOP CPKB → **maksimal 1 halaman per bahan baku** (Spek PDF + Catatan Pemeriksaan dikomposisi dalam satu halaman) → **section seluruh COA** (setelah semua bahan baku) → 2 daftar dokumen yang belum terlampir. **PDF gabungan tidak menyertakan Halal & MSDS.** | ✅ **Selesai** |
| **Generator Bab III DIP** | Data Mutu Produk Jadi — breakdown formula + lampiran. Lampiran poin 5 (SAPJ) & 6a (SPJ) **dipilih berbeda per perusahaan** agar urutan halaman tetap sesuai checklist. | ✅ **Selesai** |
| **Generator Bab IV DIP** | Data Keamanan Produk — cover + lampiran poin 1-4 + **halaman Text Design disisipkan sebelum desain kemasan** agar urutan halaman sesuai checklist. | ✅ **Selesai** |
| **Checklist Kelengkapan DIP (Dashboard)** | Matriks kelengkapan Bab I–IV per produk + progress DIP (%) + status legalitas NA. | ✅ **Selesai** |
| **FSP (Form Pengajuan Sample Produk)** | CRUD pengajuan sample, auto-generate kode `FSP/DD-MM-YYYY/X.Y`, nomor revisi otomatis, preview & cetak. | ✅ **Selesai** |
| **Manajemen Brand** | Tambah brand, upload dokumen Hak & Lisensi Merk per brand, plus quick-add via modal. | ✅ **Selesai** |
| **Activity Log & Uptime Monitor** | Riwayat aktivitas di tabel `activity_logs` + log terminal; endpoint `/health` (GET & HEAD). | ✅ **Selesai** |
| **Edit Produk Multi-Tab (Bab 1–4)** | Halaman Edit Produk 5 tab: Informasi Dasar, Bab 1, Bab 2, Bab 3, Bab 4. | ✅ **Selesai** |

---

## ✨ Fitur Utama

### 1. Database & Manajemen Bahan Baku
* **Master Data Bahan Baku:** Penyimpanan terpusat untuk INCI Name, nama dagang, fungsi, nomor CAS, supplier, dan batasan regulatori.
* **Dokumentasi per Perusahaan:** Spesifikasi, MSDS, dan PDF spesifikasi asli supplier tersimpan per perusahaan lewat `raw_material_company_docs`, sehingga dokumen legal tidak pernah tertukar antar-perusahaan.
* **Manajemen Batch & Dokumen:** Mengunggah CoA, Sertifikat Halal, MSDS, dan Laporan Pemeriksaan ke setiap batch.
* **Spesifikasi & Pemeriksaan QC per Batch:** Input parameter spesifikasi, catatan pemeriksaan fisik/scan QC (PDF), dan parameter uji laboratorium aktual. **Perbedaannya:** pada **PDF gabungan Bab II** Spek **hanya diambil dari PDF** (`spec_sheet_file_url`) dan tidak pernah digenerate dari `spec_parameters`, sedangkan **Catatan Pemeriksaan** memakai PDF bila ada, dan bila tidak ada digenerate dari data batch. Pada **versi ZIP** keduanya memakai PDF-dulu-fallback-teks.
* **Varian Komposisi:** Bahan baku tipe Komposit dapat memiliki beberapa varian komposisi, satu ditandai default; baris formula dapat menunjuk varian tertentu. Resolusi varian punya rantai fallback 5 tingkat (variant_id eksplisit → varian default → varian pertama → komponen legacy tanpa `variant_id` → kosong) sehingga data lama tidak pernah membuat breakdown hilang diam-diam.
* **Status Batch:** Tombol **"Dipakai"** / **"Dimusnahkan"** pada log kedatangan batch. Batch dengan `kesimpulan = "lab"` tidak pernah dijadikan batch referensi.
* **Tab Cek Kelengkapan Dokumen:** Matriks status kelengkapan dokumen per perusahaan dengan preview PDF inline.
* **Formula Builder:** Kalkulasi otomatis persentase bahan (pembulatan presisi via `Decimal`) dan pemeriksaan batasan regulasi.
* **Edit Produk Multi-Tab:** 5 tab (**Informasi Dasar, Bab 1, Bab 2, Bab 3, Bab 4**). Tab **Bab 2** memuat form susunan formula, status dokumen pendukung tiap bahan baku, dan lampiran SOP CPKB perusahaan.

### 2. Antarmuka, Tema & Navigasi
* **Shell terpusat:** Seluruh halaman aplikasi mewarisi `base.html`, yang menyediakan 4 block (`html_class`, `title`, `head_extra`, `content`) dan menyertakan `_sidebar.html`.
* **Sistem 4 tema** dengan arsitektur dua lapis: **lapisan token** (satu blok CSS per tema, semua nilai warna nyata) dan **lapisan pemetaan** (utility class Tailwind → token, ditulis sekali, tanpa literal warna, memakai `!important` agar mengalahkan Tailwind CDN). Rinciannya di [panduan §4.13](panduan_dip_automation_system.md#413-sistem-tema--tampilan-aplikasi).
* **Sidebar responsif:** mode collapsed + tooltip, drawer off-canvas di mobile, submenu Administration yang terlipat, dan badge mention pada Notes.
* **Dark mode tanpa flash:** skrip inline sinkron di `<head>` menerapkan tema sebelum stylesheet pertama termuat, sehingga tidak ada kedipan tema putih.
* **Aksesibilitas:** `aria-expanded`/`aria-controls`/`aria-current` pada navigasi, `role="menu"`/`menuitemradio` pada pemilih tema, focus ring eksplisit, penghormatan `prefers-reduced-motion`, dan tooltip yang juga terpicu oleh fokus keyboard.

### 3. Analitik Produksi (PO)
* **Modul Produksi** (`/purchase-orders`): membuat header PO (No. PO unik, Tanggal PO, Qty pcs), membuat batch produk jadi, dan mencatat item PO per batch.
* **Filter & pencarian:** tahun (termasuk "Semua Tahun"), kuartal (Q1–Q4, default kuartal berjalan), perusahaan (termasuk opsi "Tanpa item"), pencarian realtime No. PO + nama produk, dan pengurutan dengan tanggal null diletakkan terakhir. Filter disimpan di cookie `po_filter` supaya bertahan antar halaman.
* **Aturan validasi:** batch harus milik produk yang dipilih; nomor PO yang sudah ada ditolak dengan redirect ke PO yang ada; input angka/tanggal tidak valid ditolak dengan pesan jelas; bentrokan nomor urut item di-*retry* otomatis.
* **Analisis PO** (`/po-analytics`): seluruh angka dihitung dengan aturan yang eksplisit dan berbeda per tabel sumber — **KPI Total PO & qty** dari header `purchase_orders`; **atribusi produk/perusahaan** dari `purchase_order_items`; **metadata produk** dari `products`; dan **tidak ada** yang membaca `product_batches`. Atribut `qty_pcs` pada grafik per perusahaan selalu berasal dari header PO dan **perhitungannya unik per PO**, sehingga satu PO dengan dua produk tidak terhitung dua kali.
* **Transparansi data:** analisis membedakan secara eksplisit antara perusahaan dengan **0 PO** (memang tidak ada) dan perusahaan dengan **0 PO teratribusi** (PO-nya ada tapi belum punya item), serta menampilkan banner amber berisi jumlah dan nomor PO yang belum punya item. PO Rework dihitung sebagai PO tapi tidak menambah qty.

### 4. Generator Dokumen DIP Bab I–IV
Bab I, III, dan IV di-generate dengan satu pendekatan: halaman cover/checklist di-render dari template Jinja2 lalu dikonversi ke PDF (`xhtml2pdf`), kemudian di-*merge* dengan lampiran (diunduh dari Supabase Storage) memakai `pypdf` menjadi satu berkas PDF utuh. **Bab II berbeda:** halaman bahan bakunya disusun lewat *komposisi layout* (`app/bab2_pdf.py`) — judul section dan label digambar langsung via content stream pypdf, lalu PDF sumber diskalakan proporsional dan ditempel di dalam kotak yang tersedia.
* **Bab I — Kelengkapan Administrasi:** NIB, Sertifikat CPKB, Hak & Lisensi Merk (per brand **dan per perusahaan**), Surat Tidak Pidana, No. Notifikasi BPOM.
* **Bab II — Data Mutu & Keamanan Bahan:** menarik seluruh bahan baku unik pada formula beserta batch terbaru per perusahaan. Urutan section pada **PDF gabungan**: (1) Checklist, (2) SOP CPKB perusahaan, (3) satu halaman per bahan baku berisi Spek + Catatan Pemeriksaan — jika keduanya tersedia keduanya **tetap satu halaman**, dan PDF sumber multi-halaman ditata **berdampingan di dalam kotak yang sama** agar tidak ada data yang hilang maupun halaman tambahan, (4) section COA — seluruh COA dikumpulkan **setelah semua bahan baku selesai**, masing-masing dengan header nama bahannya, (5) daftar bahan baku tanpa Spek & Catatan Pemeriksaan, (6) daftar bahan baku dengan COA belum terlampir.
  Bahan baku yang tidak memiliki Spek **dan** tidak memiliki Catatan Pemeriksaan **tidak mendapat halaman kosong**; namanya masuk daftar nomor 5. Section daftar kosong tidak pernah dicetak.
  Tersedia tombol *Preview Bab 2* yang memakai **generator yang sama persis** dengan tombol download, hanya berbeda header (`inline` vs `attachment`).
* **Bab III — Data Mutu Produk Jadi:** breakdown kualitatif-kuantitatif formula; total persentase dihitung di Python (bukan di template) agar dijamin konsisten dengan penjumlahan baris tabel. Lampiran poin 5 & 6a dipilih berbeda per perusahaan agar urutan halaman tetap sesuai checklist.
* **Bab IV — Data Keamanan Produk:** cover + lampiran poin 1-4 + **halaman Text Design disisipkan sebelum desain kemasan** agar urutan halaman sesuai checklist.
* **Checklist Kelengkapan DIP di Dashboard:** matriks kelengkapan Bab I–IV per produk lengkap dengan progress DIP (%) dan status legalitas NA.

### 5. FSP (Form Pengajuan Sample Produk)
* Form digital dengan kode otomatis berformat `FSP/DD-MM-YYYY/X.Y` (zona waktu WIB) serta **nomor revisi otomatis** per produk. `brand_id = "new"` otomatis membuat producer + brand dan menyimpannya sebagai `draft_producer`/`draft_brand`. Pencarian pada daftar melewati `sample_code` **atau** `product_name`.

### 6. Spesifikasi Produk Jadi (PT Erfi)
* **Form Input Spesifikasi QC:** 5 *section* template standar (Pemerian, Pengemasan Primer & Sekunder, Uji Mikrobiologi, Uji Cemaran Logam), auto-fill dari Informasi Dasar Produk, generate PDF QC resmi yang meniru format PT Erfi, tersimpan di `product_finished_specs` dan terintegrasi sebagai lampiran Bab III DIP.

### 7. Keamanan & Manajemen Pengguna
* **Dual-Option Login:** masuk memakai **Username** atau **Email resmi**. Username dicocokkan ke `profiles.full_name`, dan bila tidak ditemukan ada fallback domain kantor `@erfi.com` — sehingga akun PT Heka yang tidak terdaftar di `profiles` tidak akan bisa login lewat username. Keunikan `full_name` dijaga case-insensitive saat pembuatan akun.
* **Cookie sesi:** `access_token` HTTP-Only, `SameSite=Lax`, umur cookie 24 jam; token JWT-nya valid 4 jam (dikelola Supabase Auth). Bila kedaluwarsa, handler 401 mengarahkan ke `/login?warning=session_expired`.
* **Pendaftaran mandiri dimatikan.** Akun hanya dibuat Admin. Halaman login, tombol logout, dan setiap link logout meminta konfirmasi.
* **Admin Control Panel** (`/admin/users`): tambah akun, reset password, ubah role, hapus akun, plus **Status Kehadiran 3 tingkat** (Online ≤ 90 dtk · Idle ≤ 5 menit · Offline) dengan badge, filter, counter, dan auto-refresh 15 detik. Akun bertanda `is_protected` tidak dapat diubah/dihapus admin lain.

### 8. Manajemen Brand, Produksi & Ekspor
* Tambah brand, update dokumen **Hak & Lisensi Merk** per brand per perusahaan, quick-add via modal.
* **Modul Produksi** (`/purchase-orders`), **Modul Analitik PO** (`/po-analytics`), dan **Modul Notes Tim** (`/notes`).
* Export laporan Qualitative-Quantitative Formula ke Excel (3 sheet, generate di server via `openpyxl`) dan cetak ke PDF lewat `window.print()`.

### 9. Activity Log & Monitoring
* **Activity Log:** Seluruh aksi penting tercatat di tabel `activity_logs` dan dicetak berformat ke terminal server (timestamp WIB) dengan badge aksi (`🟢 CREATED`, `🟡 UPDATED`, `🔴 DELETED`). Perubahan field teks logged sebagai pasangan nilai lama → baru; perubahan dokumen logged sebagai catatan *"File diganti"* karena upload menimpa di tempat sehingga URL tidak berubah.
* **Log portal publik:** Setiap pembukaan link publik `/dip/{slug}` mencatat IP, User-Agent, dan username ke `public_link_audits`, dengan fallback ke `activity_logs` bila tabel khusus belum ada, dan dicetak real-time ke terminal.
* **Web Uptime Monitor:** Endpoint `/health` (GET & HEAD).
* **Penyaringan log:** access log dari empat poller berfrekuensi tinggi (`/health`, heartbeat presence, unread-count mention, presence admin) disaring agar terminal tetap terbaca.

---

## 🛠️ Tech Stack

* **Backend:** Python 3.10+, FastAPI, Uvicorn, `slowapi` (rate limiting)
* **Database & Storage:** Supabase (PostgreSQL, Supabase Storage) — satu klien global memakai service role
* **Frontend:** Jinja2 Templates, HTML5, Tailwind CSS v4 (`@tailwindcss/browser`), JavaScript (vanilla, tanpa build step)
* **Document Generation:** `xhtml2pdf` (render HTML ke PDF), `pypdf` (merge PDF **dan komposisi layout halaman Bab II**), `openpyxl` (export Excel)
* **HTTP Client:** `httpx` (async, untuk fetch lampiran dari Supabase Storage)
* **Integrasi AI (opsional):** Google Gemini API untuk kalimat sapaan di halaman login. Nonaktif bila `GEMINI_API_KEY` tidak diisi.

### Versi dependensi (`requirements.txt`)

Semua dipin dengan versi exact:

| Paket | Versi | Paket | Versi |
|---|---|---|---|
| `fastapi` | 0.141.1 | `xhtml2pdf` | 0.2.20 |
| `starlette` | 1.6.0 | `pypdf` | 6.19.0 |
| `uvicorn` | 0.53.0 | `httpx` | 0.28.1 |
| `supabase` | 2.31.0 | `slowapi` | 0.1.10 |
| `pydantic-settings` | 2.15.0 | `python-slugify` | 9.0.0 |
| `jinja2` | 3.1.6 | `openpyxl` | 3.1.5 |
| `python-multipart` | 0.0.32 | `tzdata` | 2026.4 |

> ⚠️ **Dua paket yang diimpor tapi tidak tercantum di `requirements.txt`:**
>
> * **Pillow** (`PIL`) — dipakai untuk mengukur lebar logo dan me-*flatten* PNG RGBA ke latar putih (file PNG RGBA tidak bisa dirender `xhtml2pdf` tanpa itu). Kedua pemanggilannya dibungkus `try/except` dan jatuh ke lebar logo tetap, jadi fiturnya boleh tidak terpasang.
> * **python-dotenv** (`dotenv`) — dipanggil `load_dotenv()` di `main.py` **tanpa penjaga**, padahal `pydantic-settings` sudah membaca `.env` sendiri. Akibatnya lingkungan yang benar-benar belum memasangnya akan gagal saat start.
>
> Tambahkan keduanya bila ingin instalasi bersih.

### Aset pihak ketiga via CDN (dimuat di browser)

| Aset | Versi | Dipakai di |
|---|---|---|
| `@tailwindcss/browser` | `@4` | seluruh halaman aplikasi, Public Hub |
| Font Awesome `css/all.min.css` | 6.4.0 | seluruh halaman |
| Chart.js UMD | 4.4.3 | `/po-analytics` saja |

> ℹ️ Tidak ada atribut `integrity`/`crossorigin` pada skrip CDN, dan aplikasi memang tidak memasang header CSP — yang konsisten dengan keberadaan skrip inline (anti-flash tema, notifikasi ED, sapaan) dan Tailwind browser build yang mengevaluasi CSS saat runtime. Escaping dilakukan per-sink: nilai tak tepercaya masuk lewat `textContent`, dan hanya nilai yang lolos helper `escapeHtml` yang disisipkan sebagai HTML.

---

## 🚀 Panduan Pengoperasian Lokal

### 1. Prasyarat
* Python 3.10 atau versi yang lebih baru
* Akun Supabase (untuk URL Database dan Service Role Key)

### 2. Kloning Repository & Instalasi

```bash
git clone https://github.com/coretail/dip-automation-system.git
cd dip-automation-system

python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

> Disarankan juga memasang **Pillow** dan **python-dotenv** yang belum tercantum di `requirements.txt` (lihat catatan di atas).

### 3. Konfigurasi Environment Variables (.env)

```
SUPABASE_URL=https://your-supabase-project-id.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key

# Opsional — tidak dipakai kode aplikasi (seluruh akses database lewat service role).
SUPABASE_KEY=your-supabase-anon-key

# Opsional — hanya untuk fitur sapaan AI di halaman login.
GEMINI_API_KEY=your-google-gemini-api-key
```

> Catatan: `SUPABASE_KEY` (anon/public) bersifat opsional dan **tidak dipakai kode aplikasi**; seluruh akses database memakai `SUPABASE_SERVICE_ROLE_KEY` (melewati RLS), termasuk login dan pencarian username. Service role key punya hak penuh — **jangan pernah** ditaruh di sisi browser atau di-commit ke repository.

### 4. Jalankan Aplikasi

```bash
uvicorn app.main:app --reload
```

### 5. Skema Database Awal

Skema produksi tidak dikelola otomatis. Jalankan file SQL di folder `migration/` secara manual melalui Supabase SQL Editor, berurutan:

| File | Isi |
|---|---|
| `migration/001_create_purchase_orders.sql` | Membuat `purchase_orders` + `purchase_order_items`. ⚠️ **Tidak membuat `product_batches`** — tabel itu harus sudah ada, dan hanya direferensikan dengan FK `RESTRICT` |
| `migration/002_add_jenis_po.sql` | Menambah kolom `purchase_orders.jenis_po` untuk PO Rework |

---

## 📁 Struktur Proyek

```
dip-automation-system/
├── app/
│   ├── main.py                 # Entrypoint FastAPI: auth, produk, dashboard, admin, samples,
│   │                           #   brands, finished-spec, inci-breakdown, qual-quan, activity log,
│   │                           #   health, presence, ED notifications, COMPANY_INFO, filter Jinja
│   ├── config.py               # Settings pydantic (supabase_url/key/service_role, gemini_api_key)
│   ├── database.py             # Klien Supabase global (service role, melewati RLS)
│   ├── excel_generator.py      # Workbook .xlsx Qual-Quan 3 sheet (openpyxl)
│   ├── bab2_pdf.py             # Komposisi layout PDF Bab II via content stream pypdf
│   ├── efek_samping.py         # Generator laporan NIES per semester (append, locking per produk)
│   ├── dip_documents.py        # Generator Bab I–IV, ZIP Bab II, & preview (butuh login)
│   ├── dip_public.py           # Portal publik /dip/{slug} untuk verifikator BPOM (tanpa login)
│   ├── raw_materials_routes.py # CRUD bahan baku, batch, varian komposisi, usage badge
│   ├── po_routes.py            # Produksi: PO, batch produk, item PO, + halaman analitik PO
│   ├── notes_routes.py         # Notes tim, @mention, token referensi
│   ├── static/
│   │   ├── theme.css           # Sistem token 4 tema (light / terra / rose / dark)
│   │   ├── sidebar.css         # Layout app, drawer mobile, collapsed mode
│   │   ├── sidebar.js          # Sidebar: collapse, drawer, submenu, tooltip, user menu
│   │   ├── darkmode.js         # Penerapan tema, anti-flash, mode print, keyboard menu
│   │   ├── presence.js         # Heartbeat status online/idle (25 detik)
│   │   ├── po-analytics.js     # Chart.js: 5 grafik Analisis PO + palet per tema
│   │   ├── efek_samping.js     # Helper form NIES
│   │   └── images/             # logo_erfi, logo_heka, kop_erfi, kop_heka, apt, favicon
│   └── templates/              # 17 halaman extend base.html + template PDF/partial tersendiri
├── migration/                  # Toolkit migrasi data (LIHAT DI BAWAH — tidak di-commit)
├── tests/                      # Skrip verifikasi (tidak di-commit)
├── requirements.txt            # 14 dependensi, semua dipin exact
├── README.md                   # Dokumen ini
└── panduan_dip_automation_system.md  # Panduan operasional & teknis lengkap
```

> **Arsitektur.** `main.py` menangani routing inti dan menjadi pemanggil semua `register_*_routes`. Fitur yang cukup besar dipisah menjadi modul router terpisah dengan fungsi `register_*_routes(app, ...)`, sehingga `main.py` tidak terus membesar tanpa batas. Semua dependensi antar modul di-*inject* lewat parameter fungsi tersebut, sehingga tidak ada modul yang perlu meng-import `main.py` (circular import). Batas keamanan sengaja terlihat di struktur berkas: `dip_documents.py` berisi generator DIP yang **butuh login**, sedangkan `dip_public.py` berisi portal `/dip/{slug}` yang **tanpa login**.

> **Template.** 17 template mewarisi `base.html` lewat `{% extends %}` dengan 4 block yang tersedia: `html_class`, `title`, `head_extra`, dan `content`. Halaman preview FSP meng-override `html_class` dengan `force-light` supaya tema dipaksa light dan tombol switcher disembunyikan. Template yang berdiri sendiri (login, halaman error publik, Public Hub, dan seluruh template PDF) punya `<head>` sendiri. Struktur internal halaman masih memakai `{% macro %}` — belum ada pustaka komponen.

> **Filter Jinja global** yang terdaftar di `main.py`: `slugify`, `clean_pct`, dan `format_date_dd_mm_yyyy`. ⚠️ Catatan: `notes_routes.py` membuat `Jinja2Templates` sendiri sehingga template Notes **tidak** mewarisi filter kustom tersebut.

---

## 🗄️ Migrasi Data

Folder `migration/` berisi toolkit bermigrasi data historis (spreadsheet → Supabase). **Folder ini sengaja tidak di-commit ke git** (lihat `.gitignore`) karena berisi data operasional perusahaan; salin dan simpan di luar repository bila perlu dipertahankan.

### Konvensi yang dipatuhi seluruh skrip

1. **Read-only secara default.** Skrip hanya menulis ke database bila dijalankan dengan `--execute --yes` secara eksplisit. Tanpa flag itu, `--execute` selalu berhenti dengan pesan error.
2. **Dry-run lebih dulu.** `--dry-run` (default) menulis laporan CSV/JSON ke `migration/_report_rekap/` tanpa menyentuh database.
3. **Penjaga SHA-256.** Bila SHA-256 berkas sumber atau berkas alias berubah sejak dry-run terakhir, skrip **berhenti** sebelum menulis, kecuali diberi `--force-plan-changed`.
4. **Manifest.** Setiap baris yang berhasil ditulis dicatat lengkap dengan `id`-nya ke `manifest_*.json` **sebelum** proceeds ke baris berikutnya.
5. **Rollback berdasarkan manifest.** Skrip `rollback_*.py` membaca manifest dan menghapus hanya baris yang tercatat di dalamnya.

### Skema SQL

| File | Isi |
|---|---|
| `001_create_purchase_orders.sql` | `purchase_orders`, `product_batches`, `purchase_order_items` beserta FK & UNIQUE |
| `002_add_jenis_po.sql` | kolom `purchase_orders.jenis_po` untuk PO Rework |

### Skrip migrasi & rollback

| Skrip | Tujuan | Rollback |
|---|---|---|
| `migrate_po.py` | Impor PO & batch produksi dari spreadsheet | — |
| `migrate_po_rekap.py` | Impor **REKAP SOP** 2026 (Jan–Jul): produk, PO, batch, item, produk baru | `rollback_po_rekap.py` |
| `import_po_heka.py` | Impor **header PO PT Heka** (PO tanpa item) | `rollback_po_heka.py` |
| `import_po_heka_batch.py` | Impor **batch PT Heka** dari `CATATAN BATCH HEKA - 2026.xlsx`: mengisi item + batch pada 156 PO header-only | `rollback_po_heka_batch.py` |
| `import_missing_na.py` | Impor produk dari NA yang belum terdaftar | — |
| `update_qty_pcs.py` | Koreksi `qty_pcs` PO | `rollback_qty_pcs.py` |
| `tag_rework_po.py` | Tandai `jenis_po = 'Rework'` | — |
| `fix_po_number.py` | Normalisasi penomoran PO | — |
| `fill_perusahaan.py` | Lengkapi kolom `perusahaan` pada master produk | — |

### Berkas pendukung (override & alias)

| Berkas | Fungsi |
|---|---|
| `na_aliases.csv` | Pemetaan NA salah-ketik → NA master yang benar (7 alias), tiap baris disertai catatan tanggal & alasan persetujuan |
| `name_aliases.csv` | Alias nama produk |
| `overrides.csv` | Override nilai per PO/batch |
| `po_number_allow.csv`, `po_number_fix.csv` | Daftar izinkan & perbaikan nomor PO |
| `po_rework_tag.csv` | Daftar PO Rework |
| `qty_pcs_override.csv` | Override `qty_pcs` |
| `po_heka_item_na.csv`, `po_heka_rework.csv` | Pemetaan NA item & PO rework PT Heka |

### Prinsip pemrosesan yang konsisten

* **Deteksi kolom berbasis header**, bukan posisi tetap. Peta kolom dievaluasi terhadap baris header; bila tidak cocok, skrip **berhenti** alih-alih menebak.
* **Tidak ada tebakan.** Field tanpa sumber ditulis `NULL`. Nilai yang tak bisa dipastikan masuk ke laporan `REVIEW`/`HELD`, tidak pernah ditebak.
* **Normalisasi tanggal dari kode batch.** `tanggal_catatan_batch` dan `tanggal_produksi` diturunkan dari 6 digit awal `no_batch` (`YYMMDD`) bila tersedia — bukan dari kolom Tgl SOP di spreadsheet.
* **Deteksi footer berlapis.** Baris footer dikenali dari isi kolom A maupun kolom F, karena beberapa sheet menaruh label footer di kolom F.
* **Perbaikan-perbaikan otomatis hanya diterima bila ada bukti.** Contoh: kandidat nomor PO hasil normalisasi hanya dipakai bila kandidat itu benar-benar ada di `purchase_orders`.

---

## 📄 Lisensi & Hak Cipta
© 2026 Coretail DIP Automation System. Hak cipta dilindungi undang-undang.
