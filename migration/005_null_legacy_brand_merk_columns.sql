-- 005: bersihkan kolom legacy tabel `brands` (era Hak & Lisensi merk dipisah).
--
-- Konteks: dokumen Hak/Lisensi Merk SEKARANG disimpan di tabel `brand_legal_documents`
-- (kolom `hak_lisensi_merk_file_url`, per brand_id + perusahaan) dan di bucket
-- `legal-documents` dengan nama `brands/hak_lisensi_merk_<brand_id>_<erfi|heka>.pdf`.
-- Kolom `brands.hak_merk_file_url` dan `brands.lisensi_merk_file_url` sudah TIDAK
-- dipakai kode mana pun (0 referensi di app/, 0 view, 0 RLS policy, 0 function) dan
-- isinya stale (mis. link mati `brands/hak_merk_<id>.pdf`).
--
-- Dikosongkan (bukan drop kolom) agar link mati tidak mengganggu pre-check backfill
-- migrasi storage (Fase 5). Idempoten.
--
-- Diterapkan: prod 2026-10-16 (4 baris), staging 2026-10-16 (0 baris).

update brands
set hak_merk_file_url = null,
    lisensi_merk_file_url = null
where hak_merk_file_url is not null
   or lisensi_merk_file_url is not null;
