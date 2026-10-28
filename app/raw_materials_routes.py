"""Route /raw-materials/* (master bahan baku, varian komposisi, batch/ED, dokumen company)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import timedelta
from typing import List
from uuid import uuid4

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from httpx import HTTPStatusError
from postgrest.exceptions import APIError

from app.database import supabase
from app.file_validation import validate_pdf_bytes
from app import object_store


def _sort_rm_components(components: list) -> list:
    """Urutkan komponen deterministik: percent_internal desc, lalu inci_name."""
    def _to_decimal(value):
        if value is None:
            return Decimal("0")
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal("0")

    return sorted(
        [c for c in components if isinstance(c, dict)],
        key=lambda c: (-_to_decimal(c.get("percent_internal")), str(c.get("inci_name") or "")),
    )


def _is_deleted_product(embedded):
    """Cek apakah embed relasi produk sudah soft-delete.

    supabase-py bisa mengembalikan embed many-to-one sebagai dict ATAU list,
    jadi keduanya ditangani di sini. Embed yang kosong dianggap tidak terhapus
    (produk tidak punya soft-delete, jadi kasus ini hanya jaga-jaga).
    """
    if isinstance(embedded, list):
        embedded = embedded[0] if embedded else None
    return bool((embedded or {}).get("is_deleted"))


def _cleanup_uploaded_objects(paths: list, bucket: str = "raw-material-docs") -> tuple[bool, list]:
    """Hapus objek storage yang BARU dibuat satu operasi dari semua backend.

    Aman hanya untuk path yang unik per operasi (sufiks uuid4): objek dengan
    path seperti itu dijamin tidak ada sebelum operasi ini, jadi menghapus-nya
    tidak mungkin menimpa file milik batch lain.

    Return (semua_berhasil, daftar_path_yang_gagal).
    """
    failed: list = []
    for path in paths:
        try:
            result = object_store.remove_from_all_backends(bucket, path, client=supabase)
        except Exception as exc:
            print(f"[RAW MATERIALS] Gagal hapus object {path}: {exc}")
            failed.append(path)
            continue
        for backend, backend_result in (result or {}).items():
            if backend_result.get("ok") or backend_result.get("missing"):
                continue
            print(
                f"[RAW MATERIALS] Gagal hapus object {path} di backend {backend}: "
                f"{backend_result.get('error')}"
            )
            failed.append(path)
            break
    return (not failed), failed


class _BatchUpdateAffectedNoRow(Exception):
    """UPDATE batch tidak menyentuh baris mana pun (batch hilang/terhapus)."""


# Label dokumen per kolom URL di raw_material_batches (dipakai untuk pesan
# flash dan audit trail).
DOC_FIELD_LABELS = {
    "coa_file_url": "CoA",
    "halal_batch_file_url": "Halal",
    "qc_report_file_url": "Laporan Pemeriksaan",
}


def _count_url_references(table: str, column: str, url: str, exclude_id: str | None = None) -> tuple[int, str | None]:
    """Hitung baris lain yang masih menunjuk URL objek storage yang sama.

    Dipakai sebelum menghapus file lama: path warisan (mis.
    ``coa/coa_{batch}.pdf``) bisa dipakai lebih dari satu batch, jadi objek
    tidak boleh dihapus selama masih dirujuk baris lain.

    Return (jumlah_referensi, nama_tabel_yang_gagal_cek). Kalau query gagal,
    jumlah = -1 yang berarti TIDAK bisa dibuktikan bebas pakai -> pemanggil
    tidak boleh menghapus objek.
    """
    try:
        # Filter memakai builder resmi library (`.in_`) supaya nilai URL
        # diurai sebagai SATU nilai: `.in_` membungkus nilai yang memuat
        # karakter khusus PostgREST (`,:()`) di dalam tanda kutip, sedangkan
        # `.eq` menempelkan nilai mentah ke string filter.
        query = supabase.table(table).select("id").in_(column, [url])
        if exclude_id:
            query = query.neq("id", exclude_id)
        resp = query.execute()
        return len(resp.data or []), None
    except Exception as exc:
        print(f"[RAW MATERIALS] Gagal cek referensi {table}.{column}: {exc}")
        return -1, f"{table}.{column}"


def _cleanup_replaced_objects(batch_id: str, old_doc_urls: dict, new_doc_urls: dict) -> tuple[list, list]:
    """Hapus objek storage lama yang digantikan, kalau memang tidak dirujuk lagi.

    File lama TIDAK boleh langsung dihapus: path warisan (mis.
    ``coa/coa_{batch}.pdf``) bisa dipakai lebih dari satu batch, bahkan oleh
    baris ``product_batches``. Jadi sebelum dihapus, objek dicek dulu: masih
    ada baris lain yang menunjuk URL yang sama? Kalau ada, file dibiarkan.

    Return (perubahan_untuk_audit, pesan_peringatan_untuk_user).
    """
    changes: list = []
    warnings: list = []
    for column, label in DOC_FIELD_LABELS.items():
        old_url = (old_doc_urls or {}).get(column)
        new_url = (new_doc_urls or {}).get(column)
        if not old_url or not new_url or old_url == new_url:
            continue
        bucket, path = object_store.parse_storage_url(old_url)
        if not bucket or not path:
            print(f"[RAW MATERIALS] URL lama {label} tidak bisa diparse, file tidak dihapus: {old_url}")
            changes.append({
                "field": label,
                "note": "file lama tidak bisa diparse, jadi tidak dihapus dari storage",
            })
            warnings.append(f"File lama {label} tidak bisa diparse, jadi tidak dihapus.")
            continue
        # Objek yang sama bisa ditunjuk dari kolom lain atau tabel lain, jadi
        # SEMUA kombinasi dicek: file lama tidak boleh dihapus selama masih
        # dirujuk baris lain.
        refs, ref_error = _count_url_references(
            "raw_material_batches", column, old_url, exclude_id=batch_id
        )
        if refs <= 0:
            for kolom_lain in DOC_FIELD_LABELS:
                if kolom_lain == column:
                    continue
                refs_lain, err_lain = _count_url_references(
                    "raw_material_batches", kolom_lain, old_url, exclude_id=batch_id
                )
                if refs_lain > 0:
                    refs = refs_lain
                    break
                if err_lain:
                    ref_error = ref_error or err_lain
        if refs <= 0 and column == "coa_file_url":
            # CoA warisan (coa/coa_{batch}.pdf) bisa juga ditunjuk baris
            # product_batches, jadi ikut dicek sebelum dihapus.
            product_refs, product_error = _count_url_references("product_batches", column, old_url)
            if product_refs > 0:
                refs = product_refs
            elif product_error:
                ref_error = ref_error or product_error
        if ref_error:
            changes.append({
                "field": label,
                "note": "referensi file lama tidak bisa dicek, jadi file tidak dihapus dari storage",
            })
            warnings.append(f"Referensi file lama {label} tidak bisa dicek, jadi file tidak dihapus.")
            continue
        if refs > 0:
            changes.append({
                "field": label,
                "note": "file lama masih dipakai batch lain, jadi tidak dihapus dari storage",
            })
            warnings.append(f"File lama {label} masih dipakai batch lain, jadi tidak dihapus.")
            continue
        gagal_hapus = False
        try:
            remove_result = object_store.remove_from_all_backends(bucket, path, client=supabase)
            gagal_hapus = bool(object_store.failed_backends(remove_result))
            if gagal_hapus:
                print(
                    f"[RAW MATERIALS] File lama {label} gagal dihapus di backend: "
                    f"{', '.join(object_store.failed_backends(remove_result))}"
                )
        except Exception as exc:
            gagal_hapus = True
            print(f"[RAW MATERIALS] Gagal hapus file lama {label} ({path}): {exc}")
        if gagal_hapus:
            changes.append({
                "field": label,
                "note": "file lama gagal dihapus dari storage; detail ada di log server",
            })
            warnings.append(
                f"File lama {label} gagal dihapus dari storage - administrator perlu memeriksa storage."
            )
    return changes, warnings


# ---------------------------------------------------------------------------
# Klasifikasi kegagalan tulis ke database
# ---------------------------------------------------------------------------
# Tiga kemungkinan hasil saat menulis ke database:
#   1. Pasti ditolak - server menerima permintaan lalu membalas HTTP error.
#      Tulisan TIDAK terjadi, jadi objek yang baru diunggah aman dihapus.
#   2. Ambigu tapi terkonfirmasi tersimpan - respons database hilang (timeout,
#      koneksi putus), tapi query rekonsiliasi menemukan URL baru di database.
#      Datanya sudah tersimpan, jadi objek DIPERTAHANKAN dan hasilnya sukses.
#   3. Ambigu dan belum pasti - respons hilang dan URL baru tidak ditemukan
#      (atau query rekonsiliasinya sendiri gagal). Objek DIPERTAHANKAN dan
#      path-nya dicatat di activity log untuk rekonsiliasi manual.
KEGAGALAN_PASTI_DITOLAK = "pasti_ditolak"
KEGAGALAN_AMBIGU = "ambigu"

REKONSILIASI_DITEMUKAN = "ditemukan"
REKONSILIASI_TIDAK_DITEMUKAN = "tidak_ditemukan"
REKONSILIASI_GAGAL_CEK = "gagal_cek"


def _status_http_dari_exception(exc: BaseException) -> int | None:
    """Ambil status HTTP dari exception database, kalau ada.

    * ``httpx.HTTPStatusError`` membawa ``response.status_code``.
    * ``postgrest.exceptions.APIError`` dari error PostgREST yang asli punya
      ``code`` berupa string SQLSTATE/PGRST (mis. ``23505``, ``PGRST116``)
      -> bukan status HTTP, jadi dikembalikan ``None``. Tetapi kalau body
      error BUKAN JSON PostgREST (mis. halaman HTML dari gateway/proxy),
      library membuat ``APIError`` generik dengan ``code`` = status HTTP
      (``generate_default_error_message`` di ``postgrest/exceptions.py``).
    """
    if isinstance(exc, HTTPStatusError):
        return getattr(getattr(exc, "response", None), "status_code", None)
    kode = getattr(exc, "code", None)
    if isinstance(kode, int):
        return kode
    if isinstance(kode, str) and len(kode) == 3 and kode.isdigit():
        return int(kode)
    return None


def _klasifikasi_kegagalan_db(exc: BaseException) -> str:
    """Tentukan kegagalan database itu pasti ditolak atau ambigu.

    Dasarnya TIPE exception dan status HTTP, bukan pencocokan teks pesan:

    * ``postgrest.exceptions.APIError`` dilempar client PostgREST ketika
      server membalas HTTP error (lihat ``SyncQueryRequestBuilder.execute``
      di ``postgrest/_sync/request_builder.py``). Server sudah menerima dan
      menolak permintaan, jadi tulisannya tidak terjadi.
    * ``httpx.HTTPStatusError`` = server membalas status HTTP error, bukan
      kegagalan transport, jadi juga pasti ditolak.
    * PENGECUALIAN: status 5xx yang datang dari gateway/proxy (body bukan
      JSON PostgREST, mis. 502/503/504) TIDAK membuktikan tulisan gagal -
      database bisa saja sudah commit sebelum gateway menyerah -> ambigu.
      Error PostgREST asli (``code`` SQLSTATE/PGRST) tetap pasti ditolak
      karena transaksinya di-rollback.
    * ``httpx.HTTPError`` (timeout/connect/read/write/protocol/network) dan
      exception lain = permintaan mungkin sudah diterapkan di server, tapi
      responsnya tidak sampai -> ambigu.
    """
    if isinstance(exc, (APIError, HTTPStatusError)):
        status = _status_http_dari_exception(exc)
        if status is not None and status >= 500:
            return KEGAGALAN_AMBIGU
        return KEGAGALAN_PASTI_DITOLAK
    return KEGAGALAN_AMBIGU


def _rekonsiliasi_url_baru(new_doc_urls: dict) -> tuple[str, str | None]:
    """Cek apakah URL dokumen baru benar-benar sudah tersimpan di database.

    Dipakai HANYA di jalur error, ketika respons database hilang sehingga
    tidak diketahui apakah tulisan sudah diterapkan atau belum.

    Filternya dibangun lewat builder resmi library (``.in_``), bukan string
    PostgREST yang dirangkai tangan: ``postgrest`` membungkus nilai yang
    memuat karakter khusus PostgREST (``,:()``) di dalam tanda kutip,
    sehingga URL tetap diurai sebagai satu nilai utuh.

    Return: (status, id_baris_ditemukan).
    """
    target = [
        (column, (new_doc_urls or {}).get(column))
        for column in DOC_FIELD_LABELS
        if (new_doc_urls or {}).get(column)
    ]
    if not target:
        return REKONSILIASI_TIDAK_DITEMUKAN, None

    for column, url in target:
        # product_batches hanya punya kolom CoA; kolom Halal dan Laporan
        # Pemeriksaan hanya ada di raw_material_batches.
        if column == "coa_file_url":
            tabel = ("raw_material_batches", "product_batches")
        else:
            tabel = ("raw_material_batches",)
        for table in tabel:
            try:
                resp = (
                    supabase.table(table)
                    .select("id")
                    .in_(column, [url])
                    .limit(1)
                    .execute()
                )
            except Exception as exc:
                print(
                    f"[RAW MATERIALS] Gagal cek rekonsiliasi {table}.{column}: {exc}"
                )
                return REKONSILIASI_GAGAL_CEK, None
            if resp.data:
                return REKONSILIASI_DITEMUKAN, (resp.data[0] or {}).get("id")
    return REKONSILIASI_TIDAK_DITEMUKAN, None


def _rekonsiliasi_setelah_gagal(
    new_doc_urls: dict,
    uploaded_paths: list,
    *,
    pesan_tersimpan: str,
    pesan_belum_pasti: str,
) -> dict:
    """Ringkasan hasil rekonsiliasi setelah respons database hilang.

    Return dict berisi:
      - "status"    : "tersimpan" atau "belum_pasti"
      - "entity_id" : id baris yang ditemukan (None kalau belum pasti)
      - "catatan"   : catatan untuk audit trail
      - "pesan"     : pesan flash untuk user
      - "outcome"   : "success" atau "failed"

    Catatan penting: hasil query yang KOSONG bukan bukti pasti gagal -
    request-nya masih mungkin berjalan di server. Karena itu objek yang baru
    diunggah selalu DIPERTAHANKAN di jalur ini, dan path-nya dicatat di
    activity log supaya administrator bisa merekonsiliasi manual.
    """
    status_rek, id_ditemukan = _rekonsiliasi_url_baru(new_doc_urls)
    if status_rek == REKONSILIASI_DITEMUKAN:
        return {
            "status": "tersimpan",
            "entity_id": id_ditemukan,
            "catatan": (
                "respons database tidak diterima, tapi URL baru terverifikasi ada "
                "di database; file yang diunggah dipertahankan"
            ),
            "pesan": pesan_tersimpan,
            "outcome": "success",
        }
    if status_rek == REKONSILIASI_GAGAL_CEK:
        alasan = "query rekonsiliasi juga gagal"
    else:
        alasan = "URL baru belum ditemukan di database"
    daftar_path = ", ".join(uploaded_paths) if uploaded_paths else "-"
    return {
        "status": "belum_pasti",
        "entity_id": None,
        "catatan": (
            f"hasil penyimpanan belum pasti ({alasan}); file yang diunggah "
            f"sengaja dipertahankan untuk rekonsiliasi manual: {daftar_path}"
        ),
        "pesan": pesan_belum_pasti,
        "outcome": "failed",
    }


def _balas_gagal_ambigu(
    log_activity,
    current_user,
    request,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None,
    entity_label: str,
    field_label: str,
    hasil: dict,
    redirect_url: str,
    old_doc_urls: dict | None = None,
    new_doc_urls: dict | None = None,
) -> RedirectResponse:
    """Balas dan catat hasil jalur "gagal ambigu" (respons database hilang).

    Objek yang baru diunggah SELALU dipertahankan di jalur ini: hasil query
    rekonsiliasi yang kosong bukan bukti pasti gagal, karena request-nya masih
    mungkin berjalan di server.

    * Kalau URL baru ditemukan, tulisan memang tersimpan -> operasi dilaporkan
      sukses dan objek lama yang digantikan ikut dibersihkan.
    * Kalau tidak ditemukan (atau query rekonsiliasinya gagal), hasilnya
      dilaporkan belum pasti dan path objek dicatat di audit trail supaya
      administrator bisa merekonsiliasi manual.
    """
    perubahan = [{"field": field_label, "note": hasil["catatan"]}]
    peringatan = ""
    if hasil["outcome"] == "success" and old_doc_urls:
        # Tulisan terbukti tersimpan -> objek lama yang digantikan boleh
        # dibersihkan, sama seperti pada jalur sukses.
        cleanup_changes, cleanup_pesan = _cleanup_replaced_objects(
            entity_id, old_doc_urls, new_doc_urls or {}
        )
        perubahan.extend(cleanup_changes)
        peringatan = " ".join(cleanup_pesan)
    if hasil["outcome"] == "success":
        log_activity(
            current_user, action, entity_type, hasil["entity_id"] or entity_id,
            entity_label, changes=perubahan, request=request, outcome="success",
        )
        response = RedirectResponse(url=redirect_url, status_code=303)
        response.set_cookie("success_msg", hasil["pesan"])
    else:
        log_activity(
            current_user, action, entity_type, entity_id,
            entity_label, changes=perubahan, request=request, outcome="failed",
        )
        response = RedirectResponse(url=redirect_url, status_code=303)
        response.set_cookie("error_msg", hasil["pesan"])
    if peringatan:
        response.set_cookie("warning_msg", peringatan)
    return response


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
                .select("raw_material_id, product_id, products(is_deleted)").execute()
            usage_sets = {}
            for ln in (usage_lines.data or []):
                rm_id_ln = ln.get("raw_material_id")
                prod_id_ln = ln.get("product_id")
                # Produk yang sudah soft-delete (is_deleted=true) tidak dihitung sebagai
                # pemakaian aktif, supaya angka badge sama dengan isi modal
                # "Dipakai di Produk".
                if rm_id_ln and prod_id_ln and not _is_deleted_product(ln.get("products")):
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
                .select("percent_in_formula, products(id, nama_produk, perusahaan, is_deleted)") \
                .eq("raw_material_id", rm_id).execute()

            products_map = {}
            for ln in (lines_resp.data or []):
                product = ln.get("products")
                if isinstance(product, list):
                    product = product[0] if product else None
                if not product or not product.get("id"):
                    continue
                # Produk yang sudah soft-delete tidak ditampilkan sebagai pemakaian aktif.
                if product.get("is_deleted"):
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
        request: Request,
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
                    f"Upload cepat {document_list} untuk bahan baku {nama_bahan_baku} ({perusahaan})",
                    request=request
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

        log_activity(current_user, "create", "raw_material", new_rm_id, nama_dagang,
                   request=request)

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
        request: Request,
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
            log_activity(current_user, "create", "raw_material", new_rm["id"], nama_dagang,
                       request=request)

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
        request: Request,
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
            log_activity(current_user, "update", "raw_material", rm_id, nama_dagang, changes,
                       request=request)

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
    async def delete_raw_material(request: Request, rm_id: str,
                                  current_user: dict = Depends(get_current_user)):
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
                    remove_result = object_store.remove_from_all_backends(
                        bucket, path, client=supabase
                    )
                    failed = object_store.failed_backends(remove_result)
                    if failed:
                        print(
                            f"Gagal hapus file storage {path}; "
                            f"backend: {', '.join(failed)}"
                        )

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

        log_activity(current_user, "delete", "raw_material", rm_id, nama_sebelum_hapus,
                   request=request)

        return RedirectResponse(url="/raw-materials?success=Bahan+baku+beserta+seluruh+riwayat+batch+%26+dokumen+terkait+berhasil+dihapus", status_code=303)

    # ==================== ENDPOINT KELOLA VARIAN KOMPOSISI ====================
    @app.get("/raw-materials/{rm_id}/variants")
    async def list_raw_material_variants(
        rm_id: str,
        include: str | None = None,
        current_user: dict = Depends(get_current_user),
    ):
        """JSON daftar varian sebuah bahan baku (dipakai modal edit + Fase 4 formula).

        Dengan `include=components`, setiap varian disertai komponen INCI dan
        `legacy_components` hanya untuk komponen dengan `variant_id IS NULL`.
        """
        resp = supabase.table("raw_material_composition_variants") \
            .select("id, nama_varian, is_default, raw_material_components(inci_name, function, percent_internal, is_bahan_aktif)") \
            .eq("raw_material_id", rm_id).order("created_at").execute()
        variants = resp.data or []

        for variant in variants:
            comps = variant.get("raw_material_components") or []
            if isinstance(comps, dict):
                comps = [comps]
            if not isinstance(comps, list):
                comps = []
            variant["raw_material_components"] = comps
            if include == "components":
                variant["components"] = _sort_rm_components(comps)
                variant["component_count"] = len(comps)
            # Jangan bocorkan embed mentah di respons.
            variant.pop("raw_material_components", None)
            if include != "components":
                variant.pop("component_count", None)

        if include != "components":
            return JSONResponse(content={"success": True, "variants": variants})

        legacy_resp = supabase.table("raw_material_components") \
            .select("inci_name, function, percent_internal, is_bahan_aktif, variant_id") \
            .eq("raw_material_id", rm_id).is_("variant_id", "null").execute()
        legacy_components = _sort_rm_components(legacy_resp.data or []) if not variants else []

        return JSONResponse(content={
            "success": True,
            "variants": variants,
            "legacy_components": legacy_components,
        })

    @app.post("/raw-materials/{rm_id}/variants/add")
    async def add_raw_material_variant(
        request: Request,
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
        log_activity(current_user, "create", "raw_material_variant", new_variant.data[0]["id"], f"{rm_check.data[0].get('nama_dagang')} / {nama}",
                       request=request)
        response = RedirectResponse(url="/raw-materials", status_code=303)
        response.set_cookie("success_msg", f"Varian '{nama}' berhasil ditambahkan. Isi breakdown INCI-nya lewat menu Edit.")
        return response

    @app.post("/raw-materials/{rm_id}/variants/{variant_id}/set-default")
    async def set_default_raw_material_variant(request: Request, rm_id: str, variant_id: str,
                                              current_user: dict = Depends(get_current_user)):
        target = supabase.table("raw_material_composition_variants") \
            .select("id, nama_varian, raw_material_id").eq("id", variant_id).limit(1).execute()
        if not target.data or target.data[0].get("raw_material_id") != rm_id:
            raise HTTPException(status_code=400, detail="Varian yang dipilih tidak cocok dengan bahan baku ini.")
        # Unset semua dulu baru set yang baru (aman terhadap unique index 1-default).
        supabase.table("raw_material_composition_variants") \
            .update({"is_default": False}).eq("raw_material_id", rm_id).execute()
        supabase.table("raw_material_composition_variants") \
            .update({"is_default": True}).eq("id", variant_id).execute()
        log_activity(current_user, "update", "raw_material_variant", variant_id, f"{target.data[0].get('nama_varian')} (jadi default)",
                       request=request)
        response = RedirectResponse(url="/raw-materials", status_code=303)
        response.set_cookie("success_msg", f"Varian '{target.data[0].get('nama_varian')}' sekarang jadi varian default.")
        return response

    @app.post("/raw-materials/{rm_id}/variants/{variant_id}/delete")
    async def delete_raw_material_variant(request: Request, rm_id: str, variant_id: str,
                                         current_user: dict = Depends(get_current_user)):
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

        log_activity(current_user, "delete", "raw_material_variant", variant_id, nama_varian,
                   request=request)
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
        # Sufiks unik per operasi. Path file WAJIB unik supaya:
        #   - upload baru tidak menimpa file lama milik batch lain yang nomor
        #     batch-nya sama (dulu path-nya cuma "coa/coa_{batch}.pdf"),
        #   - objek yang dibuat operasi ini dijamin belum ada sebelumnya, jadi
        #     aman dihapus kalau penyimpanan ke database gagal.
        upload_uid = uuid4().hex[:8]

        # 1. Parse string data QC Aktual dari frontend ke Python list
        try:
            parsed_qc = json.loads(qc_results)
        except Exception as e:
            print(f"Gagal parsing qc_results: {e}")
            parsed_qc = []

        coa_url = None
        halal_url = None
        qc_report_url = None
        uploaded_paths: list = []   # objek yang dibuat operasi ini saja
        upload_errors: list = []    # nama dokumen yang gagal diunggah

        # 2. Proses Upload CoA jika ada filenya
        if coa_file and coa_file.filename:
            try:
                coa_bytes = await coa_file.read()
                _err = validate_pdf_bytes(coa_bytes, "File CoA")
                if _err:
                    raise ValueError(_err)
                coa_path = f"coa/coa_{clean_batch}_{upload_uid}.pdf"

                object_store.upload_pdf("raw-material-docs", coa_path, coa_bytes, client=supabase)
                uploaded_paths.append(coa_path)
                coa_url = object_store.public_url("raw-material-docs", coa_path, client=supabase)
                print("--> Sukses upload CoA.")
            except Exception as e:
                print(f"Gagal upload CoA: {e}")
                upload_errors.append("CoA")

        # 3. Proses Upload Halal Cert jika ada filenya
        if halal_file and halal_file.filename:
            try:
                halal_bytes = await halal_file.read()
                _err = validate_pdf_bytes(halal_bytes, "File Halal")
                if _err:
                    raise ValueError(_err)
                halal_path = f"halal/halal_{clean_batch}_{upload_uid}.pdf"

                object_store.upload_pdf("raw-material-docs", halal_path, halal_bytes, client=supabase)
                uploaded_paths.append(halal_path)
                halal_url = object_store.public_url("raw-material-docs", halal_path, client=supabase)
                print("--> Sukses upload Halal.")
            except Exception as e:
                print(f"Gagal upload Halal Cert: {e}")
                upload_errors.append("Halal")

        # 3b. Proses Upload Laporan Pemeriksaan Aktual (opsional) -- kalau QC punya dokumen
        # fisik/scan hasil pemeriksaan, ini dipake nanti jadi prioritas dibanding versi generate dari qc_results
        if qc_report_file and qc_report_file.filename:
            try:
                qc_report_bytes = await qc_report_file.read()
                _err = validate_pdf_bytes(qc_report_bytes, "File Laporan Pemeriksaan")
                if _err:
                    raise ValueError(_err)
                qc_report_path = f"qc-reports/qcreport_{clean_batch}_{upload_uid}.pdf"

                object_store.upload_pdf("raw-material-docs", qc_report_path, qc_report_bytes, client=supabase)
                uploaded_paths.append(qc_report_path)
                qc_report_url = object_store.public_url("raw-material-docs", qc_report_path, client=supabase)
                print("--> Sukses upload Laporan Pemeriksaan Aktual.")
            except Exception as e:
                print(f"Gagal upload Laporan Pemeriksaan Aktual: {e}")
                upload_errors.append("Laporan Pemeriksaan")

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
            ins_resp = supabase.table("raw_material_batches").insert(batch_data).execute()
            inserted = (ins_resp.data or [None])[0]
            batch_id = (inserted or {}).get("id") if isinstance(inserted, dict) else None
            print("--> Data Batch berhasil masuk ke Database!")
        except Exception as e:
            print(f"Gagal insert ke DB: {e}")
            klasifikasi = _klasifikasi_kegagalan_db(e)
            if klasifikasi == KEGAGALAN_PASTI_DITOLAK:
                # Server menolak permintaan: tulisan tidak terjadi, jadi objek
                # yang barusan diunggah jadi yatim dan BOLEH dihapus (HANYA
                # objek yang dibuat operasi ini - path-nya unik per operasi,
                # file milik batch lain tidak boleh disentuh).
                cleanup_ok, cleanup_failed = _cleanup_uploaded_objects(uploaded_paths)
                if cleanup_ok:
                    pesan = (
                        f"Gagal menyimpan batch '{no_batch.strip()}'. File yang sudah diunggah "
                        "sudah dihapus, silakan coba lagi."
                    )
                    catatan = (
                        "penyimpanan batch gagal di database; file yang diunggah sudah dibersihkan"
                    )
                else:
                    pesan = (
                        f"Gagal menyimpan batch '{no_batch.strip()}'. File yang sudah diunggah "
                        "juga gagal dihapus - administrator perlu memeriksa storage."
                    )
                    catatan = (
                        "penyimpanan batch gagal di database; file yang diunggah juga gagal dibersihkan "
                        f"({len(cleanup_failed)} objek) - admin harus memeriksa storage"
                    )
                log_activity(
                    # entity_id=None (bukan "-"): kolom activity_logs.entity_id
                    # bertipe uuid, jadi "-" gagal di-cast dan baris audit ini
                    # tidak akan pernah tersimpan.
                    current_user, "create", "raw_material_batch", None,
                    f"Batch {no_batch.strip()}",
                    changes=[{"field": "Batch", "note": catatan}],
                    request=request, outcome="failed",
                )
                response = RedirectResponse(url="/raw-materials", status_code=303)
                response.set_cookie("error_msg", pesan)
                return response
            # --- KEGAGALAN AMBIGU: respons database hilang --------------------
            # Tulisan mungkin sudah tersimpan di server, jadi objek yang baru
            # diunggah TIDAK boleh dihapus. Rekonsiliasi dulu: kalau URL baru
            # ditemukan, datanya memang tersimpan; kalau tidak, hasilnya
            # belum pasti dan file tetap dipertahankan untuk rekonsiliasi
            # manual oleh administrator.
            hasil_ambigu = _rekonsiliasi_setelah_gagal(
                batch_data,
                uploaded_paths,
                pesan_tersimpan=(
                    f"Batch '{no_batch.strip()}' tersimpan, tapi respons server tidak "
                    "diterima. File yang diunggah dipertahankan."
                ),
                pesan_belum_pasti=(
                    f"Belum bisa dipastikan apakah batch '{no_batch.strip()}' tersimpan. "
                    "File yang diunggah sengaja dipertahankan; administrator perlu "
                    "memeriksa storage."
                ),
            )
            return _balas_gagal_ambigu(
                log_activity, current_user, request,
                action="create",
                entity_type="raw_material_batch",
                entity_id=None,
                entity_label=f"Batch {no_batch.strip()}",
                field_label="Batch",
                hasil=hasil_ambigu,
                redirect_url="/raw-materials",
            )

        # Batch tersimpan. Kalau ada file yang gagal diunggah, hasilnya sukses
        # sebagian: baris batch-nya SUDAH ditulis, jadi outcome tetap "success"
        # dan file yang gagal disebut di `changes`. Outcome "failed" dipakai
        # hanya kalau baris batch-nya sendiri gagal ditulis.
        audit_changes = []
        if upload_errors:
            audit_changes.append({
                "field": "File",
                "note": "baris batch berhasil disimpan, tetapi file "
                        + ", ".join(upload_errors)
                        + " gagal diunggah. Detail teknis ada di log server.",
            })
            pesan = (
                f"Batch '{no_batch.strip()}' tersimpan, tetapi file "
                + ", ".join(upload_errors)
                + " gagal diunggah."
            )
            peringatan = (
                "File " + ", ".join(upload_errors)
                + " gagal diunggah. Silakan unggah ulang lewat menu upload cepat."
            )
        else:
            pesan = f"Batch '{no_batch.strip()}' berhasil ditambahkan."
            peringatan = ""

        log_activity(
            current_user, "create", "raw_material_batch", batch_id,
            f"Batch {no_batch.strip()}",
            changes=audit_changes or None, request=request,
            outcome="success",
        )

        # Redirect balik ke halaman utama bahan baku
        response = RedirectResponse(url="/raw-materials", status_code=303)
        response.set_cookie("success_msg", pesan)
        if peringatan:
            response.set_cookie("warning_msg", peringatan)
        return response

    @app.post("/raw-materials/batches/edit/{batch_id}")
    async def edit_material_batch(
        request: Request,
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
        clean_batch = "".join(c for c in no_batch if c.isalnum() or c in ('-', '_')).strip()
        # Sufiks unik per operasi (lihat add_material_batch): upload baru tidak
        # boleh menimpa file lama, dan objek yang baru dibuat aman dihapus
        # kalau UPDATE ke database gagal.
        upload_uid = uuid4().hex[:8]

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

        # --- Baca batch SEBELUM mengunggah apa pun -------------------------
        # .limit(1) (bukan .single()) supaya batch yang tidak ada tidak
        # melempar error -> ditolak sendiri dengan pesan yang jelas, dan
        # tidak ada file terunggah yang jadi yatim.
        pre_resp = supabase.table("raw_material_batches").select(
            "id, no_batch, coa_file_url, halal_batch_file_url, qc_report_file_url"
        ).eq("id", batch_id).limit(1).execute()
        batch_row = (pre_resp.data or [None])[0]
        if not batch_row:
            log_activity(
                current_user, "edit", "raw_material_batch", batch_id,
                f"Update batch {no_batch.strip()}",
                changes=[{"field": "Batch",
                          "note": "batch tidak ditemukan; tidak ada perubahan yang disimpan"}],
                request=request, outcome="rejected",
            )
            response = RedirectResponse(url="/raw-materials?tab=batch-tab", status_code=303)
            response.set_cookie("error_msg", "Batch tidak ditemukan. Perubahan tidak disimpan.")
            return response

        # URL dokumen LAMA -> dipakai nanti untuk menghapus objek yang
        # digantikan, kalau objek itu memang tidak dirujuk baris lain.
        old_doc_urls = {
            "coa_file_url": batch_row.get("coa_file_url"),
            "halal_batch_file_url": batch_row.get("halal_batch_file_url"),
            "qc_report_file_url": batch_row.get("qc_report_file_url"),
        }

        uploaded_paths: list = []   # objek yang dibuat operasi ini saja
        upload_errors: list = []    # nama dokumen yang gagal diunggah

        # 2. Update Files if provided
        if coa_file and coa_file.filename:
            try:
                coa_bytes = await coa_file.read()
                _err = validate_pdf_bytes(coa_bytes, "File CoA")
                if _err:
                    raise ValueError(_err)
                coa_path = f"coa/coa_{clean_batch}_{upload_uid}.pdf"
                object_store.upload_pdf("raw-material-docs", coa_path, coa_bytes, client=supabase)
                uploaded_paths.append(coa_path)
                update_data["coa_file_url"] = object_store.public_url("raw-material-docs", coa_path, client=supabase)
            except Exception as e:
                print(f"Gagal update CoA: {e}")
                upload_errors.append("CoA")

        if halal_file and halal_file.filename:
            try:
                halal_bytes = await halal_file.read()
                _err = validate_pdf_bytes(halal_bytes, "File Halal")
                if _err:
                    raise ValueError(_err)
                halal_path = f"halal/halal_{clean_batch}_{upload_uid}.pdf"
                object_store.upload_pdf("raw-material-docs", halal_path, halal_bytes, client=supabase)
                uploaded_paths.append(halal_path)
                update_data["halal_batch_file_url"] = object_store.public_url("raw-material-docs", halal_path, client=supabase)
            except Exception as e:
                print(f"Gagal update Halal: {e}")
                upload_errors.append("Halal")

        if qc_report_file and qc_report_file.filename:
            try:
                qc_report_bytes = await qc_report_file.read()
                _err = validate_pdf_bytes(qc_report_bytes, "File Laporan Pemeriksaan")
                if _err:
                    raise ValueError(_err)
                qc_report_path = f"qc-reports/qcreport_{clean_batch}_{upload_uid}.pdf"
                object_store.upload_pdf("raw-material-docs", qc_report_path, qc_report_bytes, client=supabase)
                uploaded_paths.append(qc_report_path)
                update_data["qc_report_file_url"] = object_store.public_url("raw-material-docs", qc_report_path, client=supabase)
            except Exception as e:
                print(f"Gagal update QC Report: {e}")
                upload_errors.append("Laporan Pemeriksaan")

        # 3. Simpan perubahan ke database. Audit log TIDAK lagi ditulis di
        #    dalam try yang sama, supaya kegagalan update tetap tercatat sebagai
        #    kegagalan (bukan hilang tanpa jejak).
        #    .select("id") dipakai supaya PostgREST mengembalikan baris yang
        #    terpengaruh: UPDATE tanpa baris yang cocok TIDAK melempar error,
        #    jadi harus dicek sendiri (batch hilang / terhapus di antara
        #    pre-read dan update). Kalau tidak ada baris yang terpengaruh,
        #    exception sentinel dilempar supaya ikut ditangani sebagai
        #    kegagalan - bukan dilaporkan sukses.
        try:
            upd_resp = (
                supabase.table("raw_material_batches").update(update_data)
                .eq("id", batch_id)
                .select("id")
                .execute()
            )
            affected_rows = len(upd_resp.data or [])
            if not affected_rows:
                raise _BatchUpdateAffectedNoRow(
                    "tidak ada baris batch yang terpengaruh oleh update"
                )
        except Exception as e:
            if isinstance(e, _BatchUpdateAffectedNoRow):
                print(f"Update batch {batch_id} tidak menyentuh baris mana pun: {e}")
                # Tidak ada baris yang terpengaruh -> tulisan pasti tidak
                # terjadi, sama seperti penolakan server.
                klasifikasi = KEGAGALAN_PASTI_DITOLAK
                pesan_gagal = "Batch tidak ditemukan. Perubahan tidak disimpan."
                catatan_gagal = (
                    "batch tidak ditemukan atau terhapus saat perubahan disimpan"
                )
                suffix_pesan = " File yang sudah diunggah sudah dihapus."
            else:
                print(f"Gagal update batch: {e}")
                klasifikasi = _klasifikasi_kegagalan_db(e)
                pesan_gagal = f"Gagal menyimpan perubahan batch '{no_batch.strip()}'."
                catatan_gagal = "penyimpanan perubahan batch gagal di database"
                suffix_pesan = (
                    " File yang sudah diunggah sudah dihapus, silakan coba lagi."
                )
            if klasifikasi == KEGAGALAN_PASTI_DITOLAK:
                # Kegagalan pasti: tulisan tidak terjadi, jadi objek yang
                # barusan diunggah jadi yatim dan BOLEH dihapus (HANYA objek
                # yang dibuat operasi ini - path-nya unik per operasi).
                cleanup_ok, cleanup_failed = _cleanup_uploaded_objects(uploaded_paths)
                if cleanup_ok:
                    pesan = pesan_gagal + suffix_pesan
                    catatan = catatan_gagal + "; file yang diunggah sudah dibersihkan"
                else:
                    pesan = (
                        pesan_gagal + " File yang sudah diunggah juga gagal dihapus - "
                        "administrator perlu memeriksa storage."
                    )
                    catatan = (
                        catatan_gagal + "; file yang diunggah juga gagal dibersihkan "
                        f"({len(cleanup_failed)} objek) - admin harus memeriksa storage"
                    )
                log_activity(
                    current_user, "edit", "raw_material_batch", batch_id,
                    f"Update batch {no_batch.strip()}",
                    changes=[{"field": "Batch", "note": catatan}],
                    request=request, outcome="failed",
                )
                response = RedirectResponse(url="/raw-materials?tab=batch-tab", status_code=303)
                response.set_cookie("error_msg", pesan)
                return response
            # --- KEGAGALAN AMBIGU: respons database hilang --------------------
            # Tulisan mungkin sudah tersimpan di server, jadi objek yang baru
            # diunggah TIDAK boleh dihapus. Rekonsiliasi dulu: kalau URL baru
            # ditemukan, datanya memang tersimpan; kalau tidak, hasilnya
            # belum pasti dan file tetap dipertahankan untuk rekonsiliasi
            # manual oleh administrator.
            hasil_ambigu = _rekonsiliasi_setelah_gagal(
                update_data,
                uploaded_paths,
                pesan_tersimpan=(
                    f"Perubahan batch '{no_batch.strip()}' tersimpan, tapi respons "
                    "server tidak diterima. File yang diunggah dipertahankan."
                ),
                pesan_belum_pasti=(
                    f"Belum bisa dipastikan apakah perubahan batch '{no_batch.strip()}' "
                    "tersimpan. File yang diunggah sengaja dipertahankan; administrator "
                    "perlu memeriksa storage."
                ),
            )
            return _balas_gagal_ambigu(
                log_activity, current_user, request,
                action="edit",
                entity_type="raw_material_batch",
                entity_id=batch_id,
                entity_label=f"Update batch {no_batch.strip()}",
                field_label="Batch",
                hasil=hasil_ambigu,
                redirect_url="/raw-materials?tab=batch-tab",
                old_doc_urls=old_doc_urls,
                new_doc_urls=update_data,
            )

        # Update berhasil -> file lama yang digantikan dibersihkan (hanya
        # kalau tidak dirujuk baris lain), lalu audit ditulis di sini
        # (di luar try database).
        cleanup_changes, cleanup_pesan = _cleanup_replaced_objects(batch_id, old_doc_urls, update_data)

        audit_changes = []
        if upload_errors:
            audit_changes.append({
                "field": "File",
                "note": "perubahan batch tersimpan, tetapi file "
                        + ", ".join(upload_errors)
                        + " gagal diunggah. Detail teknis ada di log server.",
            })
            pesan = (
                f"Perubahan batch '{no_batch.strip()}' tersimpan, tetapi file "
                + ", ".join(upload_errors)
                + " gagal diunggah."
            )
            peringatan = (
                "File " + ", ".join(upload_errors)
                + " gagal diunggah. Silakan unggah ulang lewat menu upload cepat."
            )
        else:
            pesan = f"Perubahan batch '{no_batch.strip()}' berhasil disimpan."
            peringatan = ""
        audit_changes.extend(cleanup_changes)
        if cleanup_pesan:
            peringatan = (peringatan + " " + " ".join(cleanup_pesan)).strip()

        log_activity(
            current_user, "edit", "raw_material_batch", batch_id,
            f"Update batch {no_batch.strip()}",
            changes=audit_changes or None, request=request,
            outcome="success",
        )

        response = RedirectResponse(url="/raw-materials?tab=batch-tab", status_code=303)
        response.set_cookie("success_msg", pesan)
        if peringatan:
            response.set_cookie("warning_msg", peringatan)
        return response

    @app.post("/raw-materials/batches/{batch_id}/quick-upload-doc")
    async def quick_upload_batch_doc(
        request: Request,
        batch_id: str,
        coa_file: UploadFile = File(None),
        halal_file: UploadFile = File(None),
        qc_report_file: UploadFile = File(None),
        current_user: dict = Depends(get_current_user)
    ):
        # Route ini CUMA nyentuh kolom file URL, tidak menyentuh field lain
        # (no_batch, supplier, tanggal, kesimpulan, dll) di baris batch tersebut.
        # .limit(1) (bukan .single()) supaya batch yang tidak ada tidak
        # melempar error -> ditolak dengan pesan yang jelas.
        batch_resp = supabase.table("raw_material_batches").select(
            "no_batch, coa_file_url, halal_batch_file_url, qc_report_file_url, "
            "raw_materials(nama_dagang)"
        ).eq("id", batch_id).limit(1).execute()
        batch_row = (batch_resp.data or [None])[0]
        if not batch_row:
            log_activity(
                current_user, "edit", "raw_material_batch", batch_id,
                "Upload cepat dokumen batch",
                changes=[{"field": "Dokumen",
                          "note": "batch tidak ditemukan; tidak ada dokumen yang diunggah"}],
                request=request, outcome="rejected",
            )
            response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
            response.set_cookie("error_msg", "Batch tidak ditemukan.")
            return response

        no_batch = batch_row["no_batch"]
        # URL dokumen LAMA -> dipakai untuk menghapus objek yang digantikan,
        # kalau update-nya terkonfirmasi sukses dan objek itu tidak dirujuk
        # baris lain.
        old_doc_urls = {
            "coa_file_url": batch_row.get("coa_file_url"),
            "halal_batch_file_url": batch_row.get("halal_batch_file_url"),
            "qc_report_file_url": batch_row.get("qc_report_file_url"),
        }
        raw_material = batch_row.get("raw_materials")
        if isinstance(raw_material, list):
            raw_material = raw_material[0] if raw_material else None
        nama_bahan_baku = raw_material.get("nama_dagang") if isinstance(raw_material, dict) else None
        nama_bahan_baku = nama_bahan_baku or "Tanpa Master"
        clean_batch = "".join(c for c in no_batch if c.isalnum() or c in ("-", "_")).strip()

        # Apakah ada file yang benar-benar dipilih? File yang dipilih tapi
        # gagal validasi BUKAN sama dengan "tidak ada file yang dipilih" -
        # dua kasus ini harus dibedakan supaya pesannya jujur.
        files_selected = any(
            upload is not None and (getattr(upload, "filename", "") or "")
            for upload in (coa_file, halal_file, qc_report_file)
        )

        update_data = {}
        uploaded_documents = []
        uploaded_paths: list = []   # objek yang dibuat operasi ini saja
        upload_errors: list = []    # nama dokumen yang gagal diunggah
        # Sufiks unik per operasi: path file tidak boleh menimpa file lama
        # milik batch lain dengan nomor batch sama, dan objek yang baru dibuat
        # aman dihapus kalau penyimpanan ke database gagal.
        upload_uid = uuid4().hex[:8]

        if coa_file and coa_file.filename:
            try:
                coa_bytes = await coa_file.read()
                _err = validate_pdf_bytes(coa_bytes, "File CoA")
                if _err:
                    raise ValueError(_err)
                coa_path = f"coa/coa_{clean_batch}_{upload_uid}.pdf"
                object_store.upload_pdf("raw-material-docs", coa_path, coa_bytes, client=supabase)
                uploaded_paths.append(coa_path)
                update_data["coa_file_url"] = object_store.public_url("raw-material-docs", coa_path, client=supabase)
                uploaded_documents.append("CoA")
            except Exception as e:
                print(f"Gagal quick-upload CoA: {e}")
                upload_errors.append("CoA")

        if halal_file and halal_file.filename:
            try:
                halal_bytes = await halal_file.read()
                _err = validate_pdf_bytes(halal_bytes, "File Halal")
                if _err:
                    raise ValueError(_err)
                halal_path = f"halal/halal_{clean_batch}_{upload_uid}.pdf"
                object_store.upload_pdf("raw-material-docs", halal_path, halal_bytes, client=supabase)
                uploaded_paths.append(halal_path)
                update_data["halal_batch_file_url"] = object_store.public_url("raw-material-docs", halal_path, client=supabase)
                uploaded_documents.append("Halal")
            except Exception as e:
                print(f"Gagal quick-upload Halal: {e}")
                upload_errors.append("Halal")

        if qc_report_file and qc_report_file.filename:
            try:
                qc_report_bytes = await qc_report_file.read()
                _err = validate_pdf_bytes(qc_report_bytes, "File Laporan Pemeriksaan")
                if _err:
                    raise ValueError(_err)
                qc_report_path = f"qc-reports/qcreport_{clean_batch}_{upload_uid}.pdf"
                object_store.upload_pdf("raw-material-docs", qc_report_path, qc_report_bytes, client=supabase)
                uploaded_paths.append(qc_report_path)
                update_data["qc_report_file_url"] = object_store.public_url("raw-material-docs", qc_report_path, client=supabase)
                uploaded_documents.append("Catatan Pemeriksaan Bahan Baku")
            except Exception as e:
                print(f"Gagal quick-upload QC Report: {e}")
                upload_errors.append("Laporan Pemeriksaan")

        # Kasus 1: tidak ada file yang dipilih sama sekali.
        if not files_selected:
            log_activity(
                current_user, "edit", "raw_material_batch", batch_id,
                f"Upload cepat untuk bahan baku {nama_bahan_baku} - batch {no_batch}",
                changes=[{"field": "Dokumen",
                          "note": "tidak ada file yang dipilih; tidak ada dokumen yang diubah"}],
                request=request, outcome="rejected",
            )
            response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
            response.set_cookie("error_msg", "Tidak ada file yang dipilih.")
            return response

        # Kasus 2: file dipilih, tapi SEMUA gagal -> tidak ada dokumen yang
        # tersimpan. Bersihkan dulu objek yang sempat terunggah (biasanya
        # daftar ini kosong, tapi tetap aman dibersihkan).
        if not update_data:
            cleanup_ok, cleanup_failed = _cleanup_uploaded_objects(uploaded_paths)
            catatan = (
                "semua file gagal diunggah ("
                + ", ".join(upload_errors)
                + "); tidak ada dokumen yang tersimpan"
            )
            if not cleanup_ok:
                catatan += (
                    f"; file yang sempat terunggah juga gagal dibersihkan ({len(cleanup_failed)} objek)"
                )
            log_activity(
                current_user, "edit", "raw_material_batch", batch_id,
                f"Upload cepat untuk bahan baku {nama_bahan_baku} - batch {no_batch}",
                changes=[{"field": "Dokumen", "note": catatan}],
                request=request, outcome="failed",
            )
            response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
            response.set_cookie(
                "error_msg",
                "Semua file gagal diunggah. Tidak ada dokumen yang tersimpan.",
            )
            return response

        # Kasus 3: ada dokumen yang berhasil tersimpan (mungkin sebagian
        # file gagal -> nanti dilaporkan lewat warning_msg).
        # .select("id") dipakai supaya PostgREST mengembalikan baris yang
        # terpengaruh: UPDATE tanpa baris yang cocok TIDAK melempar error,
        # jadi harus dicek sendiri (batch hilang / terhapus di antara
        # pre-read dan update). Kalau tidak ada baris yang terpengaruh,
        # exception sentinel dilempar supaya ikut ditangani sebagai
        # kegagalan - bukan dilaporkan sukses.
        try:
            upd_resp = (
                supabase.table("raw_material_batches").update(update_data)
                .eq("id", batch_id)
                .select("id")
                .execute()
            )
            affected_rows = len(upd_resp.data or [])
            if not affected_rows:
                raise _BatchUpdateAffectedNoRow(
                    "tidak ada baris batch yang terpengaruh oleh update"
                )
        except Exception as e:
            if isinstance(e, _BatchUpdateAffectedNoRow):
                print(f"Update batch {batch_id} tidak menyentuh baris mana pun: {e}")
                # Tidak ada baris yang terpengaruh -> tulisan pasti tidak
                # terjadi, sama seperti penolakan server.
                klasifikasi = KEGAGALAN_PASTI_DITOLAK
                pesan_dasar = "Batch tidak ditemukan. Perubahan tidak disimpan."
                catatan_dasar = (
                    "batch tidak ditemukan atau terhapus saat dokumen disimpan"
                )
                suffix_pesan = " File yang sudah diunggah sudah dihapus."
                pesan_bersih_gagal = (
                    " File yang sudah diunggah juga gagal dihapus - "
                    "administrator perlu memeriksa storage."
                )
            else:
                print(f"Gagal simpan quick-upload batch doc: {e}")
                klasifikasi = _klasifikasi_kegagalan_db(e)
                pesan_dasar = "Gagal menyimpan dokumen batch."
                catatan_dasar = "penyimpanan URL dokumen gagal di database"
                suffix_pesan = (
                    " File yang sudah diunggah sudah dihapus, silakan coba lagi."
                )
                pesan_bersih_gagal = (
                    " File yang sudah diunggah juga gagal dihapus - "
                    "administrator perlu memeriksa storage."
                )
            if klasifikasi == KEGAGALAN_PASTI_DITOLAK:
                # Kegagalan pasti: tulisan tidak terjadi, jadi objek yang
                # barusan diunggah jadi yatim dan BOLEH dihapus (HANYA
                # objek yang dibuat operasi ini - path-nya unik per operasi).
                cleanup_ok, cleanup_failed = _cleanup_uploaded_objects(uploaded_paths)
                if cleanup_ok:
                    pesan = pesan_dasar + suffix_pesan
                    catatan = catatan_dasar + "; file yang diunggah sudah dibersihkan"
                else:
                    pesan = pesan_dasar + pesan_bersih_gagal
                    catatan = (
                        catatan_dasar + "; file yang diunggah juga gagal dibersihkan "
                        f"({len(cleanup_failed)} objek) - admin harus memeriksa storage"
                    )
                log_activity(
                    current_user, "edit", "raw_material_batch", batch_id,
                    f"Upload cepat untuk bahan baku {nama_bahan_baku} - batch {no_batch}",
                    changes=[{"field": "Dokumen", "note": catatan}],
                    request=request, outcome="failed",
                )
                response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
                response.set_cookie("error_msg", pesan)
                return response
            # --- KEGAGALAN AMBIGU: respons database hilang --------------------
            # Tulisan mungkin sudah tersimpan di server, jadi objek yang baru
            # diunggah TIDAK boleh dihapus. Rekonsiliasi dulu: kalau URL baru
            # ditemukan, dokumennya memang tersimpan; kalau tidak, hasilnya
            # belum pasti dan file tetap dipertahankan untuk rekonsiliasi
            # manual oleh administrator.
            hasil_ambigu = _rekonsiliasi_setelah_gagal(
                update_data,
                uploaded_paths,
                pesan_tersimpan=(
                    f"Dokumen batch '{no_batch.strip()}' tersimpan, tapi respons server "
                    "tidak diterima. File yang diunggah dipertahankan."
                ),
                pesan_belum_pasti=(
                    f"Belum bisa dipastikan apakah dokumen batch '{no_batch.strip()}' "
                    "tersimpan. File yang diunggah sengaja dipertahankan; administrator "
                    "perlu memeriksa storage."
                ),
            )
            return _balas_gagal_ambigu(
                log_activity, current_user, request,
                action="edit",
                entity_type="raw_material_batch",
                entity_id=batch_id,
                entity_label=f"Upload cepat untuk bahan baku {nama_bahan_baku} - batch {no_batch}",
                field_label="Dokumen",
                hasil=hasil_ambigu,
                redirect_url="/raw-materials?tab=docs-tab",
                old_doc_urls=old_doc_urls,
                new_doc_urls=update_data,
            )

        # Update terkonfirmasi sukses -> objek lama yang digantikan dibersihkan
        # (hanya kalau tidak dirujuk baris lain). Hasil pembersihan ikut
        # masuk audit trail dan warning_msg, jadi masalah cleanup tidak hilang
        # diam-diam.
        cleanup_changes, cleanup_pesan = _cleanup_replaced_objects(
            batch_id, old_doc_urls, update_data
        )

        # Audit ditulis di luar try database supaya kegagalan tetap tercatat.
        # Baris batch SUDAH tersimpan, jadi outcome tetap "success"; file yang
        # gagal disebut di `changes` dan diperingatkan lewat warning_msg.
        audit_changes = []
        if upload_errors:
            audit_changes.append({
                "field": "Dokumen",
                "note": "dokumen tersimpan, tetapi file "
                        + ", ".join(upload_errors)
                        + " gagal diunggah. Detail teknis ada di log server.",
            })
        audit_changes.extend(cleanup_changes)
        document_list = ", ".join(uploaded_documents)
        log_activity(
            current_user, "edit", "raw_material_batch", batch_id,
            f"Upload cepat {document_list} untuk bahan baku {nama_bahan_baku} - batch {no_batch}",
            changes=audit_changes or None, request=request,
            outcome="success",
        )
        response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
        if upload_errors:
            response.set_cookie("success_msg", f"Batch '{no_batch.strip()}' tersimpan.")
        else:
            response.set_cookie("success_msg", "Dokumen berhasil diupload.")
        if upload_errors or cleanup_pesan:
            response.set_cookie(
                "warning_msg",
                " ".join(
                    [
                        (
                            "File " + ", ".join(upload_errors)
                            + " gagal diunggah. Silakan unggah ulang."
                            if upload_errors else ""
                        ),
                        (
                            f"Batch '{no_batch.strip()}': " + " ".join(cleanup_pesan)
                            if cleanup_pesan else ""
                        ),
                    ]
                ).strip(),
            )
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

            log_activity(current_user, "acc_dipakai", "raw_material_batch", batch_id, f"ED diperpanjang ke {new_expiry_date}",
                           request=request)

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

            log_activity(current_user, "acc_dimusnahkan", "raw_material_batch", batch_id, "Batch dimusnahkan (dispose)",
                           request=request)

            response = RedirectResponse(url="/raw-materials?tab=ed-tab", status_code=303)
            response.set_cookie("success_msg", "Batch berhasil dimusnahkan (ACC Dimusnahkan).")
            return response

        except Exception as e:
            print(f"Gagal ACC Dimusnahkan: {e}")
            response = RedirectResponse(url="/raw-materials?tab=ed-tab", status_code=303)
            response.set_cookie("error_msg", f"Gagal memusnahkan batch: {str(e)}")
            return response
