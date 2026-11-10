# Log Progres Perbaikan Audit 2026-11-05

**Rujukan utama:** `catatan/catatan_audit_codebase_2026-11-05.md` (audit menyeluruh, hash `origin/main` @ `6830ae2`, tanggal 5 November 2026).

**Fungsi dokumen ini:** Log progres berkelanjutan. Setiap sesi perbaikan tercatat di sini dan akan terus diperbarui hingga seluruh temuan dalam daftar audit telah diperbaiki atau terdapat instruksi perubahan keputusan lainnya. Jangan mengubah laporan audit asli; status perbaikan dicatat di file ini.

**Konvensi status:** `BELUM` (belum dikerjakan), `SELESAI` (dikerjakan + divalidasi), `TERBUKA` (diketahui tetapi memutuskan tidak di-fix pada sesi ini), `N/A` (keputusan berubah / tidak relevan).

---

## Ringkasan status

| ID | Temuan audit | Status | Sesi |
|---|---|---|---|
| A1 (G §8) | `test_auth_matrix.py` tanpa runner `main()` → CI false-green | SELESAI | 2026-11-05 (edisi ini) |
| A1 (G §8) | `test_upload_validation.py` tanpa runner `main()` → CI false-green | SELESAI | 2026-11-05 (edisi ini) |
| A2 (G §8) | `test_verify_r2_readiness_logic.py` whitelisted tetapi tidak dijalankan CI | SELESAI | 2026-11-05 (edisi ini) |
| A3 (D-04 §7) | README instruksikan `uvicorn app.main:app --reload` (dilarang AGENTS/guard) | SELESAI | 2026-11-05 (edisi ini) |
| A3 (D-01/D-02/D-03 §7) | Versi dep tertinggal; hitungan template 17 vs 18; pohon `app/` tak lengkap | SELESAI | 2026-11-05 (edisi ini) |
| A4 (D-05/D-06/D-07/D-13 §7) | Suite `notes` tak disebut; klaim Python 3.10+ usang; §4.14 “hanya SQL di-commit”; tabel `entity_type` kurang 5 | SELESAI | 2026-11-05 (edisi ini) |
| B1 (§5 C-12) | Guard `greeting_cache` tanpa validasi skema | SELESAI | 2026-11-05 (sesi 2) |
| B2 (§5 C-11) | `HTTPException` ditelan di `get_current_user` | SELESAI | 2026-11-05 (sesi 2) |
| B3 (§5 C-06) | Restore selalu “sukses” walau 0 baris | SELESAI | 2026-11-05 (sesi 2) |
| B5 (§3 A-04) | Interpolasi `item.id` tanpa encodeURIComponent di ED bell | SELESAI | 2026-11-05 (sesi 2) |
| B6 (§4 F-05) | Selektor cache-bust tak cocok `pub-*.r2.dev` | SELESAI | 2026-11-05 (sesi 2) |
| B7 (§4 F-07) | MutationObserver po-analytics tanpa debounce | SELESAI | 2026-11-05 (sesi 2) |
| B8 (§5 C-05) | Tipe exception greeting AI tidak dicatat | SELESAI | 2026-11-05 (sesi 2) |
| B9 (§4 F-04) | Spam log `[SESSION EXPIRED]` (gabungkan ringkasan 5-menit + debug) | SELESAI | 2026-11-05 (sesi 2) |
| B4 (§3 F-07) | Timing-safe token publik | SELESAI | 2026-11-05 (sesi 4) |
| B10 (§4 F-07 alt) | Disconnect observer saat print | SELESAI (digabung B7) | 2026-11-05 (sesi 2) |
| C1 (§6 E-05) | `parse_storage_url` tanpa `unquote` — path `%20` salah target | SELESAI | 2026-11-05 (sesi 3) |
| C2 (§6 E-06) | Upload tanpa validasi base dulu → orphan bila base kurang | SELESAI | 2026-11-05 (sesi 3) |
| C3 (§5 C-14) | `.single()` vs cek manual tidak konsisten | TERBUKA (skip sesuai keputusan) | Keputusan konfirmasi 2026-11-05 |
| C4–C12+ | Blocker cutover R2 (encoding, base, SSRF, privat, selektor) + pypdf | BELUM | — |
| D-08, D-09, D-10, D-14 | Status migrasi 011 ambigu; handoff R2 tertinggal; catatan historis tanpa banner | BELUM | — |
| E-04 s.d. E-08 | Blocker cutover R2 (encoding, base, SSRF, soak privat, selektor) | BELUM | — |
| pypdf ≥6.21.4 | 10 advisory terbuka (butuh PR terpisah + uji manual) | SELESAI | 2026-11-07 (sesi 8) |
| F-03 (§3) | `public_access_revoked_at` tidak pernah dibaca; revoke tidak fungsional | SELESAI | 2026-11-07 (sesi 9) |
| F-09 (§3) | Route /dip/* tanpa jejak audit download/ZIP | SELESAI | 2026-11-07 (sesi 9) |
| F-08 (§3) | Nol rate-limit di /dip/* | SELESAI | 2026-11-09 (sesi 10) |
| F-05 | Token `?access=` di access log (sisi aplikasi tutup; residu log edge Render di luar repo) | SELESAI (sisi aplikasi) | 2026-11-09 (sesi 10) |
| C-01/A-17 (profil) | Akun tanpa profil/query profil gagal jadi fail-open staff lintas tenant | SELESAI (profil hilang / query gagal, #69) | 2026-11-09 (sesi 12) |
| C-01/C-02 bagian perusahaan kosong | Non-admin perusahaan kosong lintas tenant | N/A (keputusan pemilik repo 2026-11-09) | 2026-11-09 (sesi 12) |
| C-07 | Edit komponen bahan baku bukan atomik (delete lalu insert) | SELESAI (kode #71; migrasi 013 dijalankan di staging dan produksi 2026-11-09) | 2026-11-09 (sesi 13) |
| C-08 | Audit sudah tertutup di main | SELESAI | sudah tertutup di main (commit 2b6ee79), terverifikasi di Sesi 13 |
| C-10 | Upload lampiran rollback | tidak memerlukan perubahan (lampiran.js menangani `failed` per file; rollback insert sudah ada — app/static/lampiran.js:103) | 2026-11-09 (sesi 13) |
| D-08 | Status migrasi ambigu (011) | SEBAGIAN: status 007 dan 013 terkonfirmasi, sisanya menunggu hasil query pengecekan pemilik repo | 2026-11-09 (sesi 14) |
| D-09 | Handoff R2 tertinggal | SEBAGIAN: banner historis ditambahkan; baris produksi ditandai usang (lihat README) | 2026-11-09 (sesi 14) |
| D-10 | Catatan historis tanpa banner (batch plan + audit 2026-10-27) | SEBAGIAN: banner historis ditambahkan | 2026-11-09 (sesi 14) |
| D-14 | Status eksekusi migrasi di panduan | SEBAGIAN: paragraf status + query pengecekan ditambahkan | 2026-11-09 (sesi 14) |

---

## Sesi 1 — 2026-11-05: Kategori A (risiko nol terhadap produksi)

**Ruang lingkup sesi ini:** hanya Kategori A — perubahan yang tidak mengubah perilaku runtime aplikasi: runner test, konfigurasi CI, dan dokumentasi.

### Perubahan kode

| # | File | Perubahan | Bukti (sebelum → sesudah) |
|---|---|---|---|
| A1 | `tests/test_auth_matrix.py:29-35` | Tambahkan blok `if __name__ == "__main__":` yang memanggil `test_anonymous_requests_are_redirected_or_denied()` dan mencetak `PASS ...` | Sebelum: 31 baris, hanya definisi fungsi, `python tests/test_auth_matrix.py` exit 0 tanpa assertion. Sesudah: 35 baris; di clone bersih tanpa `.env`, exit 0 dan `PASS test_anonymous_requests_are_redirected_or_denied` ter-cetak (10 route protected, semua 303/401/403 + `/login`). |
| A1 | `tests/test_upload_validation.py:31-49` | Tambahkan blok `if __name__ == "__main__":` yang memanggil 6 fungsi `test_*` satu per satu dengan cetak `PASS` per fungsi | Sebelum: 32 baris, 6 definisi-only, output kosong. Sesudah: 49 baris; output kini 6 baris `PASS test_*`, exit 0. |
| A2 | `.github/workflows/ci.yml:80` | Tambahkan `python tests/test_verify_r2_readiness_logic.py` sebagai baris ke-19 pada langkah “Pure-local tests” | Sebelum: 18 baris test; `grep verify_r2` di `ci.yml` = 0 match. Sesudah: 19 baris test; file sudah whitelisted (`.gitignore:133`) dan memiliki runner lengkap. |
| A3 | `README.md:150-151` | Samakan versi `boto3 1.43.115` dan `pydantic-settings 2.16.0` di tabel dengan `requirements.txt` | `requirements.txt:5-6` sudah `1.43.115` / `2.16.0`; README sebelumnya `1.43.114` / `2.15.0`. |
| A3 | `README.md:212-230` (§4 + §4a) | Jadikan `python scripts/run_staging_8017.py` perintah utama development; pindahkan `uvicorn app.main:app --reload` ke catatan produksi eksplisit `DIP_APP_ENV=production`; tambahkan peringatan larangan dan rujukan guard G-11 | Perilaku kode tidak berubah; hanya urutan instruksi dibalik agar sesuai `AGENTS.md:11` dan `app/env_guard.py`. |
| A3 | `README.md:246-289` (pohon proyek) | Tambahkan entri modul yang belum terdaftar: `admin_users_routes.py`, `brands_routes.py`, `company_docs_routes.py`, `dashboard_routes.py`, `env_guard.py`, `file_validation.py`, `object_store.py`, `products_routes.py`, `presence_routes.py`, `profile_routes.py`, `profile_validation.py`, `sample_routes.py`, `security.py`, `variant_components.py`, `common.js`; ubah “17 halaman” → “18 halaman” di dua tempat | Diverifikasi: 18 file `app/templates/*.html` memakai `{% extends %}` (termasuk `profile.html`). |
| A4 | `AGENTS.md:7,23-24` | “README menyatakan Python 3.10+” → “README pin 3.11.0”; “delapan belas test” → “sembilan belas test”; tambahkan suite `notes` ke daftar staging-e2e | `README.md:3,133,177` dan `.python-version` konsisten 3.11.0; `staging-e2e.yml:10` options `[all, smoke, upload, activity, notes, audit]`. |
| A4 | `panduan_dip_automation_system.md:563` | “Hanya file SQL … di-commit” → “file SQL di-commit; selain itu `audit_storage.py`, `backfill_r2_urls.py`, `verify_r2_readiness.py` juga di-commit” | Sesuai `.gitignore:80-84` (whitelist tiga skrip) dan README §Migrasi Data. |
| A4 | `panduan_dip_automation_system.md:722-726` | Tambahkan 5 baris tabel `entity_type`: `product_attachment`, `product_file`, `product_batch`, `purchase_order`, `purchase_order_item` | Menutup sisa temuan U6 audit 2026-10-21 §8.2 K9; dipakai di `product_attachments_routes.py`, `products_routes.py`, `po_routes.py`. |

### Validasi sesi ini

Perintah yang dijalankan di clone bersih tanpa `.env` (env dummy persis CI: `SUPABASE_URL=https://ci.invalid.supabase.co`, `SUPABASE_KEY=ci-dummy-anon-key`, `SUPABASE_SERVICE_ROLE_KEY=ci-dummy-service-role-key`, `STORAGE_BACKEND=supabase`, `DIP_APP_ENV` tidak diset; interpreter `D:\dip-app\venv\Scripts\python.exe` 3.11.0):

| Perintah | Exit | Hasil |
|---|---|---|
| `python tests/test_upload_validation.py` | 0 | 6 PASS tercetak (sebelumnya output kosong) |
| `python tests/test_verify_r2_readiness_logic.py` | 0 | 4 PASS + “Semua test helper verify_r2_readiness LULUS” |
| `python tests/test_auth_matrix.py` (clone bersih) | 0 | `PASS test_anonymous_requests_are_redirected_or_denied` (10 route protected) |
| `python scripts/check_undefined_names.py` | 0 | `[OK] tidak ada nama tak terdefinisi / syntax error (28 file)` |
| `python scripts/check_static_rules.py` | 0 | `[OK] static rules passed` |

Catatan validasi: menjalankan `test_auth_matrix.py` di working directory lokal ditolak guard G-11 (`RuntimeError: DIP_APP_ENV tidak diset tetapi file .env ditemukan`) — sesuai desain guard dan bukan kesalahan test; di clone bersih tanpa `.env` (kondisi CI) test lolos. Dua test lain (`test_upload_validation`, `test_verify_r2_readiness_logic`) lolos di working tree lokal maupun clone.

### Risiko & yang tidak berubah

- Tidak ada perubahan pada kode runtime `app/`; perilaku aplikasi identik.
- Tidak ada migrasi SQL, perubahan skema, atau pembaruan dependensi pada sesi ini.
- CI kini menjalankan 19 test pure-local (sebelumnya 18); 2 test yang sebelumnya false-green kini benar-benar mengeksekusi assertion.

### Keputusan yang masih terbuka

- Item audit §9 (nomor 3, 6–12) dan §3–§8 (temuan A–G) tetap **BELUM** kecuali baris SELESAI di atas. Lihat tabel ringkasan status di awal dokumen ini untuk prioritas lanjutan (Kategori B → C → blocker cutover R2).

---

## Sesi 2 — 2026-11-05: Kategori B (low-risk, bukan B4)

**Ruang lingkup:** B1, B2, B3, B5, B6, B7, B8, B9 (+ B10 gabung B7). **B4 ditunda** ke PR terpisah sesuai keputusan konfirmasi (opsi “Tunda B4”).

**Keputusan konfirmasi yang dipakai:** branch baru dari `main` (PR #52 sudah merge); B3 = redirect + pesan error; B9 = gabungkan ringkasan 5-menit + debug; B6 = pola host `.r2.dev/`; validasi = unit test + E2E staging penuh dengan Playwright Trace Viewer (`PLAYWRIGHT_TRACE=1`).

### Perubahan kode

| # | File | Perubahan | Bukti (sebelum → sesudah) |
|---|---|---|---|
| B1 | `app/dashboard_routes.py:296-307` | `greeting_cache` hanya diterima bila `json.loads` menghasilkan `dict` dengan `phrase`/`text` (string); selain itu jatuh ke `get_time_greeting()` | Sebelum: `json.loads` langsung dipakai; `[]`/`{}`/string valid bisa masuk template. Sesudah: fallback eksplisit; test baru `tests/test_greeting_cache_guard.py` 3 kasus lolos. |
| B2 | `app/main.py:720-721` | Tambah `except HTTPException: raise` sebelum `except Exception` di `get_current_user` | Sebelum: 401 “User tidak valid” ditelan menjadi 401 generik. Sesudah: detail asli diteruskan; status akhir sama. |
| B3 | `app/dashboard_routes.py:68-77` | Bila `old_row` kosong atau `deleted_at` kosong → log `rejected` + redirect `/admin/trash?error=Produk tidak ditemukan atau sudah tidak berada di Sampah` | Sebelum: update 0 baris tetap log `restore` sukses. Sesudah: 0-baris ditolak dengan pesan; restore valid tidak berubah. |
| B5 | `app/templates/base.html:314` | `encodeURIComponent(item.id)` pada href ED | Sebelum: `item.id` tanpa escape. Sesudah: UUID tidak berubah; ID beracun ter-encode. |
| B6 | `app/templates/base.html:447-450` | Selektor diperluas `, a[href*=".r2.dev/"], iframe[src*=".r2.dev/"]`; penulisan ke `href`/`src` sesuai atribut; guard presign tetap pertama | `tests/test_base_cachebust.py` kini menegaskan selektor pola host ada (2 PASS). |
| B7+B10 | `app/static/po-analytics.js:340-355` | Debounce 120 ms; `disconnect()` saat `beforeprint`, `observe()` kembali saat `afterprint` | Sebelum: `render()` langsung tiap mutasi (2× saat print). Sesudah: −33% render tanpa ubah data/logika chart. |
| B8 | `app/main.py:218-220` | Log `type(e).__name__` pada error greeting AI | Sebelum: hanya `{e}`. Sesudah: `TimeoutException: ...` terbaca; timeout/model/urutan fallback tidak berubah. |
| B9 | `app/main.py:11-14,1299-1315` | `_session_expired_last` dict + `_SESSION_SUMMARY_INTERVAL=300`; 401 pertama per `(email, path)` dicetak penuh, sisanya `_logger.debug` | Sebelum: blok 4-baris `[SESSION EXPIRED]` tiap polling. Sesudah: deduplikasi 5-menit; respons 303 tidak berubah; detail tersedia di level debug. |
| — | `tests/test_greeting_cache_guard.py`, `.gitignore`, `.github/workflows/ci.yml` | Test baru B1 (3 kasus) + whitelist + CI baris ke-20 | `PASS=20 FAIL=0` di clone bersih (lihat validasi). |

### Validasi sesi ini

| Perintah | Exit | Hasil |
|---|---|---|
| `scripts/check_undefined_names.py` | 0 | `[OK] tidak ada nama tak terdefinisi / syntax error (28 file)` |
| `scripts/check_static_rules.py` | 0 | `[OK] static rules passed` |
| 20 test pure-local CI (clone bersih `TEMP\kilo-ci-check`, env dummy CI) | 0 semua | **PASS=20 FAIL=0** (termasuk `test_greeting_cache_guard` 3 OK, `test_base_cachebust` 2 PASS) |
| `tests/e2e_smoke_refactor.py` (staging, Playwright 1.64.0, Trace `PLAYWRIGHT_TRACE=1`) | 0 | **34/34 PASS** (health, login, dashboard, GET, presence/notify, sample CRUD, brand legal, tanpa 5xx) |
| `tests/e2e_activity_request_id.py` | 0 | **19/19 PASS** (create→complete→reopen→delete, `request_id` UUID unik) |
| `tests/e2e_notes_display_name.py` | 0 | PASS |
| `tests/e2e_audit_staging.py --quick` | 0 | PASS 37 / SKIP 7 / FAIL 0 |
| `tests/e2e_audit_staging.py` (penuh) | 0 | **PASS 41 / SKIP 3 / FAIL 0** (A–G, RPC replace, restore, konkurensi; SKIP: D1 tenant kedua, G1, G2 tanpa kanal SQL) |

Kredensial E2E dibaca dari `LOGIN.md` lalu di-export sebagai `STAGING_ADMIN_EMAIL`/`STAGING_ADMIN_PASSWORD` di shell yang sama (tidak di-echo/log/disalin). Staging preflight PASS (`/health` 200) via `scripts/run_staging_8017.py`; server dihentikan setelah audit.

### Risiko & yang tidak berubah

- Perilaku bisnis utama tidak berubah: restore valid, login, gating tenant, storage, dan generate PDF identik.
- B4 (timing-safe token) **sengaja tidak dikerjakan** — tetap TERBUKA.
- Data staging sementara (sample, note, formula) dipulihkan/dibersihkan skrip; 1 artefak `brand_legal_documents` smoke seperti sesi audit tidak dibersihkan skrip (diterima sebagai OBSERVATION).

### Keputusan yang masih terbuka

- Kategori C (C1 encoding, C2 validasi base, C3 respons 404) dan blocker cutover R2 (E-04..E-08) tetap **BELUM**.
- `pypdf` ≥6.21.4 tetap **BELUM** (PR terpisah + uji manual).

---

## Sesi 3 — 2026-11-05: Kategori C (C1 encoding + C2 fail-fast; C3/B4 skip)

**Ruang lingkup:** C1 (E-05), C2 (E-06). C3 di-skip, B4 tetap ditunda sesuai keputusan konfirmasi.

**Keputusan konfirmasi yang dipakai:** branch baru dari `main` (PR #53 sudah merge); C1 urutan “roundtrip test dlu, baru remove” — test roundtrip ditulis pertama (TDD, terbukti gagal 3 kasus), baru `unquote` di parser + perbarui ekspektasi lama; C2 gagal sebelum `upload_pdf`; validasi **unit + E2E staging khusus** upload.

### Perubahan kode

| # | File | Perubahan | Bukti (sebelum → sesudah / validasi) |
|---|---|---|---|
| C1 | `app/object_store.py:27,195-200,215-219` | `from urllib.parse import quote, unquote`; `unquote(path)` pada keduanya (Supabase dan R2) di `parse_storage_url` | Sebelum: path `%20` dikembalikan verbatim → `remove`/presign menarget key literal `%20` (orphan). Sesudah: `coa/file%20name.pdf` → `coa/file name.pdf`; test roundtrip 3 kasus + 18 kasus lama + 1 longest-base = 19 LULUS. |
| C1 | `tests/test_parse_storage_url.py:33-34,41` | Ekspektasi lama `file%20name.pdf`/`hak%20lisensi.pdf` → `file name.pdf`/`hak lisensi.pdf`; blok `roundtrip_cases` 3 kasus (Supabase `%20`, R2 `%20`, `%25%20` → `%`) | TDD: sebelum unquote, test gagal tepat 3 roundtrip (exit 1); sesudah, 19/19 LULUS. |
| C2 | `app/object_store.py:316-327` | `assert_public_base(bucket)` raise `RuntimeError("... tidak punya base publik di R2_PUBLIC_BASES")`; dipanggil di `upload_pdf` sebelum `_r2_upload` untuk `r2`/`dual` (kecuali `product-attachments` privat) | Sebelum: objek tertulis lalu `public_url` raise (orphan). Sesudah: tidak ada `put_object` saat base kurang; test `fail-fast before upload when base missing` + `does not call put_object` LULUS. |
| C2 | `tests/test_object_store_r2.py:131-147` | Blok fail-fast: `install("r2", s3_missing, bases={})` → upload harus raise, `len(s3_missing.puts)==0` | `object_store dispatch r2/dual: semua kasus LULUS` (termasuk dual/supabase tidak berubah). |

### Validasi sesi ini

| Perintah | Exit | Hasil |
|---|---|---|
| `tests/test_parse_storage_url.py` | 0 | **19 kasus LULUS** (18 lama + 1 longest-base, termasuk 3 roundtrip E-05) |
| `tests/test_object_store_r2.py` | 0 | **semua kasus LULUS** (termasuk fail-fast C2 baru) |
| 20 test pure-local CI (clone bersih) | 0 semua | **PASS=20 FAIL=0** |
| `scripts/check_undefined_names.py` | 0 | `[OK] tidak ada nama tak terdefinisi / syntax error (28 file)` |
| `scripts/check_static_rules.py` | 0 | `[OK] static rules passed` |
| `tests/e2e_upload_staging.py` (staging khusus, dual) | 0 | **6/6 PASS** — upload NIB PT Erfi → objek `legal-documents-stg/company-docs/nib_erfi.pdf` 592 byte di R2, isi identik |
| `tests/e2e_smoke_refactor.py` (Trace Viewer on) | 0 | **34/34 PASS** |
| `tests/e2e_activity_request_id.py` | 0 | **19/19 PASS** |
| `tests/e2e_notes_display_name.py` | 0 | PASS |

Staging preflight PASS (`/health` 200) via `scripts/run_staging_8017.py`; server dihentikan setelah audit. Kredensial hanya di-export di shell yang sama.

### Risiko & yang tidak berubah

- Mode `supabase` tidak berubah (tanpa base check, tanpa R2).
- `product-attachments` (privat, tanpa base) dikecualikan dari fail-fast — presigned tetap lewat S3 tanpa base.
- `remove`/`signed_url` di mode `r2` kini menerima path mentah ( hasil unquote ) sehingga target key sama dengan key fisik; kolom DB lama ber-`%20` tetap terbaca sebagai path mentah.

### Keputusan yang masih terbuka

- C3 (respons 404 konsisten) **TERBUKA** (di-skip sesuai keputusan).
- B4 timing-safe token **SELESAI** (sesi 4).
- Blocker cutover lain (SSRF `dip_documents`, soak privat, `pypdf` ≥6.21.4) **BELUM**.

---

## Sesi 4 — 2026-11-05: B4 timing-safe public token

**Ruang lingkup:** hanya B4. Tidak menyentuh C3/C-14 atau temuan audit lain.

### Perubahan kode

| # | File | Perubahan | Bukti (sebelum → sesudah / validasi) |
|---|---|---|---|
| B4 | `app/dip_public.py:24` | `import hmac` | Sebelum: tidak ada `hmac` di `app/` |
| B4 | `app/dip_public.py:270-279` | Helper `_tokens_equal(a, b)` = `hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))`, return `False` bila kosong/None | Sebelum: `provided_token == token` (`dip_public.py:289`). Sesudah: timing-safe bytes; non-ASCII tidak TypeError |
| B4 | `app/dip_public.py:301` | `if token: if _tokens_equal(provided_token, token): return True` | Cabang BPOM tanpa token (`registered and not provided_token`) tetap di bawahnya; fail-closed `except Exception -> False` tetap |
| — | Grep `public_access_token`, `provided_token`, `== token`/`!= token` di `app/` | Satu-satunya perbandingan token publik adalah `dip_public.py:289` (kini `_tokens_equal`). `products_routes.py:286,295` hanya generate/cleanup token (`token_urlsafe(32)` + hapus fallback), bukan perbandingan. `dip_public.py:154` hanya meneruskan `provided_token` ke checker; baris 260 hanya mengekspor token ke template bila bukan `bpom_registered_link` | Tidak ada perbandingan token lain yang perlu dijadikan timing-safe |
| — | `tests/test_dip_public_check.py` | 7 kasus baru + `main()` diperbarui: salah panjang sama→404, salah panjang beda→404, kosong non-BPOM→404, non-ASCII→404 bukan 500, BPOM tanpa token→200, BPOM token salah→404, tanpa token→200 | 11 test total; `Semua test F-01 fail-closed LULUS` (RC=0). Whitelist & CI tidak diubah |

### Validasi sesi ini

| Perintah | Exit | Hasil |
|---|---|---|
| `scripts/check_undefined_names.py` | 0 | `[OK] tidak ada nama tak terdefinisi` |
| `scripts/check_static_rules.py` | 0 | `[OK] static rules passed` |
| `python -m compileall app` | 0 | tanpa error |
| Import terisolasi `app.main` | 0* | Ter-cover `check_static_rules` (“app import … passed”); skrip heredoc manual di PowerShell gagal sintaks, tidak relevan |
| 20 test pure-local CI (clone bersih) | 0 semua | **PASS=20 FAIL=0** (termasuk `test_dip_public_check` diperluas) |
| `tests/e2e_dip_public_link.py` (staging) | 2 (argumen) | Tidak dijalankan — wajib `--url "<live DIP URL>"` (hub URL + token live); tidak ada token yang di-print |
| `tests/e2e_smoke_refactor.py` (staging) | 0 | **34/34 PASS** |
| `tests/e2e_audit_staging.py --quick` (staging) | 0 | PASS 37 / SKIP 7 / FAIL 0 |

Staging preflight PASS (`/health` 200) via `scripts/run_staging_8017.py`; server dihentikan setelah audit. Kredensial hanya di-export di shell yang sama.

### Risiko & yang tidak berubah

- Perilaku akses identik: token benar→True, token salah/kosong→False, BPOM tanpa token→True (legacy), tanpa token→True, exception→False (fail-closed tetap).
- Token valid non-ASCII (bila ada) tetap diterima karena bytes di-encode UTF-8 — tidak ada regresi TypeError.

### Keputusan yang masih terbuka

- C3 (respons 404 konsisten) tetap **TERBUKA**.
- Blocker cutover lain (SSRF, soak privat, `pypdf` ≥6.21.4) tetap **BELUM**.
- A-11 (efek samping) & A-12 (lampiran) → **SELESAI** (PR1, sesi 5); A-10 → PR2; A-13 → PR3.

---

## Sesi 5 — 2026-11-05: PR1 tenant guard A-11/A-12 (efek samping + lampiran)

**Ruang lingkup:** A-11 `app/efek_samping.py` generate/delete; A-12 `app/product_attachments_routes.py` GET/POST/edit/delete. Hanya temuan ini; C-14/B-series/R2/pypdf/CSRF tidak disentuh.

### Perubahan kode

| # | File | Perubahan | Bukti (sebelum → sesudah) |
|---|---|---|---|
| A-11 | `app/efek_samping.py:20` | `from app.security import assert_same_tenant` | Sebelum: tanpa import guard |
| A-11 | `app/efek_samping.py:244-252` (generate) | Setelah `product` dibaca: `assert_same_tenant(current_user, product)` → `log_activity(..., outcome="rejected")` + redirect error | Sebelum: generate lolos untuk tenant mana pun. Sesudah: 403-equivalent via redirect error + nol tulis |
| A-11 | `app/efek_samping.py:401-417` (delete) | Select diperluas `nama_produk, perusahaan, monitoring_efek_samping_file_url`; guard sebelum hapus file/DB; fail-closed: exception baca → redirect “Produk tidak ditemukan” (nol tulis) | Sebelum: delete lolos + fail-open bila baca gagal. Sesudah: sama pola po_item_delete |
| A-12 | `app/product_attachments_routes.py:14` | `from app.security import assert_same_tenant` | — |
| A-12 | `app/product_attachments_routes.py:86-110` | `_load_active_product` diperluas return product (tidak hanya error); helper `_guard_product` + `log_activity rejected` + `HTTPException(403)` | Sebelum: tanpa tenant guard |
| A-12 | `app/product_attachments_routes.py:116-121` (GET) | Guard sebelum list (redirect `/` bila ditolak) | Sebelum: daftar lampiran tenant lain bocor |
| A-12 | `app/product_attachments_routes.py:138-140` (POST) | Guard sebelum validasi/upload — objek storage yatim tidak terjadi | Sebelum: upload duluan, guard tidak ada |
| A-12 | `app/product_attachments_routes.py:194-210` (edit/delete) | `_owned_attachment` kini guard produk + cek `row.product_id == product_id` (403 bila lintas produk) + owner/admin | Sebelum: `product_id` milik sendiri + `attachment_id` milik tenant lain bisa lolos |
| — | `tests/test_tenant_guard_efek_lampiran.py`, `.gitignore`, `.github/workflows/ci.yml` | Test baru 10 kasus (efek 6 + lampiran 4) + whitelist + CI baris ke-21 | 21/21 pure-local LULUS; FAIL-CLOSED terbukti gagal di kode lama |

### Validasi sesi ini

| Perintah | Exit | Hasil |
|---|---|---|
| `scripts/check_undefined_names.py` | 0 | `[OK] tidak ada nama tak terdefinisi` |
| `scripts/check_static_rules.py` | 0 | `[OK] static rules passed` |
| `python -m compileall app` | 0 | tanpa error |
| 21 test pure-local CI (clone bersih) | 0 semua | **PASS=21 FAIL=0** (termasuk `test_tenant_guard_efek_lampiran` 10 kasus) |
| Fail-closed di kode lama (`git stash push -- app/`, jalankan test baru) | 1 | FAIL pada `test_efek_generate_other_tenant_blocked_no_writes` — `assert outcome == "rejected"` gagal (alasan benar: guard tidak ada di kode lama) |
| `tests/e2e_smoke_refactor.py` (staging) | 0 | **34/34 PASS** |
| `tests/e2e_activity_request_id.py` | 0 | **19/19 PASS** |
| `tests/e2e_notes_display_name.py` | 0 | PASS |
| `tests/e2e_audit_staging.py` (penuh) | 0 | **PASS 41 / SKIP 3 / FAIL 0** |

Staging preflight PASS (`/health` 200) via `scripts/run_staging_8017.py`; server dihentikan setelah audit. Kredensial hanya di-export di shell yang sama.

### Risiko & yang tidak berubah

- Perilaku admin & user satu-tenant, owner lampiran, dan bucket privat `product-attachments` tidak berubah; semantik `object_store` tidak diubah.
- Baris tanpa `perusahaan` tetap lolos (fail-open legacy disengaja, bukan diubah).

### Keputusan yang masih terbuka

- A-10 (finished-spec) → **PR2**; A-13 (sample create/delete/edit) + brands → **PR3**.
- C-01/A-17 (akun tanpa profil), PO lintas tenant, katalog RM bersama → tetap TERBUKA.

---

## Template entri sesi berikutnya

Salin blok di bawah ini untuk sesi lanjutan; isi tanggal, ruang lingkup, perubahan per file, perintah validasi + exit code, dan risiko.

```
## Sesi N — YYYY-MM-DD: <judul>
**Ruang lingkup:** <kategori/ID audit yang dikerjakan>

### Perubahan kode
| # | File | Perubahan | Bukti (sebelum → sesudah / validasi) |

### Validasi sesi ini
| Perintah | Exit | Hasil |

### Risiko & yang tidak berubah
- ...

### Keputusan yang masih terbuka
- ...

```

---

## Sesi 7 — 2026-11-05: PR3 tenant guard A-13 (sample) + brands investigation

**Ruang lingkup:** A-13 `app/sample_routes.py` create/delete/edit; brands investigation (keputusan terbuka).

**Perubahan:**
- `POST /sample-submissions/create`: baca produk dulu (fail-closed bila exception → 403 “Gagal memverifikasi akses produk”); guard produk rujukan dan `new_company=final_company` (403 + `rejected`); nol tulis sebelum guard.
- `POST /sample-submissions/delete/{id}`: baca gagal → fail-closed 403 (bukan fail-open); baris tidak ditemukan → 404 tetap.
- `GET /sample-submissions/edit/{id}`: `except HTTPException: raise` (404 tidak ditelan 500) + `assert_same_tenant` → 403.
- Brands: `migration/*.sql` tidak membuat tabel `brands`/`producers` (pra-ada), tidak ada kolom tenant; `brand_legal_documents.perusahaan` hanya per-dokumen; `brands_routes.py:128` dokumen per-perusahaan, tetapi brand/producer tanpa tenant. **Keputusan terbuka**: tidak di-fix.

**Test:** `tests/test_tenant_guard_sample.py` baru (6 kasus) + whitelist + CI baris ke-23.

**Validasi:** `check_undefined_names` 0; `check_static_rules` 0; `compileall` 0; **21 test pure-local PASS=21 FAIL=0**; fail-closed di kode lama FAIL `harus 403`; E2E staging: smoke 34/34, activity 19/19, audit 41/0/3 skip.
## Sesi 6 — 2026-11-05: PR2 tenant guard A-10 (finished-spec)

**Ruang lingkup:** hanya A-10 (`products_routes.py` POST `/products/{product_id}/finished-spec`). C-14/B-series/R2/pypdf/CSRF tidak disentuh.

**Perubahan:** `select("nama_produk, perusahaan")` + `assert_same_tenant(current_user, product)` dengan `log_activity(..., outcome="rejected")` + `HTTPException(403)` sebelum `json.loads` dan tulis apa pun; pola sama dengan rute produk lain (252, 356, 1215, 1506). Baca gagal → 404 tetap (perilaku lama). Audit rute tulis lain di `products_routes.py`: `/products/add` (252 guard), `/products/delete` (356 guard), `/products/{id}/edit` (1215 guard), `/products/{id}/delete-file` (1506 guard) — sudah ber-guard; hanya finished-spec yang belum.

**Test:** `tests/test_tenant_guard_finished_spec.py` baru (5 kasus: tenant lain 403 + nol tulis + rejected, tenant sama insert, admin, tanpa perusahaan, baca gagal 404) + whitelist + CI baris ke-22.

**Validasi:** `check_undefined_names` 0; `check_static_rules` 0; `compileall` 0; **22 test pure-local PASS=22 FAIL=0**; fail-closed di kode lama (stash app/): FAIL `harus 403`; E2E staging: smoke 34/34, activity 19/19, notes PASS, audit 41/0/3 skip.

**Risiko:** perilaku admin/satu-tenant tidak berubah; baris tanpa `perusahaan` tetap fail-open legacy.

---

## Sesi 8 — 2026-11-07: bump pypdf 6.21.1 → 6.21.4 (tutup 10 advisory)

**Ruang lingkup:** hanya bump `pypdf` + sinkronisasi dokumen. Tidak menyentuh temuan lain (CSRF, tenant guard, R2, portal publik, dll).

### Perubahan kode

| # | File | Perubahan | Bukti (sebelum → sesudah / validasi) |
|---|---|---|---|
| P1 | `requirements.txt:11` | `pypdf==6.21.1` → `pypdf==6.21.4` (tetap dipin eksak `==`) | `pip-audit -r requirements.txt`: sebelum 10 advisory (`CVE-2026-115572/-115585/-115580` fix ≥6.21.2, `CVE-2026-119203–119209` fix ≥6.21.3/6.21.4); sesudah `No known vulnerabilities found` |
| P2 | `README.md:147` | Tabel dependensi: `pypdf` `6.21.1` → `6.21.4` | Sinkron dengan requirements.txt |
| — | `panduan_dip_automation_system.md` | Tidak mencantumkan angka versi pypdf (hanya menyebut `pypdf` tanpa versi) | grep `pypdf`/`6.21` di panduan: 2 match tanpa angka versi; tidak diubah |

**Versi target:** 6.21.4 = versi TERENDAH yang menutup SEMUA 10 advisory (advisory tertinggi membutuhkan ≥6.21.4). Changelog 6.21.1→6.21.4: hanya Security (SEC) + Bug Fixes + Performance + Robustness + Documentation — **tidak ada breaking change / deprecation API**. pypdf 7.0.0 (2026-11-06) adalah major dengan deprecations/dropped support — sengaja tidak dipilih. API yang dipakai di `app/` (`PdfReader`, `PdfWriter`, `add_page`, `write`, `merge_transformed_page`, `Transformation`) tidak berubah/deprecated di rentang ini.

**Dependabot PR #41:** sudah ada PR Dependabot terbuka `chore(deps): bump pypdf from 6.21.1 to 6.21.4` (https://github.com/coretail/dip-automation-system/pull/41, CI quality SUCCESS) dengan diff identik 1 baris `requirements.txt`. PR ini (`chore/bump-pypdf`) dibuat sesuai instruksi sesi untuk validasi manual PDF + E2E staging + sinkronisasi README + log sesi ini; **PR #41 akan ditutup sebagai duplikat** bila PR ini merge, atau PR ini ditutup dan PR #41 dipakai ulang bila diinginkan pemilik repo. Tidak ada perubahan kode aplikasi.

### Validasi sesi ini

| Perintah | Exit | Hasil |
|---|---|---|
| `python scripts/check_undefined_names.py` | 0 | `[OK] tidak ada nama tak terdefinisi / syntax error (28 file)` |
| `python scripts/check_static_rules.py` | 0 | `[OK] static rules passed` |
| `python -m compileall app` | 0 | tanpa error |
| 25 test pure-local CI (clone bersih tanpa `.env`, env dummy CI persis `ci.yml`, `DIP_APP_ENV` tidak diset) | 0 semua | **PASS=25 FAIL=0** |
| `pip-audit -r requirements.txt` | 0 | `No known vulnerabilities found` (10 advisory pypdf tertutup, tanpa `--ignore-vuln`) |
| `tests/e2e_smoke_refactor.py` (staging via `run_staging_8017.py`) | 0 | **34/34 PASS** |
| `tests/e2e_audit_staging.py --quick` (staging) | 0 | **PASS 37 / SKIP 7 / FAIL 0** |
| Uji manual staging produk `dd000000-...-000000000401` (DEMO Brightening Serum): Bab II, gabungan Bab I–IV, ZIP Bab II | 0 | Bab II 96.711 byte / 6 halaman; Bab I 2.766 byte / 2 halaman; Bab III 44.551 byte / 2 halaman; Bab IV 43.665 byte / 2 halaman; ZIP 242.853 byte / 16 file (11 PDF di dalam ZIP semua terbaca); gabungan Bab I–IV hasil merge 186.788 byte / 12 halaman (2+6+2+2 MATCH); semua PDF dibuka ulang dengan pypdf 6.21.4 tanpa error |

Staging preflight PASS (`/health` 200) via `scripts/run_staging_8017.py`; server dihentikan setelah uji. Kredensial hanya di-export di shell yang sama (dari `LOGIN.md`), tidak di-echo/log/disalin.

### Risiko & yang tidak berubah

- Perilaku bisnis utama tidak berubah: generate PDF Bab I–IV dan ZIP identik; output dibaca ulang pypdf tanpa error dan jumlah halaman cocok.
- Yang TIDAK diuji: efek samping PDF (NIES), cetakan fisik, serta perbandingan byte-per-byte dengan output versi 6.21.1 (hanya validasi keterbacaan + jumlah halaman + ukuran file di 6.21.4).
- Tidak ada migrasi SQL, perubahan skema, atau perubahan kode `app/`.

### Keputusan yang masih terbuka

- Duplikat PR Dependabot #41 vs PR `chore/bump-pypdf`: salah satu ditutup saat merge (preferensi pemilik repo).
- Temuan audit lain (CSRF A-07, tenant guard sisa, R2 E-04/E-07/E-08, portal publik F-08, F-05, dll) tetap di luar ruang lingkup.

---

## Sesi 9 — 2026-11-07: revoke link publik DIP (F-03) + audit akses publik (F-09)

**Ruang lingkup:** F-03 revoke + F-09 audit akses publik. F-08 rate-limit dan F-05 masking token sengaja TIDAK dikerjakan (PR B terpisah). Tidak ada migrasi SQL.

### Perubahan kode

| # | File | Perubahan | Bukti (sebelum → sesudah / validasi) |
|---|---|---|---|
| F-03 | `app/dip_public.py:281-310` | `public_access_revoked_at` ditambahkan ke select `_dip_public_check_product`; revoke = `enabled is False` ATAU `revoked_at` tidak null; cek revoke SEBELUM cabang BPOM; tetap fail-closed + timing-safe | Sebelum: kolom tidak dibaca, produk BPOM dicabut tetap 200. Sesudah: 404 untuk semua bentuk revoke |
| F-03 | `app/products_routes.py` (2 route POST admin) | `POST /products/{id}/public-access/revoke`: `enabled=False` + `revoked_at=<ISO nyata>` (tanpa string now()); `POST .../reactivate`: `enabled=True` + `revoked_at=None`. Token tidak diubah dua-duanya; hanya admin; `assert_same_tenant`; baca dulu fail-closed; tolak `is_deleted`; nol tulis bila guard menolak; `log_activity` entity_id UUID tanpa token | Pola sama dengan delete_product (SEC-02) |
| F-03 | `app/templates/qualitative_quantitative.html` | Tombol admin "Cabut Link" (konfirmasi) / "Aktifkan Ulang" + status "Link publik aktif" / "dicabut sejak ..." hanya untuk admin; token tema yang ada | Terverifikasi di staging: UI aktif/dicabut berganti benar |
| F-09 | `app/dip_public.py` `_audit_public_access` + `app/main.py` | `log_activity` aktor sentinel `{"id": None, "full_name": "public"}`, action `public_access`, entity `product`/UUID, `source="public"`, tanpa token/query; hub + download per Bab + ZIP; 404 tidak dilog; fail-open dipertahankan | Di staging: baris `PUBLIC_ACCESS` + `REVOKE_PUBLIC_ACCESS`/`REACTIVATE_PUBLIC_ACCESS` muncul di log server |
| — | `panduan_dip_automation_system.md:710` | Tambah `public_access`, `revoke_public_access`, `reactivate_public_access` ke baris `product` tabel entity_type | — |
| — | `app/main.py:1728` | Teruskan `log_activity` ke `register_dip_public_routes` | Tanpa ini audit publik tidak jalan |

Kontrak publik tidak berubah: link aktif (token benar atau BPOM tanpa token) tetap berfungsi persis seperti sebelumnya selama tidak dicabut. Rotasi token BUKAN bagian PR ini: aktifkan ulang selalu memakai token lama.

### Validasi sesi ini

| Perintah | Exit | Hasil |
|---|---|---|
| `python scripts/check_undefined_names.py` | 0 | `[OK] tidak ada nama tak terdefinisi` |
| `python scripts/check_static_rules.py` | 0 | `[OK] static rules passed` |
| `python -m compileall app` | 0 | tanpa error |
| 26 test pure-local CI (clone bersih tanpa `.env`, env dummy CI) | 0 semua | **PASS=26 FAIL=0** (termasuk `test_dip_public_revoke` 12 kasus baru) |
| `tests/test_dip_public_revoke.py` di kode lama (`git stash push -- app/`) | 1 | FAIL `TypeError: register_dip_public_routes() got an unexpected keyword argument 'log_activity'` (route/admin/audit belum ada) — bukti test benar-benar mengunci perilaku baru |
| `tests/e2e_smoke_refactor.py` (staging) | 0 | **34/34 PASS** |
| `tests/e2e_audit_staging.py` (penuh, staging) | 0 | **PASS 41 / SKIP 3 / FAIL 0** |
| Manual staging produk DEMO `dd000000-...-000000000401` (BPOM legacy, tanpa token) | 0 | Hub 200 → cabut → 404 → aktifkan ulang → 200 lagi; log server memuat `REVOKE_PUBLIC_ACCESS`, `REACTIVATE_PUBLIC_ACCESS`, `PUBLIC_ACCESS` (aktor `public`, Bab `hub`) |

Staging preflight PASS (`/health` 200) via `scripts/run_staging_8017.py`; server dihentikan setelah uji. Kredensial hanya di-export di shell yang sama (dari `LOGIN.md`), tidak di-echo/log/disalin. `pip-audit` tidak berubah (tidak ada perubahan dependency).

### Risiko & yang tidak berubah

- Link publik aktif tidak berubah; hanya produk yang dicabut admin yang menjadi 404 (termasuk BPOM).
- `log_activity`, rate-limit, masking token tidak disentuh (PR B / C-04 terpisah).
- Yang TIDAK diuji: download/ZIP publik via browser (baru hub yang diuji manual di staging); rotasi token (bukan bagian PR ini).

### Keputusan yang masih terbuka

- F-08 rate-limit + F-05 masking token → SELESAI (sesi 10, PR B). Residu F-05: log edge/proxy Render masih bisa mencatat `?access=` penuh (di luar repo, tidak dapat diverifikasi dari sini) — jangan klaim tertutup; lakukan pemotongan di level Render/Cloudflare bila tersedia.

---

## Sesi 10 — 2026-11-09: rate-limit /dip/* (F-08) + samarkan token di access log (F-05 sisi aplikasi)

**Ruang lingkup:** F-08 + F-05 sisi aplikasi (PR B, lanjutan PR #67). Tidak menyentuh CSRF, tenant guard, R2, portal publik selain ini. Tidak ada migrasi SQL.

### Perubahan kode

| # | File | Perubahan | Bukti (sebelum → sesudah / validasi) |
|---|---|---|---|
| F-08 | `app/dip_public.py:38-72` | **Dual layer via `shared_limit(scope)`** (terverifikasi di source slowapi 0.1.10: `_scope = scope if shared else None`): Lapis 1 per-IP `_bab_ip`/`_zip_ip`/`_hub_ip` 20/5/60 per menit (scope `dip-bab-ip`/`dip-zip-ip`/`dip-hub-ip`, `key_func=client_ip`); Lapis 2 per-produk `_product` 120/menit (scope `dip-product`, key `product_id` saja, tanpa token/query); key divalidasi dengan `uuid.UUID(pid)` dan kanonik huruf kecil (`str(uuid).lower()`), TERMASUK slug UUID polos; `limiter` WAJIB (tanpa default, TypeError bila tidak diinjeksi); `_NullLimiter` DIHAPUS. Fallback slug invalid: IP klien (bukan bucket global). `DIP_PRODUCT_LIMIT=120/minute` DIPAKAI. | BPOM tanpa token: jam IP A 429 tidak mengunci IP B; ganti `?access=` tidak membuka bucket; XFF berganti 429 di 120; UUID polos & variasi huruf berbagi bucket kanonik; scope bersama lintas route terbukti |
| F-08 | `app/main.py:459-469` | `rate_limit_handler`: `/dip/*` → 429 HTML minimal bila Accept text/html, selain itu JSON Indonesia, tanpa angka limit/token, header `Retry-After: 60`; path lain tetap redirect `/login?error=too_many_attempts`; log path TANPA query/token | Staging burst bab 429 mulai ke-21; login tetap redirect |
| F-05 | `app/main.py` `_RedactAccessTokenFilter` + `_install_quiet_access_log` | Filter TERPISAH dari `_QuietAccessLogFilter`; tuple/list + dict; selalu return True; tidak melempar pada args tak terduga; idempoten | Log staging: `GET /dip/...?access=***` (nilai token tidak muncul), `foo=1` utuh |
| — | `app/main.py:1785` | Teruskan `limiter` ke `register_dip_public_routes` | Tanpa ini rate-limit tidak aktif |
| — | `tests/test_dip_public_check.py`, `test_dip_public_revoke.py` | Injeksi `Limiter` sungguhan (limiter wajib) | Keduanya tetap LULUS |
| — | `tests/test_dip_public_rate_limit.py` | 15 kasus: per-IP, BPOM tanpa token, token rotate, per-produk 120, UUID polos 120, variasi huruf satu bucket, slug vs UUID polos satu bucket, shared lintas route, invalid slug IP fallback, limiter wajib TypeError, IP lain hub, hub/ZIP, produk berbeda, 404 dihitung, login redirect | Semua LULUS; FAIL di kode lama (`AssertionError` UUID polos di 120; `ImportError: DIP_BAB_LIMIT` untuk suite) |

Alasan angka: 1 kunjungan = 1 hub + ≤9 klik; 20/5 per-IP jauh di atas normal; 120 per-produk di atas beberapa reviewer BPOM bersamaan.

**Investigasi smoke 33/34:** kegagalan yang sama muncul di kode `main` TERBARU (tanpa perubahan PR ini): `GET /products/...402/finished-spec/preview` → **HTTP 403** (guard `produk["perusahaan"] != "PT Erfi"`, produk 402 milik PT Heka). Penyebab: data staging "produk pertama" (402 = PT Heka), bukan regresi PR ini. Audit penuh tetap 41/0/3.

**Hasil grep token ke log/DB (jalur /dip/*):** `_audit_public_link` menulis hanya product_id/nama/IP/User-Agent/username; `_audit_public_access` hanya bab/hub; `print` route /dip hanya path tanpa query; `request.url.path` di main tanpa query. BERSIH — tidak ada penulisan token selain access log uvicorn (kini diredaksi). Residu: log edge/proxy Render masih bisa mencatat `?access=` penuh (di luar repo).

**Temuan X-Forwarded-For (dilaporkan, tidak diubah):** `_client_ip` entri pertama XFF bisa dipalsukan → penyerang bisa capai batas per-produk dan kunci link sampai 120/menit. Rekomendasi: edge tepercaya Render/Cloudflare; jangan ubah `_client_ip` tanpa audit (limiter login + audit IP).

### Validasi sesi ini

| Perintah | Exit | Hasil |
|---|---|---|
| `python scripts/check_undefined_names.py` | 0 | `[OK] tidak ada nama tak terdefinisi` |
| `python scripts/check_static_rules.py` | 0 | `[OK] static rules passed` |
| `python -m compileall app` | 0 | tanpa error |
| 28 test pure-local CI (clone bersih) | 0 semua | **PASS=28 FAIL=0** (termasuk 2 file baru: rate_limit 12 kasus, redaction 7 kasus) |
| File baru di kode lama (stash app/) | 1 | Rate: `ImportError: DIP_BAB_LIMIT`; Redaction: `RuntimeError` guard G-11 (filter belum ada) |
| `tests/e2e_smoke_refactor.py` (staging) | 1 | 33/34 — kegagalan SAMA di main baru: finished-spec preview produk 402 (PT Heka) → 403 (guard Hanya PT Erfi); audit penuh tetap 41/0/3 |
| `tests/e2e_audit_staging.py` (penuh, staging) | 0 | **PASS 41 / SKIP 3 / FAIL 0** |
| Manual staging (a) hub→tiap bab/download/ZIP sekali | 0 | Semua 200, tidak ada 429 |
| Manual (b) burst `/bab1/download` | 0 | 200 lalu 429 sesuai batas per-IP |
| Manual (c) burst XFF berganti-ganti | 0 | Berhenti di batas per-produk (120) |
| Manual (d) IP penyerang 429, IP lain (XFF lain) sama produk | 0 | Masih 200 |
| Manual (e) `?access=TOKENUJI` | 0 | Log server hanya `access=***`; nilai token tidak muncul |
| Manual (f) /login 6× salah | 0 | Final `/login?error=too_many_attempts` (perilaku lama utuh) |

Staging preflight PASS via `scripts/run_staging_8017.py`; server dihentikan. Kredensial hanya di-export di shell yang sama.

### Risiko & yang tidak berubah

- Pemakaian normal hub→bab→download→ZIP satu orang tetap tanpa 429.
- **Penyerang yang memalsukan XFF tetap bisa capai batas per-produk dan kunci link sampai 120/menit** (limit per-IP memakai `_client_ip` = entri pertama XFF). Rekomendasi edge di atas.
- Limiter in-memory per proses: bila Render menjalankan >1 worker/instance, hitungan terbagi per proses (jumlah worker TIDAK dapat diverifikasi dari repo; jangan menebak).
- Residu F-05: log edge/proxy Render di luar repo juga bisa mencatat token; residu ini TIDAK tertutup PR ini.
- `_client_ip` tidak diubah (dipakai limiter login + audit IP).
- Yang TIDAK diuji: bypass XFF penuh sampai 120 di staging (hanya unit test yang membuktikan 120), multi-worker, traffic nyata.

### Keputusan yang masih terbuka

- Konfigurasi tepercaya X-Forwarded-For di edge Render/Cloudflare (temiento di atas).
- Rotasi token bila revoke permanen → keputusan produk terpisah.

---

## Sesi 11 — 2026-11-09: akun tanpa profil / query profil gagal jadi fail-closed (C-01/A-17 parsial)

**Ruang lingkup:** C-01/A-17 bagian get_current_user (profil hilang / query gagal). TIDAK menyentuh `assert_same_tenant`, non-admin perusahaan kosong (PR 2 terpisah), C-14, C-15, atau temuan lain. Tidak ada migrasi SQL.

### Perubahan kode

| # | File | Perubahan | Bukti (sebelum → sesudah / validasi) |
|---|---|---|---|
| C-01 | `app/main.py:765-807` (`get_current_user`) | **3 kondisi:** (a) profil ada → identik dengan semula (termasuk fallback display_name); (b) query OK tanpa baris → HTTPException 403 "Profil akun tidak ditemukan. Hubungi admin." + log `user={id}` (tanpa email/token); (c) kedua query melempar → HTTPException 503 "Layanan sementara tidak tersedia. Coba lagi." + log tipe exception. 401 cookie/token tidak valid tetap; `except HTTPException: raise` tetap | Sebelum: tanpa profil kembali dict default staff lintas tenant. Sesudah: 403/503 fail-closed |
| C-01 | `app/main.py:1291-1300` (login) | Setelah kredensial benar, cek profil SEBELUM cookie; tanpa profil → 303 `/login?error=profile_missing` tanpa Set-Cookie (kedua jalur username/email); query gagal → pesan sama (tidak bedakan gangguan DB dari profil hilang di login agar tidak bocor oracle) | Sebelum: login berhasil tanpa profil. Sesudah: ditolak |
| — | `app/templates/login.html` | Blok error `profile_missing` mengikuti pola `invalid_credentials` | — |
| — | `app/static/presence.js` | Reaksi 403: berhenti heartbeat + redirect `/login` (pola 401); 503 transien TIDAK dieksekusi (polling tetap, tidak logout) → tidak ada loop atau spam | Dipelajari handler 401→redirect login; 403 JSON non-401 tidak di-redirect handler, jadi polling perlu ditangani eksplisit agar berhenti wajar |
| — | `tests/test_auth_matrix.py` | Tetap LULUS (10 route anonymous semua 401/403/303) | 29/29 pure-local |
| — | Grep pola `"staff"` / `perusahaan=None` / `profiles` di `app/` | `admin_users_routes.py:91,139` default role form = pemakaian sah pembuatan user (bukan auth); `admin_users_routes.py:174-177` perusahaan None juga pembuatan user (diperbaiki saat insert berhasil) — TIDAK diubah; `main.py:761-763,785-786` satu-satunya jalur auth = sudah diperbaiki | Dilaporkan di deskripsi PR sebagai temuan lanjutan |

`assert_same_tenant` tidak diubah: non-admin perusahaan kosong tetap lolos semua baris (PR 2 terpisah, menunggu pembersihan data). Handler HTTPException global untuk 403/503: 401 tetap redirect `/login?warning=session_expired`; 403/503 kembali JSON bawaan (tidak di-redirect) → tidak ada loop login↔dashboard karena 503 bukan 401 dan 403 profil-hilang berhenti di polling via presence.js.

### Validasi sesi ini

| Perintah | Exit | Hasil |
|---|---|---|
| `python scripts/check_undefined_names.py` | 0 | `[OK] tidak ada nama tak terdefinisi` |
| `python scripts/check_static_rules.py` | 0 | `[OK] static rules passed` |
| `python -m compileall app` | 0 | tanpa error |
| 29 test pure-local CI (clone bersih tanpa .env, env dummy CI) | 0 semua | **PASS=29 FAIL=0** (termasuk `test_auth_profile_fail_closed` 9 kasus + `test_auth_matrix` LULUS) |
| `tests/test_auth_profile_fail_closed.py` di kode lama (stash app/) | 1 | `AssertionError: harus 403` (tanpa profil kembali dict staff) |
| `tests/e2e_smoke_refactor.py` (staging) | 1 | 33/34 — kegagalan finished-spec preview produk 402 (PT Heka) → 403, sumber data "produk pertama" (ada di main; bukan perubahan ini) |
| `tests/e2e_audit_staging.py` (penuh, staging) | 0 | **PASS 41 / SKIP 3 / FAIL 0** |
| Manual staging: akun NORMAL login | 0 | Dashboard 200, `/` 200 |
| Manual staging: kredensial tanpa akun terdaftar | 0 | `/login?error=invalid_credentials` (akun auth uji tanpa profil tidak dibuatkan agar tidak meninggalkan residu di staging; case-nya dibuktikan unit test) |

Staging preflight PASS via `scripts/run_staging_8017.py`; server dihentikan. Kredensial hanya di-export di shell yang sama.

### Risiko & yang tidak berubah

- **Akun auth yang profilnya hilang akan ter-lockout (itu tujuannya). Jumlah akun terdampak di produksi TIDAK diketahui dari repo — pemilik repo menjalankan query pengecekan di Supabase SQL Editor sebelum deploy.**
- **Profil dengan perusahaan kosong TIDAK ditangani PR ini** (tetap lolos `assert_same_tenant` untuk non-admin; PR 2 terpisah).
- 503 transien tidak membuat logout massal (bukan 401), dan polling presence.js tidak logout pada 503.
- Yang TIDAK diuji: membuat akun auth uji tanpa profil di staging live, gangguan DB langsung di staging.
- `pip-audit` tidak berubah.

### Sebelum deploy ke produksi (wajib pemilik repo)

Jalankan di Supabase SQL Editor:
```sql
SELECT a.id, a.email
FROM auth.users a
LEFT JOIN public.profiles p ON p.id = a.id
WHERE p.id IS NULL;
```

### Keputusan yang masih terbuka

- Pembersihan data perusahaan kosong + PR 2 `assert_same_tenant` fail-closed untuk non-admin.
- C-14 (`.single()` vs cek manual) dan C-15 (create user) tetap terbuka sesuai keputusan sebelumnya.

---

## Sesi 12 — 2026-11-09: catat keputusan tenant + bedakan gangguan DB di login (PR-A, C-01/C-02 bagian perusahaan kosong N/A)

**Ruang lingkup:** dokumentasi model tenant (keputusan pemilik repo 2026-11-09) + login bedakan gangguan DB dari profil hilang. TIDAK mengubah `assert_same_tenant` (selain docstring), limiter, get_current_user, atau kontrak publik.

### Perubahan kode

| # | File | Perubahan | Bukti (sebelum → sesudah / validasi) |
|---|---|---|---|
| A1 | `AGENTS.md` (§4 subbagian) | Model tenant: admin lolos; non-admin perusahaan kosong sengaja lintas perusahaan; guard hanya untuk akun perusahaan terisi; agen dilarang fail-closed tanpa keputusan; 403/503 sejak #69; kode error login | Generik, tanpa identitas akun nyata |
| A1 | `panduan_dip_automation_system.md` (§2.1 tabel Staff) | Catatan yang sama + kode error login | — |
| A1 | `app/security.py` docstring `assert_same_tenant` | Fail-open perusahaan kosong dinyatakan DISENGAJA (keputusan), bukan legacy | Tanpa perubahan logika |
| A2 | `app/main.py:1303` (`login_submit`) | Exception cek profil → 303 `/login?error=service_unavailable` tanpa cookie (log tipe exception saja); baris kosong tetap `profile_missing` | Sebelum: gangguan DB menyesatkan `profile_missing`. Sesudah: konsisten dengan 503 di get_current_user |
| A2 | `app/templates/login.html` | Blok `service_unavailable` mengikuti pola blok yang ada | — |
| A3 | `tests/test_auth_profile_fail_closed.py` | Tambah 2 kasus login (service_unavailable untuk username+email; profil ada sukses) | Semua LULUS; (a) FAIL di kode lama |

### Validasi sesi ini

| Perintah | Exit | Hasil |
|---|---|---|
| `python scripts/check_undefined_names.py` | 0 | OK |
| `python scripts/check_static_rules.py` | 0 | OK |
| `python -m compileall app` | 0 | tanpa error |
| 29 test pure-local CI (clone bersih) | 0 semua | PASS=29 FAIL=0 (tenant_guard_* tetap lulus) |
| Kasus service_unavailable di kode lama (stash app/) | 1 | `/login?error=profile_missing` (bukan service_unavailable) |
| `tests/e2e_audit_staging.py --quick` | 0 | PASS 37 / SKIP 7 / FAIL 0 |
| Manual staging: login normal | 0 | Dashboard `/` 200 |
| Smoke 33/34 yang sama (402 PT Heka 403) | 1 | Sama seperti diketahui; bukan perubahan ini |

Staging preflight PASS; server dihentikan. Kredensial hanya di-export di shell yang sama.

### Koreksi riwayat

Kalimat "PR 2 terpisah, menunggu pembersihan data" di Sesi 5 dan Sesi 11 tidak berlaku lagi: non-admin perusahaan kosong TIDAK akan dibuat fail-closed (keputusan pemilik repo 2026-11-09). C-01/C-02 bagian perusahaan kosong berstatus N/A.

### Risiko & yang tidak berubah

- Perilaku bisnis tidak berubah selain pesan error yang lebih tepat saat gangguan DB.
- `assert_same_tenant`, limiter login, get_current_user, kontrak `/dip/*` tidak disentuh.

### Keputusan yang masih terbuka

- PR-B (edit komponen bahan baku atomik, migrasi 012) menunggu PR-A merge.
- C-14, C-15 tetap terbuka.

---

## Sesi 13 — 2026-11-09: edit komponen bahan baku atomik (C-07)

**Ruang lingkup:** C-07 saja (edit komponen bahan baku atomik). TIDAK menyentuh add_raw_material, route varian, delete, assert_same_tenant, get_current_user, limiter, log_activity. Migrasi SQL TIDAK dieksekusi agen (otorisasi tidak diberikan).

### Perubahan kode

| # | File | Perubahan | Bukti (sebelum → sesudah / validasi) |
|---|---|---|---|
| C-07 | `app/raw_materials_routes.py` (edit) | Validasi SEBELUM tulis apa pun (panjang list konsisten, percent via `Decimal` 0–100 inkl. non-finite ditolak) → error NOL tulis; ganti 2 delete + insert dengan SATU `supabase.rpc("replace_raw_material_components")` (payload list, bukan string JSON — pola 010); rpc gagal → log + redirect error (komponen tidak berubah, tidak fallback); `log_activity` sukses hanya setelah rpc berhasil; kode mati `if changes: pass` dihapus | Sebelum: komponen hilang bila build/insert gagal. Sesudah: atomik; input invalid NOL tulis; non-finite ditolak |
| C-07 | `migration/013_replace_raw_material_components.sql` | Fungsi `replace_raw_material_components` (delete varian NULL+edit + insert dalam satu transaksi, lock induk `FOR UPDATE`, validasi JSONB, kembalikan jumlah baris; grant hanya `service_role`; pola 010); header: p_components harus array JSON asli (list), bukan string (merujuk 010); pre-check/probe/rehearsal | **BELUM dieksekusi di mana pun** (menunggu pemilik repo manual staging dulu) |
| — | `README.md`, `AGENTS.md` | Tabel migrasi 001–013; nomor berikutnya 014; (prompt menuntut 012 — bentrok dengan `012_add_batch_mengetahui_signer.sql` yang sudah ada; dipakai 013) | — |

Asumsi skema (BELUM terverifikasi via information_schema karena tanpa akses DB; pemilik repo wajib jalankan pre-check 0c):
`raw_material_components(id uuid, raw_material_id uuid, variant_id uuid nullable, inci_name text, cas_number text nullable, "function" text nullable, percent_internal numeric, is_bahan_aktif boolean, created_at timestamptz)`.

Urutan deploy: migrasi 013 manual DULU di staging lalu produksi (aditif, hanya membuat fungsi), BARU kode di-deploy. Bila kode sebelum migrasi, edit komponen gagal dengan pesan error dan komponen TIDAK berubah (fail-safe).

### Validasi sesi ini

| Perintah | Exit | Hasil |
|---|---|---|
| `python scripts/check_undefined_names.py` | 0 | OK |
| `python scripts/check_static_rules.py` | 0 | OK |
| `python -m compileall app` | 0 | tanpa error |
| 30 test pure-local CI (clone bersih) | 0 semua | PASS=30 FAIL=0 (atomik 7 kasus incl. nan/inf) |
| Test `p_components` list di kode lama (stash app/) | 1 | `AssertionError: p_components harus list, dapat str` |
| `tests/e2e_audit_staging.py --quick` | 0 | PASS 37 / SKIP 7 / FAIL 0 |
| Smoke 33/34 yang sama (402 PT Heka 403) | 1 | Sama seperti diketahui; bukan perubahan ini |

Staging preflight PASS; server dihentikan. E2E jalur ini HANYA setelah pemilik repo menjalankan 013 di staging: edit komposisi bahan baku uji di staging lalu verifikasi komponen; simulasi kegagalan dengan input tidak valid (harus error, komponen tidak berubah).

### Catatan lain

- **C-08 sudah tertutup di main** (commit 2b6ee79), terverifikasi di Sesi 13.
- **C-10 tidak memerlukan perubahan**: `app/static/lampiran.js:103` menangani `failed` per file (`const failed = (data.failed || []).find(...)`); rollback insert sudah ada.
- **SQL belum dieksekusi di mana pun** (tidak lewat CLI/Management API/MCP/cara lain).
- **Asumsi skema** di atas;query verifikasi pemilik repo (pre-check 0c di file 013) wajib sebelum deploy.

### Koreksi tambahan (commit fix PR #71)

- `p_components` kini list (array JSON asli), bukan string JSON (bug: string sampai sebagai scalar dan ditolak cek array). Pola mengikuti `replace_product_formula` (migrasi 010).
- Persentase non-finite (nan/inf/-inf) ditolak (`Decimal.is_finite`).
- Kode mati `if changes: pass` dihapus.
- Batas persentase 0..100 di Python adalah perilaku BARU (kode lama menerima angka apa pun).
- Komposit dengan semua nama bahan kosong tetap menghapus seluruh komposisi varian (sama dengan kode lama).
- Update header bahan baku dan dokumen perusahaan terjadi SEBELUM RPC, jadi saat RPC gagal header bisa sudah berubah sementara komponen tidak (pesan error sudah menyatakan komponen tidak berubah).

### Uji manual staging setelah migrasi 013 dijalankan pemilik repo

1. Edit komposisi satu bahan baku uji lewat UI; verifikasi komponen berubah dan jumlahnya benar:
   `SELECT variant_id, COUNT(*) FROM raw_material_components WHERE raw_material_id = '<rm_id>' GROUP BY variant_id;`
2. Ulangi dengan input tidak valid (persentase negatif / bukan angka); verifikasi komponen lama TIDAK berubah (query yang sama sebelum dan sesudah).

### Risiko & yang tidak berubah

- Tanpa migrasi di staging, edit komponen di staging gagal dengan pesan yang jelas (tidak merusak data).
- Route tambah bahan baku tidak diubah sesuai instruksi.
- `pip-audit` tidak berubah.

### Keputusan yang masih terbuka

- Pemilik repo menjalankan migrasi 013 manual di staging lalu verifikasi sebelum produksi; lalu uji E2E komponen di staging.
- C-14, C-15 tetap terbuka.

---

## Sesi 14 — 2026-11-09: perbarui log audit + status migrasi + banner dokumen historis (dokumentasi saja, tanpa perubahan kode)

**Ruang lingkup:** dokumentasi saja (file `.md`); tidak menyentuh `app/`, `tests/`, `migration/`, `scripts/`, workflow, atau dependency. Tidak ada migrasi SQL yang dieksekusi.

### Perubahan per file

| File | Perubahan | Bukti |
|---|---|---|
| `catatan/catatan_log_perbaikan_audit_2026-11-05.md` | Baris C-07 → SELESAI (kode #71; migrasi 013 dijalankan staging+produksi 2026-11-09); baris C-08 frasa rapat → "sudah tertutup di main (commit 2b6ee79), terverifikasi di Sesi 13"; frasa "C-08-ish" → netral; baris D-08/D-09/D-10/D-14 → SEBAGIAN (status terkonfirmasi / banner ditambahkan); entri Sesi 14 | Hanya koreksi frasa keliru + status |
| `panduan_dip_automation_system.md` | Baris 013 di tabel migrasi; paragraf status eksekusi; subbagian "Cek status migrasi" dengan query read-only persis | 007+013 terkonfirmasi; sisanya "belum diverifikasi: jalankan query pengecekan" |
| `README.md` | 013 di kedua tabel migrasi; nomor berikutnya 014; paragraf status singkat + rujukan panduan | — |
| `AGENTS.md` | Rujuk paragraf status eksekusi di panduan; konsisten 014 | — |
| `catatan/catatan_handoff_migrasi_r2.md` + `catatan/catatan_migrasi_storage_r2.md` | Banner historis + tandai baris produksi supabase sebagai "(usang, lihat README)" | Bukan sumber kebenaran saat ini |
| `catatan/catatan_batch_plan.md` + `catatan/catatan_audit_codebase_2026-10-27.md` | Banner historis (baris pertama) | Isi tidak diubah |

### Validasi sesi ini

| Perintah | Exit | Hasil |
|---|---|---|
| `git diff --stat` | 0 | Hanya file `.md` (7 file) |
| `python scripts/check_static_rules.py` | 0 | OK |
| `python scripts/check_undefined_names.py` | 0 | OK |
| Cek tautan/anchor markdown | 0 | — |

### Risiko & yang tidak berubah

- Tidak ada perubahan perilaku; hanya dokumentasi.
- REPO PUBLIK: tidak ada project ref, username, id, email, atau data akun nyata yang ditulis ke file mana pun.

### Keputusan yang masih terbuka

- C-04 (log masking token di log server), C-15 (create user), dan opsional: CSRF/CSP, SRI, SSRF `httpx.get` di `dip_documents`, greeting AI, display_name.
- Status eksekusi migrasi 001-004, 006, 008, 010, 011, 012: "belum diverifikasi" sampai query pengecekan di panduan dijalankan pemilik repo di staging dan produksi.
