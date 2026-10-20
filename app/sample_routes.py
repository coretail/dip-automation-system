"""Sample submission (FSP) routes (extracted from main.py)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

WIB = ZoneInfo("Asia/Jakarta")


def register_sample_routes(
    app,
    get_current_user,
    supabase,
    templates,
    log_activity,
    get_company_info,
    format_date_id,
    mask_email,
):
    # 1. PROSES POST CREATION SAMPLE (Kode FSP Manual)
    @app.post("/sample-submissions/create")
    async def create_sample_submission(
        request: Request,
        sample_prefix: str = Form("FSP"),     # <-- Cuma nangkep Prefix
        brand_id: str = Form(...),
        company: str = Form(None),
        custom_producer: str = Form(None),
        custom_brand: str = Form(None),
        product_id: str = Form(None),
        product_name: str = Form(None),
        product_item: str = Form(None),
        netto: str = Form(None),
        sediaan: str = Form(None),
        kemasan: str = Form(None),
        hero_ingredient: str = Form(None),
        description: str = Form(None),
        qc_signer: str = Form(...),
        rd_signer: str = Form(...),
        ph_value: str = Form(None),
        viscosity_value: str = Form(None),
        color_value: str = Form(None),
        current_user: dict = Depends(get_current_user)
    ):
        final_product_id = None if not product_id else product_id
        if final_product_id:
            prod_master = supabase.table("products").select("nama_produk", "perusahaan").eq("id", final_product_id).execute()
            if prod_master.data:
                final_product_name = prod_master.data[0]['nama_produk']
                # sample_submissions.company constraint: 'Erfi'|'Heka' (tanpa prefix "PT")
                raw_company = (prod_master.data[0].get("perusahaan") or "").strip()
                final_company = re.sub(r"(?i)^PT\s+", "", raw_company).strip()
            else:
                final_product_name = product_name
                final_company = company
        else:
            final_product_name = product_name
            final_company = company

        # --- 1. HITUNG SUFFIX /TGL/X.Y OTOMATIS ---
        prefix_clean = sample_prefix.strip().upper() if sample_prefix and sample_prefix.strip() else "FSP"
        today_str = datetime.now(WIB).strftime("%d-%m-%Y")

        try:
            start_of_day = datetime.now(WIB).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            today_submissions = supabase.table("sample_submissions") \
                .select("sample_code, product_name") \
                .gte("created_at", start_of_day) \
                .execute()

            existing_records = today_submissions.data or []
            distinct_products = list(dict.fromkeys([r['product_name'] for r in existing_records]))

            if final_product_name in distinct_products:
                x_index = distinct_products.index(final_product_name) + 1
            else:
                x_index = len(distinct_products) + 1

            same_product_trials = [r for r in existing_records if r['product_name'] == final_product_name]
            y_index = len(same_product_trials) + 1

            # Gabungin Prefix + Tanggal + X.Y
            sample_code = f"{prefix_clean}/{today_str}/{x_index}.{y_index}"

            all_time_trials = supabase.table("sample_submissions").select("id").eq("product_name", final_product_name).execute()
            revision_number = (len(all_time_trials.data) or 0) + 1

        except Exception as e:
            print(f"Gagal hitung logic FSP: {e}")
            sample_code = f"{prefix_clean}/{today_str}/1.1"
            revision_number = 1

        # AUTO SAVE BRAND DRAFT JIKA PILIH "NEW"
        if brand_id == "new":
            try:
                prod_check = supabase.table("producers").select("id").ilike("name", custom_producer.strip()).execute()
                producer_id = prod_check.data[0]['id'] if prod_check.data else supabase.table("producers").insert({"name": custom_producer.strip()}).execute().data[0]['id']

                brand_check = supabase.table("brands").select("id").eq("producer_id", producer_id).ilike("name", custom_brand.strip()).execute()
                final_brand_id = brand_check.data[0]['id'] if brand_check.data else supabase.table("brands").insert({"producer_id": producer_id, "name": custom_brand.strip()}).execute().data[0]['id']
                draft_prod, draft_brnd = custom_producer, custom_brand
            except Exception:
                final_brand_id, draft_prod, draft_brnd = None, custom_producer, custom_brand
        else:
            final_brand_id, draft_prod, draft_brnd = brand_id, None, None

        additional_notes = {"ph": ph_value, "viscosity": viscosity_value, "color": color_value}

        try:
            data_to_insert = {
                "sample_code": sample_code,
                "product_id": final_product_id,
                "company": final_company,
                "brand_id": final_brand_id,
                "product_name": final_product_name,
                "product_item": product_item if product_item else final_product_name,
                "netto": netto,
                "sediaan": sediaan,
                "kemasan": kemasan,
                "revision_number": revision_number,
                "hero_ingredient": hero_ingredient,
                "description": description,
                "additional_notes": additional_notes,
                "qc_signer": qc_signer,
                "rd_signer": rd_signer,
                "draft_producer": draft_prod,
                "draft_brand": draft_brnd
            }
            result = supabase.table("sample_submissions").insert(data_to_insert).execute()
            new_id = result.data[0]['id']

            # Catat pembuatan FSP. entity_label memakai sample_code (bukan UUID)
            # karena itu pengenal yang dibaca manusia saat membuka berkasan.
            log_activity(
                current_user, "create", "sample_submission", new_id, sample_code,
                changes=[
                    {"field": "Kode FSP", "new": sample_code},
                    {"field": "Produk", "new": final_product_name},
                    {"field": "Merk", "new": final_brand_id and (draft_brnd or None) or None},
                    {"field": "Produsen", "new": draft_prod},
                    {"field": "Perusahaan", "new": final_company},
                    {"field": "Revisi", "new": revision_number},
                    {"field": "Netto", "new": netto},
                    {"field": "Sediaan", "new": sediaan},
                    {"field": "Kemasan", "new": kemasan},
                    {"field": "QC Signer", "new": qc_signer},
                    {"field": "RD Signer", "new": rd_signer},
                ],
                request=request, outcome="success",
            )
        except Exception as e:
            print(f"Eror saat simpan form sample: {e}")
            try:
                log_activity(
                    current_user, "create", "sample_submission", None, sample_code,
                    changes=[{"field": "Kode FSP", "new": sample_code},
                             {"field": "Produk", "new": final_product_name},
                             {"field": "Error", "note": str(e)[:300]}],
                    request=request, outcome="failed",
                )
            except Exception:
                pass
            raise HTTPException(status_code=500, detail="Gagal menyimpan dokumen.")

        return RedirectResponse(url=f"/sample-submissions/preview/{new_id}", status_code=303)


    # 2. HALAMAN FORM EDIT SAMPLE
    @app.get("/sample-submissions/edit/{submission_id}", response_class=HTMLResponse)
    async def edit_sample_submission_page(request: Request, submission_id: str, current_user: dict = Depends(get_current_user)):
        try:
            sub_resp = supabase.table("sample_submissions").select("*").eq("id", submission_id).single().execute()
            submission = sub_resp.data
            if not submission:
                raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")

            brand_query = supabase.table("brands").select("*, producers(*)").execute()
            brands = brand_query.data or []

            product_query = supabase.table("products").select("id, nama_produk, netto, sediaan, kemasan, perusahaan").eq("is_deleted", False).execute()
            products = product_query.data or []
        except Exception as e:
            print(f"Gagal muat data edit sample: {e}")
            raise HTTPException(status_code=500, detail="Gagal memuat form edit")

        return templates.TemplateResponse(
            request=request,
            name="sample_form.html",
            context={
                "brands": brands,
                "existing_products": products,
                "submission": submission,
                "current_user": current_user,
                "ed_notification_count": await get_ed_notification_count()
            }
        )


    # 3. PROSES POST UPDATE SAMPLE
    @app.post("/sample-submissions/edit/{submission_id}")
    async def update_sample_submission(
        request: Request,
        submission_id: str,
        sample_prefix: str = Form("FSP"),   
        brand_id: str = Form(...),
        company: str = Form(None),
        custom_producer: str = Form(None),
        custom_brand: str = Form(None),
        product_id: str = Form(None),
        product_name: str = Form(None),
        product_item: str = Form(None),
        netto: str = Form(None),
        sediaan: str = Form(None),
        kemasan: str = Form(None),
        hero_ingredient: str = Form(None),
        description: str = Form(None),
        qc_signer: str = Form(...),
        rd_signer: str = Form(...),
        ph_value: str = Form(None),
        viscosity_value: str = Form(None),
        color_value: str = Form(None),
        current_user: dict = Depends(get_current_user)
    ):
        # 1. Ambil SELURUH baris lama, bukan cuma sample_code.
        # Selain untuk nemuin suffix /TGL/X.Y, baris lengkap ini dipakai untuk
        # menyusun diff old-vs-new di activity log. Kalau cuma sample_code yang
        # diambil, nilai lama field lain tidak akan pernah tercatat.
        try:
            sub_resp = supabase.table("sample_submissions").select("*").eq("id", submission_id).single().execute()
            old_row = sub_resp.data or {}
            old_code = old_row.get("sample_code") or "FSP/01-01-2026/1.1"

            # Tenant check: non-admin hanya boleh mengubah sample perusahaannya sendiri.
            if current_user.get("role") != "admin":
                _user_company = (current_user.get("perusahaan") or "").strip().lower().replace("pt ", "")
                _old_company = (old_row.get("company") or "").strip().lower().replace("pt ", "")
                if _user_company and _old_company and _user_company != _old_company:
                    raise HTTPException(status_code=403, detail="Akses ditolak! Sample bukan milik perusahaan Anda.")
        except Exception:
            raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")

        prefix_clean = sample_prefix.strip().upper() if sample_prefix and sample_prefix.strip() else "FSP"

        # 2. Pertahankan suffix /TGL/X.Y lama
        if "/" in old_code:
            suffix = old_code.split('/', 1)[1]
            new_sample_code = f"{prefix_clean}/{suffix}"
        else:
            new_sample_code = f"{prefix_clean}/{datetime.now(WIB).strftime('%d-%m-%Y')}/1.1"

        final_product_id = None if not product_id else product_id
        final_product_name = product_name
        final_company = company

        # AUTO-SAVE BRAND BARU saat edit, supaya konsisten dgn create:
        # kalau user pilih "New", produsen & merk langsung dibuat/diambil di DB
        if brand_id == "new":
            try:
                prod_check = supabase.table("producers").select("id").ilike("name", custom_producer.strip()).execute()
                producer_id = prod_check.data[0]['id'] if prod_check.data else supabase.table("producers").insert({"name": custom_producer.strip()}).execute().data[0]['id']

                brand_check = supabase.table("brands").select("id").eq("producer_id", producer_id).ilike("name", custom_brand.strip()).execute()
                final_brand_id = brand_check.data[0]['id'] if brand_check.data else supabase.table("brands").insert({"producer_id": producer_id, "name": custom_brand.strip()}).execute().data[0]['id']
                draft_prod, draft_brnd = custom_producer, custom_brand
            except Exception:
                final_brand_id, draft_prod, draft_brnd = None, custom_producer, custom_brand
        else:
            final_brand_id, draft_prod, draft_brnd = brand_id, None, None

        additional_notes = {"ph": ph_value, "viscosity": viscosity_value, "color": color_value}

        update_payload = {
            "sample_code": new_sample_code,  
            "product_id": final_product_id,
            "company": final_company,
            "brand_id": final_brand_id,
            "product_name": final_product_name,
            "product_item": product_item if product_item else final_product_name,
            "netto": netto,
            "sediaan": sediaan,
            "kemasan": kemasan,
            "hero_ingredient": hero_ingredient,
            "description": description,
            "additional_notes": additional_notes,
            "qc_signer": qc_signer,
            "rd_signer": rd_signer,
            "draft_producer": draft_prod,
            "draft_brand": draft_brnd
        }

        try:
            supabase.table("sample_submissions").update(update_payload).eq("id", submission_id).execute()
        except Exception as e:
            print(f"Gagal update sample submission: {e}")
            try:
                log_activity(
                    current_user, "update", "sample_submission", submission_id,
                    old_code,
                    changes=[{"field": "Kode FSP", "old": old_code,
                              "new": new_sample_code},
                             {"field": "Error", "note": str(e)[:300]}],
                    request=request, outcome="failed",
                )
            except Exception:
                pass
            raise HTTPException(status_code=500, detail="Gagal mengupdate pengajuan sample.")

        # Susun diff old-vs-new memakai helper yang sama dengan produk & bahan baku,
        # supaya bentuk payload audit konsisten di seluruh aplikasi.
        fsp_changes = _build_diff_changes(old_row, update_payload, FSP_FIELD_LABELS)
        fsp_changes += _fsp_notes_changes(old_row, update_payload)
        # Bila diff-nya kosong, tetap catat bahwa dokumen dibuka & disimpan tanpa
        # perubahan isi -- informasi "disimpan tanpa perubahan" itu berguna sendiri.
        if not fsp_changes:
            fsp_changes = [{"field": "Perubahan Isi", "note": "disimpan tanpa perubahan isi"}]

        log_activity(
            current_user, "update", "sample_submission", submission_id,
            new_sample_code,
            changes=fsp_changes, request=request, outcome="success",
        )

        return RedirectResponse(url=f"/sample-submissions/preview/{submission_id}", status_code=303)


    # 4. PROSES HAPUS SAMPLE
    @app.post("/sample-submissions/delete/{submission_id}")
    async def delete_sample_submission(request: Request, submission_id: str,
                                       current_user: dict = Depends(get_current_user)):
        # Baca baris SEBELUM dihapus. Setelah dihapus, isinya hilang begitu saja
        # dan tidak ada cara merekonstruksi apa yang pernah tersimpan.
        old_row = {}
        try:
            old_res = supabase.table("sample_submissions").select("*").eq("id", submission_id).execute()
            if old_res.data:
                old_row = old_res.data[0] or {}
        except Exception as e:
            print(f"Gagal baca sample submission sebelum hapus: {e}")

        old_code = old_row.get("sample_code") or f"Sample {submission_id}"

        if current_user.get("role") != "admin":
            _user_company = (current_user.get("perusahaan") or "").strip().lower().replace("pt ", "")
            _old_company = (old_row.get("company") or "").strip().lower().replace("pt ", "")
            if _user_company and _old_company and _user_company != _old_company:
                raise HTTPException(status_code=403, detail="Akses ditolak! Sample bukan milik perusahaan Anda.")

        try:
            supabase.table("sample_submissions").delete().eq("id", submission_id).execute()
            # Tidak perlu menduplikasi seluruh isi ke changes -- cukup penanda
            # penghapusan beserta pembeda utamanya. Ini menjaga ukuran tabel terkendali.
            log_activity(
                current_user, "delete", "sample_submission", submission_id, old_code,
                changes=[
                    {"field": "Kode FSP", "old": old_row.get("sample_code")},
                    {"field": "Produk", "old": old_row.get("product_name")},
                    {"field": "Perusahaan", "old": old_row.get("company")},
                    {"field": "Revisi", "old": old_row.get("revision_number")},
                    {"field": "Seluruh Isi",
                     "note": "baris dihapus dari sample_submissions"},
                ],
                request=request, outcome="success",
            )
        except Exception as e:
            print(f"Gagal hapus sample submission: {e}")
            log_activity(
                current_user, "delete", "sample_submission", submission_id, old_code,
                changes=[{"field": "Kode FSP", "old": old_row.get("sample_code")},
                         {"field": "Error", "note": str(e)[:300]}],
                request=request, outcome="failed",
            )
        return RedirectResponse(url="/sample-submissions", status_code=303)

    # =====================================================================
    @app.get("/sample-submissions", response_class=HTMLResponse)
    async def sample_submissions_list(request: Request, search: str = None, current_user: dict = Depends(get_current_user)):
        try:
            query = supabase.table("sample_submissions").select("*, brands(*, producers(*))")
            if search:
                search_term = f"%{search}%"
                query = query.or_(f"sample_code.ilike.{search_term},product_name.ilike.{search_term}")
            res = query.order("created_at", desc=True).execute()
            submissions = res.data or []
        except Exception as e:
            print(f"Gagal ambil sample submissions: {e}")
            submissions = []
        return templates.TemplateResponse(
            request=request,
            name="sample_list.html",
            context={
                "request": request,
                "current_user": current_user,
                "submissions": submissions,
                "search_value": search or "",
                "ed_notification_count": await get_ed_notification_count(),
            },
        )

    @app.get("/sample-submissions/form", response_class=HTMLResponse)
    async def sample_submissions_form(request: Request, product_id: str = None, brand_id: str = None, current_user: dict = Depends(get_current_user)):
        try:
            brands_res = supabase.table("brands").select("id, name, producers(name)").order("name").execute()
            brands = brands_res.data or []
        except Exception as e:
            print(f"Gagal ambil brands: {e}")
            brands = []
        product = None
        if product_id:
            try:
                prod_res = supabase.table("products").select("*").eq("id", product_id).execute()
                if prod_res.data:
                    product = prod_res.data[0]
            except Exception as e:
                print(f"Gagal ambil product: {e}")
        return templates.TemplateResponse(
            request=request,
            name="sample_form.html",
            context={
                "request": request,
                "current_user": current_user,
                "submission": None,
                "brands": brands,
                "product": product,
                "brand_id": brand_id,
                "ed_notification_count": await get_ed_notification_count(),
            },
        )

    @app.get("/sample-submissions/preview/{submission_id}", response_class=HTMLResponse)
    async def sample_submissions_preview(request: Request, submission_id: str, current_user: dict = Depends(get_current_user)):
        try:
            res = supabase.table("sample_submissions").select("*, brands(*, producers(*))").eq("id", submission_id).single().execute()
            submission = res.data if res.data else None
        except Exception as e:
            print(f"Gagal ambil sample submission: {e}")
            submission = None
        if not submission:
            raise HTTPException(status_code=404, detail="Pengajuan sample tidak ditemukan.")
        return templates.TemplateResponse(
            request=request,
            name="sample_preview.html",
            context={
                "request": request,
                "current_user": current_user,
                "s": submission,
                "ed_notification_count": await get_ed_notification_count(),
            },
        )
