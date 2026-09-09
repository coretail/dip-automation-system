-- Team Notes + @mention
-- Jalankan sekali di Supabase SQL Editor.

create table if not exists public.team_notes (
  id uuid primary key default gen_random_uuid(),
  author_id uuid not null references public.profiles(id) on delete cascade,
  author_name text not null,
  body text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.team_note_mentions (
  id uuid primary key default gen_random_uuid(),
  note_id uuid not null references public.team_notes(id) on delete cascade,
  mentioned_user_id uuid not null references public.profiles(id) on delete cascade,
  mentioned_username text not null,
  is_read boolean not null default false,
  created_at timestamptz not null default now()
);

create index if not exists idx_team_notes_created on public.team_notes (created_at desc);
create index if not exists idx_team_note_mentions_user on public.team_note_mentions (mentioned_user_id, is_read);
create index if not exists idx_team_note_mentions_note on public.team_note_mentions (note_id);

comment on table public.team_notes is 'Catatan singkat antar anggota tim; body boleh mengandung @username';
comment on table public.team_note_mentions is 'Relasi note → user yang di-tag via @mention';
