"""Pengiriman email undangan user baru via Brevo HTTP API (v3).

Kontrak ``send_invite_email`` -> ``tuple[bool, str]``:

    (True,  "sent")     Brevo menerima email (HTTP 2xx).
    (False, "failed")   Brevo menolak, error non-timeout, atau konfigurasi belum lengkap.
    (False, "unknown")  Timeout — email MUNGKIN sudah terkirim; JANGAN auto-retry.
    (False, "skipped")  Sengaja tidak dikirim: staging no-op, ``MAIL_ENABLED=false``,
                        atau penerima tidak ada di ``MAIL_ALLOWLIST``.

Cakupan ``MAIL_ENABLED`` / ``MAIL_ALLOWLIST`` (PENTING):
    Kedua variabel itu **HANYA berlaku di mode staging** (``DIP_APP_ENV=staging``)
    dan **diabaikan di produksi**. Di produksi email selalu dicoba dikirim bila
    ``BREVO_API_KEY`` dan ``MAIL_FROM_EMAIL`` tersedia; pengiriman produksi dapat
    dimatikan dengan mengosongkan ``BREVO_API_KEY`` (mailer mengembalikan
    ``"failed"`` tanpa panggilan jaringan).

Di staging default no-op: link aktivasi dicetak ke terminal tanpa kredensial.
API key dan body respons penuh tidak pernah dicetak.
"""
from __future__ import annotations

import httpx
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.staging_guard import is_staging_mode

TEMPLATES_DIR = "app/templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
REQUEST_TIMEOUT_SECONDS = 10.0
EMAIL_SUBJECT = "Undangan Bergabung — DIP Automation System"
DEFAULT_FROM_NAME = "DIP Automation System"
INVITE_TEMPLATE = "email/invite_email.html"

# Masa berlaku tautan undangan. HARUS sama dengan setting "Email OTP expiry" di
# Supabase Auth (Authentication -> Settings). Mengubah salah satu tanpa yang lain
# membuat teks email menjanjikan masa berlaku yang salah.
INVITE_VALID_HOURS = 24

STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown"
STATUS_SKIPPED = "skipped"


def mask_email(email: str) -> str:
    """Samarkan email untuk log/terminal (sama semantik dengan ``main.mask_email``).

    Disalin lokal supaya modul ini tidak mengimpor ``app.main`` (mencegah circular
    import). 'budi.santoso@erfi.com' -> 'b**********o@erfi.com'.
    """
    if not email or "@" not in email:
        return "-"
    local, _, domain = email.partition("@")
    if not local:
        return f"@{domain}"
    if len(local) == 1:
        masked = "*"
    elif len(local) == 2:
        masked = local[0] + "*"
    else:
        masked = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


def parse_allowlist(raw: str) -> set[str]:
    """Ubah ``MAIL_ALLOWLIST`` (dipisah koma) menjadi set email lowercase."""
    return {part.strip().lower() for part in (raw or "").split(",") if part.strip()}


def render_invite_email(
    activate_url: str,
    app_base_url: str,
    valid_hours: int = INVITE_VALID_HOURS,
) -> str:
    """Render body HTML email undangan lewat Jinja2 (autoescape aktif)."""
    template = templates.get_template(INVITE_TEMPLATE)
    return template.render(
        activate_url=activate_url,
        app_base_url=app_base_url,
        valid_hours=valid_hours,
    )


def render_invite_text(
    activate_url: str,
    app_base_url: str,
    valid_hours: int = INVITE_VALID_HOURS,
) -> str:
    """Body plain-text alternatif untuk ``textContent`` Brevo.

    Disusun sebagai string builder (bukan template Jinja) karena autoescape Jinja
    akan mengubah ``&`` pada query string URL menjadi ``&amp;`` — benar untuk HTML,
    tetapi merusak tautan pada email plain-text.
    """
    lines = [
        EMAIL_SUBJECT,
        "",
        "Anda diundang untuk bergabung ke DIP Automation System.",
        "Silakan aktifkan akun Anda melalui tautan berikut:",
        "",
        activate_url,
        "",
        f"Tautan ini hanya berlaku sementara ({valid_hours} jam) dan hanya dapat "
        "digunakan satu kali.",
        "Jika Anda tidak merasa diundang, abaikan email ini.",
        "",
        "Bila mengalami kendala, hubungi administrator Anda.",
    ]
    if app_base_url:
        lines += ["", app_base_url]
    return "\n".join(lines) + "\n"


def _print_staging_noop(to_email: str, activate_url: str, reason: str) -> None:
    print(f"[MAILER] STAGING no-op ({reason}); email TIDAK dikirim.")
    print(f"[MAILER] penerima     : {mask_email(to_email)}")
    print(f"[MAILER] link aktivasi: {activate_url}")


async def send_invite_email(to_email: str, activate_url: str, app_base_url: str) -> tuple[bool, str]:
    """Kirim email undangan aktivasi. Lihat docstring modul untuk status kembalian."""
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        print("[MAILER] penerima tidak valid; email tidak dikirim.")
        return (False, STATUS_FAILED)

    # MAIL_ENABLED / MAIL_ALLOWLIST hanya dievaluasi di staging; di produksi
    # diabaikan. Untuk mematikan pengiriman produksi, kosongkan BREVO_API_KEY.
    if is_staging_mode():
        if not settings.mail_enabled:
            _print_staging_noop(to_email, activate_url, "MAIL_ENABLED=false")
            return (False, STATUS_SKIPPED)
        if to_email.lower() not in parse_allowlist(settings.mail_allowlist):
            _print_staging_noop(to_email, activate_url, "penerima tidak di MAIL_ALLOWLIST")
            return (False, STATUS_SKIPPED)

    api_key = (settings.brevo_api_key or "").strip()
    from_email = (settings.mail_from_email or "").strip()
    from_name = (settings.mail_from_name or "").strip() or DEFAULT_FROM_NAME
    if not api_key or not from_email:
        print("[MAILER] konfigurasi belum lengkap (BREVO_API_KEY / MAIL_FROM_EMAIL).")
        return (False, STATUS_FAILED)

    try:
        html_content = render_invite_email(activate_url, app_base_url)
        text_content = render_invite_text(activate_url, app_base_url)
    except Exception as exc:  # noqa: BLE001
        print(f"[MAILER] gagal render template email ({type(exc).__name__}).")
        return (False, STATUS_FAILED)

    payload = {
        "sender": {"name": from_name, "email": from_email},
        "to": [{"email": to_email}],
        "subject": EMAIL_SUBJECT,
        "htmlContent": html_content,
        "textContent": text_content,
    }
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
        "accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(BREVO_ENDPOINT, json=payload, headers=headers)
    except httpx.TimeoutException:
        print(f"[MAILER] timeout {REQUEST_TIMEOUT_SECONDS:.0f}s ke Brevo — status unknown "
              f"(mungkin sudah terkirim). penerima={mask_email(to_email)}")
        return (False, STATUS_UNKNOWN)
    except Exception as exc:  # noqa: BLE001
        print(f"[MAILER] error koneksi ke Brevo ({type(exc).__name__}).")
        return (False, STATUS_FAILED)

    if 200 <= resp.status_code < 300:
        message_id = ""
        try:
            body = resp.json()
            if isinstance(body, dict):
                message_id = str(body.get("messageId") or "")
        except Exception:  # noqa: BLE001
            pass
        print(f"[MAILER] email terkirim ke {mask_email(to_email)} "
              f"(HTTP {resp.status_code}, messageId={message_id[:8] or '-'})")
        return (True, STATUS_SENT)

    # Jangan cetak body respons penuh (bisa memuat data sensitif).
    print(f"[MAILER] Brevo menolak (HTTP {resp.status_code}). penerima={mask_email(to_email)}")
    return (False, STATUS_FAILED)
