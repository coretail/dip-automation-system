"""Unit test murni app/mailer.py — httpx SELALU di-mock, tanpa jaringan & secret.

Kontrak yang dikunci:
  1. staging + MAIL_ENABLED=false            -> (False,"skipped"), httpx tidak dipanggil
  2. staging + enabled, di luar MAIL_ALLOWLIST -> (False,"skipped")
  3. staging + enabled + allowlist (beda case) -> benar-benar kirim
  4. produksi: 201 -> sent; 400 -> failed; ReadTimeout -> unknown
  5. BREVO_API_KEY / MAIL_FROM_EMAIL kosong  -> (False,"failed"), tanpa jaringan
  6. email penerima tidak valid              -> (False,"failed")
  7. payload & header benar (api-key, sender, to, subject, htmlContent, textContent)
  8. template: autoescape (& -> &amp;), tanpa asset eksternal, tanpa karakter tak terlihat
  9. parse_allowlist & mask_email
 10. INVITE_VALID_HOURS dipakai (tidak hardcode 24 jam)

Dijalankan: python tests/test_mailer.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
import sys

import httpx as real_httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import mailer  # noqa: E402

FAILURES = []

TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "templates", "email", "invite_email.html",
)

ACTIVATE_URL = "https://app.example.com/activate?otp=ABC123&type=invite"
BASE_URL = "https://app.example.com"

FAKE_API_KEY = "test-api-key"
FAKE_FROM_EMAIL = "noreply@example.com"


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeAsyncClient:
    """Pengganti httpx.AsyncClient. Tidak pernah menyentuh jaringan."""

    queue = []
    calls = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        item = FakeAsyncClient.queue.pop(0) if FakeAsyncClient.queue else FakeResponse(500)
        self._raises = item if isinstance(item, Exception) else None
        self._response = None if self._raises else item

    async def __aenter__(self):
        if self._raises is not None:
            raise self._raises
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, json=None, headers=None):
        FakeAsyncClient.calls.append({"url": url, "json": json, "headers": headers})
        return self._response


class FakeHttpx:
    """Modul httpx palsu; TimeoutException tetap milik httpx asli agar tertangkap."""

    TimeoutException = real_httpx.TimeoutException

    def __init__(self):
        self.AsyncClient = FakeAsyncClient


class FakeSettings:
    def __init__(self, **overrides):
        self.brevo_api_key = overrides.get("brevo_api_key", FAKE_API_KEY)
        self.mail_from_email = overrides.get("mail_from_email", FAKE_FROM_EMAIL)
        self.mail_from_name = overrides.get("mail_from_name", "DIP Automation System")
        self.mail_enabled = overrides.get("mail_enabled", True)
        self.mail_allowlist = overrides.get("mail_allowlist", "")


def reset(mail_enabled=True, mail_allowlist="", staging=False, queue=None,
          brevo_api_key=FAKE_API_KEY, mail_from_email=FAKE_FROM_EMAIL):
    mailer.httpx = FakeHttpx()
    mailer.settings = FakeSettings(
        mail_enabled=mail_enabled,
        mail_allowlist=mail_allowlist,
        brevo_api_key=brevo_api_key,
        mail_from_email=mail_from_email,
    )
    mailer.is_staging_mode = lambda: staging
    FakeAsyncClient.queue = list(queue or [])
    FakeAsyncClient.calls = []


def send(to_email=ACTIVATE_URL, activate_url=ACTIVATE_URL, app_base_url=BASE_URL):
    """Jalankan send_invite_email; cegah output mailer mengotori keluaran test."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = asyncio.run(
            mailer.send_invite_email(to_email, activate_url, app_base_url)
        )
    return result, buf.getvalue()


def main():
    # --- 1. staging + MAIL_ENABLED=false -> skipped, tanpa jaringan -----------
    reset(mail_enabled=False, staging=True)
    res, out = send(to_email="user@example.com")
    check("1 staging MAIL_ENABLED=false -> (False,'skipped')",
          res == (False, mailer.STATUS_SKIPPED), str(res))
    check("1b httpx tidak dipanggil", not FakeAsyncClient.calls)
    check("1c link tercetak ke terminal", ACTIVATE_URL in out)

    # --- 2. staging + enabled, di luar allowlist -> skipped ------------------
    reset(mail_enabled=True, mail_allowlist="other@example.com", staging=True)
    res, _ = send(to_email="user@example.com")
    check("2 staging di luar MAIL_ALLOWLIST -> (False,'skipped')",
          res == (False, mailer.STATUS_SKIPPED), str(res))
    check("2b httpx tidak dipanggil", not FakeAsyncClient.calls)

    # --- 3. staging + enabled + allowlist (beda huruf besar/kecil) ----------
    reset(mail_enabled=True, mail_allowlist="User@Example.COM", staging=True,
          queue=[FakeResponse(201, {"messageId": "msg-abcdefgh"})])
    res, _ = send(to_email="user@example.com")
    check("3 staging allowlist case-insensitive -> (True,'sent')",
          res == (True, mailer.STATUS_SENT), str(res))
    check("3b httpx dipanggil sekali", len(FakeAsyncClient.calls) == 1)

    # --- 4. produksi: 201 / 400 / timeout ----------------------------------
    reset(staging=False, queue=[FakeResponse(201, {"messageId": "msg-1"})])
    res, _ = send(to_email="user@example.com")
    check("4a produksi 201 -> (True,'sent')", res == (True, mailer.STATUS_SENT), str(res))

    reset(staging=False, queue=[FakeResponse(400, {"code": "invalid_parameter"})])
    res, _ = send(to_email="user@example.com")
    check("4b produksi 400 -> (False,'failed')", res == (False, mailer.STATUS_FAILED), str(res))

    reset(staging=False, queue=[real_httpx.ReadTimeout("timeout")])
    res, out = send(to_email="user@example.com")
    check("4c ReadTimeout -> (False,'unknown')", res == (False, mailer.STATUS_UNKNOWN), str(res))
    check("4d timeout tidak diklaim sukses", "unknown" in out)

    # --- 5. konfigurasi belum lengkap -> failed, tanpa jaringan -------------
    reset(staging=False, brevo_api_key="")
    res, _ = send(to_email="user@example.com")
    check("5a BREVO_API_KEY kosong -> (False,'failed')",
          res == (False, mailer.STATUS_FAILED), str(res))
    check("5b tanpa API key tidak ada panggilan jaringan", not FakeAsyncClient.calls)

    reset(staging=False, mail_from_email="")
    res, _ = send(to_email="user@example.com")
    check("5c MAIL_FROM_EMAIL kosong -> (False,'failed')",
          res == (False, mailer.STATUS_FAILED), str(res))
    check("5d tanpa pengirim tidak ada panggilan jaringan", not FakeAsyncClient.calls)

    # --- 6. email penerima tidak valid -------------------------------------
    reset(staging=False)
    res, _ = send(to_email="bukan-email")
    check("6 email tidak valid -> (False,'failed')", res == (False, mailer.STATUS_FAILED), str(res))
    check("6b email tidak valid tidak memanggil httpx", not FakeAsyncClient.calls)

    # --- 7. payload & header ------------------------------------------------
    reset(staging=False, queue=[FakeResponse(201, {"messageId": "msg-xyz"})])
    res, _ = send(to_email="user@example.com")
    call = FakeAsyncClient.calls[-1]
    payload = call["json"] or {}
    headers = call["headers"] or {}
    check("7a endpoint Brevo", call["url"] == mailer.BREVO_ENDPOINT, str(call["url"]))
    check("7b header api-key", headers.get("api-key") == FAKE_API_KEY)
    check("7c header Content-Type json", headers.get("Content-Type") == "application/json")
    check("7d sender.email", (payload.get("sender") or {}).get("email") == FAKE_FROM_EMAIL)
    check("7e sender.name", bool((payload.get("sender") or {}).get("name")))
    check("7f to", payload.get("to") == [{"email": "user@example.com"}], str(payload.get("to")))
    check("7g subject", payload.get("subject") == mailer.EMAIL_SUBJECT)
    check("7h htmlContent terisi", bool(payload.get("htmlContent")))
    check("7i textContent terisi", bool(payload.get("textContent")))
    check("7j textContent memuat tautan", ACTIVATE_URL in (payload.get("textContent") or ""))
    check("7k textContent plain (tanpa &amp;)", "&amp;" not in (payload.get("textContent") or ""))
    check("7l htmlContent memuat tautan (autoescaped)",
          ACTIVATE_URL.replace("&", "&amp;") in (payload.get("htmlContent") or ""))

    # --- 8. template: autoescape, tanpa asset eksternal, tanpa karakter tak terlihat
    html = mailer.render_invite_email("https://x.example/a?b=1&c=2", BASE_URL)
    check("8a autoescape & -> &amp;", "b=1&amp;c=2" in html)
    low = html.lower()
    check("8b tanpa <script>", "<script" not in low)
    check("8c tanpa <link>", "<link" not in low)
    check("8d tanpa <img>", "<img" not in low)
    check("8e tanpa @import", "@import" not in low)
    check("8f tanpa url()", "url(" not in low)
    check("8g tanpa http:// eksternal pada src/href aset",
          'src="http' not in low and 'src=\'http' not in low)

    with io.open(TEMPLATE_PATH, encoding="utf-8") as fh:
        raw_template = fh.read()
    invisible = {
        "\u200b": "ZWSP", "\u200c": "ZWNJ", "\u200d": "ZWJ", "\ufeff": "BOM",
        "\u2060": "WORD JOINER", "\u00ad": "SOFT HYPHEN", "\u00a0": "NBSP",
    }
    found = [name for ch, name in invisible.items() if ch in raw_template]
    check("8h template tanpa karakter tak terlihat", not found, ",".join(found))
    found_out = [name for ch, name in invisible.items() if ch in html]
    check("8i html render tanpa karakter tak terlihat", not found_out, ",".join(found_out))
    check("8j template diakhiri newline", raw_template.endswith("\n"))

    # --- 9. parse_allowlist & mask_email -----------------------------------
    check("9a parse_allowlist", mailer.parse_allowlist("A@b.com, c@d.com ,,") == {"a@b.com", "c@d.com"})
    check("9b parse_allowlist kosong", mailer.parse_allowlist("") == set())
    check("9c parse_allowlist None", mailer.parse_allowlist(None) == set())
    check("9d mask_email", mailer.mask_email("budi.santoso@erfi.com") == "b**********o@erfi.com",
          mailer.mask_email("budi.santoso@erfi.com"))
    check("9e mask_email 1 char", mailer.mask_email("a@b.com") == "*@b.com")
    check("9f mask_email 2 char", mailer.mask_email("ab@b.com") == "a*@b.com")
    check("9g mask_email invalid", mailer.mask_email("bukan-email") == "-")

    # --- 10. INVITE_VALID_HOURS dipakai, tidak hardcode --------------------
    html24 = mailer.render_invite_email(ACTIVATE_URL, BASE_URL)
    check("10a default INVITE_VALID_HOURS = 24", mailer.INVITE_VALID_HOURS == 24)
    check("10b html memakai konstanta (24 jam)", "(24 jam)" in html24)
    html48 = mailer.render_invite_email(ACTIVATE_URL, BASE_URL, valid_hours=48)
    check("10c valid_hours dioper ke template", "(48 jam)" in html48 and "(24 jam)" not in html48)
    txt48 = mailer.render_invite_text(ACTIVATE_URL, BASE_URL, valid_hours=48)
    check("10d textContent memakai valid_hours", "(48 jam)" in txt48)
    txt_default = mailer.render_invite_text(ACTIVATE_URL, BASE_URL)
    check("10e textContent default 24 jam", "(24 jam)" in txt_default)
    check("10f textContent memuat app_base_url", BASE_URL in txt_default)

    # --- 11. mode is_resend=True --------------------------------------------
    reset(staging=False, queue=[FakeResponse(201, {"messageId": "msg-resend"})])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res_resend = asyncio.run(
            mailer.send_invite_email(
                "user@example.com",
                ACTIVATE_URL,
                BASE_URL,
                is_resend=True,
            )
        )
    check("11a resend produksi 201 -> (True,'sent')", res_resend == (True, mailer.STATUS_SENT), str(res_resend))
    resend_payload = FakeAsyncClient.calls[-1]["json"] or {}
    check("11b resend subject == EMAIL_RESEND_SUBJECT",
          resend_payload.get("subject") == mailer.EMAIL_RESEND_SUBJECT,
          str(resend_payload.get("subject")))
    resend_html = resend_payload.get("htmlContent") or ""
    resend_text = resend_payload.get("textContent") or ""
    check("11c resend htmlContent menyebut tautan sebelumnya tidak berlaku",
          "sebelumnya sudah tidak berlaku" in resend_html)
    check("11d resend textContent menyebut tautan sebelumnya tidak berlaku",
          "sebelumnya sudah tidak berlaku" in resend_text)
    check("11e resend htmlContent autoescape & -> &amp;",
          ACTIVATE_URL.replace("&", "&amp;") in resend_html)
    check("11f resend textContent plain (tanpa &amp;)",
          ACTIVATE_URL in resend_text and "&amp;" not in resend_text)
    resend_low = resend_html.lower()
    check("11g resend html bebas tag/asset eksternal",
          "<script" not in resend_low and "<link" not in resend_low and "<img" not in resend_low
          and "@import" not in resend_low and "url(" not in resend_low)
    found_resend_inv = [name for ch, name in invisible.items() if ch in resend_html]
    check("11h resend html tanpa karakter tak terlihat", not found_resend_inv, ",".join(found_resend_inv))

    print()
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} pemeriksaan")
        for name in FAILURES:
            print(f"  - {name}")
        sys.exit(1)
    print("OK: semua pemeriksaan lolos")


if __name__ == "__main__":
    main()
