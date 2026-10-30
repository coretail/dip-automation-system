# Panduan Agen — DIP Automation System

## 1. Ringkasan proyek
- Aplikasi web FastAPI + Jinja2 untuk data bahan baku, formula, produksi, dan dokumen DIP kosmetik.
- Supabase/PostgreSQL menjadi database; akses object storage dipusatkan di `app/object_store.py`.
- Entrypoint ASGI adalah `app.main:app`; template mewarisi `base.html` bila memakai shell aplikasi.
- Runtime yang dipin repo adalah Python `3.11.0` (`.python-version`); README menyatakan Python 3.10+.

## 2. Perintah yang diaudit
- Instal dependensi: `pip install -r requirements.txt` (15 paket dipin; `pyflakes`, `pytest`, Playwright, dan `python-dotenv` tidak dipin di sana).
- Pengembangan lokal hanya lewat `python scripts/run_staging_8017.py`; `uvicorn app.main:app` langsung memakai `.env` produksi dan dilarang untuk pengembangan/tes karena `app/config.py` memilih `.env` saat tidak ada mode staging. Sejak guard G-11 (`app/env_guard.py`), proses tanpa `DIP_APP_ENV` yang menemukan file `.env` ditolak saat import (`RuntimeError`); menjalankan produksi dengan sengaja butuh `DIP_APP_ENV=production`. Render/CI tidak punya file `.env`, jadi tidak terpengaruh.
- Staging: dari root repo, `python scripts/run_staging_8017.py`; launcher bind ke `127.0.0.1:8017`, tanpa reload.
- Static check: `python scripts/check_undefined_names.py`; exit 0 bersih, 1 temuan blocking, 2 pyflakes tidak tersedia.
- Hook: `git config core.hooksPath .githooks`; `.githooks/pre-push` menjalankan static check.
- Unit/verification adalah skrip standalone: `python tests/test_parse_storage_url.py`, `python tests/test_object_store_r2.py`, dan skrip `verify_*.py`.
- Tidak ada pytest config (`pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`, `conftest.py`) yang ditemukan.
- Jika `python` tidak ada di PATH, gunakan interpreter venv repo: `venv\Scripts\python.exe` di Windows atau `venv/bin/python` di Linux/macOS; `venv/` di-ignore Git.
- E2E `e2e_*.py` membutuhkan server staging, kredensial env `STAGING_ADMIN_EMAIL`/`STAGING_ADMIN_PASSWORD`, dependency Playwright, dan menulis/cleanup data staging; bukan unit test. Nilai kredensial itu hanya ada di `LOGIN.md` di root repo (git-ignored, tidak pernah di-commit): baca dari sana saat runtime lalu export jadi env var di shell yang sama; jangan pernah menyalinnya ke `.py`, `.md`, `.env`, log, atau output apa pun.

## CI/CD (GitHub Actions)
- Sumber kebenaran pipeline adalah `.github/workflows/ci.yml`, `.github/workflows/staging-e2e.yml`, `.github/workflows/dependency-audit.yml`, dan `.github/dependabot.yml`.
- `ci.yml` berjalan pada `pull_request` dan `push` ke `main`. Job `quality` tidak memakai secret; env dummy level job berisi `SUPABASE_URL=https://ci.invalid.supabase.co`, `SUPABASE_KEY=ci-dummy-anon-key`, `SUPABASE_SERVICE_ROLE_KEY=ci-dummy-service-role-key`, dan `STORAGE_BACKEND=supabase`. `DIP_APP_ENV` **tidak boleh diset** di CI.
  - Langkah `quality`: `scripts/check_undefined_names.py`, `scripts/check_static_rules.py`, `compileall`, import terisolasi `app.main`, tiga belas test pure-local, `pip-audit`, dan Gitleaks. Audit dependency dan Gitleaks masih report-only pada fast CI.
- `staging-e2e.yml` hanya memiliki `workflow_dispatch`; trigger `push` dinonaktifkan sampai diputuskan lain. Workflow memakai GitHub Environment `staging`, concurrency tunggal dengan `cancel-in-progress: false`, serta suite `all`, `smoke`, `upload`, `activity`, dan `audit`. Suite `all` tidak memuat `upload`; suite upload memerlukan backend `dual`/`r2`.
- `dependency-audit.yml` berjalan melalui cron mingguan hari Senin dan `workflow_dispatch`; `pip-audit -r requirements.txt` membuat job gagal bila ada advisory. Pengecualian hanya boleh memakai `--ignore-vuln <ID>` dengan komentar yang mencatat alasan, owner, dan tanggal review.
- `.github/dependabot.yml` mengatur ekosistem `pip` dan `github-actions` dengan jadwal mingguan; seluruh update masuk melalui PR dan wajib melewati CI.
- `requirements-ci.txt` berisi tool CI. `scripts/check_static_rules.py` memeriksa syntax Python, duplikat route FastAPI berdasarkan method+path, kompilasi seluruh template Jinja, script HTML yang mencampur `src` dan inline code, serta syntax JavaScript inline melalui `node --check`.
- Nama secret di GitHub Environment `staging` berawalan `STAGING_` (misalnya `STAGING_SUPABASE_URL`). Workflow memetakan secret tersebut ke `.env.staging` sementara dengan nama polos yang dibutuhkan launcher. `STAGING_R2_BUCKET_SUFFIX` harus `-stg`; jangan menulis nilai secret di dokumentasi.
- Production secret tidak boleh masuk GitHub Actions. Migrasi SQL tetap manual; tidak ada langkah migrasi database di workflow.

## 3. Aturan keras
- Jangan membaca, mencetak, atau commit secret dari `.env*`, termasuk `.env.staging`; `.env.staging.example` hanya template dan tidak boleh diisi secret lalu di-commit.
- Kredensial akun tes E2E staging hanya ada di `LOGIN.md` di root repo (git-ignored); agen membacanya dari sana lalu set sebagai environment variable untuk run, dan tidak boleh echoed, di-log, disalin ke file lain, atau di-commit. Kalau nilainya pernah masuk ke file yang ter-commit atau output publik, password staging wajib segera dirotasi karena menghapus file atau commit tidak cukup - riwayat git tetap menyimpannya.
- Jangan pernah mengarahkan staging ke produksi. `DIP_APP_ENV=staging` wajib; guard menolak URL selain host staging eksak, ref produksi, shell env yang tercampur, key JWT yang terikat bukan staging, dan konfigurasi wajib yang hilang.
- Pengembangan/tes di mesin lokal hanya melalui `python scripts/run_staging_8017.py`; tanpa mode staging, `app/config.py` mengambil `.env` produksi dan `uvicorn app.main:app` langsung dilarang.
- Validasi key lokal tidak membuktikan key aktif: JWT hanya dicek klaim `ref` tanpa signature; key opaque hanya dicek keberadaan.
- Launcher membaca `.env.staging` sebagai sumber tunggal, memvalidasi sebelum import app, dan tidak mencetak secret. `.env.staging.example` sudah memuat seluruh key yang diwajibkan preflight; salin ke `.env.staging` dan isi nilai staging secara lokal, jangan commit.
- `STORAGE_BACKEND` hanya `supabase`, `dual`, atau `r2`; `R2_BUCKET_SUFFIX` memisahkan bucket fisik staging (dokumen E2E mensyaratkan `-stg`).
- Migrasi SQL tetap **tidak otomatis**: tidak pernah lewat pipeline otomatis (mis. `supabase db push`), dan tidak boleh dijalankan pada langkah baru tanpa otorisasi eksplisit pemilik repo pada sesi tersebut.
  - Jalur baku: manual oleh pemilik repo lewat Supabase SQL Editor, berurutan; staging lebih dulu dan hasil staging dibaca sebelum lanjut ke produksi.
  - Jalur tambahan yang diizinkan: atas otorisasi eksplisit pemilik repo per-jalur, agen boleh mengeksekusi migrasi lewat Supabase Management API (`POST /v1/projects/{ref}/database/query`) dengan syarat: jalankan **staging lebih dulu** dan baca hasilnya sebelum produksi; tidak pernah menyentuh produksi sebelum staging terverifikasi hijau; sertakan pre-check SELECT dan probe enforcement pasca-migrasi; file SQL dieksekusi **apa adanya** (byte-identik), tanpa modifikasi; token Management API diekstrak secara programatik dan tidak pernah dicetak atau ditulis ke file.
  - Tanpa otorisasi eksplisit tersebut, migrasi tidak boleh dieksekusi oleh agen; menyiapkan environment baru wajib lewat `scripts/run_staging_8017.py`.
  - Nomor migrasi berurutan dan unik: `migration/008_products_soft_delete_contract.sql` dan `migration/010_replace_product_formula.sql` sudah dipakai; angka `009` sengaja TIDAK dipakai (dicadangkan untuk migrasi lain, lihat catatan di `010_replace_product_formula.sql`). `migration/011_add_profile_display_name_and_avatar.sql` sudah dipersiapkan (kolom `display_name`, `avatar_path`, `avatar_updated_at` di `profiles` + CHECK constraint). DDL baru harus bernomor `012` (atau nomor berikutnya yang belum ada) — jangan memakai `009`.
- Sebelum mulai pekerjaan bersama, `git pull` dulu.
- Agen bekerja di branch dan membuat Pull Request ke `main`; agen tidak push langsung ke `main`. Status branch protection diatur pada pengaturan GitHub dan tidak terlihat dari repo. Agen hanya commit atau push bila diminta eksplisit oleh pemilik repo di sesi itu; tidak pernah `--force` atau push ke prod/deploy dengan cara lain.
- Render auto-deploy dari `main`, Build/Start command, dan status env tidak dapat diverifikasi dari repo; jangan menganggapnya fakta.

## 4. Arsitektur & menambah route
- `app/main.py` membangun app, auth, helper, client, template, lalu memanggil `register_*_routes(app, ...)` untuk modul route.
- Dependency diinjeksi eksplisit (mis. `supabase`, `templates`, `get_current_user`, `log_activity`, helper domain); modul route tidak mengimpor `main` untuk mengambil dependency.
- Saat menambah modul: buat fungsi `register_nama_routes`, terima semua dependency yang dipakai, daftarkan decorator route di dalam fungsi, import dan panggil sekali dari `main.py` dengan argumen lengkap.
- Pastikan path+method unik di seluruh modul; cek route terdaftar untuk mencegah duplikat FastAPI.
- Setelah refactor, jalankan static checker dan E2E staging relevan karena app dapat boot tetapi gagal `NameError` saat route diakses.

## 5. Konvensi kode
- Panggil `log_activity(..., request=request)` pada route yang menghasilkan audit request-context.
- Produk dihapus secara soft delete (`is_deleted`, `deleted_at`); route aktif memfilter `is_deleted=False`, dashboard menyediakan restore.
- Gunakan `Decimal` untuk persentase formula dan pembulatan, bukan aritmetika float baru.
- Template aplikasi mewarisi `base.html`; tema memakai token CSS dan atribut `data-theme` (`light`, `terra`, `rose`, `dark`) dengan key `heka-theme`.
- Upload PDF lewat `app/file_validation.py`: magic bytes `%PDF`, tidak kosong, maksimum 10 MB; ini validasi header/ukuran, bukan parser PDF penuh.
- Commit terbaru umumnya Conventional Commits (`feat`, `fix`, `test`, `docs`, `chore`, `refactor`) dengan campuran Indonesia/Inggris. Penulis dominan `coretail`; sebagian commit Claude memiliki trailer `Co-Authored-By` dan `Claude-Session`.

## 6. Jebakan yang terbukti
- Refactor route pernah meninggalkan `NameError`; `84f0f27` menambah checker dan smoke E2E.
- Asumsi redirect smoke test pernah salah (handler menuju preview, bukan daftar); diperbaiki di `2fa904a`.
- Komentar/keterangan kode memperingatkan string seperti `now()`/komentar SQL di payload PostgREST dapat diperlakukan sebagai literal dan gagal cast; kirim nilai timestamp nyata.
- `<script src="...">` hanya memuat file eksternal; inline code harus berada di elemen script terpisah (bukan dicampur dalam tag ber-`src`).
- Jangan menimpa `socket.socket` sebelum modul `ssl` ter-import (menyebabkan `TypeError` di `ssl.py`); blokir hanya fungsi koneksi `create_connection`, `getaddrinfo`, dan `socket.socket.connect` setelah import.
- `tests/test_auth_matrix.py` meng-import `app.main`, dan `app/config.py` mewajibkan `SUPABASE_URL` serta `SUPABASE_SERVICE_ROLE_KEY` saat import; di CI keduanya disediakan lewat env dummy level job.
- `pip-audit` tidak menyediakan level severity; kebijakan pipeline adalah gagal bila ada advisory yang memiliki versi perbaikan.
- `pypdf` dinaikkan ke 6.21.1 untuk menutup 8 advisory; perubahan dependency PDF perlu uji manual Bab II, gabungan Bab I-IV, dan efek samping.
- `.gitignore` mengabaikan `/tests/*`; test baru harus menambah whitelist `!/tests/nama.py`.
- Perubahan storage perlu memperhatikan encoding spasi URL (`26fba31`); mode `dual` menulis R2 **lebih dulu** dan gagal loudly bila R2 gagal (bukan best-effort), lalu Supabase (rollback best-effort untuk jalur non-upsert); baca tetap Supabase; `remove` menghapus di kedua backend.
- Presigned URL SigV4 tidak boleh diberi query tambahan; parameter tambahan (mis. cache-buster `?v=`) membuat tanda tangan tidak valid dan memberi 403. `app/templates/base.html` mengecualikan URL yang memuat `X-Amz-Signature`, `X-Amz-Algorithm`, atau `token`; test: `tests/test_base_cachebust.py`. Residu: selector `a[href*="raw-material-docs"], a[href*="legal-documents"]` tidak mencocokkan URL `pub-*.r2.dev` (keterbatasan yang diketahui).
- Cloudflare memblokir User-Agent default `Python-urllib` dengan 403; `migration/verify_r2_readiness.py` memakai UA browser-like.
- `log_activity`: `activity_logs.entity_id` bertipe uuid; nilai non-UUID dinormalkan menjadi `None` dan nilai mentah ditambahkan ke `entity_label` (lihat `app/main.py`). Panggil `log_activity` dengan UUID baris, bukan slug/perusahaan.
- Akses `r2.dev` dari jaringan kantor (2026-10-29): `NET::ERR_CERT_COMMON_NAME_INVALID` pada `pub-*.r2.dev` hanya di Wi-Fi kantor (data seluler normal) disebabkan **DNS kantor** yang membelokkan `*.r2.dev`; diagnosis dengan `nslookup <host>` vs `nslookup <host> 1.1.1.1`, perbaikan dengan DNS router/perangkat ke 1.1.1.1 atau 8.8.8.8. Jaringan lain belum teruji dan Cloudflare menyebut `r2.dev` hanya untuk pengembangan (custom domain disarankan). URL DB produksi berada di Supabase dan `STORAGE_BACKEND=dual`; jangan menjalankan `backfill_r2_urls.py --target r2 --apply` pada produksi atau menyarankan `STORAGE_BACKEND=r2` sebelum URL `r2.dev` terbukti terbuka dari kantor dan jaringan lain. Saat URL DB di Supabase, `verify_r2_readiness.py` melaporkan `STILL_SUPABASE`; itu wajar.
- E-05 (bug laten, belum diperbaiki): `parse_storage_url` di `app/object_store.py` tidak melakukan unquote, sehingga path dengan spasi (`%20`) bisa salah bila dipakai untuk `remove` atau presign. Saat ini hanya 13 objek di bucket `legal-documents` yang namanya mengandung spasi/`%`/`+`, dan semuanya dibaca lewat URL DB langsung (bukan lewat `parse_storage_url`), jadi belum berdampak. Perbaikan terjadwal setelah cutover (PR terpisah).
- Tidak ditemukan bukti commit bertajuk `Grok Build`; aturan operasional tetap `git pull` sebelum mulai.

## 7. Definisi selesai
- `python scripts/check_undefined_names.py` exit 0 dan unit/verification standalone yang relevan exit 0 (di lingkungan yang memiliki Python/dependency).
- Setiap Pull Request harus lolos job `quality` di CI.
- Jika menyentuh route, upload, auth, atau storage, jalankan E2E staging yang relevan setelah guard lokal dan kredensial staging tersedia; jangan jalankan terhadap prod.
- Perubahan yang menyentuh route, upload, auth, atau storage tetap perlu Staging E2E manual yang relevan.
- Untuk perubahan SQL, file sudah direview dan eksekusinya manual lewat Supabase SQL Editor oleh pemilik repo, atau oleh agen hanya atas otorisasi eksplisit pemilik repo per-jalur lewat Supabase Management API (staging lebih dulu, hasil staging dibaca sebelum produksi).

## 8. Dokumen sumber
- `README.md`: orientasi dan perintah; tabel migrasi kini mencantumkan 001–011 (009 tidak dipakai) dan inventaris test disesuaikan.
- `.github/workflows/*`: sumber kebenaran konfigurasi CI/CD; README dan panduan operasional harus diselaraskan bila perintah pipeline berubah.
- `panduan_dip_automation_system.md`: panduan operasional/teknis utama dan detail tema, PDF, keamanan, serta migrasi.
- `catatan/catatan_investigasi_auth500_staging.md`: investigasi Auth staging historis; hasil live belum diverifikasi ulang.
- `catatan/catatan_handoff_migrasi_r2.md` dan `catatan/catatan_migrasi_storage_r2.md`: handoff/status R2 historis; jangan dianggap status live tanpa verifikasi.
- `catatan/catatan_batch_plan.md`: rencana lama yang bertentangan dengan PO yang sudah ada; bukan sumber kebenaran saat ini.
- `.kilo/plans/rencana_fitur_input_po_qc.md`: rencana lama; klaim “belum ada perubahan code” tidak cocok dengan `app/po_routes.py` saat ini.
  - `migration/001`–`011`: urutan SQL bernomor (009 sengaja tidak dipakai); `011_add_profile_display_name_and_avatar.sql` sudah dipersiapkan. Bukti repo menunjukkan manual SQL Editor, tetapi status eksekusi aktual tidak dapat diverifikasi tanpa akses database. Nomor migrasi berikutnya adalah **012**.
