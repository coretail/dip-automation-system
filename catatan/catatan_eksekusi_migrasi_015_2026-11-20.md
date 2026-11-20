# Catatan Eksekusi Migration 015 (2026-11-20)

File migrasi: `migration/015_add_profile_invite_status.sql`
SHA-256 file: `6b4a7f9a70168b9ae21fa106c3a8da5c40d5599009b6330d2775e516b225ec0d` (8707 byte)
SHA-256 slice yang dieksekusi (section 1, byte-identik): `19641214dfb60cc1…` (4860 byte, 122 baris)
Byte-identik dengan blok rancangan: **ya** (file ditulis langsung dari blok rancangan).

Otorisasi: pemilik repo menyetujui eksekusi via Supabase Management API.
Mekanisme: `POST /v1/projects/{ref}/database/query`. Token Management API
diekstrak programatik dari konfigurasi MCP dan **tidak pernah** dicetak atau
ditulis ke file. SQL dieksekusi apa adanya (slice byte-identik), tanpa
modifikasi DDL.

## Urutan eksekusi

| # | Fase | Project | Hasil |
|---|------|---------|-------|
| 1 | Pre-check (read-only) | staging | bersih |
| 2 | Schema (section 1) | staging | HTTP 201, `setval=1` |
| 3 | Post-check + probe | staging | **HIJAU** |
| 4 | Pre-check (read-only) | produksi | bersih |
| 5 | Schema (section 1) | produksi | HTTP 201, `setval=1` |
| 6 | Post-check (TANPA probe) | produksi | **HIJAU** |

Staging diverifikasi hijau **sebelum** produksi disentuh.

## Pre-check (sebelum migrasi)

| Metrik | staging | produksi |
|--------|---------|----------|
| total_profiles | 5 | 7 |
| tanpa_username (harus 0) | 0 | 0 |
| dup `lower(full_name)` (harus 0) | 0 | 0 |
| migration 011 `display_name` (harus 1) | 1 | 1 |
| index unik `lower(full_name)` sudah ada | 0 (akan dibuat) | 0 (akan dibuat) |
| max `user-N` | null | null |
| kolom invite sudah ada | 0 | 0 |
| RPC sudah ada | 0 | 0 |
| sequence sudah ada | 0 | 0 |

FK `profiles_id_fkey` → `auth.users(id)` berstatus **ON DELETE CASCADE**
(`confdeltype='c'`) di kedua environment.

## Post-check

| Pemeriksaan | staging | produksi |
|-------------|---------|----------|
| distribusi `status` | active=5 | active=7 (semua `active`) |
| kolom `status` | text NOT NULL default `'active'` | sama |
| `invited_at` / `invited_by` / `invited_email` | ada (nullable) | sama |
| CHECK `profiles_status_check` | `status IN ('pending','active')` | sama |
| index `idx_profiles_full_name_lower_unique` | ada (unique) | ada (unique) |
| index `idx_profiles_invited_email_pending_unique` | ada (partial unique) | ada |
| sequence `last_value` / `is_called` | 1 / false → invite-1 = `user-1` | 1 / false → invite-1 = `user-1` |
| RPC `next_invite_username()` | SECURITY DEFINER, ACL `{postgres, service_role}` | sama |
| RPC `auth_email_exists(text)` | SECURITY DEFINER, ACL `{postgres, service_role}` | sama |
| PostgREST ekspos RPC | ya | ya (`/rpc/next_invite_username`, `/rpc/auth_email_exists`) |
| panggilan nyata `auth_email_exists` | `false` (benar) | HTTP 200 `false` (benar) |

### Probe yang dijalankan

- `SELECT public.next_invite_username()` → `user-1` — **hanya di staging**.
  Tidak dijalankan di produksi agar sequence produksi tidak maju.
- `SELECT public.auth_email_exists('<email absen>')` → `false` (boolean).
- `next_invite_username()` **tidak** diuji di produksi (sesuai peringatan di file).

## Catatan / sisa

1. **Sequence staging sudah maju 1** karena probe (`is_called` kini true). Invite
   pertama di staging akan menjadi `user-2`. Produksi utuh: invite pertama `user-1`.
2. **Probe insert profil tidak bisa dilakukan** karena FK `profiles_id_fkey`
   mengharuskan `id` ada di `auth.users`. Verifikasi CHECK & partial unique index
   dilakukan secara struktural (`pg_constraint` / `pg_indexes`); verifikasi
   fungsional menyatu dengan E2E Task 3/4.
3. **Tidak ada baris probe yang tertinggal** (blok DO abort sebelum insert kedua;
   `DELETE FROM public.profiles WHERE full_name LIKE 'probe015%'` dijalankan).
4. Tidak ada migration history table yang dipakai (sesuai konvensi repo: SQL
   dieksekusi manual, tanpa entry `supabase_migrations`).
5. `NOTIFY pgrst, 'reload schema'` ikut dieksekusi; terbukti PostgREST langsung
   mengenali kedua RPC.

## Dampak ke task berikutnya

- Task 3 (`POST /admin/users/invite`) sudah bisa dibangun: kolom, sequence,
  kedua RPC, dan kedua index tersedia di produksi.
- Task 3b (cancel-invite): cukup `admin.delete_user(uid)`; baris `profiles`
  terhapus otomatis (CASCADE). `activity_logs.actor_id` tetap `ON DELETE SET NULL`
  sehingga audit tidak hilang.
- Task 4: token aktivasi final menunggu retest spike v2 (lihat catatan spike).
- Task 5/6: kolom `status` sudah ada; retry fail-soft tetap diperlukan untuk
  kompatibilitas bila rollback.
