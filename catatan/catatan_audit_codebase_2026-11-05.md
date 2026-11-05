# Laporan Audit Menyeluruh — DIP Automation System

**Tanggal audit:** 5 November 2026  
**Hash yang diaudit:** `origin/main` @ `6830ae23209102f4ba6c76850b8962eed7590430` (lokal sama); working tree `fix/e2e-notes-idempotent` @ `db7f06d`. `git pull --ff-only` gagal (branch lokal belum ada di origin; hanya untracked `scripts/*.patch`) — dicatat sebagai batasan, bukan penyimpangan audit.  
**Metode:** Studio audit mengikuti `scripts/audit-prompt-v2.md`: Fase 1–2 baca konteks & pemetaan codebase; Fase 3 audit paralel A–G via subagent; eksekusi test pure-local sesuai `.github/workflows/ci.yml` di clone bersih tanpa `.env` dengan env dummy CI; eksekusi E2E staging via `scripts/run_staging_8017.py`.  
**Sifat:** READ-ONLY. Tidak ada file repo yang diubah/dicommit. Tidak membaca `.env*`/`LOGIN.md`/`backup-rls/` (kredensial E2E hanya di-export di shell yang sama, tidak di-echo/log/disalin ke file/laporan).

---

## 1. Status kesehatan & hash commit

**Kesehatan: Baik dengan catatan keamanan struktural.** Static checks, 18 test pure-local CI, dan E2E staging semuanya hijau (kecuali false-green tersembunyi di 2 test). Kestabilan runtime terbukti staging; risikonya terkonsentrasi pada otorisasi tenant yang belum lengkap dan ketiadaan CSRF.

- Tes yang dieksekusi di clone bersih tanpa `.env` dengan env dummy CI persis `ci.yml` (`SUPABASE_URL=https://ci.invalid.supabase.co`, `SUPABASE_KEY=ci-dummy-anon-key`, `SUPABASE_SERVICE_ROLE_KEY=ci-dummy-service-role-key`, `STORAGE_BACKEND=supabase`, `DIP_APP_ENV` tidak diset): `check_undefined_names` exit 0, `check_static_rules` exit 0, `compileall` exit 0, import `app.main` exit 0. **18/18 test CI exit 0**, tetapi 2 di antaranya no-op (lihat §8).
- E2E staging (preflight PASS, `STORAGE_BACKEND=dual`): smoke 34/34, activity 19/19, notes PASS, audit --quick PASS 37/SKIP 7/FAIL 0, **audit penuh PASS 41/SKIP 3/FAIL 0** (D1, G1, G2 skip — tenant kedua & kanal SQL tidak tersedia). Cleanup terverifikasi untuk sample/note/formula; 1 artefak `brand_legal_documents` dari smoke tercatat tidak dibersihkan skrip. `verify_r2_readiness --env staging --expect-suffix=-stg` exit 0, `FAIL=0, WARN=3` (extra 2 objek R2, 1 referensi masih Supabase, idempotensi backfill 1 perubahan dry-run).
- Tanpa secret yang ditulis ke laporan; `.env*`/`LOGIN.md` tidak dibaca/di-open.

## 2. Arsitektur yang dipahami

FastAPI + Jinja2 di `app/main.py` (`app.main:app`) sebagai entrypoint; semua route didaftarkan lewat `register_*_routes(app, ...)` dengan dependency di-inject eksplisit (supabase, templates, get_current_user, log_activity) — tidak ada import silang ke `main`. Supabase/PostgreSQL (service role, melewati RLS) untuk data; semua object storage terpusat di `app/object_store.py`. Empat tema via token CSS + `data-theme` (`heka-theme`), dimuat di `base.html` yang juga berisi skrip anti-flash, cache-bust PDF, notifikasi ED, dan penghitung mention. Alur DIP Bab I–IV dibangun dari formula (wajib 100% ✔) → checklist dashboard → generator (xhtml2pdf + pypdf; Bab II komposisi layout `bab2_pdf.py`) → PDF gabungan/ZIP; portal publik `/dip/*` tanpa login dengan capability token (migrasi 007, fail-closed). Auth dual username/email → `profiles.full_name`, cookie HTTP-Only SameSite=Lax 24 jam (JWT 4 jam), rate-limit login 5/menit. Dua perusahaan (PT Erfi/PT Heka) diisolasi lewat `perusahaan` + `assert_same_tenant` (fail-open untuk baris tanpa perusahaan — by design legacy). Staging terisolasi guard fail-closed (G-11 + staging preflight) dan launcher `run_staging_8017.py` di 127.0.0.1:8017.

## 3. Temuan Security (A dan F)

| ID | Judul | Klasifikasi | Risiko | Lokasi |
|---|---|---|---|---|
| A-07 | Tanpa token CSRF di semua POST; CSP/HSTS default OFF | CONFIRMED | Tinggi | grep `csrf` 0 di `app/`; POST di seluruh modul; `main.py:351-389` |
| A-06 | CDN Tailwind/FontAwesome tanpa SRI (item 7 masih berlaku) | CONFIRMED | Tinggi | `login.html:7-8`, `public_error.html:7-8`, `base.html:50-53` |
| A-10 | `finished-spec` POST tanpa `assert_same_tenant` | CONFIRMED | Tinggi | `products_routes.py:766-824` |
| A-11 | `efek_samping` generate/delete tanpa guard | CONFIRMED | Tinggi | `efek_samping.py:178-456` |
| A-13 | FSP create tanpa guard; delete fail-open saat DB gagal | CONFIRMED | Tinggi | `sample_routes.py:38-181, 345-364`; `security.py:29-33` |
| C-01/C-02 | Akun tanpa profil jadi `staff`+`perusahaan=None`; guard lolos bila tenant kosong | CONFIRMED | Tinggi | `main.py:681-718`, `security.py:31-34` |
| C-03/A-12 | Brands & lampiran tanpa otorisasi tenant | CONFIRMED | Tinggi | `brands_routes.py:25-31,180-187`, `product_attachments_routes.py:55-58,116-140` |
| A-18 | `display_name` dapat menyamar; header notes hanya display name (item 9 masih berlaku) | CONFIRMED | Sedang | `profile_validation.py:25-76`, `profile_routes.py:183-257`, `notes.html:124-127` |
| A-09 | Upload hanya magic-byte+ukuran, tanpa cek ekstensi/tipenya di jalur produk | POTENTIAL | Sedang | `file_validation.py:6-20`, `products_routes.py:1268-1270` |
| A-16/A-19 | Bocor nama produk/bahan via API global; @mention via `full_name` bukan id | POTENTIAL | Sedang/Rendah | `dashboard_routes.py:90`, `notes_routes.py:263-382,33-45` |
| A-17 | Profil hilang → fail-open; `.single()` gagal jadi redirect diam | POTENTIAL | Sedang | `main.py:654-726`, `sample_routes.py:244-251` |
| A-02/A-03/A-04 | `body_html|safe` escape-first; `tojson|safe` rapuh; `item.id` tanpa escape di ED bell | POTENTIAL | Sedang/Rendah | `notes.html:162`, `raw_materials.html:1213`, `base.html:292-334` |
| F-03 | `public_access_revoked_at` tidak pernah dicek; revoke tidak fungsional | CONFIRMED | Sedang | `dip_public.py:270-303`, `migration/007:8` |
| F-08 | Nol rate-limit di `/dip/*` (generator PDF/ZIP dapat di-scrape) | CONFIRMED | Sedang | `main.py:392` (hanya login) |
| F-09 | Audit hanya hub; download/ZIP tanpa jejak | CONFIRMED | Sedang | `dip_public.py:100-144,173-179` |
| F-07 | Perbandingan token `==`, bukan timing-safe | CONFIRMED | Rendah | `dip_public.py:289` |
| F-05 | Token `?access=` di access log; Render start command di luar repo | POTENTIAL | Sedang | `main.py:396-426,346`; tak terverifikasi |
| A-01/A-15/A-20 | `escapeHtml` aman; guard PO/RM/produk benar; open-redirect aman | CONFIRMED aman | Rendah | `common.js:9-14`, `po_routes.py:1035-1300`, `main.py:1315-1327` |

Catatan penting: `escapeHtml` sudah meng-escape `& < > " '` (A-01) dan tenant guard PO/RM/produk A-15 sudah benar — tetapi cakupannya tidak lengkap (A-10..A-13). Author notes via `author_id` benar untuk note baru, tetapi fallback legacy + tampilan display-name-only membuka impersonasi visual (A-18).

## 4. Temuan Frontend (B)

| ID | Judul | Klasifikasi | Risiko | Lokasi |
|---|---|---|---|---|
| F-02/F-01 | ED dipanggil tiap halaman (2 query berat tanpa cache/visibility); polling 401 mentah tak berhenti | CONFIRMED/POTENTIAL | Sedang | `base.html:268-269,275-277,378-383`, `presence_routes.py:91,125` |
| F-04 | `[SESSION EXPIRED]` tetap spam terminal (filter hanya akses-log) | CONFIRMED | Rendah | `main.py:396-426` vs `main.py:1298-1302` |
| F-05 | Cache-bust guard presign benar, selektor terlewat URL `pub-*.r2.dev` (item 1 terkonfirmasi) | CONFIRMED | Rendah | `base.html:439,447`, `test_base_cachebust.py:11-24` |
| F-03/F-06 | Antrean `lampiran.js` lanjut setelah expiry; autocomplete notes telan redirect jadi `[]` | POTENTIAL | Rendah | `lampiran.js:98-124`, `notes.html:306-317,459-480` |
| F-07 | `po-analytics.js` MutationObserver tanpa debounce | OBSERVATION | Rendah | `po-analytics.js:340-344` |

Positif (tidak perlu tindakan): `presence.js` idempoten + berhenti benar (pagehide, logout, 401); notes/admin polling di-skip saat hidden + guard in-flight; `handleSessionExpired` terpusat.

## 5. Temuan Backend (C)

| ID | Judul | Klasifikasi | Risiko | Lokasi |
|---|---|---|---|---|
| C-05 | Greeting AI sinkron: terburuk ~12 dtk (3 model × 4 dtk), hardcode, exception tak dibedakan (item 10) | CONFIRMED | Sedang | `main.py:150-154,204-221,1224-1226` |
| C-04 | `log_activity` fail-open: audit hilang diam-diam | CONFIRMED | Sedang | `main.py:993-998` |
| C-06 | Restore selalu “sukses” walau 0 baris | CONFIRMED | Sedang | `dashboard_routes.py:55-78` |
| C-07 | Edit komponen: delete+insert tanpa transaksi | CONFIRMED | Sedang | `raw_materials_routes.py:1071-1072,785-842` |
| C-08 | `spec_parameters` string JSON ke kolom JSONB | CONFIRMED | Sedang | `main.py:64-68`, `raw_materials_routes.py:725,797-798` |
| C-10 | Lampiran storage-dulu, `success:True` parsial | CONFIRMED | Sedang | `product_attachments_routes.py:161-192` |
| C-15 | Create user TOCTOU + akun auth yatim diakui | CONFIRMED | Sedang | `admin_users_routes.py:114-171` |
| C-11/C-12/C-13/C-14 | HTTPException ditelan; greeting_cache tanpa validasi skema; SSRF DNS-residual; `.single()` vs cek manual | POTENTIAL/OBS | Rendah | `main.py:671-726`, `dashboard_routes.py:288-291`, `efek_samping.py:298-331`, `sample_routes.py:188-200` |

Detail C-05: timeout 4.0 dtk per request × 3 model sekuensial (`gemini-3.5-flash-lite`, `3.1`, `2.5`) → terburuk ~12 dtk ditambah `sign_in_with_password` + query profil di jalur login. Status `!=200` (termasuk 404) di-`continue` ke fallback — benar secara fungsi — tetapi `except Exception` hanya `print(... {e})` tanpa tipe/errno dan daftar model hardcode (tidak env-configurable). Item #2 terkonfirmasi tertutup (§9).

## 6. Temuan Storage/R2 & kesiapan cutover (E)

**Keputusan: BELUM SIAP untuk cutover penuh ke `STORAGE_BACKEND=r2`.** Kesiapan parsial; 5 blocker di bawah ini wajib ditangani dulu.

| ID | Judul | Klasifikasi | Risiko | Lokasi |
|---|---|---|---|---|
| E-05 (#8) | `parse_storage_url` tanpa `unquote` — path `%20` salah target | CONFIRMED | Tinggi | `object_store.py:183-220`, `test_parse_storage_url.py:33-34,41` |
| E-06 | Upload-then-`public_url` tanpa validasi base dulu → orphan bila base kurang | CONFIRMED | Tinggi | pemanggil di `brands/company_docs/efek_samping/products/raw_materials` + `object_store.py:430-437` |
| E-04 | 6 `httpx.get` di `dip_documents.py` tanpa SSRF guard | CONFIRMED | Sedang | `dip_documents.py:194-205,407-416,588-598,835-851,994-1026` |
| E-08 | Jalur privat `product-attachments` di mode r2 belum ter-soak via UI | OBSERVATION | Sedang | `product_attachments_routes.py`, `object_store.py` |
| E-07b | Selektor cache-bust tak cocok `pub-*.r2.dev` (PDF basi, bukan 403) | CONFIRMED | Rendah | `base.html:447` |

Semantik yang dipahami: `dual` tulis R2 dulu (gagal = raise), lalu Supabase (rollback hanya non-upsert; upsert=True jadi orphan menunggu rekonsiliasi); `public_url`/`signed_url(s)` tetap Supabase di dual; `remove` hapus di dua backend. Jalur DB-langsung (`dip_documents`) tidak peduli backend — cutover efektif hanya bila backfill menulis ulang kolom ke base R2. `verify_r2_readiness.py` staging exit 0 `FAIL=0 WARN=3` — tetapi `supabase_bucket_exists` memberi false-FALSE sebab tak membedakan error transien, dan `norm()` unquote menutupi E-05. `audit_storage.py` report-only dan buta R2 pasca-backfill.

## 7. Dokumentasi vs Implementasi (D)

| ID | Judul | Klasifikasi | Risiko | Lokasi |
|---|---|---|---|---|
| D-04 | README instruksikan `uvicorn app.main:app --reload` (dilarang AGENTS/guard) | CONFIRMED | **Tinggi** | `README.md:214-215` vs `AGENTS.md:11`, `env_guard.py:12-30` |
| D-03 | Pohon `app/` README tak lengkap (28 file aktual vs 14 terdaftar) | CONFIRMED | Sedang | `README.md:247-273` |
| D-07 | Panduan §4.14 “hanya SQL di-commit” vs 3 skrip ter-track | CONFIRMED | Sedang | `panduan:563` vs `.gitignore:80-84` |
| D-09 | Handoff R2: status prod/staging tertinggal (prod kini `dual`, bukan `supabase`) | CONFIRMED | Sedang | `catatan_handoff_migrasi_r2.md:72-73` vs `README:372` |
| D-11 | 1 test whitelist tak jalan di CI (sama dengan G) | CONFIRMED | Sedang | `ci.yml:62-79` vs `.gitignore:133` |
| D-08 | Status eksekusi migrasi 011 ambigu | POTENTIAL | Sedang | `panduan:588` vs `AGENTS.md:43` |
| D-01/D-02/D-05/D-12/D-13 | Versi dep tertinggal; hitungan template 17 vs 18; suite `notes` tak disebut; inventaris tests sebagian; tabel `entity_type` kurang 5 | CONFIRMED | Rendah | `README:150-151,274,276`, `AGENTS:24`, `panduan:707-721` |
| D-06/D-10/D-14 | Klaim Python 3.10+ usang; batch-plan & audit-27 Okt berlabel historis tanpa banner | OBSERVATION | Rendah | `AGENTS.md:7`, `catatan/*` |

## 8. CI/Runtime/Dependensi (G)

- **False-green kritis (CONFIRMED, risiko Tinggi):** `tests/test_auth_matrix.py` (31 baris, 1 fungsi `test_*`) dan `tests/test_upload_validation.py` (32 baris, 6 fungsi `test_*`) **tidak memiliki blok `main()`** — `python tests/<file>.py` di `ci.yml:66-67` exit 0 tanpa mengeksekusi satu pun assertion. Terbukti di eksekusi (output kosong, 0.06/2.18 dtk). Perbaikan tanpa ubah perilaku: tambah `main()` pemanggil `test_*` atau jalankan lewat pytest (sudah ada di `requirements-ci.txt` tetapi tak pernah dieksekusi di `ci.yml`).
- **Whitelisted tapi tak jalan (CONFIRMED, Sedang):** `test_verify_r2_readiness_logic.py` (punya runner, pure-local) tidak ada di `ci.yml` (grep 0 match); E2E `e2e_dip_public_link.py` & `e2e_profile_staging.py` tidak disebut di `staging-e2e.yml`. Dari 29 file whitelist, CI hanya menjalankan 18.
- **Pin Python konsisten repo↔CI** (`3.11.0` di `.python-version`, `ci.yml:26`, `staging-e2e.yml:32`, `dependency-audit.yml:19`); **Render tidak terverifikasi dari repo** (tanpa `render.yaml`/`runtime.txt`) — OBSERVATION.
- **Dependensi (CONFIRMED, Tinggi):** `pip-audit` per 2026-11-05 melaporkan **10 advisory terbuka pada `pypdf 6.21.1`** (fix ≥ `6.21.4`: `CVE-2026-115572/-115585/-115580/119203–119209`) — 8 advisory lama memang tertutup, tetapi advisory baru muncul. `dependabot.yml:19` mengecualikan `pypdf` dari grup, jadi bump butuh PR terpisah + uji manual Bab II & gabungan Bab I–IV. `xhtml2pdf==0.2.20` tidak ada di advisory saat ini (item #11).
- Guard staging vs produksi sehat (G-11 + `staging_preflight` + launcher single-source tanpa cetak secret); kelemahan minor: duplikasi konstanta `STAGING_REF/PROD_REF` di dua file (`staging_guard.py:14-15`, `staging_preflight.py:19-22`) dan `check_static_rules.py:93` memalsukan `find_dotenv_files` sehingga preload bukan bukti lulus G-11.

## 9. Status temuan yang sudah diketahui

| Item | Status | Bukti `file:baris` |
|---|---|---|
| 1. Cache-buster `?v=` — guard presign | TERTUTUP (guard benar; residu selektor r2.dev tetap resah) | `base.html:439`, `test_base_cachebust.py` (hanya cek urutan guard; selektor kurang) |
| 2. `entity_id` non-UUID `company_docs` | TERTUTUP | `company_docs_routes.py:118-132` (`row_id` UUID) + `main.py:910-949` + `test_log_activity_normalize.py` 5 PASS |
| 4. `_dip_public_check_product` fail-open | TERTUTUP fail-closed | `dip_public.py:270-303`, `test_dip_public_check.py` (exception → 404) |
| 5. `verify_r2_readiness` bucket check | TERTUTUP (fungsi ada, dipakai, test ada) | `verify_r2_readiness.py:75-84,240-244`, `test_verify_r2_readiness_logic.py` (tidak di CI — lihat §8) |
| Tenant guard PR43-48; `escapeHtml` quote; author via `author_id` PR45 | SEBAGIAN (lihat A-01, A-10..A-18) | `common.js:9-14`; guard PO/RM A-15 benar; finish-spec/efek/lampiran/FSP masih celah |
| 3. Token `?access=` di access log | MASIH POTENTIAL | `main.py:396-426` tak samarkan query; Render start command di luar repo; `Referrer-Policy` mitigasi ok `main.py:346` |
| 6. `/dip/*` tanpa token untuk non-BPOM bertoken → 404 | TERTUTUP (disengaja terkonfirmasi) | `dip_public.py:295` |
| 7. Tailwind CDN v3 tanpa SRI | MASIH TERBUKA | `login.html:7-8`, `public_error.html:7-8`, `base.html:50-53` |
| 8. `parse_storage_url` decode-path (E-05) | MASIH TERBUKA (laten, belum berdampak) | `object_store.py:183-220` |
| 9. Impersonasi via `display_name` notes | MASIH TERBUKA | `profile_validation.py:25-76`, `notes.html:124-127` |
| 10. Greeting Gemini sinkron, tanpa batas total, fallback 404 | MASIH TERBUKA | `main.py:150-221` (terburuk ~12 dtk) |
| 11. Advisory `pypdf` / pin `xhtml2pdf` | MASIH TERBUKA (advisory baru 10) | `requirements.txt:6` = 6.21.1; fix ≥6.21.4; `xhtml2pdf==0.2.20` aman saat ini |
| 12. PO lintas tenant, baris tanpa `perusahaan`, katalog bersama | OBSERVATION (by design, struktural) | `security.py:31-33`, `migration/001:17-24`, `po_routes.py:979-1007,1105-1107` |

## 10. Temuan penting lainnya

- **E2E staging hijau penuh** (PASS 41/FAIL 0 audit penuh; RPC `replace_product_formula` + restore formula bekerja; XSS E1–E3 lolos) — menguatkan kestabilan runtime saat ini.
- **Artefak staging tertinggal 1 baris** `brand_legal_documents` dari smoke (skrip tanpa penghapusan) — sanitasi manual disarankan.
- **Detail keamanan tersembunyi**: `Referrer-Policy: no-referrer` benar; `main.py:1315-1327` cegah open-redirect 413; guard presigned URL SigV4 benar (kecuali residu selektor E-07b).

## 11. Cakupan audit: file dibaca, dilewati, batasan

**Fase 1–2 dibaca penuh/paralel:** `README.md`, `panduan_dip_automation_system.md` (903 baris), `AGENTS.md`, `.gitignore`, `catatan/*.md` (6 file), `app/main.py`, `app/config.py`, `app/security.py`, `app/object_store.py`, `app/dip_public.py`, `app/dip_documents.py` (bagian fetch), `app/efek_samping.py`, `app/presence_routes.py`, `app/file_validation.py`, `app/profile_validation.py`, `app/env_guard.py`, `app/staging_guard.py`, `app/staging_preflight.py`, `app/products_routes.py` (grep + 224-383,766-845,1149-1536), `app/raw_materials_routes.py` (grep + 1-1990), `app/po_routes.py` (1-1312), `app/notes_routes.py` (penuh), `app/sample_routes.py`, `app/brands_routes.py`, `app/company_docs_routes.py`, `app/product_attachments_routes.py`, `app/dashboard_routes.py`, `app/admin_users_routes.py`, `app/profile_routes.py`; `app/templates/*.html` (semua via grep pola + `base/login/public_error/notes/admin_users/dip_public_hub`), `app/static/*.js` (semua; `common/lampiran/presence/sidebar/darkmode/po-analytics/efek_samping`); `migration/*.sql` header 001–011 + `audit_storage/backfill_r2_urls/verify_r2_readiness`; `scripts/check_*.py`, `run_staging_8017.py`; `.github/workflows/*.yml`; `requirements*.txt`, `.python-version`; `tests/*.py` whitelisted (dibaca + dieksekusi).

**Dilewati (sesuai larangan):** `.env*`, `LOGIN.md` (kredensial hanya diekspor, tak di-log), `backup-rls/`, `tests/snapshot_dip.py`, `scripts/r2_live_smoke.py`, dan workflow manual di luar whitelist. Produksi tidak di-query sama sekali.

**Batasan eksplisit:** (1) Audit statis + eksekusi test lokal/staging; struktur RLS/migrasi SQL hanya header, perilaku live tidak diuji; `read` DB live tidak dilakukan. (2) Nilai env Render/isi `R2_PUBLIC_BASES`/CORS bucket & DNS publik tidak terverifikasi. (3) `product-attachments` staging kosong (0 objek) — tidak ada bukti soak lampiran. (4) E2E D1/G1/G2 skip (tenant kedua & kanal SQL tidak tersedia). (5) `pip-audit`/`gitleaks` report-only tidak dijalankan di sesi ini (kecuali untuk advisory via Audit G). (6) Hasil di clone bersih dari HEAD lokal; working-tree lokal tidak ikut. Area yang tidak dibaca dalam tidak dinyatakan “aman” — seluruhnya terdaftar di atas.

## 12. Kesimpulan & prioritas

**Sebelum cutover R2 (wajib):** (1) Perbaiki E-05 (`unquote` parser + `quote` backfill) + test roundtrip — blocker encoding. (2) Validasi `R2_PUBLIC_BASES` sebelum tulis (E-06 fail-fast) dan soak `product-attachments` via UI mode r2. (3) Bump `pypdf` ≥ 6.21.4 (PR terpisah, uji manual Bab II + gabungan Bab I–IV sesuai Dependabot). (4) Tambah `main()` runner ke `test_auth_matrix.py`/`test_upload_validation.py` dan masukkan `test_verify_r2_readiness_logic.py` ke CI — tanpa ini regresi lolos diam-diam. (5) Audit `put` R2 privat + buktikan `r2.dev` terbuka dari kantor dan jaringan verifikator luar (DNS 1.1.1.1 workaround tidak cukup sebelum cutover). (6) Perbaiki README §4 (launcher staging utama; `uvicorn` pindah ke catatan produksi `DIP_APP_ENV=production`).

**Setelah cutover (segera):** (7) Tambah rate-limit `/dip/*` + audit download/ZIP (F-08/F-09) dan samarkan `?access=` di log/access (F-05). (8) Uji E2E `upload` mode r2 + audit penuh ulang. (9) Perluas selektor cache-bust ke `pub-*.r2.dev` (E-07b) dan verifikasi CORS bucket via `--origin`.

**Opsional (terjadwal):** (10) CSRF token + CSP/HSTS produksi; bundle Tailwind lokal/SRI (A-06/A-07). (11) Tenant guard untuk finished-spec, efek samping, lampiran, FSP (A-10..A-13) + fail-closed profil hilang (C-01/A-17) dan keunikan/tampilan `display_name` (A-18). (12) Greeting AI: batas total `asyncio.wait_for`, model+timeout env-configurable, log tipe exception (C-05). (13) Transaksi RPC untuk edit komponen & sinkronisasi dokumen (D-01..D-14).

> Catatan: tidak ada temuan yang diperbaiki dalam sesi audit ini (sesuai aturan READ-ONLY). Semua temuan di atas dilengkapi bukti `file:baris` dan dapat ditindaklanjuti sebagai PR terpisah.
