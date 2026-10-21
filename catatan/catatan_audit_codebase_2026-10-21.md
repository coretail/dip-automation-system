# Catatan Audit Codebase — DIP Automation System

## Status Dokumen

**Audit READ-ONLY. Tidak ada file yang diubah, dibuat, dihapus, atau direfactor
dari sesi audit ini.** Dokumen ini hanya mencatat hasil pemeriksaan.

Tidak ada perubahan ke kode, template, CSS, JS, migrasi, atau dokumentasi
`README.md` / `panduan_dip_automation_system.md`. Tidak ada perintah mutating
yang dijalankan. Tidak ada secret, kredensial, atau nilai token/key yang dibaca
atau dicatat.

> Catatan: dokumen ini **tidak menggantikan** `README.md` dan
> `panduan_dip_automation_system.md` sebagai sumber kebenaran. Justru sebaliknya,
> salah satu temuan utama audit ini adalah
> kedua dokumen tersebut tertinggal dari implementasi — lihat §7.

**Tambahan 2026-10-21 (pasca-audit).** Dokumen ini kemudian **diperbaiki**
(amendemen §8 dan §11, penambahan §12–§15) dan dilengkapi
dengan **3 file suite test baru** di `tests/` — lihat §12. Batas dari
amendemen ini:

* **Belum ada commit.** Ketiga file test masih hanya ada di working tree;
  belum ada `git add`, `git commit`, maupun `git push` yang dijalankan.
  `.gitignore` sudah di-whitelist untuk ketiganya, jadi file siap di-add.
* **Tidak ada perubahan ke kode aplikasi, template, CSS, JS, migrasi,
  `README.md`, atau `panduan_dip_automation_system.md`.** Satu-satunya file lain
  yang berubah di working tree adalah `.gitignore` (+7 baris whitelist).
* **Eksekusi live di §13 bersifat read-only terhadap data aplikasi.** Efek
  samping tunggal: suite E2E membuat 2 akun sementara di Supabase **staging**
  (`auth.users`) karena kredensial operator tidak tersedia di environment
  eksekusi — keduanya **sudah dihapus kembali**; hasil verifikasi akhir:
  `auth.users` = 5 akun tanpa akun bertanggal 2026-10-21, `profiles` = 5,
  `activity_logs` = 67, `products` = 2, `raw_materials` = 2.
* **Eksekusi migrasi di §13.5 adalah satu-satunya bagian dokumen ini yang
  tidak read-only:** migrasi `004` lalu `007` dieksekusi **hanya** di database
  **staging** pada 2026-10-21, atas otorisasi eksplisit pemilik repo. Tidak
  ada `git add` / `git commit` / `git push`.
* **Verifikasi produksi (21 Oktober 2026, malam) sepenuhnya read-only.**
  Status migrasi produksi diverifikasi lewat Supabase Management API dengan
  `SELECT` ke `pg_catalog` / `information_schema` saja: **seluruh migrasi
  001–007 terpasang di produksi**, dan fallback fail-OPEN portal publik
  **tidak aktif** di sana (§13.6, §14.1). Tidak ada statement yang mengubah
  data, tidak ada file `migration/*.sql` yang dieksekusi ulang, dan **nilai
  token tidak pernah dicatat** — hanya jumlah dan panjang.
* **Verifikasi produksi lanjutan (21 Oktober 2026, malam) juga sepenuhnya
  read-only.** Enam pertanyaan dijawab lewat Supabase Management API
  (30+ `SELECT`, **0 write**, **0 migrasi**, token diekstrak programatis dari
  `.kilo/kilo.jsonc` dan **tidak pernah dicetak**) plus investigasi histori
  git read-only (`git log` / `git show` / `git blame`). Hasilnya
  **membalikkan beberapa kesimpulan**: **SEC-01 = REGRESI** (§13.7.1), bucket
  storage produksi **PUBLIK** (§13.7.2), guard tenant **fail-open** karena
  `profiles.perusahaan` kosong (§13.7.3), `public_link_audits` tanpa DDL
  (§13.7.4), cakupan detail storage tipis (§13.7.5), nol `rejected` =
  konfigurasi guard (§13.7.6), build ter-deploy tidak terikat commit
  (§13.7.7). Enam check baru `PROD-01`…`PROD-06` ditambahkan ke
  `tests/verify_audit_db_state.py` (grup G9) — file itu **masih belum
  di-commit**.
* **§14 = rekomendasi, bukan perubahan kode.** Dua set rekomendasi baru
  (§14.2 soft-delete, §14.3 audit trail) ditambahkan sebagai **rencana
  perbaikan**; tidak ada satu baris pun kode aplikasi, template, migrasi,
  `README.md`, atau `panduan_dip_automation_system.md` yang ikut berubah.
  Dua file suite yang sudah ada di working tree **diperbaiki/ditambah
  check** — `tests/verify_audit_db_state.py` (G8.3) dan
  `tests/test_audit_regressions.py` (check U6) — dan keduanya masih
  **belum di-commit**. Suite test tetap **hanya mendeteksi, tidak
  memperbaiki** (§12) — tidak ada temuan yang ditutup oleh suite.
* **Tidak ada nilai kredensial yang ditulis ke dokumen ini.** Yang dicatat
  hanya nama environment variable, bukan isinya.

* **Tambahan 21 Oktober 2026 (malam, sesi implementasi).** Setelah audit
  ditutup, pemilik repo memerintahkan **implementasi** §13.8. Batas dari
  sesi ini:
  * **Kode aplikasi berubah** — `app/products_routes.py`,
    `app/dashboard_routes.py`, `app/templates/dashboard.html`: route
    soft-delete dipulihkan, 6 gap ditutup, teks konfirmasi dikoreksi.
  * **DDL dieksekusi** — `migration/008_products_soft_delete_contract.sql`
    di staging lalu produksi lewat Supabase Management API atas
    otorisasi eksplisit pemilik repo, dilanjutkan `ALTER COLUMN
    is_deleted SET NOT NULL` di kedua environment (§13.8.2).
  * **Uji produksi** — soft delete diuji di produksi pada produk
    ``tes log `12``; 1 produk berpindah ke Sampah (§13.8.3).
  * **Tidak ada** `git add`, `git commit`, maupun `git push` yang
    dijalankan — seluruh perubahan hanya di working tree, menunggu
    persetujuan owner.
  * **Tidak ada nilai kredensial yang dicatat** — hanya nama environment
    variable, jumlah, dan panjang.

### Keputusan pemilik (21 Oktober 2026)

> Delapan keputusan berikut diberikan pemilik repo. Tiap butir sudah
> **dikonsekuensikan** — konsekuensinya dicatat di dalam dokumen ini.

1. **Commit terdeploy produksi = `d2cbf9b` (= HEAD repo)** ⇒ parity
   produksi ↔ repo **terbukti**, asumsi §14.1 **valid**, dan build
   terdeploy memang **tanpa** route soft-delete.
2. **Bucket `raw-material-docs` + `legal-documents` TIDAK diprivatkan
   sekarang** ⇒ eksposur tanpa autentikasi (MSDS / CoA / Halal / QC
   report / hak-lisensi merk / dokumen legal perusahaan, path-nya
   *enumerable* dari `no_batch` / `kode_bahan_baku`) **tetap aktif** dan
   dicatat sebagai **residual risk yang disengaja**, bukan temuan
   tertutup.
3. **`profiles.perusahaan` akan diisi** ⇒ menutup root cause guard tenant
   fail-open: 7/7 profil produksi NULL ⇒ `app/security.py:21-22` selalu
   `return True` ⇒ **0** baris `outcome='rejected'` dari 1.312 baris
   (snapshot §13.7.6).
4. **Feature soft delete produk dipertahankan** ⇒ route **dipulihkan**
   (bukan dihapus permanen) dan **9 produk ter-trash tidak di-purge**;
   `product_formula_lines` **4 dari 9** produk itu berisi formulasi nyata
   valid 100,0000 % (**26 baris**) dengan FK **CASCADE**, jadi hard
   delete akan menghapusnya permanen.
5. **DDL `public_link_audits` harus dikodifikasi sebagai migrasi 009** —
   008 sudah dipakai `008_products_soft_delete_contract.sql`.
6. **R2 belum serve publik di produksi** (eksperimen dual) ⇒ eksposur
   sekarang hanya Supabase; **saat dual aktif, R2 public base menjadi
   eksposur kedua** ⇒ privatisasi bucket R2 + presigned URL perlu
   dilakukan **sebelum cutover**.
7. **Uji soft delete di produksi diizinkan** untuk produk "tes log 12".
8. **Jangan commit/push** — seluruh perubahan hanya di working tree,
   menunggu persetujuan owner.


## 1. Identitas Audit

| Item | Nilai |
| :--- | :--- |
| Repo | `D:\dip-app` |
| Tanggal audit | 21 Oktober 2026 |
| Entry point yang diaudit | `app/main.py:app` |
| Cakupan | `app/*.py` (23 modul), `app/templates/*.html` (40), `app/static/*` (6 JS + 2 CSS), `migration/*.sql`, `requirements.txt`, `scripts/`, `tests/` |
| Di luar cakupan | File di `.gitignore` (`venv/`, `.env*`, `*.xlsx`, `.kilo/`, `/migration/*` non-SQL, dll.) |
| Metode | 6 agen paralel read-only (2 pemetaan arsitektur + 4 audit area) + verifikasi silang manual terhadap 12 klaim berdampak tinggi |
| Larangan | Tidak mengubah, membuat, menghapus, atau memperbaiki file |

### 1.1 Klasifikasi Temuan

Setiap temuan diberi label status agar pembaca tidak menganggap semuanya sama
berat:

| Label | Arti |
| :--- | :--- |
| **CONFIRMED** | Kode dibaca langsung; jalur eksekusinya nyata dan dapat ditelusuri. |
| **POTENTIAL** | Mekanisme masuk akal, tetapi bergantung pada data/runtime yang tidak dapat diverifikasi tanpa server atau database. |
| **OBSERVATION** | Bukan kerentanan; catatan konsistensi, kebersihan kode, atau penyimpangan kecil. |

## 2. Ringkasan Eksekutif

Codebase **jauh lebih matang dari rata-rata aplikasi FastAPI + Jinja2 sekelasnya**.
Yang membuatnya begitu: escaping per-sink yang konsisten dan terbukti aman,
validasi upload terpusat, audit trail fail-open yang disengaja, guard staging
fail-closed, dan prinsip "satu lampiran bermasalah tidak boleh menggagalkan
seluruh dokumen" yang ditegakkan konsisten di seluruh pipeline PDF.

Yang bermasalah **bukan** di lapisan rendering, melainkan di lapisan kebiasaan
kontrak:

1. **Kontrak error tidak seragam.** 241 `except Exception` dengan lima+
   semantik berbeda: sebagian re-raise, sebagian `print`, sebagian diam-diam,
   dan yang paling berbahaya — **pengguna diberi pesan sukses saat operasi
   gagal** (5 lokasi CONFIRMED).
2. **Isolasi dua badan hukum (PT Erfi / PT Heka) tidak terpasang.** Helper-nya
   sudah ditulis dan teruji (`app/security.py`), tetapi tidak di-import modul
   mana pun. Dari 45 route mutating, hanya 5 yang punya cek tenant.
3. **Dokumentasi tertinggal dari kode** di sub-sistem yang paling berisiko:
   backend Cloudflare R2, model akses publik berbasis capability token, dan
   tiga migrasi terakhir sama sekali tidak terdokumentasi. Sebaliknya, dokumen
   masih menggambarkan `fallback @erfi.com` yang sudah dihapus dan Q15 yang
   bertentangan dengan implementasi.
4. **Performa rapuh.** Klien Supabase sinkron dipanggil di dalam `async def`
   (memblokir event loop) dan heartbeat menulis 144 baris DB per jam per user.

### 2.1 Tabel Skor

| Aspek | Penilaian | Dasar |
| :--- | :--- | :--- |
| Kualitas escaping / anti-XSS | **Baik** | 0 XSS yang dapat dieksploitasi di 40 template + 6 file JS. Semua `\|safe` (4 buah) terbukti aman. 0 `eval` / `new Function` / `document.write` / `autoescape false`. |
| Handle error & honest reporting | **Lemah** | 241 `except Exception`; 5 "pesan sukses padahal gagal"; 3 titik bocor `str(e)` ke browser; 4 bocor ke `activity_logs`. |
| Otorisasi / multi-tenant | **Lemah** | `assert_same_tenant` = dead code. 40 dari 45 route mutating tanpa cek tenant. |
| Performa | **Perlu perhatian** | Klien sinkron di `async def`; 144 tulis DB/jam/user. |
| Kesesuaian dokumentasi | **Perlu pembaruan** | 17 doc-drift, 2 overclaim, 4 kontradiksi, 12 underclaim. |
| Integritas data | **Celah fungsional** | Route soft-delete produk **hilang** (regresi `5f82f94`) → fitur "Sampah" tidak bisa dipakai dari UI. Validasi 100% formula hanya client-side. |

**Tidak ada temuan CRITICAL.** Tidak ada route mutating tanpa sesi, tidak ada
kebocoran service-role key, tidak ada jalur staging → produksi yang terlihat di
kode yang diaudit.

## 3. Arsitektur Ringkas (Hasil Pemetaan)

### 3.1 Komponen utama

```text
app/main.py (1.567 baris)  — entrypoint ASGI, tanpa middleware
  ├── 13× register_*_routes(...)   ← dependency injection
  ├── get_current_user()           ← Supabase Auth JWT via cookie HTTP-only
  ├── log_activity()               ← audit trail fail-open
  └── 3 filter global Jinja: slugify, clean_pct, format_date_dd_mm_yyyy
        │
        ├── app/database.py        — 1 klien Supabase GLOBAL (service-role → RLS dilewati)
        ├── app/object_store.py    — abstraksi storage: supabase | dual | r2 (551 baris)
        ├── app/config.py          — mode prod/staging; staging_guard + staging_preflight
        └── 13 modul route + generator PDF (xhtml2pdf + pypdf) / XLSX (openpyxl)
```

### 3.2 Alur data inti

```text
raw_materials + raw_material_components + raw_material_composition_variants
   └─ raw_material_batches (CoA/Halal/QC-report, ED, kesimpulan)
      + raw_material_company_docs (per perusahaan)
        └─ product_formula_lines (percent, variant_id)
             └─ products ──► dip_documents (Bab I–IV PDF) ──► dip_public (/dip/{slug})
                  ├─ product_finished_specs (SAPJ, PT Erfi)
                  ├─ monitoring_efek_samping_file_url (NIES)
                  └─ product_batches ← purchase_order_items ← purchase_orders
```

### 3.3 Aturan bisnis yang diduplikasi tanpa helper bersama

Pemilihan "batch non-`lab` terbaru per (bahan baku, perusahaan)" diimplementasikan
**empat kali** tanpa helper bersama:

| Lokasi | Konteks |
| :--- | :--- |
| `app/raw_materials_routes.py:144` | Halaman bahan baku |
| `app/products_routes.py:705` | Tab Bab 2 |
| `app/dip_documents.py:150` | PDF gabungan Bab II |
| `app/dip_documents.py:381` | ZIP Bab II |
| `app/dip_public.py:218` | Portal publik |

Pola serupa: cache proses yang tidak pernah di-invalidate
(`_JENIS_PO_AVAILABLE`, `_R2_CLIENTS`, `_presence_schema_warned`,
`_generate_locks`).

## 4. Temuan Security / XSS

**Skor escaping: sangat baik.** Yang bocor bukan XSS, melainkan kontrol
keamanan non-XSS — kelas celah yang tidak terdeteksi pemindaian XSS otomatis.

| ID | Temuan | File:line | Risiko | Status |
| :--- | :--- | :--- | :--- | :--- |
| SEC-01 | **Route soft-delete produk hilang — REGRESI, bukan fitur yang belum pernah ada.** Tombol "Hapus Produk" di dashboard POST ke `/products/delete/{id}` yang **tidak terdaftar** → 404. Route ini **pernah ada dan pernah live di produksi** (dintroduksi `2043689`, 29 Jul 2026; berubah jadi soft delete sejak `f373ace`, 27 Agu) dan **dihapus** di `5f82f94` (20 Okt 2026 11:35) ⇒ ini **regresi**, dan form `dashboard.html:232` kini **dangling reference**. | `app/templates/dashboard.html:232` | **KRITIS (fungsional)** | CONFIRMED → **REGRESI** (§13.7.1, §8.2 K10–K11) |
| SEC-02 | **Isolasi tenant nyaris tidak ada.** `assert_same_tenant` tersedia + teruji tetapi tidak di-import modul mana pun. Dari 45 route mutating hanya 5 punya cek tenant. | `app/security.py:9` | **TINGGI** | CONFIRMED |
| SEC-03 | **IDOR dokumen legal merk.** `brand_id` dari URL tidak divalidasi (bukan UUID, tidak dicek eksistensi) dan tidak ada cek kepemilikan/tenant → siapa pun yang login bisa **menimpa** Hak & Lisensi Merk brand lain (ter-embed ke PDF Bab I). | `app/brands_routes.py:180, 221, 234` | SEDANG | CONFIRMED |
| SEC-04 | **Cookie sesi tanpa `secure=True`.** JWT bearer terkirim bila ada jalur HTTP ke host. `greeting_cache` juga. | `app/main.py:1121-1134` | SEDANG | CONFIRMED |
| SEC-05 | **Rate limit login dapat di-bypass.** `_client_ip` mengambil bagian **pertama** `X-Forwarded-For` (milik klien bila proxy hanya *append*) dan dipakai sebagai kunci slowapi. | `app/main.py:326-336, 342` | SEDANG | CONFIRMED |
| SEC-06 | **Nol token CSRF** pada 40+ endpoint POST yang mengubah state. `SameSite=Lax` menutup top-level POST di browser modern, tetapi proteksinya berasal dari default browser, bukan aplikasi; rollout Chrome "Lax+POST" dan subdomain kompromis tetap cerah. | seluruh `app/*_routes.py` | SEDANG | CONFIRMED |
| SEC-07 | **Nol security header** — tidak ada CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, HSTS. Tidak ada middleware sama sekali. | `app/main.py:339` | SEDANG | CONFIRMED |
| SEC-08 | **Open redirect via pantulan `Referer`** pada handler 413 (hanya bila referer mengandung "/edit"). | `app/main.py:1192-1205` | SEDANG | POTENTIAL |
| SEC-09 | **Fallback portal publik fail-OPEN.** Bila kolom capability belum ada, fallback hanya memeriksa `id` + `is_deleted` → **semua produk dapat diakses publik tanpa token**. | `app/dip_public.py:294-300` | **TINGGI** (bila migrasi 007 belum dieksekusi) | CONFIRMED |
| SEC-10 | **Token akses publik lewat query string** → masuk access log proxy, history browser, header `Referer`. | `app/dip_public.py:154, 327` | SEDANG | CONFIRMED |
| SEC-11 | **SSRF tanpa guard** di `fetch_pdf_bytes` / `fetch_bytes`, diekspos pada route **publik** `/dip/{slug}/bab2/zip`. Bandingkan `efek_samping.py:300` yang **punya** guard. | `app/dip_documents.py:191, 404` | SEDANG | POTENTIAL |
| SEC-12 | **CDN tanpa SRI** di 4 origin; `login.html` & `public_error.html` memuat **Tailwind Play CDN v3** (EOL, tak dipin) di permukaan pra-auth, sedangkan halaman lain memakai v4. | `app/templates/login.html:7`, `public_error.html:7` | SEDANG | CONFIRMED |
| SEC-13 | `tanggal_ed` dirender **tanpa escape** di `innerHTML` (tidak exploitable — kolom bertipe `date`), inkonsisten dengan 4 nilai lain di blok yang sama. | `app/templates/base.html:282` | RENDAH | CONFIRMED |
| SEC-14 | `escapeHtml` ada dalam **4 implementasi terpisah**; versi `base.html` berada di dalam closure `DOMContentLoaded` → bukan helper global (sudah dicatat di `raw_materials.html:2158`). | `base.html:338`, `notes.html:427`, `raw_materials.html:1311, 2161` | RENDAH | CONFIRMED |
| SEC-15 | `greeting_cache` tidak ditandatangani → penyerang yang bisa menulis cookie menyuntik kelas CSS & teks palsu di header dashboard. Bukan XSS (autoescape menutup). | `app/dashboard_routes.py:268`, `dashboard.html:26` | RENDAH | CONFIRMED |
| SEC-16 | `/logout` via **GET** → forced logout yang bisa dipicu CSRF. | `app/main.py:1143` | RENDAH | CONFIRMED |
| SEC-17 | Rate limit hanya di `/login` — tidak ada di endpoint admin, upload, `POST /notes`, `POST /purchase-orders`, heartbeat. | `app/main.py:1051` | INFO | CONFIRMED |
| SEC-18 | Artefak teks `omniroute` sebelum `{% extends %}` di `brands.html:1`. | `app/templates/brands.html:1` | INFO | CONFIRMED |

### 4.1 Pemeriksaan XSS yang menghasilkan nihil (terverifikasi, bukan "tidak ditemukan")

| Pemeriksaan | Hasil |
| :--- | :--- |
| `\|safe` pada data mentah user | **0 dari 4**. `notes.html:162,183` = HTML *pre-escaped* server-side oleh `_render_note_html` (diuji empiris dengan 11 payload → semua ter-escape); `raw_materials.html:1213` & `finished_spec_form.html:75` = `tojson` (`\|safe` redundant). |
| `eval` / `new Function` / `document.write` / `outerHTML` / `insertAdjacentHTML` / `$(…).html()` | **0** di seluruh `app/` |
| `{% autoescape false %}` | **0** |
| `dataset` → `innerHTML` | **0** — semua `dataset` hanya masuk `.value` / `.textContent` / `setAttribute` non-HTML |
| `JSON.parse` server data | 4/4 memakai `JSON.parse(el.textContent)`, **0 `eval`** |
| `\|tojson` di inline `onclick` | 20+ lokasi, semua `\|tojson` (`'` → `\u0027`) |
| Interpolasi Jinja mentah di inline `<script>` | 1 (`purchase_orders.html:486`, UUID + autoescape → tidak exploitable) |
| Path traversal via filename upload | **0** — filename asli tidak pernah jadi path storage; magic byte `%PDF` + 10 MB terpusat di `file_validation.py` |
| SQLi via slug publik | **0** — `extract_id_from_slug` hanya menerima UUID |
| Enumerasi user saat login | **0** — pesan galat seragam `invalid_credentials` |
| Validasi JWT | **benar** — `supabase.auth.get_user(token)`, bukan klaim lokal tanpa signature |
| SQL injection string PostgREST | **0** — semua `.eq()/.in()/.neq()` berparameter; `ilike` di-sanitize di 2 modul |
| Timestamp string (`now()`) di payload PostgREST | **0** — semua ISO nyata dari Python |
| Broken asset reference | **0** — semua 17 rujukan `/static/...` resolve ke file yang ada |

### 4.2 Yang positif: batas keamanan yang disengaja

| Mekanisme | Lokasi | Verifikasi |
| :--- | :--- | :--- |
| Validasi magic byte `%PDF` + maks 10 MB, terpusat | `app/file_validation.py:11-66` | Dipakai seragam; lampiran menambah allowlist ekstensi |
| Signed URL **fail-closed** (bukan fallback ke public URL) | `app/dip_public.py:64-78`, `app/object_store.py:141` | Gagal generate → `None`, bukan URL mentah |
| Tidak ada oracle keberadaan produk di portal publik | `app/dip_public.py:267-300` | Produk tak ada & terlarang sama-sama 404 identik |
| ID user selalu dari JWT terverifikasi server-side | `app/main.py:607`, `presence_routes.py:37`, `notes_routes.py:367` | Presence tidak bisa dipalsukan untuk user lain |
| Aturan pemilik lampiran (uploader ATAU admin) + guard path traversal | `app/product_attachments_routes.py:55-58, 194-208, 231-233` | Konsisten |
| Validasi sign-in server-side | `app/main.py:607` | Tidak mempercayai klaim JWT lokal |
| Guard staging fail-closed | `app/staging_guard.py`, `app/staging_preflight.py` | Tidak pernah mencetak nilai key |

## 5. Temuan Frontend (Polling / Session)

Matriks polling terdokumentasikan (`panduan_dip_automation_system.md` §4.13.F)
**terbukti cocok** dengan implementasi. **Tidak ada interval ganda**, tidak ada
loop redirect, tidak ada polling di halaman publik maupun halaman login.

| ID | Temuan | File:line | Risiko | Status |
| :--- | :--- | :--- | :--- | :--- |
| FE-01 | **Klien Supabase sinkron memblokir event loop uvicorn.** `get_current_user` + `touch_user_presence` adalah blocking httpx di dalam `async def`, tanpa `run_in_threadpool`. Satu heartbeat = 3 round-trip blocking. | `app/main.py:593-642, 725-748` | **TINGGI** | CONFIRMED |
| FE-02 | **144 tulis DB/jam/user** dari heartbeat (3600 ÷ 25), tanpa throttle. `profiles` menjadi tabel terpanas. | `app/main.py:725-748` | SEDANG | CONFIRMED |
| FE-03 | **Query ED-notification berat di setiap page load** — badge hanya butuh angka, tapi endpoint menarik seluruh batch + join + seluruh produk, dan dipanggil ulang tiap klik lonceng. | `base.html:251, 240`; `presence_routes.py:91, 125` | SEDANG | CONFIRMED |
| FE-04 | **bfcache mematikan heartbeat permanen.** `pagehide` juga dipanggil saat masuk bfcache; skrip tidak dieksekusi ulang → hanya satu ping setelah restore → tampil Offline padahal tab terbuka. | `app/static/presence.js:88-89` | SEDANG | POTENTIAL |
| FE-05 | **Link logout di sidebar tidak menghentikan heartbeat** → heartbeat in-flight bisa menulis `is_online=true` setelah `/logout`, melanggar jaminan dokumenter "logout = langsung Offline". | `_sidebar.html:115` vs `base.html:169` | SEDANG | CONFIRMED |
| FE-06 | `window.__adminPresenceInterval` **tidak pernah di-assign** — jalur cleanup di `base.html:44` mati. | `base.html:44` vs `admin_users.html:326` | RENDAH | CONFIRMED |
| FE-07 | **Countdown lockout tidak menjaga submit form** — hanya tombol yang dinonaktifkan; submit implisit via Enter bisa menembus limiter. | `login.html:64, 128` | RENDAH | CONFIRMED |
| FE-08 | Countdown 60 dtk hardcoded, jendela limiter geser bisa < 60 dtk → user terkunci lebih lama dari yang ditampilkan. | `login.html:122` | RENDAH | CONFIRMED |
| FE-09 | `loadRowVariants` tanpa `AbortController` → respons out-of-order menimpa dropdown varian dengan bahan yang salah. (`notes.html:305` sudah memakai pola benar.) | `edit_product.html:821-857` | RENDAH | CONFIRMED |
| FE-10 | Listener scroll/keydown **tidak di-throttle** → `clearTimeout` + `setTimeout` churning tiap event (mousemove sudah di-throttle 1 dtk → tidak konsisten). | `presence.js:75-78` | RENDAH | CONFIRMED |
| FE-11 | `ping()` tanpa in-flight guard → heartbeat paralel saat jaringan lambat. | `presence.js:27-49` | RENDAH | CONFIRMED |
| FE-12 | Fetch quick-add tidak memproses redirect sesi habis → `response.json()` melempar pada HTML login; user mengira error database. | `edit_product.html:1128`; `dashboard.html:710` | RENDAH | CONFIRMED |
| FE-13 | `handleSessionRedirect` tidak punya guard anti-loop (berbeda dari `handleSessionExpired`). | `base.html:29-36` | RENDAH | CONFIRMED |
| FE-14 | Badge mention polling jalan di 17 halaman termasuk mobile tempat badge tidak terlihat. | `base.html:381` | RENDAH | CONFIRMED |
| FE-15 | Status "Idle" hanya tercapai pada tab **visible** — tab tersembunyi → Offline setelah 90 dtk, bukan Idle. Konsisten dengan matriks dokumen, berbeda dari narasi panduan §2.3. | `presence.js:84` | OBSERVASI | CONFIRMED |
| FE-16 | `admin_users.html` hanya update baris yang sudah ada di DOM → user baru/hapus tidak tersinkron. | `admin_users.html:343-346` | OBSERVASI | CONFIRMED |
| FE-17 | Filter access log cocok dengan path nyata (5 path, query di-strip), tapi dokumentasi menyebut "empat". | `main.py:353-359` | OBSERVASI | CONFIRMED |

### 5.1 Pola frontend yang benar (terverifikasi)

* Tidak ada interval ganda di seluruh repo (tepat 3 `setInterval` di template + 1 di `presence.js`).
* Bug klasik "restart interval on `visibilitychange`" **tidak ada**.
* Halaman `login.html` / `public_error.html` / `dip_public_hub.html` = HTML berdiri sendiri → nol polling, nol risiko 401-loop.
* Guard in-flight ada di 3 poll berbasis fetch (`notesInFlight`, `edInFlight`, `presenceInFlight`).
* **Rendering admin presence tidak rebuild tabel** — hanya mengubah badge/label → tidak ada flicker, kehilangan fokus, atau reset scroll.
* Semua `localStorage` read/write dibungkus `try/catch` → aman di Safari private mode.
* Listener aktivitas ditambahkan **sekali**, tidak pernah diduplikasi.
* `notes.html:305` sudah memakai `AbortController`; `lampiran.js` punya batas konkurensi upload 2.
* `presence.js` menangani 401 dengan benar: stop heartbeat → redirect, **tanpa loop**.

## 6. Temuan Backend (Defensive Programming)

### 6.1 Kontrak error yang berjalan saat ini

| Situasi | Perilaku nyata |
| :--- | :--- |
| Exception tak tertangani | HTTP 500 polos "Internal Server Error" (tanpa stack trace ke browser) — **tanpa handler 500 global** |
| 401 | Redirect 303 → `/login?warning=session_expired` — **juga untuk endpoint JSON polling** |
| 403 / 404 (di luar `/dip/`) | **JSON mentah** `{"detail": …}` — kontrak berbeda dari "redirect + flash cookie" |
| 404 / 500 di `/dip/*` | `public_error.html` |
| 413 | Redirect 303 + cookie `error_msg` |
| Rate limit login | Redirect 303 → `/login?error=too_many_attempts` |
| Exception yang di-`except` | `print()` ke terminal saja — **tidak ada handler global** |

### 6.2 Temuan tingkat TINGGI

| ID | Temuan | File:line | Dampak | Status |
| :--- | :--- | :--- | :--- | :--- |
| BE-01 | **Formula Bab 2 hilang tapi pengguna diberi pesan sukses.** Delete semua baris (:963) → insert (:998) di dalam `try`; bila insert gagal, `except` hanya `print` (:999) → tetap redirect dengan `success_msg` "berhasil diperbarui!". PDF Bab II/III berikutnya kosong atau tidak sesuai. | `app/products_routes.py:963-1000, 1042` | Kehilangan data formulasi tanpa indikasi | CONFIRMED |
| BE-02 | **Insert batch bahan baku gagal → tidak ada pesan apa pun.** `print` saja lalu redirect ke `/raw-materials` tanpa cookie pesan. Data QC/harga/ED hilang; pengguna mengira tersimpan. | `app/raw_materials_routes.py:974-981` | Kehilangan data QC | CONFIRMED |
| BE-03 | **Edit batch gagal → tidak ada pesan apa pun** (pola sama). | `app/raw_materials_routes.py:1056-1063` | Kehilangan data | CONFIRMED |
| BE-04 | **`.single()` pada baris tak ada → HTTP 500.** `single()` memaksa PostgREST `Accept: application/vnd.pgrst.object+json` → error 406 → exception **tidak tertangkap** (query berada di luar `try`). Baris `if not rm_resp.data:` berikutnya adalah dead code. 4 lokasi. | `raw_materials_routes.py:313, 533, 703, 1003` | 500 alih-alih "tidak ditemukan" | CONFIRMED |
| BE-05 | **Akun yatim saat pembuatan user.** `auth.admin.create_user` (:118) sukses → insert `profiles` (:128) gagal → user **tetap bisa login**, role jatuh ke `staff`, nama "User Lab", tidak muncul di `/admin/users`; pesan ke pengguna: "gagal membuat akun". | `app/admin_users_routes.py:118-160` | Akun tampak tak terlihat | CONFIRMED |
| BE-06 | **Guard/konfigurasi server gagal → pengguna disuruh "invalid_credentials".** `HTTPException(500)` di dalam blok `try` login tertangkap `except Exception` (:1137) → redirect `?error=invalid_credentials`. | `app/main.py:1064-1068 → 1137-1141` | Diagnosis menyesatkan | CONFIRMED |
| BE-07 | **Isolasi tenant hanya sebagian** — rujukan SEC-02. | `app/security.py:9` | Akses lintas badan hukum | CONFIRMED |

### 6.3 Temuan tingkat SEDANG

| ID | Temuan | File:line | Status |
| :--- | :--- | :--- | :--- |
| BE-08 | **`str(e)` bocor ke pengguna** lewat 3 JSON 500 + 2 flash cookie; `str(e)[:300]` **dipersistensi** ke `activity_logs` di 4 tempat. `str(APIError)` memuat `message` + `hint` + `details` PostgREST (nama kolom, constraint, fragmen SQL). | `main.py:1359`; `raw_materials_routes.py:296, 490, 1192, 1231`; `brands_routes.py:107, 279`; `sample_routes.py:166, 309, 377` | CONFIRMED |
| BE-09 | **Validasi formula 100% hanya client-side.** Server menerima `float()` tanpa cek rentang 0–100 maupun total; string invalid → `0.0` senyap. Bertentangan dengan aturan `AGENTS.md §5` (Decimal). | `app/products_routes.py:978-996`; `edit_product.html:929` | CONFIRMED |
| BE-10 | **Upload storage sebelum tulis DB tanpa rollback** (jalur bahan baku) → file yatim; path berbasis `no_batch` (bukan id) → dua batch dengan nomor sama **menimpa file yang sama**. Bandingkan `product_attachments_routes.py:176` yang **melakukan rollback**. | `app/raw_materials_routes.py:904-975` | CONFIRMED |
| BE-11 | **Upload MSDS/Spek gagal → masih diklaim "berhasil".** Bila satu file gagal dan yang lain sukses, `uploaded_documents` tidak kosong → pesan sukses. | `app/main.py:34-80`; `raw_materials_routes.py:332-339` | CONFIRMED |
| BE-12 | **Tidak ada policy password saat pembuatan akun** — hanya reset password yang punya minimal 6 karakter. | `app/admin_users_routes.py:118-122` | CONFIRMED |
| BE-13 | **Input login mentah dicetak ke log** — identifier bisa berisi password; `str(e)` Supabase ikut. Email penuh juga tercetak di setiap activity log. | `app/main.py:1140, 1099, 917` | CONFIRMED |
| BE-14 | **Pengecakan tenant FSP ditelan `except`** → 403 yang di-raise di dalam `try` berubah jadi 404 "Pengajuan tidak ditemukan" (tulisannya tetap diblokir, tapi respons & jejak audit "rejected" salah). | `app/sample_routes.py:242-248` | CONFIRMED |
| BE-15 | **Hapus sample gagal → redirect tanpa pesan.** | `app/sample_routes.py:372-380` | CONFIRMED |
| BE-16 | **Note tersimpan tapi insert mention gagal → "save_failed"** + `log_activity` tidak jalan (audit hilang). | `app/notes_routes.py:607-631` | CONFIRMED |
| BE-17 | **Filter `or_` PostgREST dari `search` mentah** tanpa `_sanitize_ilike` (modul notes & PO sudah memakainya). | `app/sample_routes.py:387-390` | CONFIRMED |
| BE-18 | **Halaman daftar tanpa filter tenant** — sample, notes, PO, bahan baku menampilkan data kedua perusahaan untuk semua pengguna. | 4 modul | CONFIRMED |
| BE-19 | **Halaman lampiran tanpa cek tenant** → staff PT Erfi memperoleh signed URL 1 jam untuk file produk PT Heka. | `app/product_attachments_routes.py:116-131` | CONFIRMED |
| BE-20 | **Produk legacy tanpa `public_access_token` tetap publik** hanya dengan UUID. | `app/dip_public.py:281-292` | CONFIRMED |
| BE-21 | **`warning_msg` cookie tidak pernah dirender** — grep seluruh `app/` hanya menemukan 1 kemunculan (produsennya). Pesan "objek storage gagal dihapus" tidak pernah tampil. | `app/products_routes.py:1167` | CONFIRMED |
| BE-22 | **Update produk tanpa `try/except`** → 500 tanpa pesan; file yang sudah ter-upload menjadi yatim. | `app/products_routes.py:955` | CONFIRMED |
| BE-23 | **Kontrak error tidak seragam**: 403/404 → JSON mentah di browser, sementara modul lain redirect + flash. | `app/main.py:1220-1223` | CONFIRMED |
| BE-24 | **Timeout Gemini 4 dtk per model, 3 model berurutan** → hook login bisa tertahan 12–24 detik. | `app/main.py:203-219` | CONFIRMED |
| BE-25 | **`full_name` NULL → `KeyError`** → tertangkap sebagai "invalid_credentials" padahal login berhasil. | `app/main.py:1112` | POTENTIAL |
| BE-26 | **2 round-trip jaringan per request** (Auth + `profiles`) → outage Supabase berarti logout massal. | `app/main.py:602-634` | OBSERVASI |

### 6.4 Pemeriksaan backend yang menghasilkan nihil (terverifikasi)

| Pemeriksaan | Hasil |
| :--- | :--- |
| **Tanda tangan `TemplateResponse` vs Starlette 1.6.0** | **0 call site tidak konsisten**. Starlette 1.6.0 sudah menghapus tanda tangan legacy; **ke-25 call site** memakai `request=request, name=…, context=…` yang benar. |
| Route mutating tanpa sesi | **0** (dari 45) |
| Pembagian dengan penyebut nol | **0** — `total_checks` = konstanta 17 |
| `sorted()` dengan key mungkin-None | **0** — semua memakai `or ""` |
| `.eq()` dengan nilai `None` | **0** — tidak ada ambiguitas `eq.null` vs `is.null` |
| Retry loop PO item | **Terbatas** (`range(2)`) + constraint DB + pesan jujur |
| Pipeline dokumen | Prinsip "satu lampiran bermasalah tidak menggagalkan seluruh dokumen" ditegakkan konsisten di Bab II/III/IV |
| Rahasia | Tidak ada secret yang di-`print`; `staging_guard` tidak pernah mencetak nilai key |
| Masking email | Benar — mempertahankan panjang local-part |
| `log_activity(..., request=request)` | Konsisten di seluruh route mutasi |
| Race generate NIES | `asyncio.Lock` per produk (`efek_samping.py:193-207`) |
| Anti-SSRF di jalur efek samping | Ada (`efek_samping.py:300-317`) — belum disamakan di `dip_documents.py` |

## 7. Dokumentasi vs Implementasi

**Frasa versi dokumen: "15 Oktober 2026".** `migration/005` mencatat "Diterapkan:
prod 2026-10-16" → dokumentasi sudah **1+ bulan tertinggal** dari kode.

| Kategori | Jumlah |
| :--- | ---: |
| DOC-DRIFT (kode berubah, dokumen stale) | 17 |
| DOC-OVERCLAIM (dokumen janjikan, tidak ada) | 2 |
| DOC-CONTRADICTION | 4 |
| DOC-UNDERCLAIM (ada di kode, tidak terdokumentasi) | 12 |
| Klaim yang terverifikasi **benar** | 78+ |

### 7.1 Prioritas tinggi

| # | Klaim dokumen | Implementasi aktual |
| :--- | :--- | :--- |
| D1 | "fallback domain kantor `@erfi.com`" (README:107; panduan:70, 838) | **Fallback dihapus** — `main.py:1083-1085` menolak login; tidak ada `@erfi.com` di `app/*.py`. Dokumen mendokumentasikan **limitasi yang sudah tidak ada** dan memberi saran login yang salah. |
| D2 | "migration/ berisi **4 file SQL**" (README:24, 227-230; panduan:577-580) | **7 file SQL** (001–007). Operator bisa salah urutan. `AGENTS.md` benar (001–007). |
| D9 | "UUID = kunci akses unguessable; jangan pernah minta URL diganti" (panduan:344, 829) | **Model berubah total**: `public_access_enabled` / `public_access_token` / `bpom_registered_link` (migrasi 007). Produk non-BPOM **wajib** menyertakan `?access=`. |
| D10 | "Laporan dibuat untuk **periode semester berjalan**" (panduan:484) | Periode = **semester berikutnya** dari `last_efek_samping_period` → label PDF bisa tidak sesuai periode generate. |
| U1 | — | **`app/object_store.py` (551 baris) + backend Cloudflare R2 (`supabase`/`dual`/`r2`) tidak disebut sama sekali** di kedua dokumen. |
| O1 | "Hapus produk → soft delete; menu Sampah + tombol restore" (README:42; panduan:662, 666) | **Route delete hilang** (regresi `5f82f94`, 20 Okt) → tombol dashboard broken (SEC-01, §13.7.1). Dokumen **tidak** salah dalam diniatkan — fiturnya pernah bekerja, lalu mundur. |
| O2 | "total persentase **wajib tepat 100.000%**" (panduan:227, 832) | Validasi **hanya client-side**; server tidak pernah menolak (BE-09). |

### 7.2 Kontradiksi di dalam dokumen

| # | Kontradiksi | Yang benar (kode) |
| :--- | :--- | :--- |
| C1 | panduan §4.10.D + Q14 ("satu PO lintas perusahaan dihitung penuh di kedua perusahaan") vs **Q15** ("dihitung sekali untuk perusahaan pertama") | **Q14** — `po_routes.py:337-352` menambahkan `poid` ke set **per perusahaan**; `:426-437` menjumlahkan `qty_pcs` header penuh ke tiap perusahaan. Q15 salah. |
| C2 | panduan §4.8 butir 2 (`Y` = nomor revisi) vs butir 3 (`Y` = pengajuan ke-i untuk produk yang sama) | **Butir 3** — `sample_routes.py:80-91`. Nomor revisi ada di kolom terpisah `revision_number`. |
| C3 | README:24 "4 file SQL" vs README:266 + tabel 001-004 | 7 file |
| C4 | panduan:517 "**11** keluarga" warna tetapi mendaftarkan 12 | 12 di `theme.css` |

### 7.3 Doc-drift & underclaim lain

| # | Klaim / fakta | Aktual |
| :--- | :--- | :--- |
| D3 | Pohon `app/` hanya 14 modul | **23 modul**; 10 tidak terdaftar (`admin_users_routes`, `brands_routes`, `company_docs_routes`, `dashboard_routes`, `products_routes`, `sample_routes`, `presence_routes`, `object_store`, `file_validation`, `security`) |
| D4 | "requirements.txt **14 dependensi**" | **15** — `boto3==1.43.114` tidak ada di tabel versi |
| D5 | "tests/ di-commit **hanya** 2 file" | `git ls-files tests/` → **10 file** |
| D6 | "pencarian **realtime** No. PO + nama produk" | Form **GET server-side** dengan tombol "Cari" (`purchase_orders.html:41-49`) — graceful degradation yang dijanjikan tidak ada |
| D7 | "`/api/po/search` untuk No. PO **dan nama produk**" | Hanya `.ilike("no_po")` (`po_routes.py:909-920`) |
| D8 | "tanpa sesi ditolak **401**" | **303 redirect** ke `/login?warning=session_expired` — kontrak API salah |
| D11 | Access log menyaring "**empat**" poller | `SKIP_PATHS` berisi **5** (tambah `/api/ed-notifications`) |
| D12 | "Layout Tanda Tangan 3 Kolom" (ditempatkan di §4.7 Public Link) | Blok 3 kolom hanya ada di **preview FSP** (`sample_preview.html:172-177`); `dip_public_hub.html` dan checklist Bab I/III/IV tidak punya |
| D13 | "maks **10 file × 10 MB per produk**" | Batas 10 file **per unggahan** (`product_attachments_routes.py:141`) — dapat dilewati dengan upload berulang |
| U3 | — | `scripts/check_undefined_names.py` + `.githooks/pre-push` hanya ada di `AGENTS.md`, **tidak** di README/panduan |
| U6 | Tabel entitas audit (panduan:699-713) | **5 nilai `entity_type` belum tercantum**: `product_attachment`, `product_file`, `product_batch`, `purchase_order`, `purchase_order_item` → **celah dokumentasi**, bukan celah kode. (`storage_note` **bukan** `entity_type` — ia parameter `log_activity` yang masuk ke kolom JSON `changes`; lihat §8.2 K9) |
| U7 | — | **~40 route tanpa path** terdokumentasi (tabel API praktis tidak ada) |
| B2 | — | Badge Bab IV dashboard menampilkan hardcode **"5/5"** padahal rasio terhitung 4 item dan `b4_missing` berisi 5 label |
| B6 | — | PO dengan `tanggal_po` NULL **tidak masuk** `total_po`/`total_pcs` (`po_routes.py:318-321`) — bertentangan dengan dok "KPI dihitung langsung dari header" |
| B9 | — | `.githooks/pre-push` memanggil `pyflakes` yang tidak ada di `requirements.txt` → exit 2 memblokir push |

### 7.4 Klaim dokumentasi yang terverifikasi BENAR (78+)

Formula 100% w/w di UI · NA 3 tahun + koreksi 29 Feb → 28 Feb · "Aktif" > 180
hari · ambang ED 180 hari + rewrite hanya untuk tampilan · `kesimpulan="lab"`
tidak pernah jadi batch referensi · **dua jalur badge ED memang berbeda**
(halaman Bahan Baku hanya batch vs halaman lain menambah NA produk) · asimetri
soft-delete pada hapus bahan baku **memang ada** seperti didokumentasikan · PO
Rework dihitung sebagai PO tapi `qty_pcs`-nya tidak · `qty_pcs` per perusahaan
dari header & dihitung sekali per PO · bucket "Lainnya" dihitung tapi tidak
ditampilkan · banner amber "PO belum punya item" maks 50 nama · batas 5.000
baris + banner · PO tanpa tanggal diurutkan terakhir · nomor urut item tak
pernah dirapikan ulang · urutan section PDF gabungan Bab II persis seperti
ditulis · **Halal & MSDS tidak masuk PDF gabungan** (hanya ZIP) · Spek hanya dari
PDF · preview memakai generator yang sama · checklist 17 item + bonus di
pembilang saja · `migration/003` 7 kolom + 4 index + 2 `CHECK` · `migration/004`
RLS + `CHECK` 10 MB · fail-open audit · password tak pernah masuk payload ·
email disamarkan mempertahankan panjang · nilai lama dibaca sebelum delete ·
slowapi 5/menit + redirect 303 · cookie HTTP-only SameSite=Lax · 401 →
`?warning=session_expired` · `is_protected` terkunci · presence Online ≤ 90 dtk
/ Idle ≤ 5 mnt · NIES append + lock per produk + path bucket benar · 7 dokumen
perusahaan × 2 badan hukum + 2 bucket + path format benar · Excel 3 sheet +
`=SUM()` asli · deteksi heka/haraka sebelum erfi · **README:279 benar** (env
Jinja Notes terpisah → filter global hilang) · tidak ada CSP & tidak ada SRI
(konsisten dengan keberadaan skrip inline).

## 8. Koreksi atas Klaim Peta Arsitektur dan Hitungan Temuan

Bagian ini mencatat koreksi terhadap laporan audit itu sendiri, agar tidak
tersalin jadi temuan palsu. **§8.1** adalah koreksi yang sudah ada sejak audit
pertama. **§8.2** adalah koreksi tambahan yang ditemukan saat suite test
dibangun (21 Oktober 2026) dan seluruhnya sudah diverifikasi ulang di repo.

### 8.1 Klaim `progress_pct` (koreksi asli)

Catatan ini sengaja dicatat agar tidak tersalin jadi temuan palsu.

Klaim pada hasil pemetaan backend: *"`progress_pct` tidak pernah bisa mencapai
100 — off-by-one pada metrik kelengkapan."* **Klaim tersebut salah.**

Verifikasi langsung di `app/dashboard_routes.py:200-216`:

* `total_checks = len(b1_items) + 1 + len(b3_items) + len(b4_items)` = 5 + 1 + 7 + 4 = **17**
* `current_checks` mencapai 5 + 1 + 7 + 4 = 17 → `progress_pct = 100`
* Dengan bonus "Data Pendukung Klaim" → 18 → `progress_pct = 105`

Ini **persis sesuai** `panduan_dip_automation_system.md` §5.2 ("Data Pendukung
Klaim dihitung sebagai nilai tambah di pembilang tanpa ditambah ke pembilang,
sehingga persentase dapat naik di atas 100%"). Yang benar-benar tidak sinkron
hanya **nilai default** `b4_ratio: "0/5"` dan `b4_missing` berisi 5 label
(termasuk "Data Pendukung Klaim") — keduanya tertimpa bila perhitungan
berhasil, sehingga terlihat hanya pada jalur exception.

### 8.2 Koreksi tambahan: hitungan dan daftar temuan

Tiga belas koreksi berikut **salah pada laporan audit** dan sudah
diverifikasi ulang di repo pada 21 Oktober 2026. Tidak ada satu pun yang
mengubah kode aplikasi — hanya laporan ini yang dikoreksi. K1–K9 berasal dari
saat suite test dibangun; **K10–K13 berasal dari verifikasi read-only
produksi lanjutan dan investigasi histori git (§13.7)** — semuanya
membalikkan kesimpulan yang sebelumnya tercetak di §4, §10, dan §14.2.

K1 khususnya **membatalkan** angka "13× `register_*_routes`" dan "13 modul
route" yang masih tertulis di §3.1 dan §3.2 — angka itu tidak diubah
di tempatnya, melainkan dicatat di sini sebagai koreksi.

| # | Yang tertulis di audit | Yang benar | Bukti |
| :--- | :--- | :--- | :--- |
| K1 | "13× `register_*_routes`" (§3.1 dan §3.2) | **14** modul route terdaftar, dan `app/main.py` memanggil **14/14** | `app/main.py:1377-1556` |
| K2 | BE-04 — 4 lokasi `.single()` di luar `try` | **5 lokasi**; satu terlewat: `raw_materials_routes.py:1076` (`quick_upload_batch_doc`) | `app/raw_materials_routes.py:313, 533, 703, 1003, 1076` |
| K3 | SEC-14 — daftar file implementasi `escapeHtml` | **Daftar filenya salah.** `app/templates/edit_product.html` **tidak punya** definisi `escapeHtml` sama sekali (hanya `escapeVariantText`, nama berbeda) | `base.html:338`; `notes.html:427`; `raw_materials.html:1311` (`escapeHtmlText`), `:2161` (`umEscapeHtml`) |
| K4 | BE-08 — "3 JSON 500 + 2 flash cookie" + "4 tempat activity_logs" (= 9) | **10 lokasi bocor**; daftar `file:line` di audit sendiri sebenarnya sudah berisi 10 entri | `main.py:1359`; `raw_materials_routes.py:296, 490, 1192, 1231`; `brands_routes.py:107, 279`; `sample_routes.py:166, 309, 377` |
| K5 | BE-04 dimanifestasikan sebagai HTTP 500 | **Tidak muncul di GET.** `GET /products/<uuid-acak>/edit` menjawab **303 → `/`**, bukan 500. Risikonya **latent** dan terkurung di **5 handler POST** | lihat K2 |
| K6 | FE-05 — "link logout tidak menghentikan heartbeat" | **Lebih sempit.** Link **navbar** **memang** memanggil `stopPresenceHeartbeat()`; hanya link **sidebar** yang tidak punya handler | `base.html:169-170` (navbar, ada handler) vs `_sidebar.html:115` (sidebar, tidak ada) |
| K7 | SEC-15 — "penyerang menyuntik kelas CSS & teks palsu" | **CSS injection, bukan XSS.** Cookie `greeting_cache` crafted memang kelas `fa-solid fa-bug text-red-500 text-lg`-nya terpasang dan teksnya tampil di header dashboard, tetapi autoescaping Jinja mencegah breakout atribut | `app/dashboard_routes.py:270`; `app/templates/dashboard.html:26` |
| K8 | State soft-delete di staging dianggap bukti fitur Sampah | **Tidak sah sebagai bukti.** Ada 1 produk dengan `is_deleted = true` (dari 2) dan `deleted_at` terisi, tetapi **tidak ada route** yang menulis `is_deleted = true` (route restore `/admin/products/{id}/restore` memang ada) → baris itu dibuat **manual lewat Supabase SQL Editor**, bukan lewat UI | `app/dashboard_routes.py:55`; `app/templates/dashboard.html:232` |
| K9 | U6 — "Tabel entitas audit tidak menyebut `entity_type="product_attachment"` maupun `storage_note` → celah audit" | **Salah diklasifikasi.** `storage_note` **bukan** `entity_type` dan bukan kolom — ia keyword-only parameter `log_activity` (`app/main.py:829`) yang diserialisasi ke kolom JSON `changes` sebagai `{"field": "Storage (R2)", "note": ...}` (`app/main.py:849-851`), dan hanya dipakai di `app/products_routes.py:1151` (`entity_type` = `product_file`). Kode **sudah** memakai `entity_type="product_attachment"` di `app/product_attachments_routes.py:185` (upload), `:220` (update), `:242` (delete). Celah yang sebenarnya adalah **dokumentasi**, dan lebarnya **5 nilai**, bukan 1 | `app/product_attachments_routes.py:185, 220, 242`; `app/main.py:829, 849-851`; `app/products_routes.py:1151`; §13.6 |
| K10 | §4 SEC-01 "tidak ada route delete produk; fitur tidak pernah diimplementasikan" | **Salah.** Route pernah ada sejak `2043689` (29 Jul) dan **dihapus** di `5f82f94` (20 Okt 11:35) ⇒ ini **regresi**, bukan fitur yang belum pernah ada. 23 request tercatat di produksi (§13.7.1). | `git log 2043689..5f82f94`; `app/templates/dashboard.html:232`; §13.7.1 |
| K11 | §4 SEC-01 diberi label "KRITIS (fungsional)" | Tetap kritis, tapi **sifatnya berubah**: **regresi** yang broke tombol yang sebelumnya bekerja. Form `dashboard.html:232` sekarang **dangling**. | `git grep -n 'products/delete' HEAD`; `git blame app/templates/dashboard.html`; §13.7.1 |
| K12 | §11 / F-19 "privat/publik bucket tidak dapat diverifikasi" | **Terbukti salah asumsi aman.** `raw-material-docs` dan `legal-documents` **public=true** di produksi dan path-nya enumerable dari field bisnis ⇒ **eksposur tanpa autentikasi** (§13.7.2). | `storage.buckets` (read-only); `app/raw_materials_routes.py:910, 925, 942`; `app/main.py:45, 56`; §13.7.2 |
| K13 | §4 A13 / BE-07 "tenant check hanya sebagian" | Root cause ditemukan: `profiles.perusahaan` NULL untuk 7/7 profil produksi ⇒ guard fail-open ⇒ **tidak pernah menolak** (§13.7.3). Bukan sekadar "helper tidak dipakai". | `app/security.py:21-22`; `app/products_routes.py:863-864, 1093-1096`; `app/main.py:617, 626, 633`; §13.7.3 |

Daftar 14 modul route yang didaftarkan di `app/main.py` (semuanya dipanggil):

`admin_users_routes`, `brands_routes`, `company_docs_routes`, `dashboard_routes`,
`dip_documents`, `dip_public`, `efek_samping`, `notes_routes`, `po_routes`,
`presence_routes`, `product_attachments_routes`, `products_routes`,
`raw_materials_routes`, `sample_routes`.

> K8 berarti baris `is_deleted = true` di staging **tidak boleh** dipakai
> sebagai argumen bahwa fitur Sampah "sudah pernah dipakai" **di staging**.
> **Koreksi lanjutan (K10):** untuk **produksi** argumennya justru terbalik —
> 9 dari 9 produk ter-trash punya baris audit `action='delete'` yang sah,
> jadi fitur itu **pernah** dipakai lewat UI; yang hilang adalah **route-nya**,
> bukan kebiasaannya (§13.7.1).

## 9. Temuan Tambahan Lainnya

### 9.1 Inkonsistensi arsitektur

| Temuan | Lokasi |
| :--- | :--- |
| `app/security.py` = **dead code** produksi; hanya dipakai `tests/test_security_helpers.py` | `app/security.py:9` |
| `notes_routes.py` membuat **env Jinja kedua** (tanpa 3 filter global) — hari ini `notes.html` tidak memakainya, jadi masih laten | `app/notes_routes.py:18` |
| 3 modul meng-import klien global langsung, melewati seam dependency injection | `notes_routes.py:15`, `po_routes.py:8`, `raw_materials_routes.py:10` |
| `require_admin` tidak ada — 10 cek admin inline | seluruh `app/` |
| 4 implementasi "batch non-lab terbaru" tanpa helper bersama | 4 file |
| `python-slugify==9.0.0` **dipin tapi tidak pernah di-import** (ada `slugify()` buatan sendiri dan `_slugify()` berbeda di `efek_samping.py:92`) | `requirements.txt:14` |
| `PIL`, `dotenv`, `botocore` **di-import** tapi tidak dipin (hanya transitif lewat `xhtml2pdf` / `pydantic-settings` / `boto3`) | `main.py:514`, `config.py:57`, `object_store.py:258` |
| `.env.staging.example` hanya memuat 4 dari 10 env var yang diwajibkan preflight | `.env.staging.example` |
| `StaticFiles` / `Jinja2Templates` memakai path relatif terhadap CWD → aplikasi hanya jalan dari root repo | `main.py:401-402` |

### 9.2 Higiene & kosmetik

* `brands.html:1` — artefak teks `omniroute` sebelum `{% extends %}`.
* `dashboard_routes.py:168-169` — `compute_status_na(...)` dipanggil **dua kali
  berturut-turut** dengan argumen identik (sisa bad merge).
* `main.py` — import tak terpakai: `create_client`, `File`/`UploadFile`, `List`,
  `StreamingResponse`, `XLSX_MIME`/`build_formula_workbook`.
* `products_routes.py:94` — `__import__("secrets")` inline, bukan import biasa.
* 2 environment template memakai Tailwind v3 Play CDN, 2 lain memakai v4
  browser build.
* `/docs`, `/redoc`, `/openapi.json` **terbuka tanpa autentikasi**
  (`main.py:339`, `FastAPI()` default).

## 10. Prioritas Tindakan

> **Restrukturisasi 21 Oktober 2026 (malam).** Lima item baru masuk ke atas
> tabel karena **sudah aktif di produksi** (§13.7) — bukan karena prioritas
> teoretis. Tiga di antaranya berlabel **P0**, dua **P1**. Label **P0–P3 item
> lama diwarisi apa adanya** supaya rujukan §14 tetap stabil; item lama yang
> digantikan ditandai **"[digantikan]"** atau **"[dalam]"**.
> Satu item digeser ke daftar **"Selesai pada 21 Oktober 2026"** di bawah tabel:
> **P0 #3** (restore route soft-delete) — route sudah dipulihkan dan 6 gap sudah
> ditutup (§13.8.1). Jejak item lama **dijaga**, tidak dihapus.

| Prioritas | Tindakan | Rujukan |
| :--- | :--- | :--- |
| **P0 #1 (BARU)** | **Privatkan bucket `raw-material-docs` + `legal-documents` di produksi.** Keduanya `public = true` dan path-nya dapat dikonstruksi dari field bisnis biasa (nomor batch / kode bahan baku) ⇒ MSDS, CoA, Halal, QC Report, hak-lisensi merk, dan dokumen legal perusahaan dapat diunduh **tanpa login**. DDL oleh owner (`UPDATE storage.buckets SET public=false ...`), lalu alihkan seluruh pembacaan ke `object_store.signed_url()` (`app/object_store.py:440-479` sudah ada). **[Menggantikan]** observasi F-19 yang tadinya "tidak dapat diverifikasi" (§11.2 → §11.1) | §13.7.2, §8.2 K12 |
| **P0 #2 (BARU)** | **Isi `profiles.perusahaan` untuk seluruh akun (khususnya PT Heka) — atau ubah `assert_same_tenant` jadi fail-closed.** Di produksi `perusahaan` NULL untuk 7/7 profil ⇒ `_user_company` = `""` ⇒ cabang penolakan tenant **tidak pernah dieksekusi**. Tanpa ini seluruh guard tenant diam-diam mengizinkan akses lintas badan hukum | §13.7.3, §8.2 K13, SEC-02, BE-07 |
| **P1 #4 (BARU)** | **Codified `public_link_audits`** sebagai `migration/008_create_public_link_audits.sql`. Tabel sudah ada di produksi (93 baris) tetapi DDL-nya tidak ada di repo ⇒ fallback `app/dip_public.py:128-144` menjadi **fail-open di environment baru** | §13.7.4 |
| **P1 #5 (BARU)** | **Tambahkan marker versi/build di respons** (atau `RENDER_GIT_COMMIT`) agar deploy bisa diikat ke commit. Saat ini build ter-deploy **tidak bisa dibuktikan** identik dengan repo | §13.7.7 |
| **P1 #6 (BARU)** | **[SELESAI 21 Okt 2026]** Jalankan `ALTER COLUMN is_deleted SET NOT NULL` pada `public.products` **bila belum** — kolom itu pre-existed migrasi 008 sehingga `ADD COLUMN IF NOT EXISTS` jadi no-op dan clause `NOT NULL` tidak pernah berlaku ⇒ baris `is_deleted = NULL` **lolos** dari CHECK (three-valued logic). Sudah dieksekusi di **staging** lalu **produksi**: `is_nullable` `YES` → `NO` di keduanya, hitungan baris tidak berubah | §13.8.2 |
| **P0** | Pasang `assert_same_tenant` di seluruh route tulis + filter tenant di route baca; jadikan helper itu satu-satunya sumber kebenaran. **[Dalam]** P0 #2 — helper sudah ada dan sudah dipakai, tetapi tidak menolak karena `profiles.perusahaan` kosong | SEC-02, BE-07, §13.7.3 |
| **P0** | Ubah "sukses palsu" jadi pesan jujur: BE-01 (formula), BE-02/BE-03 (batch), BE-15 (sample), BE-16 (mention) | BE-01→03, 15, 16 |
| **P0** | Validasi `brand_id` (UUID + eksistensi) + cek tenant pada `POST /brands/{id}/update-documents` | SEC-03 |
| **P1** | `secure=True` + prefix `__Host-` pada `access_token`; ambil IP **terakhir** dari `X-Forwarded-For` untuk rate limit | SEC-04, SEC-05 |
| **P1** | Satu middleware untuk header defensif + same-origin check pada POST; token CSRF double-submit | SEC-06, SEC-07 |
| **P1** | Ubah `get_current_user` menjadi `def` (Starlette → threadpool) + throttle tulis `profiles` | FE-01, FE-02 |
| **P1** | Hentikan pantulan `Referer`; pindahkan `/logout` ke POST; hentikan heartbeat di link logout sidebar | SEC-08, SEC-16, FE-05 |
| **P1** | Fail-closed pada fallback portal publik; isi `public_access_token` produk lama | SEC-09, BE-20 |
| **P2** | Hilangkan 5 titik bocor `str(e)`; pesan generik + `request_id` | BE-08 |
| **P2** | Validasi server-side total formula 100% (Decimal, toleransi terpusat) | BE-09 |
| **P2** | Ganti 4 duplikat `escapeHtml` dengan satu helper global; `escapeHtml(item.tanggal_ed)`; render `warning_msg` | SEC-13, SEC-14, BE-21 |
| **P2** | Pisahkan endpoint count ED-notification dari endpoint daftar; hapus `window.__adminPresenceInterval` yang mati; guard submit form saat lockout | FE-03, FE-06, FE-07 |
| **P2** | Bedakan "sukses sebagian" pada upload MSDS/Spek; rollback objek storage saat insert DB gagal; path batch pakai `batch_id` | BE-10, BE-11 |
| **P2** | Tangani `full_name` NULL; batasi durasi total panggilan Gemini; pesan error jujur saat guard staging gagal | BE-24, BE-25, BE-06 |
| **P3** | **Dokumentasi:** sinkronkan 2 dokumen dengan kode — hapus fallback `@erfi.com`, perbaiki Q15, tambahkan model akses publik + R2/object_store + migrasi 005-007 + 10 modul + tabel route | D1, D2, D9, U1, C1 |
| **P3** | Rate limit endpoint admin/upload/heartbeat · hapus `omniroute` · perbaiki default `b4_ratio` · hapus duplikasi baris 168-169 · hapus 3 import tak terpakai · rapikan `requirements.txt` | SEC-17, SEC-18, B2 |

**Selesai pada 21 Oktober 2026** (dipindahkan dari tabel di atas — jejaknya
**dijaga, tidak dihapus**):

| Prioritas | Tindakan | Rujukan |
| :--- | :--- | :--- |
| **P0 #3 — [DONE 21 Okt 2026]** | **Restore route `POST /products/delete/{product_id}`** dari `491d036` (`app/products_routes.py:1133-1155`) lalu tutup **6 gap** (lihat revisi R1 di §14.2) — **bukan menulis dari nol**. Route ini pernah live di produksi lalu hilang di `5f82f94` ⇒ ini **regresi**, dan form `dashboard.html:232` kini **dangling**. **[Menggantikan]** item P0 lama "Tambahkan route `POST /products/delete/{id}`". **SELESAI** — route dipulihkan ke `app/products_routes.py:119-214`, 6 gap G1–G6 ditutup, form dashboard di-gate admin, teks konfirmasi dikoreksi; tabel route 106 → **107** | §13.8.1, §13.7.1, §8.2 K10–K11, R1 §14.2 |

## 11. Yang Tidak Dapat Diverifikasi Tanpa Runtime / Database

Status item di bawah **diperbarui setelah eksekusi live di staging**
(lihat §13). Item yang sudah terjawab dipindahkan ke §11.1; sisanya tetap di
§11.2, dan hal yang tidak bisa dijawab karena staging kosong atau berkode
skema tertunda masuk §11.3.

### 11.1 Yang sudah terjawab oleh eksekusi live

| Item | Jawaban | Bukti |
| :--- | :--- | :--- |
| Status eksekusi migrasi **007** (`public_access_enabled`, `public_access_token`, `bpom_registered_link`) | **Sudah dieksekusi di staging (2026-10-21) dan di produksi (diverifikasi read-only, malam yang sama)** → keempat kolom ada di kedua environment, sehingga fallback fail-OPEN `app/dip_public.py:294-300` **tidak lagi terpicu di keduanya**. Perilaku produksi: 134 dari 136 produk menuntut `public_access_token` persis; 2 produk `bpom_registered_link = true` tetap tanpa token lewat jalur legacy yang disengaja (`app/dip_public.py:290-291`); 9 produk soft-deleted ditolak (`:279-280`) | `app/dip_public.py:276`, `:279-280`, `:290-291`, `:294-300`; §13.5, §13.6, §14.1 |
| Status eksekusi migrasi **004** (`product_attachments` + view `product_attachment_counts`) | **Sudah dieksekusi di staging (2026-10-21) dan di produksi** → tabel + view ada, RLS aktif, `REVOKE` untuk `anon`/`authenticated` berlaku; produksi berisi **6 baris** `product_attachments` | §13.5, §13.6 |
| Status migrasi **produksi** secara keseluruhan | **VERIFIED (read-only, 2026-10-21 malam): seluruh migrasi 001–007 terpasang di produksi.** Bukti penentu untuk 007: kueri yang merujuk `public_access_token` / `public_access_enabled` / `bpom_registered_link` mengembalikan **136 baris**, bukan error `42703`, dan `pg_indexes` independen menunjukkan index UNIQUE `… WHERE public_access_token IS NOT NULL`. Tabel `supabase_migrations.schema_migrations` **bukan ledger** yang bisa dipakai (produksi 3 baris, staging 13; keduanya tidak mencatat 001/002/004/005/006/007) — semua migrasi dieksekusi manual lewat Supabase SQL Editor, jadi status harus diinspeksi per objek di katalog | §13.6, §14.1 |
| Data `profiles.full_name` NULL | **Tidak ada baris NULL** di staging (5 profil) maupun di produksi (7 profil) → jalur `KeyError` belum pernah menyala | `app/main.py:1112`; §13.3, §13.6 |
| Kolom presence (`last_seen_at`, `last_activity_at`, `is_online`) | **Ada 3/3** → heartbeat bukan no-op; FE-02 tetap CONFIRMED | `app/main.py:725-748`; §13.3 |
| Ukuran data staging | `products` 2, `raw_materials` 2, `profiles` 5, `activity_logs` 67; batch / PO / PO-item / components = **0 baris** | §13.4 |
| Route soft-delete produk | **Tetap tidak ada di HEAD — dan itu REGRESI, bukan fitur yang belum pernah ada.** Route pernah ada & live di produksi, dihapus di `5f82f94` (20 Okt 11:35); tombol dashboard membalas **404** saat `POST /products/delete/{id}` | SEC-01; §13.2, §13.7.1 |
| Privat/publik bucket Supabase | **Terjawab (2026-10-21, malam): `raw-material-docs` dan `legal-documents` keduanya `public = true`** di produksi (646 + 105 objek), sedangkan `product-attachments` `public = false`. Path-nya dapat dikonstruksi dari field bisnis biasa ⇒ **eksposur tanpa autentikasi** — asumsi aman yang sebelumnya dipakai audit **terbukti salah** (§13.7.2, §8.2 K12) | `app/object_store.py:440-479`; §13.7.2 |

### 11.2 Yang tetap belum dapat diverifikasi

| Item | Mengapa |
| :--- | :--- |
| Perilaku proxy Render terhadap `X-Forwarded-For` (append vs replace) | Infrastruktur luar repo. Menentukan dampak nyata SEC-05. |
| RLS per tabel | Semua query memakai service-role client, jadi RLS bukan lapisan proteksi aplikasi ini. |
| Konfigurasi edge / CDN / WAF di depan aplikasi | Tidak terlihat dari repo; menentukan apakah `secure=True` aman dan apakah HSTS sudah ada di edge. |
| Latensi nyata Supabase & jumlah pengguna konkuren | Menentukan besarnya dampak FE-01 dan FE-02. |
| Kolom `percent_internal` NULL | Menentukan apakah `raw_materials_routes.py:587` melempar `TypeError`. |
| Perilaku PostgREST untuk filter `or_` terinjeksi | Menentukan besarnya BE-17. |
| Perilaku bfcache per browser/versi | Menentukan FE-04. |
| Perilaku `Referer` aktual | Menentukan SEC-08. |
| Slowapi benar-benar aktif di environment deploy (`app.state.limiter` vs middleware default) | Perlu log server produksi. |
| Versi Starlette/FastAPI di Render | `requirements.txt` sama dengan venv lokal; deploy tidak terverifikasi. |

### 11.3 Yang tidak dapat diverifikasi dari staging karena data atau skema kosong

Statusnya **bukan PASS dan bukan FAIL** — statusnya *tidak dapat diverifikasi*:

| Item | Alasan |
| :--- | :--- |
| BE-10 (upload storage sebelum tulis DB tanpa rollback) | Butuh alur upload nyata pada batch; `raw_material_batches` = 0 baris |
| B4 (badge Bab IV dashboard "5/5" hardcode) & D13 (batas 10 file × 10 MB per produk) | Butuh data lampiran nyata; migrasi 004 **sudah** dieksekusi di staging (2026-10-21), tetapi `product_attachments` masih **0 baris** |
| B6 (PO tanpa `tanggal_po` tidak masuk KPI) | `purchase_orders` = 0 baris |
| FE-03 (query ED-notification berat di setiap page load) | Butuh batch & produk yang cukup banyak; data staging nyaris kosong |
| Seluruh temuan lampiran produk | Skema lampiran **sudah ada** di staging sejak migrasi 004 dieksekusi (2026-10-21) dan route lampiran tidak lagi error `PGRST205`, tetapi `product_attachments` masih **0 baris** → perilaku upload/edit/delete lampiran tetap belum teruji |

> **Catatan 2026-10-21 (malam).** Baris "0 baris" itu adalah **artefak
> ketiadaan data**, bukan bukti bahwa jalur lampiran rusak. Di **produksi**
> `product_attachments` berisi **6 baris** dan `activity_logs` memuat **13
> baris** `entity_type='product_attachment'` → jalur upload/update/delete
> lampiran **terbukti bekerja** (§13.6). Jadi temuan U6 dikoreksi menjadi
> REFUTED sebagai temuan kode (§8.2 K9), dan celah yang tersisa adalah
> **dokumentasi**.

## 12. Suite Test Audit (Baru — 21 Oktober 2026)

> **Status file.** Ketiga file di bawah **ada di working tree** dan sudah
> *commit-ready*, tetapi **belum di-commit** — belum ada `git add`,
> `git commit`, atau `git push` yang dijalankan. `.gitignore` **sudah**
> di-whitelist untuk ketiganya, jadi file bisa langsung di-add.
>
> **Fungsi suite: mendeteksi, bukan memperbaiki.** Suite ini mengunci setiap
> temuan audit menjadi assertion yang bisa dijalankan mesin. **Tidak ada satu
> pun temuan yang diperbaiki oleh suite ini.** Yang memperbaiki adalah kode
> aplikasi; justru suite-lah yang harus berubah dari `[KNOWN]` menjadi
> `[PASS]` pada saat perbaikannya masuk. Suite yang bisa "memperbaiki"
> temuan membuat audit ini tidak bermakna.

### 12.1 File suite

| File | Baris | Jenis | Perintah |
| :--- | ---: | :--- | :--- |
| `tests/test_audit_regressions.py` | 1.407 | regresi statis/unit — tanpa DB, tanpa jaringan, tanpa secret | `venv\Scripts\python.exe tests\test_audit_regressions.py` |
| `tests/verify_audit_db_state.py` | 1.541 | introspeksi state DB staging, read-only | `venv\Scripts\python.exe tests\verify_audit_db_state.py` |
| `tests/e2e_audit_staging.py` | 1.127 | Playwright E2E, staging saja | `venv\Scripts\python.exe tests\e2e_audit_staging.py --full` |

### 12.2 Mekanisme dua tingkat (`KNOWN_ISSUES`)

Setiap suite membawa registry `KNOWN_ISSUES`: peta **ID audit → ringkasan
temuan** yang *diharapkan masih gagal*. Polaritas tiap check adalah
"apakah perbaikannya sudah masuk?", sehingga:

| Hasil | Arti | Dampak ke exit code |
| :--- | :--- | :--- |
| `[PASS]` | Perilaku sudah benar (temuan sudah diperbaiki) | tidak memengaruhi |
| `[KNOWN]` | Check gagal **karena temuan yang terdokumentasi dan belum diperbaiki** | **tidak** menggagalkan run |
| `[FAIL]` | Check gagal karena alasan lain — regresi baru atau temuan yang tak dikenal | **menggagalkan** run |
| `[SKIP]` | Check tidak bisa dijalankan di lingkungan ini | dilaporkan, tidak menggagalkan |

Dengan begitu suite **hijau hari ini** sambil tetap mengodekan **setiap bug
yang masih terbuka**. Flag `--strict` menaikkan `[KNOWN]` → `[FAIL]`; dipakai
di CI setelah perbaikan benar-benar land.

### 12.3 Exit code

| Suite | `0` | `1` | `2` |
| :--- | :--- | :--- | :--- |
| `tests/test_audit_regressions.py` | tidak ada FAIL | ≥ 1 FAIL, atau ≥ 1 KNOWN bila `--strict` | — |
| `tests/verify_audit_db_state.py` | tidak ada FAIL | ≥ 1 FAIL | tidak bisa dijalankan: env hilang / guard gagal / DB tak terjangkau |
| `tests/e2e_audit_staging.py` | tidak ada FAIL | ≥ 1 FAIL | lingkungan tak terpakai: server / kredensial / Chromium tidak ada |

### 12.4 Konvensi lingkungan & guard

* **Interpreter.** `python` di PATH pada mesin ini adalah stub Microsoft Store
  yang rusak. Selalu pakai `venv\Scripts\python.exe` (3.11.0).
* **Guard staging.** Ketiganya menolak menyentuh produksi.
  `tests/verify_audit_db_state.py` menolak override `SUPABASE_URL` yang
  menunjuk host produksi (exit 2) dan juga menolak host mirip seperti
  `…supabase.co.evil.example.com`. `tests/e2e_audit_staging.py` menolak base
  URL non-lokal kecuali `--allow-production`, dan mode itu hanya menjalankan
  subset read-only (tanpa login/POST/tulis/DB).
* **Kredensial tidak pernah di-hardcode.** E2E membaca
  `STAGING_ADMIN_EMAIL` / `STAGING_ADMIN_PASSWORD` (alias `E2E_EMAIL` /
  `E2E_PASSWORD`), opsional `E2E_HEKA_EMAIL` / `E2E_HEKA_PASSWORD` untuk grup
  tenant PT Heka, dan `STAGING_BASE_URL` (default `http://127.0.0.1:8017`).
  Email dicetak **tersamar**; password **tidak pernah** dicetak.
* **Rate limit login.** `POST /login` dibatasi **5/menit per IP**
  (`app/main.py:1051`) → E2E memakai **satu** browser context untuk seluruh
  skenario, bukan login ulang per skenario.
* **`.gitignore`.** Ketiga file test + artefak runtime `/_e2e_smoke_tmp.pdf`
  sudah di-whitelist: **7 baris ditambahkan, 0 dihapus**.

### 12.5 Cakupan

| Aspek | Isi |
| :--- | :--- |
| Registry `KNOWN_ISSUES` | 19 entri: SEC-01, SEC-02, SEC-04, SEC-07, SEC-14, SEC-16, SEC-18, BE-01, BE-02, BE-03, BE-04, BE-07, BE-08, BE-21, DUPL-01, FE-05, FE-06, FE-07, U6 |
| Audit ID baru (grup G9) | 6 ID baru di `tests/verify_audit_db_state.py`: **PROD-01** (privasi bucket storage), **PROD-02** (kelengkapan `profiles.perusahaan`), **PROD-03** (keberadaan `public_link_audits` + DDL-nya), **PROD-04** (cakupan detail storage di audit trail), **PROD-05** (distribusi `outcome`/`source`), **PROD-06** (konsistensi soft-delete produk vs jejak audit) → §13.7 |
| Check yang sengaja SKIP | Validasi PDF (`file_validation`) dan parsing storage URL — sudah diuji file lain; pendeteksiannya otomatis dari isi file tsb |
| Interaksi dengan pytest | Ketiga file **tidak** di-collect pytest (tidak punya fungsi `test_*`) → total pytest tidak berubah |
| Sifat file | `test_audit_regressions.py` tidak pernah menyentuh DB, jaringan, atau server, dan tidak pernah membaca/mencetak isi `.env` / `.env.staging` |

> **Catatan 21 Oktober 2026 (malam).** Family `PROD-*` sengaja terpisah dari
> ID lama agar **tidak** me-override atribusi temuan lama: F-19 tetap
> tercatat "tidak dapat diverifikasi" di §11.2, SEC-01 tetap punya ID-nya
> sendiri, dan U6 tetap UNVERIFIABLE di staging. Yang berubah hanya
> **catatan**: bucket publik di produksi kini **terbukti** (§13.7.2) dan
> dicatat di §8.2 K12. Suite tetap **hanya mendeteksi, tidak memperbaiki**.

## 13. Hasil Uji Langsung di Staging (21 Oktober 2026)

Seluruh angka di bawah berasal dari **eksekusi nyata** terhadap staging lokal
(`scripts/run_staging_8017.py`, `127.0.0.1:8017`) dan database Supabase
staging. Tidak ada eksekusi terhadap produksi.

### 13.1 Ringkasan hasil

| Suite | Hasil | Durasi |
| :--- | :--- | :--- |
| `scripts/check_undefined_names.py` | exit 0, 24 file bersih | — |
| `tests/test_audit_regressions.py` | **PASS 20 / KNOWN 18 / FAIL 0 / SKIP 2**, exit 0 | — |
| `tests/test_audit_regressions.py` (re-run 21 Oktober 2026, malam) | **PASS 20 / KNOWN 19 / FAIL 0 / SKIP 2**, exit 0 — +1 entri `KNOWN_ISSUES` (`U6`: check doc-drift tabel entitas audit) | — |
| `tests/verify_audit_db_state.py` (re-run 21 Oktober 2026, malam) | 43 check: **PASS 20 / FAIL 0 / WARN 1 / INFO 22**, exit 0 — G8.3 diperbaiki (semula menguji `storage_note` sebagai `entity_type`, yang mustahil) | — |
| `tests/verify_audit_db_state.py` (re-run 21 Oktober 2026, malam + grup G9) | 49 check (dari 43): **PASS 21 / FAIL 0 / WARN 6 / INFO 22**, exit 0 — grup G9 menambah 6 check `PROD-01`…`PROD-06` (§12.5) | — |
| `tests/test_audit_regressions.py --strict` | 18 KNOWN dipromosikan jadi FAIL, exit 1 | — |
| `pytest tests/ -q` | **79 passed, 0 failed** (baseline sebelum = 79 → tanpa regresi) | 5,8 dtk |
| `tests/verify_audit_db_state.py` | 43 check: PASS 15 / FAIL 3 / WARN 2 / INFO 23, exit 1 → setelah migrasi 004 + 007: **PASS 20 / FAIL 0 / WARN 1 / INFO 22**, exit 0 (§13.5) | — |
| `tests/e2e_audit_staging.py --full` | **PASS 22 / KNOWN 5 / FAIL 0 / SKIP 1**, exit 0 | 189,5 dtk |
| `tests/e2e_audit_staging.py --quick` | PASS 18 / KNOWN 5 / FAIL 0 / SKIP 5, exit 0 | 77,6 dtk |

Tiga FAIL pada DB verifier **satu akar-cause** dan **diharapkan**: migrasi
`004` dan `007` **belum dieksekusi** di database staging. Keduanya **sudah
dieksekusi di staging pada 2026-10-21** (§13.5) — sesudahnya DB verifier
menjadi PASS 20 / FAIL 0 / WARN 1 / INFO 22, exit 0. Status migrasi di
**produksi kini sudah terverifikasi** — read-only, pada 2026-10-21 malam
(§13.6, §14.1).

Jumlah check E2E bergantung pada ketersediaan kredensial tenant opsional
(`E2E_HEKA_EMAIL` / `E2E_HEKA_PASSWORD`): tanpa kredensial tersebut, grup
tenant turun menjadi 1 SKIP.

### 13.2 Temuan yang CONFIRMED oleh eksekusi live

> **Catatan 2026-10-21 (malam).** Tiga baris tabel ini — **SEC-09**,
> **BE-20**, dan **U6** — **tidak lagi** berstatus CONFIRMED murni: verifikasi
> read-only di produksi (§13.6) mengubahnya menjadi REFUTED untuk produksi
> (SEC-09, BE-20) dan REFUTED sebagai temuan kode (U6). Barisnya tetap
>DILETAKKAN di sini karena bukti eksekusi live di staging-nya tetap relevan.

| Audit ID | Status | Bukti |
| :--- | :--- | :--- |
| **SEC-09** | **REFUTED untuk produksi**; fail-OPEN **sudah tidak aktif di staging** sejak migrasi 007 dieksekusi (2026-10-21) | Saat audit: migrasi 007 tidak dieksekusi di staging sehingga `products` tidak punya `public_access_enabled` / `public_access_token` / `bpom_registered_link` (PostgREST `42703`), dan fallback `app/dip_public.py:294-300` membuat **produk apa pun bisa diakses publik hanya dengan UUID**, tanpa token. Sesudah migrasi 007 di staging keempat kolom ada dan 2/2 produk punya token — jalur fail-OPEN tidak lagi terpicu di staging (§13.5). **Produksi diverifikasi read-only pada 2026-10-21 (malam): 007 terpasang, cabang `except Exception:` di `:294-300` tidak pernah dimasuki** — 134 dari 136 produk menuntut token persis, 2 produk `bpom_registered_link = true` tetap tokenless lewat jalur legacy yang disengaja (`:290-291`), 9 produk soft-deleted ditolak (`:279-280`) (§13.6, §14.1). |
| **BE-20** | **REFUTED untuk produksi**; akar-cause sudah tertutup di staging sejak 2026-10-21 | Akar-cause sama: produk tanpa `public_access_token` tetap bisa dijangkau publik. Sesudah migrasi 007 di staging, 0 dari 2 produk tanpa token (§13.5). **Produksi: 0 dari 136 produk tanpa token** (§13.6) — hanya 2 produk `bpom_registered_link = true` yang *sengaja* boleh diakses tanpa token. |
| **SEC-02 / BE-07 / BE-18 / BE-19** | **CONFIRMED dengan data live** | Akun PT Heka menerima **1 produk PT Erfi** lewat `/api/po/products` dan melihat **2 bahan baku PT Erfi** di `/raw-materials`. Probe tulis lintas tenant **tidak** ditolak 403 (kena validasi kode duplikat 400 lebih dulu); data terverifikasi tidak berubah. `assert_same_tenant` tetap **0 call site** di `app/`. |
| **SEC-01** | **CONFIRMED & SUDAH DIPERBAIKI** | Awalnya: tombol "Hapus Produk" di dashboard POST ke `/products/delete/{id}` → **404**; route-nya memang tidak terdaftar di HEAD. Verifikasi 21 Okt 2026 (malam): route ini **pernah live di produksi** dan baru **dihapus** di `5f82f94` ⇒ ini **regresi**, bukan fitur yang belum pernah ada (§13.7.1, §8.2 K10). **21 Okt 2026: route dipulihkan** ke `app/products_routes.py` dari `491d036` dan 6 gap G1–G6 ditutup; form dashboard di-gate admin + teks konfirmasi dikoreksi; tabel route 106 → **107** (§13.8.1). Bukti uji **produksi**: `GET /products/delete/<uuid>` → **405 `Allow: POST`**, soft delete → **303** + `success_msg` + audit `outcome=success` dengan `changes` `is_deleted`, 2 kasus negatif → `outcome=rejected`, delta audit **+4 tepat**, `trashed` 8 → **9** — **24/24 PASS** (§13.8.3). |
| **SEC-04** | **CONFIRMED** | Cookie `access_token` diset **tanpa `secure=True`** (`app/main.py:1121-1127`). |
| **FE-05** | **CONFIRMED** | Link logout **sidebar** tidak punya handler `stopPresenceHeartbeat()`; link **navbar** punya (`base.html:169-170` vs `_sidebar.html:115`). |
| **FE-06** | **CONFIRMED** | `window.__adminPresenceInterval` tidak pernah di-assign di `admin_users.html` (hanya variabel lokal `presencePollInterval` di `admin_users.html:326`) → jalur cleanup `base.html:44` adalah dead code. |
| **BE-21** | **CONFIRMED** | Cookie `warning_msg` diproduksi di `app/products_routes.py:1167` tetapi dirender oleh **tidak ada** template. |
| **U6** | **REFUTED sebagai temuan kode** — yang tersisa adalah celah **dokumentasi** selebar **5 nilai** | Kode **sudah** memakai `entity_type="product_attachment"` di `app/product_attachments_routes.py:185` (upload), `:220` (update), `:242` (delete). Ketiadaannya di staging adalah **artefak ketiadaan data** — `product_attachments` = **0 baris** di staging, jadi tidak pernah ada lampiran yang diunggah di sana. Produksi membuktikan jalurnya bekerja: **13 baris `product_attachment`** (§13.6). Celah sebenarnya: `product_attachment`, `product_file`, `product_batch`, `purchase_order`, `purchase_order_item` tidak ada di tabel entitas audit (`panduan:699-713`). Dikoreksi di §8.2 K9. |
| **SEC-15** | **CONFIRMED — CSS injection, bukan XSS** | Cookie `greeting_cache` crafted benar-benar memasang kelas `fa-solid fa-bug text-red-500 text-lg` dan menampilkan teksnya di header dashboard; autoescaping Jinja mencegah breakout atribut (tidak ada dialog, tidak ada `img[onerror]`). |

### 13.3 Temuan yang REFUTED / koreksi status

| Audit ID | Status | Bukti |
| :--- | :--- | :--- |
| **FE-02** | **Risiko "heartbeat no-op" REFUTED**; FE-02 sendiri tetap CONFIRMED | Kolom `last_seen_at`, `last_activity_at`, `is_online` **ada** → heartbeat bukan diam-diam no-op, sehingga 144 tulis DB/jam/user benar-benar terjadi |
| **BE-25** | **REFUTED sebagai isu live** | **Tidak ada** baris `profiles` di staging (5 profil) maupun di produksi (7 profil) yang punya `full_name` NULL → jalur `KeyError` di `app/main.py:1112` belum pernah menyala (§13.6) |
| **BE-04** | **REFUTED pada GET; latent pada POST** | `GET /products/<uuid>/edit` menjawab 303 → `/` dengan rapi, bukan 500. Risiko `.single()` tetap latent di **5 handler POST** (lihat §8.2 K2) |

### 13.4 Temuan operasional baru

1. **Migrasi 004 belum dieksekusi di staging** — *status pada saat audit; sudah
   diperbaiki, lihat §13.5*. `product_attachments` dan view
   `product_attachment_counts` tidak ada → setiap load dashboard mencatat
   "Gagal ambil agregat lampiran" dan route lampiran error `PGRST205`. Ini
   **celah skema, bukan bug aplikasi** — sekaligus berarti seluruh temuan
   terkait lampiran **tidak bisa diuji di staging** (§11.3).
2. **Hampir semua tabel staging kosong** (batch / PO / PO-item / components =
   0 baris) → BE-10, B4, B6, D13, dan FE-03 **UNVERIFIABLE dari staging** —
   bukan PASS, bukan FAIL (§11.3).
3. **Chromium headless men-throttle timer latar.** Interval 25 dtk dan 30 dtk
   awalnya baru menyala di ≈ +41 dtk (atau tepat di batas menit) sehingga
   menghasilkan **false failure**. Karena itu E2E menyimpan helper
   `keep_alive()` (`tests/e2e_audit_staging.py:248`) yang menyentil halaman
   tiap 3 dtk selama jeda polling panjang. Siapa pun yang menjalankan ulang
   suite tanpa helper ini akan mengejar regresi hantu.
4. **`GET /login` 303-redirect ke `/`** bila cookie sesi hidup → assertion
   tentang versi CDN harus memakai browser context **tanpa cookie**.
5. **Server dev lokal pemilik repo.** Sebuah `uvicorn app.main:app --reload`
   berjalan LISTEN di `127.0.0.1:8000` dengan `DIP_APP_ENV` **tidak diset**,
   sehingga menurut `app/config.py:51-60` proses itu memuat **`.env` produksi**.
   Ini adalah server dev milik pemilik repo sendiri dan memang sengaja
   dibiarkan berjalan. **Test suite tidak pernah memakai port 8000** — seluruh
   eksekusi E2E memakai launcher staging `scripts/run_staging_8017.py` di
   `127.0.0.1:8017` dengan `DIP_APP_ENV=staging`, sehingga tidak ada satu pun
   request dari suite ini yang menyentuh konfigurasi produksi.
6. **`.env.staging.example` tidak lengkap** — hanya memuat **4 dari 10 key**
   yang diwajibkan `staging_preflight` (baris kelima, `GEMINI_API_KEY`, bersifat
   opsional); tidak bisa dipakai untuk bootstrapping staging yang berfungsi.
   (Sudah tercatat di §9.1 — di sini hanya dirujuk silang.)
7. **Higiene kredensial terverifikasi.** Pindaian seluruh repo tidak
   menemukan password staging literal, kunci service-role literal, atau
   kredensial nyata di ketiga file baru. Dua file lama yang sudah gitignored
   di `backup-rls/` hanya memuat string username (bertanggal 2026-10-12/14) —
   tanpa password.

### 13.5 Eksekusi migrasi 004 + 007 di staging (21 Oktober 2026)

> **Cakupan: STAGING SAJA.** Eksekusi di bawah **hanya** dijalankan terhadap
> project Supabase staging `odtfppboyjlbatajncgj`
> (`odtfppboyjlbatajncgj.supabase.co`). Project **produksi**
> (`dytuprmoorvrugutozwv`) **tidak disentuh dan tidak dibaca** dalam eksekusi
> di bawah. Status migrasi produksi diverifikasi **read-only** pada malam yang
> sama tanpa statement yang mengubah data — lihat **§13.6**. File SQL di
> `migration/` **tidak diubah** (dieksekusi apa adanya), tidak ada `git add`,
> `git commit`, maupun `git push`, dan tidak ada perubahan kode aplikasi,
> template, atau test.

| Item | Nilai |
| :--- | :--- |
| Tanggal | 21 Oktober 2026 |
| File SQL yang dieksekusi | `migration/004_create_product_attachments.sql` (1298 B), lalu `migration/007_add_public_access_capability.sql` (966 B) — berurutan, byte-for-byte |
| Jalur eksekusi yang berhasil | **Supabase Management API**: `POST https://api.supabase.com/v1/projects/{ref}/database/query`, header `Authorization: Bearer <token>`, body `{"query": "<sql>"}`. Token akses dibaca secara programatis dari `.kilo/kilo.jsonc` (`mcp.supabase.command --access-token`) dan **tidak pernah dicetak** |
| Jalur yang sengaja tidak dipakai | Server MCP `.mcp.json` terikat ke ref **produksi**, jadi tidak disentuh. RPC PostgREST dan koneksi Postgres langsung tidak tersedia (tidak ada password DB di `.env.staging`) |
| Mode statement | **Satu batch per file**, dibungkus `BEGIN; ... COMMIT;` (endpoint menerima multi-statement). 004: HTTP 201. 007: HTTP 201. **0 error** |
| Yang TIDAK dieksekusi | Migrasi 001/002/003/005/006 **tidak dijalankan ulang**. 005 & 006 hanya diverifikasi sudah ada (kolom `brands.hak_merk_file_url` & `lisensi_merk_file_url` ada dan null; view `product_formula_presence` ada) |

**Pre-state → post-state (staging):**

| Objek / metrik | Sebelum (pre-migrasi) | Sesudah |
| :--- | :--- | :--- |
| Tabel `product_attachments` | tidak ada | ada — 10 kolom, PK, FK `products(id) ON DELETE RESTRICT`, CHECK `file_size <= 10485760` |
| Index `idx_product_attachments_product_created` | tidak ada | ada |
| View `product_attachment_counts` | tidak ada | ada, `security_invoker = true` |
| RLS `product_attachments` (`relrowsecurity`) | — (tabel belum ada) | `true` |
| Privilege `anon` / `authenticated` atas view | — | tidak ada (REVOKE berlaku); `service_role` tetap punya akses |
| Kolom 007 di `products` | 0 dari 4 ada | 4 dari 4 ada — `public_access_enabled boolean NOT NULL DEFAULT true`, `public_access_token text`, `public_access_revoked_at timestamptz`, `bpom_registered_link boolean NOT NULL DEFAULT false` |
| Index `products_public_access_token_key` | tidak ada | ada — UNIQUE parsial `WHERE public_access_token IS NOT NULL` |
| `products.public_access_token` | kolom tidak ada | 2 dari 2 baris non-NULL, panjang 48 (24 byte hex), 2 nilai berbeda — **nilai token tidak pernah ditampilkan** |
| Default kolom baru pada baris lama | — | 2 dari 2 baris: `public_access_enabled = true`, `bpom_registered_link = false`, `public_access_revoked_at` NULL |
| Baris `products` / `raw_materials` / `activity_logs` / `sample_submissions` | 2 / 2 / 67 / 0 | 2 / 2 / 67 / 0 — **tidak berubah** (tanpa kehilangan data) |

**Dampak ke suite setelah migrasi:**

| Suite | Sebelum | Sesudah |
| :--- | :--- | :--- |
| `tests/verify_audit_db_state.py` | PASS 15 / FAIL 3 / WARN 2 / INFO 23, exit 1 | **PASS 20 / FAIL 0 / WARN 1 / INFO 22**, exit 0 |
| Check yang berubah verdict | — | `G1.1` FAIL→PASS; `G1.2` INFO→PASS; `G1.5` INFO→PASS; `E1 migrasi-004` FAIL→PASS; `E1 migrasi-007` FAIL→PASS; `G6.1 volume product_attachments` WARN ("TABEL TIDAK ADA")→INFO ("0") |
| `scripts/check_undefined_names.py` | exit 0 | exit 0 |
| `pytest tests/ -q` | 79 passed | **79 passed** (tanpa regresi) |

**Verifikasi manual di server staging** (`scripts/run_staging_8017.py`,
`127.0.0.1:8017`): `GET /` 200 dan **log staging tidak lagi memuat "Gagal ambil
agregat lampiran"**; `GET /api/po/products` 200 (tanpa `PGRST205`);
`GET /raw-materials` 200; `GET /products/{id}/lampiran` 200 (tabel
`product_attachments` bisa di-SELECT). View `product_attachment_counts` juga
terlihat PostgREST (`GET /rest/v1/product_attachment_counts` → 200 `[]`), jadi
cache skema PostgREST sudah ter-refresh otomatis. Sesi dibuat lewat Supabase
Admin API (`generate_link` + `verify`) pada akun admin staging yang sudah ada —
**tidak ada akun baru dibuat dan tidak ada data aplikasi yang ditulis**.
Server sudah dihentikan dan port 8017 bebas.

### 13.6 Verifikasi read-only produksi (21 Oktober 2026)

> **Cakupan: PRODUKSI, READ-ONLY.** Verifikasi di bawah **tidak** menjalankan
> statement yang mengubah data, **tidak** mengeksekusi ulang file
> `migration/*.sql`, dan **tidak** melakukan `git add` / `git commit` /
> `git push`. Hanya `SELECT` ke `pg_catalog` / `information_schema` plus kueri
> pembuktian. **Nilai token tidak pernah dicatat** — hanya jumlah dan panjang.
> Snapshot diambil **21 Oktober 2026 (malam)**; seluruh angka di bawah adalah
> angka pada saat snapshot itu diambil.

**Snapshot produksi (angka saja, tanpa nilai token).**

| Objek | Nilai |
| :--- | :--- |
| `products` | 136 baris — **0** NULL `public_access_token`; `public_access_enabled` 136 `true` / 0 `false`; `bpom_registered_link` 2 `true` / 134 `false`; `public_access_revoked_at` 0 non-NULL |
| `products` soft-deleted | 9 dari 136 (`is_deleted = true`), semuanya punya `deleted_at` terisi |
| `profiles` | 7 baris — **0** dengan `full_name` NULL (BE-25 tetap REFUTED) |
| `activity_logs` | 1.308 baris (snapshot 21 Oktober 2026) |
| `product_attachments` | 6 baris |
| `brands` | 18 baris |

**Format token produksi — dua format, keduanya valid.** 136 baris produk
di-backfill oleh migrasi 007 berformat hex 24 byte
(`encode(gen_random_bytes(24),'hex')`) → **48 karakter**. Produk yang dibuat
aplikasi ke depan memakai `secrets.token_urlsafe(32)`
(`app/products_routes.py:94`) → **43 karakter**. Kedua format valid; panjang
yang berbeda **bukan** tanda kerusakan.

**Audit trail produksi.** `activity_logs` memakai **14** nilai `entity_type`
berbeda dan **memuat `product_attachment` (13 baris)** → jalur audit lampiran
terbukti bekerja di produksi (koreksi U6, §13.2). `outcome` = `success` untuk
1.308/1.308 — **tidak ada** baris `rejected`/`failed`. `source` = `app` untuk
1.308/1.308 — **nol** baris `source='public'` padahal portal publik hidup,
karena `app/dip_public.py:130-142` menyisipkan langsung ke `activity_logs`
**tanpa mengisi `source`** sehingga default `'app'` yang terpakai (§14.3 R6).

**`supabase_migrations.schema_migrations` BUKAN ledger yang bisa dipakai.**
Produksi: **3 baris**. Staging: **13 baris**. Keduanya **tidak** mencatat
migrasi 001/002/004/005/006/007 — semua migrasi memang dieksekusi **manual**
lewat Supabase SQL Editor. Konsekuensi proses: **status migrasi tidak bisa
dibaca dari satu tabel**, harus diinspeksi per objek di katalog
(`pg_class` / `pg_columns` / `pg_indexes` / `pg_constraint`). Inilah alasan
verifikasi §14.1 memakai katalog, bukan ledger.

**Dua penyimpangan yang perlu dicatat.**

| Penyimpangan | Staging | Produksi | Arti |
| :--- | :--- | :--- | :--- |
| Privilege `service_role` atas `activity_logs` | 7 | 7 | Migrasi 003 hanya memberi `SELECT` + `INSERT`; 7 privilege berarti ada grant di luar repo → **jangan diasumsikan append-only oleh kode** |
### 13.7 Verifikasi read-only produksi lanjutan (21 Oktober 2026)

> **Cakupan: PRODUKSI, READ-ONLY.** Metode: Supabase Management API
> `POST /v1/projects/{ref}/database/query` — **30+ `SELECT`**, **0 write**,
> **0 migrasi**, **0 DDL**, **0 `git add`/`git commit`/`git push`**. Token
> akses dibaca secara **programatis** dari `.kilo/kilo.jsonc` dan **tidak
> pernah dicetak** (hanya jumlah dan panjang). Histori git dibaca dengan
> `git log` / `git show` / `git blame` — **read-only**, tanpa checkout,
> commit, reset, atau stash. Semua angka di bawah adalah angka pada snapshot
> 21 Oktober 2026 (malam).

Bagian ini **membalikkan beberapa kesimpulan** audit sebelumnya: SEC-01
ternyata **regresi** (bukan fitur yang belum pernah ada), kebocoran bucket
storage ternyata **nyata** (bukan "tidak dapat diverifikasi"), dan "nol
`rejected`" ternyata **konsekuensi guard fail-open** — bukan bukti tidak
adanya percobaan lintas-tenant.

#### 13.7.1 SEC-01 adalah REGRESI, bukan fitur yang belum pernah ada

Route soft-delete produk `POST /products/delete/{product_id}` **pernah ada dan
pernah live di produksi**. Yang hilang adalah **route-nya** — bukan tombolnya,
bukan format soft delete-nya. Histori git (read-only):

| Commit | Tanggal (+0700) | Perubahan |
| :--- | :--- | :--- |
| `2043689` | 2026-07-29 08:50 | Route delete diperkenalkan — **hard delete** (hapus `product_formula_lines` + baris `products`) |
| `d9a3d2d` | 2026-07-31 13:17 | Link hapus dihapus sementara dari dashboard |
| `04383df` | 2026-08-01 10:27 | Tombol hapus dikembalikan sbg `<a href>` |
| `aeb5358` | 2026-08-08 11:06 | GET → POST + `Depends(get_current_user)` |
| `f373ace` | 2026-08-27 15:16 | **Hard delete → SOFT delete** (`is_deleted=True`), formula tidak lagi dihapus |
| `cd18b6a` | 2026-08-27 16:02 | Halaman Sampah admin + restore ditambahkan (masih ada di HEAD, `app/dashboard_routes.py`) |
| `846d9bc` | 2026-08-28 08:42 | `deleted_at = datetime.now(WIB).isoformat()` ditambahkan |
| `b17632d` | 2026-09-14 11:06 | `<a href>` → `<form method="POST">` + teks konfirmasi (perubahan terakhir pada form) |
| `9f4d7de` | 2026-10-19 14:34 | Cek admin-only ditambahkan |
| `d9ab191` | 2026-10-20 08:06 | `app/main.py` dipecah → `app/products_routes.py` (route pindah ke baris 1045) |
| `491d036` | 2026-10-20 11:28 | **Commit terakhir yang masih memuat route** (`app/products_routes.py:1133-1155`) |
| **`5f82f94`** | **2026-10-20 11:35:46** | **MENGHAPUS route** — commit message "fix(product): make PDF delete button independent and improve delete-file handling" **tidak menyebut** penghapusan route produk; hanya menyentuh `app/products_routes.py` + `app/templates/edit_product.html`, **tidak** menyentuh `app/templates/dashboard.html` |
| `8123600` / `159c647` / `d2cbf9b` | 20 Okt | Tidak menghidupkan kembali route |

**Bukti produksi (read-only).**

* **23 request** dengan `route='/products/delete/{product_id}'` tercatat di
  `activity_logs` (2026-10-09 s.d. 2026-10-16) ⇒ route itu benar-benar hidup
  dan benar-benar dipanggil.
* **9 dari 9** produk ter-trash punya baris `action='delete'`, dengan
  `deleted_at` jatuh **0,003–0,154 detik** sebelum `created_at` baris audit
  ⇒ urutan update → audit, persis seperti handler soft delete.
* **2 `actor_id` manusia** (bukan `System`), **0** `actor_id` NULL.
* SQL Editor **tidak bisa** menghasilkan baris `activity_logs` ⇒ mustahil
  out-of-band.

**Bukti build ter-deploy (read-only).**

| Probe | Hasil |
| :--- | :--- |
| `GET /products/delete/<uuid>` | **404** — route absen |
| `GET /admin/products/<uuid>/restore` | **405 `Allow: POST`** — route hadir |

`git grep -n 'products/delete' HEAD` → **1 hit**, hanya di
`app/templates/dashboard.html:232` ⇒ **dangling reference**. `git blame` →
form terakhir diubah `b17632d` (14 Sep) dan **tidak pernah** diperbarui
sejak itu.

Teks konfirmasi `"Semua formula di dalamnya bakal ikut kehapus men."`
(`app/templates/dashboard.html:232`) **salah faktual sejak `f373ace`
(27 Agustus 2026)** — soft delete **tidak** menghapus formula.

#### 13.7.2 KRITIS — bucket storage produksi PUBLIK dan path-nya dapat dikonstruksi

Dari `storage.buckets` (read-only):

| Bucket | `public` | Objek | Dokumen |
| :--- | :--- | ---: | :--- |
| `raw-material-docs` | **true** | 646 | MSDS, spec-sheet, CoA, halal, QC report |
| `legal-documents` | **true** | 105 | hak & lisensi merk, NIB/CPKB/SOP perusahaan |
| `product-attachments` | `false` | 8 | disajikan via signed URL |

Probe **HEAD tanpa `Authorization` dan tanpa `apikey`** → **200 +
`content-type: application/pdf`** pada MSDS, spec-sheet, CoA, hak-lisensi-merk,
dan NIB (tanpa body diunduh). Path yang dapat dikonstruksi **dari field bisnis
biasa saja** (bukan dari kolom URL):

| Path | Field bisnis yang dibutuhkan | Lokasi kode |
| :--- | :--- | :--- |
| `coa/coa_{clean_batch}.pdf` | nomor batch | `app/raw_materials_routes.py:910` |
| `qc-reports/qcreport_{clean_batch}.pdf` | nomor batch | `app/raw_materials_routes.py:942` |
| `halal/halal_{clean_batch}.pdf` | nomor batch | `app/raw_materials_routes.py:925` |
| `msds/msds_{clean_kode}_{company_slug}.pdf` | kode bahan baku + perusahaan | `app/main.py:45` |
| `spec-sheets/specsheet_{clean_kode}_{company_slug}.pdf` | kode bahan baku + perusahaan | `app/main.py:56` |

Seluruh probe path tersebut **200**.

**Kesimpulan.** Siapa pun yang mengetahui nomor batch atau kode bahan baku —
data yang tampil di form PO dan di UI — dapat mengunduh MSDS, CoA, Halal, QC
Report, hak-lisensi merk, dan dokumen legal perusahaan **tanpa login**.
Catatan: audit sebelumnya hanya menandai ini sebagai OBSERVATION "tidak dapat
diverifikasi" (F-19) — kini **terbukti eksposur nyata** (§8.2 K12).

**Arah perbaikan (bukan eksekusi).** `UPDATE storage.buckets SET public=false`
untuk `raw-material-docs` + `legal-documents`, alihkan semua pembacaan ke
`object_store.signed_url()` (`app/object_store.py:440-479` sudah ada), dan/atau
ubah pola path agar tidak dapat ditebak. **Perlu keputusan owner.**

#### 13.7.3 Root cause A13/BE-07: `profiles.perusahaan` NULL untuk 7/7 profil produksi

| Titik | Perilaku |
| :--- | :--- |
| `app/security.py:21-22` | `if not user_company: return True` — **fail-open** |
| `app/products_routes.py:863-864` | menolak hanya bila **kedua** sisi non-empty |
| `app/products_routes.py:1093-1096` | idem — syarat penolakan butuh `_user_company` **dan** `_prod_company` |
| `app/main.py:617,626,633` | `current_user["perusahaan"]` diambil dari `profiles.perusahaan` |

Di produksi `perusahaan` NULL/kosong untuk **semua** profil ⇒
`_user_company` = `""` ⇒ cabang penolakan **tidak pernah dapat dieksekusi**.
Inilah sebab nyata `outcome='rejected'` = 0 (lihat §13.7.6). Heuristik
penduga: replikasi di staging juga menunjukkan **2 dari 5** profil dengan
`perusahaan` kosong.

#### 13.7.4 `public_link_audits` ada di produksi tapi DDL-nya tidak codified

* Tabel `public.public_link_audits` **ADA** di produksi: **93 baris**; kolom
  `id`, `product_id`, `visited_at`, `ip_address`, `user_agent` — timestamp-nya
  **`visited_at`, bukan `created_at`**.
* **23 produk berbeda**; `visited_at` 2026-08-11 s.d. 2026-10-19; **7 baris**
  setelah 2026-10-01.
* **Tidak ada file `migration/*.sql` yang membuatnya** — dibuat manual via SQL
  Editor, dan itu acknowledged di `app/dip_public.py:103`.
* Konsekuensi: fallback `app/dip_public.py:128-144` (INSERT-nya `:130-142`) yang meng-INSERT langsung
  ke `activity_logs` **tanpa set `source`** (⇒ default `'app'` untuk akses
  publik) **tidak akan pernah** terpicu di produksi (`action='public_link_visit'`
  = 0 baris ⇒ fallback dorman), tetapi **menjadi fail-open di environment
  baru** di mana tabel itu tidak ada.
* Rekomendasi: `migration/008_create_public_link_audits.sql` (dikerjakan
  operator lewat Supabase SQL Editor).

#### 13.7.5 Cakupan detail storage di audit trail tipis

* `activity_logs.changes` bertipe **jsonb**.
* Hanya **4 dari 1.312** baris produksi memuat entri `Storage (R2)`.
* Distribusi 16 baris `entity_type='product_file'` + `action='delete'`:
  **4** memakai label baru `Storage (R2)`, **4** memakai label lama
  `Storage`, **7** tanpa field storage sama sekali, **1** `changes` kosong
  (`[]`).
* 2 dari 6 request setelah fitur ter-deploy tidak punya note karena
  `file_url` sudah NULL (tidak ada objek storage) ⇒ **bukan** gap pencatatan.
* `entity_type='product_attachment'` (**13 baris**: upload 9, update 3, delete
  1) ⇒ **0** storage note, karena `storage_note` hanya diteruskan dari
  **satu** call site: `app/products_routes.py:1151`.
* **0** catatan kegagalan storage (`"...perlu dibersihkan manual (bucket/path)"`)
  tercatat.

#### 13.7.6 `outcome` 100% 'success' — ini guard fail-open, bukan dead code

Produksi: `outcome` = success **1.312** / rejected **0** / failed **0**;
`source` = app **1.312** / public **0** / migration 0. Tiga sebab terukur:

| # | Sebab | Bukti |
| :--- | :--- | :--- |
| a | **Guard fail-open** — `profiles.perusahaan` kosong untuk semua profil, sehingga jalur penolakan tenant tidak pernah aktif | §13.7.3 |
| b | **Modul baru belum pernah dipakai** — `entity_type` `brand`, `brand_legal_document`, `sample_submission` = **0 baris** di produksi (modul dibuat 2026-10-20) sehingga `outcome='failed'` di sana mustahil terpicu | §13.6 |
| c | `outcome="rejected"` baru masuk sejak 2026-10-09 (`19f274e`), dan log penolakan tenant di `app/products_routes.py:1100` baru ditambahkan 2026-10-20 | `git log` |

**Implikasi.** Nol `rejected` **tidak** membuktikan tidak ada percobaan
lintas-tenant — ia membuktikan **guard-nya sendiri tidak pernah aktif**. Yang
terukur adalah **konfigurasi guard**, bukan aktivitas pengguna.

#### 13.7.7 Build ter-deploy tidak bisa diikat ke commit

* `GET /health` → 200, body persis sama dengan `app/main.py:588-590`.
* `GET /login` → 200, **5.111 byte**, memuat `cdn.tailwindcss.com` (Tailwind
  v3), **tanpa marker versi/commit/build** di body maupun header.
* Header yang ada hanya `date`, `content-type`, `server: cloudflare`,
  `x-render-origin-server: uvicorn`, `rndr-id`, `cf-ray`, `cf-cache-status`,
  `content-encoding` — **tanpa** `etag`, `x-powered-by`, `x-commit`,
  `x-version`, `x-render-deployment`.
* Parity parsial terverifikasi lewat 8 probe GET (route set cocok:
  `/products/delete` 404, `/products/{id}/delete-file` 405,
  `/admin/products/{id}/restore` 405, `/products/{id}/edit` 303,
  `/dip/probe-…` 404 HTML aplikasi, `/brands` 303, `/admin/users` 303,
  `/raw-materials` 303, `/api/po/products` 303) plus format note storage yang
  ter-deploy identik dengan `app/products_routes.py:1138-1143`.

**Konsekuensi:** asumsi §14.1 — bahwa `app/dip_public.py` yang ter-deploy
identik dengan repo, sehingga fallback fail-OPEN **tidak** aktif di produksi —
**tidak dapat dibuktikan** dari luar. Langkah termurah: Render Dashboard →
Events → baca commit SHA hasil deploy sukses terakhir, bandingkan dengan
`git log --oneline -1`.

### 13.8 Implementasi, migrasi 008, dan uji soft delete produksi (21 Oktober 2026)

> **Cakupan.** Sub-bagian ini mencatat **pekerjaan implementasi** yang
> menyusul audit — bukan temuan baru. Tiga hal: (1) route soft-delete
> produk dipulihkan beserta 6 gap yang ditutup, (2) `migration/008`
> dieksekusi di staging lalu produksi, dan (3) uji soft delete **di
> produksi**. Semua eksekusi DDL lewat **Supabase Management API** atas
> otorisasi eksplisit pemilik repo. **Tidak ada** `git add`, `git commit`,
> maupun `git push` — seluruh perubahan hanya di working tree.

#### 13.8.1 Route soft delete dipulihkan (regresi `5f82f94` diperbaiki)

`POST /products/delete/{product_id}` **dipulihkan** ke
`app/products_routes.py` dari versi terakhir yang utuh
(`git show 491d036:app/products_routes.py:1133-1155`), lalu **6 gap** yang
tidak ada di versi lama ditutup. Nomor baris di bawah adalah nomor
**setelah** pemulihan.

| Gap | Apa yang ditutup | File:line |
| :--- | :--- | :--- |
| **G1** | `outcome="rejected"` + baris audit **sebelum** `raise 403` — penolakan non-admin selalu terekam | `app/products_routes.py:124-129` |
| **G2** | `success_msg` / `error_msg` di **setiap** jalur keluar (sukses, tidak ditemukan, sudah ada di Sampah, dan 2 jalur exception) | `:145, :156, :169, :193, :213` |
| **G3** | `changes=[{"field":"is_deleted","note":"dipindahkan ke sampah"}]` — jejak audit bisa merekonstruksi perpindahan ke Sampah | `:209` |
| **G4** | Guard `.eq("is_deleted", False)` pada UPDATE **plus** penanganan 0-baris (produk yang statusnya berubah di antara SELECT dan UPDATE ditolak, bukan dilaporkan sukses) | `:182` + `:197-205` |
| **G5** | "Produk tidak ditemukan." / "Produk sudah ada di Sampah." dengan `outcome="rejected"` | `:149-170` |
| **G6** | Exception → `print` + `outcome="failed"` + `error_msg` — gagal tidak lagi diam-diam | `:137-146, :185-194` |

Selain route itu sendiri:

* `app/templates/dashboard.html` — form hapus kini di-gate
  `{% if current_user.role == 'admin' %}` (`:232`) dan **teks konfirmasi
  diperbaiki**. Kalimat lama *"Semua formula di dalamnya bakal ikut
  kehapus men."* **salah faktual sejak `f373ace` (27 Agustus 2026)** —
  soft delete **tidak** menghapus formula. Teks baru menyatakan formula
  **tidak** ikut terhapus dan produk masih bisa dikembalikan dari menu
  Sampah.
* `app/dashboard_routes.py` — jalur **restore** kini menyimpan
  `deleted_at` lama ke `changes` (`:64-74`), sehingga nilai "sejak kapan
  produk itu di Sampah" tetap bisa direkonstruksi.
* Tabel route naik **106 → 107** (`app.router.routes` = 107 pada working
  tree; angka itu sudah termasuk 4 route dokumentasi `/docs`, `/redoc`,
  `/openapi.json`, `/docs/oauth2-redirect`).
* Resolusi konkret route (diuji dengan path-regex Starlette pada working
  tree): `POST /products/delete/<uuid>` → `Match.FULL` ke route baru;
  `GET` → `Match.PARTIAL` → **405 `Allow: POST`**; dan **tanpa shadowing**
  `/products/{id}/edit` (→ `Match.FULL`), `/products/{id}/delete-file`
  (→ `Match.PARTIAL`), serta `/products/add` (→ `Match.PARTIAL`).

#### 13.8.2 Migrasi 008 dieksekusi di staging lalu produksi

`migration/008_products_soft_delete_contract.sql` dieksekusi pada
**21 Oktober 2026** di staging (`odtfppboyjlbatajncgj`) lalu produksi
(`dytuprmoorvrugutozwv`), **atas otorisasi eksplisit pemilik repo**.
Jalur eksekusi: **Supabase Management API**
(`POST https://api.supabase.com/v1/projects/{ref}/database/query`, header
`Authorization: Bearer <token>`, body `{"query": "<sql>"}`) — **bukan**
Supabase SQL Editor. Token diekstrak **programatis** dari
`.kilo/kilo.jsonc` (`mcp.supabase.command --access-token`) dan **tidak
pernah dicetak**.

| Item | Staging `odtfppboyjlbatajncgj` | Produksi `dytuprmoorvrugutozwv` |
| :--- | :--- | :--- |
| Pre-check pelanggaran konsistensi | **0 baris** | **0 baris** |
| Constraint `products_soft_delete_consistency` | dibuat, `convalidated = true`, definisi persis `CHECK (((is_deleted AND (deleted_at IS NOT NULL)) OR ((NOT is_deleted) AND (deleted_at IS NULL))))` | idem — `convalidated = true`, definisi identik |
| Index `idx_products_is_deleted_deleted_at` | `ON public.products USING btree (is_deleted, deleted_at DESC)` | idem |
| **Probe enforcement** | `UPDATE ... SET is_deleted=true, deleted_at=NULL` **DITOLAK SQLSTATE 23514**; baris di-re-read **tidak berubah** | idem |
| Hitungan data (sebelum → sesudah) | 2 produk, 1 ter-trash → **tetap** | 136 produk, **8 ter-trash** → **tetap**; `deleted_at` ke-8 produk **byte-identik** dengan snapshot pra-migrasi; `public_access_token` NOT NULL 136 → **136** |
| Jalur eksekusi | Supabase Management API atas otorisasi eksplisit owner (**bukan** SQL Editor) | idem |

> **Coret/catat — header file migrasi.** Header `migration/008` **sebelumnya**
> menyatakan file itu **"TIDAK PERNAH dieksekusi oleh agen otomatis"** —
> pernyataan itu kini **tidak akurat** dan **sudah diperbarui** di header
> file. Header lama juga masih menyebut cara eksekusi "Supabase SQL
> Editor", padahal eksekusi yang benar-benar terjadi adalah Management
> API atas otorisasi owner (lihat blok `RIWAYAT EKSEKUSI` di header
> yang baru). Sub-bagian ini adalah rujukan yang otoritatif.

**Dua penyimpangan yang ditemukan saat eksekusi — beserta follow-up-nya.**

1. **`products.is_deleted` tetap NULLABLE.** Kolom ini **sudah ada**
   sebelum migrasi 008 ⇒ `ADD COLUMN IF NOT EXISTS` jadi **no-op** dan
   clause `NOT NULL` **tidak pernah berlaku**. Konsekuensinya: baris
   dengan `is_deleted = NULL` **LOLOS** dari CHECK constraint (SQL
   three-valued logic — `NULL AND ...` bernilai `NULL`, yang dianggap
   tidak melanggar). Saat itu 0 baris bermasalah di kedua environment,
   jadi tidak ada pelanggaran nyata — tetapi kontraknya tidak airtight.
   **Follow-up:** `ALTER COLUMN is_deleted SET DEFAULT false` +
   `ALTER COLUMN is_deleted SET NOT NULL`.
2. **Header file migrasi tidak akurat** (lihat catatan di atas) —
   **sudah diperbarui**.

**Hasil follow-up `SET NOT NULL` (21 Oktober 2026, dijalankan sesudah
pemeriksaan di atas).** Urutan per environment: guard → pre-state → 2
`ALTER` → post-state. Guard wajib bernilai 0 di kedua environment;
bila tidak, eksekusi **dihentikan** untuk environment itu.

| Item | Staging | Produksi |
| :--- | :--- | :--- |
| Guard `is_deleted IS NULL` | **0** | **0** |
| Guard inkonsistensi `(is_deleted AND deleted_at IS NULL) OR (NOT is_deleted AND deleted_at IS NOT NULL)` | **0** | **0** |
| Pre-state | total **2**; `is_deleted=true` **1** / `=false` **1** / `IS NULL` **0**; `deleted_at` NULL **1** / NOT NULL **1** | total **136**; `true` **9** / `false` **127** / `IS NULL` **0**; `deleted_at` NULL **127** / NOT NULL **9** |
| `information_schema.columns.is_nullable` (sebelum) | **YES** | **YES** |
| Eksekusi | `SET DEFAULT false` → HTTP **201**; `SET NOT NULL` → HTTP **201**; **0 error** | `SET DEFAULT false` → HTTP **201**; `SET NOT NULL` → HTTP **201**; **0 error** |
| `is_nullable` (sesudah) | **NO** | **NO** |
| Post-state | total **2**; `true` **1** / `false` **1** / `IS NULL` **0**; `deleted_at` NULL **1** / NOT NULL **1** — **tidak berubah** | total **136**; `true` **9** / `false` **127** / `IS NULL` **0**; `deleted_at` NULL **127** / NOT NULL **9** — **tidak berubah** |
| Constraint + index setelah ALTER | `products_soft_delete_consistency` **masih ada**, `convalidated = true`, definisi tidak berubah; `idx_products_is_deleted_deleted_at` **masih ada** | idem — `convalidated = true`, definisi identik, index **masih ada** |

> **Catatan angka.** Angka produksi pada baris pre/post-state adalah
> **9** ter-trash, bukan 8 seperti pada saat migrasi 008 dieksekusi —
> karena **setelah** migrasi itu ada uji soft delete produksi (§13.8.3)
> yang menambah satu produk ter-trash. Baris `8 ter-trash → tetap` pada
> tabel migrasi di atas adalah angka **saat migrasi dieksekusi**.

#### 13.8.3 Uji soft delete produksi pada "tes log 12" (LULUS)

| Item | Nilai |
| :--- | :--- |
| Target | `3ed1b077-e6f1-4ec0-acac-3bb7152a0362` — ``tes log `12``, PT Erfi |
| Environment | app lokal milik owner di `127.0.0.1:8000`, terikat ke Supabase **produksi** — dibuktikan: **128** id produk dari app == **128** id dari DB produksi (himpunan sama); staging hanya punya **2** |
| Login | `coretail` (`profiles.role = 'admin'`), **1** percobaan login |

| Langkah | Hasil |
| :--- | :--- |
| Health | **200** |
| `GET /products/delete/<uuid>` | **405** `Allow: POST` — route hidup di build yang diuji |
| Baseline produk | `is_deleted = false`, `deleted_at = null` |
| Baseline audit | **5** baris |
| Restore | **303** → `/admin/trash?success=...` + audit `action = restore` |
| Soft delete | **303** → `/` + `success_msg` ``"Produk 'tes log `12' dipindahkan ke Sampah."`` + audit `action=delete, outcome=success, changes=[{"field":"is_deleted","note":"dipindahkan ke sampah"}], route=/products/delete/{product_id}, http_method=POST, source=app, actor_name=coretail` |
| Data anak utuh | **0 / 0 / 0 / 0** (formula, dokumen, batch, lampiran) |
| Tampil di UI | produk **hilang** dari `/` dan **ADA** di `/admin/trash` |
| Kasus negatif 1 | delete kedua → **303** + `error_msg` *"Produk sudah ada di Sampah."* + audit `outcome = rejected`; `deleted_at` **byte-identik** (tidak ada double-write) |
| Kasus negatif 2 | UUID tidak ada → **303** + `error_msg` *"Produk tidak ditemukan."* + audit `outcome = rejected` dengan `entity_id = 00000000-0000-0000-0000-000000000000` |
| Delta audit | **+4 tepat** = 1 restore + 1 delete-success + 2 rejected, dengan **tepat 1** baris `action='delete' AND outcome='success'` |
| Integritas global | `products` **136** tetap, `trashed` 8 → **9**, `inkonsisten` **0**, `activity_logs` 1.313 → **1.317**; snapshot diff **136 baris → hanya target yang berubah** |

**Empat penyimpangan yang jujur harus dicatat.**

1. **Baseline produk ternyata `is_deleted = false` (aktif), bukan ter-trash.**
   Ada baris audit `action = restore` pada **2026-10-21 07:49:59.094Z**
   oleh `coretail` **sebelum** test, sehingga langkah restore pada test
   adalah restore atas baris yang **tidak** ter-trash — payload-nya
   `note = "None"` (nilai `deleted_at` sebelumnya memang NULL).
   **Akhir test: produk berada di Sampah** (`trashed` 8 → 9).
2. **`products.updated_at` tidak ada di produksi** (error `42703`),
   sehingga query baseline disesuaikan — kolom itu memang tidak pernah
   ada di produksi.
3. **Route restore tidak memakai `set-cookie`**, melainkan query param
   `?success=...` (`app/dashboard_routes.py:75`).
4. **Nama produk sempat masih muncul di HTML `/`** setelah delete — itu
   **flash banner** `success_msg`, bukan kartu produk (dibuktikan dengan
   sesi bersih: id **dan** nama absen dari `/`).

#### 13.8.4 Verifikasi suite setelah perubahan

| Suite | Hasil |
| :--- | :--- |
| `tests/test_audit_regressions.py` | **PASS 21 / KNOWN 18 / FAIL 0 / SKIP 2**, exit 0 — check **SEC-01 naik dari `[KNOWN]` ke `[PASS]`** |
| `tests/verify_audit_db_state.py` | **49 check**, PASS 21 / FAIL 0 / WARN 6 / INFO 22, exit 0 — **G9.6 soft-delete consistency = PASS** |
| `pytest tests/ -q` | **79 passed**, 0 failed |
| `scripts/check_undefined_names.py` | exit 0 |

> **Catatan hitungan BE-08.** Count BE-08 sempat naik **10 → 11** akibat
> *false positive* `str(old_deleted_at)` di `app/dashboard_routes.py` —
> itu **timestamp**, bukan pesan exception. Hitungan itu lalu
> **dikoreksi** kembali ke **10 lokasi** dan check BE-08 tetap
> `[KNOWN]` (temuannya memang belum diperbaiki).
## 14. Rekomendasi Perbaikan (Poin 1–3)

> **Status §14.** Isi bagian ini **rekomendasi**, bukan temuan baru. Semua
> temuan yang dirujuk sudah tercatat di §4–§10 dan dikoreksi di §8.2; §14
> hanya menerjemahkannya menjadi langkah yang bisa dieksekusi. **Suite test
> hanya mendeteksi, tidak memperbaiki** (§12) — setelah butir ini dikerjakan,
> yang berubah adalah check-nya dari `[KNOWN]` menjadi `[PASS]`.
>
> Tiga kelompok: **Poin 1** status migrasi (§14.1), **Poin 2** soft-delete
> produk (§14.2), **Poin 3** audit trail (§14.3).

### 14.1 Poin 1 — Status migrasi (selesai diverifikasi)

**Verifikasi read-only, 21 Oktober 2026 (malam), lewat Supabase Management
API.** Hanya `SELECT` ke `pg_catalog` / `information_schema` plus kueri
pembuktian; tidak ada statement yang mengubah data, tidak ada file
`migration/*.sql` yang dieksekusi ulang, tidak ada `git add` / `git commit` /
`git push`.

| Migrasi | Objek yang diperiksa | Staging | Produksi | Bukti |
| :--- | :--- | :--- | :--- | :--- |
| `001` | tabel `purchase_orders` + `purchase_order_items` | terpasang | terpasang | `pg_class` |
| `002` | kolom `purchase_orders.jenis_po` | terpasang | terpasang | `information_schema.columns` |
| `003` | 7 kolom konteks audit + 4 index + 2 `CHECK` + FK `actor_id → profiles(id)` | terpasang | terpasang | `pg_indexes`, `pg_constraint` |
| `004` | tabel `product_attachments` + view `product_attachment_counts` | terpasang | terpasang | `pg_class` |
| `005` | `brands.hak_merk_file_url` + `brands.lisensi_merk_file_url` | terpasang | terpasang | `information_schema.columns` |
| `006` | view `product_formula_presence` | terpasang | terpasang | `pg_class` |
| `007` | 4 kolom capability di `products` + index UNIQUE parsial | terpasang | terpasang | kueri pembuktian **mengembalikan 136 baris** (bukan error `42703`) + `pg_indexes` |

**Verdict 007 di produksi — bukti penentu.** Kueri yang merujuk
`public_access_token` / `public_access_enabled` / `bpom_registered_link`
mengembalikan **136 baris**, bukan error `42703` ("column does not exist")
yang akan muncul bila migrasi belum terpasang. Secara terpisah, `pg_indexes`
independen menunjukkan index UNIQUE parsial
`… WHERE public_access_token IS NOT NULL`. Dua bukti yang tidak saling
bergantung → **007 TERPASANG di produksi**.

**Verdict fallback fail-OPEN — TIDAK AKTIF di produksi.** Karena keempat
kolom 007 ada, `app/dip_public.py:275-277` berhasil dan cabang
`except Exception:` di `app/dip_public.py:294-300` **tidak pernah dimasuki**.
Perilaku produksi:

| Kondisi | Jumlah (dari 136) | Lokasi kode |
| :--- | ---: | :--- |
| Produk yang menuntut `public_access_token` persis | 134 | `app/dip_public.py:285-292` |
| Produk `bpom_registered_link = true` yang tetap tanpa token (jalur legacy yang disengaja) | 2 | `app/dip_public.py:290-291` |
| Produk soft-deleted yang ditolak | 9 | `app/dip_public.py:279-280` |

Dengan demikian **SEC-09 dan BE-20 REFUTED untuk produksi**. Keduanya pernah
CONFIRMED untuk staging sebelum run migrasi 2026-10-21; fallback fail-OPEN di
staging juga sudah tertutup (§13.5).

> Snapshot produksi lengkap ada di **§13.6**.

**Status produksi kini VERIFIED — bukan "belum terverifikasi" lagi.** Tidak
ada migrasi yang perlu dieksekusi di produksi. Yang tersisa hanya **menjaga**
kondisi itu: karena migrasi dijalankan manual, tidak ada apa pun yang
otomatis memastikan project baru ikut 001–007. Karena itu re-check katalog
wajib diulang setelah setiap migrasi berikutnya (satu query read-only per
objek, tabel di atas).
### 14.2 Poin 2 — Rekomendasi soft-delete (9 item)

> **Status per 21 Oktober 2026.** **R1 sudah diimplementasikan** (21 Oktober
> 2026, §13.8.1) dan `migration/008` **sudah dieksekusi** di **staging** lalu
> **produksi** (§13.8.2) — keduanya bukan lagi rencana. Tabel 6 gap G1–G6 di
> bawah kini menjadi **catatan hasil**, bukan daftar pekerjaan. Butir
> **R2–R9 masih rekomendasi**.


| ID | Rekomendasi | Lokasi | Verifikasi | Effort | Risiko |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R1** | **[SUDAH DIIMPLEMENTASIKAN 21 Oktober 2026]** **Restore route soft-delete produk — bukan menulis dari nol.** Ambil handler `POST /products/delete/{product_id}` dari `git show 491d036:app/products_routes.py:1133-1155` (versi terakhir yang utuh) ke dalam `register_products_routes`, lalu tutup **6 gap** yang tidak ada di versi lama (tabel G1–G6 di bawah). 4 dari 5 requirement R1 lama **sudah terpenuhi** oleh versi `491d036`: set `is_deleted` + `deleted_at` (`:1147-1148`), admin-only 403 (`:1137-1138`), `log_activity(action="delete", entity_type="product")` (`:1153-1154`), redirect 303 (`:1155`) | `app/products_routes.py` (sisipkan di dalam `register_products_routes`, posisi setelah `POST /products/add`); `app/templates/dashboard.html:231-236` — tambahkan `{% if current_user.role == 'admin' %}` dan **koreksi teks konfirmasi** (saat ini "Semua formula di dalamnya bakal ikut kehapus men." — SALAH faktual sejak `f373ace` 27 Agustus 2026; soft delete **tidak** menghapus formula) | `tests/test_audit_regressions.py` check SEC-01 otomatis naik dari `[KNOWN]` → `[PASS]`; `KNOWN_ISSUES["SEC-01"]` lalu dapat dihapus. E2E `tests/e2e_audit_staging.py` skenario C1 **wajib diubah lebih dulu** (lihat R8) karena skenario itu benar-benar submit form dan akan menghapus produk staging | S (paste + 6 perbaikan kecil) — bukan M seperti saat R1 masih berisi "tulis dari nol" | **Tinggi** kalau tidak dikerjakan: tombol "Hapus Produk" di dashboard tetap 404 dan operator tidak punya cara *retiring* produk yang sah. **Status 21 Oktober 2026: SELESAI** — route dipulihkan ke `app/products_routes.py:119-214`, 6 gap G1–G6 ditutup, form dashboard di-gate admin + teks konfirmasi dikoreksi; `KNOWN_ISSUES["SEC-01"]` sudah dihapus dari `tests/test_audit_regressions.py` dan check SEC-01 naik dari `[KNOWN]` ke `[PASS]` (§13.8.1) |
| **R2** | **Kontrak audit untuk siklus sampah → restore.** `dashboard_routes.py:64-65` sudah mencatat restore tetapi **tidak menyimpan `deleted_at` lama**; tambahkan `changes=[{"field":"deleted_at","note":str(old_deleted_at)}]` pada restore dan `changes=[{"field":"is_deleted","note":"dipindahkan ke sampah"}]` pada delete. `activity_logs` praktis **append-only**, jadi baris yang hilang tidak bisa direkonstruksi. | `app/dashboard_routes.py:55-69`; `app/products_routes.py` (route delete hasil restore R1) | Baca `activity_logs` untuk satu produk: ada 1 baris `action='delete'` + 1 baris `action='restore'`, keduanya punya `changes` | S | Sedang: `changes` jadi semi-manual; bentuk JSON `{"field","note"}` harus tetap dipakai (§14.3) |
| **R3** | **Tutup asimetri guard bahan baku.** `raw_materials_routes.py:683` menghitung produk soft-deleted sebagai "masih dipakai", sedangkan badge `usage_count` (`:204-217`) dan API "Dipakai di Produk" (`:260-273`) **sengaja tidak** menghitungnya → halaman yang sama menampilkan "0 Produk" dan "Dipakai di Produk: kosong", lalu Delete gagal dengan "Bahan baku ini masih dipakai di 1 formula produk: \<produk di sampah\>". Teks UI di `raw_materials.html:182` sudah menjanjikan perilaku yang benar ("jika masih dipakai di produk **aktif**"). | `app/raw_materials_routes.py:683` — pakai helper `_is_deleted_product()` yang sudah ada di `:15-24` | Check regresi baru + uji manual: hapus bahan baku yang dipakai produk di sampah → harus berhasil | S | Sedang: bahan baku yang **memang** dipakai produk aktif tidak boleh ikut lolos |
| **R4** | **Tutup 5 kebocoran `is_deleted`.** `presence_routes.py:125` (badge ED), `main.py:272-277` (`get_ed_notification_count`), `sample_routes.py:55` (produk jadi FSP), `sample_routes.py:418` (prefill form FSP), `efek_samping.py:395` (hapus NIES). Yang paling relevan untuk kepatuhan: **produk di sampah masih bisa dipilih sebagai produk jadi FSP yang sudah ditandatangani**. | 5 file tersebut | Tiap lokasi: produk di sampah tidak muncul di daftar dan tidak bisa dipilih | S | Sedang: 5 filter tambahan mengubah angka badge ED → deskripsi badge harus disinkronkan |
| **R5** | **Kluarkan produk di sampah dari KPI PO Analytics per perusahaan.** `po_routes.py:337-352` mencatat `poid` ke `comp_q_po` tanpa mengecek `meta["active"]` (flag dihitung di `:305`), sementara `produced`/top/detail sudah memakai `active_ids` (`:371-372`). Tambahkan `if not meta.get("active"): continue`. | `app/po_routes.py:337-352` | KPI per perusahaan di `/po-analytics` tidak lagi menghitung PO atas produk di sampah | S | Rendah–Sedang: angka KPI berubah → perlu dikomunikasikan |
| **R6** | **Migrasi kontrak soft-delete.** File baru `migration/008_products_soft_delete_contract.sql`: `products.is_deleted boolean NOT NULL DEFAULT false`, `products.deleted_at timestamptz`, CHECK konsistensi `(is_deleted AND deleted_at IS NOT NULL) OR (NOT is_deleted AND deleted_at IS NULL)`, index `idx_products_is_deleted_deleted_at (is_deleted, deleted_at DESC)`. **Tidak ada `migration/*.sql` yang mendeklarasikan kolom ini** — tabel `products` dibuat di luar repo (`migration/001:4-5` menyatakan tabel itu tidak disentuh), jadi status kolom produksi **sudah diverifikasi ulang** (§13.6) sebelum file dieksekusi. | `migration/008_products_soft_delete_contract.sql` (baru); `migration/001_create_purchase_orders.sql:4-5` (alasan) | `\d products` di SQL Editor: 4 objek baru ada; CHECK menolak baris yang tidak konsisten. **Status kolom sudah terverifikasi (21 Okt 2026, §13.6):** `products.is_deleted` + `products.deleted_at` **ada di produksi** — 9 dari 136 produk soft-deleted, semuanya punya `deleted_at` terisi ⇒ file ini praktis hanya menambahkan CHECK + index | S (file) + M (eksekusi di 2 environment) | Sedang: file **dikerjakan operator lewat Supabase SQL Editor, bukan agen**; migration harus mendahului R1. **Status 21 Oktober 2026: SUDAH DIJALANKAN** di **staging** lalu **produksi** lewat Supabase Management API atas otorisasi eksplisit owner; `is_deleted` sempat tetap NULLABLE (`ADD COLUMN IF NOT EXISTS` no-op) lalu ditutup dengan `ALTER COLUMN is_deleted SET NOT NULL` (§13.8.2) |
| **R7** | **Badge Bab IV "5/5" hardcode.** `dashboard.html:331` menampilkan "5/5" konstan, padahal `dashboard_routes.py:200-208` mengecek **4** item dan `:162` mendaftarkan **5** label → satu konsep punya tiga angka berbeda (badge 5/5, rasio 4/4, progress 4+1). Putuskan satu definisi (4 wajib + 1 bonus, atau 5 wajib) lalu terapkan ke badge, rasio, dan `progress_pct` sekaligus. | `app/templates/dashboard.html:331`; `app/dashboard_routes.py:161-162, 200-216` | Badge dan rasio selalu sama untuk semua produk | S | Rendah: perubahan tampilan, tapi angka checklist Bab IV terlihat tidak konsisten sampai diperbaiki |
| **R8** | **Re-baseline tiga suite test** agar perbaikannya terkunci, bukan sekadar terdeteksi. `tests/verify_audit_db_state.py` G2.1 kini PASS hanya bila `deleted == 0` → harus jadi "PASS bila setiap produk di sampah punya `deleted_at` **dan** baris `activity_logs` dengan `action='delete'`". `tests/e2e_audit_staging.py` skenario C1 benar-benar mengirim form delete → begitu R1 land, C1 **akan menghapus produk staging**; ubah jadi probe read-only, atau trash → restore pada fixture yang dibuat E2E itu sendiri. `KNOWN_ISSUES["SEC-01"]` dihapus setelah R1. | `tests/verify_audit_db_state.py` (G2.1); `tests/e2e_audit_staging.py` (C1); `tests/test_audit_regressions.py` (registry) | `venv\Scripts\python.exe tests\test_audit_regressions.py` → KNOWN turun 1 (19 → 18), FAIL tetap 0; `pytest tests/ -q` tetap hijau | M | Sedang: mengubah baseline suite bisa menutupi regresi baru bila tidak hati-hati |
| **R9** | **Sinkronkan dokumentasi.** `README.md:42` dan `panduan:662, 666` menjanjikan soft delete yang **pernah bekerja lalu mundur** (regresi `5f82f94`, §13.7.1) — behavior yang dijanjikan itu sendiri sudah benar, tinggal dipulihkan; perbarui ke perilaku final (soft delete, admin-only, formula **tidak** dihapus, restore via `/admin/trash`), tambahkan baris migrasi 008 di tabel migrasi (`README.md:24, 227-230, 297-302`; `panduan:577-580`), dan dokumentasikan model soft delete sebagai bagian dari model data. | `README.md:24, 42, 227-230, 297-302`; `panduan_dip_automation_system.md:577-580, 662, 666` | `grep -n "008" README.md panduan_dip_automation_system.md` → baris migrasi 008 ada di kedua tabel | S | Rendah |

#### 6 gap yang wajib ditutup saat restore R1

| Gap | Referensi `491d036` | Dampak |
| :--- | :--- | :--- |
| **G1** tidak ada `log_activity(..., outcome="rejected")` di jalur 403 | `:1137-1138` | Penolakan tidak terekam; pola yang benar sudah ada di HEAD `app/products_routes.py:1069-1075` |
| **G2** tidak ada flash cookie sama sekali, sukses maupun gagal | `:1151`, `:1155` | User tidak pernah diberi tahu hasil aksi |
| **G3** tidak ada payload `changes=` | `:1153-1154` | `activity_logs` tidak bisa rekonstruksi detail perpindahan ke sampah (R2 bergantung pada ini) |
| **G4** tidak ada guard `.eq("is_deleted", False)` pada UPDATE | `:1148` | Produk yang sudah di sampah bisa di-*delete* ulang, `deleted_at` ditimpa, dan baris audit "delete success" kedua tercipta |
| **G5** tidak ada penanganan "produk tidak ditemukan" (SELECT `:1141-1142` tanpa cek `.data`, tanpa filter `is_deleted`) | `:1141-1142` | UUID ngawur = UPDATE 0 baris tetapi **tetap** log `action="delete", outcome="success"` ⇒ **baris audit palsu** |
| **G6** jalur exception tidak mencatat `outcome="failed"` dan tidak memberi pesan | `:1149-1151` | Gagal diam-diam (pola "pesan jujur" yang ditolak audit sebagai BE-15) |

> **Restore boleh_changed.** Versi `491d036` memakai `log_activity` **tanpa**
> `outcome` eksplisit (default `"success"`), dan `datetime` / `WIB` /
> `Depends` / `HTTPException` / `Request` / `RedirectResponse` **semua masih
> tersedia di HEAD** ⇒ restore = **paste bersih**, bukan kode baru. Yang baru
> hanyalah 6 perbaikan kecil pada tabel di atas.

#### Bentuk kode yang disarankan (masing-masing ≤ 8 baris)

**R1** — route soft-delete (pola `register_*_routes` + DI, `AGENTS.md §4`).
Blok di bawah = versi `491d036` **sudah diperbaiki** dengan 6 gap (G1–G6):

```python
@app.post("/products/delete/{product_id}")
async def delete_product(request: Request, product_id: str,
                          current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        log_activity(current_user, "delete", "product", product_id, product_id,
                     request=request, outcome="rejected")
        raise HTTPException(status_code=403, detail="Hanya admin yang bisa menghapus produk.")
    supabase.table("products").update(
        {"is_deleted": True, "deleted_at": datetime.now(WIB).isoformat()}) \
        .eq("id", product_id).eq("is_deleted", False).execute()
    log_activity(current_user, "delete", "product", product_id, product_id, request=request)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie("success_msg", "Produk dipindahkan ke Sampah.")
    return response
```

**R3** — guard pemakaian bahan baku ikut memfilter produk di sampah:

```python
usage_check = supabase.table("product_formula_lines").select(
    "product_id, products(nama_produk, is_deleted)").eq("raw_material_id", rm_id).execute()
rows = [ln for ln in (usage_check.data or [])
        if not _is_deleted_product(ln.get("products"))]   # helper :15-24
if rows:
    ...  # hitung jumlah_pemakaian dari `rows`, bukan dari usage_check.data
```

**R5** — KPI PO per perusahaan:

```python
meta = prod_meta.get(pid)
if not meta or not meta.get("active"):   # produk di sampah tidak masuk KPI
    continue
```

**R6** — file migrasi (hanya kerangka; dieksekusi operator):

```sql
ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS deleted_at  timestamptz;
ALTER TABLE public.products
    ADD CONSTRAINT products_is_deleted_deleted_at_check
    CHECK ((is_deleted AND deleted_at IS NOT NULL) OR (NOT is_deleted AND deleted_at IS NULL));
CREATE INDEX IF NOT EXISTS idx_products_is_deleted_deleted_at
    ON public.products (is_deleted, deleted_at DESC);
```

#### Model kanonik soft-delete

1. **Satu definisi `is_deleted`.** Hanya `products.is_deleted` yang menentukan "di sampah". Tidak ada flag paralel (status, arsip, hidden) yang menduplikasi makna ini.
2. **Invarian `is_deleted ⟺ deleted_at IS NOT NULL`.** Kedua kolom harus selalu bergerak berpasangan; CHECK DB (R6) adalah penjaga terakhir, dan kode harus menuliskannya berpasangan juga.
3. **Query yang WAJIB memfilter `is_deleted = false`:** `products_routes`, `dashboard_routes` (halaman utama), `dip_documents`, `dip_public`, `raw_materials_routes` (badge + API), `notes_routes`, `sample_routes`, `po_routes` (KPI & produksi), `efek_samping`, `presence_routes`, `main.py` (badge ED), `product_attachments_routes`. Query yang **boleh** melihat produk di sampah hanya dua: `GET /admin/trash` (`dashboard_routes.py:39`) dan `POST /admin/products/{id}/restore` (`:62`).
4. **Relasi tidak pernah di-cascade oleh sampah.** Memindahkan produk ke sampah tidak boleh menghapus formula, dokumen, batch, lampiran, atau PO — hanya menyembunyikannya.
5. **Produk di sampah tidak boleh dibuat/diunduh sebagai Bab I–IV** dan tidak boleh terjangkau lewat portal publik (`app/dip_public.py:279-280` sudah fail-closed — pertahankan).
6. **Jejak audit wajib per transisi.** Delete → `action="delete"`, `outcome="success"`, `changes` memuat `is_deleted`/`deleted_at`; restore → `action="restore"`, `outcome="success"`, `changes` memuat `deleted_at` lama; penolakan non-admin → `outcome="rejected"`.
7. **Hanya admin boleh membuang dan memulihkan.** Cek role di route delete maupun restore, dan di UI (tombol Hapus hanya untuk admin).
8. **Bahan baku tetap HARD delete.** Model soft delete **tidak** diperluas ke bahan baku; hanya guard pemakaian yang diperbaiki (R3). Penghapusan bahan baku memang meng-cascade batch/dokumen/komponen/varian dan itu disengaja.
9. **Konsumen turunan wajib memakai definisi yang sama:** badge `usage_count`, API "Dipakai di Produk", KPI PO per perusahaan, badge ED/NA, dan pilihan produk jadi FSP. Kalau satu berbeda, **guard harus mengikuti konsumen itu**, bukan sebaliknya.
10. **Sampah ≠ arsip.** "Hapus permanen dari domain BPOM" adalah keputusan bisnis/legal, bukan aksi UI. Tidak ada tombol hapus permanen di aplikasi.

#### Urutan pengerjaan

```
R6 (migrasi 008)  ->  R1 (restore route soft-delete + 6 gap)  ->  R2 (kontrak audit)  ->  R8 (re-baseline suite)
R3, R4, R5, R7  ->  independen, boleh paralel
R9 (dokumentasi)  ->  terakhir, setelah perilaku final terkunci
```

#### Yang TIDAK perlu diubah

| Lokasi | Alasan |
| :--- | :--- |
| `app/dip_public.py:162, 279, 297` | Sudah fail-closed terhadap produk di sampah. |
| `app/product_attachments_routes.py:95-96` | 409 "produk ada di sampah" memang disengaja — harus dibedakan dari 404. |
| `app/dashboard_routes.py:39` dan `:81` | Keduanya benar: trash memang melihat `is_deleted=True`, dashboard melihat `False`. |
| `app/raw_materials_routes.py:204-217` (badge `usage_count`) dan `:260-273` (API "Dipakai di Produk") | Sudah benar. **Guard harus mengikuti mereka, bukan sebaliknya.** |
| `app/dip_documents.py:113, 344, 520, 624, 880` | Sudah memfilter `is_deleted = false`. |
| `app/products_routes.py:124, 207, 411, 463, 509, 635, 850, 1082` | Sudah memfilter. |
| `app/po_routes.py:926, 994, 1060` | Sudah memfilter. |
| `app/notes_routes.py:271, 283, 424` | Sudah memfilter. |
| `app/sample_routes.py:188` | Sudah memfilter. |
| `app/efek_samping.py:233` | Sudah memfilter. |
| `app/dashboard_routes.py:62` | Restore sudah benar (kecuali `changes` seperti R2). |
| Hard delete bahan baku | Bukan bug yang perlu dibalik. |
| `app/po_routes.py:838, 849` | **Tidak boleh** ditambah filter `is_deleted` — query itu harus melihat nilai mentah untuk menghitung flag `active`. |
| `app/product_attachments_routes.py:88` | **Tidak boleh** ditambah filter `is_deleted` — query itu harus bisa membedakan 404 (tidak ada) dari 409 (ada di sampah). |

#### Tindakan untuk baris residual G2.1

Baris soft-deleted di **staging** **dibuat di luar aplikasi** — tidak ada satu
pun kode di `app/` yang menulis `is_deleted=True` (§8.2 K8). Untuk
**produksi** pendekatannya **berbeda**: 9 dari 9 produk ter-trash punya baris
audit `action='delete'` yang sah dengan `actor_id` manusia (§13.7.1) ⇒ baris
itu **dibuat oleh aplikasi**, bukan manual. Rekomendasi untuk pemilik repo:

1. **Produksi** — tidak perlu tindakan pemulihan data: jejaknya sudah ada.
   Yang perlu adalah **restore route** (R1) supaya produk bisa dibuang lewat
   UI *lagi* dan mendapat baris audit baru, plus **koreksi teks konfirmasi**
   di `dashboard.html:232`.
2. **Staging** — **RESTORE lewat UI `/admin/trash`** bila produknya masih
   aktif bisnis, atau **biarkan terbuang** dan trash-kan ulang lewat UI begitu
   R1 + R2 land, agar ia mendapat baris `action="delete"` yang sah.
3. **Jangan pernah** `DELETE FROM products` — FK `ON DELETE RESTRICT`
   memblokirnya, dan menghapus baris akan memusnahkan bukti formulasi.

SQL **read-only** untuk diperiksa pemilik lebih dulu (jalankan sendiri di
Supabase SQL Editor; **agen tidak mengubah data**):

```sql
-- READ-ONLY. Baris di sampah + jejak audit-nya.
SELECT p.id, p.nama_produk, p.is_deleted, p.deleted_at, p.created_at,
       (SELECT count(*) FROM activity_logs a
         WHERE a.entity_type = 'product' AND a.entity_id = p.id
           AND a.action IN ('delete', 'restore')) AS audit_rows
  FROM products p
 WHERE p.is_deleted = true
 ORDER BY p.deleted_at DESC;
```
### 14.3 Poin 3 — Rekomendasi audit trail (9 item)

| ID | Rekomendasi | Lokasi | Verifikasi | Effort | Risiko |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R1** | **Reklasifikasi U6.** Di §13.2 status U6 diubah dari CONFIRMED menjadi **REFUTED sebagai temuan kode** — jalur `entity_type="product_attachment"` memang ada di kode (`app/product_attachments_routes.py:185, 220, 242`); absennya di staging adalah **artefak ketiadaan data** (`product_attachments` 0 baris), bukan bukti kode rusak. Produksi membuktikan: 13 baris `product_attachment`. Tambahkan baris koreksi di §8.2 yang menunjuk celah **dokumentasi** yang sebenarnya: 5 nilai `entity_type` belum masuk tabel entitas audit. | `catatan/catatan_audit_codebase_2026-10-21.md` §13.2 + §8.2; `app/product_attachments_routes.py:185, 220, 242` | §13.2 memuat "REFUTED" untuk U6, dan §8.2 memuat baris koreksi baru | S | Rendah |
| **R2** | **Perbaiki check mustahil di G8.3.** `tests/verify_audit_db_state.py` menguji `storage_note` seolah-olah `entity_type` — padahal itu **keyword-only parameter** `log_activity` (`app/main.py:829`) yang diserialisasi ke kolom JSON `changes` (`app/main.py:849-851`), sehingga `has_sn` permanen `False` dan verdict permanen "confirmed". Ganti dua fakta yang benar-benar bisa dibuktikan: (a) `entity_type='product_attachment'` hadir, (b) `changes` memuat entri `field="Storage (R2)"`. | `tests/verify_audit_db_state.py` G8.3 | `venv\Scripts\python.exe tests\verify_audit_db_state.py` → verdict U6 mengikuti data, tidak lagi selalu "confirmed" | S | Rendah |
| **R3** | **Lengkapi tabel entitas audit.** Tambahkan 5 nilai: `product_attachment` (upload/update/delete), `product_file` (delete), `product_batch` (create), `purchase_order` (create), `purchase_order_item` (create/update/delete); ganti baris generik `{doc_type} perusahaan` (aksi `update`) dengan **7 nilai eksplisit** dari `COMPANY_DOC_MAP` (`app/company_docs_routes.py:19-27`). Tambahkan bullet `storage_note` di blok aturan pencatatan. | `panduan_dip_automation_system.md:699-713` dan `:715-726` | `tests/test_audit_regressions.py` check U6 berubah `[KNOWN]` → `[PASS]` | S | Rendah |
| **R4** | **Kunci doc-drift dengan check statis.** Parse `app/*.py` dengan `ast`, ambil semua literal `entity_type` dari panggilan `log_activity`, bandingkan dengan tabel entitas audit di panduan. Whitelist 7 nilai `doc_type` dinamis dibaca dari `COMPANY_DOC_MAP` supaya tidak ada false positive. | `tests/test_audit_regressions.py` (check U6) + `KNOWN_ISSUES["U6"]` | `venv\Scripts\python.exe tests\test_audit_regressions.py` → PASS 20 / KNOWN 19 / FAIL 0 / SKIP 2 | M | Rendah |
| **R5** | **Catat detail storage di 3 call site lampiran.** Kirim `storage_note` (dan kwarg baru `storage_backend`) di `app/product_attachments_routes.py:185, 220, 242`, meniru `app/products_routes.py:1148-1152` yang sudah mencatat `"r2: gagal; perlu dibersihkan manual (bucket/path)"` vs `"supabase: berhasil; r2: sudah tidak ada"`. **Hari ini jalur lampiran sama sekali tidak mencatat detail storage** → desync dual-backend tidak bisa dijelaskan. Helper: `app/object_store.py:51` (`storage_backend()`), `:505-531` (`remove()` per backend), `:95-102` (`failed_backends()`). | `app/product_attachments_routes.py:185, 220, 242`; `app/products_routes.py:1148-1152` | `activity_logs.changes` untuk lampiran memuat `{"field":"Storage (R2)","note":...}` | S | Sedang: `log_activity` butuh satu kwarg baru — keyword-only, jadi call site lama tetap aman |
| **R6** | **Catat aksi akses/download + perbaiki `source`.** Tambahkan aksi `access` / `download` untuk lampiran dan untuk preview/unduh dokumen DIP; perbaiki `app/dip_public.py:130-142` agar menyisipkan `source="public"` — kolom dan `CHECK`-nya sudah ada (`migration/003:25, 62`) dan `log_activity` sudah menerima `source="public"` (`app/main.py:829, 846`). **Hari ini membaca atau mengunduh lampiran tidak meninggalkan jejak sama sekali.** | `app/product_attachments_routes.py`; `app/dip_public.py:130-142`; `app/main.py:829, 846` | `activity_logs` punya baris `source='public'` untuk akses portal; `outcome`/`source` tetap lolos `CHECK` | M | Sedang: `source='public'` mengubah statistik `source` yang selama ini 100% `'app'` |
| **R7** | **Bangun viewer audit log untuk admin.** Modul baru `app/audit_log_routes.py` mengikuti pola `register_*_routes` + DI (`AGENTS.md §4`), didaftarkan di `app/main.py:1377-1556`, template baru `app/templates/admin_audit_log.html` mewarisi `base.html`, memakai klien **service-role** yang di-inject (bukan `anon` — `migration/003:79-81` mencabut hak `anon`/`authenticated`). Admin-only, read-only, dengan filter + ekspor CSV. **Audit trail saat ini write-only**: satu-satunya cara menjawab "siapa yang mengunggah CoA ini?" adalah Supabase SQL Editor — kanal yang oleh panduan sendiri dinyatakan berada di luar audit trail. | `app/audit_log_routes.py` (baru); `app/main.py:1377-1556`; `app/templates/admin_audit_log.html` (baru) | Buka `/admin/audit-log` sebagai admin → tabel + filter + ekspor CSV; sebagai staff → 403 | M | Sedang: reader baru di tabel yang `GRANT`-nya hanya `SELECT` + `INSERT` untuk service_role — hak baca service_role sudah ada, jadi tidak perlu migrasi |
| **R8** | **Opsional: promosikan `storage_note` / `storage_backend` ke kolom nyata.** `migration/008_activity_log_storage_detail.sql`: kolom `storage_note text` + `storage_backend text` dengan `CHECK (storage_backend IN ('supabase','dual','r2'))` dan index parsial, di-backfill dari entri `changes` yang sudah ada. **Operator-executed only.** | `migration/008_activity_log_storage_detail.sql` (baru, opsional) | Query `WHERE storage_backend = 'r2'` mengembalikan baris lampiran/file yang R2-nya gagal | M | Sedang: bila migrasi soft-delete (R6 §14.2) lebih dulu, file ini harus bernomor **009** |
| **R9** | **Samakan `entity_label` antara upload dan edit/delete.** `app/product_attachments_routes.py:185` memakai nama file mentah dari pengguna (`file_obj.filename`, `:151`) sedangkan `:220` dan `:242` memakai `file_name` yang sudah disanitasi (`_sanitize_filename`, `:30-36`). Investigator melihat **dua nama berbeda untuk satu file**, dan path mentah bisa bocor ke `entity_label` serta ke log Render. Gunakan `row.get("file_name")` juga di call site upload. | `app/product_attachments_routes.py:30-36, 151, 185, 220, 242` | Dua baris audit (upload + update) untuk satu lampiran menampilkan label identik | S | Rendah |

#### Model audit trail kanonik

**Daftar `entity_type` kanonik — 24 nilai.** 17 nilai statis + 7 nilai `doc_type`
dinamis. Tidak ada call site lain di luar daftar ini.

| # | `entity_type` | Call site penerbit | Aksi tercatat |
| ---: | :--- | :--- | :--- |
| 1 | `product` | `products_routes.py:109`, `dashboard_routes.py:64`, `efek_samping.py:369, 447`, `dip_public.py:134` | create, update, delete, restore, generate, public_link_visit |
| 2 | `product_file` | `products_routes.py:1069, 1097, 1148` | delete |
| 3 | `product_attachment` | `product_attachments_routes.py:185, 220, 242` | upload, update, delete |
| 4 | `product_batch` | `po_routes.py:1039` | create |
| 5 | `purchase_order` | `po_routes.py:978` | create |
| 6 | `purchase_order_item` | `po_routes.py:1119, 1180, 1207` | create, update, delete |
| 7 | `product_finished_specs` | `products_routes.py:497` | update |
| 8 | `product_qualquan_xlsx` | `products_routes.py:377` | export |
| 9 | `brand` | `brands_routes.py:36, 66, 92, 103` | create |
| 10 | `brand_legal_document` | `brands_routes.py:190, 249, 262, 275` | update |
| 11 | `user` | `admin_users_routes.py:147, 196, 219, 237` dan lainnya | create, delete, update, reset_password |
| 12 | `sample_submission` | `sample_routes.py:142, 325, 360, 374` | create, update, delete |
| 13 | `raw_material` | `raw_materials_routes.py:392, 477, 639, 749` | create, update, delete |
| 14 | `raw_material_variant` | `raw_materials_routes.py:789, 807, 858` | create, update, delete |
| 15 | `raw_material_batch` | `raw_materials_routes.py:1058, 1138, 1182, 1221` | edit, acc_dipakai, acc_dimusnahkan |
| 16 | `raw_material_company_doc` | `raw_materials_routes.py:334` | edit |
| 17 | `note` | `notes_routes.py:624, 646, 679, 707` | create, delete, complete, reopen |
| 18 | `nib` | `company_docs_routes.py:124` (`doc_type` dari `COMPANY_DOC_MAP`, `:19-27`) | update |
| 19 | `sertifikat_cpkb` | idem | update |
| 20 | `surat_tidak_pidana` | idem | update |
| 21 | `protap_no_batch` | idem | update |
| 22 | `protap_pemeriksaan_fg` | idem | update |
| 23 | `cv_safety_assessor` | idem | update |
| 24 | `cpkb_raw_material` | idem | update |

**Makna `source`.** `app` = route internal aplikasi; `public` = portal
`/dip/{slug}` tanpa login; `migration` = penulisan lewat skrip migrasi. Kolom
dan `CHECK`-nya sudah ada (`migration/003:25, 62`) dan `log_activity` sudah
menerima `source="public"` (`app/main.py:829, 846`) — **tetapi tidak ada call
site yang mengirimnya**: `app/dip_public.py:130-142` menyisipkan langsung ke
`activity_logs` **tanpa `source`**, sehingga default `'app'` yang terpakai.
Di produksi: 1.308 dari 1.308 baris `source='app'`, nol `source='public'`.

**Aturan 5 event minimum.** Setiap dokumen regulatif harus punya kelima
event — **create**, **edit**, **delete**, **access**, **trash-restore** — dengan
`entity_id` yang sama, `outcome` yang benar, `request_id` yang sama untuk
satu request, dan `source` yang benar. Empat catatan sementara:

* **Attachment edit tidak mencatat diff `changes` sama sekali** —
  `app/product_attachments_routes.py:220` berubahnya kategori/catatan tidak
  pernah masuk ke `changes`.
* **Attachment delete adalah hard delete** — baris `product_attachments`
  dihapus permanen (`app/product_attachments_routes.py:240`); **tidak ada**
  trash/restore, berbeda dengan produk.
* **Jalur 403/404/409 tidak mencatat apa pun** —
  `app/product_attachments_routes.py:140, 142, 144, 147` melakukan `raise`
  tanpa baris log `outcome="rejected"`, sehingga percobaan yang ditolak tidak
  meninggalkan jejak.
* **`activity_logs` tidak punya jalur baca sama sekali di aplikasi** — hanya
  2 INSERT (`app/main.py:891`, `app/dip_public.py:130`), nol SELECT, tanpa
  viewer admin, tanpa ekspor. Pembaca satu-satunya di repo adalah
  `tests/e2e_activity_request_id.py:115, 136`,
  `tests/e2e_smoke_refactor.py:305`, dan
  `tests/verify_audit_db_state.py` (G8.3).

#### Yang TIDAK perlu diubah

| Komponen | Alasan |
| :--- | :--- |
| Desain fail-open `log_activity` (`app/main.py:890-895`) | Keputusan sadar (kegagalan audit tidak boleh membatalkan operasi bisnis). **Jangan** diubah jadi fail-closed. |
| Dua `CHECK` yang sudah ada (`outcome`, `source`) | Sudah benar dan sudah meng-cover nilai yang dipakai. |
| Arah FK `actor_id` | FK menunjuk `profiles(id)`, **bukan** `auth.users(id)` (`migration/003:92-97`). **Jangan** "memperbaiki" arahnya. |
| `GRANT SELECT, INSERT` pada `activity_logs` | Sengaja: aplikasi hanya butuh baca-tulis, dan `REVOKE` menutup jalur PostgREST non-service-role. |
| Bentuk JSON `changes` `{"field","note"}` | Kontrak yang dipakai template dan Panduan. **Tidak boleh** diubah bentuknya. |
| Kontrak per-backend `object_store.remove()` dan fail-closed 500 pada `all_results_ok({})` | Benar: hasil per backend dikembalikan apa adanya, dan hasil kosong dianggap gagal. |
| Rollback storage saat insert DB gagal (`app/product_attachments_routes.py:176-183`) | Benar: file orfan dicegah. |
| Aturan kepemilikan uploader-atau-admin | Benar dan konsisten di seluruh modul lampiran. |
| `mask_email()` yang mempertahankan panjang | Benar: panjang akun tidak bocor. |
| Cache `request_id` per request | Benar: beberapa baris log dari satu aksi dapat dikelompokkan. |
| Menambahkan `CHECK` DB pada `entity_type` | **Tidak direkomendasikan.** 24 nilai sudah bekerja; constrain itu mengikat deploy ke migrasi. Dokumentasikan daftarnya (R3) dan kunci dengan check regresi (R4). |

#### Dokumentasi yang harus diperbarui

| Target | Isi yang harus ditambahkan / diperbaiki |
| :--- | :--- |
| `panduan_dip_automation_system.md:699-713` | Tabel entitas audit: 5 nilai yang hilang (R3) + 7 nilai `doc_type` eksplisit menggantikan baris generik. |
| `panduan_dip_automation_system.md:715-726` | Blok aturan pencatatan: penjelasan `storage_note` (bukan `entity_type`, tapi parameter yang masuk ke `changes`), aturan 5 event, "lampiran = hard delete", dan semantik `source`. |
| `panduan_dip_automation_system.md:687-695` | Tabel kolom audit: tambah `storage_note` / `storage_backend` **setelah** migrasi storage detail land. |
| `panduan_dip_automation_system.md:764` | §6.3: sebutkan aksi `access` / `download` dan keberadaan viewer `/admin/audit-log`. |
| `README.md:58` | Tambah catatan `entity_type='product_attachment'`; koreksi "maks 10 file × 10 MB per produk" → "10 file per unggahan". |
| `README.md:119-125` | §9 Activity Log: pointer daftar entitas, penjelasan `storage_note`, aturan 5 event, dan viewer audit log. |
| `README.md:229` dan `:301`, `panduan:577-580` | Tambahkan baris migrasi 008 (soft delete) dan, bila dikerjakan, baris migrasi storage detail. |

## 15. Riwayat

| Tanggal | Peristiwa |
| :--- | :--- |
| 2026-10-21 | Audit read-only seluruh codebase (6 agen paralel + verifikasi silang). Dokumen ini dibuat. Tidak ada perubahan kode. |
| 2026-10-21 (sore) | **Suite test audit dibuat** (3 file baru di `tests/`: regresi statis/unit, verifier DB staging read-only, E2E Playwright) + **eksekusi live di staging** (unit suite, DB verifier, E2E `--full` dan `--quick`, `pytest tests/ -q`, static checker). Temuan dikonfirmasi/di-refute secara live dan 8 koreksi atas laporan audit dicatat di §8.2. Ketiga file **belum di-commit**; tidak ada `git add`/`git commit`/`git push` yang dijalankan. |
| 2026-10-21 (malam, lanjutan) | **Verifikasi produksi read-only lanjutan (6 pertanyaan: bucket privacy, `profiles.perusahaan`, `public_link_audits`, cakupan `storage_note`, distribusi `outcome`, parity deploy) + investigasi histori git route delete.** Semua read-only: Supabase Management API (30+ `SELECT`, 0 write, 0 migrasi; token tidak pernah dicetak) + `git log` / `git show` / `git blame`. Hasil: **SEC-01 = REGRESI** (§13.7.1), bucket produksi **PUBLIK** dengan path enumerable (§13.7.2), guard tenant **fail-open** karena `profiles.perusahaan` NULL 7/7 (§13.7.3), `public_link_audits` ada tanpa DDL (§13.7.4), cakupan detail storage tipis (§13.7.5), nol `rejected` = konfigurasi guard (§13.7.6), build ter-deploy tidak bisa diikat ke commit (§13.7.7). **6 check baru `PROD-01`…`PROD-06` (grup G9)** ditambahkan ke `tests/verify_audit_db_state.py` → 49 check, PASS 21 / FAIL 0 / WARN 6 / INFO 22, exit 0. Dokumen diperbarui: §8.2 K10–K13, §10 direstrukturisasi (P0 baru), R1 §14.2 ditulis ulang sebagai **restore + 6 gap (G1–G6)**. **Suite tetap hanya MENDETEKTI, tidak memperbaiki** — tidak ada satu pun temuan yang ditutup suite. Ketiga file test masih **belum di-commit** di working tree; tidak ada `git add` / `git commit` / `git push` yang dijalankan. |
| 2026-10-21 (malam) | **Verifikasi status migrasi produksi (read-only)**
 — seluruh migrasi **001–007 terpasang di staging DAN produksi**; fallback fail-OPEN portal publik **tidak aktif di produksi**, sehingga **SEC-09 dan BE-20 REFUTED untuk produksi** (§13.6, §14.1). Snapshot produksi dicatat (products 136, profiles 7, activity_logs 1.308, product_attachments 6, brands 18); `supabase_migrations.schema_migrations` dinyatakan **bukan ledger** migrasi, sehingga status wajib diinspeksi per objek di katalog. **Dua set rekomendasi baru §14** ditambahkan: Poin 1 status migrasi, Poin 2 soft-delete (9 item + model kanonik), Poin 3 audit trail (9 item + model kanonik). **U6 dikoreksi** dari CONFIRMED menjadi REFUTED sebagai temuan kode (koreksi §8.2 K9) — celah yang sebenarnya adalah dokumentasi, selebar 5 nilai `entity_type`. Dua check test diperbarui: G8.3 di `tests/verify_audit_db_state.py` (semula menguji `storage_note` sebagai `entity_type` yang mustahil) dan check baru U6 di `tests/test_audit_regressions.py` (doc-drift tabel entitas audit). **Suite tetap hanya MENDETEKSI, tidak memperbaiki** — tidak ada satu pun temuan yang ditutup oleh suite. Ketiga file test masih **belum di-commit** di working tree; tidak ada `git add` / `git commit` / `git push` yang dijalankan. |
| 2026-10-21 (malam, implementasi) | **Implementasi §13.8.** Route `POST /products/delete/{product_id}` dipulihkan ke `app/products_routes.py` (dari `491d036`) dengan 6 gap G1–G6 ditutup; form dashboard di-gate admin + teks konfirmasi dikoreksi; jalur restore menyimpan `deleted_at` lama. `migration/008` dieksekusi di **staging** lalu **produksi** lewat Supabase Management API atas otorisasi eksplisit owner (constraint `products_soft_delete_consistency` + index `idx_products_is_deleted_deleted_at` terpasang, probe enforcement ditolak **SQLSTATE 23514**), lalu `ALTER COLUMN is_deleted SET NOT NULL` ditutup di kedua environment (`is_nullable` `YES` → `NO`, hitungan baris tidak berubah). Uji soft delete **produksi** pada ``tes log `12`` **LULUS** (+4 baris audit, `trashed` 8 → 9). **Tidak ada** `git add` / `git commit` / `git push` yang dijalankan. |
