# Catatan Migrasi Storage: Supabase → Cloudflare R2

Dokumen ringkas operasional untuk fase migrasi storage. Rahasia (nilai token/secret)
TIDAK ditulis di sini — hanya nama/scope dan perilaku.

## 1. Format log `storage_repair` (pemantauan soak `dual`)

- Ditulis oleh `logger.warning` pada modul `app.object_store` (`app/object_store.py`).
- Muncul saat mode `dual`/`r2` gagal menulis/menghapus di R2. Di mode `dual`,
  kegagalan ini **tidak** menggagalkan request (Supabase tetap otoritatif);
  rekonsiliasi utama tetap `rclone sync`.
- **Token pencarian (untuk Render): `storage_repair`.**
- Format satu baris:
  ```
  storage_repair op=<upload|remove> bucket=<logical_bucket> path=<key> backend=r2 error=<exception>
  ```
- Contoh nyata (bucket staging, kredensial sengaja salah):
  ```
  storage_repair op=upload bucket=raw-material-docs path=_smoke/<ts>/dual.pdf backend=r2 error=An error occurred (SignatureDoesNotMatch) when calling the PutObject operation: The request signature we calculated does not match the signature you provided. ...
  ```
- Kriteria cutover: baris `storage_repair` **kosong** ≥7 hari sejak `dual` aktif di PROD.

### 1a. Log sinyal positif: `storage_r2_ok`

- Ditulis oleh `logger.warning` pada `_r2_upload` (`app/object_store.py`) **setiap
  tulis R2 sukses** (mode `dual` maupun `r2`). Level WARNING disengaja: root logger
  tanpa konfigurasi berlevel efektif WARNING, jadi `logger.info` tidak terlihat
  di konsol — token sukses harus selevel `storage_repair` agar bisa dicari di
  alur log yang sama.
- Format satu baris:
  ```
  storage_r2_ok op=upload bucket=<logical_bucket> physical=<physical_bucket> path=<key>
  ```
- Pemantauan soak/prod-`dual`: setiap upload harus memunculkan `storage_r2_ok`
  (jumlah baris = jumlah tulisan R2; `physical` cocok untuk spot-check
  `rclone lsf r2stg:<bucket>-stg`), dan `storage_repair` tetap **kosong**.
- Hanya menyangkut tulis (upload). Hapus yang sukses tidak punya token —
  cukup dipastikan lewat ketiadaan `storage_repair op=remove`.

## 2. CORS diverifikasi lewat probe `Origin` dari luar (bukan `GetBucketCors`)

- Token R2 berscope **Object Read & Write** (data-plane) **tidak bisa** `GetBucketCors`
  maupun `PutBucketCors` → `AccessDenied`. Jadi konfigurasi CORS tidak dapat
  dibaca/diverifikasi lewat S3 API dengan token yang dipakai aplikasi.
- Verifikasi dilakukan **dari luar**: request ke URL publik (r2.dev) / presigned dengan
  header `Origin` yang benar harus memuat `access-control-allow-origin`, dan preflight
  `OPTIONS` mengembalikan `204` dengan `access-control-allow-methods: GET, HEAD`.
- Hasil: keenam bucket lolos. Origin: prod = `https://dip-automation-system.onrender.com`;
  staging = `http://127.0.0.1:8017` (staging lokal, belum ada domain app).
- Jika nanti ada domain custom/domain staging, tambahkan sebagai entri origin terpisah
  dan ulangi probe.

## 3. Request anonim ke endpoint S3 R2 → HTTP 400 (bukan 403)

- `GET` tanpa tanda tangan ke `https://<account>.r2.cloudflarestorage.com/<bucket>/<key>`
  dijawab R2 dengan **HTTP 400**:
  ```
  <Error><Code>InvalidArgument</Code><Message>Authorization</Message></Error>
  ```
- Jadi R2 menolak request anonim dengan `400 InvalidArgument (Authorization)`, **bukan**
  `403 AccessDenied`. Yang dibuktikan tetap sama: **tidak ada akses anonim** ke objek
  (bucket privat `product-attachments*`).
- Skrip verifikasi: `scripts/r2_live_smoke.py` (staging-only; prefix `_smoke/<ts>/`;
  cleanup di `finally`).
