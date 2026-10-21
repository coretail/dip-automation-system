"""Product, formula, finished-spec, and qualitative-quantitative routes (extracted from main.py)."""
from __future__ import annotations

import io
import json
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from app.efek_samping import _efek_samping_meta
from app.excel_generator import XLSX_MIME, build_formula_workbook
from app import object_store
from app.file_validation import validate_pdf_bytes
from app.product_attachments_routes import LAMPIRAN_CATEGORIES
from xhtml2pdf import pisa

WIB = ZoneInfo("Asia/Jakarta")


def register_products_routes(
    app,
    get_current_user,
    supabase,
    templates,
    log_activity,
    compute_status_na,
    get_company_info,
    format_date_id,
    get_ed_notification_count,
    COMPANY_INFO,
    slugify,
    _resolve_variant_components,
    _flag_bahan_aktif,
    _build_diff_changes,
    _logo_render_width,
    _pdf_link_callback,
):

    @app.post("/products/add")
    async def add_product(
        request: Request,
        nama_produk: str = Form(...),
        perusahaan: str = Form(...),
        nama_customer: str = Form(None),
        sediaan: str = Form(None),
        warna: str = Form(None),
        kemasan: str = Form(None),
        netto: str = Form(None),
        no_na_produk: str = Form(None),
        status_na: str = Form("belum_terdaftar"),
        tanggal_aktif_na: str = Form(None),
        acc_sampel: str = Form(None),
        tanggal_text_design: str = Form(None),
        teks_marketing: str = Form(None),
        cara_pakai: str = Form(None),
        peringatan: str = Form(None),
        penyimpanan: str = Form(None),
        brand_id: str = Form(None),
        current_user: dict = Depends(get_current_user)
    ):
        # Bersihkan input tanggal kosong menjadi None agar Supabase tidak error
        acc_sampel_val = acc_sampel.strip() if acc_sampel else None
        if acc_sampel_val == "":
            acc_sampel_val = None

        tgl_aktif_na_val = tanggal_aktif_na.strip() if tanggal_aktif_na else None
        if tgl_aktif_na_val == "":
            tgl_aktif_na_val = None

        product_data = {
            "nama_produk": nama_produk,
            "perusahaan": perusahaan,
            "nama_customer": nama_customer,
            "sediaan": sediaan,
            "warna": warna,
            "kemasan": kemasan,
            "netto": netto,
            "no_na_produk": no_na_produk,
            "status_na": status_na,
            "tanggal_aktif_na": tgl_aktif_na_val,
            "acc_sampel": acc_sampel_val,
            "tanggal_text_design": tanggal_text_design or None,
            "teks_marketing": teks_marketing,
            "cara_pakai": cara_pakai,
            "peringatan": peringatan,
            "penyimpanan": penyimpanan,
            "brand_id": brand_id if brand_id else None,
            # Capability token terpisah dari UUID (opsional sampai migration 007 diterapkan)
            "public_access_enabled": True,
            "public_access_token": __import__("secrets").token_urlsafe(32),
            "bpom_registered_link": False,
        }

        try:
            try:
                new_product_resp = supabase.table("products").insert(product_data).execute()
            except Exception:
                # Fallback bila kolom capability belum ada di database
                for _k in ("public_access_enabled", "public_access_token", "bpom_registered_link", "public_access_revoked_at"):
                    product_data.pop(_k, None)
                new_product_resp = supabase.table("products").insert(product_data).execute()
            new_product_id = new_product_resp.data[0]["id"] if new_product_resp.data else None
            if not new_product_id:
                raise Exception("Insert produk tidak mengembalikan data")
            log_activity(current_user, "create", "product", new_product_id, nama_produk,
                         request=request)
            return RedirectResponse(url="/", status_code=303)
        except Exception as e:
            print(f"\n🔴 [ERROR add_product] Gagal menyimpan produk '{nama_produk}': {e}")
            # Redirect balik ke halaman dashboard dengan pesan error, supaya user tahu harus input ulang
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie("error_msg", f"Gagal menyimpan produk '{nama_produk}'. Silakan coba lagi.")
            return response

    @app.post("/products/delete/{product_id}")
    async def delete_product(request: Request, product_id: str,
                             current_user: dict = Depends(get_current_user)):
        # Hanya admin yang boleh menghapus (soft delete) produk.
        if current_user.get("role") != "admin":
            log_activity(
                current_user, "delete", "product", product_id, product_id,
                changes=[{"field": "is_deleted", "note": "ditolak: bukan admin"}],
                request=request, outcome="rejected",
            )
            raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Admin.")

        # Ambil data produk dulu: perlu nama (biar activity log terbaca, bukan id doang)
        # dan perlu tahu produknya sudah ada di Sampah atau belum.
        try:
            product_before = supabase.table("products").select(
                "id, nama_produk, is_deleted, deleted_at"
            ).eq("id", product_id).execute()
        except Exception as e:
            print(f"Gagal baca produk {product_id} saat hapus: {e}")
            log_activity(
                current_user, "delete", "product", product_id, product_id,
                changes=[{"field": "is_deleted", "note": "gagal membaca data produk"}],
                request=request, outcome="failed",
            )
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie("error_msg", "Gagal memuat produk. Silakan coba lagi.")
            return response

        product_row = (product_before.data or [None])[0]
        if not product_row:
            log_activity(
                current_user, "delete", "product", product_id, product_id,
                changes=[{"field": "is_deleted", "note": "ditolak: produk tidak ditemukan"}],
                request=request, outcome="rejected",
            )
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie("error_msg", "Produk tidak ditemukan.")
            return response

        nama_produk = product_row.get("nama_produk") or product_id
        if product_row.get("is_deleted"):
            # Sudah ada di Sampah -> jangan timpa deleted_at lama dan jangan buat
            # baris audit "delete sukses" kedua untuk produk yang sama.
            log_activity(
                current_user, "delete", "product", product_id, nama_produk,
                changes=[{"field": "is_deleted", "note": "ditolak: produk sudah ada di Sampah"}],
                request=request, outcome="rejected",
            )
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie("error_msg", "Produk sudah ada di Sampah.")
            return response

        try:
            # Soft Delete: cuma tandai is_deleted=True + deleted_at, JANGAN hapus formula.
            # Guard is_deleted=False mencegah produk yang sudah di sampah (atau di-restore
            # berbarengan) ikut tertimpa, sehingga deleted_at tidak dobel dan tidak ada
            # baris audit "delete sukses" yang palsu.
            deleted_at = datetime.now(WIB).isoformat()
            update_resp = (
                supabase.table("products")
                .update({"is_deleted": True, "deleted_at": deleted_at})
                .eq("id", product_id)
                .eq("is_deleted", False)
                .execute()
            )
        except Exception as e:
            print(f"Gagal hapus produk {product_id}: {e}")
            log_activity(
                current_user, "delete", "product", product_id, nama_produk,
                changes=[{"field": "is_deleted", "note": "gagal memindahkan ke Sampah"}],
                request=request, outcome="failed",
            )
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie("error_msg", "Gagal memindahkan produk ke Sampah. Silakan coba lagi.")
            return response

        # Guard 0 baris ter-update: status produk berubah di antara SELECT dan UPDATE.
        if not (getattr(update_resp, "data", None) or []):
            log_activity(
                current_user, "delete", "product", product_id, nama_produk,
                changes=[{"field": "is_deleted", "note": "ditolak: status produk berubah sebelum update"}],
                request=request, outcome="rejected",
            )
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie("error_msg", "Produk sudah ada di Sampah.")
            return response

        log_activity(
            current_user, "delete", "product", product_id, nama_produk,
            changes=[{"field": "is_deleted", "note": "dipindahkan ke sampah"}],
            request=request, outcome="success",
        )
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie("success_msg", f"Produk '{nama_produk}' dipindahkan ke Sampah.")
        return response

    @app.get("/products/{product_id}/inci-breakdown/report", response_class=HTMLResponse)
    async def generate_inci_report(request: Request, product_id: str, current_user: dict = Depends(get_current_user)):
        try:
            prod_resp = supabase.table("products").select("*").eq("id", product_id).eq("is_deleted", False).single().execute()
        except Exception as e:
            # .single() melempar APIError kalau produk gak ketemu (URL rusak / produk terhapus) -> jangan 500
            print(f"Produk {product_id} tidak ditemukan, redirect ke dashboard: {e}")
            return RedirectResponse(url="/", status_code=303)

        if not prod_resp.data:
            return RedirectResponse(url="/", status_code=303)

        formula_resp = (
            supabase.table("product_formula_lines")
            .select(
                "percent_in_formula, variant_id, "
                "raw_materials(*, raw_material_components(*), "
                "raw_material_composition_variants(*, raw_material_components(*)))"
            )
            .eq("product_id", product_id)
            .execute()
        )

        inci_totals = {}

        if formula_resp.data:
            for line in formula_resp.data:
                pct_in_formula = float(line.get("percent_in_formula") or 0)

                # Resolusi varian terpusat: variant_id eksplisit dari baris formula,
                # fallback ke varian default lewat _resolve_variant_components.
                # (Sekalian menghilangkan N+1 query per baris formula.)
                components = _resolve_variant_components(
                    line.get("raw_materials"), line.get("variant_id")
                )

                if components:
                    for comp in components:
                        inci_name = comp.get("inci_name")
                        cas_number = comp.get("cas_number") or "-"
                        func = comp.get("function") or "-"
                        percent_internal = float(comp.get("percent_internal") or 100)

                        # Hitung absolute persen
                        absolute_pct = (pct_in_formula * percent_internal) / 100.0

                        if inci_name:
                            if inci_name in inci_totals:
                                inci_totals[inci_name]["total_percentage"] += absolute_pct
                            else:
                                inci_totals[inci_name] = {
                                    "inci_name": inci_name,
                                    "cas_number": cas_number,
                                    "function": func,
                                    "total_percentage": absolute_pct
                                }

        # KUNCI PERBAIKAN: Hilangkan nol gak kepake di hasil akhir total_percentage
        for key in inci_totals:
            raw_val = inci_totals[key]["total_percentage"]
            # Ubah ke string float dulu, konversi ke Decimal, lalu normalize
            inci_totals[key]["total_percentage"] = float(Decimal(str(raw_val)).normalize())

        sorted_inci = sorted(
            inci_totals.values(), 
            key=lambda x: x["total_percentage"], 
            reverse=True
        )

        return templates.TemplateResponse(
            request=request,
            name="ingredient_report.html",
            context={
                "current_user": current_user,
                "product": prod_resp.data,
                "inci_list": sorted_inci
            }
        )

    async def _gather_qualquant_data(product_id: str) -> dict:
        """Kumpulkan produk + breakdown formula Qual-Quan utk satu produk.

        Single source of truth yang dipakai bareng oleh:
          - route preview HTML  : /products/{id}/qualitative-quantitative
          - route export Excel  : /products/{id}/qualitative-quantitative/export-xlsx
        """
        product_resp = supabase.table("products").select("*").eq("id", product_id).eq("is_deleted", False).single().execute()
        product = product_resp.data

        lines_resp = supabase.table("product_formula_lines") \
            .select(
                "*, raw_materials(*, raw_material_components(*), "
                "raw_material_composition_variants(*, raw_material_components(*)))"
            ) \
            .eq("product_id", product_id) \
            .execute()

        grouped_trade = {}

        for line in lines_resp.data:
            raw_mat = line.get("raw_materials")

            if isinstance(raw_mat, list) and len(raw_mat) > 0:
                raw_mat = raw_mat[0]

            if isinstance(raw_mat, dict):
                nama_dagang = raw_mat.get("nama_dagang")
                kode_bahan_baku = raw_mat.get("kode_bahan_baku") or raw_mat.get("kode")
            else:
                nama_dagang = "Unknown"
                kode_bahan_baku = "-"

            if isinstance(nama_dagang, dict):
                nama_dagang = next(iter(nama_dagang.values()), "Unknown")
            if isinstance(kode_bahan_baku, dict):
                kode_bahan_baku = next(iter(kode_bahan_baku.values()), "-")

            nama_dagang_str = str(nama_dagang or "Unknown")
            kode_bahan_baku_str = str(kode_bahan_baku or "-")

            line_pct = float(line.get("percent_in_formula") or 0.0)

            # Resolusi varian terpusat: variant_id eksplisit dari baris formula,
            # fallback ke varian default lewat _resolve_variant_components.
            components = _resolve_variant_components(raw_mat, line.get("variant_id"))

            group_key = (nama_dagang_str, kode_bahan_baku_str)
            if group_key not in grouped_trade:
                grouped_trade[group_key] = []

            if components:
                for comp in components:
                    comp_share = float(comp.get("percent_internal") or comp.get("percentage") or 0.0)
                    real_pct = (comp_share * line_pct) / 100.0

                    # KUNCI PERBAIKAN 1: Murni hilangkan trailing zeros
                    clean_pct = float(Decimal(str(real_pct)).normalize())

                    grouped_trade[group_key].append({
                        "inci_name": comp.get("inci_name") or "Unknown",
                        "cas_number": comp.get("cas_number") or "-",
                        "function": comp.get("function") or "-",
                        "pct_ww": clean_pct,
                        "is_bahan_aktif": bool(comp.get("is_bahan_aktif")),
                    })
            else:
                clean_line_pct = float(Decimal(str(line_pct)).normalize())
                grouped_trade[group_key].append({
                    "inci_name": nama_dagang_str,
                    "cas_number": "-",
                    "function": "-",
                    "pct_ww": clean_line_pct,
                    "is_bahan_aktif": False,
                })

        trade_breakdown = []
        for (n_dagang, k_baku), components in grouped_trade.items():
            trade_breakdown.append({
                "nama_dagang": n_dagang,
                "kode_bahan_baku": k_baku,
                "rowspan": len(components),
                "components": components
            })

        # ==================== LOGIC DOKUMEN 2 (MURNI INCI TOTAL) ====================
        grouped_pure = {}
        for group in trade_breakdown:
            for comp in group["components"]:
                inci_name_raw = (comp["inci_name"] or "").strip()
                # Normalisasi key: hapus spasi berlebih & samakan besar-kecil huruf,
                inci_key = inci_name_raw.lower()
                if inci_key not in grouped_pure:
                    grouped_pure[inci_key] = {
                        "inci_name": inci_name_raw,
                        "cas_number": comp.get("cas_number") or "-",
                        "function": comp["function"],
                        # Gunakan Decimal('0.0') sebagai inisialisasi awal agar presisi
                        "pct_ww_decimal": Decimal('0.0'),
                        "is_bahan_aktif": False,
                    }
                if comp.get("is_bahan_aktif"):
                    grouped_pure[inci_key]["is_bahan_aktif"] = True
                if (grouped_pure[inci_key].get("cas_number") in (None, "", "-")
                        and comp.get("cas_number") not in (None, "", "-")):
                    grouped_pure[inci_key]["cas_number"] = comp["cas_number"]
                # Jumlahkan dengan tipe data Decimal murni
                grouped_pure[inci_key]["pct_ww_decimal"] += Decimal(str(comp["pct_ww"]))

        # KUNCI PERBAIKAN: Konversi hasil akhir ke float yang bersih setelah selesai dijumlahkan
        pure_breakdown = []
        for item in grouped_pure.values():
            clean_sum = float(item["pct_ww_decimal"].normalize())
            pure_breakdown.append({
                "inci_name": item["inci_name"],
                "cas_number": item.get("cas_number") or "-",
                "function": item["function"],
                "pct_ww": clean_sum,
                "is_bahan_aktif": bool(item.get("is_bahan_aktif")),
            })
        pure_breakdown.sort(key=lambda x: (-x["pct_ww"], (x["inci_name"] or "").casefold()))

        clean_product = {}
        if isinstance(product, list) and len(product) > 0:
            clean_product = product[0]
        elif isinstance(product, dict):
            clean_product = product

        final_product = {str(k): (str(v) if v is not None else "") for k, v in clean_product.items()}

        # Ambil data kop surat sesuai perusahaan produk ini, fallback ke PT Erfi kalau kosong/tidak dikenali
        company = COMPANY_INFO.get(final_product.get("perusahaan"), COMPANY_INFO["PT Erfi"])

        return {
            "product": final_product,
            "trade_breakdown": trade_breakdown,
            "pure_breakdown": pure_breakdown,
            "company": company
        }


    @app.get("/products/{product_id}/qualitative-quantitative", response_class=HTMLResponse)
    async def qualitative_quantitative_report(request: Request, product_id: str, current_user: dict = Depends(get_current_user)):
        data = await _gather_qualquant_data(product_id)
        return templates.TemplateResponse(
            request=request,
            name="qualitative_quantitative.html",
            context={
                "product": data["product"],
                "current_user": current_user,
                "trade_breakdown": data["trade_breakdown"],
                "pure_breakdown": data["pure_breakdown"],
                "company": data["company"]
            }
        )


    @app.get("/products/{product_id}/qualitative-quantitative/export-xlsx")
    async def export_qualquant_xlsx(request: Request, product_id: str,
                                    current_user: dict = Depends(get_current_user)):
        """Export dokumen Formula Kualitatif & Kuantitatif (.xlsx) via openpyxl.

        Menghasilkan workbook 3 sheet ("Formula Nama Dagang", "Formula INCI Murni",
        "Text Design") dengan styling profesional -- lihat app/excel_generator.py.
        """
        data = await _gather_qualquant_data(product_id)

        content = build_formula_workbook(
            product=data["product"],
            trade_breakdown=data["trade_breakdown"],
            pure_breakdown=data["pure_breakdown"],
            company=data["company"],
        )

        safe_name = slugify(data["product"].get("nama_produk") or "produk").replace("-", "_")
        filename = f"Qual_Quan_Formula_{safe_name}.xlsx"

        log_activity(current_user, "export", "product_qualquan_xlsx", product_id,
                     filename, request=request)

        return StreamingResponse(
            io.BytesIO(content),
            media_type=XLSX_MIME,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )


    def _apply_company_specific_docs(rm: dict, perusahaan: str) -> dict:
        """Timpa spec_parameters & msds_file_url pada dict raw_material dengan data
        yang company-specific dari raw_material_company_docs (kalau ada). Kalau data
        buat perusahaan ini belum diisi, dikosongin (bukan fallback ke company lain) --
        biar dokumen legal gak salah nampilin data company yang bukan pemiliknya."""
        doc_resp = supabase.table("raw_material_company_docs") \
            .select("spec_parameters, msds_file_url, spec_sheet_file_url") \
            .eq("raw_material_id", rm["id"]) \
            .eq("perusahaan", perusahaan) \
            .limit(1) \
            .execute()
        company_doc = doc_resp.data[0] if doc_resp.data else None
        rm["spec_parameters"] = (company_doc or {}).get("spec_parameters") or []
        rm["msds_file_url"] = (company_doc or {}).get("msds_file_url")
        rm["spec_sheet_file_url"] = (company_doc or {}).get("spec_sheet_file_url")
        return rm





    @app.get("/products/{product_id}/finished-spec", response_class=HTMLResponse)
    async def finished_spec_page(request: Request, product_id: str, current_user: dict = Depends(get_current_user)):
        try:
            product_res = supabase.table("products").select("*").eq("id", product_id).eq("is_deleted", False).single().execute()
        except Exception as e:
            # .single() melempar APIError kalau produk gak ketemu (URL rusak / produk terhapus) -> jangan 500
            print(f"Produk {product_id} tidak ditemukan, redirect ke dashboard: {e}")
            return RedirectResponse(url="/", status_code=303)

        if not product_res.data:
            return RedirectResponse(url="/", status_code=303)

        product = product_res.data

        if product["perusahaan"] != "PT Erfi":
            response = RedirectResponse(url=f"/products/{product_id}/edit", status_code=303)
            response.set_cookie("error_msg", "Fitur spesifikasi produk jadi hanya tersedia untuk PT Erfi.")
            return response

        spec_res = supabase.table("product_finished_specs").select("*").eq("product_id", product_id).execute()
        spec = spec_res.data[0] if spec_res.data else None

        # Get success/error messages from cookies
        success_msg = request.cookies.get("success_msg")
        error_msg = request.cookies.get("error_msg")

        response = templates.TemplateResponse(
            request=request,
            name="finished_spec_form.html",
            context={
                "product": product,
                "spec": spec,
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


    @app.post("/products/{product_id}/finished-spec")
    async def save_finished_spec(
        request: Request,
        product_id: str,
        kode_produk: Optional[str] = Form(None),
        disetujui_oleh: Optional[str] = Form(None),
        tanggal_disetujui: Optional[str] = Form(None),
        kota_persetujuan: str = Form("Bogor"),
        sections_json: str = Form(...),
        current_user: dict = Depends(get_current_user)
    ):
        product_res = supabase.table("products").select("nama_produk").eq("id", product_id).eq("is_deleted", False).single().execute()
        if not product_res.data:
            raise HTTPException(status_code=404, detail="Product not found")
        product = product_res.data

        try:
            sections_data = json.loads(sections_json)
        except json.JSONDecodeError:
            response = RedirectResponse(url=f"/products/{product_id}/finished-spec", status_code=303)
            response.set_cookie("error_msg", "Format data sections tidak valid. Pastikan format JSON benar.")
            return response

        tgl_disetujui_val = tanggal_disetujui.strip() if tanggal_disetujui else None
        if tgl_disetujui_val == "":
            tgl_disetujui_val = None

        spec_data = {
            "product_id": product_id,
            "kode_produk": kode_produk,
            "sections": sections_data,
            "disetujui_oleh": disetujui_oleh,
            "tanggal_disetujui": tgl_disetujui_val,
            "kota_persetujuan": kota_persetujuan,
        }

        existing_spec = supabase.table("product_finished_specs").select("id").eq("product_id", product_id).execute()

        if existing_spec.data:
            supabase.table("product_finished_specs").update(spec_data).eq("product_id", product_id).execute()
            success_msg = "Spesifikasi Produk Jadi berhasil diperbarui."
        else:
            supabase.table("product_finished_specs").insert(spec_data).execute()
            success_msg = "Spesifikasi Produk Jadi berhasil disimpan."

        log_activity(current_user, "update", "product_finished_specs", product_id,
                     f"Spesifikasi Produk Jadi - {product['nama_produk']}",
                     request=request)

        response = RedirectResponse(url=f"/products/{product_id}/finished-spec", status_code=303)
        response.set_cookie("success_msg", success_msg)
        return response


    @app.get("/products/{product_id}/finished-spec/download")
    async def download_finished_spec(product_id: str, current_user: dict = Depends(get_current_user)):
        try:
            product_res = supabase.table("products").select("nama_produk, perusahaan").eq("id", product_id).eq("is_deleted", False).single().execute()
        except Exception as e:
            # .single() melempar APIError kalau produk gak ketemu (URL rusak / produk terhapus) -> jangan 500
            print(f"Produk {product_id} tidak ditemukan, redirect ke dashboard: {e}")
            return RedirectResponse(url="/", status_code=303)

        if not product_res.data:
            return RedirectResponse(url="/", status_code=303)

        product = product_res.data

        if product["perusahaan"] != "PT Erfi":
            raise HTTPException(status_code=403, detail="Fitur ini hanya untuk produk PT Erfi.")

        spec_res = supabase.table("product_finished_specs").select("*").eq("product_id", product_id).execute()
        if not spec_res.data:
            # Redirect ke edit page jika belum diisi, biar user tau harus ngapain
            response = RedirectResponse(url=f"/products/{product_id}/edit?tab=bab3", status_code=303)
            response.set_cookie("error_msg", "Spesifikasi produk jadi belum diisi, silakan isi form terlebih dahulu.")
            return response
        spec = spec_res.data[0]

        # Grouping logic for "Metode" column merging
        for section in spec.get("sections", []):
            rows = section.get("rows", [])
            if not rows: continue

            grouped_rows = []
            i = 0
            while i < len(rows):
                current_row = rows[i]
                metode = current_row.get("metode", "")

                # Find how many subsequent rows have the same metode
                rowspan = 1
                j = i + 1
                while j < len(rows) and rows[j].get("metode") == metode and metode != "" and metode != "-":
                    rowspan += 1
                    j += 1

                # Add info to the first row of the group
                current_row["rowspan"] = rowspan
                grouped_rows.append(current_row)

                # Add subsequent rows but mark them to be skipped in template for the "Metode" cell
                for k in range(i + 1, j):
                    rows[k]["skip_metode"] = True
                    grouped_rows.append(rows[k])

                i = j
            section["rows"] = grouped_rows

        company = get_company_info(product["perusahaan"])
        company["logo_width"] = _logo_render_width(company["logo"])

        tanggal_disetujui_formatted = format_date_id(spec["tanggal_disetujui"]) if spec["tanggal_disetujui"] else "-"

        context = {
            "product": product,
            "spec": spec,
            "company": company,
            "tanggal_disetujui_formatted": tanggal_disetujui_formatted,
        }

        template = templates.env.get_template("finished_spec_pdf.html")
        html_out = template.render(context)

        pdf = pisa.CreatePDF(
            io.BytesIO(html_out.encode("UTF-8")),
            link_callback=_pdf_link_callback,
            encoding="UTF-8"
        )
        if pdf.err:
            raise HTTPException(status_code=500, detail="Gagal membuat PDF.")

        filename = f"Spesifikasi_Produk_Jadi_{slugify(product['nama_produk'])}.pdf"

        return StreamingResponse(io.BytesIO(pdf.dest.getvalue()), media_type="application/pdf", headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\""
        })


    @app.get("/products/{product_id}/finished-spec/preview")
    async def preview_finished_spec(product_id: str, current_user: dict = Depends(get_current_user)):
        try:
            resp = await download_finished_spec(product_id, current_user)
            if isinstance(resp, RedirectResponse):
                return resp
            if "Content-Disposition" in resp.headers:
                resp.headers["Content-Disposition"] = resp.headers["Content-Disposition"].replace("attachment", "inline")
            return resp
        except HTTPException as e:
            if e.status_code == 400:
                response = RedirectResponse(url=f"/products/{product_id}/edit?tab=bab3", status_code=303)
                response.set_cookie("error_msg", e.detail)
                return response
            raise e


    # =====================================================================
    #  PUBLIC LINK BPOM - PERMALINK UNTUK VERIFIKATOR BPOM
    #  Route /dip/[slug-nama-produk]-[id] bersifat PUBLIK (tanpa login) & permanen
    #  (tidak ada masa expired) supaya bisa dilampirkan ke portal
    #  e-registration BPOM dan tetap hidup bertahun-tahun.
    #
    #  Seluruh route /dip/* (hub, Bab I-IV, dan ZIP Bab II) sudah dipindah ke
    #  app/dip_public.py dan didaftarkan di bagian bawah file ini lewat
    #  register_dip_public_routes(...). _parse_storage_url tetap di sini karena
    #  juga dipakai app/raw_materials_routes.py.
    # =====================================================================
    def _parse_storage_url(url: str):
        """Ekstrak (bucket, path) dari public URL storage (Supabase ATAU R2).

        Contoh Supabase:
          https://xxxx.supabase.co/storage/v1/object/public/raw-material-docs/products/123/a.pdf
          -> ('raw-material-docs', 'products/123/a.pdf')
        Contoh R2 (base publik per bucket dari R2_PUBLIC_BASES):
          https://pub-xxx.r2.dev/products/123/a.pdf -> ('raw-material-docs', 'products/123/a.pdf')
        Kalau formatnya bukan URL storage yang dikenal, return (None, None)."""
        return object_store.parse_storage_url(url)


    # 1. Halaman Form Edit Produk
    @app.get("/products/{product_id}/edit", response_class=HTMLResponse)
    async def edit_product_page(request: Request, product_id: str, current_user: dict = Depends(get_current_user)):
        try:
            prod_resp = supabase.table("products").select("*").eq("id", product_id).eq("is_deleted", False).single().execute()
        except Exception as e:
            # .single() melempar APIError kalau produk gak ketemu (URL rusak / produk terhapus) -> jangan 500
            print(f"Produk {product_id} tidak ditemukan, redirect ke dashboard: {e}")
            return RedirectResponse(url="/", status_code=303)

        if not prod_resp.data:
            return RedirectResponse(url="/", status_code=303)

        product = prod_resp.data

        try:
            brands_resp = supabase.table("brands").select("id, name, producers(name)").order("name").execute()
            brands = brands_resp.data or []
        except Exception as e:
            print(f"Gagal ambil data brands buat dropdown: {e}")
            brands = []

        # --- Data Tab Bab 2 (Mutu Bahan & Formula) ---
        formula = []
        raw_materials = []
        bab2_materials = []
        sop_cpkb_url = None
        try:
            formula_resp = supabase.table("product_formula_lines") \
                .select("*, raw_materials(nama_dagang, kode_bahan_baku, raw_material_composition_variants(id, nama_varian, is_default))") \
                .eq("product_id", product_id) \
                .order("created_at").execute()
            formula = formula_resp.data or []

            # Normalisasi embed raw_materials (dict vs list-of-1) + siapkan daftar
            # varian terurut (default dulu) per baris untuk dropdown Fase 4.
            for line in formula:
                rm_embed = line.get("raw_materials")
                if isinstance(rm_embed, list):
                    rm_embed = rm_embed[0] if rm_embed else {}
                    line["raw_materials"] = rm_embed
                if not isinstance(rm_embed, dict):
                    rm_embed = {}
                    line["raw_materials"] = rm_embed
                variants = rm_embed.get("raw_material_composition_variants") or []
                if isinstance(variants, dict):
                    variants = [variants]
                line["rm_variants"] = sorted(
                    variants,
                    key=lambda v: (not v.get("is_default"), v.get("nama_varian") or ""),
                )

            rm_resp = supabase.table("raw_materials") \
                .select("id, nama_dagang, kode_bahan_baku") \
                .order("nama_dagang").execute()
            raw_materials = rm_resp.data or []

            perusahaan = product.get("perusahaan") or "PT Erfi"

            # Bahan baku unik yang dipakai di formula produk ini (urutan sesuai susunan formula)
            seen_ids = set()
            uniq_rm = []
            for line in formula:
                rm = line.get("raw_materials")
                if isinstance(rm, list) and rm:
                    rm = rm[0]
                if isinstance(rm, dict) and rm.get("id") and rm["id"] not in seen_ids:
                    seen_ids.add(rm["id"])
                    uniq_rm.append(rm)

            # Dokumen pendukung Bab 2 per bahan baku: PDF Spesifikasi asli + MSDS (company-specific)
            # + batch terbaru perusahaan produk ini (CoA, Halal, Laporan Pemeriksaan)
            for rm in uniq_rm:
                rm = _apply_company_specific_docs(rm, perusahaan)
                batch_resp = supabase.table("raw_material_batches") \
                    .select("*") \
                    .eq("raw_material_id", rm["id"]) \
                    .eq("perusahaan", perusahaan) \
                    .neq("kesimpulan", "lab") \
                    .order("created_at", desc=True) \
                    .limit(1) \
                    .execute()
                batch = batch_resp.data[0] if batch_resp.data else None
                bab2_materials.append({"material": rm, "batch": batch})

            # SOP CPKB perusahaan (lampiran checklist Bab 2)
            sop_resp = supabase.table("cpkb_raw_material") \
                .select("file_url") \
                .eq("perusahaan", perusahaan) \
                .limit(1) \
                .execute()
            sop_cpkb_url = sop_resp.data[0]["file_url"] if sop_resp.data else None
        except Exception as e:
            print(f"Gagal ambil data Bab 2 buat halaman edit produk {product_id}: {e}")

        # Status "sudah diisi" spek produk jadi (khusus PT Erfi) buat kartu inline Bab 3
        has_finished_spec = False
        if product.get("perusahaan") == "PT Erfi":
            try:
                spec_check = supabase.table("product_finished_specs").select("id").eq("product_id", product_id).execute()
                has_finished_spec = bool(spec_check.data)
            except Exception as e:
                print(f"Gagal cek finished spec produk {product_id}: {e}")
                has_finished_spec = False

        # Get error message from cookie (if any)
        error_msg = request.cookies.get("error_msg")
        success_msg = request.cookies.get("success_msg")

        # Lampiran produk (fitur attachment) — dikelompokkan per tanggal unggah.
        # Jika tabel atau bucket belum tersedia, halaman tetap fail-soft.
        lampiran_groups = {}
        try:
            att_resp = supabase.table("product_attachments") \
                .select("id, kategori, file_name, file_path, file_size, catatan, uploaded_by, uploaded_by_name, created_at") \
                .eq("product_id", product_id) \
                .order("created_at", desc=True) \
                .execute()
            _attachment_rows = att_resp.data or []
            for _att in _attachment_rows:
                try:
                    date_key = datetime.fromisoformat(str(_att.get("created_at") or "").replace("Z", "+00:00")).astimezone(WIB).strftime("%Y-%m-%d")
                except Exception:
                    date_key = str(_att.get("created_at") or "")[:10]
                lampiran_groups.setdefault(date_key, []).append({
                    "id": _att.get("id"),
                    "kategori": _att.get("kategori"),
                    "file_name": _att.get("file_name"),
                    "file_size": _att.get("file_size"),
                    "catatan": _att.get("catatan"),
                    "uploaded_by_name": _att.get("uploaded_by_name"),
                    "created_at": _att.get("created_at"),
                    "file_path": _att.get("file_path"),
                    "signed_url": None,
                    "can_manage": bool(_att.get("uploaded_by") and current_user.get("id") and str(_att.get("uploaded_by")) == str(current_user.get("id"))) or current_user.get("role") == "admin",
                })
            _paths = [_att.get("file_path") for _att in _attachment_rows if _att.get("file_path")]
            _signed_map = object_store.signed_urls("product-attachments", _paths, 3600, client=supabase)
            for _items in lampiran_groups.values():
                for _item in _items:
                    _item["signed_url"] = _signed_map.get(_item.get("file_path"))
        except Exception as e:
            print(f"Gagal ambil lampiran produk {product_id}: {e}")
            lampiran_groups = {}

        return templates.TemplateResponse(
            request=request,
            name="edit_product.html",
            context={
                "product": product,
                "brands": brands,
                "formula": formula,
                "raw_materials": raw_materials,
                "bab2_materials": bab2_materials,
                "sop_cpkb_url": sop_cpkb_url,
                "has_finished_spec": has_finished_spec,
                "error_msg": error_msg,
                "success_msg": success_msg,
                "efek_samping": _efek_samping_meta(product),
                "current_user": current_user,
                "lampiran_groups": lampiran_groups,
                "lampiran_categories": LAMPIRAN_CATEGORIES,
            }
        )

    # 2. Proses Simpan Perubahan Info Produk (PERBAIKAN: Kolom disinkronkan dengan add_product)
    @app.post("/products/{product_id}/edit")
    async def update_product(
        request: Request,
        product_id: str,
        nama_produk: str = Form(...),
        perusahaan: str = Form(...),
        nama_customer: str = Form(None),
        sediaan: str = Form(None),
        warna: str = Form(None),
        netto: str = Form(None),      
        kemasan: str = Form(None),
        no_na_produk: str = Form(None),
        status_na: str = Form("aktif"),
        tanggal_aktif_na: str = Form(None),
        acc_sampel: str = Form(None),
        tanggal_text_design: str = Form(None),
        teks_marketing: str = Form(None),
        cara_pakai: str = Form(None),
        peringatan: str = Form(None),
        penyimpanan: str = Form(None),
        status_progress: str = Form("R&D / Sample Phase"),
        brand_id: str = Form(None),
        # File Bab 1
        no_notifikasi_file: UploadFile = File(None),
        # File Bab 3
        cara_pembuatan_file: UploadFile = File(None),
        sistem_penomoran_batch_file: UploadFile = File(None),
        spek_produk_jadi_file: UploadFile = File(None),
        spek_pengemas_file: UploadFile = File(None),
        laporan_uji_sig_file: UploadFile = File(None),
        protokol_stabilitas_file: UploadFile = File(None),
        hasil_stabilitas_file: UploadFile = File(None),
        # File Bab 4 (NEW)
        laporan_keamanan_file: UploadFile = File(None),
        monitoring_efek_samping_file: UploadFile = File(None),
        data_klaim_file: UploadFile = File(None),
        desain_primer_file: UploadFile = File(None),
        desain_sekunder_file: UploadFile = File(None),
        # Bab 2 (Mutu Bahan & Formula): susunan formula komposisi
        formula_submitted: str = Form(None),
        raw_material_id: List[str] = Form(None),
        percentage: List[str] = Form(None),
        variant_id: List[str] = Form(None),
        current_user: dict = Depends(get_current_user)
    ):
        acc_sampel_val = acc_sampel.strip() if acc_sampel else None
        if acc_sampel_val == "": acc_sampel_val = None

        tgl_aktif_na_val = tanggal_aktif_na.strip() if tanggal_aktif_na else None
        if tgl_aktif_na_val == "": tgl_aktif_na_val = None

        # Ambil data lama dulu sebelum diubah, buat dibandingin di activity log
        try:
            old_product_resp = supabase.table("products").select("*").eq("id", product_id).eq("is_deleted", False).single().execute()
        except Exception as e:
            print(f"Produk {product_id} tidak ditemukan atau sudah dihapus: {e}")
            return RedirectResponse(url="/", status_code=303)

        if not old_product_resp.data:
            return RedirectResponse(url="/", status_code=303)

        old_product = old_product_resp.data

        # Lapisan authz tenant: non-admin hanya boleh edit produk perusahaannya sendiri
        # dan tidak boleh memindahkan produk ke perusahaan lain.
        if current_user.get("role") != "admin":
            _user_company = (current_user.get("perusahaan") or "").strip().lower()
            _old_company = (old_product.get("perusahaan") or "").strip().lower()
            _new_company = (perusahaan or "").strip().lower()
            if _user_company and (_old_company != _user_company or _new_company != _user_company):
                raise HTTPException(status_code=403, detail="Akses ditolak! Produk bukan milik perusahaan Anda.")

        update_payload = {
            "nama_produk": nama_produk,
            "perusahaan": perusahaan,
            "nama_customer": nama_customer,
            "sediaan": sediaan,
            "warna": warna,
            "netto": netto,          
            "kemasan": kemasan,
            "no_na_produk": no_na_produk,
            "status_na": status_na,
            "tanggal_aktif_na": tgl_aktif_na_val,
            "acc_sampel": acc_sampel_val,
            "tanggal_text_design": tanggal_text_design or None,
            "teks_marketing": teks_marketing,
            "cara_pakai": cara_pakai,
            "peringatan": peringatan,
            "penyimpanan": penyimpanan,
            "status_progress": status_progress,
            "brand_id": brand_id if brand_id else None
        }

        async def process_pdf_upload(file_obj, path_suffix, bucket_name="raw-material-docs"):
            if file_obj and file_obj.filename:
                try:
                    file_bytes = await file_obj.read()

                    _err = validate_pdf_bytes(file_bytes, "File")
                    if _err:
                        # Preserve 413 for size-related errors
                        if "terlalu besar" in _err:
                            raise HTTPException(status_code=413, detail=_err)
                        raise HTTPException(status_code=400, detail=_err)

                    path = f"products/{product_id}/{path_suffix}.pdf"
                    object_store.upload_pdf(bucket_name, path, file_bytes, client=supabase)
                    return object_store.public_url(bucket_name, path, client=supabase)
                except HTTPException:
                    raise
                except Exception as e:
                    # Tangkap error 413 dari Supabase/backend (payload terlalu besar)
                    error_str = str(e).lower()
                    if "413" in error_str or "payload too large" in error_str or "too large" in error_str:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Ukuran file terlalu besar! Maksimal ukuran file adalah 10 MB. Silakan kompres PDF Anda terlebih dahulu."
                        )
                    print(f"Gagal upload {path_suffix} produk {product_id}: {e}")
            return None

        # Upload Bab 1
        try:
            no_notif_url = await process_pdf_upload(no_notifikasi_file, "no_notifikasi", bucket_name="legal-documents")
            if no_notif_url: update_payload["no_notifikasi_file_url"] = no_notif_url
        except HTTPException as he:
            if he.status_code == 413:
                raise he
            print(f"Gagal upload no_notifikasi produk {product_id}: {he}")

        # Upload Map File Bab 3 & Bab 4
        file_mappings = {
            # Bab 3
            "cara_pembuatan_file_url": (cara_pembuatan_file, "cara_pembuatan"),
            "sistem_penomoran_batch_file_url": (sistem_penomoran_batch_file, "sistem_penomoran_batch"),
            "spek_produk_jadi_file_url": (spek_produk_jadi_file, "spek_produk_jadi"),
            "spek_pengemas_file_url": (spek_pengemas_file, "spek_pengemas"),
            "laporan_uji_sig_file_url": (laporan_uji_sig_file, "laporan_uji_sig"),
            "protokol_stabilitas_file_url": (protokol_stabilitas_file, "protokol_stabilitas"),
            "hasil_stabilitas_file_url": (hasil_stabilitas_file, "hasil_stabilitas"),
            # Bab 4
            "laporan_keamanan_file_url": (laporan_keamanan_file, "laporan_keamanan"),
            "monitoring_efek_samping_file_url": (monitoring_efek_samping_file, "monitoring_efek_samping"),
            "data_klaim_file_url": (data_klaim_file, "data_klaim"),
            "desain_primer_file_url": (desain_primer_file, "desain_primer"),
            "desain_sekunder_file_url": (desain_sekunder_file, "desain_sekunder"),
        }

        for db_col, (file_obj, key_suffix) in file_mappings.items():
            try:
                uploaded_url = await process_pdf_upload(file_obj, key_suffix)
                if uploaded_url:
                    update_payload[db_col] = uploaded_url
            except HTTPException as he:
                if he.status_code == 413:
                    raise he
                print(f"Gagal upload {key_suffix} produk {product_id}: {he}")

        supabase.table("products").update(update_payload).eq("id", product_id).execute()

        # --- Simpan Susunan Formula Bab 2 (kalau tab Bab 2 ikut di-submit) ---
        # Delete + re-insert semua baris formula biar urutan & komposisi selalu tersinkron.
        # Baris lama tetap dirender dari DB di halaman edit, jadi kalau gak diubah pun
        # datanya tetap tersimpan sama persis (tidak ada data Bab 2 yang hilang).
        if formula_submitted:
            try:
                supabase.table("product_formula_lines").delete().eq("product_id", product_id).execute()
                if raw_material_id:
                    # --- Validasi variant_id per baris (Fase 4): varian wajib milik
                    #     bahan bakunya sendiri; kosong/invalid = default (NULL) ---
                    rm_ids_needed = [r.strip() for r in (raw_material_id or []) if (r or "").strip()]
                    variant_owner = {}
                    if rm_ids_needed:
                        try:
                            v_resp = supabase.table("raw_material_composition_variants") \
                                .select("id, raw_material_id").in_("raw_material_id", rm_ids_needed).execute()
                            for v in (v_resp.data or []):
                                variant_owner[v["id"]] = v.get("raw_material_id")
                        except Exception as e:
                            print(f"Gagal validasi variant_id produk {product_id}: {e}")
                    lines = []
                    for i in range(len(raw_material_id)):
                        rm_id = (raw_material_id[i] or "").strip()
                        if rm_id:
                            try:
                                pct = float(percentage[i]) if percentage and i < len(percentage) else 0.0
                            except (TypeError, ValueError):
                                pct = 0.0
                            v_raw = (variant_id[i] if variant_id and i < len(variant_id) else "") or ""
                            v_clean = v_raw.strip() or None
                            # Tolak variant_id yang bukan milik bahan baku baris ini
                            # (misal hasil manipulasi form) -> fallback ke default.
                            if v_clean and variant_owner.get(v_clean) != rm_id:
                                v_clean = None
                            lines.append({
                                "product_id": product_id,
                                "raw_material_id": rm_id,
                                "percent_in_formula": pct,
                                "variant_id": v_clean,
                            })
                    if lines:
                        supabase.table("product_formula_lines").insert(lines).execute()
            except Exception as e:
                print(f"Gagal simpan formula Bab 2 produk {product_id}: {e}")

        # --- Catat activity log: field teks dibandingin beneran, field file cuma dicatet "diganti" ---
        product_field_labels = {
            "nama_produk": "Nama Produk",
            "perusahaan": "Perusahaan",
            "nama_customer": "Nama Customer",
            "sediaan": "Sediaan",
            "warna": "Warna",
            "netto": "Netto",
            "kemasan": "Kemasan",
            "no_na_produk": "No. NA Produk",
            "status_na": "Status NA",
            "tanggal_aktif_na": "Tanggal Aktif NA",
            "acc_sampel": "Tanggal Acc Sampel",
            "tanggal_text_design": "Tanggal Text Design",
            "teks_marketing": "Teks Marketing",
            "cara_pakai": "Cara Pakai",
            "peringatan": "Peringatan",
            "status_progress": "Status Progress",
            "brand_id": "Brand",
            "no_notifikasi_file_url": "File No. Notifikasi",
            "cara_pembuatan_file_url": "File Cara Pembuatan",
            "sistem_penomoran_batch_file_url": "File Sistem Penomoran Batch",
            "spek_produk_jadi_file_url": "File Spek Produk Jadi",
            "spek_pengemas_file_url": "File Spek Pengemas",
            "laporan_uji_sig_file_url": "File Laporan Uji SIG",
            "protokol_stabilitas_file_url": "File Protokol Stabilitas",
            "hasil_stabilitas_file_url": "File Hasil Stabilitas",
            "laporan_keamanan_file_url": "File Laporan Keamanan",
            "monitoring_efek_samping_file_url": "File Monitoring Efek Samping",
            "data_klaim_file_url": "File Data Klaim",
            "desain_primer_file_url": "File Desain Primer",
            "desain_sekunder_file_url": "File Desain Sekunder",
        }
        product_file_fields = {k for k in product_field_labels if k.endswith("_file_url")}
        product_changes = _build_diff_changes(old_product, update_payload, product_field_labels, product_file_fields)
        if product_changes:
            log_activity(current_user, "update", "product", product_id, nama_produk,
                         product_changes, request=request)

        response = RedirectResponse(url=f"/products/{product_id}/edit", status_code=303)
        response.set_cookie("success_msg", f"Data & dokumen DIP produk '{nama_produk}' berhasil diperbarui!")
        return response

    @app.post("/products/{product_id}/delete-file")
    async def delete_product_file(
        request: Request,
        product_id: str,
        field_name: str = Form(...),
        current_user: dict = Depends(get_current_user),
    ):
        FIELD_LABELS = {
            "no_notifikasi_file": "Surat No. Notifikasi BPOM",
            "cara_pembuatan_file": "Ringkasan Cara Pembuatan Kosmetik",
            "sistem_penomoran_batch_file": "Sistem Penomoran Batch Spesifik",
            "spek_produk_jadi_file": "SAPJ dan Spesifikasi Produk Jadi",
            "spek_pengemas_file": "Spesifikasi Bahan Pengemas",
            "laporan_uji_sig_file": "Laporan Hasil Uji Lab Eksternal / SIG",
            "protokol_stabilitas_file": "Pemantauan Stabilitas",
            "hasil_stabilitas_file": "Hasil Studi Stabilitas",
            "laporan_keamanan_file": "Laporan Penilaian Keamanan Kosmetik (Safety Assessment)",
            "monitoring_efek_samping_file": "Laporan / Data Monitoring Efek Samping (Cosmetovigilance)",
            "data_klaim_file": "Data Pendukung Klaim Kosmetik (Claim Substantiation)",
            "desain_primer_file": "Desain Kemasan Primer (Penandaan)",
            "desain_sekunder_file": "Desain Kemasan Sekunder (Penandaan)",
        }

        if field_name not in FIELD_LABELS:
            log_activity(
                current_user, "delete", "product_file", product_id, product_id,
                changes=[{"field": field_name, "note": "field tidak valid"}],
                request=request, outcome="rejected",
            )
            raise HTTPException(status_code=400, detail="Field file tidak valid.")

        db_field = field_name + "_url"
        label = FIELD_LABELS[field_name]

        try:
            prod_resp = supabase.table("products").select(
                "id, perusahaan, nama_produk, " + db_field
            ).eq("id", product_id).eq("is_deleted", False).single().execute()
        except Exception as e:
            print(f"Produk {product_id} tidak ditemukan saat hapus file: {e}")
            return RedirectResponse(url="/", status_code=303)

        if not prod_resp.data:
            return RedirectResponse(url="/", status_code=303)

        product = prod_resp.data
        entity_label = product.get("nama_produk") or product_id

        if current_user.get("role") != "admin":
            _user_company = (current_user.get("perusahaan") or "").strip().lower()
            _prod_company = (product.get("perusahaan") or "").strip().lower()
            if _user_company and _prod_company and _user_company != _prod_company:
                log_activity(
                    current_user, "delete", "product_file", product_id, entity_label,
                    changes=[{"field": label, "note": "ditolak: bukan milik perusahaan"}],
                    request=request, outcome="rejected",
                )
                raise HTTPException(status_code=403, detail="Akses ditolak! File bukan milik perusahaan Anda.")

        file_url = product.get(db_field)
        storage_note = None
        bucket = None
        path = None

        if file_url:
            bucket, path = object_store.parse_storage_url(file_url)
            if not bucket or not path:
                storage_note = "URL bukan storage internal, objek tidak dihapus"

        try:
            supabase.table("products").update({db_field: None}).eq("id", product_id).execute()
        except Exception as e:
            print(f"Gagal update DB hapus file {db_field} produk {product_id}: {e}")
            response = RedirectResponse(url=f"/products/{product_id}/edit", status_code=303)
            response.set_cookie("error_msg", "Gagal menghapus file. Silakan coba lagi.")
            return response

        storage_failed = False
        if file_url and bucket and path:
            result = object_store.remove_from_all_backends(bucket, path, client=supabase)
            failed = object_store.failed_backends(result)
            if failed:
                storage_failed = True
                details = []
                for backend in failed:
                    backend_result = result.get(backend) or {}
                    details.append(
                        f"{backend}: {backend_result.get('error') or 'gagal'}"
                    )
                storage_note = (
                    f"penghapusan gagal pada {', '.join(details)}; "
                    f"perlu dibersihkan manual ({bucket}/{path})"
                )
            elif result:
                statuses = []
                for backend, backend_result in result.items():
                    status = "sudah tidak ada" if backend_result.get("missing") else "berhasil"
                    statuses.append(f"{backend}: {status}")
                storage_note = "; ".join(statuses)

        changes = [{"field": label, "note": "File dihapus"}]

        outcome = "failed" if storage_failed else "success"
        log_activity(
            current_user, "delete", "product_file", product_id, entity_label,
            changes=changes, request=request, outcome=outcome,
            storage_note=storage_note,
        )

        def _tab_for_field(name: str) -> str:
            if name == "no_notifikasi_file":
                return "bab1"
            if name in {
                "cara_pembuatan_file", "sistem_penomoran_batch_file", "spek_produk_jadi_file",
                "spek_pengemas_file", "laporan_uji_sig_file", "protokol_stabilitas_file",
                "hasil_stabilitas_file",
            }:
                return "bab3"
            return "bab4"

        if storage_failed:
            response = RedirectResponse(url=f"/products/{product_id}/edit?tab={_tab_for_field(field_name)}", status_code=303)
            response.set_cookie("warning_msg", "File dilepas dari produk, tetapi objek di storage gagal dihapus; hubungi admin.")
            return response

        tab = _tab_for_field(field_name)
        response = RedirectResponse(url=f"/products/{product_id}/edit?tab={tab}", status_code=303)
        response.set_cookie("success_msg", "File PDF berhasil dihapus.")
        return response
