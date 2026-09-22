# Fitur: Varian Komposisi Bahan Baku (per Produsen/Distributor)

## Konteks & Kenapa Ini Proyek Besar

Sekarang 1 kode bahan baku = 1 breakdown INCI tetap (`raw_material_components`,
langsung nempel ke `raw_material_id`). Req barunya: 1 kode bahan baku (misal
"Ceraskin P") bisa punya **beberapa breakdown berbeda sekaligus**, tergantung
dari produsen/distributor mana barangnya datang — dan keduanya harus bisa
**hidup bersamaan** (produk A masih pakai breakdown lama, produk B udah pakai
breakdown baru, di waktu yang sama).

Sebelum mulai coding, saya udah grep semua tempat yang baca
`raw_material_components` — ternyata ada **7 titik baca** dan **3 tempat di
antaranya adalah implementasi terpisah-terpisah** buat hal yang sama
("hitung breakdown INCI suatu produk"): baris ~2438 (Bab III/text design),
`_gather_qualquant_data` sekitar baris ~3369 (dipakai bareng oleh halaman
Kualitatif-Kuantitatif DAN export Excel-nya), dan baris ~3614 (Bab III text
design lain lagi). Ini masalah tersendiri yang UDAH ADA sebelum fitur ini
kita mulai — 3 kali logic yang sama ditulis ulang beda-beda. Kalau fitur
varian ini ditempel ke ketiganya secara terpisah tanpa disatuin dulu,
risikonya besar salah satu kelewat update dan datanya jadi gak konsisten
antara 1 halaman dengan halaman lain. **Jadi bagian dari fix ini adalah
nyatuin resolusi breakdown ke 1 fungsi helper, bukan cuma nambahin variant
di 3 tempat terpisah.**

Kerjain bertahap sesuai fase di bawah, jangan sekaligus.

---

## Fase 1 — Skema Database

### Tabel baru: `raw_material_composition_variants`
- `id` (uuid, pk)
- `raw_material_id` (fk ke `raw_materials`)
- `nama_varian` (text) — label buat user, misal nama produsen/distributor
  ("PT Sumber Kimia" / "Distributor B")
- `is_default` (boolean, default false) — varian yang dipakai kalau formula
  produk gak milih spesifik
- `created_at`

### Ubah `raw_material_components`
Tambah kolom `variant_id` (fk ke `raw_material_composition_variants`).

### Ubah `product_formula_lines`
Tambah kolom `variant_id` (fk ke `raw_material_composition_variants`,
**nullable**). NULL artinya "pakai varian default bahan baku itu" — biar
gak perlu backfill jutaan baris formula lama.

### Migrasi data lama
Buat SETIAP `raw_materials` yang sekarang punya isi di
`raw_material_components`:
1. Insert 1 baris baru ke `raw_material_composition_variants` — `nama_varian`
   diisi dari `raw_materials.produsen` kalau ada isinya, kalau kosong isi
   "Varian Default". Set `is_default = true`.
2. UPDATE semua baris `raw_material_components` milik bahan baku itu,
   isi `variant_id`-nya ke id varian yang baru dibikin barusan.

`product_formula_lines` yang lama TIDAK perlu diubah — biarin `variant_id`
NULL, nanti di-resolve otomatis ke varian default lewat helper Fase 2.

Setelah migrasi ini, tolong tunjukin hasil query cek: pastikan **tidak ada**
baris `raw_material_components` yang `variant_id`-nya masih NULL (berarti
kelewat proses migrasi).

---

## Fase 2 — Helper Resolusi Terpusat (WAJIB sebelum lanjut ke fase manapun)

Bikin 1 fungsi baru, taruh di tempat yang gampang di-reuse (`app/main.py`
bagian atas dekat helper lain, atau file baru kalau mau):

```python
def _resolve_variant_components(raw_material: dict, variant_id: str | None) -> list[dict]:
    """
    raw_material: dict hasil query yang sudah include nested
      raw_material_composition_variants(*, raw_material_components(*))
    variant_id: dari product_formula_lines.variant_id (boleh None)

    Balikin: list komponen (raw_material_components) dari varian yang tepat.
    Kalau variant_id None atau gak ketemu -> pakai varian yang is_default=True.
    Kalau gak ada yang is_default juga (data korup/kosong) -> pakai varian
      pertama yang ada, biar gak pernah balikin list kosong secara diam-diam.
    """
```

### Ganti SEMUA 3 titik implementasi breakdown INCI yang lama supaya manggil helper ini:

1. **Baris ~2438** (Bab III/text design) — ganti query dari
   `.select("*").eq("raw_material_id", rm_id)` jadi query nested lewat
   `raw_materials(*, raw_material_composition_variants(*, raw_material_components(*)))`,
   terus ambil `line.get("variant_id")` dari `product_formula_lines`, panggil
   `_resolve_variant_components(...)`.
2. **`_gather_qualquant_data`, baris ~3369** — sama, ganti
   `raw_material_components(*)` jadi nested variants, resolve pakai helper.
   Ini dipakai bareng oleh halaman HTML Kualitatif-Kuantitatif DAN export
   Excel-nya — sekali fix di sini, dua-duanya ikut kebenerin.
3. **Baris ~3614** (Bab III text design lain) — sama persis polanya.

Titik lain yang PERLU ikut disesuaikan select query-nya (tapi gak butuh
resolusi varian, cuma jangan sampai query lama-nya rusak karena struktur
tabel berubah):
- `/raw-materials` GET (baris ~942) — tampilan daftar bahan baku, sekarang
  perlu nested ke variants dulu baru components.
- Query batch listing (baris ~955) yang nampilin CAS number di kartu batch —
  cukup ambil dari varian default aja buat tampilan ringkas ini (gak perlu
  per-produk-spesifik di context ini).

---

## Fase 3 — UI Kelola Varian di `raw_materials.html`

Di form tambah/edit bahan baku:
- Tambah tab/selector varian di atas tabel breakdown INCI yang udah ada
  (misal pill/tab per varian, isinya nama produsen/distributor).
- Tombol "+ Tambah Varian" — minta nama produsen/distributor, bikin varian
  kosong baru, breakdown INCI-nya mulai dari nol (form yang sama kayak
  sekarang, cuma scoped ke varian yang lagi dipilih).
- Tombol "Jadikan Default" per varian (cuma 1 yang boleh default dalam
  satu waktu — pilih yang baru otomatis meng-unset yang lama).
- Guard: gak boleh hapus varian terakhir yang tersisa (minimal harus ada 1).
- Guard: kalau mau hapus varian yang ternyata masih dipakai eksplisit sama
  `product_formula_lines.variant_id` di produk manapun, tolak dan kasih
  pesan jelas (mirip pola tolak-hapus yang udah ada buat bahan baku yang
  masih dipakai produk aktif).

---

## Fase 4 — Pilih Varian di Formula Produk (`edit_product.html`, tab Bab 2)

Sekarang baris formula pakai array paralel `raw_material_id[]` +
`percentage[]` (lihat baris ~320, ~354, dan JS di ~704-811). Tambah:

- Endpoint baru kecil: `GET /raw-materials/{rm_id}/variants` → JSON daftar
  varian bahan baku itu (id + nama_varian + is_default).
- Pas user pilih bahan baku di 1 baris formula (lewat search-select yang
  udah ada), JS manggil endpoint itu. Kalau hasilnya cuma 1 varian, gak usah
  nampilin apa-apa (auto-pakai itu). Kalau lebih dari 1, munculin dropdown
  kecil "Varian/Produsen" di baris itu, wajib dipilih sebelum simpan.
- Tambah array paralel baru `variant_id[]` sejajar sama `raw_material_id[]`
  dan `percentage[]` — kalau baris itu cuma 1 varian (dropdown gak muncul),
  kirim value kosong/null, backend anggap NULL (pakai default).
- Di `update_product` (baris ~4344, bagian insert `product_formula_lines`),
  tambahin `"variant_id": (variant_id[i] or None)` ke tiap baris yang
  di-insert.

---

## Catatan Penting

- Jangan ubah cara kerja fitur "Bahan Aktif" yang baru kita bikin
  (`is_bahan_aktif`) — itu tetap kolom di `raw_material_components`, otomatis
  ikut per-varian karena breakdown-nya emang per-varian sekarang.
- Produk yang formula-nya udah ada dari sebelum fitur ini gak boleh berubah
  hasilnya sama sekali — makanya migrasi Fase 1 penting: varian default hasil
  migrasi HARUS punya isi breakdown yang identik sama yang lama.
- Kerjain fase 1-2 dulu, tes hasilnya beneran konsisten di ketiga tempat lama
  (halaman qual-quant, export Excel, Bab III), baru lanjut fase 3-4 buat
  UI-nya. Jangan loncat ke fase 3 sebelum fase 2 kelar dan udah dicoba.
