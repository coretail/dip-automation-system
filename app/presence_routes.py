"""Presence and ED notification routes (extracted from main.py)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

WIB = ZoneInfo("Asia/Jakarta")


def register_presence_routes(
    app,
    get_current_user,
    supabase,
    templates,
    log_activity,
    get_ed_notification_count,
    touch_user_presence,
    compute_user_presence,
    compute_status_na,
):
    @app.post("/api/presence/heartbeat")
    async def presence_heartbeat(request: Request, current_user: dict = Depends(get_current_user)):
        online = True
        active = True
        try:
            body = await request.json()
            if isinstance(body, dict) and "online" in body:
                online = bool(body.get("online"))
            if isinstance(body, dict) and "active" in body:
                active = bool(body.get("active"))
        except Exception:
            online = True
            active = True
        ok = touch_user_presence(current_user["id"], online=online, active=active)
        return JSONResponse({"ok": ok, "online": online, "active": active})

    @app.get("/api/admin/users/presence")
    async def admin_users_presence(current_user: dict = Depends(get_current_user)):
        if current_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Super Admin.")
        try:
            profiles_res = supabase.table("profiles").select(
                "id, last_seen_at, last_activity_at, is_online, is_protected, full_name"
            ).execute()
            rows = profiles_res.data or []
        except Exception as e:
            print(f"[PRESENCE] Gagal tarik last_seen_at (kolom mungkin belum ada): {e}")
            try:
                profiles_res = supabase.table("profiles").select("id, is_protected, full_name").execute()
                rows = profiles_res.data or []
            except Exception as e2:
                print(f"[PRESENCE] Gagal tarik profiles: {e2}")
                rows = []

        items = []
        for u in rows:
            if u.get("is_protected") and u.get("id") != current_user["id"]:
                continue
            presence = compute_user_presence(u)
            items.append({
                "id": u.get("id"),
                "full_name": u.get("full_name"),
                "is_online": presence["is_online"],
                "is_idle": presence["is_idle"],
                "presence_status": presence["presence_status"],
                "last_seen_at": presence["last_seen_at"],
                "last_seen_label": presence["last_seen_label"],
                "last_activity_at": presence["last_activity_at"],
                "last_activity_label": presence["last_activity_label"],
            })
        online_count = sum(1 for i in items if i["presence_status"] == "online")
        idle_count = sum(1 for i in items if i["presence_status"] == "idle")
        return JSONResponse({
            "items": items,
            "online_count": online_count,
            "idle_count": idle_count,
            "offline_count": len(items) - online_count - idle_count,
            "online_threshold_seconds": 90,
            "idle_threshold_seconds": 5 * 60,
        })

    @app.get("/api/ed-notifications")
    async def get_ed_notifications(current_user: dict = Depends(get_current_user)):
        from datetime import datetime as _dt, timedelta
        today = _dt.now(WIB).date()
        warning_date = today + timedelta(days=180)
        try:
            query = supabase.table("raw_material_batches").select("*, raw_materials(nama_dagang, kode_bahan_baku)").neq("status_ed", "Dimusnahkan").execute()
            batches = query.data or []
            critical_batches = []
            for batch in batches:
                tanggal_ed = batch.get("tanggal_ed")
                if not tanggal_ed:
                    continue
                try:
                    if isinstance(tanggal_ed, str):
                        ed_date = _dt.strptime(tanggal_ed[:10], "%Y-%m-%d").date()
                    else:
                        ed_date = tanggal_ed
                except Exception:
                    continue
                days_remaining = (ed_date - today).days
                if days_remaining <= 180:
                    status_ed = batch.get("status_ed") or "Active"
                    if days_remaining <= 0 and status_ed == "Active":
                        status_ed = "Expired"
                    elif days_remaining <= 180 and status_ed == "Active":
                        status_ed = "Kritis (<= 180 hari)"
                    critical_batches.append({
                        "id": batch.get("id"),
                        "raw_material_id": batch.get("raw_material_id"),
                        "no_batch": batch.get("no_batch"),
                        "perusahaan": batch.get("perusahaan"),
                        "tanggal_ed": tanggal_ed,
                        "days_remaining": days_remaining,
                        "status_ed": status_ed,
                        "nama_dagang": (batch.get("raw_materials") or {}).get("nama_dagang", "Unknown"),
                        "kode_bahan_baku": (batch.get("raw_materials") or {}).get("kode_bahan_baku", "")
                    })
            critical_batches.sort(key=lambda x: x["days_remaining"])

            products_query = supabase.table("products").select("id, nama_produk, no_na_produk, tanggal_aktif_na, status_na").execute()
            na_items = []
            for p in (products_query.data or []):
                status_na, days_remaining = compute_status_na(p.get("tanggal_aktif_na"), p.get("status_na") or "belum_terdaftar")
                if status_na in ["akan_expired", "expired"]:
                    na_items.append({
                        "id": p.get("id"),
                        "nama_produk": p.get("nama_produk"),
                        "no_na_produk": p.get("no_na_produk"),
                        "days_remaining": days_remaining if days_remaining is not None else 0,
                        "status_na": status_na,
                    })

            return JSONResponse({
                "count": len(critical_batches) + len(na_items),
                "batch_items": critical_batches,
                "na_items": na_items,
            })
        except Exception as e:
            print(f"Gagal ambil ED notifications: {e}")
            return JSONResponse({"count": 0, "batch_items": [], "na_items": []})