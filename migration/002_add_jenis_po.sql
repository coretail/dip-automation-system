-- Migration: kolom jenis_po pada purchase_orders (penandaan PO jenis "Rework")
-- Keputusan user 2 Okt 2026: "untuk PO rework buat tag baru yang menandakan
--   bahwa PO tersebut berjenis Rework".
-- Sifat migrasi:
--   - Hanya menambah SATU kolom nullable. Kolom yang sudah ada tidak diubah.
--   - Tanpa DEFAULT, jadi INSERT dari form PO di app tetap berfungsi tanpa
--     perlu mengubah kode.
--   - Query yang sudah ada di app/po_routes.py memakai select("id, no_po,
--     tanggal_po, qty_pcs") secara eksplisit, jadi menambah kolom ini tidak
--     mengubah hasil query mana pun.
--   - Idempotent: aman dijalankan berkali-kali.
--
-- Cara pakai (di Supabase SQL Editor, jalankan sekali):
--   1. Jalankan seluruh statement di bawah.
--   2. Cek dulu : python migration\tag_rework_po.py --dry-run
--   3. Terapkan : python migration\tag_rework_po.py --execute --yes
--
-- Nilai yang diizinkan pada jenis_po:
--   NULL        -> PO biasa (nilai default semua PO yang ada sekarang)
--   'Rework'    -> PO untuk produksi ulang: rework innerbox, shrink, atau
--                  pencampuran ulang sisa bulk.

ALTER TABLE public.purchase_orders
    ADD COLUMN IF NOT EXISTS jenis_po TEXT NULL;

COMMENT ON COLUMN public.purchase_orders.jenis_po IS
    'Jenis PO. NULL = PO biasa. Rework = produksi ulang / rework innerbox, shrink, atau pencampuran ulang.';

-- ============================================================
-- Verifikasi, jalankan setelah ALTER TABLE
-- ============================================================
-- SELECT jenis_po, count(*) AS jml FROM public.purchase_orders GROUP BY jenis_po;
-- SELECT no_po, jenis_po FROM public.purchase_orders WHERE jenis_po IS NOT NULL;