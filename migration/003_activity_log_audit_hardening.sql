-- =====================================================================
-- 003_activity_log_audit_hardening.sql
--
-- Menambah konteks request & verdict ke activity_logs yang sudah ada,
-- tanpa mengubah baris lama (1.109 baris, 2026-08-10 s/d 2026-10-05).
-- Script ini IDEMPOTENT dan AMAN dijalankan berulang.
--
-- Latar belakang: 7 operasi berisiko tinggi (buat/hapus user, tambah merk,
-- upload dokumen merk, create/edit/delete FSP) sebelumnya tidak tercatat
-- sama sekali di audit trail.
--
-- Cara pakai: Supabase SQL Editor, jalankan sekali (aman diulang).
-- =====================================================================

BEGIN;

-- --- 1. Kolom konteks request & verdict -----------------------------
ALTER TABLE public.activity_logs
    ADD COLUMN IF NOT EXISTS ip_address   INET,
    ADD COLUMN IF NOT EXISTS user_agent   TEXT,
    ADD COLUMN IF NOT EXISTS route        TEXT,
    ADD COLUMN IF NOT EXISTS http_method  TEXT,
    ADD COLUMN IF NOT EXISTS request_id   TEXT,
    ADD COLUMN IF NOT EXISTS outcome      TEXT   NOT NULL DEFAULT 'success',
    ADD COLUMN IF NOT EXISTS source       TEXT   NOT NULL DEFAULT 'app';

COMMENT ON COLUMN public.activity_logs.ip_address  IS 'IP klien. Diisi di level request: X-Forwarded-For -> X-Real-IP -> request.client.host.';
COMMENT ON COLUMN public.activity_logs.user_agent  IS 'User-Agent browser, dipotong 500 karakter.';
COMMENT ON COLUMN public.activity_logs.route       IS 'Template route FastAPI (bukan URL konkret), supaya bisa dikelompokkan tanpa cardinality meledak.';
COMMENT ON COLUMN public.activity_logs.request_id  IS 'UUID v4 per request, dipakai bersama oleh semua baris log yang berasal dari satu request.';
COMMENT ON COLUMN public.activity_logs.outcome     IS 'success | rejected | failed. rejected = operasi ditolak validasi/role; failed = exception.';
COMMENT ON COLUMN public.activity_logs.source      IS 'app | public | migration. app = route internal; public = /dip/{slug} tanpa login.';

-- --- 2. Backfill baris lama ------------------------------------------
-- Semua baris lama dicatat oleh aplikasi, jadi default-nya success/app.
UPDATE public.activity_logs
   SET outcome = 'success' WHERE outcome IS NULL;
UPDATE public.activity_logs
   SET source  = 'app'      WHERE source  IS NULL;

-- --- 3. Jaring pengaman created_at -----------------------------------
-- Default now() sudah ada; yang hilang hanya NOT NULL.
-- Ditemukan 0 baris created_at NULL, jadi backfill di bawah tidak mengubah data.
UPDATE public.activity_logs
   SET created_at = now() WHERE created_at IS NULL;

ALTER TABLE public.activity_logs
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL;

-- --- 4. Batasan nilai ------------------------------------------------
ALTER TABLE public.activity_logs
    DROP CONSTRAINT IF EXISTS activity_logs_outcome_check;
ALTER TABLE public.activity_logs
    ADD CONSTRAINT activity_logs_outcome_check
    CHECK (outcome IN ('success', 'rejected', 'failed'));

ALTER TABLE public.activity_logs
    DROP CONSTRAINT IF EXISTS activity_logs_source_check;
ALTER TABLE public.activity_logs
    ADD CONSTRAINT activity_logs_source_check
    CHECK (source IN ('app', 'public', 'migration'));

-- --- 5. Index untuk investigasi --------------------------------------
-- Kolom yang paling sering dipakai saat menelusuri jejak audit.
-- Sebelumnya tabel ini HANYA punya primary key.
CREATE INDEX IF NOT EXISTS idx_activity_logs_created_at
    ON public.activity_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_logs_actor
    ON public.activity_logs (actor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_logs_entity
    ON public.activity_logs (entity_type, entity_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_logs_action
    ON public.activity_logs (action, created_at DESC);

-- --- 6. Cegah penulisan/penghapusan dari klien -----------------------
-- Semua akses aplikasi lewat service role (RLS dilewati). REVOKE menutup
-- jalur PostgREST non-service-role dan anon key yang bocor.
REVOKE ALL ON public.activity_logs FROM anon, authenticated;

GRANT SELECT, INSERT ON public.activity_logs TO service_role;

-- --- 7. Perbaiki FK actor_id: NO ACTION -> SET NULL --------------------
-- activity_logs.actor_id sebelumnya punya FK ke profiles(id) dengan ON DELETE
-- NO ACTION. Akibatnya DELETE FROM profiles gagal untuk setiap user yang punya
-- minimal satu baris activity_logs -- saat ini 6 user (paling banyak 523 baris).
-- Jadi POST /admin/users/delete sudah rusak untuk user-user tersebut sejak lama.
--
-- Fix: ON DELETE SET NULL. Baris audit TETAP ADA (riwayat tidak ikut terhapus),
-- hanya actor_id-nya jadi NULL. Identitas pelakunya tetap tersimpan di kolom
-- tekstual actor_name yang memang sudah didesain denormalisasi untuk ini.
ALTER TABLE public.activity_logs
    DROP CONSTRAINT IF EXISTS activity_logs_actor_id_fkey;

ALTER TABLE public.activity_logs
    ADD CONSTRAINT activity_logs_actor_id_fkey
    FOREIGN KEY (actor_id) REFERENCES profiles(id) ON DELETE SET NULL;

COMMENT ON COLUMN public.activity_logs.actor_id IS 'Pelaku. NULL bila akun pelakunya sudah dihapus, atau bila aksi dilakukan sistem/non-login. Nama pelakunya tetap ada di actor_name.';

COMMIT;