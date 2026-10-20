"""Admin user management routes (extracted from main.py)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

WIB = ZoneInfo("Asia/Jakarta")


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

            # Inject ke tabel profiles dengan role yang dipilih admin (default staff)
            final_role = role if role in ("staff", "admin") else "staff"
            supabase.table("profiles").insert({
                "id": new_uid,
                "full_name": clean_username,
                "role": final_role,
                # Jangan pakai string "now()" (PostgREST simpan sebagai literal & bisa gagal cast ke timestamptz).
                # Kirim timestamp ISO nyata dari Python.
                "updated_at": datetime.now(WIB).isoformat()
            }).execute()

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

