-- =====================================================================
-- 008_products_soft_delete_contract.sql
--
-- Mengubah soft delete produk dari "konvensi tak tertulis" menjadi
-- KONTRAK DATA yang ditegakkan database:
--   - kolom is_deleted / deleted_at resmi ada di public.products
--   - kedua kolom selalu sinkron (produk di Sampah WAJIB punya deleted_at,
--     produk aktif WAJIB punya deleted_at NULL)
--   - index gabungan (is_deleted, deleted_at DESC) untuk query Sampah
--     dan filter dashboard
--
-- Latar belakang: route POST /products/delete/{product_id} sempat hilang
-- (commit 5f82f94) sehingga tombol "Hapus Produk" di dashboard balas 404,
-- dan tidak ada mekanisme database yang mencegah is_deleted/deleted_at
-- tidak sinkron.
--
-- Script ini IDEMPOTENT dan AMAN dijalankan berulang.
--
-- CARA PAKAI (WAJIB IKUTI URUTAN):
--   1. Jalankan blok PRE-CHECK (langkah 0) lebih dulu - hanya SELECT, tidak
--      mengubah apa pun - lalu BACA hasilnya. Kalau ada baris tidak sinkron,
--      PERBAIKI DULU secara manual, karena CHECK constraint di langkah 2
--      akan GAGAL kalau baris seperti itu masih ada.
--   2. Jalankan blok DDL (langkah 1-3) lewat Supabase SQL Editor.
--   3. Ulangi langkah 1-2 di STAGING lebih dulu, periksa hasilnya, lalu
--      lanjut ke PRODUKSI. CATATAN 21 Oktober 2026: file ini SUDAH
--      dieksekusi di staging (odtfppboyjlbatajncgj) DAN produksi
--      (dytuprmoorvrugutozwv) - termasuk langkah 1b - jadi menjalankan ulang
--      sekarang aman (idempotent / no-op, tidak mengubah data). Blok
--      PRE-CHECK (langkah 0) tetap WAJIB dibaca lebih dulu sebelum
--      melakukan perubahan apa pun terhadap kontrak ini di masa depan.
--
-- CATATAN PRE-CHECK: query langkah 0 hanya bisa dijalankan bila kolom
-- is_deleted & deleted_at sudah ada (kondisi STAGING & PRODUKSI saat ini).
-- Pada fresh install yang belum punya kedua kolom, query akan error
-- "column does not exist" - itu normal: lewati langkah 0, jalankan DDL
-- langkah 1-3 dulu, lalu ULANGI langkah 0 untuk memastikan tidak ada baris
-- tidak sinkron.
--
-- EKSEKUSI: DILARANG dijalankan lewat pipeline / migrasi otomatis.
--           WAJIB staging lebih dulu sebelum produksi, dan hasil staging
--           harus dibaca sebelum lanjut ke produksi.
--           Untuk environment yang SUDAH menjalankan file ini (lihat RIWAYAT
--           EKSEKUSI di bawah), menjalankannya lagi aman: seluruh langkah
--           idempotent dan tidak mengubah data.
--
-- RIWAYAT EKSEKUSI (21 Oktober 2026):
--   - Dieksekusi atas otorisasi eksplisit pemilik repo, lewat Supabase
--     Management API (POST /v1/projects/{ref}/database/query) - bukan SQL Editor.
--   - Staging  (odtfppboyjlbatajncgj): SUDAH - pre-check 0 pelanggaran, constraint
--     + index terpasang, probe enforcement ditolak SQLSTATE 23514, data tidak berubah.
--   - Produksi (dytuprmoorvrugutozwv): SUDAH - hasil sama, 136 produk, 8 ter-trash
--     sebelum dan sesudah, seluruh deleted_at byte-identik.
--   - Catatan: kolom is_deleted SUDAH ADA sebelumnya, jadi "ADD COLUMN IF NOT
--     EXISTS" jadi no-op dan clause NOT NULL tidak berlaku pada eksekusi
--     pertama. Celah itu ditutup terpisah di langkah 1b (lihat di bawah).
--   - Langkah 1b (ALTER COLUMN is_deleted SET NOT NULL) dieksekusi 21 Okt 2026
--     di kedua environment, setelah guard "is_deleted IS NULL = 0" diverifikasi:
--     - Staging: is_nullable YES -> NO, hitungan tetap 2 produk (1 ter-trash).
--     - Produksi: is_nullable YES -> NO, hitungan tetap 136 produk (9 ter-trash).
--     Catatan: default is_deleted sudah `false` sebelum migrasi ini, jadi
--     klausa SET DEFAULT hanya no-op; hanya SET NOT NULL yang berdampak.
-- =====================================================================

-- --- 0. PRE-CHECK (SELECT saja, di luar transaksi, tidak mengubah apa pun)
-- Tampilkan produk yang soft delete-nya tidak konsisten. Baris seperti ini
-- akan membuat CHECK constraint di langkah 2 gagal, jadi harus dibersihkan
-- lebih dulu. Kalau query ini mengembalikan 0 baris -> lanjut ke langkah 1.
SELECT id,
       nama_produk,
       is_deleted,
       deleted_at,
       CASE
           WHEN is_deleted AND deleted_at IS NULL
               THEN 'perbaiki: is_deleted=true tapi deleted_at NULL -> set deleted_at = now()'
           WHEN NOT is_deleted AND deleted_at IS NOT NULL
               THEN 'perbaiki: is_deleted=false tapi deleted_at terisi -> set deleted_at = NULL'
       END AS saran_perbaikan
  FROM public.products
 WHERE (is_deleted AND deleted_at IS NULL)
    OR (NOT is_deleted AND deleted_at IS NOT NULL)
 ORDER BY nama_produk;

BEGIN;

-- --- 1. Kontrak kolom soft delete --------------------------------------
-- Kedua kolom sudah ada di produksi & staging; IF NOT EXISTS membuat
-- blok ini no-op di sana, tapi mengodifikasi kontrak untuk environment baru.
ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

COMMENT ON COLUMN public.products.is_deleted IS
    'TRUE = produk ada di Sampah (disembunyikan dari dashboard & dokumen DIP). FALSE = produk aktif.';

COMMENT ON COLUMN public.products.deleted_at IS
    'Waktu produk dipindahkan ke Sampah. NULL untuk produk aktif. WAJIB sinkron dengan is_deleted.';

-- --- 1b. Tutup celah NULLability --------------------------------------
-- Kolom is_deleted sudah ada sebelum migrasi ini, sehingga "ADD COLUMN IF NOT
-- EXISTS" di langkah 1 menjadi no-op dan clause NOT NULL tidak pernah
-- berlaku. Akibatnya kolom tetap NULLABLE, dan baris dengan is_deleted=NULL
-- akan LOLOS dari CHECK constraint (SQL three-valued logic: NULL AND ... =
-- NULL, yang dianggap tidak melanggar).
-- Pernyataan berikut menutup celah itu. Pratinjau jumlah baris bermasalah
-- harus 0 sebelum statement ini dijalankan.
--
-- PERHATIAN: bila masih ada baris dengan is_deleted IS NULL, statement ini
-- GAGAL. Jalankan SELECT count(*) FROM public.products WHERE is_deleted IS NULL
-- lebih dulu, dan perbaiki baris tersebut (set is_deleted = false) sebelum
-- melanjutkan.
ALTER TABLE public.products
    ALTER COLUMN is_deleted SET DEFAULT false;

ALTER TABLE public.products
    ALTER COLUMN is_deleted SET NOT NULL;

-- --- 2. Jaring pengaman konsistensi ------------------------------------
ALTER TABLE public.products
    DROP CONSTRAINT IF EXISTS products_soft_delete_consistency;

ALTER TABLE public.products
    ADD CONSTRAINT products_soft_delete_consistency
    CHECK ((is_deleted AND deleted_at IS NOT NULL) OR (NOT is_deleted AND deleted_at IS NULL));

COMMENT ON CONSTRAINT products_soft_delete_consistency ON public.products IS
    'Menjaga is_deleted dan deleted_at selalu sinkron: produk di Sampah wajib punya deleted_at, produk aktif wajib deleted_at NULL.';

-- --- 3. Index untuk query Sampah & filter dashboard --------------------
-- Melayani app/dashboard_routes.py: .eq("is_deleted", True).order("deleted_at", desc=True)
-- (halaman /admin/trash) dan filter .eq("is_deleted", False) di dashboard.
-- Tanpa index ini kedua query harus full-scan seluruh tabel products.
CREATE INDEX IF NOT EXISTS idx_products_is_deleted_deleted_at
    ON public.products (is_deleted, deleted_at DESC);

COMMIT;
