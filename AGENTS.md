# Panduan Agen — DIP Automation System

## 1. Ringkasan proyek
- Aplikasi web FastAPI + Jinja2 untuk data bahan baku, formula, produksi, dan dokumen DIP kosmetik.
- Supabase/PostgreSQL menjadi database; akses object storage dipusatkan di `app/object_store.py`.
- Entrypoint ASGI adalah `app.main:app`; template mewarisi `base.html` bila memakai shell aplikasi.
- Runtime yang dipin repo adalah Python `3.11.0` (`.python-version`); README menyatakan Python 3.10+.

## 2. Perintah yang diaudit
- Instal dependensi: `pip install -r requirements.txt` (15 paket dipin; `pyflakes`, `pytest`, Playwright, dan `python-dotenv` tidak dipin di sana).
- Pengembangan lokal hanya lewat `python scripts/run_staging_8017.py`; `uvicorn app.main:app` langsung memakai `.env` produksi dan dilarang untuk pengembangan/tes karena `app/config.py` memilih `.env` saat tidak ada mode staging.
- Staging: dari root repo, `python scripts/run_staging_8017.py`; launcher bind ke `127.0.0.1:8017`, tanpa reload.
- Static check: `python scripts/check_undefined_names.py`; exit 0 bersih, 1 temuan blocking, 2 pyflakes tidak tersedia.
- Hook: `git config core.hooksPath .githooks`; `.githooks/pre-push` menjalankan static check.
- Unit/verification adalah skrip standalone: `python tests/test_parse_storage_url.py`, `python tests/test_object_store_r2.py`, dan skrip `verify_*.py`.
- Tidak ada pytest config (`pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`, `conftest.py`) yang ditemukan.
- Jika `python` tidak ada di PATH, gunakan interpreter venv repo: `venv\Scripts\python.exe` di Windows atau `venv/bin/python` di Linux/macOS; `venv/` di-ignore Git.
- E2E `e2e_*.py` membutuhkan server staging, kredensial env `STAGING_ADMIN_EMAIL`/`STAGING_ADMIN_PASSWORD`, dependency Playwright, dan menulis/cleanup data staging; bukan unit test.

## 3. Aturan keras
- Jangan membaca, mencetak, atau commit secret dari `.env*`, termasuk `.env.staging`; `.env.staging.example` hanya template dan tidak boleh diisi secret lalu di-commit.
- Jangan pernah mengarahkan staging ke produksi. `DIP_APP_ENV=staging` wajib; guard menolak URL selain host staging eksak, ref produksi, shell env yang tercampur, key JWT yang terikat bukan staging, dan konfigurasi wajib yang hilang.
- Pengembangan/tes di mesin lokal hanya melalui `python scripts/run_staging_8017.py`; tanpa mode staging, `app/config.py` mengambil `.env` produksi dan `uvicorn app.main:app` langsung dilarang.
- Validasi key lokal tidak membuktikan key aktif: JWT hanya dicek klaim `ref` tanpa signature; key opaque hanya dicek keberadaan.
- Launcher membaca `.env.staging` sebagai sumber tunggal, memvalidasi sebelum import app, dan tidak mencetak secret. Contoh env saat ini belum memuat seluruh `STORAGE_BACKEND`/R2 key yang diwajibkan preflight; isi lengkap secara lokal, jangan commit.
- `STORAGE_BACKEND` hanya `supabase`, `dual`, atau `r2`; `R2_BUCKET_SUFFIX` memisahkan bucket fisik staging (dokumen E2E mensyaratkan `-stg`).
- Migrasi SQL tetap **tidak otomatis**: tidak pernah lewat pipeline otomatis (mis. `supabase db push`), dan tidak boleh dijalankan pada langkah baru tanpa otorisasi eksplisit pemilik repo pada sesi tersebut.
  - Jalur baku: manual oleh pemilik repo lewat Supabase SQL Editor, berurutan; staging lebih dulu dan hasil staging dibaca sebelum lanjut ke produksi.
  - Jalur tambahan yang diizinkan: atas otorisasi eksplisit pemilik repo per-jalur, agen boleh mengeksekusi migrasi lewat Supabase Management API (`POST /v1/projects/{ref}/database/query`) dengan syarat: jalankan **staging lebih dulu** dan baca hasilnya sebelum produksi; tidak pernah menyentuh produksi sebelum staging terverifikasi hijau; sertakan pre-check SELECT dan probe enforcement pasca-migrasi; file SQL dieksekusi **apa adanya** (byte-identik), tanpa modifikasi; token Management API diekstrak secara programatik dan tidak pernah dicetak atau ditulis ke file.
  - Tanpa otorisasi eksplisit tersebut, migrasi tidak boleh dieksekusi oleh agen; menyiapkan environment baru wajib lewat `scripts/run_staging_8017.py`.
  - Nomor migrasi berurutan dan unik: `migration/008_products_soft_delete_contract.sql` sudah dipakai, jadi DDL `public_link_audits` berikutnya harus bernomor `009`.
- Sebelum mulai pekerjaan bersama, `git pull` dulu.
- Agen hanya commit atau push bila diminta eksplisit oleh pemilik repo di sesi itu; tidak pernah `--force` atau push ke prod/deploy dengan cara lain.
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
- `.gitignore` mengabaikan `/tests/*`; test baru harus menambah whitelist `!/tests/nama.py`.
- Perubahan storage perlu memperhatikan encoding spasi URL (`26fba31`) dan mode dual yang best-effort ke R2.
- Tidak ditemukan bukti commit bertajuk `Grok Build`; aturan operasional tetap `git pull` sebelum mulai.

## 7. Definisi selesai
- `python scripts/check_undefined_names.py` exit 0 dan unit/verification standalone yang relevan exit 0 (di lingkungan yang memiliki Python/dependency).
- Jika menyentuh route, upload, auth, atau storage, jalankan E2E staging yang relevan setelah guard lokal dan kredensial staging tersedia; jangan jalankan terhadap prod.
- Untuk perubahan SQL, file sudah direview dan eksekusinya manual lewat Supabase SQL Editor oleh pemilik repo, atau oleh agen hanya atas otorisasi eksplisit pemilik repo per-jalur lewat Supabase Management API (staging lebih dulu, hasil staging dibaca sebelum produksi).

## 8. Dokumen sumber
- `README.md`: orientasi dan perintah; tabel migrasi hanya mencantumkan 001–004 dan inventaris test sudah tidak lengkap.
- `panduan_dip_automation_system.md`: panduan operasional/teknis utama dan detail tema, PDF, keamanan, serta migrasi.
- `catatan/catatan_investigasi_auth500_staging.md`: investigasi Auth staging historis; hasil live belum diverifikasi ulang.
- `catatan/catatan_handoff_migrasi_r2.md` dan `catatan/catatan_migrasi_storage_r2.md`: handoff/status R2 historis; jangan dianggap status live tanpa verifikasi.
- `catatan/catatan_batch_plan.md`: rencana lama yang bertentangan dengan PO yang sudah ada; bukan sumber kebenaran saat ini.
- `.kilo/plans/rencana_fitur_input_po_qc.md`: rencana lama; klaim “belum ada perubahan code” tidak cocok dengan `app/po_routes.py` saat ini.
- `migration/001`–`007`: urutan SQL bernomor; bukti repo menunjukkan manual SQL Editor, tetapi status eksekusi aktual tidak dapat diverifikasi tanpa akses database.
