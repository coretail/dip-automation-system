# Catatan Audit Codebase — DIP Automation System (2026-10-27)

## Status Dokumen

**Audit READ-ONLY.** Tidak ada file kode yang diubah, dibuat, dihapus, atau di-commit
selama audit. `git status` bersih sebelum dan sesudah. Tidak ada secret yang dibaca
atau dicatat.

> Satu-satunya file yang dibuat sesi ini adalah dokumen ini (atas permintaan eksplisit
> pemilik repo untuk mencatat hasil audit).

| Item | Nilai |
|---|---|
| Repo | `D:\dip-app` |
| Tanggal audit | 2026-10-27 |
| Commit `main` yang diaudit | **`c0035ee`** — "fix(storage): preserve presigned preview URLs" (2026-10-26) |
| `git pull` | Already up to date |
| Metode | 7 agen paralel read-only (A Security/XSS, B Frontend polling, C Backend, D Docs vs impl, E Storage/R2, F DIP publik, G CI/deps) + verifikasi manual atas 6 temuan yang sudah diketahui |
| Checker statis dijalankan | `scripts/check_undefined_names.py` → **exit 0** (24 file); `scripts/check_static_rules.py` → **exit 0** (via `venv\Scripts\python.exe`; `python` global tidak ada di PATH) |
| Di luar cakupan / tidak dibaca | `.env*`, `LOGIN.md`, `backup-rls/` (kecuali 20 baris definisi `activity_logs` dari `backup-rls/dip_public_schema_2026-10-14.sql:43-67` untuk bukti tipe kolom `entity_id uuid`), `venv/`, `migration/verify_r2_readiness.py` (tidak ter-track git) |

### Klasifikasi Temuan

| Label | Arti |
|---|---|
| **CONFIRMED** | Kode dibaca langsung; jalur eksekusinya nyata dan dapat ditelusuri (kutipan baris disertakan). |
| **POTENTIAL** | Mekanisme masuk akal, tetapi bergantung pada kondisi runtime/data yang tidak dapat diverifikasi tanpa server/database. |
| **OBSERVATION** | Bukan kerentanan; catatan konsistensi, kebersihan kode, atau penyimpangan kecil. |

---

## 1. Ringkasan Eksekutif

Codebase dalam kondisi **sehat-fungsional dan membaik sejak audit 2026-10-21**.
Perbaikan H3.1–H3.7 (formula transaksional via RPC `replace_product_formula`,
kejujuran hasil write, cleanup upload batch, `warning_msg` dirender) dan restore
route soft-delete terverifikasi land di `main`. Fix cache-bust presigned
(`c0035ee`) juga sudah di `main` — bukan lagi hanya di branch.

Yang masih bermasalah:

1. **Jalur publik masih punya satu blok fail-open** — fallback `_dip_public_check_product`
   (`app/dip_public.py:297–303`) melewati seluruh cek token saat query pertama melempar
   exception apa pun (termasuk error transient Supabase post-migrasi 007).
2. **Jejak audit gagal diam-diam** — `entity_id` non-UUID (nama perusahaan, `"-"`)
   membuat baris `activity_logs` gagal cast UUID dan tertelan oleh fail-open
   `log_activity`; seluruh update dokumen legal perusahaan tidak pernah tersimpan di DB.
3. **Kesenjangan tooling/dokumen migrasi R2 vs kode** — semantik mode `dual` di kode
   fail-loud (berlawanan dengan klaim "best-effort" di catatan handoff), audit storage
   buta R2, gerbang cutover (`verify_r2_readiness.py`) tidak ter-track git, dan ada
   asimetri encoding `%20` yang bisa menghasilkan orphan "sukses palsu".
4. **Default konfigurasi fail-open menuju produksi** — menjalankan `uvicorn app.main:app`
   tanpa `DIP_APP_ENV` memuat `.env` produksi tanpa preflight apa pun.
5. **Hulu dokumen tertinggal** — AGENTS.md stale soal nomor migrasi (repo sudah 010,
   "berikutnya 009" salah; 009 tidak ada), README/panduan tidak mendokumentasikan
   `STORAGE_BACKEND`/R2 dan model token publik, tabel migrasi hanya 001–004.

**Tidak ada temuan KRITIS baru.**

---

## 2. Arsitektur yang Dipahami

- **Entry point**: `app.main:app` (FastAPI, tanpa middleware). `app/main.py` (1.567 baris)
  membangun app, auth cookie JWT (Supabase Auth), `log_activity`, 3 filter Jinja global,
  lalu memanggil **14 modul `register_*_routes`** (`app/main.py:1377–1556`): dashboard,
  company_docs, products, brands, sample, presence, admin_users, notes, efek_samping,
  raw_materials, po, product_attachments, dip_documents (butuh login), dip_public
  (tanpa login). Dependency di-inject eksplisit; tidak ada modul yang mengimpor `main`.
- **Database**: satu klien Supabase global service-role (RLS dilewati) — `app/database.py`.
- **Storage**: semua akses terpusat di `app/object_store.py` (551 baris), backend
  `supabase | dual | r2` (`STORAGE_BACKEND`).
- **Alur DIP**: bahan baku + batch per perusahaan (PT Erfi / PT Heka) → formula
  (`product_formula_lines`, tulis via RPC transaksional `replace_product_formula`
  dari migrasi 010) → generator Bab I–IV (`app/dip_documents.py`, xhtml2pdf + pypdf)
  → portal publik `/dip/<slug>-<uuid>?access=<token>` untuk verifikator BPOM,
  ter-audit di `public_link_audits`.
- **Frontend**: Jinja2 + Tailwind browser CDN + vanilla JS (presence 25 dtk, mention
  30 dtk, admin presence 15 dtk, ED sekali-buka + saat dropdown dibuka).
- **Staging**: `DIP_APP_ENV=staging` + guard fail-closed (`app/staging_guard.py`,
  `app/staging_preflight.py`, launcher `scripts/run_staging_8017.py`, 127.0.0.1:8017).
- Tidak ada route duplikat (`check_static_rules.py` memverifikasi dari tabel routing final).
- Klien Supabase sinkron masih dipanggil di `async def` (warisan FE-01 — memblokir
  event loop; tidak diaudit ulang mendalam sesi ini).

---

## 3. Temuan Security (Audit A + F)

### 3a. Status temuan lama (audit 2026-10-21) di `main`

| ID | Temuan | Status | Risiko | Lokasi |
|---|---|---|---|---|
| SEC-01 | Route soft-delete hilang (regresi) | **FIXED** | — | `app/products_routes.py:298` (`POST /products/delete/{product_id}`, admin-only) |
| SEC-06 | Nol token CSRF pada 40+ POST | **TERBUKA** — CONFIRMED | Tinggi | seluruh `app/` (grep `csrf` = 0). `SameSite=Lax` adalah mitigasi utama; tidak ada defense-in-depth. → token CSRF atau cek `Origin`/`Sec-Fetch-Site` |
| SEC-07 | Nol security header (CSP, X-Frame-Options, dll.) | **TERBUKA** — CONFIRMED | Sedang | `app/main.py` (tanpa middleware) |
| SEC-08 | Open redirect via `Referer` pada handler 413 | **TERBUKA** — CONFIRMED | Sedang | `app/main.py:1198–1203` (substring `"/edit"` lolos `Referer: https://evil.com/phish/edit`) |
| SEC-12 | CDN tanpa SRI; Tailwind Play v3 di halaman pra-auth & publik | **TERBUKA** — CONFIRMED | Sedang | `login.html:7`, `public_error.html:7`, `base.html:49`, `dip_public_hub.html:7`, `po_analytics.html:386` |
| SEC-13 | `tanggal_ed` tak di-escape ke `innerHTML` | **TERBUKA** — CONFIRMED | Sedang | `base.html:291` (sumber `presence_routes.py:117`; bypass parse mungkin: `2099-01-01<img ...>`) |
| SEC-14 | 5 implementasi `escapeHtml` (bertambah dari 4) | **TERBUKA** — CONFIRMED | Rendah | `base.html:347`, `notes.html:427`, `raw_materials.html:1311,2161`, `edit_product.html:822` |
| SEC-15 | `greeting_cache` cookie unsigned | **TERBUKA** — CONFIRMED | Rendah | `app/main.py:1128–1134`; render `dashboard.html:26–30` |
| SEC-16 | `/logout` via GET (CSRF logout) | **TERBUKA** — CONFIRMED | Rendah | `app/main.py:1143` |
| SEC-18 | Artefak `omniroute` sebelum `{% extends %}` | **TERBUKA** — CONFIRMED | Rendah | `app/templates/brands.html:1` |

### 3b. Temuan baru Audit A

| ID | Temuan | Klasifikasi | Risiko | Lokasi | Skenario kegagalan | Rekomendasi |
|---|---|---|---|---|---|---|
| SEC-19 | Cookie sesi & flash tanpa `secure=True` | CONFIRMED | Sedang | `app/main.py:1121–1127`; flash cookies di puluhan call site | JWT dikirim bila ada jalur HTTP (misconfig proxy) | `secure=True` (+ pertimbangkan `__Host-`); `httponly/samesite/secure` untuk flash cookies (SEC-20, Rendah) |
| SEC-21 | `_client_ip` percaya `X-Forwarded-For` hop pertama | POTENTIAL (jika proxy tidak menimpa XFF) | Sedang | `app/main.py:326–336,342` | Bypass rate limit login 5/menit + IP audit palsu | Trusted proxy eksplisit (`--proxy-headers` + `ProxyHeadersMiddleware`) |
| SEC-22 | Upload MSDS/Spec inline fail-open tanpa pesan per-file | CONFIRMED | Rendah | `app/main.py:41–61` | File non-PDF di-skip diam-diam; tidak pakai `validate_pdf_bytes` | Pakai helper terpusat + lapor error per-file |
| SEC-24 | `openDocPreview()` tidak lolos `safeDocUrl()` | POTENTIAL | Rendah | `raw_materials.html:1950–1954` | Butuh URL berbahaya di DB (`javascript:`) | Whitelist juga di modal preview |

**Pemeriksaan nihil terverifikasi** (bukan "tidak ditemukan"): `|tojson` konsisten di
semua sink; `body_html|safe` di notes ter-escape server-side dengan urutan benar
(`_render_note_html`, `app/notes_routes.py:118–194`); 0 `eval`/`document.write`/
`autoescape false`; dari 52 `innerHTML`, hanya 1 interpolasi tak-ter-escape (SEC-13);
validasi `%PDF` + 10 MB terpusat dan konsisten (termasuk `read(MAX_SIZE+1)`).

### 3c. Temuan Audit F — Akses Publik `/dip/*`

Semantik checker (`app/dip_public.py:277–303`): produk `is_deleted` / `public_access_enabled=False`
ditolak; produk bertoken menuntut `?access=` persis **kecuali** `bpom_registered_link=true`
(jalur legacy yang disengaja); token NULL → akses tanpa token (`return True`).

| ID | Temuan | Klasifikasi | Risiko | Lokasi | Skenario kegagalan | Rekomendasi |
|---|---|---|---|---|---|---|
| F-01 | Fallback `except Exception` **fail-open** (tanpa cek token) | CONFIRMED | Tinggi | `app/dip_public.py:297–303` | Error transient Supabase (timeout, 5xx, rate limit) pada query pertama → akses publik hanya dengan UUID | Fail-closed (`return False`); deteksi eksplisit PGRST204 saja bila butuh kompatibilitas pre-007 |
| F-03 | `public_access_revoked_at` **tidak pernah dibaca/di-set** kode | CONFIRMED | Sedang | `migration/007:8` (kolom ada); tidak di checker; grep `app/` = 0 penggunaan | Revoke tidak fungsional; token "dicabut" tetap valid selamanya | Cek `revoked_at` di checker + route admin revoke/rotasi token |
| F-09 | Route bab1–4/download/ZIP **tidak memanggil** `_audit_public_link`; audit tanpa `source`/jenis akses | CONFIRMED | Sedang | `app/dip_public.py:100–144,173–179` | Dokumen inti bisa diunduh tanpa jejak di `public_link_audits`; akses valid-token vs legacy tak terbedakan | Audit di semua route download + flag jenis akses/status token |
| F-04 | Produk NULL-token → akses tanpa token; fallback insert bisa menghasilkan produk tanpa token | CONFIRMED | Sedang | `app/dip_public.py:296`; `app/products_routes.py:280–284` | Hanya relevan di env pre-007 | Hapus fallback setelah 007 terkonfirmasi semua env |
| F-02 | Token di query string → access log uvicorn, history browser, Referer | CONFIRMED | Sedang | `app/dip_public.py:154,330–395`; filter log `app/main.py:346–376` (`/dip/*` tidak di `SKIP_PATHS`) | Token 256-bit tercatat penuh di log | Sanitasi query di log `/dip/*`; `Referrer-Policy: no-referrer` |
| F-06 | Referer leakage tanpa mitigasi eksplisit | POTENTIAL | Rendah | `dip_public_hub.html` (tanpa `<meta name="referrer">`) | Browser default `strict-origin-when-cross-origin` menutup sebagian besar; bergantung default browser | `<meta name="referrer" content="no-referrer">` + header |
| F-07 | Perbandingan token `==` (bukan timing-safe) | CONFIRMED | Rendah | `app/dip_public.py:289` | Timing attack teoretis; entropi 192–256 bit menutup praktisnya | `hmac.compare_digest` |
| F-08 | Nol rate limit di `/dip/*` (generator PDF/ZIP mahal) | CONFIRMED | Rendah | `app/main.py:1050` (slowapi hanya `/login`) | DoS resource / scraping jika token bocor; `traceback.print_exc()` spam | Rate limit per-IP pada prefix `/dip/` |
| F-11 | Hub publik menampilkan kode internal bahan baku + nama customer | CONFIRMED | Rendah | `dip_public_hub.html:66–84,137–140` | Konsisten dengan isi PDF Bab II; formula/batch tidak dirender | Sembunyikan `m.kode` bila dianggap rahasia komersial; `rel="noopener noreferrer"` |

**Positif (Audit F)**: cek token konsisten di semua 11 route (hub, bab1–4 + download, ZIP);
semua kondisi gagal → 404 identik (tanpa oracle keberadaan); signed URL fail-closed
(`_storage_signed_url` → `None`); produk soft-deleted ditolak; migrasi 007 backfill
token 192-bit + unique partial index.
**Token format**: backfill = hex 48 karakter; produk baru = `token_urlsafe(32)` 43 karakter —
keduanya valid.

---

## 4. Temuan Frontend (Audit B)

| ID | Temuan | Klasifikasi | Risiko | Lokasi | Alur eksekusi | Rekomendasi |
|---|---|---|---|---|---|---|
| FE-B01 | **Baru** — Polling mention 30 dtk tidak di-skip saat tab hidden | CONFIRMED | Sedang | `base.html:390–397` | Tab background → request tetap terkirim (±60/jam/tab; Chrome throttle ke ±1/menit) + spam `[SESSION EXPIRED]` di server setelah sesi mati | Skip saat `visibilityState === 'hidden'` (samakan pola `admin_users.html:361–363`) |
| FE-04 | bfcache mematikan heartbeat permanen | CONFIRMED (unchanged) | Sedang | `presence.js:88–101` | `pagehide` stop interval → kembali dari bfcache tanpa `pageshow` → interval tak pernah dibuat ulang → Offline palsu setelah 90 dtk | Listener `pageshow` + refactor `startHeartbeat()` |
| FE-05 | Logout sidebar tidak stop heartbeat | CONFIRMED (unchanged) | Sedang | `_sidebar.html:115` vs `base.html:169–171` | Heartbeat in-flight (`keepalive: true`) bisa menulis `is_online=true` pasca-logout | Handler `stopPresenceHeartbeat` di link sidebar |
| FE-06 | `window.__adminPresenceInterval` tak pernah di-assign | CONFIRMED (unchanged) | Rendah | `admin_users.html:326` vs `base.html:44` | Cleanup di `handleSessionExpired` = dead code | Assign ke window |
| FE-12 | Quick-add fetch tak menangani redirect sesi | CONFIRMED (unchanged) | Rendah | `edit_product.html:1144–1148`; `dashboard.html:712–716` | `response.json()` melempar pada HTML login → "error sistem" palsu | Panggil `handleSessionRedirect` sebelum `.json()` |
| FE-13 | `handleSessionRedirect` tanpa guard anti-loop | CONFIRMED (unchanged) | Rendah | `base.html:29–36` | Dua poller redirect hampir bersamaan (harmless saat ini, tidak idempotent by design) | Guard `__sessionExpiredHandled` |
| FE-07/08 | Countdown login tidak menjaga submit form; 60 dtk hardcoded | CONFIRMED (unchanged) | Rendah | `login.html:105–128` | Submit via Enter bisa menembus limiter (tergantung browser); UI 60 dtk ≠ jendela limiter | Guard di `handleLoginSubmit`; sisa waktu dari server |
| FE-09 | `loadRowVariants` tanpa `AbortController` | CONFIRMED (unchanged) | Rendah | `edit_product.html:837–873` | Respons out-of-order menimpa dropdown varian; tanpa penanganan sesi | AbortController per-baris |
| FE-10/11 | Listener aktivitas tak di-throttle (kecuali mousemove); `ping()` tanpa in-flight guard | CONFIRMED (unchanged) | Rendah | `presence.js:27–49,68–78` | Churn timer per-frame saat scroll; heartbeat paralel saat jaringan lambat | Throttle seragam 1 dtk + flag in-flight |
| FE-B02–B05 | Cabang 401 di `ping()` praktis dead code (server meng-303 semua 401 via `main.py:1187–1190`); `handleSessionExpired` tak clear `notesVisibilityTimer`; lampiran.js menandai job "error" saat sesi habis | OBSERVATION | Rendah | `presence.js:43–47`; `base.html:39–46`; `lampiran.js:99,107` | Kosmetik/konsistensi | Konsolidasi helper penanganan sesi |
| FE-14/15/16/17 | Mention polling di semua halaman; tab hidden → Offline bukan Idle; admin presence tak sinkron daftar; filter log 5 path vs dok "4" | OBSERVATION (unchanged) | Rendah | `presence.js:84`; `admin_users.html:343–346`; `main.py:353–359` | — | — |

**Positif (Audit B)**: tepat 4 `setInterval` di seluruh app (tidak ada duplikasi); keempat
poller utama menangani `response.redirected` + cleanup interval dengan benar; tidak ada
loop redirect; tidak ada polling di halaman publik/login; `lampiran.js` murni DOM API
(tanpa innerHTML).

**Verifikasi fix `c0035ee`**: guard presign di `bust()` (`base.html:430`,
`/[?&](X-Amz-Signature|X-Amz-Algorithm|token)=/i`) utuh di `main` dan punya test
(`tests/test_base_cachebust.py`) — tetapi test itu **tidak dijalankan CI** (G-1), dan
selector `<a>` cache-bust (`base.html:438`) tidak akan match URL `pub-*.r2.dev`
pasca-cutover (E-07b).

---

## 5. Temuan Backend (Audit C)

| ID | Temuan | Klasifikasi | Risiko | Lokasi | Skenario kegagalan | Rekomendasi |
|---|---|---|---|---|---|---|
| TYPE-01 | **`entity_id` non-UUID → baris audit gagal diam-diam** | CONFIRMED | Sedang | `app/company_docs_routes.py:124` (nama perusahaan), `app/notes_routes.py:614,666` (`"-"`), `app/raw_materials_routes.py:1469` (`batch_id or "-"`) | Cast `activity_logs.entity_id uuid` gagal → tertelan fail-open `log_activity` (`main.py:890–895`) → **seluruh jejak audit update dokumen legal (NIB/CPKB/dll.) tidak pernah tersimpan di DB**, hanya print terminal | Standarkan UUID/`None`; tambah test per call site |
| BE-04 | `.single()` di luar try — 5 lokasi aktif + 1 query halaman | CONFIRMED | Sedang | `raw_materials_routes.py:695,915,1085,426`; `products_routes.py:481,743` | UUID invalid/tak ada → PGRST116/cast error → 500 mentah | Bungkus try / pola `.limit(1)` + cek `data` |
| BE-08 | `str(e)` bocor — tepat 9 lokasi (5 ke user, 4 ke `activity_logs`) | CONFIRMED | Sedang | `main.py:1359`; `raw_materials_routes.py:678,872,2072,2111`; `sample_routes.py:166,309`; `brands_routes.py:107,279` | Detail PostgREST (kolom/constraint) tampil ke user / tersimpan permanen | Pola `products_routes` (pesan aman + detail ke log server) |
| BE-14 | Tenant check FSP: update 403 terselubung jadi 404; **delete fail-open** | CONFIRMED (delete) | Sedang | `sample_routes.py:236–248,340–357` | Pre-read gagal → `old_row={}` → cek tenant dilewati → staff perusahaan A bisa menghapus pengajuan perusahaan B saat gangguan jaringan | Fail-closed pada pre-read; pisahkan try tenant-check |
| BE-05 | Akun auth yatim saat `profiles.insert` gagal setelah `create_user` | CONFIRMED | Sedang | `admin_users_routes.py:118–135` | Email terblokir "already registered" selamanya; akun tak terlihat di `/admin/users` | Kompensasi `auth.admin.delete_user(new_uid)` |
| BE-06 | Kegagalan staging guard di login → `invalid_credentials` | CONFIRMED | Sedang | `main.py:1068 → 1137` | `HTTPException(500)` tertangkap `except Exception` → diagnosis menyesatkan | `except HTTPException: raise` sebelum `except Exception` |
| BE-12/13 | Nol password policy saat create user; input login mentah dicetak ke log | CONFIRMED | Rendah/Sedang | `admin_users_routes.py:118,195`; `main.py:1140` | Password 1 karakter diterima; PII di log Render | Validasi min-6 di create; pakai `mask_email()` |
| BE-17 | `.or_()` pencarian FSP tanpa `_sanitize_ilike` | CONFIRMED | Sedang | `sample_routes.py:398–400` | Input dengan koma/paren menyuntik filter PostgREST (service-role, RLS dilewati) | `_sanitize_ilike` (pola sudah ada di `notes_routes.py:235`, `po_routes.py:29–30`) |
| TRX-01 | Rangkaian multi-tabel tanpa transaksi | CONFIRMED | Sedang | `raw_materials_routes.py:983–1057,1120–1126,1185–1188`; `sample_routes.py:102–113,265–274` | Gagal di tengah edit bahan baku → komponen INCI terhapus permanen tanpa rollback; producer yatim | RPC transaksional seperti `migration/010` |
| RACE-01 | Check-then-insert (PO/batch/kode bahan); retry urutan item berbasis teks error | POTENTIAL | Rendah | `po_routes.py:963–1116`; `raw_materials_routes.py:758–767` | Klik ganda → 500/duplikat; deteksi teks gagal menangkap `23505` | Klasifikasi `APIError.code == "23505"`; unique constraint; upsert/RPC |
| VAL-01 | Validasi input lemah (tanggal mentah, enum bebas, `sections_json` tak divalidasi) | CONFIRMED | Sedang | `raw_materials_routes.py:1252–1257,2072`; `sample_routes.py:53–137`; `products_routes.py:768–775` | Input salah → 500 generik; data liar masuk bila constraint DB longgar | Helper `_parse_opt_date` (`po_routes.py:51–61`) + whitelist enum |
| DATA-01 | Restore produk tanpa guard `is_deleted=True` / cek 0-baris | CONFIRMED | Rendah | `dashboard_routes.py:61–78` | Restore produk tak ada/sudah aktif → "berhasil" + audit success palsu | Samakan kontrak dengan delete (`products_routes.py:357–376` sudah benar) |
| AI-01/02 | Gemini ±12 dtk worst-case di jalur login; API key via query string; `full_name=NULL` → `'{None}'` di prompt | CONFIRMED | Rendah | `main.py:203–219,1112,1115` | Login menunggu 3×4 dtk saat Gemini down | Background task; header `x-goog-api-key`; `or "Kamu"` |
| OBS-01/02/03 | `log_activity` fail-open tanpa validasi UUID; kontrak error campuran (JSON mentah ke form browser); tenant check hanya di 4 modul (`assert_same_tenant` = dead code) | OBSERVATION | Sedang (tenant) | `main.py:826–895`; `raw_materials_routes.py:900,910,1159`; `security.py:9` | Mismatch tipe tak berisikan; 403/404 JSON mentah; `profiles.perusahaan` NULL = guard tak pernah menolak (warisan audit 2026-10-21 §13.7.3, tak terverifikasi ulang tanpa akses DB) | Konvensi error; pasang guard tenant + isi `profiles.perusahaan` |

**Fixed terkonfirmasi di `main` (verifikasi ulang)**: BE-01/02/03/15/16 (kejujuran hasil
write, H3.1–H3.5), BE-10/11 (cleanup upload batch dengan klasifikasi exception +
rekonsiliasi ambigu, H3.2/3.3/3.7), BE-21 (`warning_msg` dirender `base.html:188–216`),
BE-25 sebagian besar. Jalur formula kini lewat RPC transaksional (migrasi 010).

---

## 6. Temuan Storage/R2 dan Kesiapan Cutover (Audit E)

**Semantik per mode** (`app/object_store.py`):

| Operasi | `supabase` | `dual` | `r2` |
|---|---|---|---|
| `upload_pdf` | Supabase | **R2 dulu (gagal = raise), lalu Supabase**; return = Supabase; rollback R2 hanya non-upsert | R2 (fail-loud kredensial) |
| `public_url` | Supabase | Supabase | `R2_PUBLIC_BASES` (RuntimeError bila bucket tak terdaftar); path di-quote `%20` |
| `signed_url(s)` | Supabase batch | Supabase | presigned per-path, fail-open (`None`) |
| `remove` | Supabase | hapus keduanya; gagal hanya log `storage_repair` (kecuali `product_attachments` yang menuntut kedua backend sukses) | R2 |

| ID | Temuan | Klasifikasi | Risiko | Lokasi | Skenario kegagalan | Rekomendasi |
|---|---|---|---|---|---|---|
| E-02 | Mode `dual` **fail-loud** — kontradiksi dengan catatan handoff ("R2 best-effort, request tetap sukses") | CONFIRMED | Tinggi | `object_store.py:402–407` vs `catatan/catatan_handoff_migrasi_r2.md:35–37` | R2 outage → SEMUA upload gagal meski Supabase sehat; kriteria soak "storage_repair kosong" tidak menguji resiliensi; env R2 kurang di prod `dual` → RuntimeError tiap tulis | Putuskan: perbaiki dokumen atau ubah urutan dispatch; test simulasi R2 gagal |
| E-05 | Asimetri encoding path: `_r2_public_url` quote `%20`, `parse_storage_url` tak unquote, `backfill.build_url` tak quote | CONFIRMED | Sedang | `object_store.py:374,183–220`; `backfill_r2_urls.py:132–134,246` | Key ber-spasi: remove/presign menarget key ter-encode → **orphan "sukses palsu"** (delete key salah tetap "ok"); URL backfill vs upload baru beda bentuk → pencocokan referensi gagal | Kanon: key=raw, URL=encoded; unquote di parser; unit test roundtrip remove/presign |
| E-10 | `audit_storage.py` buta R2 (hanya listing Supabase); tabel salah ketik → skipped + exit 0; `unquote` ganda menyamarkan mismatch | CONFIRMED | Sedang | `audit_storage.py:65–100,170–181` | Pasca-cutover tak ada tooling ter-track yang memverifikasi DB vs R2; drift dual tak terdeteksi | Mode `--side r2` via boto3; MISSING>0 = exit non-zero |
| E-11 | Pre-check backfill hanya atas baris yang berubah; `exists()` menelan semua exception | CONFIRMED | Sedang | `backfill_r2_urls.py:136–141,221,241–256` | Baris "sudah di target" tak di-HEAD → objek hilang tetap lapor "APPLIED sukses" (false PASS cutover) | Pre-check seluruh (bucket,path); laporkan "already-at-target but missing" |
| E-12 | **`migration/verify_r2_readiness.py` tidak ter-track git** | OBSERVATION | Sedang | `.gitignore:76–82`; `git log --all` kosong | Gerbang cutover tak auditable/tak bisa direproduksi | Commit dengan rahasia via env-var |
| E-04 | SSRF guard hanya di `efek_samping`; 6 titik `httpx.get` di `dip_documents.py` tanpa guard, tanpa `follow_redirects=False` | CONFIRMED (asimetri) / POTENTIAL (eksploitasi) | Sedang | `dip_documents.py:194–205,407–416,588–598,844,996,1017`; guard: `efek_samping.py:298–317` | DB compromise → server fetch `169.254.169.254` / host internal, hasil ter-embed ke PDF publik `/dip/.../babN` | Helper guard bersama + whitelist host storage; matikan follow-redirect |
| E-06 | `r2`: upload sukses → `public_url` RuntimeError → user "gagal" + objek orphan, tanpa `storage_repair` | CONFIRMED | Sedang | `object_store.py:366–374`; `main.py:46–50` | `R2_PUBLIC_BASES` kurang satu bucket → objek tertulis, DB tak diperbarui | Validasi base sebelum tulis (fail-fast); log `storage_repair` bila gagal setelah tulis |
| E-08 | Alur `product-attachments` (privat, presigned) **tidak pernah ter-soak via aplikasi** di staging | OBSERVATION | Sedang | `product_attachments_routes.py`; `catatan_handoff:150–151` (staging tak punya tabel/bucket) | Jalur presigned R2 dalam app hanya teruji di smoke mentah boto3 | Replikasi di staging + E2E mode `r2` sebelum cutover |
| E-07b | Selector cache-bust `<a href*="raw-material-docs|legal-documents">` tak match URL `pub-*.r2.dev` | POTENTIAL | Rendah | `base.html:438` | Cache-bust link PDF mati diam-diam pasca-cutover (guard presign iframe tetap jalan) | Selector netral backend |
| E-13 | CORS R2 diverifikasi manual sekali, tanpa re-probe otomatis | OBSERVATION | Rendah | `catatan_migrasi_storage_r2.md:40–48` | Bucket dibuat ulang / r2.dev dimatikan → tak terdeteksi | Probe `Origin` di `r2_live_smoke.py` |

**Verdict kesiapan `STORAGE_BACKEND=r2` (berdasarkan kode)**: mekanis siap (dispatch
tuntas, semua akses lewat `object_store`, test ter-track fail-loud untuk backend tak
dikenal, live smoke staging-only ada, guard presign frontend utuh) — **tetapi belum siap
dijalankan** sebelum: E-05 (kanonisasi encoding), E-10/E-12 (verifikasi R2-side yang
auditable), E-08 (soak alur lampiran privat di `r2`), dan keputusan eksplisit atas E-02
(mode `r2` tidak punya jalur baca fallback sama sekali).

---

## 7. Dokumentasi vs Implementasi (Audit D)

12 CONFIRMED + 5 OBSERVATION; yang berdampak operasional:

| ID | Temuan | Risiko | Lokasi |
|---|---|---|---|
| D-01 | AGENTS.md stale: "DDL berikutnya harus bernomor 009" — repo punya **010** (tereksekusi staging+produksi) dan **009 tidak ada** | Tinggi | `AGENTS.md:43,91` vs `migration/010_replace_product_formula.sql:33–40` |
| D-02 | README/panduan tabel migrasi hanya 001–004 — DB baru yang mengikuti dokumen: **gagal simpan formula** (010 belum terpasang), fallback fail-open terpicu (007 absen), kontrak soft-delete 008 absen | Tinggi | `README.md:225–231,295–303`; `panduan:573–581` |
| D-03 | panduan §4.7/Q6 masih klaim "UUID = kunci unguessable" — model kini capability token `?access=`; verifikator dengan link lama dapat 404 | Tinggi | `panduan:343–344,828–829` vs `dip_public.py:270–303` |
| D-06 | `STORAGE_BACKEND`, env R2, `object_store.py` **tidak didokumentasikan** di README/panduan (hanya AGENTS + catatan historis) | Tinggi | `panduan:738–749`; `README.md:134` |
| D-07 | Semantik `dual` di catatan ("best-effort") bertentangan dengan kode (fail-loud) — termasuk `AGENTS.md:73` | Sedang–Tinggi | lihat E-02 |
| D-04 | Fallback login `@erfi.com` sudah dihapus, dokumen masih mendeskripsikannya | Sedang | `README.md:107`; `panduan:70,838` vs `main.py:1082–1085` |
| D-05 | Tabel versi README salah: 14 vs 15 paket, `pypdf 6.19.0` (aktual 6.21.1), boto3 tak tercantum | Sedang | `README.md:144–152,270` vs `requirements.txt` |
| D-08 | panduan §5.3 "penghapusan produk tanpa pemeriksaan role" — kini admin-only + audit `rejected` | Sedang | `panduan:666` vs `products_routes.py:298–305` |
| D-09/10/11/12 | "Empat poller disaring" vs 5 di `SKIP_PATHS`; inventaris tests/ (2 vs 16 file); "hanya SQL di-commit" (`audit_storage.py` + `backfill_r2_urls.py` juga); Python 3.10+ vs pin 3.11.0 | Rendah | `main.py:353–359`; `README.md:267,266,3`; `.python-version:1` |

**Klaim yang terverifikasi BENAR**: langkah CI sesuai `AGENTS.md:23`; konfigurasi
staging-e2e/dependabot/dependency-audit sesuai; interval polling cocok kode; aturan
PO analytics (limit 5.000, rework qty tidak dijumlahkan, banner amber maks 50, cookie
`po_filter`) cocok; `load_dotenv` hanya jalur produksi cocok.

---

## 8. CI / Runtime / Dependensi (Audit G)

| ID | Temuan | Klasifikasi | Risiko | Lokasi | Rekomendasi |
|---|---|---|---|---|---|
| G-11 | Jalur tanpa `DIP_APP_ENV` → default **produksi** tanpa preflight | CONFIRMED | **Tinggi** | `app/config.py:47–60`; hanya launcher yang men-set mode | `uvicorn app.main:app` langsung memuat `.env` produksi. → wajibkan flag eksplisit `DIP_APP_ENV=production` atau fail-closed |
| G-1 | `tests/test_base_cachebust.py` di-whitelist tapi **tidak dijalankan CI** | CONFIRMED | Sedang | `.gitignore:101` vs `ci.yml:58–67` | Regresi guard presign lolos CI. → tambahkan ke step / loop `test_*.py` |
| G-2 | Semua 5 E2E staging hanya di workflow `workflow_dispatch` (disabled otomatis) | CONFIRMED | Sedang | `staging-e2e.yml:2–4` | Aktifkan push/schedule setelah secrets lengkap |
| G-7 | `python-dotenv` & `Pillow` dipakai runtime produksi, tak ada di `requirements.txt` (dotenv tanpa penjaga) | CONFIRMED | Sedang | `requirements.txt`; `config.py:57`; `main.py:514,535` | Instalasi bersih gagal start (`dotenv`) / meledak saat runtime (`PIL`, lazy) | Pin keduanya |
| G-8/G-14 | pip-audit & gitleaks di ci.yml **report-only** (`continue-on-error: true`) | CONFIRMED | Sedang | `ci.yml:68–75` | CVE/secret tak memblokir merge | Hapus `continue-on-error` setelah baseline |
| G-4/G-5 | README 3.10+ vs pin 3.11.0; versi Render tak terverifikasi | CONFIRMED/OBS | Rendah/Sedang | `README.md:3,133,176`; `.python-version:1`; `ci.yml:26` | Floor 3.10 tak pernah diuji; drift runtime Render mungkin | Samakan klaim; pastikan `PYTHON_VERSION` Render |
| G-3 | pytest di-install CI tapi tak pernah dipakai | OBSERVATION | Rendah | `requirements-ci.txt:3` | — | Hapus atau migrasi runner |
| G-9 | `requirements-ci.txt` tak diaudit pip-audit | OBSERVATION | Rendah | `dependency-audit.yml` | — | Audit juga file CI |
| G-13 | Check statis efektif namun glob non-rekursif, tanpa near-duplicate path, tanpa mypy/bandit | OBSERVATION | Rendah | `check_static_rules.py:223–247` | Subpackage future di `app/` tak tercek undefined-name | `rglob`; normalisasi placeholder |

**Positif (Audit G)**: full-pin 15 dependensi; guard staging berlapis (host eksak
`odtfppboyjlbatajncgj.supabase.co`, JWT ref claim, 10 required keys termasuk R2,
shell clean, binding 127.0.0.1:8017, tanpa impor app sebelum validasi) dengan LIMITS
jujur; import `app.main` di CI fail-closed terhadap jaringan; duplicate-route check
membaca tabel routing final (menangkap duplikat dari registrasi apa pun).

---

## 9. Status Temuan yang Sudah Diketahui (6 item — verifikasi ulang di `main`)

| # | Temuan | Status | Bukti |
|---|---|---|---|
| 1 | Cache-buster `?v=` merusak presigned preview lampiran | **SUDAH DIPERBAIKI di `main`** (bukan hanya di branch) | `c0035ee` → `base.html:430` guard `X-Amz-Signature\|X-Amz-Algorithm\|token`; test `tests/test_base_cachebust.py` ikut ter-commit (belum dijalankan CI — G-1). Catatan sisa: selector `<a>` tak match URL r2.dev (E-07b) |
| 2 | `company_docs_routes.py` kirim nama perusahaan sebagai `entity_id` (kolom UUID) | **MASIH TERBUKA** | `company_docs_routes.py:124–125` — `log_activity(current_user, "update", doc_type, perusahaan, ...)`; cast uuid gagal → audit update dokumen legal tak tersimpan (fail-open) |
| 3 | Token `?access=` tercatat di access log uvicorn | **MASIH TERBUKA** | `/dip/*` tidak di `SKIP_PATHS` (`main.py:353–359`); launcher `run_staging_8017.py` memakai access log default (F-02) |
| 4 | `_dip_public_check_product` blok `except` jatuh ke mode legacy tanpa cek token (fail-open) | **MASIH TERBUKA** (code path tetap ada) | `dip_public.py:297–303` — fallback hanya cek `id` + `is_deleted`. Post-007 pemicunya bukan lagi kolom absen, melainkan **error transient Supabase**; di produksi terverifikasi historis tidak aktif, tapi jalurnya hidup (F-01) |
| 5 | `migration/verify_r2_readiness.py` tidak memeriksa bucket Supabase (PASS palsu) | **TIDAK TERVERIFIKASI** — file **tidak ter-track git** (di-ignore `.gitignore:76–82`), tak bisa diaudit dari `main`. Temuan terkait: gerbang cutover tak auditable (E-12); audit ter-track punya false-PASS sendiri (E-10/E-11) | `git log --all -- migration/verify_r2_readiness.py` kosong |
| 6 | Link `/dip/<slug>-<id>` tanpa `?access=` untuk produk non-BPOM bertoken → 404 | **TERKONFIRMASI — perilaku disengaja** | `dip_public.py:288–295 → return False → 404` (`:155–156`); semua kondisi gagal 404 identik (tanpa oracle) — pertahankan (F-10) |

---

## 10. Temuan Penting Lainnya

- **Semantik `dual` vs dokumentasi** (E-02/D-07) = risiko keputusan cutover paling
  material: soak yang "hijau" tidak membuktikan ketahanan terhadap gagal R2, dan mode
  `r2` tidak punya jalur baca fallback sama sekali.
- **SSRF asimetris** (E-04): guard ada di satu modul, absen di 6 titik jalur yang
  terjangkau publik.
- **Audit trail bocor dua arah** (TYPE-01 + fail-open tanpa metrik): baris hilang
  diam-diam karena non-UUID, kegagalan logging tak terlihat, sementara download/ZIP
  publik tidak ter-audit sama sekali (F-09).
- **Gap CI**: test yang justru mengunci fix terbaru (`test_base_cachebust.py`) tidak
  dijalankan pipeline (G-1); semua E2E hanya manual-dispatch (G-2).
- **Tidak ada regresi baru** dibanding audit 2026-10-21; semua perbaikan H3 dan restore
  soft-delete terverifikasi land di `main`.

---

## 11. Cakupan Audit

**Dibaca penuh (baris per baris)**:
`app/main.py` (1.567), `app/object_store.py` (551), `app/dip_public.py` (407),
`app/raw_materials_routes.py` (2.112), `app/po_routes.py` (1.209), `app/products_routes.py`
(1.520), `app/sample_routes.py`, `app/notes_routes.py`, `app/brands_routes.py`,
`app/admin_users_routes.py`, `app/dashboard_routes.py`, `app/company_docs_routes.py`,
`app/product_attachments_routes.py`, `app/config.py`, `app/database.py`,
`app/file_validation.py`, `app/security.py`, `app/staging_guard.py`,
`app/staging_preflight.py` (fragment), `scripts/run_staging_8017.py`,
`scripts/r2_live_smoke.py` (fragment), `migration/audit_storage.py`,
`migration/backfill_r2_urls.py`, `migration/007` & `010` (header), semua workflow CI +
dependabot + `requirements.txt` + `requirements-ci.txt` + `.python-version` + `.gitignore`.

**Template/JS dibaca penuh**: `base.html`, `dip_public_hub.html`, `login.html`,
`public_error.html`, `notes.html`, `dashboard.html`, `raw_materials.html` (2.211),
`brands.html`, `admin_users.html`, `edit_product.html` (1.306), `admin_trash.html`,
`_sidebar.html`, `lampiran.js`, `presence.js`, `efek_samping.js`.

**Dibaca parsial / grep ter-target**: `dip_documents.py` (segmen fetch/SSRF),
`efek_samping.py`, `presence_routes.py`, sisa templates (`purchase_orders`,
`po_analytics`, `sample_*`, `finished_spec_*`, `product_attachments`,
`lampiran_uploader`, `admin_company_documents`, `efek_samping_modal`,
`qualitative_quantitative`), `sidebar.js`, `darkmode.js`, `po-analytics.js`.

**Dibaca (dokumen)**: README.md (341), panduan (883), AGENTS.md (91), 5 catatan
historis (`catatan_audit_codebase_2026-10-21.md` dibaca penuh; `auth500` &
`batch_plan` skim).

**Dilewati / tidak dibaca sesuai aturan**: `.env*`, `LOGIN.md`, `backup-rls/` (kecuali
20 baris definisi `activity_logs` — dipakai Audit C untuk membuktikan tipe kolom
`entity_id uuid`), `venv/`, `migration/verify_r2_readiness.py` (tidak ter-track).

**Batasan**:
- Tidak menjalankan server/E2E/query DB — status eksekusi migrasi dan env Render/R2
  live tidak dapat diverifikasi dari repo.
- Perilaku proxy Render (XFF ditimpa atau tidak) dan bfcache browser = analisis
  spesifikasi, bukan pengujian langsung.
- Template PDF-generator (`bab1–4_checklist*`, `bab2_*`, `text_design_block`,
  `monitoring_efek_samping_block`, `finished_spec_pdf`, `ingredient_report`,
  `qualitative_quantitative`, `sample_*`) dan `bab2_pdf.py`/`excel_generator.py`
  hanya di-grep pattern dasar — **tidak diperiksa mendalam, dan tidak boleh dianggap
  aman karena itu**.
- `python` global tidak ada di PATH; checker dijalankan via `venv\Scripts\python.exe`.
- Nomor baris mengikuti `main` @ `c0035ee`; bisa bergeser pada commit berikutnya.

---

## 12. Kesimpulan dan Prioritas

**Kesimpulan**: codebase dalam kondisi sehat-fungsional dengan disiplin escaping dan
guard staging yang baik; sebagian besar temuan berdampak tinggi dari audit 2026-10-21
sudah diperbaiki di `main`. Risiko terbesar saat ini bukan di lapisan rendering,
melainkan: (1) jalur publik yang masih punya satu blok fail-open, (2) jejak audit yang
gagal diam-diam, (3) kesenjangan tooling/dokumen migrasi R2 yang bisa menghasilkan
cutover dengan verifikasi palsu, dan (4) default konfigurasi yang fail-open menuju
produksi.

### Sebelum cutover R2 (urut risiko)

| # | Tindakan | Rujukan |
|---|---|---|
| 1 | Jadikan fallback `_dip_public_check_product` fail-closed | F-01 |
| 2 | Kanonisasi encoding key/URL + test roundtrip remove/presign | E-05 |
| 3 | Commit `verify_r2_readiness.py`; tambahkan mode audit R2-side; perketat pre-check backfill | E-10/E-11/E-12 |
| 4 | Putuskan & dokumenkan semantik `dual` (fail-loud vs best-effort); revisi kriteria soak | E-02/D-07 |
| 5 | Soak alur `product-attachments` (bucket privat) via aplikasi di mode `r2` staging | E-08 |
| 6 | Standarkan `entity_id` UUID/`None` di semua call site `log_activity` | TYPE-01 |
| 7 | Fail-fast base R2 sebelum tulis; selector cache-bust netral backend | E-06/E-07b |
| 8 | Jalankan `test_base_cachebust.py` di CI | G-1 |

### Setelah cutover (urut risiko)

| # | Tindakan | Rujukan |
|---|---|---|
| 1 | Tutup jalur default-produksi tanpa flag `DIP_APP_ENV=production` | G-11 |
| 2 | CSRF token/origin check, security headers, `secure=True` cookie | SEC-06/07/19 |
| 3 | Trusted proxy untuk XFF (rate limit & IP audit) | SEC-21 |
| 4 | Defensif backend: BE-04/08/14/17, TRX-01, BE-05/06, VAL-01 | §5 |
| 5 | Enforce revoke + audit semua route download publik | F-03/F-09 |
| 6 | Higiene polling & presence (FE-B01, FE-04/05/06) | §4 |
| 7 | Sinkronkan AGENTS.md/README/panduan (nomor migrasi, model token, R2, fallback login) | D-01 s.d. D-12 |

### Opsional

Hapus artefak `omniroute` (SEC-18) · unifikasi 5 `escapeHtml` (SEC-14) · `/logout` →
POST (SEC-16) · SRI/vendor CDN (SEC-12) · hapus pytest dari requirements-ci (G-3) ·
rate limit `/dip/*` (F-08) · `hmac.compare_digest` (F-07) · Referrer-Policy (F-06) ·
SSRF guard `follow_redirects=False` (E-04).

---

## 13. Eksekusi Test (tambahan sesi yang sama, atas instruksi eksplisit pemilik repo)

### 13.1 Langkah 1 — Test pure-local (env dummy CI: `PYTHONPATH=.`, tanpa `DIP_APP_ENV`)

| Test | Exit | Hasil |
|---|---|---|
| `tests/test_parse_storage_url.py` | 0 | 19 kasus LULUS |
| `tests/test_object_store_r2.py` | 0 | dispatch r2/dual LULUS |
| `tests/test_security_helpers.py` | 0 | LULUS |
| `tests/test_upload_validation.py` | 0 | LULUS |
| `tests/test_auth_matrix.py` | 0 | LULUS (deprecation warning starlette/httpx — bukan fail) |
| `tests/test_audit_regressions.py` | 0 | **PASS 58 / KNOWN 14 / FAIL 0 / SKIP 2** |
| `tests/test_base_cachebust.py` | 0 | guard presign PASS |

**OBSERVATION (TEST-01):** tanpa `PYTHONPATH=.`, 3 test (`test_security_helpers`, `test_upload_validation`, `test_auth_matrix`) gagal `ModuleNotFoundError: No module named 'app'`. CI men-set `PYTHONPATH: .` (`ci.yml:60`) sehingga pipeline aman — hanya eksekusi manual tanpa PYTHONPATH yang keliru. Tanpa dampak produksi.

### 13.2 Langkah 2 — E2E staging (`scripts/run_staging_8017.py`, 127.0.0.1:8017)

- **Preflight: "STAGING PREFLIGHT PASS"**; `/health` = 200. Mode efektif `STORAGE_BACKEND=dual` (dibaca dari config saat runtime, hanya nama mode yang dicetak) → **seluruh suite dijalankan termasuk `upload`**. `.env.staging` tidak diubah. Server **dihentikan** di akhir.
- Kredensial E2E dibaca runtime dari `LOGIN.md` → `STAGING_ADMIN_EMAIL`/`STAGING_ADMIN_PASSWORD` via wrapper sementara di `%TEMP%\kilo\` (tanpa kredensial di dalam file; wrapper dihapus setelah selesai). Nilai tidak pernah di-echo ke laporan.

| Suite | Exit | Hasil | Data staging yang dibuat | Dibersihkan? |
|---|---|---|---|---|
| `e2e_smoke_refactor.py` | 0 | **34/34 PASS** | 1 sample + 1 brand uji | ✅ ya (sample terhapus, brand terhapus oleh suite) |
| `e2e_activity_request_id.py` | 0 | **19/19 PASS** (request_id, route/method, outcome, actor) | notes uji | ✅ ya |
| `e2e_audit_staging.py --quick` | 0 | **PASS 34 / KNOWN 3 / FAIL 0 / SKIP 7** | penulisan formula uji | ✅ ya (snapshot formula dipulihkan — G11 PASS) |
| `e2e_upload_staging.py` (backend `dual`) | 0 | **6/6 PASS, 1 SKIP** (cek log dilewati: `staging.log` tidak ada di root) | objek `company-docs/nib_erfi.pdf` ditimpa di Supabase **dan** R2 `legal-documents-stg` (592 byte, file uji) | ⚠️ tidak dihapus — timpa-in-place by design; objek uji menjadi NIB staging aktif sampai upload berikutnya |

- 3 KNOWN di suite audit = persis registry KNOWN_ISSUES (SEC-04 cookie tanpa `secure`, FE-05 logout sidebar, FE-06 `__adminPresenceInterval`) — konsisten dengan temuan statis §3/§4. **Tidak ada FAIL baru.**

**OBSERVATION (TEST-02):** `e2e_upload_staging.py` menimpa objek NIB staging dengan file uji (di Supabase dan R2, mode `dual`) dan tidak mengembalikan objek asli. Perilaku tampak disengaja (idempoten), tetapi berarti **dokumen NIB staging berisi file uji** setelah run — patut dicatat bagi yang mengandalkan isi staging.

### 13.3 Langkah 2e — `migration/verify_r2_readiness.py --env staging --expect-suffix=-stg`

- **Exit 0 — "SIAP untuk STORAGE_BACKEND=r2; FAIL=0; WARN=4"** (perintah dengan `="=-stg"` salah — tanda `=` ikut jadi nilai; gunakan `--expect-suffix=-stg` apa adanya).
- WARN yang muncul (semua explainable, bukan blocker):
  1. `KESAMAAN ISI raw-material-docs` — `EXTRA_IN_R2=2` (objek `_smoke/` sisa live smoke; MISSING=0, SIZE_MISMATCH=0).
  2. `REFERENSI nib_documents.file_url` — `STILL_SUPABASE=1`: URL NIB di DB masih Supabase (konsisten mode `dual` + upload E2E barusan menulis URL Supabase; backfill `--target r2` memang belum dijalankan di staging).
  3. `IDEMPOTENSI BACKFILL changes=1` — akar sama dengan (2).
  4. `AKSES PUBLIK tanpa CORS=6` (sample 6, non-200=0) — **kontradiksi dengan `catatan_migrasi_storage_r2.md` yang mengklaim keenam bucket lolos probe CORS**; patut diverifikasi ulang (lihat E-13).
- Catatan status dokumen: temuan lama #5 ("verify_r2_readiness tidak memeriksa bucket Supabase") — verifier ini **tetap tidak ter-track git** (E-12 tetap berlaku), tetapi output aktualnya memeriksa kesamaan isi + referensi DB → klaim "PASS palsu karena tidak memeriksa bucket" **tidak terkonfirmasi** pada versi di disk; versi di disk bisa berbeda dari yang dirujuk temuan lama. Status tetap: **tidak dapat diverifikasi dari `main`** karena file tidak di-commit.

### 13.4 Insiden prosedur

- **Kebocoran output sesi:** satu perintah diagnosa "key-only" gagal men-strip nilai (pola tabel ber-backtick `LOGIN.md` tidak cocok regex) sehingga **kredensial akun tes staging sempat tercetak ke output sesi**. Nilai tidak disalin ke file/laporan/commit mana pun. Sesuai aturan `LOGIN.md` butir 5: **password akun tes staging disarankan dirotasi** setelah sesi ini.
- Tidak dijalankan (sesuai larangan): `tests/snapshot_dip.py`, `scripts/r2_live_smoke.py`, apa pun yang menyentuh produksi.

### 13.5 Ringkasan hasil eksekusi

**Seluruh test lulus: 7/7 pure-local, 4/4 suite E2E staging, verifier R2 SIAP (0 FAIL, 4 WARN explainable).** Tidak ada temuan CONFIRMED baru dari eksekusi; semua KNOWN cocok dengan registry audit. Satu insiden prosedural (kebocoran output sesi kredensial tes staging) — rotasi password disarankan.

---

## Riwayat

| Tanggal | Peristiwa |
|---|---|
| 2026-10-27 | Audit read-only seluruh codebase di `main` @ `c0035ee` (7 agen paralel + verifikasi manual 6 temuan yang diketahui + 2 checker statis). Dokumen ini dibuat atas permintaan pemilik repo. Tidak ada perubahan kode. |
| 2026-10-27 (lanjutan) | **Eksekusi test** (atas instruksi eksplisit): 7/7 test pure-local PASS (env dummy CI), 4/4 suite E2E staging PASS (smoke 34/34, activity 19/19, audit --quick PASS 34/KNOWN 3/FAIL 0/SKIP 7, upload 6/6 di backend `dual`), `verify_r2_readiness.py` staging SIAP (exit 0, 0 FAIL, 4 WARN explainable). Server staging dinyalakan lewat launcher (preflight PASS) dan dihentikan di akhir; data uji dibersihkan oleh suite (kecuali objek NIB staging ditimpa file uji — TEST-02). Satu insiden prosedural: kredensial tes staging sempat tercetak ke output sesi saat parsing LOGIN.md — rotasi password disarankan. Lihat §13. |
