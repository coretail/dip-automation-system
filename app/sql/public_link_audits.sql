-- ============================================================
-- Tabel Audit Akses Public Link DIP (/dip/v/:uuid)
-- Jalankan sekali di Supabase Dashboard -> SQL Editor.
-- Setiap kali link publik dibuka, satu baris disimpan:
--   product_id (produk mana), visited_at (kapan),
--   ip_address (dari mana), user_agent (perangkat/browser apa).
-- ============================================================

create table if not exists public.public_link_audits (
    id          uuid primary key default gen_random_uuid(),
    product_id  uuid not null,
    visited_at  timestamptz not null default now(),
    ip_address  text,
    user_agent  text
);

-- Indeks biar query "link produk X dibuka kapan saja" cepat
create index if not exists idx_public_link_audits_product
    on public.public_link_audits (product_id, visited_at desc);

-- ============================================================
-- Contoh query laporan:
--
--   -- Riwayat pembukaan link per produk (terbaru dulu):
--   select p."nama_produk", a.visited_at, a.ip_address, a.user_agent
--   from public_link_audits a
--   join products p on p.id = a.product_id
--   order by a.visited_at desc;
--
--   -- Jumlah pembukaan link per produk:
--   select p."nama_produk", count(*) as total_buka
--   from public_link_audits a
--   join products p on p.id = a.product_id
--   group by p."nama_produk"
--   order by total_buka desc;
-- ============================================================
