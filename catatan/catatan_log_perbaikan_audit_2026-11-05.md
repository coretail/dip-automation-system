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
| pypdf ≥6.21.4 | 10 advisory terbuka (butuh PR terpisah + uji manual) | BELUM | — |

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
