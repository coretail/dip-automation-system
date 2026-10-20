"""Dashboard, trash, and restore routes (extracted from main.py)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

WIB = ZoneInfo("Asia/Jakarta")


def register_dashboard_routes(
    app,
    get_current_user,
    supabase,
    templates,
    log_activity,
    get_ed_notification_count,
    compute_status_na,
    get_company_info,
    format_date_id,
    _logo_render_width,
    _efek_samping_meta,
    _pdf_link_callback,
    slugify,
    COMPANY_INFO,
    _resolve_variant_components,
    _flag_bahan_aktif,
    _build_diff_changes,
):
    @app.get("/admin/trash", response_class=HTMLResponse)
    async def admin_trash_page(request: Request, current_user: dict = Depends(get_current_user)):
        if current_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak")

        try:
            response = supabase.table("products").select("*, brands(name)").eq("is_deleted", True).order("deleted_at", desc=True).execute()
            products = response.data or []
        except Exception as e:
            print(f"Gagal memuat trash: {e}")
            products = []

        return templates.TemplateResponse(
            request=request,
            name="admin_trash.html",
            context={
                "products": products,
                "current_user": current_user,
                "ed_notification_count": await get_ed_notification_count()
            }
        )

    @app.post("/admin/products/{product_id}/restore")
    async def restore_product(request: Request, product_id: str,
                              current_user: dict = Depends(get_current_user)):
        if current_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak")

        try:
            supabase.table("products").update({"is_deleted": False, "deleted_at": None}).eq("id", product_id).execute()
            # Perlu fungsi log_activity yang sudah ada di main.py
            log_activity(current_user, "restore", "product", product_id,
                         "Restore produk dari sampah", request=request)
            return RedirectResponse(url="/admin/trash?success=Produk berhasil dikembalikan", status_code=303)
        except Exception as e:
            print(f"Gagal restore produk: {e}")
            return RedirectResponse(url="/admin/trash?error=Gagal mengembalikan produk", status_code=303)


    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, current_user: dict = Depends(get_current_user)):
        # Pastikan variabel ini didefinisikan dengan nilai default None agar tidak error
        success_msg = request.cookies.get("success_msg") or request.query_params.get("success")
        error_msg = request.cookies.get("error_msg") or request.query_params.get("error")

        products, brands = [], []
        try:
            # 1. Ambil data produk master
            response_prod = supabase.table("products").select("*, brands(name)").eq("is_deleted", False).order("created_at", desc=True).execute()
            products = response_prod.data or []

            # 2. Ambil ID produk yang udah punya formula (Bab 2) lewat view agregat
            #    product_formula_presence (1 baris per produk, lihat migration/006).
            #    Fetch full-table product_formula_lines bisa dipotong diam-diam sama
            #    batas PostgREST db.max-rows=1000, bikin Bab II salah tampil "Kosong".
            #    Kalau view-nya belum kepasang, fallback ke fetch berhalaman (.range).
            prods_with_formula = set()
            try:
                formula_prods_resp = supabase.table("product_formula_presence").select("product_id").execute()
                prods_with_formula = set([item["product_id"] for item in (formula_prods_resp.data or []) if item.get("product_id")])
            except Exception as e:
                print(f"Gagal tarik product_formula_presence, fallback fetch berhalaman: {e}")
                try:
                    page_size, offset = 1000, 0
                    while True:
                        lines_resp = supabase.table("product_formula_lines").select("product_id") \
                            .range(offset, offset + page_size - 1).execute()
                        lines_data = lines_resp.data or []
                        if not lines_data:
                            break
                        prods_with_formula.update(item["product_id"] for item in lines_data if item.get("product_id"))
                        if len(lines_data) < page_size:
                            break
                        offset += page_size
                except Exception as e2:
                    print(f"Gagal tarik formula lines: {e2}")

            # Data pendukung Bab I: NIB, CPKB, Tidak Pidana itu per-perusahaan (bukan per-produk),
            # Hak & Lisensi Merk itu per-brand+perusahaan. Ambil sekali di luar loop biar efisien.
            nib_by_company = {}
            try:
                nib_resp = supabase.table("nib_documents").select("perusahaan, file_url").execute()
                for row in (nib_resp.data or []):
                    if row.get("file_url"):
                        nib_by_company[row["perusahaan"]] = True
            except Exception as e:
                print(f"Gagal tarik nib_documents: {e}")

            cpkb_by_company = {}
            try:
                cpkb_resp = supabase.table("sertifikat_cpkb_documents").select("perusahaan, file_url").execute()
                for row in (cpkb_resp.data or []):
                    if row.get("file_url"):
                        cpkb_by_company[row["perusahaan"]] = True
            except Exception as e:
                print(f"Gagal tarik sertifikat_cpkb_documents: {e}")

            pidana_by_company = {}
            try:
                pidana_resp = supabase.table("surat_tidak_pidana_documents").select("perusahaan, file_url").execute()
                for row in (pidana_resp.data or []):
                    if row.get("file_url"):
                        pidana_by_company[row["perusahaan"]] = True
            except Exception as e:
                print(f"Gagal tarik surat_tidak_pidana_documents: {e}")

            hak_merk_by_brand_company = {}
            try:
                hak_merk_resp = supabase.table("brand_legal_documents").select("brand_id, perusahaan, hak_lisensi_merk_file_url").execute()
                for row in (hak_merk_resp.data or []):
                    if row.get("hak_lisensi_merk_file_url"):
                        hak_merk_by_brand_company[(row["brand_id"], row["perusahaan"])] = True
            except Exception as e:
                print(f"Gagal tarik brand_legal_documents: {e}")


            # 3. Hitung status NA dan matriks kelengkapan dokumen Bab I - IV per produk
            for p in products:
                # Inisialisasi default value dulu biar Jinja2 gak crash
                p["dip_summary"] = {
                    "b1_ok": False,
                    "b1_ratio": "0/5",
                    "b1_missing": ["NIB", "Sertifikat CPKB", "Hak & Lisensi Merk", "Surat Tidak Pidana", "Surat Notifikasi BPOM"],
                    "b2_ok": False,
                    "b3_ok": False,
                    "b3_ratio": "0/7",
                    "b3_missing": ["Ringkasan Cara Pembuatan Kosmetik", "Sistem Penomoran Batch Spesifik", "Spesifikasi Produk Jadi", "Spesifikasi Bahan Pengemas", "Laporan Hasil Uji Lab Eksternal (SIG)", "Protokol Pemantauan Stabilitas", "Hasil Studi Stabilitas"],
                    "b4_ok": False,
                    "b4_ratio": "0/5",
                    "b4_missing": ["Laporan Penilaian Keamanan Kosmetik", "Laporan Monitoring Efek Samping Kosmetik", "Data Pendukung Klaim Kosmetik", "Penandaan & Desain Kemasan Primer", "Penandaan & Desain Kemasan Sekunder"],
                    "progress_pct": 0,
                    "is_complete": False
                }

                try:
                    p["status_na"], p["na_days_remaining"] = compute_status_na(p.get("tanggal_aktif_na"), p.get("status_na") or "belum_terdaftar")
                    p["status_na"], p["na_days_remaining"] = compute_status_na(p.get("tanggal_aktif_na"), p.get("status_na") or "belum_terdaftar")


                    b1_perusahaan = p.get("perusahaan") or "PT Erfi"
                    b1_brand_id = p.get("brand_id")
                    b1_items = {
                        "NIB": bool(nib_by_company.get(b1_perusahaan)),
                        "Sertifikat CPKB": bool(cpkb_by_company.get(b1_perusahaan)),
                        "Hak & Lisensi Merk": bool(hak_merk_by_brand_company.get((b1_brand_id, b1_perusahaan))),
                        "Surat Tidak Pidana": bool(pidana_by_company.get(b1_perusahaan)),
                        "Surat Notifikasi BPOM": bool(p.get("no_notifikasi_file_url")),
                    }
                    b1_count = sum(1 for v in b1_items.values() if v)
                    b1_ok = (b1_count == len(b1_items))
                    b1_missing = [k for k, v in b1_items.items() if not v]

                    b2_ok = p.get("id") in prods_with_formula

                    b3_items = {
                        "Ringkasan Cara Pembuatan Kosmetik": bool(p.get("cara_pembuatan_file_url")),
                        "Sistem Penomoran Batch Spesifik": bool(p.get("sistem_penomoran_batch_file_url")),
                        "Spesifikasi Produk Jadi": bool(p.get("spek_produk_jadi_file_url")),
                        "Spesifikasi Bahan Pengemas": bool(p.get("spek_pengemas_file_url")),
                        "Laporan Hasil Uji Lab Eksternal (SIG)": bool(p.get("laporan_uji_sig_file_url")),
                        "Protokol Pemantauan Stabilitas": bool(p.get("protokol_stabilitas_file_url")),
                        "Hasil Studi Stabilitas": bool(p.get("hasil_stabilitas_file_url")),
                    }
                    b3_count = sum(1 for v in b3_items.values() if v)
                    b3_ok = (b3_count == len(b3_items))
                    b3_missing = [k for k, v in b3_items.items() if not v]

                    b4_items = {
                        "Laporan Penilaian Keamanan Kosmetik": bool(p.get("laporan_keamanan_file_url")),
                        "Laporan Monitoring Efek Samping Kosmetik": bool(p.get("monitoring_efek_samping_file_url")),
                        "Penandaan & Desain Kemasan Primer": bool(p.get("desain_primer_file_url")),
                        "Penandaan & Desain Kemasan Sekunder": bool(p.get("desain_sekunder_file_url")),
                    }
                    b4_count = sum(1 for v in b4_items.values() if v)
                    b4_ok = (b4_count == len(b4_items))
                    b4_missing = [k for k, v in b4_items.items() if not v]

                    b4_bonus = bool(p.get("data_klaim_file_url"))

                    total_checks = len(b1_items) + 1 + len(b3_items) + len(b4_items)
                    current_checks = b1_count + (1 if b2_ok else 0) + b3_count + b4_count
                    if b4_bonus:
                        current_checks += 1
                    progress_pct = int((current_checks / total_checks) * 100)

                    p["dip_summary"] = {
                        "b1_ok": b1_ok,
                        "b1_ratio": f"{b1_count}/{len(b1_items)}",
                        "b1_missing": b1_missing,
                        "b2_ok": b2_ok,
                        "b3_ok": b3_ok,
                        "b3_ratio": f"{b3_count}/{len(b3_items)}",
                        "b3_missing": b3_missing,
                        "b4_ok": b4_ok,
                        "b4_ratio": f"{b4_count}/{len(b4_items)}",
                        "b4_missing": b4_missing,
                        "progress_pct": progress_pct,
                        "is_complete": progress_pct == 100
                    }
                except Exception as err:
                    print(f"Error hitung dip_summary produk {p.get('id')}: {err}")

            # Data brands buat modal Tambah Produk
            try:
                response_brands = supabase.table("brands").select("id, name, producers(name)").order("name").execute()
                brands = response_brands.data or []
            except Exception as e:
                print(f"Gagal tarik brands: {e}")

        except Exception as e:
            print(f"Gagal ambil data dashboard: {e}")

        # Jumlah lampiran per produk (tabel product_attachments) — dibutuhkan
        # dashboard.html untuk badge jumlah lampiran pada tiap kartu produk.
        try:
            att_rows = supabase.table("product_attachment_counts").select("product_id, jumlah").execute()
            attachment_counts = {}
            for _row in (att_rows.data or []):
                if _row.get("product_id"):
                    attachment_counts[_row["product_id"]] = int(_row.get("jumlah") or 0)
        except Exception as e:
            print(f"Gagal ambil agregat lampiran, fallback tabel: {e}")
            try:
                att_rows = supabase.table("product_attachments").select("product_id").execute()
                attachment_counts = {}
                for _row in (att_rows.data or []):
                    _pid = _row.get("product_id")
                    if _pid:
                        attachment_counts[_pid] = attachment_counts.get(_pid, 0) + 1
            except Exception as fallback_exc:
                print(f"Gagal hitung lampiran: {fallback_exc}")
                attachment_counts = {}

        ed_notification_count = await get_ed_notification_count()

        import json
        try:
            greeting = json.loads(request.cookies.get("greeting_cache", ""))
        except Exception:
            greeting = get_time_greeting()

        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "request": request,
                "current_user": current_user,
                "products": products,
                "user": current_user,
                "brands": brands,
                "ed_notification_count": ed_notification_count,
                "greeting": greeting,
                "error_msg": error_msg,
                "success_msg": success_msg,
                "attachment_counts": attachment_counts
            }
        )

