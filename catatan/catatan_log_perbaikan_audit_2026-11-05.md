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
| B1–B10, C1–C3 | Saran low-risk lainnya (§3–§5 audit) | BELUM | — |
| A-02 s.d. A-20, B, C, E, F, G §3–§8 | Temuan keamanan, frontend, backend, storage, CI | BELUM | — |
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
