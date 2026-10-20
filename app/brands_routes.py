"""Brand management routes (extracted from main.py)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from app.file_validation import validate_pdf_bytes
from app import object_store
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

WIB = ZoneInfo("Asia/Jakarta")


def register_brands_routes(
    app,
    get_current_user,
    supabase,
    templates,
    log_activity,
    get_ed_notification_count,
):
    #                     MODUL KELOLA MERK (BRAND)
    # =====================================================================
    @app.post("/brands/add")
    async def add_brand(
        request: Request,
        producer_name: str = Form(...),
        brand_name: str = Form(...),
        current_user: dict = Depends(get_current_user)
    ):
        producer_name = producer_name.strip()
        brand_name = brand_name.strip()

        if not producer_name or not brand_name:
            log_activity(
                current_user, "create", "brand", None, brand_name or "-",
                changes=[{"field": "Validasi",
                          "note": "nama produsen atau nama merk kosong"}],
                request=request, outcome="rejected",
            )
            response = RedirectResponse(url="/brands", status_code=303)
            response.set_cookie("error_msg", "Nama Produsen dan Nama Merk wajib diisi.")
            return response

        try:
            # 1. Cek/get-or-create Produsen (case-insensitive, biar 'Seruni' & 'seruni' gak dobel)
            prod_check = supabase.table("producers").select("id").ilike("name", producer_name).execute()
            # Lacak apakah produsen ikut dibuat, karena itu perubahan master data tersendiri.
            producer_created = False
            if prod_check.data:
                producer_id = prod_check.data[0]["id"]
            else:
                new_prod = supabase.table("producers").insert({"name": producer_name}).execute()
                producer_id = new_prod.data[0]["id"]
                producer_created = True

            # 2. Cek/get-or-create Brand di bawah produsen itu
            brand_check = supabase.table("brands") \
                .select("id") \
                .eq("producer_id", producer_id) \
                .ilike("name", brand_name) \
                .execute()

            if brand_check.data:
                log_activity(
                    current_user, "create", "brand", brand_check.data[0]["id"], brand_name,
                    changes=[{"field": "Nama Merk",
                              "note": f"sudah terdaftar di bawah produsen '{producer_name}'"}],
                    request=request, outcome="rejected",
                )
                response = RedirectResponse(url="/brands", status_code=303)
                response.set_cookie("error_msg", f"Merk '{brand_name}' sudah terdaftar di bawah produsen '{producer_name}'.")
                return response

            new_brand_res = supabase.table("brands").insert({
                "producer_id": producer_id,
                "name": brand_name
            }).execute()
            new_brand_id = new_brand_res.data[0]["id"] if new_brand_res.data else None

            changes = [
                {"field": "Nama Merk", "new": brand_name},
                {"field": "Produsen", "new": producer_name},
                {"field": "ID Produsen", "new": producer_id},
            ]
            # Bedakan dua perubahan master data yang terjadi dalam satu request.
            if producer_created:
                changes.append({"field": "Produsen",
                                "note": "produsen baru ikut dibuat"})

            log_activity(
                current_user, "create", "brand", new_brand_id, brand_name,
                changes=changes, request=request, outcome="success",
            )

            response = RedirectResponse(url="/brands", status_code=303)
            response.set_cookie("success_msg", f"Merk '{brand_name}' berhasil ditambahkan.")
            return response

        except Exception as e:
            print(f"Gagal tambah brand baru: {e}")
            log_activity(
                current_user, "create", "brand", None, brand_name or "-",
                changes=[{"field": "Nama Merk", "new": brand_name},
                         {"field": "Produsen", "new": producer_name},
                         {"field": "Error", "note": str(e)[:300]}],
                request=request, outcome="failed",
            )
            response = RedirectResponse(url="/brands", status_code=303)
            response.set_cookie("error_msg", "Gagal menambahkan merk. Coba lagi.")
            return response


    @app.get("/brands", response_class=HTMLResponse)
    async def brands_page(request: Request, current_user: dict = Depends(get_current_user)):
        try:
            brands_resp = supabase.table("brands").select("*, producers(*)").order("name").execute()
            brands = brands_resp.data or []
        except Exception as e:
            print(f"Gagal ambil data brands: {e}")
            brands = []

        # Fetch legal documents for all brands from brand_legal_documents table
        if brands:
            brand_ids = [b["id"] for b in brands]
            try:
                docs_resp = supabase.table("brand_legal_documents").select("brand_id, perusahaan, hak_lisensi_merk_file_url").in_("brand_id", brand_ids).execute()
                docs_by_brand = {}
                for doc in docs_resp.data or []:
                    bid = doc["brand_id"]
                    if bid not in docs_by_brand:
                        docs_by_brand[bid] = {
                            "PT Erfi": {"hak_lisensi_merk_file_url": None},
                            "PT Heka": {"hak_lisensi_merk_file_url": None},
                        }
                    docs_by_brand[bid][doc["perusahaan"]] = {"hak_lisensi_merk_file_url": doc.get("hak_lisensi_merk_file_url")}

                # Attach to each brand
                for b in brands:
                    # Pastikan selalu ada struktur default, meski merk baru
                    b["legal_docs"] = docs_by_brand.get(b["id"], {
                        "PT Erfi": {"hak_lisensi_merk_file_url": None},
                        "PT Heka": {"hak_lisensi_merk_file_url": None},
                    })
            except Exception as e:
                print(f"Gagal ambil dokumen legal brand: {e}")
                for b in brands:
                    b["legal_docs"] = {
                        "PT Erfi": {"hak_lisensi_merk_file_url": None},
                        "PT Heka": {"hak_lisensi_merk_file_url": None},
                    }
        else:
            # Tambahkan fallback untuk kasus merk ada tapi docs_by_brand kosong
            for b in brands:
                b["legal_docs"] = {
                    "PT Erfi": {"hak_lisensi_merk_file_url": None},
                    "PT Heka": {"hak_lisensi_merk_file_url": None},
                }

        success_msg = request.cookies.get("success_msg")
        error_msg = request.cookies.get("error_msg")

        response = templates.TemplateResponse(
            request=request,
            name="brands.html",
            context={
                "brands": brands,
                "success_msg": success_msg,
                "error_msg": error_msg,
                "ed_notification_count": await get_ed_notification_count(),
                "current_user": current_user
            }
        )
        response.delete_cookie("success_msg")
        response.delete_cookie("error_msg")
        return response


    @app.post("/brands/{brand_id}/update-documents")
    async def update_brand_documents(
        request: Request,
        brand_id: str,
        perusahaan: str = Form(...),
        hak_lisensi_merk_file: UploadFile = File(None),
        current_user: dict = Depends(get_current_user)
    ):
        # Validasi perusahaan
        if perusahaan not in ["PT Erfi", "PT Heka"]:
            log_activity(
                current_user, "update", "brand_legal_document", brand_id, "-",
                changes=[{"field": "Perusahaan", "note": "nilai tidak valid"}],
                request=request, outcome="rejected",
            )
            response = RedirectResponse(url="/brands", status_code=303)
            response.set_cookie("error_msg", "Perusahaan tidak valid. Harus PT Erfi atau PT Heka.")
            return response

        # Label merk supaya log_activity tidak cuma berisi UUID.
        brand_label = brand_id
        try:
            b_res = supabase.table("brands").select("name").eq("id", brand_id).execute()
            if b_res.data and b_res.data[0].get("name"):
                brand_label = b_res.data[0]["name"]
        except Exception:
            pass

        # Map perusahaan to slug for file path
        perusahaan_slug = "erfi" if perusahaan == "PT Erfi" else "heka"

        try:
            update_data = {}
            path = None

            if hak_lisensi_merk_file and hak_lisensi_merk_file.filename:
                file_bytes = await hak_lisensi_merk_file.read()
                _err = validate_pdf_bytes(file_bytes, "File Hak & Lisensi Merk")
                if _err:
                    raise ValueError(_err)
                # Path includes perusahaan_slug to avoid conflicts
                path = f"brands/hak_lisensi_merk_{brand_id}_{perusahaan_slug}.pdf"
                object_store.upload_pdf("legal-documents", path, file_bytes, client=supabase)
                update_data["hak_lisensi_merk_file_url"] = object_store.public_url("legal-documents", path, client=supabase)

            if update_data:
                # Check if row exists for this brand_id + perusahaan
                existing_resp = supabase.table("brand_legal_documents").select("id").eq("brand_id", brand_id).eq("perusahaan", perusahaan).limit(1).execute()

                row_action = "update" if existing_resp.data else "insert"
                if existing_resp.data:
                    # Update existing row.
                    # updated_at harus timestamp ISO dari Python, bukan string "now()" --
                    # PostgREST menyimpan string itu apa adanya dan gagal di-cast ke timestamptz.
                    supabase.table("brand_legal_documents").update({
                        "hak_lisensi_merk_file_url": update_data["hak_lisensi_merk_file_url"],
                        "updated_at": datetime.now(WIB).isoformat()
                    }).eq("brand_id", brand_id).eq("perusahaan", perusahaan).execute()
                else:
                    # Insert new row
                    supabase.table("brand_legal_documents").insert({
                        "brand_id": brand_id,
                        "perusahaan": perusahaan,
                        "hak_lisensi_merk_file_url": update_data["hak_lisensi_merk_file_url"]
                    }).execute()

                # URL lama SENGAJA tidak dicatat: upload memakai upsert di path yang sama,
                # jadi URL lama identik dengan URL baru. Yang dicatat adalah path & aksi
                # baris -- informasi yang berguna tanpa membocorkan apa pun.
                log_activity(
                    current_user, "update", "brand_legal_document", brand_id,
                    f"{brand_label} — {perusahaan}",
                    changes=[
                        {"field": "Hak & Lisensi Merk", "note": "File diganti"},
                        {"field": "Perusahaan", "new": perusahaan},
                        {"field": "Bucket", "new": "legal-documents"},
                        {"field": "Path", "new": path},
                        {"field": "Aksi Baris", "note": row_action},
                    ],
                    request=request, outcome="success",
                )
            else:
                log_activity(
                    current_user, "update", "brand_legal_document", brand_id,
                    f"{brand_label} — {perusahaan}",
                    changes=[{"field": "Upload", "note": "tidak ada berkas yang diunggah"}],
                    request=request, outcome="rejected",
                )

            response = RedirectResponse(url="/brands", status_code=303)
            response.set_cookie("success_msg", f"Dokumen Hak/Lisensi Merk untuk {perusahaan} berhasil diperbarui.")
            return response

        except Exception as e:
            print(f"Gagal update dokumen brand {brand_id} untuk {perusahaan}: {e}")
            log_activity(
                current_user, "update", "brand_legal_document", brand_id,
                f"{brand_label} — {perusahaan}",
                changes=[{"field": "Perusahaan", "new": perusahaan},
                         {"field": "Error", "note": str(e)[:300]}],
                request=request, outcome="failed",
            )
            response = RedirectResponse(url="/brands", status_code=303)
            response.set_cookie("error_msg", "Gagal upload dokumen. Coba lagi.")
            return response
