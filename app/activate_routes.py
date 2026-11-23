"""Route publik aktivasi akun undangan (GET/POST /activate)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.profile_validation import validate_display_name

WIB = ZoneInfo("Asia/Jakarta")
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 72
ALLOWED_ACTIVATION_TYPES = frozenset({"invite"})
ACTIVATE_GET_LIMIT = "20/minute"
ACTIVATE_POST_LIMIT = "10/minute"

GENERIC_ACTIVATION_ERROR = (
    "Link tidak valid, sudah kedaluwarsa, atau aktivasi tidak dapat diselesaikan. "
    "Minta admin mengirim ulang atau membatalkan dan mengundang ulang."
)


def is_valid_activation_type(link_type: str) -> bool:
    """Whitelist tipe tautan aktivasi: hanya ``invite`` yang diterima."""
    return (link_type or "").strip() in ALLOWED_ACTIVATION_TYPES


def validate_activation_password(password: str, confirm_password: str) -> str | None:
    """Validasi password aktivasi sesuai kebijakan 6..72 karakter."""
    if not password or len(password) < MIN_PASSWORD_LENGTH or len(password.strip()) < MIN_PASSWORD_LENGTH:
        return f"Password minimal {MIN_PASSWORD_LENGTH} karakter."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password maksimal {MAX_PASSWORD_LENGTH} karakter."
    if password != confirm_password:
        return "Konfirmasi password tidak cocok."
    return None


def create_disposable_verify_client():
    """Buat client Supabase baru sekali pakai untuk ``verify_otp`` (dibuang setelah pakai)."""
    import supabase as supabase_pkg
    from supabase.lib.client_options import SyncClientOptions

    from app.config import settings
    from app.staging_guard import assert_allowed_target

    assert_allowed_target("activate_verify_otp")
    url = (settings.supabase_url or "").strip()
    key = (settings.supabase_service_role_key or "").strip()
    if not url or not key:
        raise RuntimeError("[ACTIVATE] konfigurasi Supabase tidak lengkap.")
    return supabase_pkg.create_client(
        url,
        key,
        options=SyncClientOptions(auto_refresh_token=False, persist_session=False),
    )


def _apply_no_store_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def activate_rate_limit_response(request: Request):
    """Respons 429 untuk ``/activate`` tanpa redirect login dan tanpa membocorkan token."""
    headers = {
        "Retry-After": "60",
        "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex, nofollow",
    }
    accept = (request.headers.get("accept") or "").lower()
    if "text/html" in accept:
        html_body = (
            "<!DOCTYPE html>"
            '<html lang="id"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
            "<title>Terlalu Banyak Percobaan — DIP Automation System</title>"
            "<style>"
            "body{font-family:Segoe UI,Roboto,Arial,sans-serif;background:#f8fafc;color:#1e293b;"
            "margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;}"
            ".card{max-width:440px;width:100%;background:#fff;border:1px solid #e2e8f0;"
            "border-radius:12px;padding:28px;box-shadow:0 4px 16px rgba(15,23,42,.06);}"
            "h1{margin:0 0 10px;font-size:18px;color:#991b1b;}"
            "p{margin:0 0 16px;font-size:14px;line-height:1.6;color:#475569;}"
            "a{color:#b45309;font-size:14px;font-weight:600;text-decoration:none;}"
            "</style></head><body><main class=\"card\">"
            "<h1>Terlalu Banyak Percobaan</h1>"
            "<p>Terlalu banyak permintaan aktivasi dari koneksi Anda. "
            "Tunggu 60 detik, lalu kembali dan coba kirim ulang formulir Anda.</p>"
            '<a href="/login">Kembali ke Halaman Login</a>'
            "</main></body></html>"
        )
        return HTMLResponse(status_code=429, content=html_body, headers=headers)
    return JSONResponse(
        status_code=429,
        content={"detail": "Terlalu banyak percobaan, coba lagi dalam 60 detik."},
        headers=headers,
    )


def register_activate_routes(
    app,
    supabase,
    templates,
    log_activity,
    mask_email,
    limiter,
    verify_client_factory=create_disposable_verify_client,
):
    """Daftarkan endpoint publik aktivasi undangan GET/POST ``/activate``."""

    def _render(
        request: Request,
        *,
        status_code: int,
        token_hash: str = "",
        display_name: str = "",
        error_msg: str | None = None,
        invalid_link: bool = False,
    ) -> HTMLResponse:
        resp = templates.TemplateResponse(
            request=request,
            name="activate.html",
            context={
                "request": request,
                "token_hash": token_hash,
                "link_type": "invite",
                "display_name": display_name,
                "error_msg": error_msg,
                "invalid_link": invalid_link,
            },
            status_code=status_code,
        )
        return _apply_no_store_headers(resp)

    @app.get("/activate", response_class=HTMLResponse)
    @limiter.limit(ACTIVATE_GET_LIMIT)
    async def activate_page(
        request: Request,
        token_hash: str = "",
        link_type: str = Query("", alias="type"),
    ):
        clean_token = (token_hash or "").strip()
        clean_type = (link_type or "").strip()
        if not is_valid_activation_type(clean_type) or not clean_token:
            return _render(
                request,
                status_code=404,
                error_msg=GENERIC_ACTIVATION_ERROR,
                invalid_link=True,
            )
        return _render(
            request,
            status_code=200,
            token_hash=clean_token,
            invalid_link=False,
        )

    @app.post("/activate", response_class=HTMLResponse)
    @limiter.limit(ACTIVATE_POST_LIMIT)
    async def activate_submit(
        request: Request,
        token_hash: str = Form(""),
        link_type: str = Form("", alias="type"),
        display_name: str = Form(""),
        password: str = Form(""),
        confirm_password: str = Form(""),
    ):
        clean_token = (token_hash or "").strip()
        clean_type = (link_type or "").strip()

        # (a) Validasi tipe, token, password, dan display_name SEBELUM verify_otp.
        if not is_valid_activation_type(clean_type) or not clean_token:
            return _render(
                request,
                status_code=404,
                error_msg=GENERIC_ACTIVATION_ERROR,
                invalid_link=True,
            )

        pw_err = validate_activation_password(password, confirm_password)
        if pw_err:
            return _render(
                request,
                status_code=400,
                token_hash=clean_token,
                display_name=display_name,
                error_msg=pw_err,
                invalid_link=False,
            )

        cleaned_display_name, dn_err = validate_display_name(display_name)
        if dn_err:
            return _render(
                request,
                status_code=400,
                token_hash=clean_token,
                display_name=display_name,
                error_msg=dn_err,
                invalid_link=False,
            )

        # (b) verify_otp via client BARU sekali pakai (bukan supabase global).
        verify_client = None
        try:
            verify_client = verify_client_factory()
            verify_res = verify_client.auth.verify_otp(
                {"token_hash": clean_token, "type": "invite"}
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[ACTIVATE] verify_otp gagal: {type(exc).__name__}")
            return _render(
                request,
                status_code=400,
                error_msg=GENERIC_ACTIVATION_ERROR,
                invalid_link=True,
            )
        finally:
            verify_client = None

        if verify_res is None:
            return _render(
                request,
                status_code=400,
                error_msg=GENERIC_ACTIVATION_ERROR,
                invalid_link=True,
            )

        # (c) Ambil user.id + user.email dan baca profil via client admin bersih.
        auth_user = getattr(verify_res, "user", None)
        uid = (getattr(auth_user, "id", None) or "").strip()
        auth_email = (getattr(auth_user, "email", None) or "").strip().lower()
        if not uid or not auth_email:
            return _render(
                request,
                status_code=400,
                error_msg=GENERIC_ACTIVATION_ERROR,
                invalid_link=True,
            )

        try:
            prof_res = (
                supabase.table("profiles")
                .select("id, full_name, status, invited_email")
                .eq("id", uid)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[ACTIVATE] gagal baca profil uid={uid}: {type(exc).__name__}")
            return _render(
                request,
                status_code=400,
                error_msg=GENERIC_ACTIVATION_ERROR,
                invalid_link=True,
            )

        rows = prof_res.data or []
        if not rows:
            return _render(
                request,
                status_code=400,
                error_msg=GENERIC_ACTIVATION_ERROR,
                invalid_link=True,
            )

        profile = rows[0] or {}
        invited_email = (profile.get("invited_email") or "").strip().lower()
        if profile.get("status") != "pending" or invited_email != auth_email:
            return _render(
                request,
                status_code=400,
                error_msg=GENERIC_ACTIVATION_ERROR,
                invalid_link=True,
            )

        username = profile.get("full_name") or f"User {uid}"

        # (d) Klaim atomik pending -> active. invited_at TIDAK pernah diubah/NULL.
        update_payload = {
            "status": "active",
            "updated_at": datetime.now(WIB).isoformat(),
        }
        if cleaned_display_name is not None:
            update_payload["display_name"] = cleaned_display_name

        try:
            claim_res = (
                supabase.table("profiles")
                .update(update_payload)
                .eq("id", uid)
                .eq("status", "pending")
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[ACTIVATE] klaim atomik profil gagal uid={uid}: {type(exc).__name__}")
            return _render(
                request,
                status_code=400,
                error_msg=GENERIC_ACTIVATION_ERROR,
                invalid_link=True,
            )

        if not (claim_res.data or []):
            return _render(
                request,
                status_code=400,
                error_msg=GENERIC_ACTIVATION_ERROR,
                invalid_link=True,
            )

        actor_user = {
            "id": uid,
            "full_name": username,
            "email": mask_email(auth_email),
            "role": "staff",
        }

        # (e) Set password via client admin bersih.
        try:
            supabase.auth.admin.update_user_by_id(uid, {"password": password})
        except Exception as exc:  # noqa: BLE001
            # (f) Kompensasi kondisional status kembali pending.
            print(f"[ACTIVATE] update_user_by_id gagal uid={uid}: {type(exc).__name__}")
            try:
                (
                    supabase.table("profiles")
                    .update({"status": "pending", "updated_at": datetime.now(WIB).isoformat()})
                    .eq("id", uid)
                    .eq("status", "active")
                    .execute()
                )
            except Exception as comp_exc:  # noqa: BLE001
                print(f"[ACTIVATE] gagal kompensasi pending uid={uid}: {type(comp_exc).__name__}")
            log_activity(
                actor_user,
                "activate",
                "user",
                uid,
                username,
                changes=[
                    {"field": "Status", "old": "pending", "new": "pending"},
                    {
                        "field": "Error",
                        "note": "gagal menyetel password; status dikembalikan pending (perlu Batalkan & undang ulang)",
                    },
                ],
                request=request,
                outcome="failed",
            )
            return _render(
                request,
                status_code=400,
                error_msg=GENERIC_ACTIVATION_ERROR,
                invalid_link=True,
            )

        # (g) Catat aktivasi sukses (tanpa password/email mentah) & redirect ke login.
        changes = [
            {"field": "Status", "old": "pending", "new": "active"},
            {"field": "Password", "note": "disetel saat aktivasi (nilai tidak dicatat)"},
        ]
        if cleaned_display_name is not None:
            changes.append({"field": "Display Name", "new": cleaned_display_name})

        log_activity(
            actor_user,
            "activate",
            "user",
            uid,
            username,
            changes=changes,
            request=request,
            outcome="success",
        )
        redirect = RedirectResponse(url="/login?status=account_activated", status_code=303)
        return _apply_no_store_headers(redirect)
