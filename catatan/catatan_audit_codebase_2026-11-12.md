# Laporan Audit Kode & Keamanan — DIP Automation System

**Tanggal audit:** 12 November 2026
**Commit yang diaudit:** `bf9815e9a2ba54cff407359037c0971c8dadfe61` (`main`, hasil merge PR #80)
**Sifat:** READ-ONLY terhadap kode aplikasi. Tidak ada file `app/`, `tests/`, `migration/`, atau konfigurasi yang diubah. Satu-satunya perubahan repo adalah dokumen laporan ini.
**Batasan kredensial:** tidak membaca `.env*`, `LOGIN.md`, atau `backup-rls/`. Tidak ada koneksi ke Supabase/R2 staging maupun produksi. Semua eksekusi memakai env dummy CI dengan jaringan diblokir (pola `ci.yml`).
**Bahasa:** Bahasa Indonesia, mengikuti konvensi `catatan/`.

---

## 1. Ringkasan eksekutif

**Kesehatan: baik, dengan satu kelas risiko baru yang belum tercatat di audit mana pun.**

Kualitas engineering repo ini di atas rata-rata: 36/36 test pure-local CI hijau, static check bersih, `pip-audit` **0 advisory**, guard staging fail-closed, CSRF guard berlapis, portal publik `/dip/*` sudah fail-closed + timing-safe + rate-limited + ber-audit. Sebagian besar temuan audit 21 Okt / 27 Okt / 5 Nov **sudah benar-benar ditutup** (lihat §5 — 22 item terverifikasi tertutup).

Yang menjadi fokus laporan ini:

| Kelompok | Jumlah | Catatan |
| :--- | :---: | :--- |
| Temuan **baru** (belum ada di 3 audit sebelumnya) | **9** | 2 TINGGI, 4 SEDANG, 3 RENDAH |
| Temuan lama **masih terbuka** (diverifikasi ulang) | **12** | termasuk 2 TINGGI struktural (FE-01, SEC-05) |
| Temuan lama **terverifikasi tertutup** | **22** | dengan bukti `file:baris` / hasil eksekusi |
| Risiko yang **diterima sadar** (keputusan pemilik repo) | **6** | bukan celah, dicatat agar tidak dilaporkan ulang |

**Tema temuan baru:** PR #80 (7 jam sebelum audit ini) memperkenalkan `app/pagination.py` untuk mengatasi pemotongan diam-diam oleh `db.max-rows=1000`, tetapi **baru diterapkan pada 1 dari sekian banyak call site**. Sister call site yang lain masih mengambil koleksi tanpa `.range()`, dan yang paling berbahaya: **guard "terpotong" di analytics PO membandingkan terhadap batas yang diminta (5000), bukan batas server (1000), sehingga tidak akan pernah menyala.**

**Tiga hal yang saya sarankan dikerjakan lebih dulu:**

1. **N-01** — KPI `/po-analytics` bisa salah tanpa peringatan apa pun (guard truncation mati).
2. **N-02** — notifikasi kedaluwarsa bahan baku (ED) bisa kehilangan batch setelah tabel melewati 1000 baris. Ini isu mutu/regulatori, bukan sekadar tampilan.
3. **SEC-05** — `_client_ip` mempercaya elemen pertama `X-Forwarded-For`. Selain membuat rate-limit login bisa dilewati, ini **juga membatalkan mitigasi F-08 yang baru dipasang di `/dip/*`** dan membuat kolom `ip_address` di audit trail bisa dipalsukan.

---

## 2. Metodologi & bukti yang benar-benar dieksekusi

Semua perintah dijalankan pada clone bersih commit di atas, Python 3.11.2, venv terpisah, dependensi dari `requirements.txt` + `requirements-ci.txt` (pin repo, tanpa perubahan).

| Langkah | Perintah | Hasil |
| :--- | :--- | :--- |
| Static check nama | `python scripts/check_undefined_names.py` | exit 0 — `[OK] 32 file` |
| Static check aturan | `python scripts/check_static_rules.py` | exit 0 — syntax, route duplikat, Jinja, inline JS |
| Kompilasi | `python -m compileall -q app scripts` | exit 0 |
| Import terisolasi | blok `import app.main` dengan socket diblokir (pola `ci.yml`) | sukses, `app.main.app` terbentuk |
| Unit test CI | 36 file `tests/test_*.py` yang terdaftar di `ci.yml` | **36 PASS / 0 FAIL** |
| Unit test di luar CI | `test_bahansemi_spec_parameters.py`, `test_manual_preview_pdf.py` | **2 PASS** (lihat N-07) |
| Audit dependensi | `pip-audit -r requirements.txt` | **0 vulnerability** (advisory `pypdf` 5 Nov sudah tertutup di `6.21.4`) |
| Inventaris route | introspeksi `app.routes` + pohon `dependant` | **114 route**, **51 mutasi** (semua POST) |
| Analisis AST query | deteksi rantai `.execute()` tanpa `limit/range/single` | **184 call site** (dipilah manual, lihat N-01..N-04) |

**Hasil inventaris otorisasi (mekanis, bukan kesan):**

- **51/51 route mutasi punya dependency auth.** Hanya `/login` dan `/logout` yang tanpa `get_current_user` — memang seharusnya begitu. Tidak ada endpoint tulis yang telanjang.
- **10/10 route `/admin/*` punya cek `role != "admin"`** di body handler.
- **31 route memanggil `assert_same_tenant` langsung**; sisanya lewat helper (`_guard_product`, `_owned_attachment`) atau memang lintas-tenant by design.
- **49 route memanggil `log_activity`**. Dari 51 mutasi, yang tanpa jejak audit: `/login`, `/logout`, `/api/presence/heartbeat` (disengaja) dan **`/brands/quick-add` (tidak disengaja — N-05)**.
- **113 dari 114 route berbentuk `async def`; ≥86 di antaranya memanggil `.execute()` sinkron** di badan handler (belum termasuk helper). Ini kuantifikasi baru untuk FE-01.

Catatan kejujuran metode: analisis AST atas `log_activity`/`assert_same_tenant` memberi 2 false-positive awal (`efek_samping.generate` mencatat lewat `_generate_monitoring_efek_samping_inner`, `lampiran` menjaga lewat `_guard_product`). Keduanya sudah dibaca manual dan **dinyatakan aman**, tidak masuk daftar temuan.

---

## 3. Temuan BARU

Format: ID · klasifikasi · risiko · lokasi · dampak · bukti · saran.

### N-01 · CONFIRMED · **TINGGI** — Guard "terpotong" di analytics PO tidak akan pernah menyala

**Lokasi:** `app/po_routes.py:84` (`_PO_STATS_LIMIT = 5000`), `:79` (`_PO_LIST_LIMIT = 5000`), `:476`, `:560`, `:870`

Kode mengambil PO dengan `.limit(5000)` lalu menyimpulkan kelengkapan data dari jumlah baris yang kembali:

```python
# po_routes.py:560
stat_complete = len(stat_rows) < _PO_STATS_LIMIT      # 1000 < 5000 -> True
# po_routes.py:476
"truncated": len(po_by_id) >= _PO_STATS_LIMIT,        # 1000 >= 5000 -> False
# po_routes.py:870
ana["produk_truncated"] = len(prod_rows) >= _PO_STATS_LIMIT
```

Bila `db.max-rows = 1000` (asumsi yang **dipakai repo ini sendiri** di `app/pagination.py:6`, `app/dashboard_routes.py:103`, dan `app/raw_materials_routes.py:646`), server mengembalikan maksimal 1000 baris. `1000 < 5000` selalu benar → `stat_complete = True` dan `truncated = False`, **padahal data terpotong**. Guard yang dirancang untuk memberi tahu user justru menjadi jaminan palsu.

**Dampak:** `total_po`, `total_pcs`, komposisi per kuartal, grafik per perusahaan, Top-5 produk, daftar "PO belum punya item", dan `produk_diproduksi` dihitung dari subset 1000 baris pertama (urutan `tanggal_po desc`) — jadi yang hilang justru PO terlama. Komentar di `:76` menyebut "~420 PO saat ini", jadi ini **belum terpicu hari ini**, tetapi tabel PO bertambah terus dan tidak ada alarm saat batas terlampaui. Untuk halaman analitik yang dipakai mengambil keputusan produksi, salah senyap lebih buruk daripada error.

**Saran:** ganti ke `paginate_all()` dari `app/pagination.py` (sudah ada, sudah teruji `tests/test_paginate_all.py`), atau bila memang ingin batas keras: set `_PO_STATS_LIMIT = 1000` dan deteksi `len(rows) == page_size`. Tambahkan test pure-local yang mensimulasikan halaman penuh 1000 baris.

### N-02 · CONFIRMED · **TINGGI** — Notifikasi ED bahan baku diambil tanpa pagination

**Lokasi:** `app/main.py:262-272` (`get_ed_notification_count`), `app/presence_routes.py:91` (`GET /api/ed-notifications`)

```python
# main.py:266 — dipanggil dari hampir setiap halaman lewat base.html
supabase.table("raw_material_batches").select("id, tanggal_ed, status_ed")
    .neq("status_ed", "Dimusnahkan").execute()          # tanpa .range()/.limit()

# presence_routes.py:91 — versi API, lebih berat lagi
supabase.table("raw_material_batches").select("*, raw_materials(nama_dagang, kode_bahan_baku)")
    .neq("status_ed", "Dimusnahkan").execute()
```

Filter "≤180 hari menuju ED" dilakukan **di Python setelah** semua baris diambil. Begitu `raw_material_batches` melewati 1000 baris, batch di luar 1000 baris pertama tidak pernah masuk hitungan badge maupun daftar notifikasi.

**Dampak:** bahan baku yang kedaluwarsa bisa **tidak muncul** di bell notifikasi dan badge ED — tepat di fitur yang menjadi kontrol mutu sebelum bahan dipakai produksi. Tabel batch adalah tabel yang tumbuh paling cepat di sistem ini (setiap kedatangan bahan = 1 baris), jadi ini bukan skenario jauh. Aspek beban query per halaman sudah tercatat sebagai F-01/F-02; **aspek pemotongannya baru**.

**Saran:** pindahkan filter tanggal ke server (`.lte("tanggal_ed", (today+180d).isoformat())`, `.not_.is_("tanggal_ed", "null")`) lalu paginasi sisanya dengan `paginate_all`. Ini sekaligus menutup F-01/F-02 karena payload turun drastis. Tambahkan cache pendek (mis. 60 detik) untuk helper yang dipanggil tiap halaman.

### N-03 · CONFIRMED · SEDANG — Halaman master `/raw-materials` terpotong, padahal badge-nya sudah dipaginasi

**Lokasi:** `app/raw_materials_routes.py:479-483` dan `:500`; pembanding `:646-660`

```python
rm_resp = supabase.table("raw_materials").select(
    "*, raw_material_components(*), "
    "raw_material_composition_variants(*, raw_material_components(*)), "
    "raw_material_company_docs(*)"
).order("nama_dagang").execute()                        # tanpa .range()
```

PR #80 sudah memakai `paginate_all` untuk menghitung badge "N Produk" (`:656-660`), tetapi **daftar bahan bakunya sendiri** dan query batch (`:500`) masih tanpa paginasi.

**Dampak:** inkonsistensi yang membingungkan — badge bisa menghitung pemakaian untuk bahan yang barisnya tidak tampil di tabel. Selain itu query ini menarik 4 relasi bersarang untuk seluruh tabel pada setiap kunjungan halaman; ini kandidat terkuat untuk lambat seiring pertumbuhan data.

**Saran:** paginasi + search/filter di sisi server untuk tabel master, atau minimal `.range()` berhalaman dengan indikator "menampilkan N dari M".

### N-04 · CONFIRMED · SEDANG — Atribusi perusahaan/produk di daftar PO tanpa pagination

**Lokasi:** `app/po_routes.py:690` dan `:737`

```python
pr = supabase.table("purchase_order_items") \
    .select("purchase_order_id, products(nama_produk, perusahaan)") \
    .in_("purchase_order_id", po_ids).order("urutan").execute()   # tanpa .range()
```

`po_ids` bisa berisi ratusan PO (batas daftar 5000), dan satu PO punya banyak item. Total item dengan mudah melewati 1000.

**Dampak:** PO yang item-nya terpotong akan tampak sebagai **"Tanpa item"** dan tidak teratribusi ke PT Erfi/PT Heka — persis kegagalan yang ingin dihindari komentar di `:682` ("Satu query untuk semua PO ... jadi tidak ada N+1"). N+1-nya memang sudah dihindari, tetapi digantikan risiko pemotongan.

**Saran:** paginasi `.in_("purchase_order_id", po_ids)` dengan `paginate_all`, atau chunk `po_ids` per batch kecil lalu gabungkan.

### N-05 · CONFIRMED · SEDANG — `/brands/quick-add` tidak tercatat di audit trail

**Lokasi:** `app/main.py:1555-1608`; pembanding `app/brands_routes.py:36-103`

`POST /brands/add` menulis `log_activity` di 4 titik (sukses, duplikat, validasi, gagal). `POST /brands/quick-add` — jalur yang dipakai modal "Tambah merk baru" dari form produk, jadi justru jalur yang paling sering dipakai — **menulis baris `producers` dan `brands` tanpa satu pun `log_activity`**.

**Dampak:** README (§Hardening Audit Trail) menyatakan "tambah merk" sudah ditutup dari daftar operasi berisiko yang tidak tercatat. Klaim itu benar untuk `/brands/add`, tidak untuk `/brands/quick-add`. Jejak siapa yang membuat produsen/merk baru hilang untuk jalur utama.

**Saran:** panggil `log_activity(current_user, "create", "brand", new_brand["id"], brand_name, request=request)` — perlu menambahkan parameter `request: Request` dan `log_activity` ke signature handler. Sekalian catat pembuatan produsen baru. Tambahkan kasus ini ke `tests/test_audit_regressions.py`.

### N-06 · CONFIRMED · SEDANG — Tidak ada `Cache-Control: no-store` pada halaman ber-sesi

**Lokasi:** `app/main.py:378-408` (`SecurityHeadersMiddleware`), `:541-549` (`_CachedStaticFiles`)

Satu-satunya `Cache-Control` di aplikasi adalah `public, max-age=3600` untuk aset statis. Respons HTML berisi data DIP, formula, harga/qty PO, dan data pengguna tidak membawa direktif cache apa pun.

**Dampak:** halaman sensitif dapat disimpan cache browser (tombol Back setelah logout masih menampilkan data) dan, bila ada proxy perantara yang meng-cache respons tanpa direktif, berpotensi tersimpan di luar perangkat pengguna. Risiko naik pada komputer bersama di lingkungan lab/kantor.

**Saran:** di `SecurityHeadersMiddleware`, set `Cache-Control: no-store, private` untuk respons `text/html` (kecuali `/static/*` dan `/health`). Murah, tanpa perubahan template, dan bisa diuji dengan test pure-local seperti `test_access_log_redaction.py`.

### N-07 · CONFIRMED · RENDAH — Dua unit test ada di repo tetapi tidak dijalankan CI

**Lokasi:** `.github/workflows/ci.yml:62-99` vs `tests/test_bahansemi_spec_parameters.py`, `tests/test_manual_preview_pdf.py`

Keduanya di-whitelist `.gitignore`, punya runner, pure-local, dan **LULUS** saat dijalankan manual dalam audit ini:

```
[PASS] normalize: string JSON diparse menjadi list ... Semua test spec_parameters LULUS.
[PASS] qc manual preview: beda tenant -> 403 ... Semua test manual preview PDF LULUS.
```

**Dampak:** ini pola yang sama dengan D-11 (5 Nov) yang sudah ditutup untuk `test_verify_r2_readiness_logic.py` — terulang lagi untuk dua file yang ditambahkan kemudian. Test yang tidak pernah jalan tidak mencegah regresi; `test_manual_preview_pdf` bahkan menjaga guard tenant 403.

**Saran:** tambahkan dua baris ke `ci.yml`. Lebih tahan lama: ganti daftar manual dengan `python -m pytest tests/ -q` (pytest sudah dipin di `requirements-ci.txt` tapi belum pernah dipakai CI), sehingga file test baru otomatis ikut.

### N-08 · CONFIRMED · RENDAH — `/health` tidak menguji dependensi apa pun

**Lokasi:** `app/main.py:740-741`

```python
async def health_check():
    return {"status": "i know i'm strong, but ya Allah tolong"}
```

**Dampak:** uptime monitor tetap hijau walaupun Supabase tidak terjangkau, kunci service-role dicabut, atau R2 mati. Untuk aplikasi yang seluruh fungsinya bergantung pada dua layanan eksternal, health check ini tidak memberi sinyal apa pun. (Konten string-nya juga kurang pantas untuk endpoint yang mungkin dipantau pihak ketiga.)

**Saran:** pertahankan `/health` sebagai liveness murah, tambahkan `/health/ready` yang melakukan satu query ringan ber-timeout (mis. `select id from profiles limit 1`) dan mengembalikan 503 bila gagal. Jangan gabungkan keduanya agar kegagalan DB tidak memicu restart loop.

### N-09 · CONFIRMED · RENDAH — 83 cookie flash di-set tanpa `secure`/`samesite`

**Lokasi:** `app/main.py:1451`, `app/brands_routes.py:43,73,98`, `app/sample_routes.py:435,442`, dan 78 titik lain (`set_cookie("error_msg"|"success_msg", ...)`)

Cookie sesi sudah benar (`httponly=True, secure=True, samesite="lax"`, `main.py:1348-1362`). Cookie pesan flash tidak memakai flag apa pun.

**Dampak:** rendah — Jinja autoescape menutup XSS (`base.html:209,216` merender dengan `{{ }}`), dan isinya pesan server, bukan input mentah. Tetap inkonsisten dengan standar cookie sesi, dan isi pesan bisa ikut terkirim pada request lintas-situs.

**Saran:** tambahkan `secure=True, samesite="lax"` pada helper flash-cookie terpusat. `httponly` **tidak bisa** dipakai di sini karena `base.html:230-231` menghapus cookie lewat JavaScript — jadi sebaiknya satu helper saja agar keputusan ini terdokumentasi di satu tempat.

---

## 4. Temuan lama yang MASIH TERBUKA (diverifikasi ulang di commit ini)

| ID lama | Judul | Risiko | Bukti `file:baris` saat ini |
| :--- | :--- | :---: | :--- |
| **SEC-05** | `_client_ip` mengambil elemen **pertama** `X-Forwarded-For` → rate-limit bisa dilewati dengan mengganti header tiap request | **TINGGI** (naik dari SEDANG) | `main.py:344-354`, dipakai `limiter` `:419` dan `/dip/*` `:1823` |
| **FE-01** | Klien Supabase sinkron memblokir event loop. **≥86 dari 113 route `async def`** memanggil `.execute()` sinkron; `get_current_user` melakukan 2 round-trip blocking (`auth.get_user` + query `profiles`) pada **setiap** request | **TINGGI** | `main.py:744-800`; `postgrest 2.31.0` `.execute()` bukan coroutine (diverifikasi via `inspect`) |
| **A-06 / SEC-12** | CDN tanpa SRI. `login.html` & `public_error.html` masih memuat **Tailwind Play CDN v3** (`cdn.tailwindcss.com`, tanpa pin, EOL) di permukaan **pra-auth**; `base.html` memakai `@tailwindcss/browser@4` tanpa pin; FontAwesome 6.4.0 & Chart.js 4.4.3 tanpa `integrity` | **TINGGI** | `login.html:7-8`, `public_error.html:7-8`, `base.html:52-53` |
| SEC-03 / C-03 / A-12 | Dokumen legal merk: `brand_id` tidak divalidasi (UUID/eksistensi), tanpa guard tenant/kepemilikan; **upload ke storage terjadi sebelum baris brand diverifikasi** → objek orphan bila `brand_id` ngawur. Dokumen ini masuk PDF Bab I | SEDANG | `brands_routes.py:180-247` (0 panggilan `assert_same_tenant` di modul ini) |
| A-07 (sisa) | CSP & HSTS didefinisikan tetapi **default OFF** (di-gate env) | SEDANG | `main.py:372-373`, `:396-400` |
| — | `/docs`, `/redoc`, `/openapi.json` terbuka tanpa auth (`FastAPI()` tanpa `docs_url=None`) → seluruh skema API terpublikasi | SEDANG | `main.py:357`; terkonfirmasi di inventaris route |
| C-05 | Greeting AI **di jalur login**: 3 model dicoba berurutan × timeout 4 dtk, tanpa batas total → worst case ~12 dtk sebelum user masuk | SEDANG | `main.py:173-221`, dipanggil `:1342` |
| F-01 / F-02 | ED dihitung ulang di setiap halaman, 2 query berat tanpa cache/visibility check | SEDANG | `main.py:262`, `presence_routes.py:91` (lihat juga N-02) |
| A-09 | Validasi upload hanya magic-byte `%PDF` + ukuran 10 MB; tanpa cek ekstensi/tipe MIME | SEDANG | `file_validation.py:6-20` |
| C-15 | Create user TOCTOU: cek username unik lalu insert (tanpa constraint/transaksi), dan ceknya mengambil **seluruh** tabel `profiles` | SEDANG | `admin_users_routes.py:114-150` |
| A-18 | `display_name` tanpa keunikan → impersonasi visual di notes/header | SEDANG | `profile_validation.py:24-76` (hanya format & panjang) |
| SEC-17 | Rate limit hanya `/login` + `/dip/*`; upload, `POST /notes`, `POST /purchase-orders`, endpoint admin tanpa batas | RENDAH | `main.py:419`, `:1265`; `dip_public.py:240-243` |

**Catatan penting tentang SEC-05 (interaksi baru).** Audit 5 Nov memasang rate-limit `/dip/*` untuk menutup F-08. Kunci limiter itu adalah `client_ip=_client_ip` (`main.py:1823`) — fungsi yang sama yang sudah dinyatakan CONFIRMED bermasalah sejak 21 Okt. Akibatnya:

- penyerang cukup mengirim `X-Forwarded-For: <IP acak>` per request untuk melewati batas 20/menit (bab) dan 5/menit (ZIP) — generator PDF/ZIP tetap bisa di-scrape;
- batas login 5/menit juga tidak efektif terhadap brute-force yang memutar header;
- kolom `ip_address` di `activity_logs` (hasil hardening audit trail) dapat diisi nilai palsu, melemahkan nilai forensiknya.

Satu perbaikan kecil — ambil elemen **terakhir** XFF (atau `request.client.host` bila tidak di belakang proxy tepercaya) — menaikkan nilai tiga fitur keamanan sekaligus. Karena itu saya menaikkan prioritasnya ke P0.

---

## 5. Temuan lama yang TERVERIFIKASI TERTUTUP

Ini bukan daftar klaim; setiap baris dicek di kode commit ini atau dibuktikan lewat eksekusi.

| ID lama | Status | Bukti |
| :--- | :--- | :--- |
| SEC-01 (route soft-delete hilang) | **TERTUTUP** | `POST /products/delete/{product_id}` terdaftar di inventaris route |
| SEC-02 (isolasi tenant nyaris nol) | **TERTUTUP signifikan** | 31 route memanggil `assert_same_tenant` langsung + helper `_guard_product`/`_owned_attachment`; test `test_sec02_po_rm_guard`, `test_tenant_guard_*` hijau |
| SEC-04 (cookie tanpa `secure`) | **TERTUTUP** | `main.py:1348-1362` `httponly/secure/samesite` untuk `access_token` & `greeting_cache` |
| SEC-06 / A-07 (nol CSRF) | **TERTUTUP (lapisan Origin/Referer)** | `app/csrf_guard.py` 299 baris + `tests/test_csrf_guard.py` PASS; urutan middleware benar (`main.py:415-416`) |
| SEC-07 (nol security header) | **TERTUTUP sebagian** | `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy: same-origin` aktif (`main.py:378-408`); CSP/HSTS masih off |
| SEC-08 (open redirect 413) | **TERTUTUP** | `main.py:1443-1449` membandingkan netloc Referer dengan host request |
| SEC-09 / item 4 (portal publik fail-open) | **TERTUTUP fail-closed** | `dip_public.py:393-410`; `test_dip_public_check.py` PASS |
| SEC-13 / A-04 (ED bell tanpa escape) | **TERTUTUP** | `base.html:300-336` semua field lewat `escapeHtml`, id lewat `encodeURIComponent` |
| SEC-16 (`/logout` via GET) | **TERTUTUP** | `main.py:1378` `@app.post("/logout")` |
| SEC-18 (artefak `omniroute`) | **TERTUTUP** | `brands.html:1` = `{% extends 'base.html' %}` |
| F-03 (revoke tidak fungsional) | **TERTUTUP** | `dip_public.py:406` cek `public_access_revoked_at` sebelum cabang lain; `test_dip_public_revoke.py` PASS |
| F-05 (token `?access=` di log) | **TERTUTUP (sisi aplikasi)** | `_redact_access_value` + `_RedactAccessTokenFilter`; `test_access_log_redaction.py` PASS |
| F-07 (token dibandingkan `==`) | **TERTUTUP** | `dip_public.py:382` `hmac.compare_digest` |
| F-08 (nol rate-limit `/dip/*`) | **TERTUTUP secara desain** | `dip_public.py:240-243` batas per-IP + per-produk; efektivitasnya tersandera SEC-05 |
| F-09 (download/ZIP tanpa jejak) | **TERTUTUP** | `_audit_public_access` dipanggil di hub & tiap bab (`dip_public.py:283,448`) |
| E-05 (`parse_storage_url` tanpa unquote) | **TERTUTUP** | `object_store.py:200,219` `unquote(path)`; `test_parse_storage_url.py` PASS |
| C-06 (restore selalu "sukses") | **TERTUTUP** | `dashboard_routes.py:68-79` cek baris + `outcome="rejected"` |
| C-07 (delete+insert tanpa transaksi) | **TERTUTUP** | RPC `replace_raw_material_components` (`raw_materials_routes.py:1298-1317`, migrasi 013); `test_raw_material_components_atomic.py` PASS |
| C-10 (lampiran `success:True` parsial) | **TERTUTUP** | `product_attachments_routes.py:185-200` rollback objek storage bila insert gagal |
| C-01 / A-17 (profil hilang → fail-open) | **TERTUTUP fail-closed** | `main.py:795-812`: DB error → 503, profil tak ada → 403; `test_auth_profile_fail_closed.py` PASS |
| False-green test (5 Nov §8) | **TERTUTUP** | `test_auth_matrix.py:34` & `test_upload_validation.py:35` punya runner; dieksekusi menghasilkan 1 + 6 PASS nyata |
| Advisory `pypdf` (10 temuan) | **TERTUTUP** | `requirements.txt` pin `pypdf==6.21.4`; `pip-audit` sesi ini **0 vulnerability** |
| D-11 (test whitelist tak jalan) | **TERTUTUP untuk file itu** | `test_verify_r2_readiness_logic.py` ada di `ci.yml`; tapi polanya terulang → N-07 |

---

## 6. Risiko yang diterima secara sadar (bukan temuan)

Dicatat supaya audit berikutnya tidak melaporkannya lagi sebagai celah:

1. **Staff boleh mengerjakan data lintas perusahaan** — keputusan pemilik repo 2026-11-09, tertulis di `app/security.py:14-22`. Guard hanya mengikat akun yang `perusahaan`-nya terisi.
2. **`log_activity` fail-open** — keputusan 2026-10-05, `main.py:1105-1109`. Kegagalan audit tidak membatalkan operasi bisnis.
3. **CSRF tanpa token per-form** — desain berlapis: `SameSite=Lax` + validasi Origin/Referer. Residu "Origin dan Referer dua-duanya absen → izinkan" didokumentasikan eksplisit di docstring `csrf_guard.py`.
4. **Service-role melewati RLS** — semua otorisasi di lapisan aplikasi (`app/database.py:52`). Konsekuensinya: bug otorisasi aplikasi = akses data penuh, sehingga inventaris route seperti §2 layak dijadikan pemeriksaan rutin.
5. **Migrasi SQL manual, tidak lewat pipeline** — `AGENTS.md` §3.
6. **`X-Frame-Options: SAMEORIGIN`, bukan `DENY`** — diperlukan untuk preview PDF same-origin (`main.py:361-364`).

---

## 7. Prioritas yang disarankan

| Prioritas | Item | Alasan | Perkiraan lingkup |
| :---: | :--- | :--- | :--- |
| **P0** | N-01, N-02 | Kebenaran angka analitik & kontrol kedaluwarsa bahan; keduanya salah **senyap** | 2 PR kecil, pakai `paginate_all` yang sudah ada + test pure-local |
| **P0** | SEC-05 | Satu perbaikan menaikkan nilai rate-limit login, rate-limit `/dip/*`, dan integritas IP audit trail | 1 fungsi + test; perlu keputusan sumber IP tepercaya (Render) |
| **P1** | N-03, N-04 | Kelas pemotongan yang sama, dampak tampilan/atribusi | 1 PR paginasi daftar |
| **P1** | N-05, N-07 | Menutup klaim audit trail yang belum penuh & membuat test benar-benar jalan | 2 PR kecil |
| **P1** | A-06 | Bundle Tailwind lokal (atau SRI + pin) — menghapus dependensi runtime ke CDN di halaman login | 1 PR frontend, perlu uji 4 tema |
| **P1** | FE-01 | Bungkus panggilan DB dengan `run_in_threadpool` (atau pindah ke klien async) — throughput naik tanpa ubah logika | bertahap, mulai dari `get_current_user` |
| **P2** | N-06, N-08, N-09, CSP/HSTS, `/docs`, C-05, C-15, A-09, A-18, SEC-17 | Hardening & kebersihan | masing-masing PR kecil |

**Urutan yang saya sarankan:** N-01 + N-02 dalam satu PR bertema "paginasi kebenaran data" (satu test file baru), lalu SEC-05 sendiri (karena menyentuh asumsi deployment), baru sisanya.

---

## 8. Lampiran

### 8.1 Cara mereproduksi

Skrip analisis disimpan **di luar repo** (folder kerja `audit/`) agar tidak mengotori tree:

```bash
python -m venv .venv && .venv/bin/pip install -r repo/requirements.txt -r repo/requirements-ci.txt
cd repo
export PYTHONPATH=. SUPABASE_URL=https://ci.invalid.supabase.co \
       SUPABASE_KEY=ci-dummy-anon-key SUPABASE_SERVICE_ROLE_KEY=ci-dummy-service-role-key \
       STORAGE_BACKEND=supabase
../.venv/bin/python scripts/check_undefined_names.py
../.venv/bin/python scripts/check_static_rules.py
../.venv/bin/python ../audit/route_inventory.py     # inventaris 114 route + dependency auth
../.venv/bin/python ../audit/query_bounds.py app    # 184 .execute() tanpa limit/range/single
../.venv/bin/pip-audit -r requirements.txt
```

`route_inventory.py` meniru blok "isolated app import" di `ci.yml` (socket diblokir), lalu menulis `audit/routes.json`. `query_bounds.py` murni AST — tidak mengimpor app dan tidak menyentuh jaringan.

### 8.2 Cakupan

**Dibaca penuh:** `app/config.py`, `env_guard.py`, `staging_guard.py` (header), `csrf_guard.py`, `security.py`, `database.py`, `safe_fetch.py`, `file_validation.py`, `profile_validation.py`, `pagination.py`, `notes_routes.py` (bagian render & API), `brands_routes.py`, `product_attachments_routes.py`, `dashboard_routes.py` (bagian relevan), `admin_users_routes.py` (bagian relevan), `dip_public.py` (bagian relevan), seluruh `app/templates/*.html` via grep pola berisiko, `.github/workflows/ci.yml`, `.gitignore`, `AGENTS.md`, `requirements*.txt`, dan 3 laporan `catatan/` sebelumnya.

**Dibaca sebagian (grep + blok terkait):** `main.py`, `po_routes.py`, `raw_materials_routes.py`, `products_routes.py`, `sample_routes.py`, `efek_samping.py`, `object_store.py`, `dip_documents.py`, `presence_routes.py`.

**Tidak dilakukan:** E2E staging (butuh kredensial yang tidak boleh dibaca), query DB live, uji beban, verifikasi konfigurasi Render/Cloudflare, verifikasi RLS di database, uji penetrasi aktif. Area yang tidak dibaca mendalam **tidak** dinyatakan aman.

### 8.3 Klasifikasi

- **CONFIRMED** — terlihat langsung di kode dan/atau dibuktikan lewat eksekusi.
- **POTENTIAL** — butuh kondisi runtime yang tidak dapat diverifikasi dari repo (mis. nilai `db-max-rows` aktual, perilaku proxy Render).

Temuan N-01..N-04 ditandai CONFIRMED untuk **logika kodenya**; pemicu dampaknya bergantung pada `db.max-rows = 1000`. Nilai itu adalah asumsi yang sudah dipakai repo ini sendiri di tiga tempat, tetapi **tidak dapat diverifikasi dari repo** — bila ternyata di-set lebih tinggi atau tanpa batas, dampak N-01..N-04 turun menjadi isu beban query, bukan kebenaran data. Cara memastikan: Supabase Dashboard → Settings → API → `db-max-rows`, atau bandingkan `select count(*)` dengan jumlah baris yang dikembalikan REST tanpa `.range()`.

---

*Laporan ini tidak mengubah kode aplikasi. Semua temuan dilengkapi bukti `file:baris` dan dapat ditindaklanjuti sebagai PR terpisah sesuai alur repo (commit per domain, test pure-local, CI hijau).*
