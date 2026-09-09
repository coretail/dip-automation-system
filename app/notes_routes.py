"""Team Notes + @mention routes."""
from __future__ import annotations

import html as _html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import supabase

WIB = ZoneInfo("Asia/Jakarta")
templates = Jinja2Templates(directory="app/templates")

_MENTION_RE = re.compile(r"(?<!\w)@([a-zA-Z0-9._\-]+)")


def _parse_mentions(body: str, username_to_id: dict) -> list:
    found = []
    seen = set()
    for m in _MENTION_RE.finditer(body or ""):
        uname = m.group(1).strip()
        key = uname.lower()
        if key in seen:
            continue
        uid = username_to_id.get(key)
        if uid:
            seen.add(key)
            found.append({"user_id": uid, "username": uname})
    return found


def _render_note_html(body: str) -> str:
    escaped = _html.escape(body or "")
    def _repl(m):
        return (
            f'<span class="inline-flex items-center px-1.5 py-0.5 rounded '
            f'bg-indigo-100 text-indigo-700 font-semibold text-xs">@'
            f'{_html.escape(m.group(1))}</span>'
        )
    return _MENTION_RE.sub(_repl, escaped).replace("\n", "<br>")


def _parse_presence_ts(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=WIB)
    return dt.astimezone(WIB)


def _relative_last_seen(dt):
    if not dt:
        return "Belum pernah online"
    sec = int((datetime.now(WIB) - dt).total_seconds())
    if sec < 45:
        return "Baru saja"
    if sec < 90:
        return "1 menit lalu"
    if sec < 3600:
        return f"{max(1, sec // 60)} menit lalu"
    if sec < 86400:
        return f"{max(1, sec // 3600)} jam lalu"
    hari = max(1, sec // 86400)
    if hari == 1:
        return "Kemarin " + dt.strftime("%H:%M")
    if hari < 7:
        return f"{hari} hari lalu"
    return dt.strftime("%d-%m-%Y %H:%M WIB")


def register_notes_routes(app, get_current_user, get_ed_notification_count, log_activity):
    """Attach notes endpoints to the FastAPI app (avoids circular imports)."""

    @app.get("/api/notes/users")
    async def api_notes_users(q: str = "", current_user: dict = Depends(get_current_user)):
        try:
            res = supabase.table("profiles").select("id, full_name").order("full_name").execute()
            rows = res.data or []
        except Exception as e:
            print(f"[NOTES] Gagal ambil users: {e}")
            rows = []
        qn = (q or "").strip().lower()
        items = []
        for r in rows:
            name = (r.get("full_name") or "").strip()
            if not name or r.get("id") == current_user.get("id"):
                continue
            if qn and qn not in name.lower():
                continue
            items.append({"id": r["id"], "full_name": name})
            if len(items) >= 12:
                break
        return JSONResponse({"items": items})

    @app.get("/notes", response_class=HTMLResponse)
    async def notes_page(request: Request, filter: str = "all", current_user: dict = Depends(get_current_user)):
        notes = []
        mention_count = 0
        schema_ok = True
        try:
            notes_res = (
                supabase.table("team_notes").select("*").order("created_at", desc=True).limit(100).execute()
            )
            notes = notes_res.data or []
        except Exception as e:
            print(f"[NOTES] Gagal tarik team_notes (jalankan supabase_team_notes.sql?): {e}")
            schema_ok = False
            notes = []

        mentions_by_note = {}
        try:
            if notes:
                note_ids = [n["id"] for n in notes]
                ment_res = supabase.table("team_note_mentions").select("*").in_("note_id", note_ids).execute()
                for m in (ment_res.data or []):
                    mentions_by_note.setdefault(m["note_id"], []).append(m)
                    if m.get("mentioned_user_id") == current_user["id"] and not m.get("is_read"):
                        mention_count += 1
        except Exception as e:
            print(f"[NOTES] Gagal tarik mentions: {e}")

        if filter == "mentioned":
            my_id = current_user["id"]
            notes = [n for n in notes if any(m.get("mentioned_user_id") == my_id for m in mentions_by_note.get(n["id"], []))]

        enriched = []
        for n in notes:
            ments = mentions_by_note.get(n["id"], [])
            enriched.append({
                **n,
                "body_html": _render_note_html(n.get("body") or ""),
                "mentions": ments,
                "mentioned_me": any(m.get("mentioned_user_id") == current_user["id"] for m in ments),
                "created_label": _relative_last_seen(_parse_presence_ts(n.get("created_at"))) if n.get("created_at") else "-",
            })

        try:
            supabase.table("team_note_mentions").update({"is_read": True}).eq(
                "mentioned_user_id", current_user["id"]
            ).eq("is_read", False).execute()
        except Exception:
            pass

        return templates.TemplateResponse(
            request=request,
            name="notes.html",
            context={
                "current_user": current_user,
                "notes": enriched,
                "filter": filter,
                "mention_count": mention_count,
                "schema_ok": schema_ok,
                "ed_notification_count": await get_ed_notification_count(),
            },
        )

    @app.post("/notes")
    async def create_note(request: Request, body: str = Form(...), current_user: dict = Depends(get_current_user)):
        text = (body or "").strip()
        if not text:
            return RedirectResponse(url="/notes?error=empty", status_code=303)
        if len(text) > 4000:
            return RedirectResponse(url="/notes?error=too_long", status_code=303)

        try:
            profiles = supabase.table("profiles").select("id, full_name").execute()
            username_to_id = {
                (p.get("full_name") or "").strip().lower(): p["id"]
                for p in (profiles.data or [])
                if p.get("full_name")
            }
        except Exception as e:
            print(f"[NOTES] Gagal ambil profiles: {e}")
            username_to_id = {}

        mentions = _parse_mentions(text, username_to_id)

        try:
            ins = supabase.table("team_notes").insert({
                "author_id": current_user["id"],
                "author_name": current_user.get("full_name") or "User",
                "body": text,
                "created_at": datetime.now(WIB).isoformat(),
                "updated_at": datetime.now(WIB).isoformat(),
            }).execute()
            note_row = (ins.data or [None])[0]
            if not note_row:
                last = (
                    supabase.table("team_notes").select("id").eq("author_id", current_user["id"])
                    .order("created_at", desc=True).limit(1).execute()
                )
                note_row = (last.data or [None])[0]
            note_id = note_row["id"] if note_row else None

            if note_id and mentions:
                rows = [{
                    "note_id": note_id,
                    "mentioned_user_id": m["user_id"],
                    "mentioned_username": m["username"],
                    "is_read": False,
                    "created_at": datetime.now(WIB).isoformat(),
                } for m in mentions]
                supabase.table("team_note_mentions").insert(rows).execute()

            log_activity(
                current_user, "create", "note", note_id or "-",
                text[:80] + ("…" if len(text) > 80 else ""),
            )
        except Exception as e:
            print(f"[NOTES] Gagal simpan note: {e}")
            return RedirectResponse(url="/notes?error=save_failed", status_code=303)

        return RedirectResponse(url="/notes?status=created", status_code=303)

    @app.post("/notes/{note_id}/delete")
    async def delete_note(note_id: str, current_user: dict = Depends(get_current_user)):
        try:
            res = supabase.table("team_notes").select("id, author_id, body").eq("id", note_id).execute()
            row = (res.data or [None])[0]
            if not row:
                return RedirectResponse(url="/notes?error=not_found", status_code=303)
            if row["author_id"] != current_user["id"] and current_user.get("role") != "admin":
                raise HTTPException(status_code=403, detail="Hanya penulis atau admin yang boleh hapus.")
            supabase.table("team_notes").delete().eq("id", note_id).execute()
            log_activity(current_user, "delete", "note", note_id, (row.get("body") or "")[:80])
        except HTTPException:
            raise
        except Exception as e:
            print(f"[NOTES] Gagal hapus note: {e}")
            return RedirectResponse(url="/notes?error=delete_failed", status_code=303)
        return RedirectResponse(url="/notes?status=deleted", status_code=303)
