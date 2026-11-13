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
        from app.pagination import paginate_all
        from app.ed_notifications import critical_ed_items, critical_na_items
        today = _dt.now(WIB).date()
        cutoff = (today + timedelta(days=180)).isoformat()
        try:
            # Paginasi lengkap: PostgREST memotong di db.max-rows (default 1000).
            # order("id") untuk urutan deterministik. Filter berat di SQL:
            # .neq("status_ed","Dimusnahkan") + .lte("tanggal_ed", cutoff) +
            # .not_().is_("tanggal_ed", None) — sama dengan badge (main.py).
            # Kolom lengkap + embed raw_materials untuk tampilan di panel.
            def _fetch_batches_page(offset):
                return supabase.table("raw_material_batches") \
                    .select("id, tanggal_ed, status_ed, no_batch, perusahaan, raw_material_id, raw_materials(nama_dagang, kode_bahan_baku)") \
                    .neq("status_ed", "Dimusnahkan") \
                    .lte("tanggal_ed", cutoff) \
                    .not_().is_("tanggal_ed", None) \
                    .order("id") \
                    .range(offset, offset + 999).execute().data or []
            batch_rows = paginate_all(_fetch_batches_page)
            critical_batches = critical_ed_items(batch_rows, today)

            # Products: TANPA filter status_na (sama seperti badge) karena
            # filter SQL tidak bisa membuktikan setara semantik compute_status_na.
            def _fetch_products_page(offset):
                return supabase.table("products") \
                    .select("id, nama_produk, no_na_produk, tanggal_aktif_na, status_na") \
                    .order("id") \
                    .range(offset, offset + 999).execute().data or []
            product_rows = paginate_all(_fetch_products_page)
            na_items = critical_na_items(product_rows, compute_status_na)

            return JSONResponse({
                "count": len(critical_batches) + len(na_items),
                "batch_items": critical_batches,
                "na_items": na_items,
            })
        except Exception as e:
            print(f"Gagal ambil ED notifications: {e}")
            return JSONResponse({"count": 0, "batch_items": [], "na_items": []})