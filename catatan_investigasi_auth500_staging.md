# Catatan Investigasi — Supabase Auth HTTP 500 (Project Staging)

## Status Dokumen

**Dokumentasi saja — tidak ada perubahan kode, konfigurasi, skema, atau data.**

Dokumen ini mencatat hasil investigasi kegagalan Supabase Auth HTTP 500 pada
project staging. Fakta teramati, hipotesis teknis, dan tindakan yang belum
dilakukan dipisahkan secara eksplisit. Tanpa secret, tanpa kredensial, tanpa
nilai token/key.

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

### Belum Diketahui

* Baris mana yang terkait, bagaimana nilai `NULL` tersebut terbentuk, dan
  apakah penyebab dasarnya merupakan bug GoTrue, migrasi, impor data, atau
  kondisi lain.
* Belum terbukti bahwa satu baris tertentu menyebabkan seluruh operasi Auth
  gagal sebelum ada konfirmasi tambahan.

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
3. Jangan melakukan SQL `UPDATE`/`DELETE` langsung terhadap `auth.users`.
4. Jangan menghapus atau membuat ulang user berdasarkan tebakan. Dashboard
   list sendiri dilaporkan gagal, sehingga identifikasi user terdampak belum
   dapat diandalkan.
5. Setelah perbaikan terkonfirmasi, uji secara bertahap:
   * Auth admin list users;
   * lookup user yang valid;
   * lookup ID yang tidak ada dan pastikan respons sesuai;
   * login dengan akun staging khusus pengujian;
   * verifikasi profil aplikasi dan isolasi akses sesuai desain.
6. Jangan menyatakan staging production-ready sebelum seluruh pengujian
   relevan lulus.
