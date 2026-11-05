-- 012_add_batch_mengetahui_signer.sql
-- Menambah kolom penandatangan ke-3 "Mengetahui (Kepala QC)" pada
-- public.raw_material_batches (catatan pemeriksaan bahan baku).
--
-- Backward-compatible: kolom nullable tanpa default, tanpa backfill, jadi kode
-- yang tidak mengirim nilai ini tetap bisa menyimpan batch (nilai NULL).
--
-- URUTAN WAJIB:
--   1. Jalankan manual di Supabase SQL Editor: STAGING dulu, baca hasil pre-check
--      dan post-check, baru PRODUKSI.
--   2. Baru deploy kode yang menulis/membaca kolom ini. Urutan deploy:
--      (1) SQL di staging → verifikasi, (2) deploy kode ke staging,
--      (3) ulangi di produksi.
--
-- ROLLBACK (bila diperlukan): ALTER TABLE public.raw_material_batches DROP COLUMN IF EXISTS mengetahui_signer;

-- ---------------------------------------------------------------------------
-- 0. PRE-CHECK (read-only). Baca hasilnya sebelum lanjut.
-- ---------------------------------------------------------------------------
SELECT count(*) AS total_batches,
       count(*) FILTER (WHERE mengetahui_signer IS NOT NULL) AS sudah_terisi
FROM public.raw_material_batches;

-- ---------------------------------------------------------------------------
-- 1. ALTER TABLE idempotent (ADD COLUMN IF NOT EXISTS).
-- ---------------------------------------------------------------------------
ALTER TABLE public.raw_material_batches
    ADD COLUMN IF NOT EXISTS mengetahui_signer text;

-- ---------------------------------------------------------------------------
-- 2. POST-CHECK (read-only). Kolom harus nullable, tanpa default.
-- ---------------------------------------------------------------------------
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'raw_material_batches'
  AND column_name = 'mengetahui_signer';
