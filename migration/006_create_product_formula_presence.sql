-- View agregat: daftar produk yang punya minimal satu baris formula (Bab II).
-- Dipakai dashboard (/) untuk checklist kelengkapan DIP sebagai pengganti
-- fetch full-table product_formula_lines, yang bisa dipotong diam-diam
-- oleh batas PostgREST db.max-rows=1000 dan bikin status Bab II salah
-- tampil "Kosong" padahal formulanya sudah diisi.
-- Hasil view = 1 baris per produk, jauh di bawah batas baris PostgREST.
CREATE OR REPLACE VIEW public.product_formula_presence
WITH (security_invoker = true) AS
SELECT DISTINCT product_id
FROM public.product_formula_lines
WHERE product_id IS NOT NULL;

COMMENT ON VIEW public.product_formula_presence IS
    'Distinct product_id yang punya minimal satu baris di product_formula_lines (Bab II terisi).';

REVOKE ALL ON public.product_formula_presence FROM anon, authenticated;
