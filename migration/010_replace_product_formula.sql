-- =====================================================================
-- 010_replace_product_formula.sql
--
-- Menyediakan fungsi Postgres public.replace_product_formula(p_product_id,
-- p_lines) yang menghapus + menulis ulang baris formula Bab 2 dalam SATU
-- TRANSAKSI, sehingga mode kegagalan "DELETE berhasil, INSERT gagal ->
-- formula produk hilang permanen" tidak mungkin terjadi.
--
-- Latar belakang (temuan audit H3.1):
--   app/products_routes.py sebelumnya menghapus semua baris
--   public.product_formula_lines lalu insert ulang baris baru sebagai dua
--   operasi terpisah. Kalau INSERT-nya gagal, produk Tertinggal tanpa
--   formula sama sekali, dan halaman tetap melapor "berhasil diperbarui".
--   Perbaikan H3.1 di sisi aplikasi memakai jalur SNAPSHOT + ROLLBACK
--   (snapshot baris lama sebelum delete, insert ulang bila insert gagal).
--   Fungsi di file ini adalah jalur yang lebih baik (atomik), tapi SIAP-SIAP
--   SAJA - belum dipakai dan belum dieksekusi.
--
-- CATATAN PENTING - FILE INI BELUM DIEKSEKUSI (22 Oktober 2026):
--   - File ini hanya DISIAPKAN. TIDAK pernah dieksekusi di staging maupun
--     produksi, dan TIDAK boleh dieksekusi lewat pipeline otomatis
--     (mis. supabase db push).
--   - Yang harus menjalankannya: pemilik repo, manual lewat Supabase SQL
--     Editor, STAGING LEBIH DAHULU, dan hasil eksekusi staging WAJIB dibaca
--     sebelum lanjut ke produksi.
--   - Kode aplikasi (app/products_routes.py) TIDAK bergantung pada fungsi
--     ini sama sekali. Tanpa file ini aplikasi tetap berjalan normal lewat
--     jalur snapshot + rollback yang sudah ada di app/products_routes.py.
--
-- CARA PAKAI (WAJIB IKUTI URUTAN):
--   1. Jalankan blok PRE-CHECK (langkah 0) lebih dulu - hanya SELECT, tidak
--      mengubah apa pun - lalu BACA hasilnya.
--   2. Jalankan blok DDL (langkah 1) lewat Supabase SQL Editor.
--   3. Ulangi langkah 1-2 di STAGING lebih dulu, periksa hasilnya, lalu
--      lanjut ke PRODUKSI.
--
-- EKSEKUSI: DILARANG dijalankan lewat pipeline / migrasi otomatis.
--           WAJIB staging lebih dulu sebelum produksi, dan hasil staging
--           harus dibaca sebelum lanjut ke produksi.
--
-- Struktur tabel public.product_formula_lines (diverifikasi 22 Oktober 2026
-- lewat information_schema.columns secara READ-ONLY, hasilnya identik di
-- staging DAN produksi):
--   id                 uuid        NOT NULL  default gen_random_uuid()
--   product_id         uuid        NOT NULL
--   raw_material_id    uuid        NOT NULL
--   percent_in_formula numeric     NOT NULL
--   created_at         timestamptz nullable  default now()
--   variant_id         uuid        nullable
--
-- Kolom id & created_at sengaja TIDAK ikut diisi saat INSERT: keduanya
-- punya default database, jadi baris yang dipulihkan/ditulis ulang tetap
-- konsisten dengan baris yang dibuat aplikasi.
-- =====================================================================

-- --- 0. PRE-CHECK (SELECT saja, di luar transaksi, tidak mengubah apa pun)
-- Tampilkan komposisi formula yang ada sekarang + cari produk yang total
-- persennya bukan 100 (data seperti itu tidak boleh hilang diam-diam).
SELECT pfl.product_id,
       COUNT(*)                                   AS jumlah_baris,
       SUM(pfl.percent_in_formula)                AS total_persen,
       CASE
           WHEN SUM(pfl.percent_in_formula) = 100 THEN 'ok'
           ELSE 'PERIKSA: total bukan 100'
       END                                        AS catatan
  FROM public.product_formula_lines pfl
 GROUP BY pfl.product_id
 ORDER BY pfl.product_id;

-- Detail baris per produk (siapkan salinan data sebelum ada penggantian):
SELECT product_id,
       raw_material_id,
       percent_in_formula,
       variant_id,
       created_at
  FROM public.product_formula_lines
 ORDER BY product_id, created_at;

BEGIN;

-- --- 1. Fungsi atomik replace formula Bab 2 ------------------------------
-- DELETE + INSERT dalam satu transaksi: kalau INSERT gagal, DELETE ikut
-- di-rollback sehingga formula lama tetap utuh.
CREATE OR REPLACE FUNCTION public.replace_product_formula(
    p_product_id uuid,
    p_lines jsonb
)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM public.product_formula_lines
     WHERE product_id = p_product_id;

    INSERT INTO public.product_formula_lines
        (product_id, raw_material_id, percent_in_formula, variant_id)
    SELECT p_product_id,
           (l ->> 'raw_material_id')::uuid,
           (l ->> 'percent_in_formula')::numeric,
           NULLIF(l ->> 'variant_id', '')::uuid
      FROM jsonb_array_elements(COALESCE(p_lines, '[]'::jsonb)) AS l
     WHERE NULLIF(l ->> 'raw_material_id', '') IS NOT NULL;
END;
$$;

COMMENT ON FUNCTION public.replace_product_formula(uuid, jsonb) IS
    'Ganti seluruh baris formula Bab 2 sebuah produk dalam satu transaksi. p_lines = array JSON [{raw_material_id, percent_in_formula, variant_id}]. Dipakai sebagai upgrade dari jalur snapshot+rollback di app/products_routes.py (belum diaktifkan).';

COMMIT;

-- --- 2. VERIFIKASI (SELECT saja, tidak mengubah apa pun) ------------------
-- Fungsi harus ada di katalog:
SELECT p.proname,
       pg_get_function_identity_arguments(p.oid) AS argumen,
       pg_get_function_result(p.oid)              AS hasil
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND p.proname = 'replace_product_formula';

-- Contoh pemanggilan (JANGAN dijalankan di produksi tanpa procedure):
--   SELECT public.replace_product_formula(
--       '00000000-0000-0000-0000-000000000000'::uuid,
--       '[{"raw_material_id": "11111111-1111-1111-1111-111111111111",
--          "percent_in_formula": "100.0000",
--          "variant_id": null}]'::jsonb
--   );
