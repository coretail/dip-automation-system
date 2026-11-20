-- 015_add_profile_invite_status.sql
-- Status undangan (pending/active), invited_at, invited_by, invited_email
-- + SEQUENCE & RPC next_invite_username().
-- URUTAN WAJIB: STAGING dulu (baca pre/post-check) → PRODUKSI → baru deploy kode.

-- ---------------------------------------------------------------------------
-- 0. PRE-CHECK (read-only). Baca hasilnya sebelum lanjut.
-- ---------------------------------------------------------------------------
SELECT count(*) AS total_profiles,
       count(*) FILTER (WHERE btrim(coalesce(full_name,'')) = '') AS tanpa_username
FROM public.profiles;

-- 0b. Duplikat username case-insensitive? (harus 0 baris, kalau tidak 015 akan abort)
SELECT lower(full_name) AS username, count(*) AS n, array_agg(id) AS ids
FROM public.profiles
WHERE full_name IS NOT NULL
GROUP BY lower(full_name) HAVING count(*) > 1;

-- 0c. Migration 011 sudah jalan? (harus 1 baris)
SELECT column_name FROM information_schema.columns
WHERE table_schema='public' AND table_name='profiles' AND column_name='display_name';

-- 0d. Index unik lower(full_name) yang SUDAH ada (nama apa pun)
SELECT indexname, indexdef FROM pg_indexes
WHERE schemaname='public' AND tablename='profiles'
  AND indexdef ILIKE '%unique%' AND indexdef ILIKE '%lower%full_name%';

-- 0e. FK profiles.id → auth.users: cascade atau tidak? (menentukan urutan cancel-invite)
SELECT conname, confdeltype FROM pg_constraint
WHERE conrelid='public.profiles'::regclass AND contype='f';
-- confdeltype: 'c' = CASCADE, 'a' = NO ACTION, 'n' = SET NULL

-- 0f. Username user-N yang sudah terpakai (untuk setval)
SELECT max((substring(full_name from '^user-(\d+)$'))::bigint) AS n_terbesar
FROM public.profiles WHERE full_name ~ '^user-\d+$';

-- ---------------------------------------------------------------------------
-- 1. PERUBAHAN SKEMA (satu transaksi, fail-closed)
-- ---------------------------------------------------------------------------
BEGIN;

-- 1a. GUARD: abort bila prasyarat tidak terpenuhi (bukan sekadar komentar)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='profiles' AND column_name='display_name'
    ) THEN
        RAISE EXCEPTION 'ABORT 015: migration 011 (display_name) belum dijalankan.';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.profiles WHERE full_name IS NOT NULL
        GROUP BY lower(full_name) HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'ABORT 015: ada duplikat lower(full_name). Bersihkan dulu (lihat pre-check 0b).';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.profiles
        WHERE btrim(coalesce(full_name, '')) = ''
    ) THEN
        RAISE EXCEPTION 'ABORT 015: ada full_name kosong. Bersihkan dulu (lihat pre-check 0a).';
    END IF;
END $$;

-- 1b. Kolom baru
ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS status        text DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS invited_at    timestamptz,
    ADD COLUMN IF NOT EXISTS invited_by    uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS invited_email text;

COMMENT ON COLUMN public.profiles.status        IS 'active | pending (menunggu aktivasi undangan).';
COMMENT ON COLUMN public.profiles.invited_at    IS 'Waktu undangan terakhir dikirim; jejak audit, tidak di-NULL-kan.';
COMMENT ON COLUMN public.profiles.invited_by    IS 'Admin pengundang; SET NULL bila admin dihapus.';
COMMENT ON COLUMN public.profiles.invited_email IS 'Email tujuan undangan (untuk resend & tampilan admin).';

-- 1c. CHECK status
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname='profiles_status_check' AND conrelid='public.profiles'::regclass) THEN
        ALTER TABLE public.profiles ADD CONSTRAINT profiles_status_check
            CHECK (status IN ('pending','active'));
    END IF;
END $$;

-- 1d. Backfill + NOT NULL
UPDATE public.profiles SET status='active' WHERE status IS NULL;
ALTER TABLE public.profiles ALTER COLUMN status SET NOT NULL;

-- 1e. Cegah undangan pending ganda untuk alamat email yang sama (case-insensitive)
CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_invited_email_pending_unique
    ON public.profiles (lower(invited_email))
    WHERE status = 'pending' AND invited_email IS NOT NULL;

-- 1f. Index unik lower(full_name): hanya bila belum ada index unik setara (nama apa pun)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname='public' AND tablename='profiles'
          AND indexdef ILIKE '%unique%' AND indexdef ILIKE '%lower%full_name%'
    ) THEN
        CREATE UNIQUE INDEX idx_profiles_full_name_lower_unique
            ON public.profiles (lower(full_name));
        RAISE NOTICE '015: index unik lower(full_name) DIBUAT oleh migrasi ini.';
    ELSE
        RAISE NOTICE '015: index unik lower(full_name) sudah ada — dilewati (rollback tidak boleh menghapusnya).';
    END IF;
END $$;

-- 1g. SEQUENCE + sinkronisasi dengan username yang sudah ada
CREATE SEQUENCE IF NOT EXISTS public.profiles_username_seq
    START WITH 1 INCREMENT BY 1 NO CYCLE;

SELECT setval('public.profiles_username_seq',
    COALESCE((SELECT max((substring(full_name from '^user-(\d+)$'))::bigint)
              FROM public.profiles WHERE full_name ~ '^user-\d+$'), 0) + 1,
    false);

-- 1h. RPC username
CREATE OR REPLACE FUNCTION public.next_invite_username()
RETURNS text
LANGUAGE sql
SECURITY DEFINER
SET search_path = 'public', 'pg_temp'
AS $$ SELECT 'user-' || nextval('public.profiles_username_seq'); $$;

REVOKE EXECUTE ON FUNCTION public.next_invite_username() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.next_invite_username() FROM anon;
REVOKE EXECUTE ON FUNCTION public.next_invite_username() FROM authenticated;
GRANT  EXECUTE ON FUNCTION public.next_invite_username() TO service_role;

-- 1i. Pengecekan email Auth tanpa pagination admin.list_users().
CREATE OR REPLACE FUNCTION public.auth_email_exists(p_email text)
RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
SET search_path = 'public', 'auth', 'pg_temp'
AS $$
    SELECT EXISTS (
        SELECT 1 FROM auth.users
        WHERE lower(email) = lower(btrim(p_email))
    );
$$;

REVOKE EXECUTE ON FUNCTION public.auth_email_exists(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.auth_email_exists(text) FROM anon;
REVOKE EXECUTE ON FUNCTION public.auth_email_exists(text) FROM authenticated;
GRANT  EXECUTE ON FUNCTION public.auth_email_exists(text) TO service_role;

COMMIT;

-- 1j. Reload schema cache PostgREST (tanpa ini RPC bisa 404)
NOTIFY pgrst, 'reload schema';

-- ---------------------------------------------------------------------------
-- 2. POST-CHECK
-- ---------------------------------------------------------------------------
SELECT status, count(*) FROM public.profiles GROUP BY status;         -- semua 'active'
SELECT last_value, is_called FROM public.profiles_username_seq;       -- > n_terbesar
-- Jangan jalankan probe RPC ini di produksi: ia memajukan sequence 1 angka,
-- sehingga undangan pertama akan menjadi user-2. Di produksi cukup cek last_value/is_called di atas.
SELECT public.next_invite_username();                                 -- probe hanya di staging; memajukan sequence 1 angka
SELECT indexname FROM pg_indexes
WHERE schemaname='public' AND tablename='profiles'
  AND indexdef ILIKE '%unique%' AND indexdef ILIKE '%lower%full_name%';
SELECT indexname FROM pg_indexes
WHERE schemaname='public' AND indexname='idx_profiles_invited_email_pending_unique';
SELECT proname, proacl FROM pg_proc
WHERE proname IN ('next_invite_username', 'auth_email_exists');

-- ---------------------------------------------------------------------------
-- 3. ROLLBACK (hati-hati: JANGAN hapus index yang sudah ada sebelum 015)
-- ---------------------------------------------------------------------------
-- BEGIN;
-- -- Pending yang belum aktif akan kehilangan penanda; daftar dulu:
-- -- SELECT id, full_name, invited_email, invited_at FROM public.profiles WHERE status='pending';
-- DROP INDEX IF EXISTS idx_profiles_invited_email_pending_unique;
-- ALTER TABLE public.profiles
--     DROP CONSTRAINT IF EXISTS profiles_status_check,
--     DROP COLUMN IF EXISTS status,
--     DROP COLUMN IF EXISTS invited_at,
--     DROP COLUMN IF EXISTS invited_by,
--     DROP COLUMN IF EXISTS invited_email;
-- DROP FUNCTION IF EXISTS public.auth_email_exists(text);
-- DROP FUNCTION IF EXISTS public.next_invite_username();
-- DROP SEQUENCE IF EXISTS public.profiles_username_seq;
-- -- Index: hapus HANYA bila NOTICE 1e menyatakan "DIBUAT oleh migrasi ini".
-- -- DROP INDEX IF EXISTS idx_profiles_full_name_lower_unique;
-- COMMIT;
-- NOTIFY pgrst, 'reload schema';
