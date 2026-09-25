# Rencana Fitur: Halaman Input Batch Produksi (PO) untuk Tim QC

## Status

**Approved — siap masuk tahap implementasi. Belum ada perubahan code.** Dokumen ini lanjutan dari
`catatan_batch_plan.md` (migrasi data historis, sudah LOCKED & sudah dieksekusi
25 Sep 2026 — tabel `purchase_orders` & `purchase_order_items` sudah ada di
Supabase). Plan ini khusus untuk fitur baru: **halaman live-input** supaya tim
QC mencatat PO/batch produksi langsung ke sistem, menggantikan pencatatan
manual di spreadsheet Excel (`Book2.xlsx` / sheet `AGUSTUS 2026` dst).

> Plan sudah disetujui Dzaki pada 25 Sep 2026. Implementasi tetap dilakukan bertahap dan divalidasi per fase.

## 1. Latar Belakang

Selama ini tim QC mencatat data produksi per PO (No. PO, item, batch, qty,
WIP, status BPOM, dst.) di file Excel bulanan. Data itu baru dimigrasikan
sekali secara historis ke tabel `purchase_orders` / `purchase_order_items`.
Ke depan, pencatatan baru harus langsung masuk ke sistem lewat halaman web,
bukan Excel lagi.

## 2. Tujuan

Halaman baru di DIP Automation System tempat QC:
1. Membuat PO baru **atau** menambah item ke PO yang sudah ada.
2. Mengisi satu baris/item batch produksi per submit (bukan bulk seperti
   tabel spreadsheet).
3. Kalau No. Batch yang diketik belum ada di `product_batches` untuk produk
   itu, sistem menawarkan buat batch baru lewat modal kecil, lalu lanjut
   simpan item PO — tanpa harus pindah halaman.

## 3. Cakupan

**In scope:**
- Halaman/form input item PO baru (single-item-per-submit).
- Search & pilih PO existing (dropdown/search, bukan auto-detect ketik bebas).
- Buat PO baru kalau No. PO belum pernah ada.
- Search produk berdasarkan `no_na_produk` (prioritas) / nama produk.
- Search batch existing untuk produk terpilih.
- Modal "Tambah Batch Baru" kalau batch belum ada → insert ke `product_batches`
  → lanjut submit item PO dengan `product_batch_id` yang baru dibuat.
- Listing/riwayat item per PO (buat QC lihat apa saja yang sudah diinput di
  PO tersebut, untuk nentuin urutan berikutnya & cross-check).

**Out of scope (plan ini):**
- Bulk import dari Excel (sudah ada `migrate_po.py`, terpisah, khusus data
  historis, dry-run/execute manual oleh Dzaki — tidak disentuh fitur ini).
- Edit/hapus item PO yang sudah tersimpan (kalau dibutuhkan, itu fitur
  susulan, exact behavior — soft delete/audit trail — perlu didiskusikan
  terpisah).
- Approval/workflow multi-tahap (submit → review → approve). Asumsi sementara:
  begitu QC submit, langsung tersimpan (lihat Bagian 10, poin permission).
- Export/rekap PO ke Excel atau PDF (fitur pelaporan, di luar plan ini).
- Role/permission baru khusus "QC" (lihat Bagian 10).

## 4. Keputusan Terkunci (diskusi 25 Sep 2026)

1. Alur input: **1 form = 1 item/baris**, dipakai baik untuk menambah item ke
   PO existing maupun untuk item pertama dari PO baru.
2. No. PO existing: QC **memilih dari dropdown/search PO existing** — sistem
   tidak auto-detect dari ketikan bebas. Kalau No. PO yang dicari tidak ada di
   list, berarti itu PO baru → form "Buat PO Baru".
3. No. Batch belum ada di `product_batches` untuk produk terkait → sistem
   **tidak** menolak begitu saja. Muncul modal kecil "Tambah Batch Baru" (isi
   `tanggal_produksi`, dst.), setelah tersimpan, form item PO lanjut submit
   dengan batch yang baru dibuat.
4. (Dari plan migrasi, tetap berlaku) Matching produk **prioritas
   `no_na_produk`**, bukan nama produk.

## 5. Temuan Penting dari Audit Codebase

- Tabel `product_batches` (batch produk jadi) **sama sekali belum punya
  halaman/route create** di codebase saat ini. Satu-satunya pemakaian yang ada
  adalah read-only di `main.py` (ambil batch terbaru untuk cover Bab III PDF).
  Halaman "Bahan Baku" yang sudah ada mengelola `raw_materials` /
  `raw_material_company_docs` (bahan baku), **bukan** `product_batches`
  (produk jadi) — dua konsep & tabel yang berbeda.
- Konsekuensinya: **modal "Tambah Batch Baru" di fitur ini akan jadi
  create-path pertama untuk `product_batches` di seluruh sistem.** Perlu
  hati-hati field apa saja yang wajib diisi (lihat Bagian 7).
- Pola registrasi route yang sudah dipakai di codebase (`raw_materials_routes.py`,
  `notes_routes.py`): fungsi `register_xxx_routes(app, get_current_user,
  log_activity, templates, ...)` dipanggil dari `main.py`, menghindari circular
  import. Fitur ini sebaiknya ikut pola yang sama — modul baru misal
  `po_routes.py` dengan `register_po_routes(...)`.
- Role yang ada di sistem cuma `admin` dan `staff` (RBAC di `main.py`) — tidak
  ada role `qc` terpisah. Lihat Bagian 10.

## 6. Alur Halaman (UX)

### 6.1 Entry point
Halaman baru, misal `/purchase-orders` atau `/produksi/input-batch` (nama
final ikut konvensi Dzaki). Isinya:
- Tombol "Tambah Item Baru".
- Search/filter PO existing (by `no_po`), tiap PO expand menampilkan
  item-item yang sudah diinput (urutan, produk, batch, qty) — buat konteks
  QC sebelum nambah item baru.

### 6.2 Form "Tambah Item"
Langkah:
1. **Pilih PO:**
   - Search dropdown PO existing (by `no_po`) — pilih salah satu, ATAU
   - Toggle "PO Baru" → input `no_po`, `tanggal_po`, `qty_pcs` (field header,
     lihat Bagian 8).
2. **Pilih Produk:** search-combobox by `no_na_produk` (prioritas) / nama
   produk — pola sama seperti "searchable product dropdown" yang sudah ada
   di fitur lain di app.
3. **Pilih Batch:**
   - Dropdown batch existing untuk produk terpilih (query `product_batches`
     where `product_id` = terpilih).
   - Opsi "+ Tambah Batch Baru" di dropdown yang sama → buka modal (lihat
     6.3).
4. **Isi field item** (urutan, tanggal catatan batch, WIP, netto, qty kg,
   keterangan, dst — lihat Bagian 8 untuk daftar lengkap & tipe field).
5. Submit → insert ke `purchase_order_items` (dan `purchase_orders` dulu
   kalau PO baru).

### 6.3 Modal "Tambah Batch Baru"
Dipicu dari step 3 di atas. Minimal field yang perlu (ikut kolom
`product_batches` yang sudah ada — lihat catatan_batch_plan.md Bagian 5):
`no_batch`, `tanggal_produksi` (default hari ini kalau kosong, atau isi dari
`tanggal_catatan_batch` yang sudah diketik di form utama), `tanggal_ed`
(opsional saat input awal — **NEEDS VERIFICATION**, lihat Bagian 10),
`qc_results`/`kesimpulan`/`coa_file_url` dikosongkan dulu (diisi belakangan
lewat proses QC lain, kalau memang itu alurnya — **NEEDS VERIFICATION**).
Setelah modal submit sukses → `product_batch_id` baru otomatis terpilih di
form item, modal tertutup, QC lanjut isi field item lainnya.

## 7. Business Rules & Validasi

- **Urutan** per PO: auto-generate di server = `MAX(urutan) WHERE
  purchase_order_id = ...` + 1 (bukan diketik manual oleh QC, supaya konsisten
  dengan constraint unique `(purchase_order_id, urutan)` dan menghindari
  bentrok).
- **no_po** unik (constraint sudah ada) — kalau QC pilih "PO Baru" tapi
  ternyata `no_po` itu sudah ada, tampilkan error & arahkan pilih dari
  dropdown existing, jangan insert dobel.
- **Produk wajib match `no_na_produk`** ke `products` — kalau tidak ketemu,
  form tidak bisa submit (sama seperti keputusan #2 di migrasi: jangan buat
  produk baru otomatis dari halaman ini).
- **Batch**: `product_batch_id` wajib terisi sebelum submit item (baik pilih
  existing atau baru dibuat lewat modal).
- **Angka** (`wip`, `qty_kg`, `qty_belum_sop`, `qty_po_kg`, `qty_pcs`): input
  numerik standar (titik desimal, HTML `<input type="number">`), **tidak**
  perlu logika parsing Excel Indonesia (koma desimal, suffix "Kg", tanda
  kurung untuk minus) seperti di `migrate_po.py` — itu khusus buat baca data
  mentah spreadsheet lama. Untuk input langsung dari form, angka masuk apa
  adanya. (Flag ini ke Cline supaya tidak ikut-ikutan reuse fungsi
  `parse_id_number` dari script migrasi.)
- **Tanggal**: date picker biasa, simpan sebagai `DATE`.
- **Revisi Produksi** & **Temporary Reject**: tetap nullable, boleh dikosongkan
  (sesuai keputusan #7 di migrasi).
- **excel_row**: kosongkan/NULL untuk semua item hasil input manual (kolom ini
  murni jejak audit untuk baris hasil migrasi Excel).

## 8. Pemetaan Field Form → Kolom Database

### Header PO (`purchase_orders`) — hanya diisi saat "PO Baru":
| Field form | Kolom | Tipe |
|---|---|---|
| No. PO | `no_po` | text, unik |
| Tgl PO | `tanggal_po` | date, nullable |
| Qty (Pcs) | `qty_pcs` | numeric, nullable |

### Item (`purchase_order_items`) — selalu diisi tiap submit:
| Field form | Kolom | Tipe | Wajib? |
|---|---|---|---|
| (auto) | `purchase_order_id` | FK | ya |
| Produk (search NA) | `product_id` | FK | ya |
| Batch (existing/baru) | `product_batch_id` | FK | ya |
| (auto, server-side) | `urutan` | int | ya |
| Tgl Catatan Batch | `tanggal_catatan_batch` | date | tidak |
| WIP | `wip` | numeric | tidak |
| Netto | `netto` | text bebas (mis. "522,08 Gram /520 ml") | tidak |
| Qty (kg) | `qty_kg` | numeric | tidak |
| Keterangan | `keterangan` | text | tidak |
| Qty Belum Turun SOP | `qty_belum_sop` | numeric | tidak |
| Qty PO (kg) | `qty_po_kg` | numeric | tidak |
| Catatan Batch BPOM | `status_bpom` | text (mis. "V (DONE)") | tidak |
| Catatan Produksi | `catatan_produksi` | text | tidak |
| Revisi Produksi | `revisi_produksi` | text, nullable | tidak |
| Temporary Reject | `temporary_reject` | text, nullable | tidak |
| — | `excel_row` | NULL (bukan dari Excel) | — |

## 9. Struktur Teknis (usulan, ikut konvensi existing)

- Modul baru `app/po_routes.py`, pola `register_po_routes(app,
  get_current_user, log_activity, templates, ...)` dipanggil dari `main.py` —
  sama seperti `raw_materials_routes.py` / `notes_routes.py`.
- Template baru di `app/templates/` (nama menyusul), reuse komponen search
  produk yang sudah ada di halaman lain kalau memungkinkan (hindari
  duplikasi logic search-by-NA).
- Endpoint kasar (nama final menyusul, contoh saja):
  - `GET /purchase-orders` — halaman utama + search PO existing.
  - `GET /purchase-orders/{po_id}` atau via query — detail item-item PO
    tertentu (buat konteks urutan berikutnya).
  - `POST /purchase-orders` — buat PO baru (kalau toggle "PO Baru" dipakai).
  - `GET /purchase-orders/search-batches?product_id=...` — buat isi dropdown
    batch existing per produk (JSON, dipanggil dari JS saat produk dipilih).
  - `POST /product-batches` — dipanggil dari modal "Tambah Batch Baru".
  - `POST /purchase-orders/{po_id}/items` — submit item PO.
- Aktivitas insert (PO baru, batch baru, item baru) dicatat ke
  `activity_logs` seperti fitur lain (pola `log_activity` yang sudah ada).

## 10. Catatan Implementasi & Guardrail

Agar create-path pertama untuk `product_batches` tidak menimbulkan data parsial atau duplikat:

1. **Submit item harus atomic.** Untuk mode "PO Baru", pembuatan `purchase_orders` dan `purchase_order_items` harus dianggap satu operasi. Jika item gagal disimpan, jangan meninggalkan PO baru yang setengah jadi. Jika kemampuan transaksi Supabase tidak dipakai langsung dari aplikasi, gunakan RPC/database function untuk operasi multi-tabel ini.
2. **Pembuatan batch harus idempotent.** Sebelum `INSERT product_batches`, cek kombinasi `product_id + no_batch`; jika sudah ada, gunakan batch existing. Jangan membuat batch kedua hanya karena modal dibuka ulang atau request terkirim dua kali.
3. **Urutan harus aman terhadap race condition.** Jangan hanya mengandalkan pola `MAX(urutan)+1` dari dua request yang bisa berjalan bersamaan. Constraint `UNIQUE (purchase_order_id, urutan)` tetap menjadi pengaman terakhir; implementasi server harus menangani conflict dengan retry/re-fetch urutan.
4. **Validasi dilakukan server-side.** Validasi UI/JavaScript hanya untuk UX. Server tetap memvalidasi PO, product, batch, angka, tanggal, FK, dan duplicate item sebelum insert.
5. **Produk tidak boleh dibuat dari halaman ini.** Jika `no_na_produk` tidak ditemukan, submit ditolak dan user diminta memilih produk yang valid. Tidak ada fuzzy auto-match dan tidak ada auto-create product.
6. **Batch baru mengikuti produk yang dipilih.** `product_id` batch berasal dari produk yang dipilih di form, bukan dari teks nama produk atau input bebas user.
7. **Activity log setelah sukses.** `activity_logs` hanya dicatat setelah operasi terkait berhasil, sehingga log tidak menyatakan sukses untuk transaksi yang gagal.
8. **Jangan reuse parser migrasi.** `parse_id_number()` dan aturan koma desimal dari `migrate_po.py` tetap khusus migrasi spreadsheet. Form live memakai input numerik standar.
9. **Tahap awal tanpa edit/delete.** Karena edit/delete masih out of scope, implementasi pertama fokus pada create + listing/riwayat dan error handling yang jelas.
10. **Uji dengan data historis.** Sebelum dianggap siap dipakai QC, test minimal mencakup: tambah item ke PO hasil migrasi, buat PO baru + batch baru, pilih batch existing, submit ganda, batch dengan `no_batch` sama pada produk berbeda, product NA tidak ditemukan, dan dua submit bersamaan ke PO yang sama.

## 11. Hal yang Perlu Diverifikasi/Diputuskan Sebelum Implementasi

Ditandai `NEEDS VERIFICATION` — mohon dikonfirmasi Dzaki sebelum prompt Cline
ditulis:

1. **Field wajib di modal "Tambah Batch Baru".** `product_batches` punya
   kolom `tanggal_ed`, `qc_results`, `kesimpulan`, `coa_file_url` — apakah
   semua itu wajib diisi QC saat itu juga, atau boleh kosong dulu dan
   dilengkapi lewat proses/halaman lain nanti?
2. **Akses halaman.** Sistem cuma punya role `admin`/`staff` — apakah semua
   staff yang login boleh akses halaman ini, atau perlu pembatasan tertentu
   (mengingat belum ada role `qc` khusus)?
3. **Riwayat/audit item PO.** Apakah item yang sudah tersimpan boleh
   diedit/dihapus QC sendiri, atau begitu submit sifatnya final (perlu
   admin buat koreksi)? Ini menentukan apakah perlu endpoint edit/delete di
   fase ini atau menyusul.
4. **Nama route & lokasi menu.** Halaman ini masuk menu/navigasi yang mana
   (menu baru "Produksi"/"PO", atau sub-menu dari halaman existing)?
5. **Relasi ke PO lama hasil migrasi.** Kalau QC menambah item ke PO yang
   sebenarnya berasal dari migrasi historis (`no_po` sama), apakah itu
   skenario yang valid/diharapkan, atau PO hasil migrasi dianggap "closed"
   dan tidak akan ditambah item baru lagi?

## 12. Langkah Selanjutnya

Setelah poin-poin di Bagian 10 dikonfirmasi, dokumen ini dijadikan basis buat
menulis prompt implementasi untuk Cline (route baru, template, JS
search/modal), lalu Claude audit commit-nya seperti biasa.
