-- Product attachments are private, non-DIP supporting documents.
CREATE TABLE IF NOT EXISTS public.product_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES public.products (id) ON DELETE RESTRICT,
    kategori TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER NULL,
    catatan TEXT NULL,
    uploaded_by UUID NULL,
    uploaded_by_name TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT product_attachments_file_size_max CHECK (file_size IS NULL OR file_size <= 10485760)
);

CREATE INDEX IF NOT EXISTS idx_product_attachments_product_created
    ON public.product_attachments (product_id, created_at DESC);

COMMENT ON TABLE public.product_attachments IS 'Private supporting documents attached to products; excluded from DIP.';
COMMENT ON COLUMN public.product_attachments.file_path IS 'Relative path in the private product-attachments bucket.';

CREATE OR REPLACE VIEW public.product_attachment_counts
WITH (security_invoker = true) AS
SELECT product_id, COUNT(*) AS jumlah
FROM public.product_attachments
GROUP BY product_id;

ALTER TABLE public.product_attachments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.product_attachment_counts FROM anon, authenticated;
