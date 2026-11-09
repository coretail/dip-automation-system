-- =====================================================================
-- 013_replace_raw_material_components.sql
--
-- Menyediakan fungsi Postgres public.replace_raw_material_components(
-- p_raw_material_id, p_variant_id, p_components) yang menghapus + menulis
-- ulang baris komponen INCI raw_material_components dalam SATU TRANSAKSI,
-- dengan baris induk terkunci (SELECT ... FOR UPDATE) dan input divalidasi.
--
-- Latar belakang (temuan audit C-07):
--   app/raw_materials_routes.py (route POST /raw-materials/edit/{rm_id})
--   menghapus baris raw_material_components (variant NULL + varian yang
--   diedit) lalu insert baris baru sebagai dua operasi terpisah. Bila
--   membangun list gagal (mis. IndexError karena panjang list form tidak
--   sama) atau insert gagal, komponen lama SUDAH terhapus dan tidak ada
--   penggantinya: komposisi bahan baku hilang.
--   Salinan log_activity(... "update" ...) dipanggil sebelum blok komponen,
--   jadi audit mencatat sukses walau komponen gagal.
--
-- SESUDAH file ini dieksekusi, app/raw_materials_routes.py memanggil fungsi
-- ini sebagai SATU-SATUNYA jalur tulis komponen pada route edit:
--   - aplikasi TIDAK lagi menghapus/meng-insert raw_material_components
--     sendiri pada jalur edit;
--   - kalau pemanggilan fungsi gagal (termasuk fungsi belum ada), TIDAK ada
--     fallback DELETE+INSERT: transaksi fungsi di-rollback sehingga komponen
--     lama utuh, dan pengguna diberi tahu komponen TIDAK berubah;
--   - sebelum file ini dieksekusi, edit komponen gagal dengan pesan error
--     dan komponen TIDAK berubah (fail-safe). Jadi urutan eksekusi WAJIB:
--     STAGING -> baca hasil staging -> PRODUKSI.
--
-- CARA PAKAI (WAJIB IKUTI URUTAN):
--   1. Jalankan blok PRE-CHECK (langkah 0) lebih dulu - hanya SELECT - lalu
--      BACA hasilnya.
--   2. Jalankan blok DDL (langkah 1) lewat Supabase SQL Editor manual oleh
--      pemilik repo. STAGING lebih dulu, hasil staging dibaca sebelum
--      lanjut ke produksi.
--   3. Jalankan blok VERIFIKASI (langkah 3) dan baca hasilnya.
--
-- EKSEKUSI: DILARANG dijalankan agen. WAJIB manual oleh pemilik repo via
--           Supabase SQL Editor (staging dulu). TIDAK BOLEH lewat pipeline
--           otomatis (mis. supabase db push).
--
-- Struktur tabel public.raw_material_components (disimpulkan dari kode
-- app/raw_materials_routes.py dan app/variant_components.py per 2026-11-09;
-- BELUM terverifikasi via information_schema karena agen tidak punya akses
-- DB. Pemilik repo wajib menjalankan pre-check 0c sebelum DDL):
--   id                  uuid     NOT NULL  default gen_random_uuid()
--   raw_material_id     uuid     NOT NULL
--   variant_id          uuid     nullable
--   inci_name           text
--   cas_number          text     nullable
--   "function"          text     nullable
--   percent_internal    numeric  NOT NULL
--   is_bahan_aktif      boolean  NOT NULL  default false
--   created_at          timestamptz nullable default now()
-- Kolom id, is_bahan_aktif, created_at Boleh dilewati saat INSERT bila
-- punya default; fungsi ini hanya mengisi kolom yang disebut eksplisit.
--
-- CATATAN PEMANGGILAN: p_components WAJIB dikirim sebagai array JSON asli
-- (list Python di PostgREST), BUKAN string JSON. String sampai sebagai
-- string scalar dan cek jsonb_typeof(v_components) <> 'array' akan menolak
-- setiap panggilan. Pola yang sama dengan migrasi 010
-- (replace_product_formula): app/products_routes.py mengirim list langsung.
--
-- Tabel pendukung yang dipakai fungsi:
--   public.raw_materials                        (baris induk yang dikunci)
--   public.raw_material_composition_variants    (pemilik variant_id)
-- =====================================================================

-- --- 0. PRE-CHECK (SELECT saja, di luar transaksi, tidak mengubah apa pun)
-- 0a. Komposisi yang ada sekarang (siapkan salinan sebelum ada penggantian):
SELECT raw_material_id,
       variant_id,
       inci_name,
       percent_internal,
       is_bahan_aktif
  FROM public.raw_material_components
 ORDER BY raw_material_id, variant_id, inci_name;

-- 0b. Apakah fungsi ini sudah ada di database? (tanpa baris = belum ada)
SELECT p.proname,
       pg_get_function_identity_arguments(p.oid) AS argumen,
       pg_get_function_result(p.oid)              AS hasil
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND p.proname = 'replace_raw_material_components';

-- 0c. Kolom yang dibutuhkan fungsi harus ada. Verifikasi tipe ini sebelum DDL.
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_schema = 'public'
   AND table_name = 'raw_material_components'
 ORDER BY ordinal_position;

BEGIN;

-- --- 1. Fungsi atomik replace komponen ----------------------------------
-- DELETE + INSERT dalam satu transaksi: kalau INSERT gagal, DELETE ikut
-- di-rollback sehingga komponen lama tetap utuh. Baris induk dikunci
-- lebih dulu (FOR UPDATE) supaya dua edit komponen bahan baku yang sama
-- tidak saling menyela.
--
-- DROP + CREATE (bukan CREATE OR REPLACE) dipakai supaya file ini
-- idempotent: menjalankannya dua kali menghasilkan fungsi yang sama.
DROP FUNCTION IF EXISTS public.replace_raw_material_components(uuid, uuid, jsonb);

CREATE FUNCTION public.replace_raw_material_components(
    p_raw_material_id uuid,
    p_variant_id uuid,
    p_components jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_components jsonb;
    v_elem     jsonb;
    v_idx      integer := 0;
    v_locked   uuid;
    v_inci     text;
    v_cas      text;
    v_fn       text;
    v_pct_text text;
    v_pct      numeric;
    v_flag     boolean;
    v_inserted integer := 0;
BEGIN
    -- (1) Kunci baris bahan baku induk sebelum komponen disentuh.
    SELECT r.id
      INTO v_locked
      FROM public.raw_materials r
     WHERE r.id = p_raw_material_id
     FOR UPDATE;

    IF v_locked IS NULL THEN
        RAISE EXCEPTION
            'Komponen RM: bahan baku % tidak ditemukan, komponen tidak diubah.', p_raw_material_id
            USING ERRCODE = 'P0002';
    END IF;

    -- (2) Bentuk payload harus berupa array (boleh kosong = hapus varian).
    v_components := COALESCE(p_components, '[]'::jsonb);

    IF jsonb_typeof(v_components) <> 'array' THEN
        RAISE EXCEPTION
            'Komponen RM: data komponen harus berupa daftar baris, tidak ada yang diubah.'
            USING ERRCODE = '22023';
    END IF;

    -- (3) Validasi tiap baris SEBELUM ada DELETE (tidak perlu rollback).
    FOR v_elem IN SELECT e.item FROM jsonb_array_elements(v_components) AS e(item) LOOP
        v_idx := v_idx + 1;

        v_inci := btrim(COALESCE(v_elem ->> 'inci_name', ''));
        IF v_inci = '' THEN
            RAISE EXCEPTION
                'Komponen RM: baris ke-% tidak punya inci_name.', v_idx
                USING ERRCODE = '22023';
        END IF;

        v_cas := btrim(COALESCE(v_elem ->> 'cas_number', ''));
        v_fn := btrim(COALESCE(v_elem ->> 'function', ''));

        v_pct_text := btrim(COALESCE(v_elem ->> 'percent_internal', ''));
        IF v_pct_text = '' THEN
            RAISE EXCEPTION
                'Komponen RM: baris ke-% tidak punya persentase (percent_internal kosong).', v_idx
                USING ERRCODE = '22023';
        END IF;

        IF v_pct_text !~ '^-?[0-9]+(\.[0-9]+)?$' THEN
            RAISE EXCEPTION
                'Komponen RM: baris ke-% punya persentase yang bukan angka sederhana.', v_idx
                USING ERRCODE = '22023';
        END IF;

        v_pct := v_pct_text::numeric;
        IF v_pct < 0 THEN
            RAISE EXCEPTION
                'Komponen RM: baris ke-% punya persentase negatif (%), '
                'persentase tidak boleh negatif.', v_idx, v_pct
                USING ERRCODE = '22023';
        END IF;

        v_flag := (v_elem ->> 'is_bahan_aktif') = 'true';
    END LOOP;

    -- (4) Ganti atomik: hapus varian NULL + varian yang diedit (persis
    --     cakupan delete sekarang; varian lain TIDAK disentuh), lalu sisip.
    DELETE FROM public.raw_material_components
     WHERE raw_material_id = p_raw_material_id
       AND (variant_id IS NULL OR variant_id = p_variant_id);

    INSERT INTO public.raw_material_components
        (raw_material_id, variant_id, inci_name, cas_number, "function",
         percent_internal, is_bahan_aktif)
    SELECT p_raw_material_id,
           p_variant_id,
           btrim(e.item ->> 'inci_name'),
           NULLIF(btrim(COALESCE(e.item ->> 'cas_number', '')), ''),
           NULLIF(btrim(COALESCE(e.item ->> 'function', '')), ''),
           btrim(e.item ->> 'percent_internal')::numeric,
           (e.item ->> 'is_bahan_aktif') = 'true'
      FROM jsonb_array_elements(v_components) AS e(item);

    GET DIAGNOSTICS v_inserted = ROW_COUNT;

    RETURN v_inserted;
END;
$$;

COMMENT ON FUNCTION public.replace_raw_material_components(uuid, uuid, jsonb) IS
    'Ganti komponen INCI sebuah bahan baku dalam satu transaksi. '
    'p_components = array JSON [{inci_name, cas_number, function, '
    'percent_internal, is_bahan_aktif}]. Menghapus baris variant NULL dan '
    'varian yang diedit, menyisipkan baris baru; mengembalikan jumlah baris.';

-- --- 2. Hak akses (pola yang sama seperti migrasi 010) -------------------
-- Aplikasi memanggil fungsi ini lewat service role, jadi hanya service_role
-- yang diberi hak EXECUTE.
REVOKE ALL ON FUNCTION public.replace_raw_material_components(uuid, uuid, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.replace_raw_material_components(uuid, uuid, jsonb) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.replace_raw_material_components(uuid, uuid, jsonb) TO service_role;

COMMIT;

-- Minta PostgREST memuat ulang cache skema supaya fungsi langsung bisa
-- dipanggil lewat /rest/v1/rpc/replace_raw_material_components.
NOTIFY pgrst, 'reload schema';

-- --- 3. VERIFIKASI (SELECT saja, tidak mengubah apa pun) ------------------
SELECT p.proname,
       pg_get_function_identity_arguments(p.oid) AS argumen,
       pg_get_function_result(p.oid)              AS hasil,
       p.prosecdef                                 AS security_definer,
       p.proconfig                                 AS search_path,
       p.proacl                                    AS hak_akses
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND p.proname = 'replace_raw_material_components';

SELECT routine_name,
       grantee,
       privilege_type
  FROM information_schema.routine_privileges
 WHERE routine_name = 'replace_raw_material_components'
 ORDER BY grantee, privilege_type;

-- --- 4. REHEARSAL (opsional, SELALU rollback; jangan dijalankan di
--        produksi tanpa prosedur). Contoh memakai bahan baku uji:
-- BEGIN;
-- SELECT public.replace_raw_material_components(
--     '00000000-0000-0000-0000-000000000000'::uuid,
--     NULL,
--     '[{"inci_name": "Aqua", "cas_number": "7732-18-5",
--       "function": "Solvent", "percent_internal": "100.0000",
--       "is_bahan_aktif": false}]'::jsonb
-- );
-- ROLLBACK;
