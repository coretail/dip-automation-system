-- 007_add_public_access_capability.sql
-- Menambahkan lapisan capability terpisah dari UUID produk untuk akses publik /dip/.
-- Backward-compatible: kolom token boleh NULL (mode legacy tetap diizinkan).

ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS public_access_enabled boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS public_access_token text,
    ADD COLUMN IF NOT EXISTS public_access_revoked_at timestamptz,
    ADD COLUMN IF NOT EXISTS bpom_registered_link boolean NOT NULL DEFAULT false;

-- Token acak untuk produk yang belum punya token (produk baru nanti generate di app).
-- Produk lama tetap bisa diakses lewat mode legacy sampai migrasi link dilakukan.
UPDATE public.products
SET public_access_token = encode(gen_random_bytes(24), 'hex')
WHERE public_access_token IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS products_public_access_token_key
    ON public.products (public_access_token)
    WHERE public_access_token IS NOT NULL;
