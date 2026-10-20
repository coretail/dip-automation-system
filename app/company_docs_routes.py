"""Company document management routes (extracted from main.py)."""
from __future__ import annotations

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app import object_store
from app.file_validation import validate_pdf_bytes


def register_company_docs_routes(
    app,
    get_current_user,
    supabase,
    templates,
    log_activity,
    get_ed_notification_count,
):
    COMPANY_DOC_MAP = {
        "nib":                     ("nib_documents",                "file_url",                            "legal-documents",    "company-docs/{doc_type}_{slug}.pdf"),
        "sertifikat_cpkb":         ("sertifikat_cpkb_documents",    "file_url",                            "legal-documents",    "company-docs/{doc_type}_{slug}.pdf"),
        "surat_tidak_pidana":      ("surat_tidak_pidana_documents", "file_url",                            "legal-documents",    "company-docs/{doc_type}_{slug}.pdf"),
        "protap_no_batch":         ("company_sop_documents",        "protap_no_batch_url",                 "legal-documents",    "company-docs/{doc_type}_{slug}.pdf"),
        "protap_pemeriksaan_fg":   ("company_sop_documents",        "protap_pemeriksaan_fg_url",           "legal-documents",    "company-docs/{doc_type}_{slug}.pdf"),
        "cv_safety_assessor":      ("company_sop_documents",        "cv_safety_assessor_url",              "legal-documents",    "company-docs/{doc_type}_{slug}.pdf"),
        "cpkb_raw_material":       ("cpkb_raw_material",            "file_url",                            "raw-material-docs",  "sop-cpkb/sop_cpkb_{slug}.pdf"),
    }

    # Label tampilan tiap doc_type (urutan menentukan urutan baris di tabel)
    COMPANY_DOC_LABELS = {
        "nib":                     "NIB",
        "sertifikat_cpkb":         "Sertifikat CPKB",
        "surat_tidak_pidana":      "Surat Tidak Pidana",
        "protap_no_batch":         "Protap No. Batch",
        "protap_pemeriksaan_fg":   "Protap Pemeriksaan Produk Jadi",
        "cv_safety_assessor":      "CV Safety Assessor",
        "cpkb_raw_material":       "SOP CPKB Pemeriksaan Bahan Baku",
    }


    @app.get("/admin/company-documents", response_class=HTMLResponse)
    async def admin_company_documents_page(request: Request, current_user: dict = Depends(get_current_user)):
        if current_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak")

        companies = ["PT Erfi", "PT Heka"]
        # docs[perusahaan][doc_type] = url_or_None
        docs = {c: {} for c in companies}

        # Ambil data per tabel (1 baris per perusahaan)
        for doc_type, (table, column, _, _) in COMPANY_DOC_MAP.items():
            try:
                resp = supabase.table(table).select("perusahaan, " + column).execute()
                by_company = {row.get("perusahaan"): row for row in (resp.data or [])}
                for c in companies:
                    row = by_company.get(c)
                    docs[c][doc_type] = (row or {}).get(column) if row else None
            except Exception as e:
                print(f"[COMPANY DOCS] Gagal ambil {table}/{column}: {e}")
                for c in companies:
                    docs[c].setdefault(doc_type, None)

        return templates.TemplateResponse(
            request=request,
            name="admin_company_documents.html",
            context={
                "docs": docs,
                "doc_labels": COMPANY_DOC_LABELS,
                "current_user": current_user,
                "ed_notification_count": await get_ed_notification_count(),
            }
        )


    @app.post("/admin/company-documents/update")
    async def update_company_document(
        request: Request,
        doc_type: str = Form(...),
        perusahaan: str = Form(...),
        file: UploadFile = File(...),
        current_user: dict = Depends(get_current_user)
    ):
        if current_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Akses ditolak")

        # Validasi doc_type & perusahaan
        mapping = COMPANY_DOC_MAP.get(doc_type)
        if not mapping:
            response = RedirectResponse(url="/admin/company-documents", status_code=303)
            response.set_cookie("error_msg", f"Jenis dokumen '{doc_type}' tidak dikenal.")
            return response
        if perusahaan not in ("PT Erfi", "PT Heka"):
            response = RedirectResponse(url="/admin/company-documents", status_code=303)
            response.set_cookie("error_msg", "Perusahaan tidak valid. Harus PT Erfi atau PT Heka.")
            return response

        table, column, bucket, path_template = mapping
        label = COMPANY_DOC_LABELS.get(doc_type, doc_type)
        company_slug = "erfi" if perusahaan == "PT Erfi" else "heka"

        try:
            file_bytes = await file.read()
            _err = validate_pdf_bytes(file_bytes, label)
            if _err:
                response = RedirectResponse(url="/admin/company-documents", status_code=303)
                response.set_cookie("error_msg", _err)
                return response

            path = path_template.format(doc_type=doc_type, slug=company_slug)
            object_store.upload_pdf(bucket, path, file_bytes, client=supabase)
            file_url = object_store.public_url(bucket, path, client=supabase)

            # Upsert 1 baris per perusahaan:
            # - 3 tabel pertama (nib_documents, sertifikat_cpkb_documents,
            #   surat_tidak_pidana_documents) punya kolom file_url -> update kolom itu.
            # - company_sop_documents punya 4 kolom berbeda -> UPDATE HANYA kolom spesifik,
            #   jangan overwrite kolom lain (protap_no_batch_url, dll).
            existing = supabase.table(table).select("id").eq("perusahaan", perusahaan).limit(1).execute()
            if existing.data:
                supabase.table(table).update({column: file_url}).eq("perusahaan", perusahaan).execute()
            else:
                supabase.table(table).insert({"perusahaan": perusahaan, column: file_url}).execute()

            log_activity(current_user, "update", doc_type, perusahaan,
                         f"{label} {perusahaan}", request=request)

            response = RedirectResponse(url="/admin/company-documents", status_code=303)
            response.set_cookie("success_msg", f"{label} ({perusahaan}) berhasil diperbarui.")
            return response

        except Exception as e:
            print(f"[COMPANY DOCS] Gagal update {doc_type} ({perusahaan}): {e}")
            response = RedirectResponse(url="/admin/company-documents", status_code=303)
            response.set_cookie("error_msg", f"Gagal upload {label}. Coba lagi.")
            return response


