"""Generator dokumen DIP Bab I-IV + ZIP Bab II.

Refactor murni dari blok generator yang sebelumnya berada di app/main.py.
Semua route tetap sama persis (path, method, response, status code, pesan
error) dan badan setiap fungsi TIDAK diubah satu baris pun.

Dependency dari main.py di-inject sebagai parameter agar tidak ada circular
import (pola yang sama seperti raw_materials_routes / dip_public).

Route /dip/* (public link BPOM) TIDAK ada di modul ini - itu milik
app/dip_public.py. Route finished-spec juga tetap di main.py.
"""

import io
import logging
import os
import re
import zipfile
from decimal import Decimal

import httpx
from fastapi import Depends, HTTPException, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from pypdf import PdfReader, PdfWriter
from xhtml2pdf import pisa

from app import bab2_pdf

# Catatan: nama logger berubah dari "app.main" menjadi "app.dip_documents".
logger = logging.getLogger(__name__)

# Folder app/static — dipakai untuk resolve path absolut gambar kop surat.
_STATIC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


# Lebar area konten Bab III = A4 (595,28 pt) dikurangi margin 10 mm kiri/kanan.
# Tabel formula memakai width:100% jadi lebarnya sama dengan nilai ini.
BAB3_CONTENT_WIDTH_PT = 538.58
# Kop surat dibuat 80% dari lebar tabel formula lalu dipusatkan.
KOP_WIDTH_RATIO = 0.80
# Rasio tinggi/lebar berkas kop aslinya, supaya gambar tidak gepeng.
KOP_ASPECT = {"kop_erfi.png": 114 / 805, "kop_heka.png": 132 / 802}


def _kop_image(company: dict, max_width_pt: float = BAB3_CONTENT_WIDTH_PT):
    """Gambar kop surat perusahaan sebagai dict {src, width, height, name} untuk xhtml2pdf.

    xhtml2pdf tidak bisa resolve URL "/static/images/kop_*.png" tanpa base_url, jadi
    path filesystem absolut yang dipakai. Ukuran ditulis lewat CSS (style="width:...")
    karena yang dihormati xhtml2pdf; atribut width=反而 diskala 0,75 dan
    style="width:100%" di-collapse jadi 0.

    Return None kalau file-nya tidak ada, supaya template bisa fallback ke kop teks.
    """
    company = company or {}
    uri = (company.get("kop") or "").strip()
    if not uri:
        logo = (company.get("logo") or "").lower()
        nama = (company.get("nama") or "").lower()
        # "heka"/"haraka" dicek lebih dulu: nama resmi PT Heka mengandung kata "erfi".
        if "heka" in logo or "haraka" in nama:
            uri = "/static/images/kop_heka.png"
        elif "erfi" in logo or "erfi" in nama:
            uri = "/static/images/kop_erfi.png"
    if not uri:
        return None

    relative = uri.split("/static/", 1)[-1] if "/static/" in uri else uri.lstrip("/")
    path = os.path.join(_STATIC_ROOT, relative.replace("/", os.sep))
    if not os.path.isfile(path):
        logger.warning("Gambar kop surat tidak ditemukan: %s", path)
        return None

    width = round(float(max_width_pt) * KOP_WIDTH_RATIO, 1)
    height = round(width * KOP_ASPECT.get(os.path.basename(path), 0.15), 1)
    return {"src": path, "width": width, "height": height,
            "name": os.path.basename(path)}


def _safe_zip_name(name: str) -> str:
    """Bersihin nama biar aman dipakai sebagai nama file/folder di dalam ZIP
    (buang karakter yang gak diizinkan di Windows/macOS: < > : " / \\ | ? *)."""
    name = (name or "").strip()
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "Tanpa_Nama"


def register_dip_document_routes(
    app,
    get_current_user,
    templates,
    supabase,
    get_company_info,
    format_date_id,
    _apply_company_specific_docs,
    _resolve_variant_components,
    _pdf_link_callback,
    _logo_render_width,
):
    """Daftarkan 9 route generator DIP (Bab I-IV, preview, ZIP Bab II).

    Nama parameter sengaja sama dengan nama global aslinya di main.py
    supaya badan fungsi tidak perlu diubah satu baris pun.
    """

    # =====================================================================
    #           FASE 2B: GENERATOR DOKUMEN BAB II (PDF GABUNGAN)
    # =====================================================================
    @app.get("/products/{product_id}/bab2/download")
    async def download_bab2_document(product_id: str, current_user: dict = Depends(get_current_user)):
        try:
            product_resp = supabase.table("products").select("*").eq("id", product_id).eq("is_deleted", False).single().execute()
        except Exception as e:
            # .single() melempar APIError kalau produk gak ketemu (URL rusak / produk terhapus) -> jangan 500
            print(f"Produk {product_id} tidak ditemukan, redirect ke dashboard: {e}")
            return RedirectResponse(url="/", status_code=303)

        if not product_resp.data:
            return RedirectResponse(url="/", status_code=303)

        product = product_resp.data

        perusahaan = product.get("perusahaan") or "PT Erfi"
        company = get_company_info(perusahaan)

        # 2. Ambil semua bahan baku unik yang dipakai di formula produk ini
        lines_resp = supabase.table("product_formula_lines") \
            .select("raw_material_id, raw_materials(*)") \
            .eq("product_id", product_id) \
            .execute()

        seen_ids = set()
        raw_materials = []
        for line in (lines_resp.data or []):
            rm = line.get("raw_materials")
            if isinstance(rm, list) and rm:
                rm = rm[0]
            if isinstance(rm, dict) and rm.get("id") and rm["id"] not in seen_ids:
                seen_ids.add(rm["id"])
                raw_materials.append(rm)

        # 2b. Timpa spec_parameters & msds_file_url tiap bahan baku dengan data company-specific
        for rm in raw_materials:
            _apply_company_specific_docs(rm, perusahaan)

        # 3. Per bahan baku, tarik data batch TERBARU khusus company ini (kesepakatan: pakai batch terbaru)
        materials_data = []
        for rm in raw_materials:
            batch_resp = supabase.table("raw_material_batches") \
                .select("*") \
                .eq("raw_material_id", rm["id"]) \
                .eq("perusahaan", perusahaan) \
                .neq("kesimpulan", "lab") \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()
            latest_batch = batch_resp.data[0] if batch_resp.data else None
            materials_data.append({"material": rm, "batch": latest_batch})

        # 4. Ambil SOP CPKB sesuai perusahaan produk (tabel cpkb_raw_material)
        sop_resp = supabase.table("cpkb_raw_material") \
            .select("file_url") \
            .eq("perusahaan", perusahaan) \
            .limit(1) \
            .execute()
        sop_url = sop_resp.data[0]["file_url"] if sop_resp.data else None

        # 5. Render Checklist (halaman pembuka) jadi PDF sendiri.
        # Template terpisah dari bab2_checklist.html karena generator ZIP masih melampirkan
        # Halal & MSDS, sedangkan PDF Bab II ini tidak.
        checklist_html = templates.env.get_template("bab2_checklist_pdf.html").render(
            product=product,
            company=company
            )
        checklist_buffer = io.BytesIO()
        checklist_status = pisa.CreatePDF(src=checklist_html, dest=checklist_buffer)
        if checklist_status.err:
            raise HTTPException(status_code=500, detail="Gagal generate halaman Checklist Bab II.")
        checklist_buffer.seek(0)

        # 6. Gabungin PDF sesuai urutan request BPOM:
        # Checklist -> SOP CPKB -> 1 halaman per bahan baku (Spek + Catatan Pemeriksaan)
        # -> section seluruh CoA -> daftar missing Spek/Catatan -> daftar missing CoA
        # (Sertifikat Halal & MSDS TIDAK ikut di pipeline PDF ini -- hanya di generator ZIP)
        writer = PdfWriter()

        for page in PdfReader(checklist_buffer).pages:
            writer.add_page(page)

        async def fetch_pdf_bytes(client: httpx.AsyncClient, url: str | None, label: str) -> bytes | None:
            """Ambil PDF dari URL Supabase Storage. Return None kalau URL kosong, HTTP gagal,
            atau file rusak -- satu dokumen bermasalah tidak boleh menggagalkan seluruh Bab II."""
            if not url:
                return None
            try:
                resp = await client.get(url, timeout=30)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                logger.warning("Gagal ambil %s: %s", label, e)
                return None

        async def append_pdf_from_bytes(pdf_bytes: bytes | None, label: str) -> None:
            if not pdf_bytes:
                return
            pages = bab2_pdf.read_pdf_pages(pdf_bytes, label)
            if not pages:
                return
            for page in pages:
                writer.add_page(page)

        def render_block_to_pdf(template_name: str, **context) -> bytes | None:
            block_html = templates.env.get_template(template_name).render(**context)
            return bab2_pdf.render_html_to_pdf(block_html)

        # Accumulator dokumen yang belum tersedia (dipakai untuk section di bagian akhir PDF)
        missing_material_documents: list[str] = []
        missing_coa: list[str] = []

        async with httpx.AsyncClient() as client:
            # 6a. SOP CPKB (tetap di depan, setelah Checklist)
            await append_pdf_from_bytes(
                await fetch_pdf_bytes(client, sop_url, f"SOP CPKB ({perusahaan})"),
                f"SOP CPKB ({perusahaan})",
            )

            # 6b. Per bahan baku: Spek + Catatan Pemeriksaan dikomposisi jadi MAKSIMAL 1 halaman.
            # Spek: HANYA PDF spek sheet asli (spec_sheet_file_url) yang dianggap Spek valid.
            # Spek manual (spec_parameters) sengaja TIDAK dipakai di pipeline PDF ini.
            # Catatan Pemeriksaan: PDF laporan QC asli kalau ada, kalau tidak -> data batch.
            for idx, item in enumerate(materials_data, start=1):
                material = item["material"]
                batch = item["batch"]
                nama_bahan = material.get("nama_dagang") or f"Bahan Baku {idx}"

                documents: list[tuple[str, bytes]] = []

                # --- Spek Bahan Baku (hanya dari PDF) ---
                spec_bytes = await fetch_pdf_bytes(
                    client, material.get("spec_sheet_file_url"), f"PDF Spesifikasi {nama_bahan}")
                if spec_bytes and bab2_pdf.read_pdf_pages(spec_bytes, f"Spek {nama_bahan}"):
                    documents.append(("SPEK BAHAN BAKU", spec_bytes))
                else:
                    logger.info("Spek bahan baku %s tidak tersedia (PDF spek sheet kosong/gagal diambil)", nama_bahan)

                # --- Catatan Pemeriksaan Bahan Baku ---
                qc_bytes = await fetch_pdf_bytes(
                    client, batch.get("qc_report_file_url") if batch else None,
                    f"PDF Laporan Pemeriksaan {nama_bahan}")
                if qc_bytes and bab2_pdf.read_pdf_pages(qc_bytes, f"Catatan Pemeriksaan {nama_bahan}"):
                    documents.append(("CATATAN PEMERIKSAAN", qc_bytes))
                elif batch:
                    # Batch valid (hasil query existing) -> Catatan Pemeriksaan tetap ditampilkan
                    # dari data batch. Tidak ada empty-note kalau batch tidak ada.
                    manual_qc = render_block_to_pdf("bab2_qc_section.html", batch=batch)
                    if manual_qc:
                        documents.append(("CATATAN PEMERIKSAAN", manual_qc))
                else:
                    logger.info("Catatan Pemeriksaan bahan baku %s tidak tersedia (tidak ada batch)", nama_bahan)

                if not documents:
                    # Tanpa Spek & tanpa Catatan Pemeriksaan: jangan buat halaman kosong,
                    # cukup catat di daftar missing bagian akhir PDF.
                    missing_material_documents.append(nama_bahan)
                    continue

                composed = bab2_pdf.compose_material_page(nama_bahan, documents)
                if not composed:
                    logger.warning("Gagal mengomposisi halaman bahan baku %s", nama_bahan)
                    continue
                await append_pdf_from_bytes(composed, f"komposisi {nama_bahan}")

            # 6c. Section COA: seluruh CoA dikumpulkan di sini, berurutan sesuai bahan baku,
            # masing-masing dengan header nama bahan bakunya.
            coa_entries: list[tuple[str, bytes]] = []
            for idx, item in enumerate(materials_data, start=1):
                batch = item["batch"]
                nama_bahan = item["material"].get("nama_dagang") or f"Bahan Baku {idx}"
                coa_bytes = await fetch_pdf_bytes(
                    client, batch.get("coa_file_url") if batch else None, f"CoA bahan baku {nama_bahan}")
                if coa_bytes and bab2_pdf.read_pdf_pages(coa_bytes, f"CoA {nama_bahan}"):
                    coa_entries.append((nama_bahan, coa_bytes))
                else:
                    missing_coa.append(nama_bahan)

            coa_section = bab2_pdf.build_coa_section(coa_entries)
            if coa_section:
                await append_pdf_from_bytes(coa_section, "section CoA")

            # 6d. Bagian akhir: daftar dokumen yang belum tersedia (section kosong tidak dibuat)
            await append_pdf_from_bytes(
                bab2_pdf.build_missing_list_page(
                    "Bahan baku yang belum memiliki Spek dan Catatan Pemeriksaan:",
                    missing_material_documents,
                ),
                "daftar missing Spek/Catatan Pemeriksaan",
            )
            await append_pdf_from_bytes(
                bab2_pdf.build_missing_list_page(
                    "Bahan baku dengan COA belum terlampir:",
                    missing_coa,
                ),
                "daftar missing CoA",
            )

        output_buffer = io.BytesIO()
        writer.write(output_buffer)
        output_buffer.seek(0)

        safe_name = "".join(c for c in (product.get("nama_produk") or "Produk") if c.isalnum() or c in (" ", "-", "_")).strip()
        filename = f"Bab2_{safe_name.replace(' ', '_')}.pdf"

        return StreamingResponse(
            output_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )


    @app.get("/products/{product_id}/bab2/preview")
    async def preview_dip_bab2(product_id: str, current_user: dict = Depends(get_current_user)):
        # Preview Bab 2: generate PDF yang sama persis dengan /bab2/download, tapi disajikan
        # inline (browser menampilkan preview di tab baru) -- bukan force-download.
        resp = await download_bab2_document(product_id, current_user)
        resp.headers["Content-Disposition"] = resp.headers["Content-Disposition"].replace("attachment", "inline")
        return resp

    @app.get("/products/{product_id}/bab1/preview")
    async def preview_dip_bab1(product_id: str, current_user: dict = Depends(get_current_user)):
        # Preview Bab 1: generate PDF yang sama persis dengan /bab1/download, tapi disajikan
        # inline (browser menampilkan preview di tab baru) -- bukan force-download.
        resp = await download_bab1_document(product_id, current_user)
        resp.headers["Content-Disposition"] = resp.headers["Content-Disposition"].replace("attachment", "inline")
        return resp


    # =====================================================================
    #   GENERATOR DOKUMEN BAB II (VERSI FOLDER/ZIP -- per bahan baku terpisah)
    # =====================================================================
    @app.get("/products/{product_id}/bab2/download-zip")
    async def download_bab2_document_zip(product_id: str, current_user: dict = Depends(get_current_user)):
        try:
            product_resp = supabase.table("products").select("*").eq("id", product_id).eq("is_deleted", False).single().execute()
        except Exception as e:
            # .single() melempar APIError kalau produk gak ketemu (URL rusak / produk terhapus) -> jangan 500
            print(f"Produk {product_id} tidak ditemukan, redirect ke dashboard: {e}")
            return RedirectResponse(url="/", status_code=303)

        if not product_resp.data:
            return RedirectResponse(url="/", status_code=303)

        product = product_resp.data

        perusahaan = product.get("perusahaan") or "PT Erfi"
        company = get_company_info(perusahaan)

        # 2. Ambil semua bahan baku unik yang dipakai di formula produk ini
        lines_resp = supabase.table("product_formula_lines") \
            .select("raw_material_id, raw_materials(*)") \
            .eq("product_id", product_id) \
            .execute()

        seen_ids = set()
        raw_materials = []
        for line in (lines_resp.data or []):
            rm = line.get("raw_materials")
            if isinstance(rm, list) and rm:
                rm = rm[0]
            if isinstance(rm, dict) and rm.get("id") and rm["id"] not in seen_ids:
                seen_ids.add(rm["id"])
                raw_materials.append(rm)

        # 2b. Timpa spec_parameters & msds_file_url tiap bahan baku dengan data company-specific
        for rm in raw_materials:
            _apply_company_specific_docs(rm, perusahaan)

        # 3. Per bahan baku, tarik data batch TERBARU khusus company ini (kesepakatan: pakai batch terbaru)
        materials_data = []
        for rm in raw_materials:
            batch_resp = supabase.table("raw_material_batches") \
                .select("*") \
                .eq("raw_material_id", rm["id"]) \
                .eq("perusahaan", perusahaan) \
                .neq("kesimpulan", "lab") \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()
            latest_batch = batch_resp.data[0] if batch_resp.data else None
            materials_data.append({"material": rm, "batch": latest_batch})

        # 4. Ambil SOP CPKB sesuai perusahaan produk
        sop_resp = supabase.table("cpkb_raw_material") \
            .select("file_url") \
            .eq("perusahaan", perusahaan) \
            .limit(1) \
            .execute()
        sop_url = sop_resp.data[0]["file_url"] if sop_resp.data else None

        # 5. Siapin ZIP di memory
        zip_buffer = io.BytesIO()
        root_folder = _safe_zip_name(f"BAB II Data Mutu Bahan Baku - {product.get('nama_produk', 'Produk')}")

        async def fetch_bytes(client: httpx.AsyncClient, url: str, label: str):
            if not url:
                return None
            try:
                resp = await client.get(url, timeout=30)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                print(f"[BAB II ZIP] Gagal ambil {label}: {e}")
                return None

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # 5a. Checklist Bab II (halaman pembuka) -> PDF
            checklist_html = templates.env.get_template("bab2_checklist.html").render(
                product=product,
                company=company
                )
            checklist_buffer = io.BytesIO()
            checklist_status = pisa.CreatePDF(src=checklist_html, dest=checklist_buffer)
            if not checklist_status.err:
                zf.writestr(f"{root_folder}/00_Checklist_Bab_II.pdf", checklist_buffer.getvalue())

            async with httpx.AsyncClient() as client:
                # 5b. SOP CPKB perusahaan (kalau ada)
                sop_bytes = await fetch_bytes(client, sop_url, f"SOP CPKB ({perusahaan})")
                if sop_bytes:
                    zf.writestr(f"{root_folder}/00_SOP_CPKB_{_safe_zip_name(perusahaan)}.pdf", sop_bytes)

                # 5c. Per bahan baku -> 1 subfolder isinya: Spesifikasi+Catatan, CoA, Halal, MSDS
                for idx, item in enumerate(materials_data, start=1):
                    material = item["material"]
                    batch = item["batch"]
                    nama_bahan = material.get("nama_dagang") or f"Bahan {idx}"
                    folder_name = f"{idx:02d}_{_safe_zip_name(nama_bahan)}"

                    # --- 1. Spesifikasi Standar: prioritas PDF asli dari supplier, fallback generate dari text ---
                    spec_sheet_url = material.get("spec_sheet_file_url")
                    if spec_sheet_url:
                        spec_bytes = await fetch_bytes(client, spec_sheet_url, f"PDF Spesifikasi Asli {nama_bahan}")
                    else:
                        spec_bytes = None

                    if spec_bytes:
                        zf.writestr(f"{root_folder}/{folder_name}/1_Spesifikasi_Bahan_Baku.pdf", spec_bytes)
                    else:
                        spec_html = templates.env.get_template("bab2_spec_block.html").render(item=item, index=idx)
                        spec_buffer = io.BytesIO()
                        spec_status = pisa.CreatePDF(src=spec_html, dest=spec_buffer)
                        if not spec_status.err:
                            zf.writestr(f"{root_folder}/{folder_name}/1_Spesifikasi_Bahan_Baku.pdf", spec_buffer.getvalue())
                        else:
                            print(f"[BAB II ZIP] Gagal generate blok Spesifikasi bahan baku {nama_bahan}")

                    # --- 2. Catatan Pemeriksaan Aktual: prioritas PDF laporan asli, fallback generate dari qc_results ---
                    qc_report_url = batch.get("qc_report_file_url") if batch else None
                    if qc_report_url:
                        qc_bytes = await fetch_bytes(client, qc_report_url, f"PDF Laporan Pemeriksaan {nama_bahan}")
                    else:
                        qc_bytes = None

                    if qc_bytes:
                        zf.writestr(f"{root_folder}/{folder_name}/2_Catatan_Pemeriksaan_Bahan_Baku.pdf", qc_bytes)
                    else:
                        qc_html = templates.env.get_template("bab2_qc_block.html").render(item=item, index=idx)
                        qc_buffer = io.BytesIO()
                        qc_status = pisa.CreatePDF(src=qc_html, dest=qc_buffer)
                        if not qc_status.err:
                            zf.writestr(f"{root_folder}/{folder_name}/2_Catatan_Pemeriksaan_Bahan_Baku.pdf", qc_buffer.getvalue())
                        else:
                            print(f"[BAB II ZIP] Gagal generate blok Catatan Pemeriksaan bahan baku {nama_bahan}")

                    coa_url = batch.get("coa_file_url") if batch else None
                    halal_url = batch.get("halal_batch_file_url") if batch else None
                    msds_url = material.get("msds_file_url")

                    coa_bytes = await fetch_bytes(client, coa_url, f"CoA bahan baku {nama_bahan}")
                    if coa_bytes:
                        zf.writestr(f"{root_folder}/{folder_name}/3_CoA.pdf", coa_bytes)

                    halal_bytes = await fetch_bytes(client, halal_url, f"Sertifikat Halal bahan baku {nama_bahan}")
                    if halal_bytes:
                        zf.writestr(f"{root_folder}/{folder_name}/4_Sertifikat_Halal.pdf", halal_bytes)

                    msds_bytes = await fetch_bytes(client, msds_url, f"MSDS bahan baku {nama_bahan}")
                    if msds_bytes:
                        zf.writestr(f"{root_folder}/{folder_name}/5_MSDS.pdf", msds_bytes)

                    # Kasih catatan kalau ada dokumen yang belum diupload, biar ketauan pas dibuka foldernya
                    missing = []
                    if not coa_bytes:
                        missing.append("CoA")
                    if not halal_bytes:
                        missing.append("Sertifikat Halal")
                    if not msds_bytes:
                        missing.append("MSDS")
                    if missing:
                        note = "Dokumen berikut belum tersedia/gagal diunduh untuk bahan baku ini:\n- " + "\n- ".join(missing)
                        zf.writestr(f"{root_folder}/{folder_name}/PERHATIAN.txt", note)

        zip_buffer.seek(0)
        safe_name = _safe_zip_name(product.get("nama_produk") or "Produk").replace(" ", "_")
        filename = f"Bab2_Folder_{safe_name}.zip"

        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )


    # =====================================================================
    #           GENERATOR DOKUMEN BAB I (DATA ADMINISTRATIF, PDF GABUNGAN)
    # =====================================================================
    @app.get("/products/{product_id}/bab1/download")
    async def download_bab1_document(product_id: str, current_user: dict = Depends(get_current_user)):
        try:
            product_resp = supabase.table("products").select("*").eq("id", product_id).eq("is_deleted", False).single().execute()
        except Exception as e:
            # .single() melempar APIError kalau produk gak ketemu (URL rusak / produk terhapus) -> jangan 500
            print(f"Produk {product_id} tidak ditemukan, redirect ke dashboard: {e}")
            return RedirectResponse(url="/", status_code=303)

        if not product_resp.data:
            return RedirectResponse(url="/", status_code=303)

        product = product_resp.data

        perusahaan = product.get("perusahaan") or "PT Erfi"
        company = get_company_info(perusahaan)
        brand_id = product.get("brand_id")

        # 2. NIB & Sertifikat CPKB & Surat Tidak Pidana -> statis per PT
        nib_resp = supabase.table("nib_documents").select("file_url").eq("perusahaan", perusahaan).limit(1).execute()
        nib_url = nib_resp.data[0]["file_url"] if nib_resp.data else None

        cpkb_resp = supabase.table("sertifikat_cpkb_documents").select("file_url").eq("perusahaan", perusahaan).limit(1).execute()
        cpkb_url = cpkb_resp.data[0]["file_url"] if cpkb_resp.data else None

        pidana_resp = supabase.table("surat_tidak_pidana_documents").select("file_url").eq("perusahaan", perusahaan).limit(1).execute()
        pidana_url = pidana_resp.data[0]["file_url"] if pidana_resp.data else None

        # 3. Hak & Lisensi Merk -> dari brand yang di-link ke produk (kalau ada)
        # Sekarang ambil dari brand_legal_documents, filter by brand_id DAN perusahaan produk
        hak_merk_url = None
        if brand_id:
            doc_resp = supabase.table("brand_legal_documents") \
                .select("hak_lisensi_merk_file_url") \
                .eq("brand_id", brand_id) \
                .eq("perusahaan", perusahaan) \
                .limit(1).execute()
            if doc_resp.data:
                hak_merk_url = doc_resp.data[0].get("hak_lisensi_merk_file_url")

        # 4. Surat No. Notifikasi BPOM -> langsung dari kolom produk
        notifikasi_url = product.get("no_notifikasi_file_url")

        status = {
            "nib": bool(nib_url),
            "cpkb": bool(cpkb_url),
            "hak_merk": bool(hak_merk_url),
            "tidak_pidana": bool(pidana_url),
            "notifikasi": bool(notifikasi_url)
        }

        # 5. Render Checklist jadi PDF
        checklist_html = templates.env.get_template("bab1_checklist.html").render(
            product=product,
            status=status,
            company=company
            )
        checklist_buffer = io.BytesIO()
        checklist_status = pisa.CreatePDF(src=checklist_html, dest=checklist_buffer)
        if checklist_status.err:
            raise HTTPException(status_code=500, detail="Gagal generate halaman Checklist Bab I.")
        checklist_buffer.seek(0)

        # 6. Gabung sesuai urutan: Checklist -> NIB -> Sertifikat CPKB -> Hak & Lisensi Merk -> Surat Tidak Pidana -> Surat No. Notifikasi BPOM
        writer = PdfWriter()
        for page in PdfReader(checklist_buffer).pages:
            writer.add_page(page)

        async def append_pdf_from_url(client: httpx.AsyncClient, url: str, label: str):
            if not url:
                return
            try:
                resp = await client.get(url, timeout=30)
                resp.raise_for_status()
                reader = PdfReader(io.BytesIO(resp.content))
                for page in reader.pages:
                    writer.add_page(page)
            except Exception as e:
                print(f"Gagal ambil {label}: {e}")

        async with httpx.AsyncClient() as client:
            await append_pdf_from_url(client, nib_url, f"NIB ({perusahaan})")
            await append_pdf_from_url(client, cpkb_url, f"Sertifikat CPKB ({perusahaan})")
            await append_pdf_from_url(client, hak_merk_url, "Hak & Lisensi Merk")
            await append_pdf_from_url(client, pidana_url, f"Surat Tidak Pidana ({perusahaan})")
            await append_pdf_from_url(client, notifikasi_url, "Surat No. Notifikasi BPOM")

        output_buffer = io.BytesIO()
        writer.write(output_buffer)
        output_buffer.seek(0)

        safe_name = "".join(c for c in (product.get("nama_produk") or "Produk") if c.isalnum() or c in (" ", "-", "_")).strip()
        filename = f"Bab1_{safe_name.replace(' ', '_')}.pdf"

        return StreamingResponse(
            output_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    @app.get("/products/{product_id}/bab3/download")
    async def download_dip_bab3(
        product_id: str,
        current_user: dict = Depends(get_current_user)
    ):
        # 1. AMBIL DATA PRODUK
        try:
            prod_resp = supabase.table("products").select("*, brands(name)").eq("id", product_id).eq("is_deleted", False).single().execute()
        except Exception as e:
            # .single() melempar APIError kalau produk gak ketemu (URL rusak / produk terhapus) -> jangan 500
            print(f"Produk {product_id} tidak ditemukan, redirect ke dashboard: {e}")
            return RedirectResponse(url="/", status_code=303)

        if not prod_resp.data:
            return RedirectResponse(url="/", status_code=303)

        product = prod_resp.data
        if not product:
            raise HTTPException(status_code=404, detail="Produk kagak ketemu men!")

        perusahaan = product.get("perusahaan", "PT Erfi")
        company = get_company_info(perusahaan)

        # 2. AMBIL DATA FORMULA KUALITATIF & KUANTITATIF (POIN 1)
        # Catatan: nama tabel yang bener "raw_material_components" (bukan "compositions"),
        # dan kolom persentase-nya "percent_internal" -- ini yang dipakai konsisten di
        # seluruh app (Formula Builder, Ingredient Report, Bab II).
        formula_resp = supabase.table("product_formula_lines") \
            .select(
                "percent_in_formula, variant_id, "
                "raw_materials(*, raw_material_components(*), "
                "raw_material_composition_variants(*, raw_material_components(*)))"
            ) \
            .eq("product_id", product_id) \
            .execute()

        raw_formula = formula_resp.data if formula_resp.data else []
        processed_formula = []

        for line in raw_formula:
            rm = line.get("raw_materials") or {}
            percent_total = float(line.get("percent_in_formula") or 0)
            compositions = _resolve_variant_components(rm, line.get("variant_id"))

            if compositions and len(compositions) > 0:
                comp_list = []
                for comp in compositions:
                    pct_in_rm = float(comp.get("percent_internal") or 100)
                    calc_pct = round((pct_in_rm / 100.0) * percent_total, 4)
                    comp_list.append({
                        "ingredient": comp.get("inci_name") or "-",
                        "function": comp.get("function") or "-",
                        "percent": calc_pct,
                        "is_bahan_aktif": bool(comp.get("is_bahan_aktif")),
                    })
                processed_formula.append({
                    "nama_dagang": rm.get("nama_dagang") or "-",
                    "kode": rm.get("kode_bahan_baku") or "-",
                    "row_span": len(comp_list),
                    "compositions": comp_list
                })
            else:
                processed_formula.append({
                    "nama_dagang": rm.get("nama_dagang") or "-",
                    "kode": rm.get("kode_bahan_baku") or "-",
                    "row_span": 1,
                    "compositions": [{
                        "ingredient": rm.get("nama_dagang") or "-",
                        "function": "-",
                        "percent": percent_total,
                        # Bahan tanpa komponen tidak punya penanda bahan aktif di
                        # DB (kolomnya hanya ada di raw_material_components) —
                        # konsisten dengan Qual-Quan & export Excel.
                        "is_bahan_aktif": False,
                    }]
                })

        # 3. AMBIL SOP MASTER PERUSAHAAN (POIN 3 & 8) - Safe Fallback
        company_sop = {}
        try:
            sop_resp = supabase.table("company_sop_documents").select("*").eq("perusahaan", perusahaan).execute()
            if sop_resp.data and len(sop_resp.data) > 0:
                company_sop = sop_resp.data[0]
        except Exception as e:
            print(f"[WARNING] Gagal/belum ada data company_sop_documents: {e}")

        # 4. AMBIL BATCH PRODUK JADI TERBARU (POIN 5) - Safe Fallback
        latest_batch = {}
        try:
            batch_resp = supabase.table("product_batches") \
                .select("*") \
                .eq("product_id", product_id) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()
            if batch_resp.data and len(batch_resp.data) > 0:
                latest_batch = batch_resp.data[0]
        except Exception as e:
            print(f"[WARNING] Gagal/belum ada data product_batches: {e}")

        # NEW: Fetch Finished Product Specification (for dynamic PDF generation and checklist status)
        finished_spec = None
        try:
            spec_res = supabase.table("product_finished_specs").select("*").eq("product_id", product_id).execute()
            if spec_res.data:
                finished_spec = spec_res.data[0]
        except Exception as e:
            print(f"[WARNING] Gagal/belum ada data product_finished_specs: {e}")

        # 5. RENDER COVER & FORMULA VIA TEMPLATE HTML
        # Total % w/w dihitung di sini (bukan di template) supaya angkanya pasti
        # konsisten dengan penjumlahan baris tabel.
        formula_total_percent = round(
            sum(float(c.get("percent") or 0)
                for item in processed_formula
                for c in item.get("compositions") or []),
            4,
        )
        template = templates.get_template("bab3_checklist.html")
        rendered_html = template.render({
            "product": product,
            "perusahaan": perusahaan,
            "company": {**company, "logo_width": _logo_render_width(company.get("logo"))},
            "company_sop": company_sop,
            "latest_batch": latest_batch,
            "processed_formula": processed_formula,
            "formula_total_percent": formula_total_percent,
            "kop_image": _kop_image(company),
            "finished_spec": finished_spec, # Pass finished_spec to template
        })

        cover_pdf_io = io.BytesIO()
        pisa_status = pisa.CreatePDF(
            io.StringIO(rendered_html),
            dest=cover_pdf_io,
            link_callback=_pdf_link_callback
        )
        if pisa_status.err:
            print(f"[BAB 3 WARNING] Ada error saat render cover PDF: {pisa_status.err}")
        cover_pdf_io.seek(0)

        # 6. MERGE WITH ATTACHMENTS
        pdf_writer = PdfWriter()
        cover_reader = PdfReader(cover_pdf_io)
        for page in cover_reader.pages:
            pdf_writer.add_page(page)

        # Generate finished spec PDF bytes if finished_spec data exists
        finished_spec_pdf_bytes = None
        if finished_spec:
            try:
                tanggal_disetujui_formatted = format_date_id(finished_spec["tanggal_disetujui"]) if finished_spec.get("tanggal_disetujui") else "-"
                for section in finished_spec.get("sections", []):
                    rows = section.get("rows", [])
                    if not rows: continue
                    grouped_rows = []
                    i = 0
                    while i < len(rows):
                        current_row = rows[i]
                        metode = current_row.get("metode", "")
                        rowspan = 1
                        j = i + 1
                        while j < len(rows) and rows[j].get("metode") == metode and metode != "" and metode != "-":
                            rowspan += 1
                            j += 1
                        current_row["rowspan"] = rowspan
                        grouped_rows.append(current_row)
                        for k in range(i + 1, j):
                            rows[k]["skip_metode"] = True
                            grouped_rows.append(rows[k])
                        i = j
                    section["rows"] = grouped_rows

                spec_context = {
                    "product": product,
                    "spec": finished_spec,
                    "company": {**company, "logo_width": _logo_render_width(company.get("logo"))},
                    "tanggal_disetujui_formatted": tanggal_disetujui_formatted,
                }
                spec_template = templates.env.get_template("finished_spec_pdf.html")
                spec_html_out = spec_template.render(spec_context)
                spec_pdf = pisa.CreatePDF(
                    io.BytesIO(spec_html_out.encode("UTF-8")),
                    link_callback=_pdf_link_callback,
                    encoding="UTF-8"
                )
                if not spec_pdf.err:
                    finished_spec_pdf_bytes = spec_pdf.dest.getvalue()
            except Exception as e:
                print(f"[BAB 3 FINISHED SPEC PDF ERROR] Gagal generate spek produk jadi: {e}")

        # Poin 5 (SAPJ) dan 6a (SPJ): untuk PT Erfi, SAPJ pakai PDF hasil generate finished_spec,
        # SPJ pakai file upload manual. Untuk perusahaan lain (PT Heka), keduanya pakai file
        # upload manual yang sama (dokumen gabungan lama), sengaja dilampirkan dua kali supaya
        # urutan halaman tetap sejajar dengan urutan item checklist 5 dan 6a.
        if perusahaan == 'PT Erfi':
            poin5_sapj = finished_spec_pdf_bytes
            poin6a_spj = product.get("spek_produk_jadi_file_url")
        else:
            poin5_sapj = product.get("spek_produk_jadi_file_url")
            poin6a_spj = None  

        attachments = [
            product.get("cara_pembuatan_file_url"),              # Poin 2
            company_sop.get("protap_no_batch_url"),              # Poin 3
            product.get("sistem_penomoran_batch_file_url"),      # Poin 4
            poin5_sapj,                                           # Poin 5 (SAPJ)
            poin6a_spj,                                           # Poin 6a (SPJ)
            product.get("spek_pengemas_file_url"),               # Poin 6b
            product.get("laporan_uji_sig_file_url"),             # Poin 7
            company_sop.get("protap_pemeriksaan_fg_url"),        # Poin 8
            product.get("protokol_stabilitas_file_url"),         # Poin 9
            product.get("hasil_stabilitas_file_url"),            # Poin 10
        ]

        async with httpx.AsyncClient() as client:
            for item in attachments:
                if not item:
                    continue
                try:
                    if isinstance(item, bytes):
                        doc_reader = PdfReader(io.BytesIO(item))
                        for page in doc_reader.pages:
                            pdf_writer.add_page(page)
                    elif isinstance(item, str) and item.startswith("http"):
                        res = await client.get(item, timeout=15.0)
                        if res.status_code == 200:
                            doc_reader = PdfReader(io.BytesIO(res.content))
                            for page in doc_reader.pages:
                                pdf_writer.add_page(page)
                except Exception as e:
                    print(f"[BAB 3 MERGE ERROR] Gagal memproses attachment: {e}")

        output_pdf_io = io.BytesIO()
        pdf_writer.write(output_pdf_io)
        output_pdf_io.seek(0)

        safe_product_name = "".join([c for c in product.get('nama_produk', 'Produk') if c.isalnum() or c in (' ', '_')]).rstrip()
        filename = f"DIP_Bab_3_{safe_product_name}.pdf"

        return Response(
            content=output_pdf_io.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )


    @app.get("/products/{product_id}/bab3/preview")
    async def preview_dip_bab3(product_id: str, current_user: dict = Depends(get_current_user)):
        # Preview Bab 3: generate PDF yang sama persis dengan /bab3/download, tapi disajikan
        # inline (browser menampilkan preview di tab baru) -- bukan force-download.
        resp = await download_dip_bab3(product_id, current_user)
        resp.headers["Content-Disposition"] = resp.headers["Content-Disposition"].replace("attachment", "inline")
        return resp


    @app.get("/products/{product_id}/bab4/download")
    async def download_dip_bab4(
        product_id: str,
        current_user: dict = Depends(get_current_user)
    ):
        # 1. AMBIL DATA PRODUK & PERUSAHAAN
        try:
            prod_resp = supabase.table("products").select("*, brands(name)").eq("id", product_id).eq("is_deleted", False).single().execute()
        except Exception as e:
            # .single() melempar APIError kalau produk gak ketemu (URL rusak / produk terhapus) -> jangan 500
            print(f"Produk {product_id} tidak ditemukan, redirect ke dashboard: {e}")
            return RedirectResponse(url="/", status_code=303)

        if not prod_resp.data:
            return RedirectResponse(url="/", status_code=303)

        product = prod_resp.data
        if not product:
            raise HTTPException(status_code=404, detail="Produk kagak ketemu men!")

        perusahaan = product.get("perusahaan", "PT Erfi")
        company = get_company_info(perusahaan)

        # 2. AMBIL SOP MASTER PERUSAHAAN
        company_sop = {}
        try:
            sop_resp = supabase.table("company_sop_documents").select("*").eq("perusahaan", perusahaan).execute()
            if sop_resp.data and len(sop_resp.data) > 0:
                company_sop = sop_resp.data[0]
        except Exception as e:
            print(f"[WARNING] Gagal/belum ada data company_sop_documents: {e}")

        # 3. HITUNG KOMPOSISI INCI MURNI (TEXT DESIGN)
        komposisi_text = "-"
        try:
            formula_resp = supabase.table("product_formula_lines") \
                .select(
                    "percent_in_formula, variant_id, "
                    "raw_materials(nama_dagang, raw_material_components(*), "
                    "raw_material_composition_variants(*, raw_material_components(*)))"
                ) \
                .eq("product_id", product_id) \
                .execute()

            grouped_pure = {}
            for line in (formula_resp.data or []):
                pct_in_formula = float(line.get("percent_in_formula") or 0)
                rm = line.get("raw_materials") or {}
                components = _resolve_variant_components(rm, line.get("variant_id"))

                if components:
                    for comp in components:
                        inci_name = comp.get("inci_name") or "-"
                        pct_internal = float(comp.get("percent_internal") or 100)
                        abs_pct = (pct_in_formula * pct_internal) / 100.0
                        if inci_name not in grouped_pure:
                            grouped_pure[inci_name] = Decimal('0.0')
                        grouped_pure[inci_name] += Decimal(str(abs_pct))
                else:
                    nama_dagang = rm.get("nama_dagang") or "Unknown"
                    if nama_dagang not in grouped_pure:
                        grouped_pure[nama_dagang] = Decimal('0.0')
                    grouped_pure[nama_dagang] += Decimal(str(pct_in_formula))

            sorted_inci = sorted(grouped_pure.items(), key=lambda x: x[1], reverse=True)
            komposisi_list = [item[0] for item in sorted_inci]
            if komposisi_list:
                komposisi_text = ", ".join(komposisi_list) + "."
        except Exception as e:
            print(f"[BAB 4 WARNING] Gagal kalkulasi komposisi Text Design: {e}")

        # 4. RENDER CHECKLIST BAB 4
        template = templates.get_template("bab4_checklist.html")
        rendered_html = template.render({
            "product": product,
            "perusahaan": perusahaan,
            "company": company,
            "company_sop": company_sop
        })

        cover_pdf_io = io.BytesIO()
        pisa.CreatePDF(io.StringIO(rendered_html), dest=cover_pdf_io)
        cover_pdf_io.seek(0)

        # 5. RENDER HALAMAN TEXT DESIGN PDF
        text_design_template = templates.get_template("text_design_block.html")
        text_design_rendered = text_design_template.render({
            "product": product,
            "company": company,
            "komposisi_text": komposisi_text
        })
        text_design_pdf_io = io.BytesIO()
        pisa.CreatePDF(io.StringIO(text_design_rendered), dest=text_design_pdf_io)
        text_design_pdf_io.seek(0)

        # 6. MERGE PDF COVER + LAMPIRAN BAB 4 (TEXT DESIGN MASUK SEBELUM DESAIN PRIMER)
        pdf_writer = PdfWriter()
        cover_reader = PdfReader(cover_pdf_io)
        for page in cover_reader.pages:
            pdf_writer.add_page(page)

        attachment_urls = [
            product.get("laporan_keamanan_file_url"),               # Poin 1
            company_sop.get("cv_safety_assessor_url"),              # Poin 2
            product.get("monitoring_efek_samping_file_url"), # Poin 3
            product.get("data_klaim_file_url"),                     # Poin 4
        ]

        async with httpx.AsyncClient() as client:
            # Append Lampiran Poin 1-4
            for url in attachment_urls:
                if url:
                    try:
                        res = await client.get(url, timeout=15.0)
                        if res.status_code == 200:
                            doc_reader = PdfReader(io.BytesIO(res.content))
                            for page in doc_reader.pages:
                                pdf_writer.add_page(page)
                    except Exception as e:
                        print(f"[BAB 4 MERGE ERROR] Gagal mengunduh {url}: {e}")

            # APPEND TEXT DESIGN (SEBELUM DESAIN KEMASAN PRIMER)
            text_design_reader = PdfReader(text_design_pdf_io)
            for page in text_design_reader.pages:
                pdf_writer.add_page(page)

            # Append Desain Kemasan Primer & Sekunder
            design_urls = [
                product.get("desain_primer_file_url"),              # Poin 5a / 6a
                product.get("desain_sekunder_file_url"),            # Poin 5b / 6b
            ]
            for url in design_urls:
                if url:
                    try:
                        res = await client.get(url, timeout=15.0)
                        if res.status_code == 200:
                            doc_reader = PdfReader(io.BytesIO(res.content))
                            for page in doc_reader.pages:
                                pdf_writer.add_page(page)
                    except Exception as e:
                        print(f"[BAB 4 MERGE ERROR] Gagal mengunduh {url}: {e}")

        output_pdf_io = io.BytesIO()
        pdf_writer.write(output_pdf_io)
        output_pdf_io.seek(0)

        safe_product_name = "".join([c for c in product.get('nama_produk', 'Produk') if c.isalnum() or c in (' ', '_')]).rstrip()
        filename = f"DIP_Bab_4_{safe_product_name}.pdf"

        return Response(
            content=output_pdf_io.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )


    @app.get("/products/{product_id}/bab4/preview")
    async def preview_dip_bab4(product_id: str, current_user: dict = Depends(get_current_user)):
        # Preview Bab 4: generate PDF yang sama persis dengan /bab4/download, tapi disajikan
        # inline (browser menampilkan preview di tab baru) -- bukan force-download.
        resp = await download_dip_bab4(product_id, current_user)
        resp.headers["Content-Disposition"] = resp.headers["Content-Disposition"].replace("attachment", "inline")
        return resp
    # Dipakai app/main.py untuk meneruskan generator ke app/dip_public.py.
    return {
        "bab1": download_bab1_document,
        "bab2": download_bab2_document,
        "bab3": download_dip_bab3,
        "bab4": download_dip_bab4,
        "bab2_zip": download_bab2_document_zip,
    }
