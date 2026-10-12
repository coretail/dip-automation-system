# Catatan Investigasi — Supabase Auth HTTP 500 (Project Staging)

## Status Dokumen

**Dokumentasi + remediasi staging terotorisasi — belum ada perubahan yang
dieksekusi dari sesi ini.**

Dokumen ini mencatat hasil investigasi kegagalan Supabase Auth HTTP 500 pada
project staging. Fakta teramati, hipotesis teknis, dan tindakan yang belum
dilakukan dipisahkan secara eksplisit. Tanpa secret, tanpa kredensial, tanpa
nilai token/key.

> Pembaruan 2026-10-12: pengguna mengotorisasi satu `UPDATE` terbatas pada
> `auth.users` project staging (`odtfppboyjlbatajncgj`) untuk mengisi empat
> kolom token yang `NULL` dengan string kosong. `UPDATE` tersebut BELUM
> dieksekusi dari workspace karena tidak ada jalur eksekusi SQL ke skema
> `auth` yang tersedia (tidak ada `DATABASE_URL`/password DB di workspace,
> tidak ada fungsi RPC `exec_sql`, endpoint `/pg/query` dan `/pg-meta/query`
> mengembalikan 404, dan Auth Admin API tidak dapat menjangkau kolom token
> internal). Probe read-only terakhir masih menunjukkan `admin list users`
> 500 (`Database error finding users`). Eksekusi harus dilakukan manual via
> SQL Editor Dashboard project staging, mengikuti instruksi §7.

## 1. Identitas Lingkungan (Fakta)

* Target: Supabase staging `dip-erfi-stagging`.
* Project ref staging: `odtfppboyjlbatajncgj`.
* Project ref produksi (berbeda, tidak disentuh): `dytuprmoorvrugutozwv`.
* Versi GoTrue yang dilaporkan: `v2.197.0`.
* Investigasi ini tidak melakukan perubahan pada database maupun project
  produksi. Tidak ada `INSERT`, `UPDATE`, atau `DELETE`. Tidak ada perubahan
  pada `auth.users`.

## 2. Urutan Lima Log Auth (Temuan Berdasarkan Laporan Investigasi)

Lima log dilaporkan terjadi dalam rentang sekitar tiga detik dan menggunakan
`remote_addr` serta `referer` yang sama, konsisten dengan satu sesi pengujian
dari localhost.

> Catatan sumber: isi log berikut berasal dari ringkasan laporan investigasi,
> bukan dari salinan mentah yang tersimpan di workspace. Zona waktu tanggal
> log asli dipertahankan apa adanya; tidak ada inferensi zona waktu tambahan.

| Waktu yang dilaporkan | Endpoint/operasi                        | Hasil                                                                    |
| --------------------- | --------------------------------------- | ------------------------------------------------------------------------ |
| 03:56:03              | `GET /admin/users`                      | HTTP 500, `unable to fetch records`, kegagalan scan `confirmation_token` |
| 03:56:04              | `POST /token?grant_type=password`       | HTTP 500, kegagalan scan `confirmation_token`                            |
| 03:56:05              | `GET /admin/users/{dummy-id}` — tiga ID | Tiga HTTP 500, `error finding user`, kegagalan scan yang sama            |

Detail error yang dilaporkan:

```text
converting NULL to string is unsupported
```

dengan `column index 3` pada hasil query yang gagal dipindai.

Request ID yang dilaporkan:

```text
01a12e40-d65d-7461-9a5b-29748c8161c3
```

### Konteks Tambahan yang Teramati

* Dua entri probe infrastruktur internal (`GET /auth/v1/health` 200 dan
  `POST /admin/v1/network-bans/retrieve` 200, user-agent
  `@supabase-infra/mgmt-api`) menunjukkan lapisan edge dan proses Auth hidup.
  Keduanya tidak membaca baris `auth.users`, sehingga tidak membantah
  kegagalan pada jalur data Auth.
* Dua entri 500 via `python-httpx/0.28.1` (`GET /admin/users/{id}` dan
  `POST /token?grant_type=password`) konsisten dengan user-agent SDK aplikasi,
  dan dipetakan ke call-site `login_submit` di `app/main.py`
  (`auth.admin.get_user_by_id` dan `sign_in_with_password`).

## 3. Interpretasi Teknis (Tingkat Kepastian)

### Teramati

* Beberapa operasi Auth mengembalikan HTTP 500 dengan error scan yang mengacu
  pada `confirmation_token` bernilai `NULL`.

### Indikasi Kuat

* Kegagalan terjadi pada jalur pemrosesan data internal Auth, bukan pada
  respons aplikasi yang seharusnya sekadar menunjukkan user tidak ditemukan.
  Lookup ID dummy yang seharusnya 404 justru 500 dengan pesan scan yang sama.

### Hipotesis yang Belum Dikonfirmasi

* Ada ketidakcocokan antara nilai `NULL` pada data internal Auth dan asumsi
  tipe/model yang digunakan GoTrue saat melakukan scan.

### Terjawab dari Instruksi Remediasi Terotorisasi (2026-10-12)

* Semua 3 baris terdampak, di 4 kolom: `confirmation_token`,
  `recovery_token`, `email_change_token_new`, `email_change`. Bagian
  "Belum Diketahui" sebelumnya tentang cakupan baris/kolom kini terjawab
  untuk keperluan remediasi.
* Alasan 4 kolom sekaligus: perbaikan resmi Supabase hanya menyebut
  `confirmation_token`; jika hanya kolom itu yang diisi, error kemungkinan
  besar pindah ke kolom berikutnya (`recovery_token`, dst.) karena model
  GoTrue memindai semuanya sebagai string non-nullable.

### Belum Diketahui

* Bagaimana nilai `NULL` tersebut terbentuk, dan apakah penyebab dasarnya
  merupakan bug GoTrue, migrasi, impor data, atau kondisi lain.
* Apakah user dibuat via SQL langsung (melewati Auth Admin API) — jika ya,
  itulah kandidat asal `NULL`. Jalur pembuatan akun di aplikasi
  (`POST /admin/users/create`, `app/main.py`, `auth.admin.create_user`
  dengan `email_confirm: True`) memakai Auth Admin API resmi dan tidak
  melakukan `INSERT` langsung ke `auth.users`; tidak ada skrip seed SQL ke
  `auth.users` di repo.

## 4. Pengujian yang Sudah Dilakukan (Fakta)

* Validasi file konfigurasi staging: PASS.
* Pengujian REST read-only `products`, operasi `select-limit1`: PASS, satu
  baris dikembalikan.
* Tidak ada `INSERT`, `UPDATE`, atau `DELETE`.
* Tidak ada perubahan pada `auth.users`.
* Dashboard Auth dan log masih membutuhkan tindak lanjut support/manual.
* REST read pada `products` tidak membuktikan Auth, CRUD penuh, maupun
  isolasi RLS telah lolos.

## 5. Status Hardening dan Git (Fakta)

Dua commit lokal yang dilaporkan (push ditunda):

1. `b17f7a9` — `hardening(staging): isolate staging fail-closed with
   preflight validator, guard, split config, launcher 8017`
2. `9f41550` — `chore(config): whitelist staging env example and ignore
   local rls backups`

Status worktree terakhir yang dilaporkan: bersih setelah kedua commit.
Kondisi aktual pada saat dokumen ini ditulis:

* Branch: `main`.
* Remote: `origin` (`https://github.com/coretail/dip-automation-system.git`).
* `git status --short` kosong; `git log -5` diawali `9f41550`, `b17f7a9`.

Tidak ada bukti saat ini bahwa Auth 500 disebabkan oleh commit hardening;
kode Auth GoTrue berjalan di sisi layanan Supabase dan belum ada regresi
aplikasi yang teridentifikasi dari temuan ini.

## 6. Rencana Tindak Lanjut

1. Eskalasi ke Supabase Support dengan project ref staging, versi GoTrue,
   timestamp lengkap, pesan error, dan request ID di atas.
2. Minta konfirmasi penyebab `confirmation_token` bernilai `NULL` dan
   remediasi resmi yang didukung platform.
3. Jangan menghapus lalu membuat ulang user. ID `auth.users` kemungkinan
   dirujuk tabel `profiles`, sehingga membuat ulang bisa merusak relasi.
   `UPDATE` terbatas di bawah lebih aman.
4. Jangan menghapus atau membuat ulang user berdasarkan tebakan. Dashboard
   list sendiri dilaporkan gagal, sehingga identifikasi user terdampak belum
   dapat diandalkan.

## 7. Remediasi Terotorisasi — UPDATE 4 Kolom (Staging Saja, Belum Dieksekusi)

> Otorisasi: pengguna, 2026-10-12. Scope: HANYA project staging
> `odtfppboyjlbatajncgj`. Produksi (`dytuprmoorvrugutozwv`) TIDAK tersentuh.

Query mengisi `NULL` menjadi string kosong di keempat kolom, hanya pada
baris yang memiliki minimal satu `NULL` di antara keempatnya. Tidak mengubah
ID, password, atau identitas:

```sql
update auth.users
   set confirmation_token     = coalesce(confirmation_token, ''),
       recovery_token         = coalesce(recovery_token, ''),
       email_change_token_new = coalesce(email_change_token_new, ''),
       email_change           = coalesce(email_change, '')
 where confirmation_token is null or recovery_token is null
    or email_change_token_new is null or email_change is null;
```

Langkah eksekusi manual (workspace tidak memiliki jalur SQL ke skema
`auth`):

1. Buka SQL Editor pada Dashboard project staging `odtfppboyjlbatajncgj`
   (bukan project produksi). Verifikasi project ref di URL sebelum
   menjalankan apa pun.
2. (Read-only dulu) Jalankan `SELECT` sebaran untuk konfirmasi cakupan
   sebelum `UPDATE`:

   ```sql
   select id,
          confirmation_token is null as ct_null,
          recovery_token is null as rt_null,
          email_change_token_new is null as ectn_null,
          email_change is null as ec_null
     from auth.users
    where confirmation_token is null or recovery_token is null
       or email_change_token_new is null or email_change is null;
   ```

   Ekspektasi dari otorisasi: 3 baris.
3. Jalankan `UPDATE` di atas. Catat jumlah baris yang diubah (harus 3).
4. Uji ulang sesuai urutan:
   * Auth admin list users (harus 200);
   * lookup user yang valid (harus 200);
   * lookup ID yang tidak ada (harus 404, bukan 500);
   * login dengan akun staging khusus pengujian (harus 200 + sesi);
   * verifikasi profil aplikasi dan isolasi akses sesuai desain.

## 8. Pencegahan Terulang — Jalur Pembuatan User

* Tidak ada skrip seed SQL ke `auth.users` di repo (hasil `grep`
  `auth.users`/`confirmation_token`/`recovery_token`/`email_change_token`
  pada `*.py`: nihil di luar catatan ini dan komentar kode).
* Satu-satunya jalur pembuatan user di aplikasi:
  `POST /admin/users/create` → `auth.admin.create_user` dengan
  `email_confirm: True` (`app/main.py`). Jalur ini memakai Auth Admin API
  resmi; GoTrue mengisi kolom token melalui jalurnya sendiri.
* Aturan: buat user hanya lewat Auth Admin API (aplikasi atau Dashboard).
  Jangan `INSERT` langsung ke `auth.users`; jika `INSERT` langsung tidak
  terhindarkan, isi keempat kolom token dengan `''` agar scan GoTrue tidak
  gagal.
* Tidak ada perubahan kode yang dilakukan pada sesi ini untuk aturan ini;
  penegakan bersifat prosedural sampai ada kebutuhan patch kode yang
  disetujui terpisah.

## 9. Kriteria Selesai

Jangan menyatakan staging production-ready sebelum seluruh pengujian
relevan lulus (urutan §7 langkah 4 + isolasi akses sesuai desain).

## 10. Hasil Uji Ulang Pasca-UPDATE (2026-10-12, Fakta)

`UPDATE` 4 kolom dijalankan manual via SQL Editor Dashboard staging oleh
pengguna. Uji ulang bertahap via skrip terisolasi (`staging_retest_auth.py`,
guard fail-closed, tanpa cetak secret):

* [1] Auth admin list users: OK, `count=3` — tiga ID yang sebelumnya 500
  kini terbaca: `admin.staging@test.local`, `staff1.staging@test.local`,
  `staff2.staging@test.local`.
* [2] Lookup user valid (ID pertama): OK 200, email sesuai.
* [3] Lookup ID tak-ada (`00000000-...`): `AuthApiError code=404
  User not found` — 404 sesuai harapan, bukan 500.
* [4] Login akun uji staging khusus: LOLOS via akun ke-4
  `uitest.staging@test.local` (dibuat pada sesi ini via Auth Admin API
  dengan `email_confirm: True`, tanpa `INSERT` SQL langsung).
* Verifikasi profil aplikasi: LOLOS — baris `profiles` terbaca kembali
  (`full_name=uitest.staging`, `role=staff`, ID cocok dengan `auth.users`).
  Isolasi akses sesuai desain (RLS penuh): BELUM dilakukan.

Kesimpulan sementara: kegagalan scan `confirmation_token` NULL teratasi
untuk jalur list, lookup valid, lookup tak-ada, pembuatan user via Admin
API, login password grant, dan penulisan/pembacaan profil. Verifikasi
isolasi akses (RLS) masih menunggu.

> Password akun uji ke-4 TIDAK dicatat di dokumen/repo ini. Password acak
> ditampilkan sekali pada output eksekusi dan harus disimpan di pengelola
> kredensial terpisah bila masih diperlukan.
