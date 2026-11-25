# Catatan Pembersihan Data Lama: Karakter Tak Terlihat pada Kolom Nama (2026-11-25)

> [!CAUTION]
> **JANGAN dijalankan otomatis oleh skrip atau pipeline CI/CD.**
> Seluruh query di bawah ini adalah **usulan manual** untuk dijalankan oleh pemilik repo lewat **Supabase SQL Editor**:
> 1. Jalankan di environment **staging terlebih dahulu** dan verifikasi hasilnya.
> 2. Hanya setelah staging terverifikasi bersih dan tidak ada bentrokan unik, jalankan di **produksi**.
> 3. **Tidak ada data nyata** di dokumen ini; semua contoh memakai escape Unicode (`E'[\u200B...]'`).

## Latar Belakang

Insiden produksi `2026-11-25 10:10 WIB`: `POST /products/{id}/edit` mengembalikan HTTP `500` (`UnicodeEncodeError: 'latin-1' codec can't encode character '\u2060'`) karena `nama_produk` diawali karakter tak terlihat `U+2060` (WORD JOINER) hasil copy-paste.

Aplikasi kini sudah:
1. Meng-encode seluruh flash cookie (`success_msg`, `error_msg`, `warning_msg`) dengan `urllib.parse.quote(..., safe="")` saat menulis dan `unquote` saat membaca (`app/flash_cookie.py`).
2. Membersihkan 9 karakter tak terlihat (`U+200B`, `U+200C`, `U+200D`, `U+2060`, `U+FEFF`, `U+00AD`, `U+180E`, `U+2028`, `U+2029`) + spasi di ujung lewat `clean_visible_text()` pada input nama baru/edit.

Data yang sudah telanjur tersimpan di database **belum** dibersihkan. Dokumen ini menyediakan query audit (read-only), pre-check keunikan, dan usulan `UPDATE` dalam transaksi.

---

## 1. Query Audit Read-Only (`SELECT`)

Jalankan query read-only berikut terlebih dahulu (di staging, lalu produksi) untuk menghitung jumlah baris yang masih memuat karakter tak terlihat pada kolom nama/kode yang relevan:

```sql
-- Audit read-only: hitung baris yang mengandung karakter tak terlihat
-- U+200B, U+200C, U+200D, U+2060, U+FEFF, U+00AD, U+180E, U+2028, U+2029
WITH pat AS (
    SELECT E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]' AS rx
)
SELECT 'products' AS tabel, 'nama_produk' AS kolom, COUNT(*) AS jumlah_baris
FROM public.products, pat
WHERE nama_produk ~ pat.rx
UNION ALL
SELECT 'products', 'nama_customer', COUNT(*)
FROM public.products, pat
WHERE nama_customer ~ pat.rx
UNION ALL
SELECT 'product_finished_specs', 'kode_produk', COUNT(*)
FROM public.product_finished_specs, pat
WHERE kode_produk ~ pat.rx
UNION ALL
SELECT 'product_finished_specs', 'disetujui_oleh', COUNT(*)
FROM public.product_finished_specs, pat
WHERE disetujui_oleh ~ pat.rx
UNION ALL
SELECT 'brands', 'name', COUNT(*)
FROM public.brands, pat
WHERE name ~ pat.rx
UNION ALL
SELECT 'producers', 'name', COUNT(*)
FROM public.producers, pat
WHERE name ~ pat.rx
UNION ALL
SELECT 'raw_materials', 'nama_dagang', COUNT(*)
FROM public.raw_materials, pat
WHERE nama_dagang ~ pat.rx
UNION ALL
SELECT 'raw_materials', 'kode_bahan_baku', COUNT(*)
FROM public.raw_materials, pat
WHERE kode_bahan_baku ~ pat.rx
UNION ALL
SELECT 'raw_materials', 'produsen', COUNT(*)
FROM public.raw_materials, pat
WHERE produsen ~ pat.rx
UNION ALL
SELECT 'raw_material_components', 'inci_name', COUNT(*)
FROM public.raw_material_components, pat
WHERE inci_name ~ pat.rx
UNION ALL
SELECT 'raw_material_composition_variants', 'nama_varian', COUNT(*)
FROM public.raw_material_composition_variants, pat
WHERE nama_varian ~ pat.rx
UNION ALL
SELECT 'raw_material_batches', 'no_batch', COUNT(*)
FROM public.raw_material_batches, pat
WHERE no_batch ~ pat.rx
UNION ALL
SELECT 'raw_material_batches', 'supplier', COUNT(*)
FROM public.raw_material_batches, pat
WHERE supplier ~ pat.rx
UNION ALL
SELECT 'raw_material_batches', 'nama_produsen', COUNT(*)
FROM public.raw_material_batches, pat
WHERE nama_produsen ~ pat.rx
UNION ALL
SELECT 'raw_material_batches', 'qc_signer', COUNT(*)
FROM public.raw_material_batches, pat
WHERE qc_signer ~ pat.rx
UNION ALL
SELECT 'raw_material_batches', 'qa_signer', COUNT(*)
FROM public.raw_material_batches, pat
WHERE qa_signer ~ pat.rx
UNION ALL
SELECT 'raw_material_batches', 'mengetahui_signer', COUNT(*)
FROM public.raw_material_batches, pat
WHERE mengetahui_signer ~ pat.rx
UNION ALL
SELECT 'sample_submissions', 'product_name', COUNT(*)
FROM public.sample_submissions, pat
WHERE product_name ~ pat.rx
UNION ALL
SELECT 'sample_submissions', 'product_item', COUNT(*)
FROM public.sample_submissions, pat
WHERE product_item ~ pat.rx
UNION ALL
SELECT 'sample_submissions', 'draft_brand', COUNT(*)
FROM public.sample_submissions, pat
WHERE draft_brand ~ pat.rx
UNION ALL
SELECT 'sample_submissions', 'draft_producer', COUNT(*)
FROM public.sample_submissions, pat
WHERE draft_producer ~ pat.rx
UNION ALL
SELECT 'sample_submissions', 'qc_signer', COUNT(*)
FROM public.sample_submissions, pat
WHERE qc_signer ~ pat.rx
UNION ALL
SELECT 'sample_submissions', 'rd_signer', COUNT(*)
FROM public.sample_submissions, pat
WHERE rd_signer ~ pat.rx
UNION ALL
SELECT 'purchase_orders', 'no_po', COUNT(*)
FROM public.purchase_orders, pat
WHERE no_po ~ pat.rx
UNION ALL
SELECT 'product_batches', 'no_batch', COUNT(*)
FROM public.product_batches, pat
WHERE no_batch ~ pat.rx
UNION ALL
SELECT 'profiles', 'full_name', COUNT(*)
FROM public.profiles, pat
WHERE full_name ~ pat.rx
UNION ALL
SELECT 'profiles', 'display_name', COUNT(*)
FROM public.profiles, pat
WHERE display_name ~ pat.rx
ORDER BY jumlah_baris DESC, tabel, kolom;
```

Jika ingin melihat ID baris yang terdampak (tanpa mengubah data) untuk kolom tertentu, misalnya `products.nama_produk`:

```sql
SELECT id, length(nama_produk) AS panjang_asli
FROM public.products
WHERE nama_produk ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';
```

---

## 2. Pre-Check Bentrokan Nilai Unik (`SELECT`)

Sebelum membersihkan kolom yang memiliki constraint unik atau pengecekan duplikat, pastikan pembersihan + `btrim()` tidak menghasilkan dua baris dengan nilai yang sama:

```sql
WITH pat AS (
    SELECT E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+' AS rx
)
-- 1) profiles.full_name (unique index lower(full_name))
SELECT 'profiles.full_name' AS target,
       lower(btrim(regexp_replace(full_name, pat.rx, '', 'g'))) AS nilai_bersih,
       COUNT(*) AS jumlah
FROM public.profiles, pat
GROUP BY 2
HAVING COUNT(*) > 1

UNION ALL

-- 2) purchase_orders.no_po
SELECT 'purchase_orders.no_po',
       btrim(regexp_replace(no_po, pat.rx, '', 'g')),
       COUNT(*)
FROM public.purchase_orders, pat
GROUP BY 2
HAVING COUNT(*) > 1

UNION ALL

-- 3) raw_materials.kode_bahan_baku
SELECT 'raw_materials.kode_bahan_baku',
       btrim(regexp_replace(kode_bahan_baku, pat.rx, '', 'g')),
       COUNT(*)
FROM public.raw_materials, pat
GROUP BY 2
HAVING COUNT(*) > 1

UNION ALL

-- 4) brands (producer_id, lower(name))
SELECT 'brands.(producer_id, name)',
       producer_id::text || ' | ' || lower(btrim(regexp_replace(name, pat.rx, '', 'g'))),
       COUNT(*)
FROM public.brands, pat
GROUP BY 2
HAVING COUNT(*) > 1;
```

> [!IMPORTANT]
> Pastikan hasil query Section 2 **kosong (0 baris)** sebelum menjalankan `UPDATE` di Section 3. Jika ada bentrokan pada kolom unik, selesaikan manual per-ID sebelum commit.

---

## 3. Usulan Query Pembersihan (`UPDATE` dalam Transaksi)

Jalankan di **staging lebih dulu**, periksa jumlah baris yang terubah per pernyataan, jalankan post-check (harus 0 baris tersisa), baru putuskan `COMMIT;` (atau `ROLLBACK;` bila jumlah baris tidak sesuai hasil audit Section 1).

> Catatan: Sesuaikan daftar pernyataan `UPDATE` dengan kolom yang jumlahnya `> 0` pada hasil Section 1. Untuk kolom wajib (`NOT NULL` / tidak boleh kosong), kondisi `AND btrim(regexp_replace(...)) <> ''` mencegah pembersihan mengubah nilai menjadi string kosong.

```sql
BEGIN;

-- Pre-check di dalam transaksi: pastikan tidak ada produk yang menjadi string kosong
DO $$
DECLARE
    v_empty_count integer;
    v_rx text := E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+';
BEGIN
    SELECT COUNT(*) INTO v_empty_count
    FROM public.products
    WHERE nama_produk ~ v_rx
      AND btrim(regexp_replace(nama_produk, v_rx, '', 'g')) = '';
    IF v_empty_count > 0 THEN
        RAISE EXCEPTION 'Abort: % baris products.nama_produk akan menjadi kosong setelah dibersihkan', v_empty_count;
    END IF;
END $$;

-- products
UPDATE public.products
SET nama_produk = btrim(regexp_replace(nama_produk, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE nama_produk ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

UPDATE public.products
SET nama_customer = btrim(regexp_replace(nama_customer, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE nama_customer ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

-- product_finished_specs
UPDATE public.product_finished_specs
SET kode_produk = btrim(regexp_replace(kode_produk, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE kode_produk ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

UPDATE public.product_finished_specs
SET disetujui_oleh = btrim(regexp_replace(disetujui_oleh, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE disetujui_oleh ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

-- brands & producers
UPDATE public.brands
SET name = btrim(regexp_replace(name, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE name ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]'
  AND btrim(regexp_replace(name, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g')) <> '';

UPDATE public.producers
SET name = btrim(regexp_replace(name, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE name ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]'
  AND btrim(regexp_replace(name, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g')) <> '';

-- raw_materials, raw_material_components, raw_material_composition_variants, raw_material_batches
UPDATE public.raw_materials
SET nama_dagang = btrim(regexp_replace(nama_dagang, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE nama_dagang ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]'
  AND btrim(regexp_replace(nama_dagang, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g')) <> '';

UPDATE public.raw_materials
SET kode_bahan_baku = btrim(regexp_replace(kode_bahan_baku, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE kode_bahan_baku ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]'
  AND btrim(regexp_replace(kode_bahan_baku, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g')) <> '';

UPDATE public.raw_materials
SET produsen = btrim(regexp_replace(produsen, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE produsen ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

UPDATE public.raw_material_components
SET inci_name = btrim(regexp_replace(inci_name, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE inci_name ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]'
  AND btrim(regexp_replace(inci_name, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g')) <> '';

UPDATE public.raw_material_composition_variants
SET nama_varian = btrim(regexp_replace(nama_varian, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE nama_varian ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]'
  AND btrim(regexp_replace(nama_varian, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g')) <> '';

UPDATE public.raw_material_batches
SET no_batch = btrim(regexp_replace(no_batch, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE no_batch ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]'
  AND btrim(regexp_replace(no_batch, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g')) <> '';

UPDATE public.raw_material_batches
SET supplier = btrim(regexp_replace(supplier, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE supplier ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]'
  AND btrim(regexp_replace(supplier, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g')) <> '';

UPDATE public.raw_material_batches
SET nama_produsen = btrim(regexp_replace(nama_produsen, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE nama_produsen ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

UPDATE public.raw_material_batches
SET qc_signer = btrim(regexp_replace(qc_signer, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE qc_signer ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

UPDATE public.raw_material_batches
SET qa_signer = btrim(regexp_replace(qa_signer, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE qa_signer ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

UPDATE public.raw_material_batches
SET mengetahui_signer = btrim(regexp_replace(mengetahui_signer, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE mengetahui_signer ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

-- sample_submissions
UPDATE public.sample_submissions
SET product_name = btrim(regexp_replace(product_name, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE product_name ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

UPDATE public.sample_submissions
SET product_item = btrim(regexp_replace(product_item, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE product_item ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

UPDATE public.sample_submissions
SET draft_brand = btrim(regexp_replace(draft_brand, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE draft_brand ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

UPDATE public.sample_submissions
SET draft_producer = btrim(regexp_replace(draft_producer, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE draft_producer ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

UPDATE public.sample_submissions
SET qc_signer = btrim(regexp_replace(qc_signer, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE qc_signer ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

UPDATE public.sample_submissions
SET rd_signer = btrim(regexp_replace(rd_signer, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE rd_signer ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

-- purchase_orders & product_batches
UPDATE public.purchase_orders
SET no_po = btrim(regexp_replace(no_po, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE no_po ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]'
  AND btrim(regexp_replace(no_po, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g')) <> '';

UPDATE public.product_batches
SET no_batch = btrim(regexp_replace(no_batch, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE no_batch ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]'
  AND btrim(regexp_replace(no_batch, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g')) <> '';

-- profiles (full_name & display_name)
UPDATE public.profiles
SET full_name = btrim(regexp_replace(full_name, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g'))
WHERE full_name ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]'
  AND btrim(regexp_replace(full_name, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g')) <> '';

UPDATE public.profiles
SET display_name = NULLIF(
    btrim(regexp_replace(display_name, E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]+', '', 'g')),
    ''
)
WHERE display_name ~ E'[\u200B\u200C\u200D\u2060\uFEFF\u00AD\u180E\u2028\u2029]';

COMMIT;
```

Setelah `COMMIT;`, jalankan ulang query Section 1 untuk memastikan seluruh `jumlah_baris` bernilai `0`. Jika sebelum `COMMIT;` ada jumlah baris terubah yang tidak sesuai, jalankan `ROLLBACK;`.
