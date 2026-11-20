"""Admin user management routes (extracted from main.py)."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import mailer
from app.config import settings

WIB = ZoneInfo("Asia/Jakarta")

# Batas percobaan alokasi username saat bentrok unique index lower(full_name).
INVITE_MAX_USERNAME_ATTEMPTS = 3

# Jendela bukti "user Auth baru dibuat request ini" untuk kompensasi hapus Auth.
INVITE_NEW_USER_WINDOW_SECONDS = 60

# Jeda minimum kirim ulang undangan dari waktu invited_at terakhir.
INVITE_RESEND_COOLDOWN_SECONDS = 60

# Validator format email sederhana (pola sama semangat dengan validasi existing).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

# Constraint yang menandakan bentrok identitas -> perlakukan sebagai email_exists.
_CONSTRAINT_USERNAME = "idx_profiles_full_name_lower_unique"
_CONSTRAINT_PENDING_EMAIL = "idx_profiles_invited_email_pending_unique"
_CONSTRAINT_PK = "profiles_pkey"


def is_valid_email(email: str) -> bool:
    """Validasi format email minimal (tanpa DNS/verify)."""
    return bool(_EMAIL_RE.match((email or "").strip()))


def constraint_name_of(exc: Exception) -> str:
    """Ambil nama constraint dari pesan error Postgres/PostgREST bila ada."""
    match = re.search(r'constraint\s+"([^"]+)"', str(exc))
    if match:
        return match.group(1)
    return ""


def is_proven_new_auth_user(
    created_at,
    now: datetime | None = None,
    window_seconds: int = INVITE_NEW_USER_WINDOW_SECONDS,
) -> bool:
    """True bila `created_at` berada dalam ±window detik dari `now`.

    Dipakai sebagai bukti bahwa user Auth benar-benar dibuat oleh request ini
    sebelum mengizinkan penghapusan kompensasi.
    """
    if not created_at:
        return False
    if isinstance(created_at, datetime):
        created = created_at
    else:
        try:
            text = str(created_at).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            created = datetime.fromisoformat(text)
        except Exception:  # noqa: BLE001
            return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return abs((reference - created).total_seconds()) <= window_seconds


def should_delete_auth_user(supabase, uid: str, created_at) -> bool:
    """True hanya bila user Auth terbukti baru DAN belum punya baris profiles.

    Kompensasi hapus Auth dibatasi (BE-05): bila salah satu bukti tidak
    terpenuhi, pemanggil harus memperlakukan akun sebagai yatim (flag only).
    """
    if not is_proven_new_auth_user(created_at, datetime.now(timezone.utc)):
        return False
    try:
        res = supabase.table("profiles").select("id").eq("id", uid).execute()
    except Exception:  # noqa: BLE001
        return False
    return not bool(res.data)


def resend_cooldown_remaining(
    invited_at,
    now: datetime | None = None,
    cooldown_seconds: int = INVITE_RESEND_COOLDOWN_SECONDS,
) -> int:
    """Sisa waktu jeda resend (detik); 0 jika sudah boleh kirim ulang."""
    if not invited_at:
        return 0
    if isinstance(invited_at, datetime):
        invited_dt = invited_at
    else:
        try:
            text = str(invited_at).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            invited_dt = datetime.fromisoformat(text)
        except Exception:  # noqa: BLE001
            return 0
    if invited_dt.tzinfo is None:
        invited_dt = invited_dt.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    elapsed = (reference - invited_dt).total_seconds()
    if elapsed >= cooldown_seconds:
        return 0
    if elapsed < 0:
        return cooldown_seconds
    return int(math.ceil(cooldown_seconds - elapsed))


def register_admin_users_routes(
    app,
    get_current_user,
    supabase,
    templates,
    log_activity,
    compute_user_presence,
    mask_email,
    _user_label,
    _user_role_and_label,
    get_ed_notification_count,
    compute_status_na,
    limiter,
):
    # =====================================================================
    #                     MODUL MANAJEMEN USER (ADMIN ONLY)
    # =====================================================================

    # 1. TAMPILAN HALAMAN UTAMA USER & REGISTER
    @app.get("/admin/users", response_class=HTMLResponse)
    async def manage_users_page(request: Request, current_user: dict = Depends(get_current_user)):
        # Proteksi: Cuma admin yang boleh masuk page ini
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Super Admin.")

        try:
            # Tarik semua data dari tabel profiles
            profiles_res = supabase.table("profiles").select("*").order("full_name").execute()
            users_list = profiles_res.data or []

            # Sembunyikan akun yang di-protect dari admin lain -- akun itu cuma bisa
            # lihat dirinya sendiri di list, admin lain sama sekali gak lihat baris ini
            users_list = [
                u for u in users_list
                if not u.get("is_protected") or u["id"] == current_user["id"]
            ]
            for u in users_list:
                presence = compute_user_presence(u)
                u["is_online"] = presence["is_online"]
                u["is_idle"] = presence["is_idle"]
                u["presence_status"] = presence["presence_status"]
                u["last_seen_label"] = presence["last_seen_label"]
                u["last_seen_at"] = presence["last_seen_at"]
                u["last_activity_label"] = presence["last_activity_label"]
            online_count = sum(1 for u in users_list if u.get("presence_status") == "online")
            idle_count = sum(1 for u in users_list if u.get("presence_status") == "idle")
            offline_count = len(users_list) - online_count - idle_count
        except Exception as e:
            print(f"Gagal ambil data profiles: {e}")
            users_list = []
            online_count = 0
            idle_count = 0
            offline_count = 0

        return templates.TemplateResponse(
            request=request,
            name="admin_users.html",
            context={
                "request": request,
                "user": current_user,
                "current_user": current_user,
                "users": users_list,
                "online_count": online_count,
                "idle_count": idle_count,
                "offline_count": offline_count,
            }
        )

    # CATATAN: Self-register publik (GET/POST /register) sengaja DIHAPUS.
    # Alasan: app internal perusahaan dengan data sensitif (formula, harga, dokumen regulasi).
    # Pembuatan akun sekarang cuma bisa lewat admin, lihat POST /admin/users/create di bawah.

    # 1. PROSES ADMIN BIKIN AKUN USER BARU (KHUSUS ADMIN)
    @app.post("/admin/users/create")
    async def admin_create_user(
        request: Request,
        email: str = Form(...),
        username: str = Form(...),
        password: str = Form(...),
        role: str = Form("staff"),
        current_user: dict = Depends(get_current_user)
    ):
        # Proteksi: cuma admin yang boleh bikin akun baru
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Super Admin.")

        try:
            clean_username = username.strip().lower()
            clean_email = email.strip().lower()

            # BE-12: policy password saat create akun — minimal 6 karakter, sama
            # dengan aturan reset-password dan minlength form modal.
            if len(password.strip()) < 6:
                log_activity(
                    current_user, "create", "user", None, clean_username,
                    changes=[{"field": "Password", "note": "password terlalu pendek (< 6 karakter)"}],
                    request=request, outcome="rejected",
                )
                return RedirectResponse(url="/admin/users?error=password_too_short", status_code=303)

            # VALIDASI: Username wajib unik (case-insensitive). Login via username memakai
            # kolom full_name di tabel profiles, jadi kalau dobel, login bisa ambigu.
            existing_profiles = supabase.table("profiles").select("full_name").execute()
            existing_usernames = {str(pf.get("full_name") or "").strip().lower() for pf in (existing_profiles.data or [])}
            if clean_username in existing_usernames:
                print(f"Tolak buat akun: username '{clean_username}' sudah dipakai.")
                # Dicatat sebagai 'rejected': percobaan membuat akun yang bentrok adalah
                # sinyal keamanan, sama pentingnya dicatat sebagai keberhasilan.
                log_activity(
                    current_user, "create", "user", None, clean_username,
                    changes=[{"field": "Username", "note": "sudah dipakai akun lain"}],
                    request=request, outcome="rejected",
                )
                return RedirectResponse(url="/admin/users?error=username_exists", status_code=303)

            # Daftarin ke Supabase Auth Service, langsung confirmed (dibuat admin, bukan self-register)
            auth_res = supabase.auth.admin.create_user({
                "email": clean_email,
                "password": password,
                "email_confirm": True
            })

            new_uid = auth_res.user.id

            # Inject ke tabel profiles dengan role yang dipilih admin (default staff).
            # display_name diisi dengan clean_username[:60] (sesuai constraint DB)
            # agar akun baru punya nama tampilan default yang sama dengan username.
            final_role = role if role in ("staff", "admin") else "staff"
            try:
                supabase.table("profiles").insert({
                    "id": new_uid,
                    "full_name": clean_username,
                    "display_name": clean_username[:60],
                    "role": final_role,
                    # Jangan pakai string "now()" (PostgREST simpan sebagai literal & bisa gagal cast ke timestamptz).
                    # Kirim timestamp ISO nyata dari Python.
                    "updated_at": datetime.now(WIB).isoformat()
                }).execute()
            except Exception as insert_err:
                # BE-05: akun auth TERLANJIR terbentuk tapi insert profiles gagal ->
                # akun yatim (email terblokir "already registered", tak tampil di
                # /admin/users). Kebijakan: TIDAK menghapus akun auth otomatis;
                # marker eksplisit untuk bersih-bersih manual pemilik repo.
                print(
                    f"[AKUN AUTH YATIM] uid={new_uid} email={mask_email(clean_email)} "
                    f"username={clean_username} - akun Auth terbentuk tetapi baris profiles "
                    f"gagal dibuat; perlu tindakan manual via Supabase Auth Admin. "
                    f"Detail: {insert_err}"
                )
                log_activity(
                    current_user, "create", "user", new_uid, clean_username,
                    changes=[
                        {"field": "Email", "new": mask_email(clean_email)},
                        {"field": "Role", "new": final_role},
                        {"field": "Error", "note": "akun Auth terbentuk tetapi profil gagal dibuat; "
                                                   "akun auth perlu dibersihkan manual oleh admin"},
                    ],
                    request=request, outcome="failed",
                )
                return RedirectResponse(url="/admin/users?error=create_failed", status_code=303)

            # Ambil perusahaan account agar tercatat penuh di audit.
            new_perusahaan = None
            try:
                prof_res = supabase.table("profiles").select("perusahaan").eq("id", new_uid).execute()
                new_perusahaan = prof_res.data[0].get("perusahaan") if prof_res.data else None
            except Exception:
                pass

            # CATATAN: password SENGAJA TIDAK pernah masuk changes / entity_label.
            # Email disamarkan sebagian sesuai kebijakan redaksi data.
            log_activity(
                current_user, "create", "user", new_uid, clean_username,
                changes=[
                    {"field": "Username", "new": clean_username},
                    {"field": "Email", "new": mask_email(clean_email)},
                    {"field": "Display Name", "new": clean_username[:60]},
                    {"field": "Role", "new": final_role},
                    {"field": "Perusahaan", "new": new_perusahaan},
                ],
                request=request, outcome="success",
            )

            return RedirectResponse(url="/admin/users?status=create_success", status_code=303)

        except Exception as e:
            print(f"Gagal bikin user baru (admin): {e}")
            error_str = str(e).lower()
            dup_email = ("already been registered" in error_str
                         or "already registered" in error_str
                         or "user already exists" in error_str)
            try:
                log_activity(
                    current_user, "create", "user", None,
                    (username or "").strip().lower(),
                    changes=[{"field": "Email",
                              "note": "sudah terdaftar di Auth" if dup_email
                                      else "gagal membuat akun"}],
                    request=request,
                    outcome="rejected" if dup_email else "failed",
                )
            except Exception:
                pass
            if dup_email:
                return RedirectResponse(url="/admin/users?error=email_exists", status_code=303)
            return RedirectResponse(url="/admin/users?error=create_failed", status_code=303)

    # 1b. UNDANG USER BARU VIA EMAIL (KHUSUS ADMIN)
    @app.post("/admin/users/invite")
    @limiter.limit("3/minute")
    async def admin_invite_user(
        request: Request,
        email: str = Form(...),
        current_user: dict = Depends(get_current_user)
    ):
        """Buat user Auth pending lalu kirim email undangan aktivasi.

        Endpoint ini TIDAK PERNAH menyetel password dan TIDAK PERNAH memanggil
        ``update_user_by_id``. ``generate_link(type="invite")`` sudah membuat user
        Auth dalam keadaan pending; password diisi sendiri oleh user di halaman
        aktivasi.
        """
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Super Admin.")

        clean_email = (email or "").strip().lower()
        masked_email = (
            mask_email(clean_email)
            if "@" in clean_email
            else ("(tidak valid)" if clean_email else "(kosong)")
        )

        def _compensate_auth_user(
            target_uid: str,
            target_created_at,
            target_username: str,
            reason_detail: str,
        ) -> None:
            if should_delete_auth_user(supabase, target_uid, target_created_at):
                try:
                    supabase.auth.admin.delete_user(target_uid)
                    print(f"[INVITE] kompensasi: user Auth {target_uid} dihapus (terbukti baru).")
                except Exception as exc:  # noqa: BLE001
                    print(f"[INVITE] gagal hapus Auth kompensasi uid={target_uid}: {exc}")
            else:
                print(
                    f"[AKUN AUTH YATIM] uid={target_uid} email={masked_email} "
                    f"username={target_username} - {reason_detail}"
                )

        # Guard fail-closed APP_BASE_URL: tanpa base URL tautan aktivasi tidak bisa
        # dibentuk, jadi batalkan SEBELUM membuat user Auth atau mengirim email.
        app_base_url = (getattr(settings, "app_base_url", "") or "").strip()
        if not app_base_url:
            print("[INVITE] APP_BASE_URL belum diset; invite dibatalkan sebelum membuat user.")
            log_activity(
                current_user, "invite", "user", None, masked_email,
                changes=[{"field": "Email",
                          "note": "APP_BASE_URL belum diset; invite dibatalkan"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=invite_not_configured", status_code=303)

        if not is_valid_email(clean_email):
            invalid_label = "(kosong)" if not clean_email else "(tidak valid)"
            log_activity(
                current_user, "invite", "user", None, invalid_label,
                changes=[{"field": "Email", "note": "format email tidak valid"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=invalid_email", status_code=303)

        # Dedupe 1: Auth (RPC SECURITY DEFINER). Gagal -> fail-closed.
        try:
            auth_exists = bool(
                supabase.rpc("auth_email_exists", {"p_email": clean_email}).execute().data
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[INVITE] RPC auth_email_exists gagal: {exc}")
            log_activity(
                current_user, "invite", "user", None, masked_email,
                changes=[{"field": "Email", "note": "dedupe Auth gagal (fail-closed)"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=invite_failed", status_code=303)

        if auth_exists:
            log_activity(
                current_user, "invite", "user", None, masked_email,
                changes=[{"field": "Email", "note": "sudah terdaftar di Auth"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=email_exists", status_code=303)

        # Dedupe 2: profiles.invited_email (case-insensitive, hanya yang pending). Fail-closed.
        try:
            pending_res = (
                supabase.table("profiles")
                .select("id, invited_email")
                .eq("status", "pending")
                .execute()
            )
            pending_emails = {
                str(row.get("invited_email") or "").strip().lower()
                for row in (pending_res.data or [])
            }
        except Exception as exc:  # noqa: BLE001
            print(f"[INVITE] cek profiles.invited_email gagal: {exc}")
            log_activity(
                current_user, "invite", "user", None, masked_email,
                changes=[{"field": "Email", "note": "dedupe pending gagal (fail-closed)"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=invite_failed", status_code=303)

        if clean_email in pending_emails:
            log_activity(
                current_user, "invite", "user", None, masked_email,
                changes=[{"field": "Email", "note": "sudah ada undangan pending"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=email_exists", status_code=303)

        # Alokasi username (RPC). Dipakai sebagai full_name sekaligus display_name.
        try:
            username = str(supabase.rpc("next_invite_username").execute().data or "").strip()
        except Exception as exc:  # noqa: BLE001
            print(f"[INVITE] RPC next_invite_username gagal: {exc}")
            username = ""

        if not username:
            log_activity(
                current_user, "invite", "user", None, masked_email,
                changes=[{"field": "Email", "note": "alokasi username gagal"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=invite_failed", status_code=303)

        # Buat user Auth pending. generate_link TIDAK PERNAH diulang di request ini.
        try:
            link_res = supabase.auth.admin.generate_link({
                "type": "invite",
                "email": clean_email,
                "options": {"data": {"username": username}},
            })
            uid = link_res.user.id
            created_at = getattr(link_res.user, "created_at", None)
            hashed_token = getattr(link_res.properties, "hashed_token", None)
        except Exception as exc:  # noqa: BLE001
            message = str(exc).lower()
            if ("already" in message and "registered" in message) or "user already exists" in message:
                log_activity(
                    current_user, "invite", "user", None, masked_email,
                    changes=[{"field": "Email", "note": "sudah terdaftar di Auth"}],
                    request=request, outcome="rejected",
                )
                return RedirectResponse(url="/admin/users?error=email_exists", status_code=303)
            print(f"[INVITE] generate_link gagal: {exc}")
            log_activity(
                current_user, "invite", "user", None, masked_email,
                changes=[{"field": "Email", "note": "generate_link gagal"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=invite_failed", status_code=303)

        if not uid or not hashed_token:
            print("[INVITE] generate_link tidak mengembalikan user.id / hashed_token.")
            if uid:
                _compensate_auth_user(
                    uid,
                    created_at,
                    username,
                    "akun Auth terbentuk tetapi hashed_token kosong; perlu tindakan manual.",
                )
            log_activity(
                current_user, "invite", "user", uid, username or masked_email,
                changes=[
                    {"field": "Email", "new": masked_email},
                    {"field": "Error", "note": "respons generate_link tidak lengkap"},
                ],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=invite_failed", status_code=303)

        # Insert profil dengan retry HANYA untuk bentrok username.
        # `perusahaan` sengaja TIDAK diset (NULL) -- sama semantik dengan
        # POST /admin/users/create yang membacanya kembali setelah insert.
        insert_error = None
        for attempt in range(1, INVITE_MAX_USERNAME_ATTEMPTS + 1):
            payload = {
                "id": uid,
                "full_name": username,
                "display_name": username[:60],
                "role": "staff",
                "status": "pending",
                "invited_email": clean_email,
                "invited_at": datetime.now(WIB).isoformat(),
                "invited_by": current_user["id"],
                "updated_at": datetime.now(WIB).isoformat(),
            }
            try:
                supabase.table("profiles").insert(payload).execute()
                insert_error = None
                break
            except Exception as exc:  # noqa: BLE001
                insert_error = exc
                constraint = constraint_name_of(exc)
                if constraint == _CONSTRAINT_USERNAME and attempt < INVITE_MAX_USERNAME_ATTEMPTS:
                    try:
                        username = str(
                            supabase.rpc("next_invite_username").execute().data or ""
                        ).strip()
                    except Exception:  # noqa: BLE001
                        break
                    if not username:
                        break
                    continue
                break

        if insert_error is not None:
            constraint = constraint_name_of(insert_error)
            if constraint in (_CONSTRAINT_PK, _CONSTRAINT_PENDING_EMAIL):
                # Jangan retry; perlakukan sebagai email_exists. Auth/profile yang
                # sudah ada TIDAK boleh dihapus.
                log_activity(
                    current_user, "invite", "user", uid, username or masked_email,
                    changes=[{"field": "Email", "note": "bentrok email/UID (email_exists)"}],
                    request=request, outcome="rejected",
                )
                return RedirectResponse(url="/admin/users?error=email_exists", status_code=303)

            # Non-retryable: kompensasi hanya bila user Auth terbukti baru dibuat
            # request ini DAN belum punya baris profiles. Bila ragu -> BE-05.
            _compensate_auth_user(
                uid,
                created_at,
                username,
                f"akun Auth terbentuk tetapi baris profiles gagal dibuat; perlu tindakan manual. Detail: {insert_error}",
            )
            log_activity(
                current_user, "invite", "user", uid, username or masked_email,
                changes=[
                    {"field": "Username", "new": username},
                    {"field": "Email", "new": masked_email},
                    {"field": "Error", "note": "insert profil gagal; invite dibatalkan"},
                ],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=invite_failed", status_code=303)

        # Kirim email. Gagal/timeout TIDAK menghapus akun/profil.
        activate_url = f"{app_base_url.rstrip('/')}/activate?token_hash={hashed_token}&type=invite"
        try:
            _mail_ok, mail_status = await mailer.send_invite_email(
                to_email=clean_email,
                activate_url=activate_url,
                app_base_url=app_base_url,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[INVITE] mailer exception: {exc}")
            mail_status = mailer.STATUS_FAILED

        if mail_status == mailer.STATUS_UNKNOWN:
            redirect_status = "invite_unknown"
        elif mail_status == mailer.STATUS_FAILED:
            redirect_status = "invite_failed_email"
        else:
            # "sent" atau "skipped" (staging no-op) -> invite berhasil dibuat.
            redirect_status = "invite_sent"

        log_activity(
            current_user, "invite", "user", uid, username,
            changes=[
                {"field": "Username", "new": username},
                {"field": "Email", "new": mask_email(clean_email)},
                {"field": "Role", "new": "staff"},
                {"field": "Status", "new": "pending"},
                {"field": "Mail", "new": mail_status},
            ],
            request=request, outcome="success",
        )

        return RedirectResponse(url=f"/admin/users?status={redirect_status}", status_code=303)

    # 1c. KIRIM ULANG UNDANGAN USER PENDING (KHUSUS ADMIN)
    @app.post("/admin/users/resend-invite")
    @limiter.limit("3/minute")
    async def admin_resend_invite(
        request: Request,
        target_uid: str = Form(...),
        current_user: dict = Depends(get_current_user),
    ):
        """Kirim ulang tautan aktivasi untuk user Auth yang masih pending."""
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Super Admin.")

        clean_uid = (target_uid or "").strip()

        app_base_url = (getattr(settings, "app_base_url", "") or "").strip()
        if not app_base_url:
            print("[RESEND INVITE] APP_BASE_URL belum diset; resend dibatalkan.")
            log_activity(
                current_user, "resend_invite", "user", clean_uid or None,
                f"User {clean_uid}" if clean_uid else "(kosong)",
                changes=[{"field": "Email", "note": "APP_BASE_URL belum diset; resend dibatalkan"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=invite_not_configured", status_code=303)

        if not clean_uid:
            log_activity(
                current_user, "resend_invite", "user", None, "(kosong)",
                changes=[{"field": "Target", "note": "target_uid kosong"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=user_not_found", status_code=303)

        try:
            prof_res = (
                supabase.table("profiles")
                .select("id, full_name, status, invited_email, invited_at, is_protected")
                .eq("id", clean_uid)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[RESEND INVITE] gagal baca profil uid={clean_uid}: {exc}")
            log_activity(
                current_user, "resend_invite", "user", clean_uid, f"User {clean_uid}",
                changes=[{"field": "Profil", "note": "gagal membaca data profil target"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=resend_failed", status_code=303)

        if not prof_res.data:
            log_activity(
                current_user, "resend_invite", "user", clean_uid, f"User {clean_uid}",
                changes=[{"field": "Target", "note": "target user tidak ditemukan"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=user_not_found", status_code=303)

        profile = prof_res.data[0] or {}
        username = profile.get("full_name") or f"User {clean_uid}"
        invited_email = (profile.get("invited_email") or "").strip().lower()
        masked = mask_email(invited_email) if "@" in invited_email else "(kosong)"

        if profile.get("is_protected") and clean_uid != current_user["id"]:
            log_activity(
                current_user, "resend_invite", "user", clean_uid, username,
                changes=[{"field": "Proteksi", "note": "akun ditandai terproteksi"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=protected_account", status_code=303)

        if profile.get("status") != "pending":
            log_activity(
                current_user, "resend_invite", "user", clean_uid, username,
                changes=[{"field": "Status", "old": profile.get("status"), "note": "bukan akun pending"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=not_pending", status_code=303)

        if not is_valid_email(invited_email):
            log_activity(
                current_user, "resend_invite", "user", clean_uid, username,
                changes=[{"field": "Email", "new": masked, "note": "invited_email tidak valid atau kosong"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=resend_failed", status_code=303)

        remaining = resend_cooldown_remaining(profile.get("invited_at"))
        if remaining > 0:
            log_activity(
                current_user, "resend_invite", "user", clean_uid, username,
                changes=[
                    {"field": "Email", "new": masked},
                    {"field": "Cooldown",
                     "note": f"jeda minimal {INVITE_RESEND_COOLDOWN_SECONDS} detik belum terpenuhi (sisa {remaining} dtk)"},
                ],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=resend_too_soon", status_code=303)

        # WAJIB cek status konfirmasi di Supabase Auth sebelum generate_link (R7).
        try:
            auth_res = supabase.auth.admin.get_user_by_id(clean_uid)
        except Exception as exc:  # noqa: BLE001
            print(f"[RESEND INVITE] get_user_by_id gagal uid={clean_uid}: {exc}")
            log_activity(
                current_user, "resend_invite", "user", clean_uid, username,
                changes=[{"field": "Email", "new": masked},
                         {"field": "Auth", "note": "gagal memeriksa status Auth user"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=resend_failed", status_code=303)

        auth_user = getattr(auth_res, "user", None)
        if auth_user is None:
            log_activity(
                current_user, "resend_invite", "user", clean_uid, username,
                changes=[{"field": "Email", "new": masked},
                         {"field": "Auth", "note": "user Auth tidak ditemukan"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=resend_failed", status_code=303)

        if getattr(auth_user, "email_confirmed_at", None):
            log_activity(
                current_user, "resend_invite", "user", clean_uid, username,
                changes=[
                    {"field": "Email", "new": masked},
                    {"field": "Auth",
                     "note": "email sudah terkonfirmasi di Auth; gunakan Batalkan & undang ulang"},
                ],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=resend_already_confirmed", status_code=303)

        try:
            link_res = supabase.auth.admin.generate_link({
                "type": "invite",
                "email": invited_email,
                "options": {"data": {"username": username}},
            })
            hashed_token = getattr(getattr(link_res, "properties", None), "hashed_token", None)
        except Exception as exc:  # noqa: BLE001
            print(f"[RESEND INVITE] generate_link gagal uid={clean_uid}: {exc}")
            log_activity(
                current_user, "resend_invite", "user", clean_uid, username,
                changes=[{"field": "Email", "new": masked},
                         {"field": "Error", "note": "generate_link resend gagal"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=resend_failed", status_code=303)

        if not hashed_token:
            log_activity(
                current_user, "resend_invite", "user", clean_uid, username,
                changes=[{"field": "Email", "new": masked},
                         {"field": "Error", "note": "respons generate_link tidak memiliki hashed_token"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=resend_failed", status_code=303)

        invited_at_update_failed = False
        now_iso = datetime.now(WIB).isoformat()
        try:
            (
                supabase.table("profiles")
                .update({"invited_at": now_iso, "updated_at": now_iso})
                .eq("id", clean_uid)
                .eq("status", "pending")
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            invited_at_update_failed = True
            print(f"[RESEND INVITE] gagal update invited_at uid={clean_uid}: {exc}")

        activate_url = f"{app_base_url.rstrip('/')}/activate?token_hash={hashed_token}&type=invite"
        try:
            _mail_ok, mail_status = await mailer.send_invite_email(
                to_email=invited_email,
                activate_url=activate_url,
                app_base_url=app_base_url,
                is_resend=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[RESEND INVITE] mailer exception: {exc}")
            mail_status = mailer.STATUS_FAILED

        if mail_status == mailer.STATUS_UNKNOWN:
            redirect_status = "resend_unknown"
        elif mail_status == mailer.STATUS_FAILED:
            redirect_status = "resend_failed_email"
        else:
            redirect_status = "resend_sent"

        changes = [
            {"field": "Username", "new": username},
            {"field": "Email", "new": masked},
            {"field": "Mail", "new": mail_status},
            {"field": "Token", "note": "tautan lama otomatis tidak berlaku"},
        ]
        if invited_at_update_failed:
            changes.append({"field": "invited_at", "note": "gagal memperbarui invited_at di profiles"})

        log_activity(
            current_user, "resend_invite", "user", clean_uid, username,
            changes=changes, request=request, outcome="success",
        )

        return RedirectResponse(url=f"/admin/users?status={redirect_status}", status_code=303)

    # 1d. BATALKAN UNDANGAN USER PENDING (KHUSUS ADMIN)
    @app.post("/admin/users/cancel-invite")
    @limiter.limit("5/minute")
    async def admin_cancel_invite(
        request: Request,
        target_uid: str = Form(...),
        current_user: dict = Depends(get_current_user),
    ):
        """Batalkan undangan user pending dengan menghapus user Auth (cascade profiles)."""
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Super Admin.")

        clean_uid = (target_uid or "").strip()
        if not clean_uid:
            log_activity(
                current_user, "cancel_invite", "user", None, "(kosong)",
                changes=[{"field": "Target", "note": "target_uid kosong"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=user_not_found", status_code=303)

        if clean_uid == current_user["id"]:
            log_activity(
                current_user, "cancel_invite", "user", clean_uid, "akun sendiri",
                changes=[{"field": "Proteksi", "note": "admin mencoba membatalkan akun sendiri"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=cannot_delete_self", status_code=303)

        try:
            snap_res = (
                supabase.table("profiles")
                .select("id, full_name, role, status, invited_email, is_protected")
                .eq("id", clean_uid)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[CANCEL INVITE] gagal baca snapshot profil uid={clean_uid}: {exc}")
            log_activity(
                current_user, "cancel_invite", "user", clean_uid, f"User {clean_uid}",
                changes=[{"field": "Profil", "note": "gagal membaca snapshot profil target"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=cancel_failed", status_code=303)

        if not snap_res.data:
            log_activity(
                current_user, "cancel_invite", "user", clean_uid, f"User {clean_uid}",
                changes=[{"field": "Target", "note": "target user tidak ditemukan"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=user_not_found", status_code=303)

        profile = snap_res.data[0] or {}
        username = profile.get("full_name") or f"User {clean_uid}"
        invited_email = (profile.get("invited_email") or "").strip().lower()
        masked = mask_email(invited_email) if "@" in invited_email else "(kosong)"

        if profile.get("is_protected"):
            log_activity(
                current_user, "cancel_invite", "user", clean_uid, username,
                changes=[{"field": "Proteksi", "note": "akun ditandai terproteksi"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=protected_account", status_code=303)

        if profile.get("status") != "pending":
            log_activity(
                current_user, "cancel_invite", "user", clean_uid, username,
                changes=[
                    {"field": "Status", "old": profile.get("status"),
                     "note": "bukan akun pending; pembatalan ditolak"},
                ],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=not_pending", status_code=303)

        try:
            supabase.auth.admin.delete_user(clean_uid)
        except Exception as exc:  # noqa: BLE001
            print(f"[CANCEL INVITE] gagal hapus Auth uid={clean_uid}: {exc}")
            log_activity(
                current_user, "cancel_invite", "user", clean_uid, username,
                changes=[
                    {"field": "Username", "old": username},
                    {"field": "Email", "old": masked},
                    {"field": "Error", "note": "hapus akun Auth gagal; profil pending tidak diubah"},
                ],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=cancel_failed", status_code=303)

        partial_failure = False
        cascade_note = "dihapus dari Supabase Auth (profil ikut terhapus via cascade)"
        try:
            rem_res = supabase.table("profiles").select("id").eq("id", clean_uid).execute()
            remaining = rem_res.data or []
        except Exception as exc:  # noqa: BLE001
            partial_failure = True
            cascade_note = "akun Auth terhapus, tetapi verifikasi cascade profil gagal"
            print(f"[CANCEL INVITE] verifikasi cascade profil gagal uid={clean_uid}: {exc}")
            remaining = []

        if not partial_failure and remaining:
            try:
                (
                    supabase.table("profiles")
                    .delete()
                    .eq("id", clean_uid)
                    .eq("status", "pending")
                    .execute()
                )
                cascade_note = "akun Auth terhapus; baris profil pending dibersihkan manual (cascade tidak berjalan)"
            except Exception as exc:  # noqa: BLE001
                partial_failure = True
                cascade_note = "kegagalan parsial: akun Auth terhapus tetapi baris profil sisa gagal dihapus"
                print(f"[CANCEL INVITE] fallback hapus profil gagal uid={clean_uid}: {exc}")

        if partial_failure:
            log_activity(
                current_user, "cancel_invite", "user", clean_uid, username,
                changes=[
                    {"field": "Username", "old": username},
                    {"field": "Email", "old": masked},
                    {"field": "Error", "note": cascade_note},
                ],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=cancel_partial", status_code=303)

        log_activity(
            current_user, "cancel_invite", "user", clean_uid, username,
            changes=[
                {"field": "Username", "old": username},
                {"field": "Email", "old": masked},
                {"field": "Auth", "note": cascade_note},
            ],
            request=request, outcome="success",
        )
        return RedirectResponse(url="/admin/users?status=cancel_success", status_code=303)

    # 2. PROSES RESET PASSWORD USER (KHUSUS ADMIN)
    @app.post("/admin/users/reset-password")
    async def admin_reset_password(
        request: Request,
        target_uid: str = Form(...),
        new_password: str = Form(...),
        current_user: dict = Depends(get_current_user)
    ):
        # Proteksi: cuma admin yang boleh reset password user
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Super Admin.")

        # Validasi minimal: password baru minimal 6 karakter (sama kayak minlength di form modal)
        if len(new_password.strip()) < 6:
            log_activity(
                current_user, "reset_password", "user", target_uid,
                _user_label(target_uid),
                changes=[{"field": "Proteksi", "note": "password baru terlalu pendek (< 6 karakter)"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=password_too_short", status_code=303)

        # Cek apakah target akun terproteksi -- kalau iya dan yang minta bukan akun itu sendiri, tolak
        if target_uid != current_user["id"]:
            target_check = supabase.table("profiles").select("is_protected").eq("id", target_uid).execute()
            if target_check.data and target_check.data[0].get("is_protected"):
                log_activity(
                    current_user, "reset_password", "user", target_uid,
                    _user_label(target_uid),
                    changes=[{"field": "Proteksi", "note": "akun ditandai terproteksi"}],
                    request=request, outcome="rejected",
                )
                return RedirectResponse(url="/admin/users?error=protected_account", status_code=303)

        # Validasi target user ada (cegah operasi pada UID tidak valid).
        target_exists = supabase.table("profiles").select("id").eq("id", target_uid).execute()
        if not target_exists.data:
            log_activity(
                current_user, "reset_password", "user", target_uid,
                f"User {target_uid}",
                changes=[{"field": "Proteksi", "note": "target user tidak ditemukan"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=user_not_found", status_code=303)

        try:
            target_res = supabase.table("profiles").select("full_name").eq("id", target_uid).execute()
            target_name = target_res.data[0].get("full_name") if target_res.data else None

            # Update password di Supabase Auth Service.
            # Dipakai update_user_by_id karena di supabase-py v2 method update_user sudah dihapus.
            supabase.auth.admin.update_user_by_id(target_uid, {"password": new_password})

            # Catat activity log. Password SENGAJA TIDAK pernah dicatat, hanya bahwa
            # reset berhasil dilakukan.
            log_activity(
                current_user,
                "reset_password",
                "user",
                target_uid,
                target_name or f"User {target_uid}",
                changes=[{"field": "Password", "note": "di-reset oleh admin (nilai tidak dicatat)"}],
                request=request,
                outcome="success",
            )

            return RedirectResponse(url="/admin/users?status=reset_success", status_code=303)

        except Exception as e:
            print(f"Gagal reset password user {target_uid}: {e}")
            log_activity(
                current_user, "reset_password", "user", target_uid,
                _user_label(target_uid),
                changes=[{"field": "Password", "note": "reset gagal"},
                         {"field": "Error", "note": "reset password gagal (detail di log server)"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=reset_failed", status_code=303)

    # 3. PROSES UPDATE ROLE USER (POST)
    @app.post("/admin/users/update-role")
    async def update_user_role(
        request: Request,
        target_uid: str = Form(...),
        new_role: str = Form(...),
        current_user: dict = Depends(get_current_user)
    ):
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak!")

        # Validasi role yang boleh diberikan.
        if new_role not in {"admin", "staff"}:
            log_activity(
                current_user, "update", "user", target_uid,
                _user_label(target_uid),
                changes=[{"field": "Role", "note": "role tidak valid"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=invalid_role", status_code=303)

        # Validasi target user ada.
        target_exists = supabase.table("profiles").select("id").eq("id", target_uid).execute()
        if not target_exists.data:
            log_activity(
                current_user, "update", "user", target_uid,
                f"User {target_uid}",
                changes=[{"field": "Proteksi", "note": "target user tidak ditemukan"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=user_not_found", status_code=303)

        # Cek apakah target akun terproteksi -- kalau iya dan yang minta bukan akun itu sendiri, tolak
        if target_uid != current_user["id"]:
            target_check = supabase.table("profiles").select("is_protected").eq("id", target_uid).execute()
            if target_check.data and target_check.data[0].get("is_protected"):
                log_activity(
                    current_user, "update", "user", target_uid,
                    _user_label(target_uid),
                    changes=[{"field": "Proteksi", "note": "akun ditandai terproteksi"}],
                    request=request, outcome="rejected",
                )
                return RedirectResponse(url="/admin/users?error=protected_account", status_code=303)

        # Ambil role SEBELUM diubah supaya diff old/new bisa diisi.
        old_role, target_label = _user_role_and_label(target_uid)

        try:
            # Update kolom role di tabel profiles berdasarkan UUID user yang dipilih
            # (updated_at pakai timestamp ISO asli, bukan string "now()" biar gak gagal cast di PostgREST)
            supabase.table("profiles").update({"role": new_role, "updated_at": datetime.now(WIB).isoformat()}).eq("id", target_uid).execute()

            log_activity(
                current_user, "update", "user", target_uid, target_label,
                changes=[{"field": "Role", "old": old_role, "new": new_role}],
                request=request, outcome="success",
            )
            return RedirectResponse(url="/admin/users?status=update_success", status_code=303)
        except Exception as e:
            print(f"Gagal update role: {e}")
            log_activity(
                current_user, "update", "user", target_uid, target_label,
                changes=[{"field": "Role", "old": old_role, "new": new_role},
                         {"field": "Error", "note": "update role gagal (detail di log server)"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=update_failed", status_code=303)

    @app.post("/admin/users/delete")
    async def delete_user(
        request: Request,
        target_uid: str = Form(...),
        current_user: dict = Depends(get_current_user)
    ):
        # Proteksi: cuma admin yang boleh hapus user
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Super Admin.")

        # Cek biar admin gak ketidaksengajaan ngapus akunnya sendiri
        if target_uid == current_user["id"]:
            log_activity(
                current_user, "delete", "user", target_uid, "akun sendiri",
                changes=[{"field": "Proteksi", "note": "admin mencoba menghapus akunnya sendiri"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=cannot_delete_self", status_code=303)

        # Snapshot profil target SEBELUM dihapus. Setelah baris profiles hilang,
        # nama/role/perusahaan tidak bisa direkonstruksi lagi -- karena itu seluruh
        # data ini harus diambil di sini dan disimpan ke activity log.
        target_snapshot = {}
        try:
            snap_res = supabase.table("profiles").select(
                "full_name, role, perusahaan, is_protected").eq("id", target_uid).execute()
            if snap_res.data:
                target_snapshot = snap_res.data[0] or {}
        except Exception as ex:
            print(f"Gagal ambil snapshot profil target {target_uid}: {ex}")

        target_label = (target_snapshot.get("full_name") or f"User {target_uid}")

        # Validasi target user ada (cegah operasi pada UID tidak valid).
        if not target_snapshot:
            return RedirectResponse(url="/admin/users?error=user_not_found", status_code=303)

        # Cek apakah target akun terproteksi (dan bukan dirinya sendiri -- walau baris di atas
        # sudah menangkap kasus itu, ini sebagai lapis proteksi tambahan)
        if target_snapshot.get("is_protected"):
            log_activity(
                current_user, "delete", "user", target_uid, target_label,
                changes=[{"field": "Proteksi", "note": "akun ditandai terproteksi"}],
                request=request, outcome="rejected",
            )
            return RedirectResponse(url="/admin/users?error=protected_account", status_code=303)

        try:
            # Inisialisasi admin client lewat guard staging (fail-closed)
            from app.staging_guard import staging_client as _staging_client2

            supabase_admin = _staging_client2("admin-delete-user")

            # 1. Hapus dari Supabase Auth Service
            supabase_admin.auth.admin.delete_user(target_uid)

            # 2. Hapus dari tabel profiles.
            # activity_logs.actor_id memakai ON DELETE SET NULL, jadi baris audit milik
            # user ini tetap tersimpan (aktor jadi NULL, identitasnya ada di actor_name).
            supabase.table("profiles").delete().eq("id", target_uid).execute()

            log_activity(
                current_user, "delete", "user", target_uid, target_label,
                changes=[
                    {"field": "Username", "old": target_snapshot.get("full_name")},
                    {"field": "Role", "old": target_snapshot.get("role")},
                    {"field": "Perusahaan", "old": target_snapshot.get("perusahaan")},
                    {"field": "Auth", "note": "dihapus dari Supabase Auth"},
                ],
                request=request, outcome="success",
            )

            return RedirectResponse(url="/admin/users?status=delete_success", status_code=303)

        except Exception as e:
            print(f"Gagal hapus user: {e}")
            log_activity(
                current_user, "delete", "user", target_uid, target_label,
                changes=[{"field": "Username", "old": target_snapshot.get("full_name")},
                         {"field": "Error", "note": "hapus user gagal (detail di log server)"}],
                request=request, outcome="failed",
            )
            return RedirectResponse(url="/admin/users?error=delete_failed", status_code=303)

