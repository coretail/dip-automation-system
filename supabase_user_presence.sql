-- Presence / status Online-Offline user
-- Jalankan sekali di Supabase SQL Editor (project yang sama dengan DIP).
-- Kolom ini dipakai heartbeat POST /api/presence/heartbeat dan halaman /admin/users.

alter table public.profiles
  add column if not exists last_seen_at timestamptz,
  add column if not exists is_online boolean not null default false;

comment on column public.profiles.last_seen_at is 'Waktu heartbeat / login terakhir (presence)';
comment on column public.profiles.is_online is 'True saat sesi aktif (heartbeat). False saat logout eksplisit.';

create index if not exists idx_profiles_presence
  on public.profiles (is_online, last_seen_at desc);
