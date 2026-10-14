-- Migration: Purchase Orders (PO) produksi dari spreadsheet batch
-- Source decisions: d:\dip-app\catatan_batch_plan.md Bagian 18 (LOCKED 2026-09-23)
-- Safety:
--   - Tidak menyentuh tabel existing (products, product_batches, dll).
--   - Tabel baru berdiri sendiri, FK ke products / product_batches dengan ON DELETE RESTRICT.
--   - Idempotent: UNIQUE(no_po) dan UNIQUE(purchase_order_id, urutan).
-- Cara pakai (di Supabase SQL Editor, jalankan sekali):
--   1. Review file ini.
--   2. Jalankan seluruh statement.
--   3. Verifikasi via dry-run migrate_po.py sebelum EXECUTE.

-- ============================================================
-- 1. purchase_orders
-- Identitas PO = no_po (keputusan #4).
-- Satu No. PO dapat mencakup banyak item/batch (merged cell, forward-fill).
-- ============================================================
CREATE TABLE IF NOT EXISTS public.purchase_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    no_po TEXT NOT NULL,
    tanggal_po DATE NULL,
    qty_pcs NUMERIC NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT purchase_orders_no_po_unique UNIQUE (no_po)
);

COMMENT ON TABLE public.purchase_orders IS 'Header PO produksi dari migrasi spreadsheet batch. no_po unik.';
COMMENT ON COLUMN public.purchase_orders.no_po IS 'Identitas PO (keputusan #4). Contoh: 203/PO-ERFI/VII/26';
COMMENT ON COLUMN public.purchase_orders.tanggal_po IS 'Tgl PO (kolom A). Diambil dari baris header PO pertama untuk no_po tersebut.';
COMMENT ON COLUMN public.purchase_orders.qty_pcs IS 'Qty (Pcs) kolom C pada baris header PO. NULL jika tidak konsisten antar baris lanjutan.';

CREATE INDEX IF NOT EXISTS idx_purchase_orders_no_po
    ON public.purchase_orders (no_po);

-- ============================================================
-- 2. purchase_order_items
-- Identitas item = purchase_order_id + urutan (keputusan #4).
-- Satu item = satu baris batch spreadsheet (satu no_batch).
-- product_id HANYA dari match products.no_na_produk (keputusan #2, #3).
-- product_batch_id FK ke product_batches.id (keputusan #5).
-- Revisi Produksi & Temporary Reject NULLABLE (keputusan #7).
-- Angka Indonesia: koma = desimal (keputusan #8), disimpan NUMERIC.
-- ============================================================
CREATE TABLE IF NOT EXISTS public.purchase_order_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    purchase_order_id UUID NOT NULL
        REFERENCES public.purchase_orders (id) ON DELETE RESTRICT,
    product_id UUID NOT NULL
        REFERENCES public.products (id) ON DELETE RESTRICT,
    product_batch_id UUID NOT NULL
        REFERENCES public.product_batches (id) ON DELETE RESTRICT,
    urutan INTEGER NOT NULL,
    tanggal_catatan_batch DATE NULL,
    wip NUMERIC NULL,
    netto TEXT NULL,
    qty_kg NUMERIC NULL,
    keterangan TEXT NULL,
    qty_belum_sop NUMERIC NULL,
    qty_po_kg NUMERIC NULL,
    status_bpom TEXT NULL,
    catatan_produksi TEXT NULL,
    revisi_produksi TEXT NULL,
    temporary_reject TEXT NULL,
    excel_row INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT purchase_order_items_po_urutan_unique UNIQUE (purchase_order_id, urutan)
);

COMMENT ON TABLE public.purchase_order_items IS 'Item/batch PO. Satu baris = satu batch. Idempotent via (purchase_order_id, urutan).';
COMMENT ON COLUMN public.purchase_order_items.urutan IS 'Kolom E Urutan. Bagian identitas item bersama purchase_order_id.';
COMMENT ON COLUMN public.purchase_order_items.product_batch_id IS 'FK ke product_batches.id (keputusan #5). Batch dibuat dulu bila belum ada.';
COMMENT ON COLUMN public.purchase_order_items.excel_row IS 'Nomor baris Excel sumber untuk audit/repro. Bukan kunci.';

CREATE INDEX IF NOT EXISTS idx_po_items_po_id
    ON public.purchase_order_items (purchase_order_id);
CREATE INDEX IF NOT EXISTS idx_po_items_product_id
    ON public.purchase_order_items (product_id);
CREATE INDEX IF NOT EXISTS idx_po_items_batch_id
    ON public.purchase_order_items (product_batch_id);
