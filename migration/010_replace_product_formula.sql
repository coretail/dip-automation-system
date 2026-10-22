-- =====================================================================
-- 010_replace_product_formula.sql
--
-- Menyediakan fungsi Postgres public.replace_product_formula(p_product_id,
-- p_lines) yang menghapus + menulis ulang baris formula Bab 2 dalam SATU
-- TRANSAKSI, dengan baris produk induk TERKUNCI (SELECT ... FOR UPDATE)
-- dan seluruh input divalidasi di sisi database.
--
-- Latar belakang (temuan audit H3.1):
--   app/products_routes.py sebelumnya menghapus semua baris
--   public.product_formula_lines lalu insert ulang baris baru sebagai dua
--   operasi terpisah. Kalau INSERT-nya gagal, produk tertinggal tanpa
--   formula sama sekali, dan halaman tetap melapor "berhasil diperbarui".
--   Perbaikan H3.1 sementara di sisi aplikasi memakai jalur SNAPSHOT +
--   ROLLBACK (snapshot baris lama sebelum delete, insert ulang bila insert
--   gagal). Jalur itu belum atomik: dua edit bersamaan bisa saling
--   menyela, pembaca lain bisa melihat formula kosong di antara DELETE dan
--   INSERT, dan kegagalan yang tidak pasti (timeout setelah INSERT
--   sebenarnya sudah committed) bisa membuat rollback menyalin baris jadi
--   dobel. File ini menggantikan jalur tersebut.
--
-- SESUDAH file ini dieksekusi, app/products_routes.py memanggil fungsi ini
-- sebagai SATU-SATUNYA jalur tulis formula Bab 2:
--   - aplikasi TIDAK lagi menghapus baris product_formula_lines sendiri;
--   - kalau pemanggilan fungsi gagal, TIDAK ada fallback DELETE+INSERT:
--     transaksi fungsi di-rollback sehingga formula lama utuh, dan pengguna
--     diberi tahu bahwa data produk lain sudah tersimpan;
--   - sebelum file ini dieksekusi, penyimpanan formula Bab 2 akan gagal
--     dengan pesan "fungsi transaksi belum terpasang" (data produk & dokumen
--     tetap tersimpan). Jadi urutan eksekusi WAJIB:
--     STAGING -> baca hasil staging -> PRODUKSI.
--
-- CATATAN PENTING - STATUS EKSEKUSI (22 Oktober 2026):
--   - File ini SUDAH dieksekusi di STAGING (ref odtfppboyjlbatajncgj) pada
--     21 Oktober 2026 (dua kali, karena file ini idempoten) dan hasilnya
--     sudah dibaca dan diverifikasi: fungsi terdaftar di pg_proc, hak
--     EXECUTE hanya untuk service_role, dan PostgREST sudah memuat
--     /rpc/replace_product_formula.
--   - File ini SUDAH dieksekusi juga di PRODUKSI (ref dytuprmoorvrugutozwv)
--     pada 22 Oktober 2026. Slice DDL yang dipakai di kedua environment
--     identik byte per byte (sha256 de7f8d33...), blok pre-check dibaca
--     lebih dulu, dan tidak ada satu baris pun data aplikasi yang berubah.
--   - Untuk environment BARU nanti, file ini tetap harus dijalankan manual
--     oleh pemilik repo lewat Supabase SQL Editor: STAGING lebih dulu, hasil
--     eksekusi staging WAJIB dibaca sebelum lanjut ke produksi.
--   - Eksekusi TIDAK BOLEH lewat pipeline otomatis (mis. supabase db
--     push).
--   - Nomor file 010 TIDAK boleh diubah atau ditukar dengan 009: angka 009
--     sengaja dipakai untuk migrasi lain. Nama file tetap
--     010_replace_product_formula.sql.
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
-- punya default database, jadi baris yang ditulis ulang tetap konsisten
-- dengan baris yang dibuat aplikasi.
--
-- Tabel pendukung yang dipakai fungsi:
--   public.products                           (baris induk yang dikunci)
--   public.raw_material_composition_variants  (pemilik variant_id)
-- =====================================================================

-- --- 0. PRE-CHECK (SELECT saja, di luar transaksi, tidak mengubah apa pun)
-- 0a. Komposisi formula yang ada sekarang + cari produk yang total persennya
--     bukan 100 (data seperti itu tidak boleh hilang diam-diam).
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

-- 0b. Apakah fungsi ini sudah ada di database? (tanpa baris = belum ada)
SELECT p.proname,
       pg_get_function_identity_arguments(p.oid) AS argumen,
       pg_get_function_result(p.oid)              AS hasil
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND p.proname = 'replace_product_formula';

-- 0c. Kolom yang dibutuhkan fungsi harus ada (produk induk + varian).
SELECT table_name,
       column_name,
       data_type
  FROM information_schema.columns
 WHERE table_schema = 'public'
   AND table_name IN ('products', 'raw_material_composition_variants')
   AND column_name IN ('id', 'raw_material_id')
 ORDER BY table_name, column_name;

BEGIN;

-- --- 1. Fungsi atomik replace formula Bab 2 ------------------------------
-- DELETE + INSERT dalam satu transaksi: kalau INSERT gagal, DELETE ikut
-- di-rollback sehingga formula lama tetap utuh. Baris produk induk dikunci
-- lebih dulu (FOR UPDATE) supaya dua penggantian formula untuk produk yang
-- sama tidak saling menyela.
--
-- DROP + CREATE (bukan CREATE OR REPLACE) dipakai supaya tipe balik boleh
-- diubah dan file ini tetap idempotent: menjalankannya dua kali menghasilkan
-- fungsi yang sama persis.
DROP FUNCTION IF EXISTS public.replace_product_formula(uuid, jsonb);

CREATE FUNCTION public.replace_product_formula(
    p_product_id uuid,
    p_lines jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_lines    jsonb;
    v_elem     jsonb;
    v_idx      integer := 0;
    v_total    numeric := 0;
    v_locked   uuid;
    v_rm_id    text;
    v_pct_text text;
    v_pct      numeric;
    v_variant  text;
    v_inserted integer := 0;
BEGIN
    -- (1) Kunci baris produk induk. Dua penggantian formula untuk produk
    --     yang sama jadi berurutan, bukan saling menyela. Kunci diambil
    --     SEBELUM baris formula disentuh.
    SELECT p.id
      INTO v_locked
      FROM public.products p
     WHERE p.id = p_product_id
     FOR UPDATE;

    IF v_locked IS NULL THEN
        RAISE EXCEPTION
            'Formula Bab 2: produk % tidak ditemukan, formula tidak disimpan.', p_product_id
            USING ERRCODE = 'P0002';
    END IF;

    -- (2) Bentuk payload harus berupa array baris dan tidak boleh kosong.
    v_lines := COALESCE(p_lines, '[]'::jsonb);

    IF jsonb_typeof(v_lines) <> 'array' THEN
        RAISE EXCEPTION
            'Formula Bab 2: data formula harus berupa daftar baris, tidak ada yang disimpan.'
            USING ERRCODE = '22023';
    END IF;

    IF jsonb_array_length(v_lines) = 0 THEN
        RAISE EXCEPTION
            'Formula Bab 2: tidak ada baris formula untuk disimpan, komposisi produk tidak diubah.'
            USING ERRCODE = '22023';
    END IF;

    -- (3) Validasi tiap baris. Semua error dilempar SEBELUM ada DELETE,
    --     jadi kalau validasi gagal tidak ada yang perlu di-rollback.
    FOR v_elem IN SELECT e.item FROM jsonb_array_elements(v_lines) AS e(item) LOOP
        v_idx := v_idx + 1;

        -- 3a. raw_material_id wajib ada dan harus UUID valid.
        v_rm_id := btrim(COALESCE(v_elem ->> 'raw_material_id', ''));

        IF v_rm_id = '' THEN
            RAISE EXCEPTION
                'Formula Bab 2: baris ke-% tidak punya bahan baku (raw_material_id kosong).', v_idx
                USING ERRCODE = '22023';
        END IF;

        BEGIN
            PERFORM v_rm_id::uuid;
        EXCEPTION WHEN others THEN
            RAISE EXCEPTION
                'Formula Bab 2: baris ke-% punya raw_material_id yang bukan UUID valid.', v_idx
                USING ERRCODE = '22023';
        END;

        -- 3b. percent_in_formula wajib ada, harus angka sederhana (bukan
        --     "1e5" / "abc" / kosong), dan tidak boleh negatif.
        v_pct_text := btrim(COALESCE(v_elem ->> 'percent_in_formula', ''));

        IF v_pct_text = '' THEN
            RAISE EXCEPTION
                'Formula Bab 2: baris ke-% tidak punya persentase (percent_in_formula kosong).', v_idx
                USING ERRCODE = '22023';
        END IF;

        IF v_pct_text !~ '^-?[0-9]+(\.[0-9]+)?$' THEN
            RAISE EXCEPTION
                'Formula Bab 2: baris ke-% punya persentase yang bukan angka sederhana '
                '(hanya boleh angka desimal, contoh 12.5).', v_idx
                USING ERRCODE = '22023';
        END IF;

        v_pct := v_pct_text::numeric;

        IF v_pct < 0 THEN
            RAISE EXCEPTION
                'Formula Bab 2: baris ke-% punya persentase negatif (%), '
                'persentase tidak boleh negatif.', v_idx, v_pct
                USING ERRCODE = '22023';
        END IF;

        v_total := v_total + v_pct;

        -- 3c. variant_id kalau ada harus UUID valid DAN milik raw_material_id
        --     pada baris yang sama (database adalah sumber kebenaran).
        v_variant := btrim(COALESCE(v_elem ->> 'variant_id', ''));

        IF v_variant <> '' THEN
            BEGIN
                PERFORM v_variant::uuid;
            EXCEPTION WHEN others THEN
                RAISE EXCEPTION
                    'Formula Bab 2: baris ke-% punya variant_id yang bukan UUID valid.', v_idx
                    USING ERRCODE = '22023';
            END;

            IF NOT EXISTS (
                SELECT 1
                  FROM public.raw_material_composition_variants v
                 WHERE v.id = v_variant::uuid
                   AND v.raw_material_id = v_rm_id::uuid
            ) THEN
                RAISE EXCEPTION
                    'Formula Bab 2: baris ke-% punya variant_id yang bukan milik bahan baku '
                    'pada baris itu.', v_idx
                    USING ERRCODE = '22023';
            END IF;
        END IF;
    END LOOP;

    -- (4) Total persentase harus tepat 100.0000% (toleransi 0.0001).
    IF abs(v_total - 100) > 0.0001 THEN
        RAISE EXCEPTION
            'Formula Bab 2: total persentase harus tepat 100.0000%%, total saat ini %. '
            'Formula tidak disimpan.', to_char(v_total, 'FM9999990.0000')
            USING ERRCODE = '22023';
    END IF;

    -- (5) Ganti atomik: DELETE + INSERT dalam satu transaksi (satu transaksi
    --     fungsi). Bila INSERT gagal, seluruh transaksi rollback sehingga
    --     formula lama tetap utuh.
    DELETE FROM public.product_formula_lines
     WHERE product_id = p_product_id;

    INSERT INTO public.product_formula_lines
        (product_id, raw_material_id, percent_in_formula, variant_id)
    SELECT p_product_id,
           btrim(COALESCE(e.item ->> 'raw_material_id', ''))::uuid,
           btrim(COALESCE(e.item ->> 'percent_in_formula', ''))::numeric,
           NULLIF(btrim(COALESCE(e.item ->> 'variant_id', '')), '')::uuid
      FROM jsonb_array_elements(v_lines) AS e(item);

    GET DIAGNOSTICS v_inserted = ROW_COUNT;

    -- (6) Balikan: jumlah baris formula yang ditulis (dipakai app untuk
    --     mencatat di audit log).
    RETURN v_inserted;
END;
$$;

COMMENT ON FUNCTION public.replace_product_formula(uuid, jsonb) IS
    'Ganti seluruh baris formula Bab 2 sebuah produk dalam satu transaksi. '
    'p_lines = array JSON [{raw_material_id, percent_in_formula, variant_id}]. '
    'Baris produk induk dikunci (FOR UPDATE), tiap baris divalidasi (UUID, '
    'persentase non-negatif, variant milik bahan bakunya) dan total persentase '
    'harus 100.0000 (toleransi 0.0001). Mengembalikan jumlah baris yang ditulis.';

-- --- 2. Hak akses (pola yang sama seperti migrasi 003 & 004) --------------
-- Fungsi baru secara bawaan punya hak EXECUTE untuk PUBLIC, jadi hak itu
-- WAJIB dicabut lebih dulu. Aplikasi memanggil fungsi ini lewat service
-- role (client Supabase service-role), jadi hanya service_role yang diberi
-- hak EXECUTE.
REVOKE ALL ON FUNCTION public.replace_product_formula(uuid, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.replace_product_formula(uuid, jsonb) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.replace_product_formula(uuid, jsonb) TO service_role;

COMMIT;

-- Minta PostgREST memuat ulang cache skema supaya fungsi langsung bisa
-- dipanggil lewat /rest/v1/rpc/replace_product_formula.
NOTIFY pgrst, 'reload schema';

-- --- 3. VERIFIKASI (SELECT saja, tidak mengubah apa pun) ------------------
-- Fungsi harus ada di katalog, dengan hak akses yang benar:
SELECT p.proname,
       pg_get_function_identity_arguments(p.oid) AS argumen,
       pg_get_function_result(p.oid)              AS hasil,
       p.prosecdef                                   AS security_definer,
       p.proconfig                                   AS search_path,
       p.proacl                                      AS hak_akses
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND p.proname = 'replace_product_formula';

-- Daftar siapa saja yang boleh memanggil fungsi ini (harus ada service_role,
-- dan TIDAK boleh ada PUBLIC / anon / authenticated):
SELECT routine_name,
       grantee,
       privilege_type
  FROM information_schema.routine_privileges
 WHERE routine_name = 'replace_product_formula'
 ORDER BY grantee, privilege_type;

-- Contoh pemanggilan (JANGAN dijalankan di produksi tanpa procedure):
--   SELECT public.replace_product_formula(
--       '00000000-0000-0000-0000-000000000000'::uuid,
--       '[{"raw_material_id": "11111111-1111-1111-1111-111111111111",
--          "percent_in_formula": "100.0000",
--          "variant_id": null}]'::jsonb
--   );