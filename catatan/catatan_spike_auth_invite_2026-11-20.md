# Catatan Spike Supabase Auth — v1 (2026-11-20) dan Retest v2 (2026-11-20)

## Ringkasan

Dua putaran spike pada Supabase Auth (`supabase==2.31.0`) di staging untuk
memverifikasi perilaku `generate_link(type="invite")` dan `verify_otp` sebelum
implementasi fitur undang user via email.

- **v1** (skrip sementara di `.kilo/`): eksplorasi awal. Sebagian kesimpulannya
  **keliru** karena dua cacat metodologi — parameter `verify_otp` yang salah dan
  client global yang sudah memegang session user.
- **v2** (`.kilo/_spike_auth_invite_v2.py`): retest dengan isolasi client ketat
  dan parameter yang benar. **Inilah sumber kebenaran.**

Skrip spike bersifat sementara dan **tidak** disimpan di repo (hanya di `.kilo/`,
git-ignored). Dijalankan di bawah guard staging fail-closed
(`check_shell_clean` + `validate_staging_file`), target host staging eksak.
Seluruh akun uji dibuat lalu dihapus; pemeriksaan akhir: **tidak ada akun
tersisa**. Tidak ada email yang dikirim oleh spike (`generate_link` hanya
menghasilkan link + token). Tidak ada secret, token, password, atau kredensial
yang dicetak.

## Hasil Spike v2 (FINAL)

| Skenario | Langkah | Hasil | Fakta non-rahasia |
|---|---|---|---|
| R1 | `verify_otp({"token_hash", "type":"invite"})` | **OK** | `session` + `user` ada; `email_confirmed_at` terisi |
| R1 | `auth.update_user({"password"})` pada client verifikasi yang sama | **OK** | client V menyimpan session di memori |
| R1 | `sign_in_with_password` pada client baru | **OK** | `session` terbentuk |
| R2 | `verify_otp({"token_hash", "type":"invite"})` | **OK** | — |
| R2 | `admin.update_user_by_id(uid, {"password"})` | **OK** | client admin tetap bersih |
| R2 | `sign_in_with_password` pada client baru | **OK** | `session` terbentuk |
| R3 | `admin.update_user_by_id(uid, {"password"})` **sebelum** verify | **OK** | set password memang diizinkan |
| R3 | `verify_otp({"token_hash"})` sesudahnya | **GAGAL** | `Email link is invalid or has expired` — token undangan mati |
| R3 | `sign_in_with_password` | **GAGAL** | `Email not confirmed` |
| R4 | `verify_otp(token_hash)` ke-1 | **OK** | `session` terbentuk |
| R4 | `verify_otp(token_hash)` ke-2 (token sama) | **GAGAL** | `Email link is invalid or has expired` — sekali pakai |
| R5 | `verify_otp({"email", "token": email_otp, "type":"email"})` | **OK** | `email_confirmed_at` terisi |
| R5 | `generate_link` kedua untuk email yang sama | **GAGAL** | `already been registered` — kasus "tanpa email" tidak teruji |
| R6 | `generate_link` #1 | **OK** | token A |
| R6 | `generate_link` #2 (user masih pending) | **OK** | user sama, token B **berbeda** |
| R6 | `verify_otp(token_hash = A)` | **GAGAL** | token lama tidak berlaku |
| R6 | `verify_otp(token_hash = B)` | **OK** | `email_confirmed_at` terisi |
| R7 | `generate_link(invite)` untuk user yang sudah confirmed | **GAGAL** | `already been registered` |

Catatan tambahan:

- Setiap `admin.get_user_by_id(uid)` yang dijalankan **setelah** tiap `verify_otp`
  mengembalikan **OK** — membuktikan client admin (service role) tidak pernah
  terkontaminasi session user, selama verify/sign-in memakai client baru terpisah.
- Kegagalan `User not allowed` pada v1 **murni** akibat session user bocor ke
  client global (efek `verify_otp` pada client yang sama), bukan perilaku Auth.

## Klaim v1 -> status v2

| Klaim v1 | Status v2 | Penjelasan |
|---|---|---|
| **S1.2** — "token invite tidak bisa di-verify" | **SALAH (salah parameter)** | v1 memakai parameter `token`; dengan **`token_hash`** verify **berhasil** (R1). |
| **S2.2** — token lama tidak berlaku setelah `generate_link` ke-2 | **BENAR** | R6: token A mati, token B hidup. |
| **P2** — `admin.update_user_by_id` → "User not allowed" | **ARTEFAK** | R2: admin update password **berhasil**. Kegagalan v1 karena client global memegang session user. |
| **P3** — set password sebelum konfirmasi → "User not allowed" | **ARTEFAK + temuan nyata** | R3: set password sebelum verify **diizinkan**, tetapi **membatalkan token undangan** (verify jadi gagal). |
| **P1** — jalur `email_otp` bekerja | **BENAR** | R5a: verify `email_otp` OK. Tidak lagi dipakai (lihat keputusan final). |

## Keputusan final

1. **Token aktivasi memakai `properties.hashed_token` + `type="invite"`.**
   Link aktivasi: `{APP_BASE_URL}/activate?token_hash=<hashed_token>&type=invite`.
   Tidak ada email di dalam link. `type` hanya menerima `invite`.
   `verify_otp({"token_hash": ..., "type": "invite"})` **tidak membutuhkan**
   parameter `email` (R1).
2. **Urutan POST /activate: verifikasi dulu, baru set password.**
   `verify_otp` → ambil `user.id` & `user.email` → validasi profil (status
   `pending` dan `invited_email` cocok) → klaim atomik `pending`→`active` →
   `admin.update_user_by_id(password)`. **Jangan pernah** menyetel password
   sebelum verify (R3 mematikan token).
3. **Client baru sekali-pakai per request wajib.** `verify_otp` memanggil
   `_save_session` bila respons membawa session, sehingga client global akan
   "menginap" sesi user. Gunakan
   `create_client(url, key, SyncClientOptions(auto_refresh_token=False, persist_session=False))`
   lalu buang. Client admin tidak boleh dipakai untuk `verify_otp`,
   `sign_in_with_password`, atau `auth.update_user`.
4. **Resend hanya untuk user pending.** `generate_link` gagal dengan
   `already been registered` bila email sudah terkonfirmasi (R7), jadi resend
   harus memeriksa `email_confirmed_at` lebih dulu dan mengarahkan admin ke
   *Batalkan & undang ulang*. Selama user masih pending, `generate_link` baru
   berhasil dan **token lama otomatis tidak berlaku** (R6).
5. **Pemulihan "confirmed tanpa password" = Batalkan & undang ulang.**
   Setelah verify sukses tetapi set password gagal, user Auth sudah confirmed
   tanpa password; resend mustahil (R7). Satu-satunya jalur adalah
   `admin.delete_user(uid)` (profil ikut terhapus karena FK `ON DELETE CASCADE`)
   lalu undang ulang.

## Catatan tambahan

- **C1** — `SyncClientOptions(auto_refresh_token=False, persist_session=False)`
  valid; desain "client baru sekali pakai" layak.
- **C2** — `generate_link` hanya menghasilkan link + token di respons; tidak ada
  email yang dikirim GoTrue. Pengiriman email (Brevo) adalah tanggung jawab
  aplikasi.
- **Bersih-bersih Auth yatim harus lewat client bersih.** Pada v1,
  `supabase.table("profiles").delete()` gagal `permission denied` (RLS) setelah
  client global "menginap" sesi. Jalur cancel-invite harus memakai client
  service-role yang bersih (fresh), bukan client yang sudah memegang sesi.
- Masa berlaku token undangan mengikuti setting **Email OTP expiry** di Supabase
  Auth; kesesuaiannya dengan konstanta aplikasi **belum teruji**.
