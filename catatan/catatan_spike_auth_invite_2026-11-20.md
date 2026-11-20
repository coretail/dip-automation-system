# Catatan Spike Task 0 — `generate_link` + `verify_otp` (staging, 2026-11-20)

Latar: verifikasi terbatas perilaku Supabase Auth (`supabase==2.31.0`) sebelum
implementasi fitur undang user via email. Skrip spike bersifat sementara dan
**tidak** disimpan di repo (hanya di `.kilo/`, git-ignored).

Dijalankan di bawah guard staging fail-closed (`app.database` lolos preflight
`check_shell_clean` + `validate_staging_file`), target host staging eksak.
Semua akun spike (`dip-spike-20261120-*@example.com`)
sudah dibersihkan dari Auth — pemeriksaan akhir: **tidak ada orphan**.

Tidak ada secret, token, password, atau kredensial yang dicetak.

## Hasil

| # | Skenario | Hasil | Detail |
|---|----------|-------|--------|
| C1 | `inspect.signature(create_client)` | **OK** | `ClientOptions` memuat `auto_refresh_token` & `persist_session`; `SyncClientOptions(auto_refresh_token=False, persist_session=False)` valid. Desain "client baru sekali pakai" layak. |
| S1.1 | `generate_link(type='invite')` | **OK** | Membentuk user Auth pending (`user.id` + `user.created_at` ada); respons membawa `properties.hashed_token`, `properties.verification_type=='invite'`, `properties.action_link`, dan **`properties.email_otp`** (kode 8 digit). |
| S1.2 | `verify_otp(type='invite', token=hashed_token)` | **GAGAL** | `AuthApiError: Token has expired or is invalid`. Token invite (hashed) **tidak bisa** di-verify via `verify_otp`. |
| P1 | `verify_otp(type='email', token=email_otp)` | **OK** | Mengonfirmasi user pending: `email_confirmed_at` terisi, session terbentuk. **Jalur aktivasi yang viable.** |
| S2.1 | Invite ke-2 untuk email pending | **OK** | Menghasilkan `hashed_token` baru (berbeda); `verification_type` tetap `invite`. |
| S2.2 | Token lama setelah invite ke-2 | **GAGAL** | Token lama tidak lagi bisa di-verify (sejalan dengan desain). |
| C2 | Email Supabase otomatis | **OK** | `generate_link` hanya menghasilkan link + token di respons; tidak ada email dikirim GoTrue. Pengiriman email (Brevo) adalah tanggung jawap aplikasi. |
| P2 | `admin.update_user_by_id(uid, {email_confirmed:True})` | **GAGAL** | `User not allowed` (user sudah confirmed oleh P1). Belum diuji pada user pending murni — jalur P1 sudah cukup. |
| P3 | set password sebelum email confirmed | **GAGAL** | `User not allowed`. Password hanya bisa di-set **setelah** email terkonfirmasi. |

## Dampak desain (WAJIB ditindaklanjuti)

1. **Token aktivasi adalah `email_otp`, bukan `hashed_token`.**
   - `verify_otp(type='invite', token=hashed_token)` **tidak bekerja**.
   - Invite **mengganti** token lama (S2.1/S2.2) dan `generate_link` tidak mengirim
     email, jadi hashed-token (yang hanya hidup di respons, bukan di email) tidak
     pernah sampai ke user.
   - Satu-satunya nilai yang sampai ke user (via email Brevo) dan bisa di-verify
     adalah **`properties.email_otp`** melalui `verify_otp(type='email', token=email_otp)`.
   - Konsekuensi: link aktivasi memakai `email_otp` (mis. `/activate?otp=...&type=invite`),
     dan `_redact_access_value` harus meredact `otp`/`token` (bukan `token_hash`).
   - "Token tidak hangus oleh salah ketik" tetap berlaku: OTP tidak hangus selama
     belum submit sukses; namun verifikasi OTP yang sukses mengonfirmasi email dan
     OTP tidak bisa dipakai ulang (sekali pakai).

2. **Client baru sekali-pakai per request WAJIB, bukan opsional.**
   `verify_otp` memanggil `_save_session` bila respons membawa `session`, sehingga
   client global `supabase` akan "menginap" sesi user yang sedang aktivasi.
   Gunakan `create_client(url, key, SyncClientOptions(auto_refresh_token=False,
   persist_session=False))` lalu buang setelah dipakai.

3. **Urutan aktivasi tetap**: verifikasi (konfirmasi email) → klaim profil →
   `admin.update_user_by_id(password=...)`. Hanya tokennya yang berganti ke
   `email_otp`. `auth_email_exists` (dedupe) tidak terpengaruh.

4. **Bersih-bersih Auth yatim harus lewat client bersih.**
   Saat spike, `supabase.table("profiles").delete()` gagal `permission denied`
   (RLS) setelah client global "menginap" sesi dari P1, dan `admin.delete_user()`
   ikut terpengaruh. Jalur cancel-invite (Task 3b) harus memakai client
   service-role yang bersih (fresh), bukan client yang sudah memegang sesi.

## Keputusan

Spike **tidak** menentukan pilihan desain cabang (cabang `create_user` terpisah
dan `recovery` sudah dihapus dari rencana). Ia hanya mengonfirmasi perilaku
project: jalur aktivasi yang viable adalah **`email_otp` + `verify_otp(type='email')`**.
