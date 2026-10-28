"""Authenticated profile and self-service password routes."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse


WIB = ZoneInfo("Asia/Jakarta")
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 72

STATUS_MESSAGES = {
    "password_changed": "Password berhasil diubah. Sesi di perangkat lain dapat tetap aktif sampai JWT kedaluwarsa.",
}
ERROR_MESSAGES = {
    "password_invalid": "Password baru harus 6–72 karakter dan berbeda dari password lama.",
    "password_mismatch": "Konfirmasi password baru tidak cocok.",
    "current_password_invalid": "Password lama tidak valid.",
    "password_failed": "Password tidak dapat diubah. Silakan coba lagi.",
}

ACTION_LABELS = {
    "create": "Created",
    "update": "Updated",
    "delete": "Deleted",
    "change_password": "Changed password",
    "reset_password": "Reset password",
    "upload": "Uploaded",
    "export": "Exported",
    "generate": "Generated",
    "restore": "Restored",
    "complete": "Completed",
    "reopen": "Reopened",
}
MONTHS_ID = (
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
)


def _format_created_at(value) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=WIB)
        local = parsed.astimezone(WIB)
        return f"{local.day} {MONTHS_ID[local.month - 1]} {local.year}, {local:%H:%M} WIB"
    except (TypeError, ValueError):
        return "-"


def _activity_row(row: dict) -> dict:
    created_at = row.get("created_at")
    return {
        "action": row.get("action") or "activity",
        "action_label": ACTION_LABELS.get(row.get("action"), "Activity"),
        "entity_type": row.get("entity_type") or "",
        "entity_label": row.get("entity_label") or "",
        "outcome": row.get("outcome") or "success",
        "created_at": created_at,
        "created_label": _format_created_at(created_at),
    }


def register_profile_routes(
    app,
    get_current_user,
    supabase,
    templates,
    log_activity,
    limiter,
    staging_client,
):
    @app.get("/profile", response_class=HTMLResponse)
    async def profile_page(
        request: Request,
        current_user: dict = Depends(get_current_user),
    ):
        created_at = None
        try:
            auth_response = supabase.auth.admin.get_user_by_id(current_user["id"])
            auth_user = getattr(auth_response, "user", None)
            created_at = getattr(auth_user, "created_at", None)
        except Exception:
            created_at = None

        activity = []
        activity_error = False
        try:
            response = (
                supabase.table("activity_logs")
                .select("action, entity_type, entity_label, outcome, created_at")
                .eq("actor_id", current_user["id"])
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            activity = [_activity_row(row) for row in (response.data or [])]
        except Exception:
            activity_error = True

        status_code = request.query_params.get("status")
        error_code = request.query_params.get("error")
        return templates.TemplateResponse(
            request=request,
            name="profile.html",
            context={
                "request": request,
                "user": current_user,
                "current_user": current_user,
                "account_created": _format_created_at(created_at),
                "activity": activity,
                "activity_error": activity_error,
                "success_msg": STATUS_MESSAGES.get(status_code),
                "error_msg": ERROR_MESSAGES.get(error_code),
                "ed_notification_count": 0,
            },
        )

    @app.post("/profile/change-password")
    @limiter.limit("5/minute")
    async def change_password(
        request: Request,
        current_password: str = Form(""),
        new_password: str = Form(""),
        confirm_new_password: str = Form(""),
        current_user: dict = Depends(get_current_user),
    ):
        if not current_password or not new_password or not confirm_new_password:
            return RedirectResponse(url="/profile?error=password_invalid", status_code=303)
        if (
            len(new_password) < MIN_PASSWORD_LENGTH
            or len(new_password) > MAX_PASSWORD_LENGTH
            or new_password == current_password
        ):
            return RedirectResponse(url="/profile?error=password_invalid", status_code=303)
        if new_password != confirm_new_password:
            return RedirectResponse(url="/profile?error=password_mismatch", status_code=303)

        login_client = None
        try:
            login_client = staging_client("profile_password")
            login_client.auth.sign_in_with_password({
                "email": current_user.get("email"),
                "password": current_password,
            })
        except Exception:
            return RedirectResponse(url="/profile?error=current_password_invalid", status_code=303)
        finally:
            # supabase-py has no public close API; release the temporary client
            # reference and never reuse it for service-role operations.
            login_client = None

        try:
            supabase.auth.admin.update_user_by_id(
                current_user["id"],
                {"password": new_password},
            )
            log_activity(
                current_user,
                "change_password",
                "user",
                current_user["id"],
                current_user.get("full_name") or "Current user",
                changes=[{"field": "Password", "note": "changed by self (value not recorded)"}],
                request=request,
                outcome="success",
            )
            return RedirectResponse(url="/profile?status=password_changed", status_code=303)
        except Exception:
            return RedirectResponse(url="/profile?error=password_failed", status_code=303)
