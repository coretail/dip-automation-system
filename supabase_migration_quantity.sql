-- Jalankan ini di Supabase SQL Editor
alter table raw_material_batches
    add column quantity numeric,
    add column quantity_unit text;
