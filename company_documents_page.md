# Prompt: Halaman "Dokumen Perusahaan" (dokumen statis per-PT untuk Bab I/III/IV)

## Konteks

Digrep langsung ke `main.py`: ada 7 jenis dokumen yang levelnya **per-perusahaan**
(bukan per-produk) dan dipakai berulang lintas Bab I, III, dan IV pas generate
PDF — tapi **gak ada satupun endpoint upload buat mereka**. Satu-satunya cara
ganti filenya sekarang adalah lewat Supabase dashboard langsung (gak ada log
aktivitas, gak lewat aplikasi).

File-file yang per-produk (`cara_pembuatan_file_url`, `spek_produk_jadi_file_url`,
dll) **sudah** ada form upload-nya di `edit_product.html` — itu jangan disentuh,
di luar scope ini.

## Daftar 7 dokumen yang perlu dikasih UI upload

| Kode internal | Label tampilan | Tabel | Kolom | Dipakai di |
|---|---|---|---|---|
| `nib` | NIB | `nib_documents` | `file_url` | Bab I |
| `sertifikat_cpkb` | Sertifikat CPKB | `sertifikat_cpkb_documents` | `file_url` | Bab I |
| `surat_tidak_pidana` | Surat Tidak Pidana | `surat_tidak_pidana_documents` | `file_url` | Bab I |
| `protap_no_batch` | Protap No. Batch | `company_sop_documents` | `protap_no_batch_url` | Bab III (poin 3) |
| `protap_pemeriksaan_fg` | Protap Pemeriksaan Produk Jadi | `company_sop_documents` | `protap_pemeriksaan_fg_url` | Bab III (poin 8) |
| `cv_safety_assessor` | CV Safety Assessor | `company_sop_documents` | `cv_safety_assessor_url` | Bab IV (poin 2) |
| `monitoring_efek_samping` | Monitoring Efek Samping (level company) | `company_sop_documents` | `monitoring_efek_samping_file_url` | Bab IV (poin 3, fallback) |

**Penting soal tabel:** 3 baris pertama masing-masing tabel terpisah dengan
pola 1-baris-per-perusahaan (persis kayak `cpkb_raw_material` yang sudah ada
di fitur SOP CPKB). 4 baris terakhir itu **kolom yang berbeda dalam SATU
tabel yang sama** (`company_sop_documents`, juga 1 baris per perusahaan) —
jadi update-nya harus `UPDATE ... SET <kolom_spesifik> = ...`, bukan bikin
baris baru tiap kali salah satu dari 4 dokumen itu di-upload.

## Yang perlu dibuat

### 1. Route baru, admin-only

`GET /admin/company-documents` — proteksi pakai pola yang sama kayak route
admin lain (`if current_user["role"] != "admin": ...` redirect/403, cek
`app/main.py` sekitar baris 4817 buat contoh persis).

`POST /admin/company-documents/update` — terima `doc_type` (salah satu dari 7
kode di tabel atas), `perusahaan` (`PT Erfi` / `PT Heka`), dan file upload.
Server-side map `doc_type` ke tabel+kolom yang benar sesuai tabel di atas,
lalu upsert (create row kalau belum ada utk company itu, update kolom
spesifik kalau baris company-nya udah ada). Ikuti pola upload+upsert yang
sudah dipakai di `/raw-materials/cpkb/update` (baris ~2086), termasuk
`log_activity()` abis berhasil update.

**Storage bucket:** pakai `legal-documents` (bucket yang sama yang udah
dipakai buat Hak & Lisensi Merk di `brands.html`), BUKAN `raw-material-docs`
— soalnya ini dokumen legal/regulasi, bukan dokumen bahan baku. Path
sarannya: `company-docs/{doc_type}_{company_slug}.pdf` dengan `upsert: true`.

### 2. Template baru: `admin_company_documents.html`

Standalone kayak `admin_users.html` (gak perlu extend `base.html`, ikutin
pola halaman admin yang udah ada). Isi: tabel/grid 7 baris (dokumen) × 2
kolom (PT Erfi / PT Heka). Tiap sel nampilin:
- Status: ada file (kasih link "Lihat" ke file_url) atau belum ada ("Belum
  diupload")
- Tombol "Upload" / "Ganti File" yang buka modal kecil (form
  `enctype="multipart/form-data"`, kirim `doc_type` + `perusahaan` yang
  sesuai lewat hidden input) — modal-nya bisa 1 aja yang dipakai bareng
  buat ke-7×2 sel, tinggal isi hidden input-nya pakai JS pas modal dibuka
  (sama kayak pola `openCpkbModal()` di `raw_materials.html`).

### 3. Link ke halaman ini

Tambahin link di `dashboard.html`, deket tombol "Manage Users" yang udah ada
(baris ~35, di dalam blok `{% if user.role == 'admin' %}`). Style-nya samain
aja (badge kecil, warna beda biar kebedain dari tombol Manage Users — misal
sky/blue).

## Catatan

Jangan bikin 7 endpoint terpisah buat tiap jenis dokumen — cukup 1 endpoint
generik yang terima `doc_type` sebagai parameter, biar gampang di-maintain
kalau nanti nambah jenis dokumen lagi.

Setelah selesai, jelasin singkat: route baru apa aja, dan konfirmasi upsert
buat `company_sop_documents` beneran update kolom spesifik (bukan overwrite
seluruh baris / bikin duplikat baris per perusahaan).
