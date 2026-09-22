"""Route /raw-materials/* (master bahan baku, varian komposisi, batch/ED, dokumen company)."""
from __future__ import annotations

from datetime import timedelta
from typing import List

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.database import supabase


def register_raw_materials_routes(
    app,
    get_current_user,
    log_activity,
    templates,
    compute_status_na,
    _resolve_variant_components,
    _ensure_default_variant,
    _flag_bahan_aktif,
    _build_diff_changes,
    _parse_storage_url,
    _upload_msds_and_upsert_company_doc,
):
    """Attach semua route /raw-materials/* ke FastAPI app (avoids circular imports)."""

    @app.get("/raw-materials", response_class=HTMLResponse)
    async def raw_materials_page(request: Request, current_user: dict = Depends(get_current_user)):
        rm_resp = supabase.table("raw_materials").select(
            "*, raw_material_components(*), "
            "raw_material_composition_variants(*, raw_material_components(*)), "
            "raw_material_company_docs(*)"
        ).order("nama_dagang").execute()

        # Tampilan ringkas pakai komponen varian default; struktur variants penuh
        # tetap dibawa buat modal edit (masterRawMaterials di raw_materials.html).
        for rm in (rm_resp.data or []):
            rm["raw_material_components"] = _resolve_variant_components(rm, None)

        success_msg = request.cookies.get("success_msg") or request.query_params.get("success")
        error_msg = request.cookies.get("error_msg") or request.query_params.get("error")

        try:
            query_batches = (
                supabase.table("raw_material_batches")
                .select("""
                    *,
                    raw_materials (
                        nama_dagang,
                        produsen,
                        raw_material_composition_variants (
                            is_default,
                            raw_material_components (
                                inci_name,
                                cas_number
                            )
                        ),
                        raw_material_company_docs (
                            perusahaan,
                            msds_file_url
                        )
                    )
                """)
                .order("created_at", desc=True)
                .execute()
            )
            batches_data = query_batches.data
            # CAS di kartu batch cukup dari varian default (tampilan ringkas,
            # bukan per-produk-spesifik di context ini). Flatten biar kontrak
            # data b.raw_materials.raw_material_components tetap sama.
            for b in batches_data:
                rm_nested = b.get("raw_materials")
                if isinstance(rm_nested, list) and rm_nested:
                    rm_nested = rm_nested[0]
                if isinstance(rm_nested, dict):
                    rm_nested["raw_material_components"] = _resolve_variant_components(rm_nested, None)
        except Exception as e:
            print(f"Gagal ambil data batches: {e}")
            batches_data = []

        # ===== PRE-COMPUTE ED CRITICAL BATCHES FOR NOTIFICATION BADGE =====
        from datetime import datetime
        from zoneinfo import ZoneInfo
        WIB = ZoneInfo("Asia/Jakarta")
        today = datetime.now(WIB).date()
        warning_date = today + timedelta(days=180)

        ed_critical_count = 0
        ed_critical_batches_for_tab = []  # Filtered for ED tab (days_remaining <= 180)

        for b in batches_data:
            tanggal_ed = b.get("tanggal_ed")
            status_ed = b.get("status_ed") or "Active"

            if not tanggal_ed or status_ed == "Dimusnahkan":
                continue

            try:
                if isinstance(tanggal_ed, str):
                    ed_date = datetime.strptime(tanggal_ed[:10], "%Y-%m-%d").date()
                else:
                    ed_date = tanggal_ed
            except Exception:
                continue

            days_remaining = (ed_date - today).days

            # Count for notification badge (critical: <= 180 days or expired)
            if days_remaining <= 180:
                ed_critical_count += 1

                # Add to ED tab filtered list
                # Auto-update status for display
                display_status = status_ed
                if days_remaining <= 0 and status_ed == "Active":
                    display_status = "Expired"
                elif days_remaining <= 180 and status_ed == "Active":
                    display_status = "Kritis (<= 180 hari)"

                ed_critical_batches_for_tab.append({
                    **b,
                    "computed_days_remaining": days_remaining,
                    "computed_status_ed": display_status
                })

        # Sort ED tab batches by days_remaining (expired first, then closest to expiry)
        ed_critical_batches_for_tab.sort(key=lambda x: x["computed_days_remaining"])

        sorted_batches = sorted(batches_data, key=lambda b: b.get("created_at") or "", reverse=True)
        latest_batch_map = {}
        for b in sorted_batches:
            if b.get("kesimpulan") == "lab":
                continue
            key = (b.get("raw_material_id"), b.get("perusahaan"))
            if key not in latest_batch_map:
                latest_batch_map[key] = b

        # Pre-map all batch numbers to raw_material_id for searching in frontend Master Tab
        rm_batch_nums = {}
        for b in batches_data:
            rm_id = b.get("raw_material_id")
            bn = b.get("no_batch")
            if rm_id and bn:
                if rm_id not in rm_batch_nums:
                    rm_batch_nums[rm_id] = set()
                rm_batch_nums[rm_id].add(str(bn).strip())

        # Compute has_lab_batch for badge display in Master tab
        lab_material_ids = {b.get("raw_material_id") for b in batches_data if b.get("kesimpulan") == "lab"}

        doc_status = {}
        for rm in rm_resp.data:
            rm_id = rm["id"]
            # Add all batch numbers as a space-separated string for frontend search
            rm["all_batch_numbers"] = " ".join(rm_batch_nums.get(rm_id, []))
            rm["has_lab_batch"] = rm_id in lab_material_ids

            company_docs = {d["perusahaan"]: d for d in (rm.get("raw_material_company_docs") or [])}
            status_per_company = {}
            for company in ["PT Erfi", "PT Heka"]:
                doc = company_docs.get(company, {})
                spec_params = doc.get("spec_parameters") or []
                spec_text_filled = any((item.get("value") or "").strip() for item in spec_params if isinstance(item, dict))
                spec_sheet_url = doc.get("spec_sheet_file_url")
                msds_url = doc.get("msds_file_url")

                batch = latest_batch_map.get((rm["id"], company))
                qc_results = (batch.get("qc_results") if batch else None) or []
                qc_text_filled = any((item.get("value") or "").strip() for item in qc_results if isinstance(item, dict))
                qc_report_url = batch.get("qc_report_file_url") if batch else None
                coa_url = batch.get("coa_file_url") if batch else None
                halal_url = batch.get("halal_batch_file_url") if batch else None

                status_per_company[company] = {
                    "spec_ok": bool(spec_text_filled or spec_sheet_url),
                    "spec_sheet_url": spec_sheet_url,
                    "msds_url": msds_url,
                    "coa_url": coa_url,
                    "halal_url": halal_url,
                    "qc_report_url": qc_report_url,
                    "qc_ok": bool(qc_text_filled or qc_report_url),
                    "has_batch": batch is not None,
                    "batch_id": batch.get("id") if batch else None,
                }
            doc_status[rm["id"]] = status_per_company

        # ===== HITUNG JUMLAH PRODUK PEMAKAI TIAP BAHAN BAKU (Badge Counter) =====
        try:
            usage_lines = supabase.table("product_formula_lines") \
                .select("raw_material_id, product_id").execute()
            usage_sets = {}
            for ln in (usage_lines.data or []):
                rm_id_ln = ln.get("raw_material_id")
                prod_id_ln = ln.get("product_id")
                if rm_id_ln and prod_id_ln:
                    # Satu bahan baku dihitung maksimal sekali per produk
                    usage_sets.setdefault(rm_id_ln, set()).add(prod_id_ln)
            for rm in rm_resp.data:
                rm["usage_count"] = len(usage_sets.get(rm["id"], ()))
        except Exception as e:
            print(f"Gagal hitung pemakaian bahan baku: {e}")
            for rm in rm_resp.data:
                rm.setdefault("usage_count", 0)

        response = templates.TemplateResponse(
            request=request,
            name="raw_materials.html",
            context={
                "raw_materials": rm_resp.data,
                "batches": batches_data,
                "ed_critical_batches": ed_critical_batches_for_tab,  # Filtered for ED tab
                "ed_notification_count": ed_critical_count,  # For immediate badge rendering
                "doc_status": doc_status,
                "current_user": current_user,
                "success_msg": success_msg,
                "error_msg": error_msg
            }
        )

        if success_msg:
            response.delete_cookie("success_msg")
        if error_msg:
            response.delete_cookie("error_msg")

        return response

    # ==================== API: PRODUK PEMAKAI BAHAN BAKU ====================
    @app.get("/raw-materials/{rm_id}/used-in-products")
    async def get_raw_material_used_in_products(rm_id: str, current_user: dict = Depends(get_current_user)):
        """API JSON: daftar produk yang memakai bahan baku tertentu di formula-nya."""
        try:
            rm_resp = supabase.table("raw_materials") \
                .select("id, nama_dagang, kode_bahan_baku") \
                .eq("id", rm_id).limit(1).execute()
            raw_material = (rm_resp.data or [None])[0]
            if not raw_material:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "error": "Bahan baku tidak ditemukan."}
                )

            lines_resp = supabase.table("product_formula_lines") \
                .select("percent_in_formula, products(id, nama_produk, perusahaan)") \
                .eq("raw_material_id", rm_id).execute()

            products_map = {}
            for ln in (lines_resp.data or []):
                product = ln.get("products")
                if not product or not product.get("id"):
                    continue
                pid = product["id"]
                if pid in products_map:
                    continue  # satu produk cukup tampil sekali
                try:
                    percent = float(ln.get("percent_in_formula") or 0)
                except (TypeError, ValueError):
                    percent = 0.0
                products_map[pid] = {
                    "product_id": pid,
                    "nama_produk": product.get("nama_produk") or "-",
                    "perusahaan": product.get("perusahaan") or "-",
                    "percent_in_formula": round(percent, 4),
                }

            products = sorted(products_map.values(), key=lambda p: p["nama_produk"].lower())
            return JSONResponse(status_code=200, content={
                "success": True,
                "raw_material": raw_material,
                "total_products": len(products),
                "products": products,
            })
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

    @app.post("/raw-materials/{rm_id}/quick-upload-company-doc")
    async def quick_upload_company_doc(
        rm_id: str,
        perusahaan: str = Form(...),
        msds_file: UploadFile = File(None),
        spec_sheet_file: UploadFile = File(None),
        current_user: dict = Depends(get_current_user)
    ):
        # PENTING: ambil dulu spec_parameters yang sudah tersimpan sebelum manggil helper,
        # supaya field spesifikasi teks (Pemerian Standar, Batas pH, dst.) yang sudah diisi
        # sebelumnya TIDAK ke-timpa kosong oleh helper _upload_msds_and_upsert_company_doc
        # (helper itu selalu menimpa kolom spec_parameters dengan apa yang dikirim).
        import json

        rm_resp = supabase.table("raw_materials").select("kode_bahan_baku, nama_dagang").eq("id", rm_id).single().execute()
        if not rm_resp.data:
            response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
            response.set_cookie("error_msg", "Bahan baku tidak ditemukan.")
            return response
        kode_bahan_baku = rm_resp.data["kode_bahan_baku"]
        nama_bahan_baku = rm_resp.data.get("nama_dagang") or kode_bahan_baku

        existing_resp = supabase.table("raw_material_company_docs") \
            .select("spec_parameters") \
            .eq("raw_material_id", rm_id).eq("perusahaan", perusahaan).execute()
        existing_specs = existing_resp.data[0]["spec_parameters"] if existing_resp.data else []
        spec_parameters_raw = json.dumps(existing_specs or [])

        try:
            uploaded_documents = await _upload_msds_and_upsert_company_doc(
                rm_id, kode_bahan_baku, perusahaan, spec_parameters_raw, msds_file, spec_sheet_file
            )
            response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
            if uploaded_documents:
                document_list = " dan ".join(uploaded_documents)
                log_activity(
                    current_user, "edit", "raw_material_company_doc", rm_id,
                    f"Upload cepat {document_list} untuk bahan baku {nama_bahan_baku} ({perusahaan})"
                )
                response.set_cookie("success_msg", "Dokumen berhasil diupload.")
            else:
                response.set_cookie("error_msg", "Tidak ada dokumen yang berhasil diupload.")
        except Exception as e:
            print(f"Gagal quick-upload company doc: {e}")
            response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
            response.set_cookie("error_msg", "Gagal upload dokumen. Coba lagi.")
        return response

    @app.post("/raw-materials/add")
    async def add_raw_material(
        request: Request,
        nama_dagang: str = Form(...),
        kode_bahan_baku: str = Form(...),
        tipe: str = Form(...),
        produsen: str = Form(None),
        msds_file_erfi: UploadFile = File(None),
        msds_file_heka: UploadFile = File(None),
        spec_sheet_file_erfi: UploadFile = File(None),
        spec_sheet_file_heka: UploadFile = File(None),
        inci_name: list[str] = Form(None),
        cas_number: list[str] = Form(None),
        function: list[str] = Form(None),
        percent_internal: list[float] = Form(None),
        is_bahan_aktif: list[str] = Form(None),
        spec_parameters_erfi: str = Form("[]"),
        spec_parameters_heka: str = Form("[]"),
        current_user: dict = Depends(get_current_user)
    ):
        # Payload raw_materials sekarang cuma identitas -- spec & MSDS udah pindah ke raw_material_company_docs
        insert_payload = {
            "nama_dagang": nama_dagang,
            "kode_bahan_baku": kode_bahan_baku,
            "tipe": tipe,
            "produsen": produsen,
        }

        kode_check = kode_bahan_baku.strip()
        existing_rm = supabase.table("raw_materials").select("id").eq("kode_bahan_baku", kode_check).execute()

        # JIKA GAGAL (Kode Dobel)
        if existing_rm.data:
            response = RedirectResponse(url="/raw-materials", status_code=303)
            response.set_cookie("error_msg", f"Kode '{kode_check}' udah terdaftar. Gunakan kode lain.")
            return response

        rm_resp = supabase.table("raw_materials").insert(insert_payload).execute()
        if not rm_resp.data:
            response = RedirectResponse(url="/raw-materials", status_code=303)
            response.set_cookie("error_msg", f"Gagal menyimpan bahan baku '{nama_dagang}'. Silakan coba lagi.")
            return response
        new_rm_id = rm_resp.data[0]["id"]

        log_activity(current_user, "create", "raw_material", new_rm_id, nama_dagang)

        # --- Simpan spec + MSDS per perusahaan (kalau diisi) ---
        try:
            await _upload_msds_and_upsert_company_doc(new_rm_id, kode_check, "PT Erfi", spec_parameters_erfi, msds_file_erfi, spec_sheet_file_erfi)
            await _upload_msds_and_upsert_company_doc(new_rm_id, kode_check, "PT Heka", spec_parameters_heka, msds_file_heka, spec_sheet_file_heka)

            # Bahan baru selalu mulai dengan 1 varian default (nama dari produsen);
            # semua komponen breakdown nempel ke varian ini.
            default_variant_id = _ensure_default_variant(new_rm_id, produsen)

            if tipe == "single":
                given_inci = inci_name[0].strip() if (inci_name and inci_name[0]) else ""
                comp_data = {
                    "raw_material_id": new_rm_id,
                    "variant_id": default_variant_id,
                    "inci_name": given_inci if given_inci else nama_dagang, 
                    "cas_number": cas_number[0] if cas_number else None,
                    "function": function[0] if function else None,
                    "percent_internal": 100.0,
                    "is_bahan_aktif": _flag_bahan_aktif(is_bahan_aktif, 0),
                }
                supabase.table("raw_material_components").insert(comp_data).execute()

            elif tipe == "komposit" and inci_name:
                components = []
                for i in range(len(inci_name)):
                    if inci_name[i].strip():
                        components.append({
                            "raw_material_id": new_rm_id,
                            "variant_id": default_variant_id,
                            "inci_name": inci_name[i],
                            "cas_number": cas_number[i] if i < len(cas_number) else None,
                            "function": function[i] if i < len(function) else None,
                            "percent_internal": percent_internal[i],
                            "is_bahan_aktif": _flag_bahan_aktif(is_bahan_aktif, i),
                        })
                if components:
                    supabase.table("raw_material_components").insert(components).execute()

            # JIKA BERHASIL: Set cookie tanda sukses lalu redirect
            response = RedirectResponse(url="/raw-materials", status_code=303)
            response.set_cookie("success_msg", f"Mantap! Bahan baku '{nama_dagang}' berhasil ditambahkan.")
            return response

        except Exception as e:
            print(f"\n🔴 [ERROR add_raw_material] Bahan baku '{nama_dagang}' (id={new_rm_id}) sudah tersimpan, tapi data pendukung (komponen INCI/dokumen) gagal: {e}")
            response = RedirectResponse(url="/raw-materials", status_code=303)
            response.set_cookie("error_msg", f"Bahan baku '{nama_dagang}' tersimpan, tapi ada data pendukung yang gagal disimpan. Silakan cek dan lengkapi lewat menu Edit.")
            return response

    @app.post("/raw-materials/quick-add")
    async def quick_add_raw_material(
        nama_dagang: str = Form(...),
        kode_bahan_baku: str = Form(...),
        tipe: str = Form(...),
        produsen: str = Form(None),
        current_user: dict = Depends(get_current_user)
    ):
        kode_check = kode_bahan_baku.strip()
        # Cek duplikat kode (pola yang sama dengan add_raw_material)
        existing_rm = supabase.table("raw_materials").select("id").eq("kode_bahan_baku", kode_check).execute()

        if existing_rm.data:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"Kode '{kode_check}' udah terdaftar."}
            )

        insert_payload = {
            "nama_dagang": nama_dagang,
            "kode_bahan_baku": kode_check,
            "tipe": tipe,
            "produsen": produsen,
        }

        try:
            rm_resp = supabase.table("raw_materials").insert(insert_payload).execute()
            if not rm_resp.data:
                return JSONResponse(status_code=500, content={"success": False, "error": "Gagal menyimpan ke database."})

            new_rm = rm_resp.data[0]
            # Panggil log_activity (pola yang sama dengan add_raw_material)
            log_activity(current_user, "create", "raw_material", new_rm["id"], nama_dagang)

            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "id": new_rm["id"],
                    "nama_dagang": new_rm["nama_dagang"],
                    "kode_bahan_baku": new_rm["kode_bahan_baku"]
                }
            )
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

    @app.post("/raw-materials/edit/{rm_id}")
    async def edit_raw_material(
        rm_id: str,
        nama_dagang: str = Form(...),
        kode_bahan_baku: str = Form(...),
        tipe: str = Form(...),
        produsen: str = Form(None),
        inci_name: List[str] = Form(None),
        cas_number: List[str] = Form(None),
        function: List[str] = Form(None),
        percent_internal: List[float] = Form(None),
        is_bahan_aktif: List[str] = Form(None),
        msds_file_erfi: UploadFile = File(None),
        msds_file_heka: UploadFile = File(None),
        spec_sheet_file_erfi: UploadFile = File(None),
        spec_sheet_file_heka: UploadFile = File(None),
        spec_parameters_erfi: str = Form("[]"),
        spec_parameters_heka: str = Form("[]"),
        current_user: dict = Depends(get_current_user),
        variant_id: str = Form(None),
    ):
        kode_check = " ".join(kode_bahan_baku.split())  # trim + collapse spasi ganda jadi 1
        existing_rm = supabase.table("raw_materials").select("id").eq("kode_bahan_baku", kode_check).neq("id", rm_id).execute()

        if existing_rm.data:
            raise HTTPException(status_code=400, detail=f"Gagal Edit! Kode '{kode_check}' sudah dipakai oleh bahan baku lain.")

        # --- Target varian yang lagi diedit (form baru kirim variant_id; form lama
        #     / tanpa kirim = varian default, get-or-create biar selalu ada) ---
        editing_variant_id = (variant_id or "").strip() or None
        if editing_variant_id:
            variant_check = supabase.table("raw_material_composition_variants") \
                .select("id").eq("id", editing_variant_id).eq("raw_material_id", rm_id) \
                .limit(1).execute()
            if not variant_check.data:
                raise HTTPException(status_code=400, detail="Varian yang dipilih tidak cocok dengan bahan baku ini.")
        else:
            editing_variant_id = _ensure_default_variant(rm_id, produsen)

        # --- Ambil data LAMA dulu sebelum diubah, buat dibandingin di activity log ---
        old_rm_resp = supabase.table("raw_materials").select("*").eq("id", rm_id).single().execute()
        old_rm = old_rm_resp.data or {}
        old_company_docs_resp = supabase.table("raw_material_company_docs").select("*").eq("raw_material_id", rm_id).execute()
        old_company_docs = {d["perusahaan"]: d for d in (old_company_docs_resp.data or [])}
        # --- Ambil data komponen LAMA buat dibandingin (scoped ke varian yang lagi
        #     diedit + sisa legacy tanpa varian) ---
        old_components_resp = supabase.table("raw_material_components").select("*").eq("raw_material_id", rm_id).order("id").execute()
        old_components = [
            c for c in (old_components_resp.data or [])
            if c.get("variant_id") in (None, editing_variant_id)
        ]

        # --- Bangun list komponen BARU dari form data ---
        new_components = []
        if tipe == "single":
            given_inci = inci_name[0].strip() if (inci_name and inci_name[0]) else ""
            comp_data = {
                "inci_name": given_inci if given_inci else nama_dagang,
                "cas_number": cas_number[0] if cas_number else None,
                "function": function[0] if function else None,
                "percent_internal": 100.0,
                "is_bahan_aktif": _flag_bahan_aktif(is_bahan_aktif, 0),
            }
            new_components.append(comp_data)
        elif tipe == "komposit" and inci_name:
            for i in range(len(inci_name)):
                if inci_name[i].strip():
                    new_components.append({
                        "inci_name": inci_name[i],
                        "cas_number": cas_number[i] if i < len(cas_number) else None,
                        "function": function[i] if i < len(function) else None,
                        "percent_internal": percent_internal[i],
                        "is_bahan_aktif": _flag_bahan_aktif(is_bahan_aktif, i),
                    })

        # --- Bandingin komponen lama vs baru (scoped ke varian yang lagi diedit) ---
        changes = []
        old_map = {c["inci_name"]: c for c in old_components}
        new_map = {c["inci_name"]: c for c in new_components}
        variant_label = ""
        variant_name_resp = supabase.table("raw_material_composition_variants") \
            .select("nama_varian").eq("id", editing_variant_id).limit(1).execute()
        if variant_name_resp.data:
            variant_label = f" [varian {variant_name_resp.data[0].get('nama_varian')}]"

        for inci in set(old_map.keys()) - set(new_map.keys()):
            changes.append({"field": f"Bahan ({inci}){variant_label}", "note": "Dihapus dari breakdown"})
        for inci in set(new_map.keys()) - set(old_map.keys()):
            changes.append({"field": f"Bahan ({inci}){variant_label}", "note": "Ditambahkan ke breakdown"})
        for inci in set(old_map.keys()) & set(new_map.keys()):
            old_c = old_map[inci]
            new_c = new_map[inci]
            if old_c.get("is_bahan_aktif") != new_c.get("is_bahan_aktif"):
                 changes.append({"field": f"Bahan Aktif ({inci}){variant_label}", "old": "Ya" if old_c.get("is_bahan_aktif") else "Tidak", "new": "Ya" if new_c.get("is_bahan_aktif") else "Tidak"})
            if float(old_c.get("percent_internal", 0)) != float(new_c.get("percent_internal", 0)):
                 changes.append({"field": f"Persentase ({inci}){variant_label}", "old": f"{old_c.get('percent_internal')}%", "new": f"{new_c.get('percent_internal')}%"})
            if (old_c.get("function") or "") != (new_c.get("function") or ""):
                 changes.append({"field": f"Fungsi ({inci}){variant_label}", "old": old_c.get("function") or "-", "new": new_c.get("function") or "-"})
            if (old_c.get("cas_number") or "") != (new_c.get("cas_number") or ""):
                 changes.append({"field": f"CAS Number ({inci}){variant_label}", "old": old_c.get("cas_number") or "-", "new": new_c.get("cas_number") or "-"})

        # 1. UPDATE IDENTITAS DI RAW_MATERIALS (spec & MSDS udah pindah ke raw_material_company_docs)
        update_data = {
            "nama_dagang": nama_dagang,
            "kode_bahan_baku": kode_check,
            "tipe": tipe,
            "produsen": produsen,
        }
        supabase.table("raw_materials").update(update_data).eq("id", rm_id).execute()

        # --- Bandingin perubahan identitas buat activity log ---
        field_labels = {
            "nama_dagang": "Nama Dagang",
            "kode_bahan_baku": "Kode Bahan Baku",
            "tipe": "Tipe",
            "produsen": "Produsen",
        }
        changes.extend(_build_diff_changes(old_rm, update_data, field_labels))

        # --- Bandingin perubahan spesifikasi & dokumen per perusahaan ---
        import json as _json_diff
        for company, spec_raw, msds_file, spec_sheet_file in [
            ("PT Erfi", spec_parameters_erfi, msds_file_erfi, spec_sheet_file_erfi),
            ("PT Heka", spec_parameters_heka, msds_file_heka, spec_sheet_file_heka),
        ]:
            old_doc = old_company_docs.get(company, {})
            try:
                new_specs = _json_diff.loads(spec_raw) if spec_raw else []
            except Exception:
                new_specs = []
            old_specs = old_doc.get("spec_parameters") or []
            old_map = {i.get("key"): (i.get("value") or "").strip() for i in old_specs if isinstance(i, dict)}
            new_map = {i.get("key"): (i.get("value") or "").strip() for i in new_specs if isinstance(i, dict)}
            for key in set(list(old_map.keys()) + list(new_map.keys())):
                if old_map.get(key, "") != new_map.get(key, ""):
                    changes.append({"field": f"Spek {key} ({company})", "old": old_map.get(key) or "-", "new": new_map.get(key) or "-"})
            if msds_file and msds_file.filename:
                changes.append({"field": f"MSDS ({company})", "note": "File diganti"})
            if spec_sheet_file and spec_sheet_file.filename:
                changes.append({"field": f"PDF Spesifikasi ({company})", "note": "File diganti"})

        # 2. UPSERT SPEC + MSDS PER PERUSAHAAN
        await _upload_msds_and_upsert_company_doc(rm_id, kode_check, "PT Erfi", spec_parameters_erfi, msds_file_erfi, spec_sheet_file_erfi)
        await _upload_msds_and_upsert_company_doc(rm_id, kode_check, "PT Heka", spec_parameters_heka, msds_file_heka, spec_sheet_file_heka)

        if changes:
            log_activity(current_user, "update", "raw_material", rm_id, nama_dagang, changes)

        # --- Sisa kode management komponen INCI lu di bawah biarkan utuh ---
        # TAPI scoped ke varian yang lagi diedit: komponen milik varian itu + sisa
        # legacy tanpa varian dihapus & diganti (varian lain tidak disentuh).
        supabase.table("raw_material_components").delete().eq("raw_material_id", rm_id).is_("variant_id", None).execute()
        supabase.table("raw_material_components").delete().eq("variant_id", editing_variant_id).execute()

        if tipe == "single":
            given_inci = inci_name[0].strip() if (inci_name and inci_name[0]) else ""
            comp_data = {
                "raw_material_id": rm_id,
                "variant_id": editing_variant_id,
                "inci_name": given_inci if given_inci else nama_dagang,
                "cas_number": cas_number[0] if cas_number else None,
                "function": function[0] if function else None,
                "percent_internal": 100.0,
                "is_bahan_aktif": _flag_bahan_aktif(is_bahan_aktif, 0),
            }
            supabase.table("raw_material_components").insert(comp_data).execute()

        elif tipe == "komposit" and inci_name:
            components = []
            for i in range(len(inci_name)):
                if inci_name[i].strip():
                    components.append({
                        "raw_material_id": rm_id,
                        "variant_id": editing_variant_id,
                        "inci_name": inci_name[i],
                        "cas_number": cas_number[i] if i < len(cas_number) else None,
                        "function": function[i] if i < len(function) else None,
                        "percent_internal": percent_internal[i],
                        "is_bahan_aktif": _flag_bahan_aktif(is_bahan_aktif, i),
                    })
            if components:
                supabase.table("raw_material_components").insert(components).execute()

        return RedirectResponse(url="/raw-materials", status_code=303)

    @app.post("/raw-materials/delete/{rm_id}")
    async def delete_raw_material(rm_id: str, current_user: dict = Depends(get_current_user)):
        # Cek dulu apakah bahan baku ini masih dipakai di formula produk manapun
        usage_check = supabase.table("product_formula_lines").select("product_id, products(nama_produk)").eq("raw_material_id", rm_id).execute()

        if usage_check.data:
            jumlah_pemakaian = len(usage_check.data)
            # Ambil daftar nama produk
            produk_terkait = []
            for line in usage_check.data:
                if line.get("products") and line.get("products").get("nama_produk"):
                    produk_terkait.append(f"{line.get('products').get('nama_produk')} (ID: {line.get('product_id')})")

            produk_str = ", ".join(produk_terkait[:3]) # Limit ke 3 produk pertama
            if len(produk_terkait) > 3:
                produk_str += "..."

            return RedirectResponse(
                url=f"/raw-materials?error=Bahan+baku+ini+masih+dipakai+di+{jumlah_pemakaian}+formula+produk:+{produk_str.replace(' ', '+')}",
                status_code=303
            )

        # Ambil nama-nya dulu sebelum dihapus, biar activity log masih kebaca gak "id doang"
        rm_before = supabase.table("raw_materials").select("nama_dagang").eq("id", rm_id).single().execute()
        nama_sebelum_hapus = rm_before.data.get("nama_dagang") if rm_before.data else rm_id

        try:
            # Cascade delete: kumpulkan semua URL file (batch: CoA/Halal/CPBB, company docs: Spek/MSDS)
            # sebelum baris DB-nya dihapus, biar filenya juga ikut dibersihkan dari storage
            batches_resp = supabase.table("raw_material_batches") \
                .select("coa_file_url, halal_batch_file_url, qc_report_file_url") \
                .eq("raw_material_id", rm_id).execute()
            docs_resp = supabase.table("raw_material_company_docs") \
                .select("msds_file_url, spec_sheet_file_url") \
                .eq("raw_material_id", rm_id).execute()

            urls_to_delete = []
            for b in (batches_resp.data or []):
                urls_to_delete += [b.get("coa_file_url"), b.get("halal_batch_file_url"), b.get("qc_report_file_url")]
            for d in (docs_resp.data or []):
                urls_to_delete += [d.get("msds_file_url"), d.get("spec_sheet_file_url")]

            for url in urls_to_delete:
                if not url:
                    continue
                bucket, path = _parse_storage_url(url)
                if bucket and path:
                    try:
                        supabase.storage.from_(bucket).remove([path])
                    except Exception as e:
                        print(f"Gagal hapus file storage {path}: {e}")

            # Hapus baris-baris dependent dulu, baru bahan bakunya sendiri
            supabase.table("raw_material_batches").delete().eq("raw_material_id", rm_id).execute()
            supabase.table("raw_material_company_docs").delete().eq("raw_material_id", rm_id).execute()
            supabase.table("raw_material_components").delete().eq("raw_material_id", rm_id).execute()
            # Varian komposisi ikut dibersihkan (FK raw_material_id pakai CASCADE,
            # tapi di sini eksplisit biar tetap bersih walau skema belum migrasi penuh)
            supabase.table("raw_material_composition_variants").delete().eq("raw_material_id", rm_id).execute()
            supabase.table("raw_materials").delete().eq("id", rm_id).execute()
        except Exception as e:
            print(f"Gagal hapus raw_material {rm_id}: {e}")
            return RedirectResponse(url="/raw-materials?error=Gagal+menghapus+bahan+baku.+Coba+lagi+atau+hubungi+admin.", status_code=303)

        log_activity(current_user, "delete", "raw_material", rm_id, nama_sebelum_hapus)

        return RedirectResponse(url="/raw-materials?success=Bahan+baku+beserta+seluruh+riwayat+batch+%26+dokumen+terkait+berhasil+dihapus", status_code=303)

    # ==================== ENDPOINT KELOLA VARIAN KOMPOSISI ====================
    @app.get("/raw-materials/{rm_id}/variants")
    async def list_raw_material_variants(rm_id: str, current_user: dict = Depends(get_current_user)):
        """JSON daftar varian sebuah bahan baku (dipakai modal edit + Fase 4 formula)."""
        resp = supabase.table("raw_material_composition_variants") \
            .select("id, nama_varian, is_default") \
            .eq("raw_material_id", rm_id).order("created_at").execute()
        return JSONResponse(content={"success": True, "variants": resp.data or []})

    @app.post("/raw-materials/{rm_id}/variants/add")
    async def add_raw_material_variant(
        rm_id: str,
        nama_varian: str = Form(...),
        current_user: dict = Depends(get_current_user),
    ):
        nama = (nama_varian or "").strip()
        if not nama:
            response = RedirectResponse(url="/raw-materials", status_code=303)
            response.set_cookie("error_msg", "Nama varian/produsen wajib diisi.")
            return response
        rm_check = supabase.table("raw_materials").select("id, nama_dagang").eq("id", rm_id).limit(1).execute()
        if not rm_check.data:
            raise HTTPException(status_code=404, detail="Bahan baku tidak ditemukan.")
        dup = supabase.table("raw_material_composition_variants") \
            .select("id").eq("raw_material_id", rm_id).ilike("nama_varian", nama).limit(1).execute()
        if dup.data:
            response = RedirectResponse(url="/raw-materials", status_code=303)
            response.set_cookie("error_msg", f"Varian '{nama}' sudah ada untuk bahan ini.")
            return response
        new_variant = supabase.table("raw_material_composition_variants").insert({
            "raw_material_id": rm_id,
            "nama_varian": nama,
            "is_default": False,
        }).execute()
        log_activity(current_user, "create", "raw_material_variant", new_variant.data[0]["id"], f"{rm_check.data[0].get('nama_dagang')} / {nama}")
        response = RedirectResponse(url="/raw-materials", status_code=303)
        response.set_cookie("success_msg", f"Varian '{nama}' berhasil ditambahkan. Isi breakdown INCI-nya lewat menu Edit.")
        return response

    @app.post("/raw-materials/{rm_id}/variants/{variant_id}/set-default")
    async def set_default_raw_material_variant(rm_id: str, variant_id: str, current_user: dict = Depends(get_current_user)):
        target = supabase.table("raw_material_composition_variants") \
            .select("id, nama_varian, raw_material_id").eq("id", variant_id).limit(1).execute()
        if not target.data or target.data[0].get("raw_material_id") != rm_id:
            raise HTTPException(status_code=400, detail="Varian yang dipilih tidak cocok dengan bahan baku ini.")
        # Unset semua dulu baru set yang baru (aman terhadap unique index 1-default).
        supabase.table("raw_material_composition_variants") \
            .update({"is_default": False}).eq("raw_material_id", rm_id).execute()
        supabase.table("raw_material_composition_variants") \
            .update({"is_default": True}).eq("id", variant_id).execute()
        log_activity(current_user, "update", "raw_material_variant", variant_id, f"{target.data[0].get('nama_varian')} (jadi default)")
        response = RedirectResponse(url="/raw-materials", status_code=303)
        response.set_cookie("success_msg", f"Varian '{target.data[0].get('nama_varian')}' sekarang jadi varian default.")
        return response

    @app.post("/raw-materials/{rm_id}/variants/{variant_id}/delete")
    async def delete_raw_material_variant(rm_id: str, variant_id: str, current_user: dict = Depends(get_current_user)):
        target = supabase.table("raw_material_composition_variants") \
            .select("id, nama_varian, is_default, raw_material_id").eq("id", variant_id).limit(1).execute()
        if not target.data or target.data[0].get("raw_material_id") != rm_id:
            raise HTTPException(status_code=400, detail="Varian yang dipilih tidak cocok dengan bahan baku ini.")
        nama_varian = target.data[0].get("nama_varian") or variant_id

        # Guard 1: minimal harus ada 1 varian yang tersisa.
        all_variants = supabase.table("raw_material_composition_variants") \
            .select("id").eq("raw_material_id", rm_id).execute()
        if len(all_variants.data or []) <= 1:
            response = RedirectResponse(url="/raw-materials", status_code=303)
            response.set_cookie("error_msg", f"Varian '{nama_varian}' tidak bisa dihapus karena ini satu-satunya varian yang tersisa.")
            return response

        # Guard 2: tolak kalau masih dipakai eksplisit di formula produk manapun.
        usage = supabase.table("product_formula_lines") \
            .select("product_id, products(nama_produk)").eq("variant_id", variant_id).execute()
        if usage.data:
            produk_list = []
            for line in usage.data:
                if line.get("products") and line.get("products").get("nama_produk"):
                    produk_list.append(line["products"]["nama_produk"])
            produk_str = ", ".join(produk_list[:3])
            if len(produk_list) > 3:
                produk_str += "..."
            response = RedirectResponse(url="/raw-materials", status_code=303)
            response.set_cookie("error_msg", f"Varian '{nama_varian}' masih dipakai di formula produk: {produk_str}. Pindahkan dulu ke varian lain sebelum menghapus.")
            return response

        # Hapus komponen milik varian ini, lalu variannya.
        supabase.table("raw_material_components").delete().eq("variant_id", variant_id).execute()
        supabase.table("raw_material_composition_variants").delete().eq("id", variant_id).execute()

        # Kalau yang dihapus adalah default, promosikan varian tertua lain jadi default
        # biar invariant "tepat 1 default" tetap terjaga.
        if target.data[0].get("is_default"):
            remaining = supabase.table("raw_material_composition_variants") \
                .select("id").eq("raw_material_id", rm_id).order("created_at").limit(1).execute()
            if remaining.data:
                supabase.table("raw_material_composition_variants") \
                    .update({"is_default": True}).eq("id", remaining.data[0]["id"]).execute()

        log_activity(current_user, "delete", "raw_material_variant", variant_id, nama_varian)
        response = RedirectResponse(url="/raw-materials", status_code=303)
        response.set_cookie("success_msg", f"Varian '{nama_varian}' berhasil dihapus.")
        return response

    @app.post("/raw-materials/batches/add")
    async def add_material_batch(
        request: Request,
        raw_material_id: str = Form(...),
        no_batch: str = Form(...),
        supplier: str = Form(...),
        tanggal_terima_sampel: str = Form(...),
        tanggal_ed: str = Form(...),
        kesimpulan: str = Form(...),
        perusahaan: str = Form(...),
        asal_negara: str = Form(None),
        nama_produsen: str = Form(None),
        tanggal_sampling: str = Form(None),
        qc_signer: str = Form(None),
        qa_signer: str = Form(None),
        qc_results: str = Form("[]"),
        harga_per_kg: float = Form(0.0),
        coa_file: UploadFile = File(None),
        halal_file: UploadFile = File(None),
        qc_report_file: UploadFile = File(None),
        quantity: float = Form(None),
        quantity_unit: str = Form(None),
        keterangan: str = Form(None),
        current_user: dict = Depends(get_current_user)
    ):
        import json

        clean_batch = "".join(c for c in no_batch if c.isalnum() or c in ('-', '_')).strip()

        # 1. Parse string data QC Aktual dari frontend ke Python list
        try:
            parsed_qc = json.loads(qc_results)
        except Exception as e:
            print(f"Gagal parsing qc_results: {e}")
            parsed_qc = []

        coa_url = None
        halal_url = None

        # 2. Proses Upload CoA jika ada filenya
        if coa_file and coa_file.filename:
            try:
                coa_bytes = await coa_file.read()
                coa_path = f"coa/coa_{clean_batch}.pdf"

                supabase.storage.from_("raw-material-docs").upload(
                    path=coa_path,
                    file=coa_bytes,
                    file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                coa_url = supabase.storage.from_("raw-material-docs").get_public_url(coa_path)
                print("--> Sukses upload CoA.")
            except Exception as e:
                print(f"Gagal upload CoA: {e}")

        # 3. Proses Upload Halal Cert jika ada filenya
        if halal_file and halal_file.filename:
            try:
                halal_bytes = await halal_file.read()
                halal_path = f"halal/halal_{clean_batch}.pdf"

                supabase.storage.from_("raw-material-docs").upload(
                    path=halal_path,
                    file=halal_bytes,
                    file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                halal_url = supabase.storage.from_("raw-material-docs").get_public_url(halal_path)
                print("--> Sukses upload Halal.")
            except Exception as e:
                print(f"Gagal upload Halal Cert: {e}")

        # 3b. Proses Upload Laporan Pemeriksaan Aktual (opsional) -- kalau QC punya dokumen
        # fisik/scan hasil pemeriksaan, ini dipake nanti jadi prioritas dibanding versi generate dari qc_results
        qc_report_url = None
        if qc_report_file and qc_report_file.filename:
            try:
                qc_report_bytes = await qc_report_file.read()
                qc_report_path = f"qc-reports/qcreport_{clean_batch}.pdf"

                supabase.storage.from_("raw-material-docs").upload(
                    path=qc_report_path,
                    file=qc_report_bytes,
                    file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                qc_report_url = supabase.storage.from_("raw-material-docs").get_public_url(qc_report_path)
                print("--> Sukses upload Laporan Pemeriksaan Aktual.")
            except Exception as e:
                print(f"Gagal upload Laporan Pemeriksaan Aktual: {e}")

        # 4. Simpan record data lengkap ke tabel raw_material_batches
        batch_data = {
            "raw_material_id": raw_material_id,
            "perusahaan": perusahaan,
            "no_batch": no_batch.strip(),
            "supplier": supplier.strip(),
            "asal_negara": asal_negara.strip() if asal_negara else None,
            "nama_produsen": nama_produsen.strip() if nama_produsen else None,
            "harga_per_kg": harga_per_kg,
            "tanggal_terima_sampel": tanggal_terima_sampel,
            "tanggal_sampling": tanggal_sampling if tanggal_sampling else None,
            "tanggal_ed": tanggal_ed,
            "kesimpulan": kesimpulan,
            "keterangan": keterangan.strip() if keterangan else None,
            "qc_signer": qc_signer.strip() if qc_signer else None,
            "qa_signer": qa_signer.strip() if qa_signer else None,
            "hasil_pemerian": "-",
            "quantity": quantity,
            "quantity_unit": quantity_unit,
            "coa_file_url": coa_url,
            "halal_batch_file_url": halal_url,
            "qc_report_file_url": qc_report_url
        }

        try:
            supabase.table("raw_material_batches").insert(batch_data).execute()
            print("--> Data Batch berhasil masuk ke Database!")
        except Exception as e:
            print(f"Gagal insert ke DB: {e}")

        # Redirect balik ke halaman utama bahan baku
        return RedirectResponse(url="/raw-materials", status_code=303)

    @app.post("/raw-materials/batches/edit/{batch_id}")
    async def edit_material_batch(
        batch_id: str,
        no_batch: str = Form(...),
        supplier: str = Form(...),
        tanggal_terima_sampel: str = Form(...),
        tanggal_ed: str = Form(...),
        kesimpulan: str = Form(...),
        asal_negara: str = Form(None),
        nama_produsen: str = Form(None),
        coa_file: UploadFile = File(None),
        halal_file: UploadFile = File(None),
        qc_report_file: UploadFile = File(None),
        quantity: float = Form(None),
        quantity_unit: str = Form(None),
        keterangan: str = Form(None),
        current_user: dict = Depends(get_current_user)
    ):
        # 1. Ambil data lama untuk handle file upload
        old_batch = supabase.table("raw_material_batches").select("*").eq("id", batch_id).single().execute().data

        clean_batch = "".join(c for c in no_batch if c.isalnum() or c in ('-', '_')).strip()

        update_data = {
            "no_batch": no_batch.strip(),
            "supplier": supplier.strip(),
            "tanggal_terima_sampel": tanggal_terima_sampel,
            "tanggal_ed": tanggal_ed,
            "kesimpulan": kesimpulan,
            "asal_negara": asal_negara.strip() if asal_negara else None,
            "quantity": quantity,
            "quantity_unit": quantity_unit,
            "keterangan": keterangan.strip() if keterangan else None
        }

        # 2. Update Files if provided
        if coa_file and coa_file.filename:
            try:
                coa_bytes = await coa_file.read()
                coa_path = f"coa/coa_{clean_batch}.pdf"
                supabase.storage.from_("raw-material-docs").upload(
                    path=coa_path, file=coa_bytes, file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                update_data["coa_file_url"] = supabase.storage.from_("raw-material-docs").get_public_url(coa_path)
            except Exception as e:
                print(f"Gagal update CoA: {e}")

        if halal_file and halal_file.filename:
            try:
                halal_bytes = await halal_file.read()
                halal_path = f"halal/halal_{clean_batch}.pdf"
                supabase.storage.from_("raw-material-docs").upload(
                    path=halal_path, file=halal_bytes, file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                update_data["halal_batch_file_url"] = supabase.storage.from_("raw-material-docs").get_public_url(halal_path)
            except Exception as e:
                print(f"Gagal update Halal: {e}")

        if qc_report_file and qc_report_file.filename:
            try:
                qc_report_bytes = await qc_report_file.read()
                qc_report_path = f"qc-reports/qcreport_{clean_batch}.pdf"
                supabase.storage.from_("raw-material-docs").upload(
                    path=qc_report_path, file=qc_report_bytes, file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                update_data["qc_report_file_url"] = supabase.storage.from_("raw-material-docs").get_public_url(qc_report_path)
            except Exception as e:
                print(f"Gagal update QC Report: {e}")

        try:
            supabase.table("raw_material_batches").update(update_data).eq("id", batch_id).execute()
            log_activity(current_user, "edit", "raw_material_batch", batch_id, f"Update batch {no_batch}")
        except Exception as e:
            print(f"Gagal update batch: {e}")

        return RedirectResponse(url="/raw-materials?tab=batch-tab", status_code=303)

    @app.post("/raw-materials/batches/{batch_id}/quick-upload-doc")
    async def quick_upload_batch_doc(
        batch_id: str,
        coa_file: UploadFile = File(None),
        halal_file: UploadFile = File(None),
        qc_report_file: UploadFile = File(None),
        current_user: dict = Depends(get_current_user)
    ):
        # Route ini CUMA nyentuh kolom file URL, tidak menyentuh field lain
        # (no_batch, supplier, tanggal, kesimpulan, dll) di baris batch tersebut.
        batch_resp = supabase.table("raw_material_batches").select(
            "no_batch, raw_materials(nama_dagang)"
        ).eq("id", batch_id).single().execute()
        if not batch_resp.data:
            response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
            response.set_cookie("error_msg", "Batch tidak ditemukan.")
            return response

        no_batch = batch_resp.data["no_batch"]
        raw_material = batch_resp.data.get("raw_materials")
        if isinstance(raw_material, list):
            raw_material = raw_material[0] if raw_material else None
        nama_bahan_baku = raw_material.get("nama_dagang") if isinstance(raw_material, dict) else None
        nama_bahan_baku = nama_bahan_baku or "Tanpa Master"
        clean_batch = "".join(c for c in no_batch if c.isalnum() or c in ("-", "_")).strip()

        update_data = {}
        uploaded_documents = []

        if coa_file and coa_file.filename:
            try:
                coa_bytes = await coa_file.read()
                coa_path = f"coa/coa_{clean_batch}.pdf"
                supabase.storage.from_("raw-material-docs").upload(
                    path=coa_path, file=coa_bytes, file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                update_data["coa_file_url"] = supabase.storage.from_("raw-material-docs").get_public_url(coa_path)
                uploaded_documents.append("CoA")
            except Exception as e:
                print(f"Gagal quick-upload CoA: {e}")

        if halal_file and halal_file.filename:
            try:
                halal_bytes = await halal_file.read()
                halal_path = f"halal/halal_{clean_batch}.pdf"
                supabase.storage.from_("raw-material-docs").upload(
                    path=halal_path, file=halal_bytes, file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                update_data["halal_batch_file_url"] = supabase.storage.from_("raw-material-docs").get_public_url(halal_path)
                uploaded_documents.append("Halal")
            except Exception as e:
                print(f"Gagal quick-upload Halal: {e}")

        if qc_report_file and qc_report_file.filename:
            try:
                qc_report_bytes = await qc_report_file.read()
                qc_report_path = f"qc-reports/qcreport_{clean_batch}.pdf"
                supabase.storage.from_("raw-material-docs").upload(
                    path=qc_report_path, file=qc_report_bytes, file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                update_data["qc_report_file_url"] = supabase.storage.from_("raw-material-docs").get_public_url(qc_report_path)
                uploaded_documents.append("Catatan Pemeriksaan Bahan Baku")
            except Exception as e:
                print(f"Gagal quick-upload QC Report: {e}")

        if update_data:
            try:
                supabase.table("raw_material_batches").update(update_data).eq("id", batch_id).execute()
                document_list = ", ".join(uploaded_documents)
                log_activity(
                    current_user, "edit", "raw_material_batch", batch_id,
                    f"Upload cepat {document_list} untuk bahan baku {nama_bahan_baku} — batch {no_batch}"
                )
                response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
                response.set_cookie("success_msg", "Dokumen berhasil diupload.")
            except Exception as e:
                print(f"Gagal simpan quick-upload batch doc: {e}")
                response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
                response.set_cookie("error_msg", "Gagal upload dokumen. Coba lagi.")
        else:
            response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
            response.set_cookie("error_msg", "Tidak ada file yang dipilih.")
        return response

    # ==================== ED MANAGEMENT ENDPOINTS ====================
    @app.post("/raw-materials/batches/acc-dipakai")
    async def acc_dipakai_batch(
        request: Request,
        batch_id: str = Form(...),
        new_expiry_date: str = Form(...),
        new_status_ed: str = Form("ACC Dipakai"),
        catatan_qc: str = Form(...),
        current_user: dict = Depends(get_current_user)
    ):
        """ACC Dipakai - Perpanjang ED (Retest Passed)"""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        WIB = ZoneInfo("Asia/Jakarta")
        now = datetime.now(WIB)

        try:
            # Update batch with new ED, status, and QC notes
            update_data = {
                "tanggal_ed": new_expiry_date,
                "status_ed": new_status_ed,
                "catatan_qc": catatan_qc,
                "tanggal_acc_qc": now.isoformat()
            }

            supabase.table("raw_material_batches").update(update_data).eq("id", batch_id).execute()

            log_activity(current_user, "acc_dipakai", "raw_material_batch", batch_id, f"ED diperpanjang ke {new_expiry_date}")

            response = RedirectResponse(url="/raw-materials?tab=ed-tab", status_code=303)
            response.set_cookie("success_msg", f"ACC Dipakai berhasil disimpan. ED baru: {new_expiry_date}")
            return response

        except Exception as e:
            print(f"Gagal ACC Dipakai: {e}")
            response = RedirectResponse(url="/raw-materials?tab=ed-tab", status_code=303)
            response.set_cookie("error_msg", f"Gagal menyimpan ACC Dipakai: {str(e)}")
            return response

    @app.post("/raw-materials/batches/acc-dimusnahkan")
    async def acc_dimusnahkan_batch(
        request: Request,
        batch_id: str = Form(...),
        catatan_qc: str = Form(...),
        current_user: dict = Depends(get_current_user)
    ):
        """ACC Dimusnahkan - Dispose batch"""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        WIB = ZoneInfo("Asia/Jakarta")
        now = datetime.now(WIB)

        try:
            # Update batch: status = Dimusnahkan, stok = 0, save QC notes and timestamp
            update_data = {
                "status_ed": "Dimusnahkan",
                "catatan_qc": catatan_qc,
                "tanggal_acc_qc": now.isoformat(),
                # Note: If there's a quantity/stock column, set it to 0
                # "qty": 0  # Uncomment if you have a qty column
            }

            supabase.table("raw_material_batches").update(update_data).eq("id", batch_id).execute()

            log_activity(current_user, "acc_dimusnahkan", "raw_material_batch", batch_id, "Batch dimusnahkan (dispose)")

            response = RedirectResponse(url="/raw-materials?tab=ed-tab", status_code=303)
            response.set_cookie("success_msg", "Batch berhasil dimusnahkan (ACC Dimusnahkan).")
            return response

        except Exception as e:
            print(f"Gagal ACC Dimusnahkan: {e}")
            response = RedirectResponse(url="/raw-materials?tab=ed-tab", status_code=303)
            response.set_cookie("error_msg", f"Gagal memusnahkan batch: {str(e)}")
            return response
