# Catatan Modul Mailer Undangan (2026-11-20)

Bagian dari fitur "Undang User Baru via Email". Modul ini hanya mengurus
**pengiriman email**; pembuatan user, dedupe, dan audit ada di Task 3.

## File

| File | Keterangan |
|------|------------|
| `app/mailer.py` | `send_invite_email()`, `render_invite_email()`, `parse_allowlist()`, `mask_email()` |
| `app/templates/email/invite_email.html` | Template email HTML (inline CSS, tanpa asset eksternal) |
| `app/config.py` | Field mail: `brevo_api_key`, `mail_from_name`, `mail_from_email`, `mail_enabled`, `mail_allowlist`, `app_base_url` (di `_StagingSettings` & `_ProdSettings`) |
| `.env.staging.example` | Nama key mail (tanpa secret) |

`requirements.txt` **tidak diubah** — `httpx==0.28.1` sudah dipin.

## Kontrak

```python
async def send_invite_email(to_email: str, activate_url: str, app_base_url: str) -> tuple[bool, str]
```

| Return | Arti | Aksi pemanggil (Task 3) |
|--------|------|--------------------------|
| `(True, "sent")` | Brevo menerima email (HTTP 2xx) | `status=invite_sent` |
| `(False, "failed")` | ditolak / error non-timeout / konfigurasi kurang | `status=invite_failed_email` |
| `(False, "unknown")` | **timeout** — email mungkin sudah terkirim | `status=invite_unknown`, **jangan auto-retry** |
| `(False, "skipped")` | staging no-op / `MAIL_ENABLED=false` / di luar allowlist | belum benar-benar terkirim; UI/audit harus membedakannya |

## Perilaku staging

Default **no-op**: link aktivasi dicetak ke terminal (email penerima di-mask).
Pengiriman nyata hanya bila `MAIL_ENABLED=true` **dan** penerima ada di
`MAIL_ALLOWLIST` (parse dipisah koma, case-insensitive).

## Keamanan

- Header `api-key` (Brevo v3) + `Content-Type: application/json`.
- `BREVO_API_KEY` tidak pernah dicetak; body respons penuh tidak pernah dicetak
  (hanya HTTP status + `messageId` 8 karakter pertama).
- Template memakai autoescape Jinja; tidak memuat `<script>`/`<link>`/`<img>`/
  `@import`/`url()` sehingga tidak ada asset eksternal yang bisa menerima Referer.
- `mask_email()` dipakai di log agar penerima tidak tampil penuh.
- Modul tidak mengimpor `app.main` (mencegah circular import); `mask_email`
  disalin lokal dengan semantik sama.

## Verifikasi yang sudah dilakukan

Dijalankan dengan `httpx` **selalu di-mock** (tidak ada email nyata terkirim):

- staging + `MAIL_ENABLED=false` → `(False,"skipped")`, httpx tidak dipanggil;
- staging + enabled tapi di luar allowlist → `(False,"skipped")`, tidak dikirim;
- staging + enabled + di allowlist (case-insensitive) → benar-benar kirim;
- produksi 201 → `(True,"sent")`; 400 → `(False,"failed")`;
- timeout (`httpx.ReadTimeout`) → `(False,"unknown")`;
- `BREVO_API_KEY`/`MAIL_FROM_EMAIL` kosong → `(False,"failed")`, tanpa jaringan;
- email tidak valid → `(False,"failed")`;
- payload `sender`/`to`/`subject`/`htmlContent` dan header `api-key` benar;
- template: `&` → `&amp;`, HTML seimbang (3407 char), tanpa asset eksternal.

Static: `check_undefined_names.py` exit 0, `check_static_rules.py` exit 0,
`compileall` OK, import terisolasi `app.main` + `app.mailer` OK.