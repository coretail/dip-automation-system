"""Public Link BPOM - permalink untuk verifikator BPOM.

Route /dip/[slug-nama-produk]-[id] bersifat PUBLIK (tanpa login) & permanen
(tidak ada masa expired) supaya bisa dilampirkan ke portal e-registration BPOM
dan tetap hidup bertahun-tahun.
Contoh: /dip/sunscreen-serum-spf-50-e623d2e4-1234-5678-9abc-def012345678

Keamanan akses file:
  - PDF gabungan tiap Bab (I, II, III, IV) -> di-stream lewat backend
    (proxy), browser tidak pernah menyentuh storage langsung.
  - File individu di Supabase Storage (CoA, Halal, MSDS, Spesifikasi)
    -> short-lived signed URL (default 1 jam) yang di-generate otomatis
    tiap kali halaman hub dibuka.

Modul ini adalah refactor murni dari blok "PUBLIC LINK BPOM" yang sebelumnya
berada di app/main.py. Tidak ada perubahan perilaku: URL, response, status
code, pesan error, dan urutan pemanggilan tetap sama.

Semua dependency dari main.py di-inject sebagai parameter supaya tidak ada
circular import (pola yang sama seperti notes_routes, efek_samping,
raw_materials_routes, dan po_routes).
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse

# Zona waktu bisnis (WIB) — harus nilainya sama dengan main.py
WIB = ZoneInfo("Asia/Jakarta")


def register_dip_public_routes(
    app: FastAPI,
    templates,
    supabase,
    get_company_info,
    extract_id_from_slug,
    client_ip,
    apply_company_specific_docs,
    parse_storage_url,
    bab_generators,
    download_bab2_zip,
):
    """Daftarkan seluruh route publik /dip/* ke aplikasi.

    Parameter:
      app                       : instance FastAPI
      templates                 : Jinja2Templates
      supabase                  : klien Supabase
      get_company_info          : pemetaan perusahaan -> data kop surat
      extract_id_from_slug      : ambil UUID produk dari slug publik
      client_ip                 : helper IPAddr request
      apply_company_specific_docs : timpa spec/msds bahan baku per perusahaan
      parse_storage_url         : (url) -> (bucket, path) dari public storage URL
      bab_generators            : dict {"1".."4"} pemetaan bab -> fungsi generator
      download_bab2_zip         : generator ZIP Bab II
    """

    def _storage_signed_url(public_url: str, expires_in: int = 3600):
        """Generate short-lived signed URL dari public URL Supabase Storage.
        URL asli storage tidak dibocorkan ke browser; yang dikirim cuma signed URL
        sementara (default 1 jam). Kalau parsing/generate gagal, fallback ke URL
        asli supaya link tetap jalan di halaman publik."""
        if not public_url:
            return None
        bucket, path = parse_storage_url(public_url)
        if not bucket or not path:
            return public_url
        try:
            resp = supabase.storage.from_(bucket).create_signed_url(path, expires_in)
            signed = resp.get("signedURL") or resp.get("signedUrl")
            return signed or public_url
        except Exception as e:
            print(f"Gagal generate signed URL ({bucket}/{path}): {e}")
            return public_url

    def _get_audit_username(request: Request) -> str:
        """Best-effort ambil username (full_name) user yang sedang login, buat log audit
        public link. Kalau tidak login / token invalid / query gagal, return '-' supaya
        log tetap jalan. Dipanggil di route publik yang TIDAK boleh gagal gara-gara ini."""
        token_cookie = request.cookies.get("access_token")
        if not token_cookie:
            return "-"
        try:
            token = token_cookie.replace("Bearer ", "")
            user_auth = supabase.auth.get_user(token)
            user_data = user_auth.user
            if not user_data:
                return "-"
            profile_res = supabase.table("profiles").select("full_name").eq("id", user_data.id).execute()
            if profile_res.data and profile_res.data[0].get("full_name"):
                return profile_res.data[0]["full_name"]
            return user_data.email or "-"
        except Exception:
            return "-"

    def _audit_public_link(product_id: str, product_name: str, ip_address: str, user_agent: str, username: str = "-"):
        """Catat setiap akses ke public link DIP (/dip/[slug]-[id]).
        Field DB: product_id, visited_at (timestamp), ip_address, user_agent.
        1) Simpan ke tabel khusus public_link_audits (sudah dibuat di Supabase).
        2) Fallback ke activity_logs kalau tabel khusus belum dibuat, biar tidak ada akses yang hilang.
        Kegagalan logging TIDAK pernah mengganggu halaman (diamankan try/except)."""
        # 1. Cetak ke terminal supaya terpantau realtime (produk ditampilkan sebagai NAMA, bukan id)
        now_str = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
        print("\n" + "=" * 60)
        print(f"🔗 [PUBLIC LINK OPENED] | {now_str}")
        print(f"   • Product   : {product_name or product_id}")
        print(f"   • IP        : {ip_address}")
        print(f"   • User-Agent: {(user_agent or '-')[:120]}")
        print(f"   • Username  : {username or '-'}")
        print("=" * 60)

        # 2. Simpan ke tabel audit khusus (public_link_audits)
        try:
            supabase.table("public_link_audits").insert({
                "product_id": product_id,
                "visited_at": datetime.now(ZoneInfo("UTC")).isoformat(),
                "ip_address": ip_address,
                "user_agent": (user_agent or "-")[:500],
            }).execute()
            return
        except Exception as e:
            print(f"[AUDIT PUBLIC LINK] Gagal simpan ke public_link_audits: {e}")

        # 3. Fallback: simpan ke activity_logs (tabel lama) biar akses tetap tercatat
        try:
            supabase.table("activity_logs").insert({
                "actor_id": None,
                "actor_name": "System",
                "action": "public_link_visit",
                "entity_type": "product",
                "entity_id": product_id,
                "entity_label": product_name or "Public link DIP dibuka",
                "changes": [
                    {"field": "ip_address", "note": ip_address},
                    {"field": "user_agent", "note": (user_agent or "-")[:500]},
                    {"field": "username", "note": username or "-"},
                ],
            }).execute()
        except Exception as e:
            print(f"[AUDIT PUBLIC LINK] Gagal simpan ke activity_logs: {e}")

    @app.get("/dip/{slug_id}", response_class=HTMLResponse)
    async def dip_public_hub(request: Request, slug_id: str):
        """Landing page/hub publik khusus verifikator BPOM untuk 1 produk.

        Format URL: /dip/[slug-nama-produk]-[id]
        Contoh: /dip/sunscreen-serum-spf-50-e623d2e4-...
        """
        product_id = extract_id_from_slug(slug_id)

        try:
            prod_resp = supabase.table("products") \
                .select("*, brands(name, producers(name))") \
                .eq("id", product_id) \
                .eq("is_deleted", False) \
                .single() \
                .execute()
            product = prod_resp.data if prod_resp.data else None
        except Exception as e:
            print(f"[PUBLIC HUB] Produk {product_id} tidak ditemukan: {e}")
            product = None
        if not product:
            raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")

        # Audit log: catat setiap kali public link dibuka (product_id, timestamp, IP, user-agent, username)
        _audit_public_link(
            product_id=product_id,
            product_name=product.get("nama_produk") or "Produk",
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent") or "-",
            username=_get_audit_username(request),
        )

        perusahaan = product.get("perusahaan") or "PT Erfi"
        company = get_company_info(perusahaan)

        # Normalisasi relasi brand (supabase bisa return dict atau list tergantung setup)
        brand_info = product.get("brands") or {}
        if isinstance(brand_info, list):
            brand_info = brand_info[0] if brand_info else {}
        producers = brand_info.get("producers") or {}
        if isinstance(producers, list):
            producers = producers[0] if producers else {}
        brand_name = brand_info.get("name")
        producer_name = producers.get("name")

        # --- Kumpulin daftar file Bab II per bahan baku (Spesifikasi, CoA, Halal, MSDS) ---
        bab2_materials = []
        try:
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

            for rm in raw_materials:
                # Timpa spec/msds dengan data company-specific (biar gak tertukar antar-PT)
                apply_company_specific_docs(rm, perusahaan)

                batch = None
                try:
                    batch_resp = supabase.table("raw_material_batches") \
                        .select("*") \
                        .eq("raw_material_id", rm["id"]) \
                        .eq("perusahaan", perusahaan) \
                        .neq("kesimpulan", "lab") \
                        .order("created_at", desc=True) \
                        .limit(1) \
                        .execute()
                    batch = batch_resp.data[0] if batch_resp.data else None
                except Exception as e:
                    print(f"[PUBLIC HUB] Gagal ambil batch bahan baku: {e}")

                candidate_files = [
                    {"label": "Spesifikasi Bahan Baku", "url": rm.get("spec_sheet_file_url"), "icon": "fa-file-lines"},
                    {"label": "CoA (Certificate of Analysis)", "url": batch.get("coa_file_url") if batch else None, "icon": "fa-file-circle-check"},
                    {"label": "Sertifikat Halal", "url": batch.get("halal_batch_file_url") if batch else None, "icon": "fa-file-shield"},
                    {"label": "MSDS (Material Safety Data Sheet)", "url": rm.get("msds_file_url"), "icon": "fa-file-triangle"},
                ]
                files = []
                for f in candidate_files:
                    if f["url"]:
                        files.append({
                            "label": f["label"],
                            "icon": f["icon"],
                            "url": _storage_signed_url(f["url"])
                        })
                if files:
                    bab2_materials.append({
                        "nama": rm.get("nama_dagang") or "Unknown",
                        "kode": rm.get("kode_bahan_baku") or "-",
                        "files": files
                    })
        except Exception as e:
            print(f"[PUBLIC HUB] Gagal kumpulin file Bab II: {e}")

        return templates.TemplateResponse(
            request=request,
            name="dip_public_hub.html",
            context={
                "product": product,
                "company": company,
                "perusahaan": perusahaan,
                "brand_name": brand_name,
                "producer_name": producer_name,
                "bab2_materials": bab2_materials,
                "tanggal_generate": datetime.now(WIB).strftime("%d %B %Y %H:%M WIB"),
            }
        )

    def _dip_public_check_product(product_id: str) -> bool:
        """Validasi UUID produk eksis (buat route publik /dip/[slug]-[id])."""
        try:
            check = supabase.table("products").select("id").eq("id", product_id).eq("is_deleted", False).single().execute()
            return bool(check.data)
        except Exception:
            return False

    async def _dip_stream_bab(product_id: str, bab_num: str, as_attachment: bool):
        """Stream PDF gabungan Bab I-IV lewat backend (proxy), tanpa login."""
        if not _dip_public_check_product(product_id):
            raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")
        gen = bab_generators.get(bab_num)
        if not gen:
            raise HTTPException(status_code=404, detail="Bab tidak ditemukan.")
        try:
            resp = await gen(product_id, None)
        except HTTPException:
            raise
        except Exception as e:
            import traceback
            print(f"\n🔴 [PUBLIC DIP ERROR] Gagal generate Bab {bab_num} untuk product_id={product_id}")
            print(f"   Error: {e}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="Dokumen sedang tidak dapat diproses. Silakan coba beberapa saat lagi.")
        disposition = "attachment" if as_attachment else "inline"
        current = resp.headers.get("Content-Disposition") or f"{disposition}; filename=document.pdf"
        resp.headers["Content-Disposition"] = re.sub(r"^(attachment|inline)", disposition, current, flags=re.IGNORECASE)
        return resp

    @app.get("/dip/{slug_id}/bab1")
    async def dip_public_bab1(slug_id: str):
        product_id = extract_id_from_slug(slug_id)
        return await _dip_stream_bab(product_id, "1", False)

    @app.get("/dip/{slug_id}/bab1/download")
    async def dip_public_bab1_download(slug_id: str):
        product_id = extract_id_from_slug(slug_id)
        return await _dip_stream_bab(product_id, "1", True)

    @app.get("/dip/{slug_id}/bab2")
    async def dip_public_bab2(slug_id: str):
        product_id = extract_id_from_slug(slug_id)
        return await _dip_stream_bab(product_id, "2", False)

    @app.get("/dip/{slug_id}/bab2/download")
    async def dip_public_bab2_download(slug_id: str):
        product_id = extract_id_from_slug(slug_id)
        return await _dip_stream_bab(product_id, "2", True)

    @app.get("/dip/{slug_id}/bab3")
    async def dip_public_bab3(slug_id: str):
        product_id = extract_id_from_slug(slug_id)
        return await _dip_stream_bab(product_id, "3", False)

    @app.get("/dip/{slug_id}/bab3/download")
    async def dip_public_bab3_download(slug_id: str):
        product_id = extract_id_from_slug(slug_id)
        return await _dip_stream_bab(product_id, "3", True)

    @app.get("/dip/{slug_id}/bab4")
    async def dip_public_bab4(slug_id: str):
        product_id = extract_id_from_slug(slug_id)
        return await _dip_stream_bab(product_id, "4", False)

    @app.get("/dip/{slug_id}/bab4/download")
    async def dip_public_bab4_download(slug_id: str):
        product_id = extract_id_from_slug(slug_id)
        return await _dip_stream_bab(product_id, "4", True)

    @app.get("/dip/{slug_id}/bab2/zip")
    async def dip_public_bab2_zip(slug_id: str):
        """Stream ZIP Bab II (folder per bahan baku) lewat backend, tanpa login."""
        product_id = extract_id_from_slug(slug_id)
        if not _dip_public_check_product(product_id):
            raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")
        try:
            return await download_bab2_zip(product_id, None)
        except HTTPException:
            raise
        except Exception as e:
            import traceback
            print(f"\n🔴 [PUBLIC DIP ZIP ERROR] Gagal generate ZIP Bab 2 untuk product_id={product_id}")
            print(f"   Error: {e}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="Dokumen sedang tidak dapat diproses. Silakan coba beberapa saat lagi.")
