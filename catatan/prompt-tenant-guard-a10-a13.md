Tutup celah isolasi tenant (audit 2026-11-05: A-10, A-11, A-12, A-13) dengan pola yang SAMA dengan PR 46-48. Kerjakan sebagai 3 PR terpisah, berurutan; selesaikan dan laporkan satu PR sebelum mulai berikutnya. Jangan mengerjakan temuan audit lain (C-14, B-series, R2, pypdf, CSRF, dll.).

## Aturan (dari AGENTS.md)
- `git pull`, lalu branch baru dari `main` untuk TIAP PR. Jangan push/commit ke `main`. Jangan merge sendiri.
- Jangan membaca/mencetak `.env*`, `LOGIN.md`, `backup-rls/`. Tidak ada akses produksi. Tanpa migrasi SQL dan tanpa perubahan skema (kolom yang tidak ada = keputusan untuk saya, bukan untuk dibuat).
- Tes lokal di clone bersih / env dummy CI (SUPABASE_URL=https://ci.invalid.supabase.co, SUPABASE_KEY=ci-dummy-anon-key, SUPABASE_SERVICE_ROLE_KEY=ci-dummy-service-role-key, STORAGE_BACKEND=supabase; DIP_APP_ENV tidak diset). E2E staging hanya lewat `scripts/run_staging_8017.py`, satu suite per waktu (jangan paralel).
- Jangan menulis secret/kredensial di kode, test, atau laporan.

## Helper dan kontraknya (`app/security.py::assert_same_tenant(current_user, row, new_company=None)`)
- admin selalu lolos; user tanpa perusahaan lolos; baris tanpa `perusahaan`/`company` lolos (fail-open untuk data legacy, SENGAJA, jangan diubah di PR ini)
- nama dinormalisasi ("PT Erfi" == "erfi"); `new_company` yang DIBERIKAN tapi kosong ditolak
- Baris tenant dibaca dari kunci `perusahaan` (products, raw_materials) atau `company` (sample_submissions)

## Pola yang wajib diikuti (lihat `app/po_routes.py`: `po_item_update`/`po_item_delete`, dan `app/raw_materials_routes.py`: `add_material_batch`)
1. Baca baris induk (produk) SEBELUM validasi form, upload, dan tulis apa pun.
2. Guard dulu, baru tulis. Tidak boleh ada tulis/upload/storage yang terjadi sebelum guard.
3. FAIL-CLOSED: jika pembacaan baris induk melempar exception -> tolak (jangan jalankan tulis). Baris yang memang TIDAK ditemukan (tanpa exception) -> perilaku lama dipertahankan (404/redirect lama). Pesan galat: "Gagal memverifikasi akses ... Silakan coba lagi.".
4. Guard gagal -> 403 (route HTML dapat memakai pola redirect+pesan yang sudah dipakai modul itu) dan `log_activity(..., outcome="rejected")` bila modul itu sudah memakai log_activity.
5. Jangan ubah perilaku admin dan user satu-tenant.

## Kerangka test: `tests/test_sec02_po_rm_guard.py`
Pakai `FakeQuery`/`FakeSupabase`/`FakeApp` di sana (mendukung `fail_tables` dan `fail_calls` untuk simulasi kegagalan DB). Buat file test BARU per PR (jangan membengkak-kan file lama), salin harness secukupnya. Tiap test baru, minimal:
- user tenant A -> baris tenant B: 403/ditolak DAN nol tulis/upload/delete tercatat di fake
- user tenant A -> baris tenant A: lolos seperti sebelumnya
- admin -> baris tenant mana pun: lolos
- baris tanpa perusahaan: lolos (kunci perilaku fail-open legacy)
- pembacaan baris induk gagal (exception): ditolak, nol tulis
- baris induk tidak ditemukan: perilaku lama (pin test)
Verifikasi bahwa test fail-closed GAGAL pada kode lama (git stash perubahan app, jalankan test) dan sebutkan buktinya; pastikan test gagal karena alasan yang benar (bukan karena validasi lain menolak lebih dulu; isi semua parameter Form opsional dan perhatikan pesan galatnya).
Tiap test baru: tambah `!/tests/<nama>.py` di `.gitignore`, satu baris `python tests/<nama>.py` di `.github/workflows/ci.yml`, dan blok `main()` yang benar-benar memanggil semua test (CI tidak memakai pytest).

## PR 1 — A-11 `app/efek_samping.py` dan A-12 `app/product_attachments_routes.py`
Route (cek ulang nomor baris di `main`; audit menulis efek_samping 178-456, lampiran 55-58 dan 116-140):
- `POST /products/{product_id}/monitoring-efek-samping/generate` (~178) dan `/delete` (~380): guard terhadap produk (`products.perusahaan`) sebelum generate/upload/hapus.
- Lampiran: `GET /products/{product_id}/lampiran` (~116), `POST /products/{product_id}/lampiran` (~133, storage-dulu), `.../{attachment_id}/edit` (~210), `.../{attachment_id}/delete` (~225).
  - Guard produk di SEMUA route, termasuk GET (jangan bocorkan daftar lampiran tenant lain) dan sebelum upload (jangan ada objek storage yatim akibat penolakan).
  - Untuk edit/delete: pastikan `attachment_id` benar-benar milik `product_id` yang di-guard (cek `attachments.product_id == product_id`); kalau tidak, tenant guard bisa dikelabui dengan product_id milik sendiri + attachment_id milik tenant lain. Tambahkan test untuk kasus ini.
  - Bucket `product-attachments` privat; jangan mengubah semantik storage/object_store.

## PR 2 — A-10 `app/products_routes.py` `POST /products/{product_id}/finished-spec` (~766-824)
- Baca produk dengan pola `.limit(1)` (bukan `.single()`) bila perlu; guard sebelum update/upload spesifikasi barang jadi. Ada guard di rute produk lain (baris ~252, 356, 1215, 1506); samakan gaya. Cek juga route produk lain yang menulis ke produk tapi belum ber-guard (grep semua `@app.post` di `products_routes.py` dan dokumentasikan hasilnya; perbaiki yang jelas ber-tenant, laporkan yang ambigu).

## PR 3 — A-13 `app/sample_routes.py`
- `POST /sample-submissions/create` (~38-181): guard `new_company=` (company yang diajukan) vs tenant user, serta produk yang dirujuk bila ada.
- `POST /sample-submissions/delete/{submission_id}` (~345-364): saat ini fail-open bila pembacaan baris gagal; jadikan fail-closed (baris tidak ditemukan tetap perilaku lama).
- `GET /sample-submissions/edit/{submission_id}` (~185) belum ber-guard tenant: tambahkan, dan pastikan `HTTPException(404)` di dalam `try` tidak ditelan `except Exception` jadi 500 hanya bila perubahannya kecil dan tidak mengubah hal lain (itu temuan C-14; kalau ragu, biarkan dan catat).
- `app/brands_routes.py` (`/brands/add`, `/brands/{id}/update-documents`): periksa di `migration/*.sql` dan kode apakah tabel `brands`/`producers`/`brand_legal_documents` punya kolom perusahaan. JANGAN menambah kolom. Jika tidak ada kolom tenant, JANGAN memperbaiki; tulis sebagai keputusan terbuka (katalog brand bersama atau per-tenant) beserta bukti `file:baris`.

## Di luar lingkup (jangan dikerjakan)
- Akun tanpa profil jadi `staff`+`perusahaan=None` (C-01/A-17) dan perilaku fail-open untuk baris tanpa `perusahaan`: butuh keputusan produk. Sebutkan di laporan sebagai yang masih terbuka.
- PO lintas tenant, katalog raw materials bersama (D1b).

## Validasi tiap PR
- `python scripts/check_undefined_names.py`, `python scripts/check_static_rules.py`, `python -m compileall app`, import terisolasi `app.main`
- semua `python tests/test_*.py` di `ci.yml` (clone bersih, env dummy CI)
- E2E staging, satu per satu: `smoke`, `activity`, `notes`, `audit` (tanpa `--quick`, tenant kedua D2 bila tersedia). Catat bila ada yang tidak bisa dijalankan. Jangan memperbaiki test E2E yang gagal tanpa membedakan kegagalan test vs aplikasi.
- Tambah route baru ke tenant matrix di `tests/e2e_audit_staging.py` (grup D/D2) HANYA bila polanya jelas dan tetap staging-only; bersihkan akun/data sementara.

## Dokumentasi
Tambah entri sesi di `catatan/catatan_log_perbaikan_audit_2026-11-05.md` (format template di file itu): ubah status A-10/A-11/A-12/A-13 per PR, sertakan perintah validasi + exit code. Jangan mengubah laporan audit asli. Perbarui `AGENTS.md`/`panduan` bila daftar test CI berubah.

## Keluaran per PR
Commit (pesan bahasa Indonesia), push branch, buka PR ke `main`. Laporkan: route yang diguard (`file:baris`), diff ringkas, hasil test + bukti test gagal di kode lama, hasil validasi, hal yang tidak bisa diverifikasi, dan keputusan yang dibiarkan terbuka.
