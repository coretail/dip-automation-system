-- =====================================================================
-- 014_add_raw_material_journal_link.sql
--
-- Menambah kolom `journal_link` (text, nullable, tanpa default) ke
-- public.raw_materials, plus CHECK constraint:
--   journal_link IS NULL
--   OR journal_link ~* '^https?://'   (hanya URL http/https, case-insensitive)
--   AND char_length(journal_link) <= 2048
--
-- Tujuan: form "Tambah/Edit Bahan Baku" di /raw-materials (route
-- app/raw_materials_routes.py) membolehkan pengisian link jurnal/literatur
-- keselamatan untuk tiap bahan baku. Quick-add Formula Builder TIDAK
-- mengirim kolom ini (nilai tetap NULL).
--
-- Nomor 014: 009 sengaja TIDAK dipakai (dicadangkan untuk migrasi lain);
-- 013 adalah migrasi terakhir sebelum ini.
--
-- Backward-compatible: kolom nullable tanpa default dan tanpa backfill, jadi
-- kode lama yang tidak mengirim journal_link tetap bisa menulis
-- raw_materials (nilai NULL). CHECK constraint tidak menolak baris lama
-- (semua journal_link NULL).
--
-- URUTAN WAJIB (pola migrasi 012):
--   1. Jalankan manual di Supabase SQL Editor: STAGING dulu, baca hasil
--      PRE-CHECK (langkah 0) dan POST-CHECK (langkah 2), baru PRODUKSI.
--   2. SQL 014 harus selesai di staging dan produksi SEBELUM merge/deploy
--      kode yang menulis/membaca kolom ini (PR feat/rm-journal-link-field).
--
-- CATATAN: jangan kumpulkan validasi di sisi aplikasi TIDAK menggantikan
-- constraint ini — sisi DB tetap sumber kebenaran (defense-in-depth);
-- app/journal_link.py melakukan normalisasi + reject yang sama di form.
--
-- ROLLBACK (bila diperlukan):
--   ALTER TABLE public.raw_materials DROP CONSTRAINT IF EXISTS raw_materials_journal_link_check;
--   ALTER TABLE public.raw_materials DROP COLUMN IF EXISTS journal_link;
-- =====================================================================

-- ---------------------------------------------------------------------------
-- 0. PRE-CHECK (read-only). Baca hasilnya sebelum lanjut.
-- ---------------------------------------------------------------------------
SELECT count(*) AS total_bahan_baku
FROM public.raw_materials;

-- Kolom belum ada saat pertama dijalankan (tanpa baris = belum ada):
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'raw_materials'
  AND column_name = 'journal_link';

-- Constraint belum ada saat pertama dijalankan (tanpa baris = belum ada):
SELECT conname
FROM pg_constraint c
JOIN pg_namespace n ON n.oid = c.connamespace
WHERE n.nspname = 'public'
  AND c.conname = 'raw_materials_journal_link_check';

-- ---------------------------------------------------------------------------
-- 1. DDL idempotent.
-- ---------------------------------------------------------------------------
ALTER TABLE public.raw_materials
    ADD COLUMN IF NOT EXISTS journal_link text;

ALTER TABLE public.raw_materials
    DROP CONSTRAINT IF EXISTS raw_materials_journal_link_check;

ALTER TABLE public.raw_materials
    ADD CONSTRAINT raw_materials_journal_link_check
    CHECK (journal_link IS NULL
           OR (journal_link ~* '^https?://' AND char_length(journal_link) <= 2048));

-- ---------------------------------------------------------------------------
-- 2. POST-CHECK (read-only). Kolom harus nullable, tanpa default;
--    constraint harus terdaftar.
-- ---------------------------------------------------------------------------
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'raw_materials'
  AND column_name = 'journal_link';

SELECT conname, pg_get_constraintdef(c.oid) AS definisi
FROM pg_constraint c
JOIN pg_namespace n ON n.oid = c.connamespace
WHERE n.nspname = 'public'
  AND c.conname = 'raw_materials_journal_link_check';
