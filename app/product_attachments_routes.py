"""Routes for private, non-DIP product attachments."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import List
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import object_store

LAMPIRAN_CATEGORIES = (
    "Form ACC Sample",
    "Catatan Formula R&D",
    "Catatan Formula Trial & Perubahan",
    "Surat Pengajuan Uji Sample",
    "Lain-lain",
)
MAX_SIZE = 10 * 1024 * 1024
MAX_FILES_PER_REQUEST = 10
MAX_CATATAN = 500
BUCKET = "product-attachments"
WIB = ZoneInfo("Asia/Jakarta")


def _sanitize_filename(name: str) -> str:
    value = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    value = value.replace("\\", "/").split("/")[-1]
    stem, _ = value.rsplit(".", 1) if "." in value else (value, "")
    stem = re.sub(r"[^A-Za-z0-9]+", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip("_")[:80] or "lampiran"
    return stem + ".pdf"


def _product_slug(nama_produk: str | None) -> str:
    value = unicodedata.normalize("NFKD", nama_produk or "").encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9]+", "_", value)
    return (re.sub(r"_+", "_", value).strip("_")[:80] or "produk").lower()


def _validate_pdf_bytes(data: bytes, filename: str) -> str | None:
    if not (filename or "").lower().endswith(".pdf"):
        return f"File '{filename}' bukan PDF."
    if data[:4] != b"%PDF":
        return f"File '{filename}' bukan PDF yang valid."
    if len(data) > MAX_SIZE:
        return "Ukuran file terlalu besar! Maksimal ukuran file adalah 10 MB. Silakan kompres PDF Anda terlebih dahulu."
    return None


def _can_manage_attachment(row: dict, current_user: dict) -> bool:
    owner = row.get("uploaded_by")
    uid = current_user.get("id")
    return bool(owner and uid and str(owner) == str(uid)) or current_user.get("role") == "admin"


def register_product_attachment_routes(app, *, get_current_user, log_activity, templates, supabase):
    def _signed_urls_or_none(paths: list[str]) -> dict[str, str | None]:
        result = {p: None for p in paths if p}
        if not result:
            return result
        try:
            result.update(object_store.signed_urls(BUCKET, list(result), 3600, client=supabase))
        except Exception as exc:
            print(f"[PRODUCT ATTACHMENTS] signed URL batch gagal: {exc}")
        return result

    def _group_rows(rows, user):
        urls = _signed_urls_or_none([r.get("file_path") for r in rows])
        groups = {}
        for row in rows:
            row["signed_url"] = urls.get(row.get("file_path"))
            raw = row.get("created_at")
            try:
                date_key = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(WIB).strftime("%Y-%m-%d")
            except Exception:
                date_key = str(raw or "")[:10] or "-"
            row["can_manage"] = _can_manage_attachment(row, user)
            groups.setdefault(date_key, []).append(row)
        return groups

    def _load_active_product(product_id: str):
        try:
            response = supabase.table("products").select("*").eq("id", product_id).execute()
            product = (response.data or [None])[0]
        except Exception as exc:
            print(f"Gagal mencari produk {product_id}: {exc}")
            return None, (404, "Produk tidak ditemukan.")
        if not product:
            return None, (404, "Produk tidak ditemukan.")
        if product.get("is_deleted"):
            return None, (409, "Produk ada di sampah (trash). Kembalikan dulu dari trash sebelum mengelola lampiran.")
        return product, None

    def _validation_error(kategori: str, catatan: str):
        if kategori not in LAMPIRAN_CATEGORIES:
            return "Kategori lampiran tidak valid."
        if len(catatan or "") > MAX_CATATAN:
            return "Catatan terlalu panjang (maksimal 500 karakter)."
        return None

    def _attachment_json(row, user):
        return {
            "id": row.get("id"), "file_name": row.get("file_name"),
            "kategori": row.get("kategori"), "catatan": row.get("catatan"),
            "file_size": row.get("file_size"), "uploaded_by_name": row.get("uploaded_by_name"),
            "created_at": row.get("created_at"),
            "signed_url": row.get("signed_url"),
            "can_manage": _can_manage_attachment(row, user),
        }

    @app.get("/products/{product_id}/lampiran", response_class=HTMLResponse)
    async def product_attachments_page(request: Request, product_id: str,
                                        current_user: dict = Depends(get_current_user)):
        product, error = _load_active_product(product_id)
        if error:
            return RedirectResponse(url="/", status_code=303)
        try:
            rows = supabase.table("product_attachments").select("*").eq("product_id", product_id).order("created_at", desc=True).execute().data or []
        except Exception as exc:
            print(f"[PRODUCT ATTACHMENTS] list gagal: {exc}")
            rows = []
        lampiran_groups = _group_rows(rows, current_user)
        return templates.TemplateResponse(request=request, name="product_attachments.html", context={
            "request": request, "product": product, "lampiran": rows, "lampiran_groups": lampiran_groups,
            "lampiran_categories": LAMPIRAN_CATEGORIES, "current_user": current_user,
        })

    @app.post("/products/{product_id}/lampiran")
    async def upload_product_attachments(request: Request, product_id: str,
                                          files: List[UploadFile] = File(...),
                                          kategori: str = Form(...), catatan: str = Form(""),
                                          current_user: dict = Depends(get_current_user)):
        product, error = _load_active_product(product_id)
        if error:
            raise HTTPException(status_code=error[0], detail=error[1])
        if len(files) > MAX_FILES_PER_REQUEST:
            raise HTTPException(400, "Maksimal 10 file per unggahan.")
        if not files or not any(f.filename for f in files):
            raise HTTPException(400, "Pilih minimal satu file PDF.")
        validation = _validation_error(kategori, catatan)
        if validation:
            raise HTTPException(400, validation)
        product_slug = _product_slug(product.get("nama_produk"))
        uploaded, failed = [], []
        for file_obj in files:
            name = file_obj.filename or "lampiran.pdf"
            data = await file_obj.read(MAX_SIZE + 1)
            validation = _validate_pdf_bytes(data, name)
            if validation:
                failed.append({"name": name, "error": validation})
                continue
            now = datetime.now(WIB)
            uid = uuid4().hex[:8]
            new_name = f"{product_slug}_attachment_{now:%Y-%m-%d}_{uid[:4]}.pdf"
            path = f"products/{product_id}/{now:%Y-%m-%d}/{uid}_{new_name}"
            try:
                object_store.upload_pdf(BUCKET, path, data, upsert=False, client=supabase)
            except Exception as exc:
                print(f"[PRODUCT ATTACHMENTS] storage upload gagal: {exc}")
                failed.append({"name": name, "error": "Gagal mengunggah file lampiran ke storage."})
                continue
            try:
                response = supabase.table("product_attachments").insert({
                    "product_id": product_id, "kategori": kategori, "file_name": new_name,
                    "file_path": path, "file_size": len(data), "catatan": catatan or None,
                    "uploaded_by": current_user.get("id"), "uploaded_by_name": current_user.get("full_name"),
                }).execute()
                row = (response.data or [None])[0]
                if not row:
                    raise RuntimeError("empty insert response")
            except Exception as exc:
                try:
                    object_store.remove(BUCKET, path, client=supabase)
                except Exception as rollback_exc:
                    print(f"[PRODUCT ATTACHMENTS] rollback gagal {path}: {rollback_exc}")
                print(f"[PRODUCT ATTACHMENTS] insert gagal: {exc}")
                failed.append({"name": name, "error": "Gagal menyimpan data lampiran ke database."})
                continue
            try:
                log_activity(current_user, "upload", "product_attachment", row["id"], name, request=request)
            except Exception as exc:
                print(f"[PRODUCT ATTACHMENTS] upload audit gagal: {exc}")
            uploaded.append(row)
        urls = _signed_urls_or_none([r.get("file_path") for r in uploaded])
        for row in uploaded:
            row["signed_url"] = urls.get(row.get("file_path"))
        return JSONResponse({"success": True, "uploaded": [_attachment_json(r, current_user) for r in uploaded], "failed": failed})

    async def _owned_attachment(product_id, attachment_id, user, action):
        _, error = _load_active_product(product_id)
        if error:
            raise HTTPException(error[0], error[1])
        try:
            response = supabase.table("product_attachments").select("*").eq("id", attachment_id).eq("product_id", product_id).execute()
            row = (response.data or [None])[0]
        except Exception:
            row = None
        if not row:
            raise HTTPException(404, "Lampiran tidak ditemukan.")
        if not _can_manage_attachment(row, user):
            verb = "menghapus" if action == "delete" else "mengubah"
            raise HTTPException(403, f"Hanya pengunggah atau admin yang boleh {verb} lampiran ini.")
        return row

    @app.post("/products/{product_id}/lampiran/{attachment_id}/edit")
    async def edit_product_attachment(request: Request, product_id: str, attachment_id: str,
                                      kategori: str = Form(...), catatan: str = Form(""),
                                      current_user: dict = Depends(get_current_user)):
        row = await _owned_attachment(product_id, attachment_id, current_user, "edit")
        validation = _validation_error(kategori, catatan)
        if validation:
            raise HTTPException(400, validation)
        supabase.table("product_attachments").update({"kategori": kategori, "catatan": catatan or None}).eq("id", attachment_id).execute()
        try:
            log_activity(current_user, "update", "product_attachment", attachment_id, row.get("file_name"), request=request)
        except Exception as exc:
            print(f"[PRODUCT ATTACHMENTS] edit audit gagal: {exc}")
        return JSONResponse({"success": True})

    @app.post("/products/{product_id}/lampiran/{attachment_id}/delete")
    async def delete_product_attachment(request: Request, product_id: str, attachment_id: str,
                                        current_user: dict = Depends(get_current_user)):
        row = await _owned_attachment(product_id, attachment_id, current_user, "delete")
        path = row.get("file_path") or ""
        prefix = f"products/{product_id}/"
        if (not path.startswith(prefix) or "\\" in path or
                any(part in ("", ".", "..") for part in path.split("/"))):
            raise HTTPException(500, "Path lampiran tidak valid.")
        try:
            remove_result = object_store.remove(BUCKET, path, client=supabase)
        except Exception:
            remove_result = {}
        if not object_store.all_results_ok(remove_result):
            raise HTTPException(500, "Gagal menghapus file lampiran dari storage.")
        supabase.table("product_attachments").delete().eq("id", attachment_id).eq("product_id", product_id).execute()
        try:
            log_activity(current_user, "delete", "product_attachment", attachment_id, row.get("file_name"), request=request)
        except Exception as exc:
            print(f"[PRODUCT ATTACHMENTS] delete audit gagal: {exc}")
        return JSONResponse({"success": True})
