"""Team Notes + @mention + #product-reference + /raw-material-reference routes."""
from __future__ import annotations

import html as _html
import json
import re
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import supabase

WIB = ZoneInfo("Asia/Jakarta")
templates = Jinja2Templates(directory="app/templates")

_MENTION_RE = re.compile(r"(?<!\w)@([a-zA-Z0-9._\-]+)")
_UUID_RE = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
# Token inserted by autocomplete: #[uuid|Display Name With Spaces]
_PRODUCT_TOKEN_RE = re.compile(r"#\[(" + _UUID_RE + r")\|([^\]]*)\]")
# Token inserted by autocomplete: /[uuid|Nama Dagang With Spaces]
_RM_TOKEN_RE = re.compile(r"/\[(" + _UUID_RE + r")\|([^\]]*)\]")
# Token inserted by autocomplete: ![uuid|Nama Merk With Spaces]
_BRAND_TOKEN_RE = re.compile(r"!\[(" + _UUID_RE + r")\|([^\]]*)\]")


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


def _parse_product_refs(body: str) -> list:
    """Extract product refs from #[uuid|label] tokens. UUID is the source of truth."""
    found = []
    seen = set()
    for m in _PRODUCT_TOKEN_RE.finditer(body or ""):
        pid = m.group(1)
        label = (m.group(2) or "").strip() or pid
        key = pid.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append({"id": pid, "name": label})
    return found


def _parse_rm_refs(body: str) -> list:
    """Extract raw-material refs from /[uuid|label] tokens. UUID is the source of truth."""
    found = []
    seen = set()
    for m in _RM_TOKEN_RE.finditer(body or ""):
        rid = m.group(1)
        label = (m.group(2) or "").strip() or rid
        key = rid.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append({"id": rid, "name": label})
    return found


def _parse_brand_refs(body: str) -> list:
    """Extract brand refs from ![uuid|label] tokens. UUID is the source of truth."""
    found = []
    seen = set()
    for m in _BRAND_TOKEN_RE.finditer(body or ""):
        bid = m.group(1)
        label = (m.group(2) or "").strip() or bid
        key = bid.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append({"id": bid, "name": label})
    return found


def _parse_product_ids_field(raw: str) -> list:
    """Fallback: hidden input may send JSON array or comma-separated UUIDs."""
    text = (raw or "").strip()
    if not text:
        return []
    ids = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            ids = [str(x).strip() for x in parsed if str(x).strip()]
        elif isinstance(parsed, str):
            ids = [p.strip() for p in parsed.split(",") if p.strip()]
    except Exception:
        ids = [p.strip() for p in text.split(",") if p.strip()]
    uuid_ok = re.compile(r"^" + _UUID_RE + r"$")
    out, seen = [], set()
    for pid in ids:
        key = pid.lower()
        if not uuid_ok.match(pid) or key in seen:
            continue
        seen.add(key)
        out.append(pid)
    return out


def _render_note_html(
    body: str,
    live_product_ids: set | None = None,
    live_rm_ids: set | None = None,
    live_brand_ids: set | None = None,
) -> str:
    escaped = _html.escape(body or "")

    def _prod(m):
        pid = m.group(1)
        label = m.group(2) or "produk"
        chip_inner = f'<i class="fa-solid fa-box-open"></i> {label}'
        chip_cls = "inline-flex items-center gap-1 px-1.5 py-0.5 font-semibold text-xs"
        if live_product_ids is not None and pid not in live_product_ids and pid.lower() not in live_product_ids:
            return (
                f'<span class="{chip_cls} rounded bg-emerald-100 text-emerald-800 line-through opacity-70" '
                f'title="Produk tidak ditemukan / sudah dihapus">{chip_inner}</span>'
            )
        return (
            f'<span class="inline-flex items-stretch overflow-hidden rounded bg-emerald-100 text-emerald-800">'
            f'<a href="/products/{pid}/edit" class="{chip_cls} hover:bg-emerald-200" '
            f'title="Buka halaman Edit Produk">{chip_inner}</a>'
            f'<a href="/products/{pid}/qualitative-quantitative" '
            f'class="inline-flex items-center px-1.5 border-l border-blue-200 bg-blue-50 text-blue-600 hover:bg-blue-100" '
            f'title="Buka Formula Kualitatif &amp; Kuantitatif" '
            f'aria-label="Buka Formula Kualitatif dan Kuantitatif untuk {label}">'
            f'<i class="fa-solid fa-file-lines text-xs"></i></a></span>'
        )

    rendered = _PRODUCT_TOKEN_RE.sub(_prod, escaped)

    def _rm(m):
        rid = m.group(1)
        label = m.group(2) or "bahan baku"
        chip_inner = f'<i class="fa-solid fa-flask-vial"></i> {label}'
        chip_cls = "inline-flex items-center gap-1 px-1.5 py-0.5 font-semibold text-xs"
        if live_rm_ids is not None and rid not in live_rm_ids and rid.lower() not in live_rm_ids:
            return (
                f'<span class="{chip_cls} rounded bg-amber-100 text-amber-800 line-through opacity-70" '
                f'title="Bahan baku tidak ditemukan">{chip_inner}</span>'
            )
        raw_label = _html.unescape(label)
        href = f"/raw-materials?q={quote(raw_label, safe='')}&rm={rid}"
        return (
            f'<a href="{href}" class="{chip_cls} rounded bg-amber-100 text-amber-800 hover:bg-amber-200" '
            f'title="Cari di Master Bahan Baku">{chip_inner}</a>'
        )

    rendered = _RM_TOKEN_RE.sub(_rm, rendered)

    def _brand(m):
        bid = m.group(1)
        label = m.group(2) or "merk"
        chip_inner = f'<i class="fa-solid fa-copyright"></i> {label}'
        chip_cls = "inline-flex items-center gap-1 px-1.5 py-0.5 font-semibold text-xs"
        if live_brand_ids is not None and bid not in live_brand_ids and bid.lower() not in live_brand_ids:
            return (
                f'<span class="{chip_cls} rounded bg-violet-100 text-violet-800 line-through opacity-70" '
                f'title="Merk tidak ditemukan">{chip_inner}</span>'
            )
        href = f"/brands?brand={bid}"
        return (
            f'<a href="{href}" class="{chip_cls} rounded bg-violet-100 text-violet-800 hover:bg-violet-200" '
            f'title="Buka Kelola Merk">{chip_inner}</a>'
        )

    rendered = _BRAND_TOKEN_RE.sub(_brand, rendered)

    def _mention(m):
        return (
            f'<span class="inline-flex items-center px-1.5 py-0.5 rounded '
            f'bg-indigo-100 text-indigo-700 font-semibold text-xs">@'
            f'{m.group(1)}</span>'
        )

    rendered = _MENTION_RE.sub(_mention, rendered)
    return rendered.replace("\n", "<br>")


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


def _sanitize_ilike(q: str) -> str:
    return re.sub(r"[%_,()\"'\\]", " ", q or "").strip()[:80]


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

    @app.get("/api/notes/products")
    async def api_notes_products(q: str = "", current_user: dict = Depends(get_current_user)):
        qn = _sanitize_ilike(q)
        rows = []
        try:
            query = (
                supabase.table("products")
                .select("id, nama_produk, brands(name)")
                .eq("is_deleted", False)
            )
            if qn:
                query = query.ilike("nama_produk", f"%{qn}%")
            res = query.order("nama_produk").limit(12).execute()
            rows = res.data or []
        except Exception as e:
            print(f"[NOTES] Gagal ambil products (join brands): {e}")
            try:
                query = (
                    supabase.table("products")
                    .select("id, nama_produk")
                    .eq("is_deleted", False)
                )
                if qn:
                    query = query.ilike("nama_produk", f"%{qn}%")
                res = query.order("nama_produk").limit(12).execute()
                rows = res.data or []
            except Exception as e2:
                print(f"[NOTES] Gagal ambil products: {e2}")
                rows = []
        items = []
        for r in rows:
            name = (r.get("nama_produk") or "").strip()
            if not name:
                continue
            brand = ""
            b = r.get("brands")
            if isinstance(b, dict):
                brand = (b.get("name") or "").strip()
            items.append({"id": r["id"], "nama_produk": name, "brand": brand})
        return JSONResponse({"items": items})

    @app.get("/api/notes/raw-materials")
    async def api_notes_raw_materials(q: str = "", current_user: dict = Depends(get_current_user)):
        qn = _sanitize_ilike(q)
        rows = []
        try:
            query = supabase.table("raw_materials").select(
                "id, nama_dagang, kode_bahan_baku, tipe"
            )
            if qn:
                query = query.or_(
                    f"nama_dagang.ilike.%{qn}%,kode_bahan_baku.ilike.%{qn}%"
                )
            res = query.order("nama_dagang").limit(12).execute()
            rows = res.data or []
        except Exception as e:
            print(f"[NOTES] Gagal ambil raw_materials: {e}")
            rows = []
        items = []
        for r in rows:
            name = (r.get("nama_dagang") or "").strip()
            if not name:
                continue
            items.append({
                "id": r["id"],
                "nama_dagang": name,
                "kode_bahan_baku": (r.get("kode_bahan_baku") or "").strip(),
                "tipe": (r.get("tipe") or "").strip(),
            })
        return JSONResponse({"items": items})

    @app.get("/api/notes/brands")
    async def api_notes_brands(q: str = "", current_user: dict = Depends(get_current_user)):
        qn = _sanitize_ilike(q)
        rows = []
        try:
            query = supabase.table("brands").select("id, name, producers(name)")
            if qn:
                query = query.ilike("name", f"%{qn}%")
            res = query.order("name").limit(12).execute()
            rows = res.data or []
        except Exception as e:
            print(f"[NOTES] Gagal ambil brands: {e}")
            rows = []
        items = []
        for r in rows:
            name = (r.get("name") or "").strip()
            if not name:
                continue
            producer = ""
            p = r.get("producers")
            if isinstance(p, dict):
                producer = (p.get("name") or "").strip()
            items.append({"id": r["id"], "name": name, "producer": producer})
        return JSONResponse({"items": items})

    @app.get("/api/notes/mentions/unread-count")
    async def api_notes_unread_count(current_user: dict = Depends(get_current_user)):
        """Read-only. Do NOT mark mentions as read — this is polled from every page."""
        count = 0
        try:
            res = (
                supabase.table("team_note_mentions")
                .select("id", count="exact")
                .eq("mentioned_user_id", current_user["id"])
                .eq("is_read", False)
                .execute()
            )
            if getattr(res, "count", None) is not None:
                count = int(res.count)
            else:
                count = len(res.data or [])
        except Exception as e:
            print(f"[NOTES] Gagal hitung unread mentions: {e}")
            count = 0
        return JSONResponse({"count": count})

    @app.get("/notes", response_class=HTMLResponse)
    async def notes_page(request: Request, filter: str = "all", status_filter: str = "all", current_user: dict = Depends(get_current_user)):
        notes = []
        mention_count = 0
        schema_ok = True
        try:
            query = supabase.table("team_notes").select("*").order("created_at", desc=True).limit(100)
            if status_filter == "pending":
                query = query.eq("is_completed", False)
            
            notes_res = query.execute()
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

        live_product_ids: set = set()
        try:
            pref_ids = []
            seen_p = set()
            for n in notes:
                for p in _parse_product_refs(n.get("body") or ""):
                    key = p["id"].lower()
                    if key not in seen_p:
                        seen_p.add(key)
                        pref_ids.append(p["id"])
            if pref_ids:
                pr = (
                    supabase.table("products")
                    .select("id")
                    .in_("id", pref_ids)
                    .eq("is_deleted", False)
                    .execute()
                )
                live_product_ids = {str(r["id"]) for r in (pr.data or [])}
                live_product_ids |= {x.lower() for x in live_product_ids}
        except Exception as e:
            print(f"[NOTES] Gagal cek produk live: {e}")
            live_product_ids = None  # fail open: still render as links

        live_rm_ids: set = set()
        try:
            rm_ids = []
            seen_r = set()
            for n in notes:
                for r in _parse_rm_refs(n.get("body") or ""):
                    key = r["id"].lower()
                    if key not in seen_r:
                        seen_r.add(key)
                        rm_ids.append(r["id"])
            if rm_ids:
                rr = (
                    supabase.table("raw_materials")
                    .select("id")
                    .in_("id", rm_ids)
                    .execute()
                )
                live_rm_ids = {str(row["id"]) for row in (rr.data or [])}
                live_rm_ids |= {x.lower() for x in live_rm_ids}
        except Exception as e:
            print(f"[NOTES] Gagal cek bahan baku live: {e}")
            live_rm_ids = None

        live_brand_ids: set = set()
        try:
            brand_ids = []
            seen_b = set()
            for n in notes:
                for b in _parse_brand_refs(n.get("body") or "") + _parse_brand_refs(n.get("completion_note") or ""):
                    key = b["id"].lower()
                    if key not in seen_b:
                        seen_b.add(key)
                        brand_ids.append(b["id"])
            if brand_ids:
                br = (
                    supabase.table("brands")
                    .select("id")
                    .in_("id", brand_ids)
                    .execute()
                )
                live_brand_ids = {str(row["id"]) for row in (br.data or [])}
                live_brand_ids |= {x.lower() for x in live_brand_ids}
        except Exception as e:
            print(f"[NOTES] Gagal cek merk live: {e}")
            live_brand_ids = None

        if filter == "mentioned":
            my_id = current_user["id"]
            notes = [n for n in notes if any(m.get("mentioned_user_id") == my_id for m in mentions_by_note.get(n["id"], []))]

        enriched = []
        for n in notes:
            ments = mentions_by_note.get(n["id"], [])
            prefs = _parse_product_refs(n.get("body") or "")
            for pref in prefs:
                pid = pref["id"]
                pref["is_live"] = (
                    live_product_ids is None
                    or pid in live_product_ids
                    or pid.lower() in live_product_ids
                )
            rrefs = _parse_rm_refs(n.get("body") or "")
            for rref in rrefs:
                rid = rref["id"]
                rref["is_live"] = (
                    live_rm_ids is None
                    or rid in live_rm_ids
                    or rid.lower() in live_rm_ids
                )
                rref["search_url"] = (
                    f"/raw-materials?q={quote(rref['name'], safe='')}&rm={rid}"
                )
            brefs = _parse_brand_refs(n.get("body") or "")
            for bref in brefs:
                bid = bref["id"]
                bref["is_live"] = (
                    live_brand_ids is None
                    or bid in live_brand_ids
                    or bid.lower() in live_brand_ids
                )
                bref["search_url"] = f"/brands?brand={bid}"
            enriched.append({
                **n,
                "body_html": _render_note_html(n.get("body") or "", live_product_ids, live_rm_ids, live_brand_ids),
                "completion_note_html": _render_note_html(n.get("completion_note") or "", live_product_ids, live_rm_ids, live_brand_ids) if n.get("is_completed") else None,
                "mentions": ments,
                "product_refs": prefs,
                "rm_refs": rrefs,
                "brand_refs": brefs,
                "mentioned_me": any(m.get("mentioned_user_id") == current_user["id"] for m in ments),
                "created_label": _relative_last_seen(_parse_presence_ts(n.get("created_at"))) if n.get("created_at") else "-",
                "completed_at_label": _relative_last_seen(_parse_presence_ts(n.get("completed_at"))) if n.get("completed_at") else None,
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
                "status_filter": status_filter,
                "status_filter": status_filter,
                "mention_count": mention_count,
                "schema_ok": schema_ok,
                "ed_notification_count": await get_ed_notification_count(),
            },
        )

    @app.post("/notes")
    async def create_note(
        request: Request,
        body: str = Form(...),
        product_ids: str = Form(""),
        rm_ids: str = Form(""),
        brand_ids: str = Form(""),
        current_user: dict = Depends(get_current_user),
    ):
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
        product_refs = _parse_product_refs(text)
        if not product_refs:
            # Fallback: IDs sent separately (hidden field), not parsed from free-text names.
            for pid in _parse_product_ids_field(product_ids):
                product_refs.append({"id": pid, "name": pid})
        rm_refs = _parse_rm_refs(text)
        if not rm_refs:
            for rid in _parse_product_ids_field(rm_ids):
                rm_refs.append({"id": rid, "name": rid})
        brand_refs = _parse_brand_refs(text)
        if not brand_refs:
            for bid in _parse_product_ids_field(brand_ids):
                brand_refs.append({"id": bid, "name": bid})

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

            extra = ""
            if product_refs:
                extra += " | produk: " + ", ".join(p.get("name") or p["id"] for p in product_refs[:5])
            if rm_refs:
                extra += " | rm: " + ", ".join(r.get("name") or r["id"] for r in rm_refs[:5])
            if brand_refs:
                extra += " | merk: " + ", ".join(b.get("name") or b["id"] for b in brand_refs[:5])
            log_activity(
                current_user, "create", "note", note_id or "-",
                (text[:80] + ("…" if len(text) > 80 else "")) + extra,
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

    @app.post("/notes/{note_id}/complete")
    async def complete_note(
        note_id: str,
        completion_note: str = Form(""),
        current_user: dict = Depends(get_current_user),
    ):
        try:
            # Update status
            supabase.table("team_notes").update({
                "is_completed": True,
                "completion_note": completion_note.strip() if completion_note.strip() else None,
                "completed_by_user_id": current_user["id"],
                "completed_by_user_name": current_user.get("full_name") or "User",
                "completed_at": datetime.now(WIB).isoformat(),
            }).eq("id", note_id).execute()
            
            # Log
            log_activity(current_user, "complete", "note", note_id, "Selesai")
        except Exception as e:
            print(f"[NOTES] Gagal menyelesaikan note: {e}")
            return RedirectResponse(url="/notes?error=complete_failed", status_code=303)
        return RedirectResponse(url="/notes?status=completed", status_code=303)

    @app.post("/notes/{note_id}/reopen")
    async def reopen_note(note_id: str, current_user: dict = Depends(get_current_user)):
        try:
            # Reopen
            supabase.table("team_notes").update({
                "is_completed": False,
                "completion_note": None,
                "completed_by_user_id": None,
                "completed_by_user_name": None,
                "completed_at": None,
            }).eq("id", note_id).execute()
            
            # Log
            log_activity(current_user, "reopen", "note", note_id, "Reopened")
        except Exception as e:
            print(f"[NOTES] Gagal membuka kembali note: {e}")
            return RedirectResponse(url="/notes?error=reopen_failed", status_code=303)
        return RedirectResponse(url="/notes?status=reopened", status_code=303)

