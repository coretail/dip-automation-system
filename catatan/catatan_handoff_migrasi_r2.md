# Handoff — Migrasi Storage Supabase → Cloudflare R2

> **Catatan historis (2026-10):** status fase di bawah mencerminkan kondisi saat handoff ditulis. Perilaku mode `dual` yang sebenarnya (fail-loud upload ke R2) mengikuti kode di `app/object_store.py` dan panduan bagian **Object Storage** — jangan anggap "best-effort"/"request tetap sukses" sebagai perilaku saat ini. Lihat panduan bagian Object Storage untuk prosedur cutover/rollback terkini.

_Update terakhir: 2026-10-17._

**Tujuan:** memindahkan object storage dari Supabase Storage ke Cloudflare R2 (mode
`dual` → `r2`), tanpa downtime, dengan URL kolom DB diganti prefix secara idempoten.

**Plan acuan:** `.kilo/plans/1792047573445-supabase-to-r2-migration.md`
(langkah 15 ditandai DONE; catatan langkah 14 & Fase 4 sudah ditambahkan).

## Status per fase
| Fase | Status | Bukti ringkas |
|---|---|---|
| 0 Cloudflare (bucket/token/r2.dev/CORS/env) | ✅ | 6 bucket; token prod & `-stg` terpisah; r2.dev hanya bucket publik; CORS ke-6 bucket lolos probe `Origin`; `boto3==1.43.114`; preflight staging fail-closed 10 key |
| 1 Konsolidasi `cpkb_documents` | ✅ | 2 objek → `legal-documents`; `cpkb_raw_material.file_url` (2 baris) diupdate; bucket dihapus; 0 referensi tersisa |
| 2 Abstraksi `object_store` | ✅ | 42 call site dipindah (semua akses storage lewat `object_store`; `storage.from_` hanya di situ); parser 19/19; `snapshot_dip guardtest` AKTIF |
| 3 Backend R2 + mode `dual`/`r2` | 🟡 soak staging jalan | unit test dispatch LULUS; live smoke R2 staging 12/12 PASS |
| 4 Salin data + audit | ✅ | `rclone check --download` 100% semua bucket; audit prod 770 ref; legacy columns dibersihkan; `backfill_r2_urls.py` siap (idempoten terbukti) |
| 5 Cutover | ⛔ belum | tunggu soak |
| 6 Pensiun | ⛔ belum | — |

## Infrastruktur (tanpa nilai rahasia)
- Satu akun R2 dipakai prod & staging → **bucket fisik staging wajib ber-suffix `-stg`**.
- Bucket: prod `raw-material-docs`, `legal-documents`, `product-attachments`;
  staging `<masing-masing>-stg`.
- r2.dev aktif hanya untuk `raw-material-docs` & `legal-documents` (prod + `-stg`);
  `product-attachments*` **privat penuh** (presigned).
- Token R2: prod (scope 3 bucket prod) & staging (scope 3 bucket `-stg`), izin
  **Object Read & Write** (data-plane → **tidak bisa** `GetBucketCors`/`PutBucketCors`).
- Endpoint S3 R2: `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com`.
- Endpoint S3 Supabase (source rclone): `https://<ref>.storage.supabase.co/storage/v1/s3`.

## Kode & berkas penting
- `app/object_store.py` — satu-satunya jalur storage. `upload_pdf / public_url /
  signed_url(s) / remove` + dispatch `supabase|dual|r2`. `dual` = upload ke **R2 lebih
  dulu (fail-loud)** lalu Supabase (rollback best-effort untuk jalur non-upsert);
  baca tetap Supabase. Tulis R2 sukses → log `storage_r2_ok` (level WARNING).
  `_r2_public_url` meng-encode path (`%20`).
  `_r2_physical_bucket` = nama logis + `R2_BUCKET_SUFFIX`.
- `app/config.py` — field `storage_backend`, `r2_account_id/access_key_id/
  secret_access_key/public_bases/bucket_suffix`. Preflight **hanya** saat `DIP_APP_ENV=staging`.
- `app/staging_preflight.py` + `scripts/run_staging_8017.py` — `REQUIRED_KEYS`/`EXPORT_KEYS`
  mencakup 5 key R2 + `R2_BUCKET_SUFFIX` (fail-closed saat staging).
- `scripts/r2_live_smoke.py` — live smoke **staging-only** (guard `-stg`, prefix
  `_smoke/<ts>/`, cleanup `finally`).
- `migration/audit_storage.py` — audit referensi vs objek (MISSING/ORPHAN), report-only,
  decode-aware.
- `migration/backfill_r2_urls.py` — idempoten; `--target r2|supabase`; default dry-run;
  `--apply`; pre-check objek wajib ada di target.
- `migration/005_null_legacy_brand_merk_columns.sql` — NULL-kan kolom legacy
  `brands.hak_merk_file_url` / `brands.lisensi_merk_file_url`.
- `tests/test_parse_storage_url.py`, `tests/test_object_store_r2.py` (di-track).
- `catatan_migrasi_storage_r2.md` — format log `storage_repair`, CORS via probe `Origin`,
  R2 anonim → 400.

## Commit (main, sudah di-push)
`79d38a8` docs catatan → `bd97419` r2_live_smoke → `26fba31` encode public_url R2 →
`d207c89` backfill_r2_urls → `7bed4a7` 005 legacy null → `560225d` audit_storage →
`e4a1879` unit test → `77e688e` object_store + R2/dual. Working tree bersih; file
handoff ini kini ikut ter-track (commit `c2b4933`).

## Kondisi saat ini
- **staging** `.env.staging`: `STORAGE_BACKEND=dual`, `R2_BUCKET_SUFFIX=-stg`. App staging
  dijalankan lokal (127.0.0.1:8017) — **soak di-restart 2026-10-19** (soak pertama
  2026-10-16T08:24Z terputus saat proses mati bersama sesi; estimasi lulus ≈ 2026-10-22).
  Log konsol kini di-append ke `staging.log` (persisten antar restart). Launcher WAJIB
  via `venv\Scripts\python.exe` — `py` global tidak punya uvicorn.
- **prod**: Render env masih `GEMINI_API_KEY`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
  `SUPABASE_URL` saja; `STORAGE_BACKEND` **tidak di-set → default `supabase`** →
  perilaku prod tak berubah. Jangan set `DIP_APP_ENV` di prod.
- Data: R2 prod 642/105/4 objek (identik Supabase, `check` 0 diff); R2 staging 1/2 objek.

## Yang dipantau selama soak (≥3 hari)
1. **Log `storage_repair`** dari app staging → target **kosong** (token pencarian
   `storage_repair`).
2. **Log `storage_r2_ok`** → setiap upload staging harus memunculkan token ini
   (pasangan positif `storage_repair`; lihat §1a `catatan_migrasi_storage_r2.md`).
3. **Gunakan staging**: upload/hapus/preview PDF, beberapa `dip_public`, bahan baku/produk.
4. **Spot-check** objek baru muncul di bucket `…-stg` (mis. `rclone lsf r2stg:raw-material-docs-stg`).

> Proses app staging ber-umur **sesi** (mati saat sesi ditutup) — untuk soak 3 hari
> sungguhan, jalankan/host-kan staging terus.

## Langkah selanjutnya
1. **Soak staging ≥3 hari**. Estimasi lulus ≈ 2026-10-22 (jam soak di-reset 2026-10-19;
   soak pertama 10-16 terputus). Bukti awal: E2E UI→R2 8/8 PASS (2026-10-19).
2. **Prod `dual`** — tambah 6 env di Render **bersamaan**: `STORAGE_BACKEND=dual`,
   `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
   `R2_PUBLIC_BASES={"raw-material-docs":"…","legal-documents":"…"}`,
   `R2_BUCKET_SUFFIX=` (**kosong**). Lalu pantau `storage_repair` **kosong ≥7 hari**.
   (Jangan set `dual` sebelum 6 var R2 lengkap — `_r2_client` akan error tiap tulis.)
3. **`rclone sync` final prod** — `--dry-run` dulu, tinjau daftar hapus, lalu eksekusi
   (delta 0). Sebelum ini hindari upload via dashboard Supabase.
4. **Cutover**: `backfill_r2_urls.py --env prod --target r2` (dry-run, simpan laporan) →
   `--apply`; set `STORAGE_BACKEND=r2` + deploy segera; verifikasi (audit 0 anomali vs
   base baru; smoke upload→URL→hapus). Rollback: balik flag → `--target supabase --apply`.
5. **Fase 6**: soak ≥4 minggu (bucket Supabase utuh) → hentikan tulis Supabase; saat
   domain custom ada → tambah base di `R2_PUBLIC_BASES` + jalankan ulang backfill; update docs.

## Perintah penting
```
# staging (dual) — konsol; untuk log persisten bungkus launcher dengan
# redirect stdout+stderr ke staging.log (pola wrapper subprocess append)
venv\Scripts\python.exe scripts\run_staging_8017.py
# E2E upload UI -> R2 (staging hidup + --log staging.log; env: STAGING_ADMIN_EMAIL/PASSWORD)
py tests/e2e_upload_staging.py --log staging.log
# live smoke R2 (staging-only)
python scripts/r2_live_smoke.py
# audit (report-only)
python migration/audit_storage.py --env prod        # atau --env staging
# backfill (default dry-run)
python migration/backfill_r2_urls.py --env prod --target r2
python migration/backfill_r2_urls.py --env prod --target r2 --apply
```

### Menyiapkan rclone (untuk `copy`/`check`/`sync`)
rclone 1.75.1 (winget). PowerShell diblokir Execution Policy → jalankan skrip via
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File <script.ps1>`. Remote (via env
var `RCLONE_CONFIG_<NAMA>_*` atau `rclone config`):
- **Supabase (source)**: `type=s3`, `provider=Other`,
  `endpoint=https://<ref>.storage.supabase.co/storage/v1/s3`, `access_key_id=<ref>`,
  `secret_access_key=<anon key>`, `session_token=<service_role JWT>`,
  `region=<project region>` (`ap-southeast-1` prod / `ap-northeast-1` staging),
  `force_path_style=true`.
- **R2 (dest)**: `type=s3`, `provider=Cloudflare`,
  `endpoint=https://<acct>.r2.cloudflarestorage.com`, `access_key_id`/`secret_access_key`
  = token R2, `region=auto`.
- Verifikasi: `rclone lsd sbprod:`, `rclone lsf r2prod:raw-material-docs`,
  `rclone check <src> <dst> --download`.

## Keputusan terkunci (jangan diubah tanpa konfirmasi)
- URL kolom DB tetap **absolut, ganti prefix** (path-only ditunda).
- Backfill **idempoten berbasis konfigurasi** (`R2_PUBLIC_BASES`), default dry-run +
  pre-check keberadaan objek di target.
- Key objek **identik** path Supabase (spasi dipertahankan; URL di-encode `%20`).
- `product-attachments*` **privat** via presigned (tanpa r2.dev/domain).
- Bucket Supabase lama **tidak dihapus ≥4 minggu**; rollback = balik flag + backfill ke
  base Supabase.
- `R2_BUCKET_SUFFIX`: prod `""`, staging `"-stg"` (mencegah staging menulis ke bucket R2 prod).

## Temuan & catatan (penting)
- R2 menjawab request anonim ke endpoint S3 dengan **400 `InvalidArgument (Authorization)`**,
  bukan 403.
- Token Object Read & Write **tidak** bisa `GetBucketCors` → CORS diverifikasi lewat probe
  `Origin` dari luar.
- 2 MISSING lama (kolom **legacy** `brands.hak_merk_file_url`, tak dipakai kode) sudah
  di-NULL-kan; audit prod kini **MISSING=0**.
- **12 ORPHAN** prod (mayoritas produk `284d1915…` + `coa/coa_123123.pdf`) — report-only,
  belum diputuskan.
- Staging **tidak punya** tabel/bucket `product_attachments` → alur lampiran tak ter-soak
  di staging.
- Preflight staging **fail-closed**: staging wajib punya 10 key (termasuk R2) atau gagal
  start. Prod tidak terpengaruh.
- `.env`/`.env.staging`/`.kilo/` gitignored (rahasia). `tests/` mayoritas gitignored;
  yang di-track: 2 unit test + `tests/verify_po_analytics_detail.py` +
  `tests/verify_product_attachments.py` + `migration/audit_storage.py` +
  `migration/backfill_r2_urls.py`.
- Wrapper rclone sementara (`%TEMP%\kilo\r2rc.ps1`) bisa hilang — pakai resep remote di atas
  untuk membuat ulang.

## Blocker
Tidak ada yang memblokir kode; **hanya menunggu waktu soak**.
