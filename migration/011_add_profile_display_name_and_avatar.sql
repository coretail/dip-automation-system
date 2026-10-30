-- 011_add_profile_display_name_and_avatar.sql
-- Menambah kolom nama tampilan (display_name) dan foto profil (avatar_path,
-- avatar_updated_at) pada public.profiles.
--
-- Backward-compatible: semua kolom baru boleh NULL tanpa default, jadi kode lama
-- tetap berjalan. full_name TIDAK diubah: tetap menjadi username login dan label
-- audit (activity_logs.actor_name, uploaded_by_name, dst).
--
-- URUTAN WAJIB:
--   1. Jalankan manual di Supabase SQL Editor: STAGING dulu, baca hasil pre-check
--      dan post-check, baru PRODUKSI.
--   2. Baru deploy kode yang membaca kolom ini. get_current_user memilih kolom
--      profil secara eksplisit; kode yang meminta display_name sebelum kolomnya
--      ada akan membuat semua request gagal 401.
--
-- Catatan avatar: avatar_path menyimpan KUNCI objek (path di dalam bucket), bukan
-- URL penuh, supaya tidak bergantung pada host penyimpanan (Supabase/R2) dan tidak
-- perlu backfill URL saat backend berpindah. Bucket dan cara menyajikan fotonya
-- (public URL atau signed URL) diputuskan saat fitur foto dibuat.

-- ---------------------------------------------------------------------------
-- 0. PRE-CHECK (read-only). Baca hasilnya sebelum lanjut.
-- ---------------------------------------------------------------------------
SELECT count(*)                                                   AS total_profiles,
       count(*) FILTER (WHERE btrim(coalesce(full_name, '')) = '') AS tanpa_username,
       max(char_length(btrim(coalesce(full_name, ''))))           AS username_terpanjang
FROM public.profiles;

SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'profiles'
  AND column_name IN ('display_name', 'avatar_path', 'avatar_updated_at');
-- Harapan: 0 baris pada eksekusi pertama (kolom belum ada).

-- ---------------------------------------------------------------------------
-- 1. PERUBAHAN SKEMA + BACKFILL (satu transaksi)
-- ---------------------------------------------------------------------------
BEGIN;

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS display_name      text,
    ADD COLUMN IF NOT EXISTS avatar_path       text,
    ADD COLUMN IF NOT EXISTS avatar_updated_at timestamptz;

COMMENT ON COLUMN public.profiles.display_name IS
    'Nama yang ditampilkan di UI. NULL = pakai full_name (username). Bukan identitas login/audit.';
COMMENT ON COLUMN public.profiles.avatar_path IS
    'Kunci objek foto profil di dalam bucket (bukan URL). NULL = belum ada foto.';
COMMENT ON COLUMN public.profiles.avatar_updated_at IS
    'Waktu foto profil terakhir diganti (untuk cache-busting URL publik).';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'profiles_display_name_len_check'
          AND conrelid = 'public.profiles'::regclass
    ) THEN
        ALTER TABLE public.profiles
            ADD CONSTRAINT profiles_display_name_len_check
            CHECK (display_name IS NULL
                   OR char_length(btrim(display_name)) BETWEEN 1 AND 60);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'profiles_avatar_path_check'
          AND conrelid = 'public.profiles'::regclass
    ) THEN
        -- Tanpa spasi (menghindari masalah encoding %20 seperti temuan E-05),
        -- tanpa awalan "/", tanpa segmen "..", dan panjang wajar.
        ALTER TABLE public.profiles
            ADD CONSTRAINT profiles_avatar_path_check
            CHECK (avatar_path IS NULL
                   OR (char_length(avatar_path) BETWEEN 1 AND 300
                       AND avatar_path !~ '\s'
                       AND avatar_path !~ '^/'
                       AND avatar_path !~ '(^|/)\.\.(/|$)'));
    END IF;
END $$;

-- Backfill: akun yang sudah ada mendapat display_name = username (dipotong 60
-- karakter agar lolos constraint). Hanya baris yang masih NULL; aman dijalankan ulang.
UPDATE public.profiles
SET display_name = left(btrim(full_name), 60)
WHERE display_name IS NULL
  AND btrim(coalesce(full_name, '')) <> '';

COMMIT;

-- ---------------------------------------------------------------------------
-- 2. POST-CHECK (read-only)
-- ---------------------------------------------------------------------------
SELECT count(*)                                              AS total_profiles,
       count(display_name)                                   AS display_name_terisi,
       count(*) FILTER (WHERE display_name IS NULL)          AS display_name_kosong,
       count(avatar_path)                                    AS avatar_terisi
FROM public.profiles;
-- Harapan: display_name_terisi = total_profiles - tanpa_username (pre-check),
--          avatar_terisi = 0.

SELECT conname
FROM pg_constraint
WHERE conrelid = 'public.profiles'::regclass
  AND conname IN ('profiles_display_name_len_check', 'profiles_avatar_path_check');
-- Harapan: 2 baris.

-- ---------------------------------------------------------------------------
-- ROLLBACK (hanya bila benar-benar perlu; kolom nullable tidak mengganggu kode lama,
-- jadi biasanya cukup rollback kode saja). PERINGATAN: menghapus data kolom.
-- ---------------------------------------------------------------------------
-- BEGIN;
-- ALTER TABLE public.profiles
--     DROP CONSTRAINT IF EXISTS profiles_display_name_len_check,
--     DROP CONSTRAINT IF EXISTS profiles_avatar_path_check,
--     DROP COLUMN IF EXISTS display_name,
--     DROP COLUMN IF EXISTS avatar_path,
--     DROP COLUMN IF EXISTS avatar_updated_at;
-- COMMIT;
