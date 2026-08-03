from fastapi import FastAPI, Request, Form, HTTPException, Response, File, UploadFile, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List
from app.database import supabase
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from zoneinfo import ZoneInfo
from supabase import create_client
import os
import io
import httpx
from xhtml2pdf import pisa
from pypdf import PdfReader, PdfWriter

from dotenv import load_dotenv
load_dotenv()
# Zona waktu bisnis (WIB) — dipakai buat semua logika berbasis "hari ini"
# (kode FSP, hitungan revisi) biar gak geser gara-gara server jalan di UTC.
WIB = ZoneInfo("Asia/Jakarta")
import uuid

app = FastAPI(title="DIP Kosmetik Automation")

# Setup static files (Tailwind CSS) dan Jinja2 Templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

def clean_pct(value, decimals=4):
    """Bulatkan dulu buat buang floating point noise, baru hilangkan trailing zero."""
    if value is None:
        return "0"
    try:
        # Bulatkan dulu ke n desimal pakai Decimal biar presisi (bukan round() bawaan Python)
        d = Decimal(str(value)).quantize(Decimal('1.' + '0' * decimals), rounding=ROUND_HALF_UP)
        d = d.normalize()
        return format(d, 'f')
    except Exception:
        return str(value)

# Data kop surat per perusahaan — sesuaikan detail PT Heka dengan data resmi yang benar
COMPANY_INFO = {
    "PT Erfi": {
        "nama": "PT. ERFI KARYA ABADI",
        "alamat": "Office : Jl. Kampung Klapanunggal, RT 001/RW 01. Desa Klapanunggal Kec. Klapanunggal Bogor, Indonesia",
        "email": "contact@erfikaryaabadi.com",
        "website": "www.erfikaryaabadi.com",
        "logo": "/static/images/logo_erfi.png"
    },
    "PT Heka": {
        "nama": "PT. HARAKA ERFI KOSMETINDO ABADI",          
        "alamat": "Office : Jl. Kampung Klapanunggal, RT 001/RW 01. Desa Klapanunggal Kec. Klapanunggal Bogor, Indonesia",
        "Telp": "081281938715", 
        "logo": "/static/images/logo_heka.png"
    }
}

templates.env.filters["clean_pct"] = clean_pct

@app.on_event("startup")
async def print_routes():
    for route in app.routes:
        if hasattr(route, "methods"):
            print(f"{list(route.methods)} - {route.path}")
        else:
            print(f"[MOUNT/STATIC] - {route.path}")

# ================= FUNCTION Login (REPLACEMENT) =================
async def get_current_user(request: Request):
    # 1. Ambil cookie token dari browser
    token_cookie = request.cookies.get("access_token")
    if not token_cookie:
        # PENTING: Pakai raise HTTPException 307 biar FastAPI paksa browser redirect!
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
        )
    
    try:
        # 2. Ekstrak token aslinya
        token = token_cookie.replace("Bearer ", "")
        
        # 3. Minta data user ke Supabase Auth
        user_auth = supabase.auth.get_user(token)
        user_data = user_auth.user
        
        # 4. Tarik info nama & role dari tabel profiles yg baru lu buat
        profile_res = supabase.table("profiles").select("full_name", "role").eq("id", user_data.id).execute()
        
        # Default value aman kalau data profile di DB lu belum lengkap
        user_role = "staff"
        full_name = "User Lab"
        
        if profile_res.data:
            user_role = profile_res.data[0].get("role", "staff")
            full_name = profile_res.data[0].get("full_name", "User Lab")
            
        # Balikin dictionary komplit biar bisa dipakai di route-route lain ntar
        return {
            "id": user_data.id,
            "email": user_data.email,
            "full_name": full_name,
            "role": user_role
        }
        
    except Exception as e:
        print(f"Token invalid atau expired: {e}")
        # Kalo tokennya ngaco/expired, hapus cookie dan tendang balik ke login.
        # PENTING: instruksi hapus cookie harus nempel di header HTTPException yang
        # di-raise, bukan di response terpisah yang nggak pernah dipakai/dibuang.
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={
                "Location": "/login",
                "Set-Cookie": "access_token=; Max-Age=0; Path=/; HttpOnly; SameSite=lax"
            }
        )


# ================= 1. ROUTE TAMPILAN LOGIN =================
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # Cek dulu kalau tokennya udah ada di cookie, langsung lempar ke dashboard
    if request.cookies.get("access_token"):
        return RedirectResponse(url="/", status_code=303)
        
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={}
    )

# ================= 2. ROUTE PROSES LOGIN (POST) =================
from supabase import create_client
import os

@app.post("/login")
async def login_submit(
    response: Response,
    email: str = Form(...), # Menangkap input dari form (bisa email ataupun username)
    password: str = Form(...)
):
    try:
        login_identifier = email.strip()
        
        # 1. Ambil langsung variabel dari environment yang udah di-load sempurna di atas
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        # Validasi darurat biar keliatan di log terminal lu kalau env lu masih kosong
        if not supabase_url or not supabase_service_key:
            print("❌ Eror: SUPABASE_URL atau SUPABASE_SERVICE_ROLE_KEY di file .env kagak kebaca men!")
            
        supabase_admin = create_client(supabase_url, supabase_service_key)
        
        # JIKA YANG DIINPUT BUKAN EMAIL (GA ADA TANDA @)
        if "@" not in login_identifier:
            # Cari di tabel profiles menggunakan client admin bebas hambatan
            profile_query = supabase_admin.table("profiles").select("id").eq("full_name", login_identifier.lower()).execute()
            
            if profile_query.data:
                # Kalo username ketemu, ambil email aslinya via admin auth service
                user_id = profile_query.data[0]["id"]
                user_auth_data = supabase_admin.auth.admin.get_user_by_id(user_id)
                login_identifier = user_auth_data.user.email
            else:
                # Kalo ga ketemu di profiles, fallback otomatis pake domain kantor
                login_identifier = f"{login_identifier.lower()}@erfi.com"
            
        # 2. PENTING: sign-in HARUS pakai client terpisah, BUKAN client global `supabase`.
        # SDK supabase-py otomatis nempelin sesi user yang baru login ke client yang
        # dipakai buat sign_in. Client `supabase` global dipakai bareng2 di SELURUH
        # aplikasi pakai service_role key (biar bypass RLS) -- kalau sign_in numpang
        # di situ, sesi service_role-nya ketiban sesi user biasa, dan abis itu SEMUA
        # request lain (termasuk punya orang lain) ikut kena RLS user yang baru login.
        # Makanya kemarin /admin/users cuma nampilin 1 akun (akun yang lagi login).
        # `supabase_admin` di atas aman dipake karena dia dibikin fresh tiap request
        # (variable lokal), bukan client yang di-share ke seluruh server kayak `supabase`.
        auth_response = supabase_admin.auth.sign_in_with_password({
            "email": login_identifier,
            "password": password
        })
        
        session_token = auth_response.session.access_token
        redirect = RedirectResponse(url="/", status_code=303)
        redirect.set_cookie(
            key="access_token",
            value=f"Bearer {session_token}",
            httponly=True,
            max_age=86400,
            samesite="lax"
        )
        return redirect

    except Exception as e:
        print(f"Gagal login: {e}")
        return RedirectResponse(url="/login?error=invalid_credentials", status_code=303)

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    # Hapus cookie token yang tersimpan di browser
    response.delete_cookie(key="access_token")
    return response

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: dict = Depends(get_current_user)):
    try:
        # 1. Mengambil data produk master terbaru
        response_prod = supabase.table("products").select("*").order("created_at", desc=True).execute()
        products = response_prod.data or []
        
        # 2. Tambahan: Tarik 5 data pengajuan sample (FSP) paling baru
        response_sample = supabase.table("sample_submissions") \
            .select("id, sample_code, product_name, company, created_at, revision_number") \
            .order("created_at", desc=True) \
            .limit(5) \
            .execute()
        recent_samples = response_sample.data or []
        
    except Exception as e:
        print(f"Gagal ambil data dashboard: {e}")
        products = []
        recent_samples = []
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html", 
        # Oper variabel 'products' dan 'recent_samples' ke HTML
        context={
            "request": request, 
            "products": products, 
            "recent_samples": recent_samples,
            "user": current_user
        }
    )

@app.get("/products/{product_id}", response_class=HTMLResponse)
async def product_detail(request: Request, product_id: str):
    prod_resp = supabase.table("products").select("*").eq("id", product_id).single().execute()
    
    formula_resp = supabase.table("product_formula_lines") \
        .select("*, raw_materials(nama_dagang, kode_bahan_baku)") \
        .eq("product_id", product_id).execute()
        
    rm_resp = supabase.table("raw_materials").select("id, nama_dagang, kode_bahan_baku").order("nama_dagang").execute()
        
    return templates.TemplateResponse(
        request=request,
        name="formula_builder.html", 
        context={
            "product": prod_resp.data, 
            "formula": formula_resp.data,
            "raw_materials": rm_resp.data  
        }
    )

@app.get("/products/{product_id}/report", response_class=HTMLResponse)
async def ingredient_report(request: Request, product_id: str):
    prod_resp = supabase.table("products").select("nama_produk, no_na_produk").eq("id", product_id).single().execute()
    report_resp = supabase.table("view_ingredient_reports").select("*").eq("product_id", product_id).execute()
    
    return templates.TemplateResponse(
        request=request,
        name="ingredient_report.html", 
        context={"product": prod_resp.data, "ingredients": report_resp.data}
    )

@app.get("/raw-materials", response_class=HTMLResponse)
async def raw_materials_page(request: Request):
    rm_resp = supabase.table("raw_materials").select("*, raw_material_components(*)").order("nama_dagang").execute()
    
    success_msg = request.cookies.get("success_msg")
    error_msg = request.cookies.get("error_msg")
    
    try:
        query_batches = (
            supabase.table("raw_material_batches")
            .select("""
                *,
                raw_materials (
                    nama_dagang,
                    produsen,
                    msds_file_url,
                    spec_parameters,
                    raw_material_components (
                        inci_name,
                        cas_number
                    )
                )
            """)
            .execute()
        )
        batches_data = query_batches.data
        print(batches_data[0] if batches_data else "KOSONG")
    except Exception as e:
        print(f"Gagal ambil data batches: {e}")
        batches_data = []
    
    response = templates.TemplateResponse(
        request=request,
        name="raw_materials.html",
        context={
            "raw_materials": rm_resp.data,
            "batches": batches_data,
            "success_msg": success_msg,
            "error_msg": error_msg
        }
    )
    
    if success_msg:
        response.delete_cookie("success_msg")
    if error_msg:
        response.delete_cookie("error_msg")
        
    return response

@app.post("/raw-materials/add")
async def add_raw_material(
    request: Request,
    nama_dagang: str = Form(...),
    kode_bahan_baku: str = Form(...),
    tipe: str = Form(...),
    produsen: str = Form(None),
    msds_file: UploadFile = File(None),
    inci_name: list[str] = Form(None),
    cas_number: list[str] = Form(None),
    function: list[str] = Form(None),
    percent_internal: list[float] = Form(None),
    spec_parameters: str = Form("[]"), # 👈 SUNTIK PARAMETER BARU DI SINI
    current_user: dict = Depends(get_current_user)
):
    # 1. Parsing string JSONB dari frontend ke Python Object
    import json
    try:
        parsed_specs = json.loads(spec_parameters)
    except Exception as e:
        print(f"Gagal parsing spec_parameters pas add: {e}")
        parsed_specs = []

    # 2. Masukkan ke dalam payload insert raw_materials lu
    insert_payload = {
        "nama_dagang": nama_dagang,
        "kode_bahan_baku": kode_bahan_baku,
        "tipe": tipe,
        "produsen": produsen,
        "spec_parameters": parsed_specs 
    }
    # KITA PAKSA TULISAN INI KELUAR DI TERMINAL APAPUN YANG TERJADI
    print("\n" + "="*40)
    print("LOG INI HARUSNYA MUNCUL DI TERMINAL!")
    print(f"Nama Dagang: {nama_dagang}")
    print(f"Produsen: {produsen}")
    print(f"File MSDS: {msds_file.filename if msds_file else 'Kosong'}")
    print("="*40 + "\n")

    kode_check = kode_bahan_baku.strip()
    existing_rm = supabase.table("raw_materials").select("id").eq("kode_bahan_baku", kode_check).execute()
    
    # JIKA GAGAL (Kode Dobel)
    if existing_rm.data:
        response = RedirectResponse(url="/raw-materials", status_code=303)
        response.set_cookie("error_msg", f"Kode '{kode_check}' udah terdaftar. Gunakan kode lain.")
        return response
        
    # --- LOGIC UPLOAD MSDS KE SUPABASE STORAGE ---
    msds_url = None
    if msds_file and msds_file.filename:
        try:
            file_bytes = await msds_file.read()
            # Bersihkan nama kode buat nama file agar aman di URL
            clean_kode = "".join(c for c in kode_check if c.isalnum() or c in ('-', '_')).strip()
            file_path = f"msds/msds_{clean_kode}.pdf"
            
            # Upload fisik file ke bucket 'raw-material-docs'
            supabase.storage.from_("raw-material-docs").upload(
                path=file_path,
                file=file_bytes,
                file_options={"content-type": msds_file.content_type}
            )
            
            # Dapatkan Link Public-nya
            msds_url = supabase.storage.from_("raw-material-docs").get_public_url(file_path)
        except Exception as e:
            print(f"Gagal upload MSDS: {e}")
            # Lanjut proses tanpa menggagalkan insert jika upload bermasalah

    # --- INSERT DATA UTAMA (Ditambah Produsen & MSDS URL) ---
    rm_resp = supabase.table("raw_materials").insert({
        "nama_dagang": nama_dagang,
        "kode_bahan_baku": kode_bahan_baku,
        "tipe": tipe,
        "produsen": produsen,        # <-- Masuk ke database
        "msds_file_url": msds_url    # <-- Simpan URL link filenya
    }).execute()
    new_rm_id = rm_resp.data[0]["id"]

    if tipe == "single":
        given_inci = inci_name[0].strip() if (inci_name and inci_name[0]) else ""
        comp_data = {
            "raw_material_id": new_rm_id,
            "inci_name": given_inci if given_inci else nama_dagang, 
            "cas_number": cas_number[0] if cas_number else None,
            "function": function[0] if function else None,
            "percent_internal": 100.0
        }
        supabase.table("raw_material_components").insert(comp_data).execute()
    
    elif tipe == "komposit" and inci_name:
        components = []
        for i in range(len(inci_name)):
            if inci_name[i].strip():
                components.append({
                    "raw_material_id": new_rm_id,
                    "inci_name": inci_name[i],
                    "cas_number": cas_number[i] if i < len(cas_number) else None,
                    "function": function[i] if i < len(function) else None,
                    "percent_internal": percent_internal[i]
                })
        if components:
            supabase.table("raw_material_components").insert(components).execute()

    # JIKA BERHASIL: Set cookie tanda sukses lalu redirect
    response = RedirectResponse(url="/raw-materials", status_code=303)
    response.set_cookie("success_msg", f"Mantap! Bahan baku '{nama_dagang}' berhasil ditambahkan.")
    return response

@app.post("/raw-materials/edit/{rm_id}")
async def edit_raw_material(
    rm_id: str,
    nama_dagang: str = Form(...),
    kode_bahan_baku: str = Form(...),
    tipe: str = Form(...),
    inci_name: List[str] = Form(None),
    cas_number: List[str] = Form(None),
    function: List[str] = Form(None),
    percent_internal: List[float] = Form(None),
    msds_file: UploadFile = File(None),
    spec_parameters: str = Form("[]"), # <-- SUNTIK PARAMETER BARU
    current_user: dict = Depends(get_current_user)
):
    print("\n" + "="*40)
    print("LOG INI MUNCUL PAS LU KLIK EDIT!")
    print(f"ID Bahan Baku: {rm_id}")
    print(f"Nama Dagang: {nama_dagang}")
    print(f"File MSDS Baru: {msds_file.filename if msds_file else 'Tidak Ada File Baru'}")
    print("="*40 + "\n")
    
    kode_check = kode_bahan_baku.strip()
    existing_rm = supabase.table("raw_materials").select("id").eq("kode_bahan_baku", kode_check).neq("id", rm_id).execute()
    
    if existing_rm.data:
        raise HTTPException(status_code=400, detail=f"Gagal Edit! Kode '{kode_check}' sudah dipakai oleh bahan baku lain.")
    
    # PARSING STRING JSONB DARI FRONTEND KE PYTHON OBJECT
    import json
    try:
        parsed_specs = json.loads(spec_parameters)
    except Exception as e:
        print(f"Gagal parsing spec_parameters: {e}")
        parsed_specs = []

    # 2. SIAPKAN DICTIONARY DATA UNTUK UPDATE TABLE RAW_MATERIALS
    update_data = {
        "nama_dagang": nama_dagang,
        "kode_bahan_baku": kode_bahan_baku,
        "tipe": tipe,
        "spec_parameters": parsed_specs # <-- SUNTIK DATA BATCH KE KOLOM JSONB
    }
    
    # 3. LOGIKA PROSES UPLOAD FILE MSDS (JIKA USER UPLOAD FILE BARU)
    if msds_file and msds_file.filename:
        try:
            file_contents = await msds_file.read()
            clean_filename = f"msds_{rm_id}_{msds_file.filename.replace(' ', '_')}"
            storage_path = f"msds/{clean_filename}"
            
            supabase.storage.from_("raw-material-docs").upload(
                path=storage_path,
                file=file_contents,
                file_options={"content-type": msds_file.content_type, "upsert": "true"}
            )
            
            msds_url = supabase.storage.from_("raw-material-docs").get_public_url(storage_path)
            update_data["msds_file_url"] = msds_url
            print(f"Sukses upload MSDS baru ke: {msds_url}")
            
        except Exception as e:
            print(f"Gagal proses upload MSDS: {e}")
    
    # 4. JALANKAN UPDATE KE TABEL RAW_MATERIALS
    supabase.table("raw_materials").update(update_data).eq("id", rm_id).execute()

    # --- Sisa kode management komponen INCI lu di bawah biarkan utuh ---
    supabase.table("raw_material_components").delete().eq("raw_material_id", rm_id).execute()
    
    if tipe == "single":
        given_inci = inci_name[0].strip() if (inci_name and inci_name[0]) else ""
        comp_data = {
            "raw_material_id": rm_id,
            "inci_name": given_inci if given_inci else nama_dagang,
            "cas_number": cas_number[0] if cas_number else None,
            "function": function[0] if function else None,
            "percent_internal": 100.0
        }
        supabase.table("raw_material_components").insert(comp_data).execute()
        
    elif tipe == "komposit" and inci_name:
        components = []
        for i in range(len(inci_name)):
            if inci_name[i].strip():
                components.append({
                    "raw_material_id": rm_id,
                    "inci_name": inci_name[i],
                    "cas_number": cas_number[i] if i < len(cas_number) else None,
                    "function": function[i] if i < len(function) else None,
                    "percent_internal": percent_internal[i]
                })
        if components:
            supabase.table("raw_material_components").insert(components).execute()

    return RedirectResponse(url="/raw-materials", status_code=303)

@app.get("/raw-materials/delete/{rm_id}")
async def delete_raw_material(rm_id: str):
    # Cek dulu apakah bahan baku ini masih dipakai di formula produk manapun
    usage_check = supabase.table("product_formula_lines").select("id").eq("raw_material_id", rm_id).execute()

    if usage_check.data:
        jumlah_pemakaian = len(usage_check.data)
        return RedirectResponse(
            url=f"/raw-materials?error=Bahan+baku+ini+masih+dipakai+di+{jumlah_pemakaian}+formula+produk.+Hapus+dari+formula+dulu+sebelum+menghapus+bahan+baku.",
            status_code=303
        )

    try:
        # Hapus komponen internal dulu (kalau bahan komposit)
        supabase.table("raw_material_components").delete().eq("raw_material_id", rm_id).execute()
        supabase.table("raw_materials").delete().eq("id", rm_id).execute()
    except Exception as e:
        return RedirectResponse(url=f"/raw-materials?error=Gagal+menghapus:+{str(e)}", status_code=303)

    return RedirectResponse(url="/raw-materials?success=Bahan+baku+berhasil+dihapus", status_code=303)

@app.post("/raw-materials/batches/add")
async def add_material_batch(
    request: Request,
    raw_material_id: str = Form(...),
    no_batch: str = Form(...),
    supplier: str = Form(...),
    tanggal_terima_sampel: str = Form(...),
    tanggal_ed: str = Form(...),
    kesimpulan: str = Form(...),
    tanggal_sampling: str = Form(None),
    qc_signer: str = Form(None),
    qa_signer: str = Form(None),
    qc_results: str = Form("[]"),
    harga_per_kg: float = Form(0.0),
    coa_file: UploadFile = File(None),
    halal_file: UploadFile = File(None),
    current_user: dict = Depends(get_current_user) # Memastikan auth login tetap sinkron
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
                file_options={"content-type": coa_file.content_type, "upsert": "true"}
            )
            coa_url = supabase.storage.from_("raw-material-docs").get_public_url(coa_path)
            print(f"--> Sukses upload CoA ke: {coa_url}")
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
                file_options={"content-type": halal_file.content_type, "upsert": "true"}
            )
            halal_url = supabase.storage.from_("raw-material-docs").get_public_url(halal_path)
            print(f"--> Sukses upload Halal ke: {halal_url}")
        except Exception as e:
            print(f"Gagal upload Halal Cert: {e}")

    # 4. Simpan record data lengkap ke tabel raw_material_batches
    batch_data = {
        "raw_material_id": raw_material_id,
        "no_batch": no_batch.strip(),
        "supplier": supplier.strip(),
        "harga_per_kg": harga_per_kg,
        "tanggal_terima_sampel": tanggal_terima_sampel,
        "tanggal_sampling": tanggal_sampling if tanggal_sampling else None,
        "tanggal_ed": tanggal_ed,
        "kesimpulan": kesimpulan,
        "qc_signer": qc_signer.strip() if qc_signer else None,
        "qa_signer": qa_signer.strip() if qa_signer else None,
        "hasil_pemerian": "-", # Nilai default untuk kolom legasi fisik
        "coa_file_url": coa_url,
        "halal_batch_file_url": halal_url,
        "qc_results": parsed_qc # 👈 Array hasil uji lab aktual masuk ke kolom JSONB ini
    }

    try:
        supabase.table("raw_material_batches").insert(batch_data).execute()
        print("--> Data Batch berhasil masuk ke Database!")
    except Exception as e:
        print(f"Gagal insert ke DB: {e}")

    # Redirect balik ke halaman utama bahan baku
    return RedirectResponse(url="/raw-materials", status_code=303)

@app.post("/products/add")
async def add_product(
    nama_produk: str = Form(...),
    perusahaan: str = Form(...),
    nama_customer: str = Form(None),
    sediaan: str = Form(None),
    warna: str = Form(None),
    kemasan: str = Form(None),
    netto: str = Form(None),
    no_na_produk: str = Form(None),
    status_na: str = Form("belum_terdaftar"),
    acc_sampel: str = Form(None),
    tanggal_text_design: str = Form(None),
    teks_marketing: str = Form(None),
    cara_pakai: str = Form(None),
    current_user: dict = Depends(get_current_user)
):
    # Bersihkan input tanggal kosong menjadi None agar Supabase tidak error
    acc_sampel_val = acc_sampel.strip() if acc_sampel else None
    if acc_sampel_val == "":
        acc_sampel_val = None

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
        "acc_sampel": acc_sampel_val,
        "tanggal_text_design": tanggal_text_design or None,
        "teks_marketing": teks_marketing,
        "cara_pakai": cara_pakai
    }
    
    supabase.table("products").insert(product_data).execute()
    return RedirectResponse(url="/", status_code=303)

@app.post("/products/{product_id}/formula/save")
async def save_product_formula(
    product_id: str,
    raw_material_id: List[str] = Form(None),
    percentage: List[float] = Form(None)
):
    supabase.table("product_formula_lines").delete().eq("product_id", product_id).execute()

    if raw_material_id and percentage:
        lines = []
        for i in range(len(raw_material_id)):
            if raw_material_id[i].strip():
                lines.append({
                    "product_id": product_id,
                    "raw_material_id": raw_material_id[i],
                    "percent_in_formula": percentage[i] 
                })
        if lines:
            supabase.table("product_formula_lines").insert(lines).execute()

    return RedirectResponse(url=f"/products/{product_id}", status_code=303)

@app.get("/products/{product_id}/inci-breakdown/report", response_class=HTMLResponse)
async def generate_inci_report(request: Request, product_id: str):
    prod_resp = supabase.table("products").select("*").eq("id", product_id).single().execute()
    formula_resp = supabase.table("product_formula_lines").select("*").eq("product_id", product_id).execute()
    
    inci_totals = {}
    
    if formula_resp.data:
        for line in formula_resp.data:
            pct_in_formula = float(line.get("percent_in_formula") or 0)
            rm_id = line.get("raw_material_id")
            
            comp_resp = supabase.table("raw_material_components").select("*").eq("raw_material_id", rm_id).execute()
            
            if comp_resp.data:
                for comp in comp_resp.data:
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
            "product": prod_resp.data,
            "inci_list": sorted_inci
        }
    )

@app.get("/products/{product_id}/qualitative-quantitative", response_class=HTMLResponse)
async def qualitative_quantitative_report(request: Request, product_id: str):
    product_resp = supabase.table("products").select("*").eq("id", product_id).single().execute()
    product = product_resp.data

    lines_resp = supabase.table("product_formula_lines") \
        .select("*, raw_materials(*)") \
        .eq("product_id", product_id) \
        .execute()
    
    breakdown_resp = supabase.table("raw_material_components") \
        .select("*") \
        .execute()
    all_inci_items = breakdown_resp.data

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
        raw_mat_id = line.get("raw_material_id")
        
        components = [item for item in all_inci_items if item.get("raw_material_id") == raw_mat_id]
        
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
                    "function": comp.get("function") or "-",
                    "pct_ww": clean_pct
                })
        else:
            clean_line_pct = float(Decimal(str(line_pct)).normalize())
            grouped_trade[group_key].append({
                "inci_name": nama_dagang_str,
                "function": "-",
                "pct_ww": clean_line_pct
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
            inci_name = comp["inci_name"]
            if inci_name not in grouped_pure:
                grouped_pure[inci_name] = {
                    "inci_name": inci_name,
                    "function": comp["function"],
                    # Gunakan Decimal('0.0') sebagai inisialisasi awal agar presisi
                    "pct_ww_decimal": Decimal('0.0') 
                }
            # Jumlahkan dengan tipe data Decimal murni
            grouped_pure[inci_name]["pct_ww_decimal"] += Decimal(str(comp["pct_ww"]))

    # KUNCI PERBAIKAN: Konversi hasil akhir ke float yang bersih setelah selesai dijumlahkan
    pure_breakdown = []
    for item in grouped_pure.values():
        clean_sum = float(item["pct_ww_decimal"].normalize())
        pure_breakdown.append({
            "inci_name": item["inci_name"],
            "function": item["function"],
            "pct_ww": clean_sum
        })

    clean_product = {}
    if isinstance(product, list) and len(product) > 0:
        clean_product = product[0]
    elif isinstance(product, dict):
        clean_product = product
        
    final_product = {str(k): (str(v) if v is not None else "") for k, v in clean_product.items()}

    # Ambil data kop surat sesuai perusahaan produk ini, fallback ke PT Erfi kalau kosong/tidak dikenali
    company = COMPANY_INFO.get(final_product.get("perusahaan"), COMPANY_INFO["PT Erfi"])

    return templates.TemplateResponse(
        request=request,
        name="qualitative_quantitative.html",
        context={
            "product": final_product,
            "trade_breakdown": trade_breakdown,
            "pure_breakdown": pure_breakdown,
            "company": company
        }
    )

# =====================================================================
#           FASE 2B: GENERATOR DOKUMEN BAB II (PDF GABUNGAN)
# =====================================================================
@app.get("/products/{product_id}/bab2/download")
async def download_bab2_document(product_id: str):
    # 1. Ambil data produk
    product_resp = supabase.table("products").select("*").eq("id", product_id).single().execute()
    product = product_resp.data
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan.")

    perusahaan = product.get("perusahaan") or "PT Erfi"

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

    # 3. Per bahan baku, tarik data batch TERBARU (kesepakatan: pakai batch terbaru)
    materials_data = []
    for rm in raw_materials:
        batch_resp = supabase.table("raw_material_batches") \
            .select("*") \
            .eq("raw_material_id", rm["id"]) \
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

    # 5. Render bagian yang di-generate (Checklist + Spesifikasi + Catatan) jadi HTML -> PDF
    html_content = templates.env.get_template("bab2_generated.html").render(
        product=product,
        materials_data=materials_data
    )

    generated_pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(src=html_content, dest=generated_pdf_buffer)
    if pisa_status.err:
        raise HTTPException(status_code=500, detail="Gagal generate PDF dari data Bab II.")
    generated_pdf_buffer.seek(0)

    # 6. Gabungin semua PDF jadi satu: [Generated] + [SOP CPKB] + [CoA per bahan baku]
    writer = PdfWriter()

    reader_generated = PdfReader(generated_pdf_buffer)
    for page in reader_generated.pages:
        writer.add_page(page)

    async with httpx.AsyncClient() as client:
        # 6a. SOP CPKB
        if sop_url:
            try:
                resp = await client.get(sop_url, timeout=30)
                resp.raise_for_status()
                sop_reader = PdfReader(io.BytesIO(resp.content))
                for page in sop_reader.pages:
                    writer.add_page(page)
            except Exception as e:
                print(f"Gagal ambil SOP CPKB ({perusahaan}): {e}")

        # 6b. CoA tiap bahan baku (dari batch terbaru masing-masing)
        for item in materials_data:
            batch = item["batch"]
            coa_url = batch.get("coa_file_url") if batch else None
            if coa_url:
                try:
                    resp = await client.get(coa_url, timeout=30)
                    resp.raise_for_status()
                    coa_reader = PdfReader(io.BytesIO(resp.content))
                    for page in coa_reader.pages:
                        writer.add_page(page)
                except Exception as e:
                    print(f"Gagal ambil CoA bahan baku {item['material'].get('nama_dagang')}: {e}")

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

# 1. Halaman Form Edit Produk
@app.get("/products/{product_id}/edit", response_class=HTMLResponse)
async def edit_product_page(request: Request, product_id: str):
    prod_resp = supabase.table("products").select("*").eq("id", product_id).single().execute()
    return templates.TemplateResponse(
        request=request,
        name="edit_product.html",
        context={"product": prod_resp.data}
    )

# 2. Proses Simpan Perubahan Info Produk (PERBAIKAN: Kolom disinkronkan dengan add_product)
@app.post("/products/{product_id}/edit")
async def update_product(
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
    acc_sampel: str = Form(None),
    tanggal_text_design: str = Form(None),
    teks_marketing: str = Form(None),
    cara_pakai: str = Form(None),
    status_progress: str = Form("R&D / Sample Phase"),
    current_user: dict = Depends(get_current_user)
):
    # 2. Bersihin input tanggal biar tipenya pas di database
    acc_sampel_val = acc_sampel.strip() if acc_sampel else None
    if acc_sampel_val == "":
        acc_sampel_val = None

    supabase.table("products").update({
        "nama_produk": nama_produk,
        "perusahaan": perusahaan,
        "nama_customer": nama_customer,
        "sediaan": sediaan,
        "warna": warna,
        "netto": netto,          
        "kemasan": kemasan,
        "no_na_produk": no_na_produk,
        "status_na": status_na,
        "acc_sampel": acc_sampel_val,
        "tanggal_text_design": tanggal_text_design or None,
        "teks_marketing": teks_marketing,
        "cara_pakai": cara_pakai,
        "status_progress": status_progress 
    }).eq("id", product_id).execute()
    
    return RedirectResponse(url="/", status_code=303)

@app.get("/products/delete/{product_id}")
async def delete_product(product_id: str):
    try:
        # Hapus dulu baris formula terkait (kalau FK belum di-set CASCADE)
        supabase.table("product_formula_lines").delete().eq("product_id", product_id).execute()
        # Baru hapus produknya
        supabase.table("products").delete().eq("id", product_id).execute()
    except Exception as e:
        print(f"Gagal hapus produk {product_id}: {e}")
    return RedirectResponse(url="/", status_code=303)

@app.post("/sample-submissions/create")
async def create_sample_submission(
    request: Request,
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
    # Catatan tambahan dikirim sebagai form teks biasa dulu nanti kita bungkus ke JSON
    ph_value: str = Form(None),
    viscosity_value: str = Form(None),
    color_value: str = Form(None)
):
    final_product_id = None if not product_id else product_id
    if final_product_id:
        # Jalur kilat: Tarik data asli dari master produk
        # Kolom di tabel products namanya "perusahaan", bukan "company" (bug #2)
        prod_master = supabase.table("products").select("nama_produk", "perusahaan").eq("id", final_product_id).execute()
        if prod_master.data:
            final_product_name = prod_master.data[0]['nama_produk']
            final_company = prod_master.data[0]['perusahaan']
        else:
            # Fallback: product_id dikirim tapi nggak ketemu di database -> pakai input form manual
            final_product_name = product_name
            final_company = company
    else:
        # Jalur manual: Pakai inputan ketikan dari form
        final_product_name = product_name
        final_company = company

    today_str = datetime.now(WIB).strftime("%d-%m-%Y")
    
    # --- 1. LOGIKAHITUNG X.Y (OTOMATIS) ---
    # Cari tahu total produk berbeda hari ini untuk menentukan X
    # Cari tahu total percobaan untuk produk yang sama hari ini untuk menentukan Y
    # Untuk sementara lu bisa pakai dummy increment atau query count dari DB.
    try:
        # Ambil data submission khusus yang dibuat dari awal hari ini (WIB)
        start_of_day = datetime.now(WIB).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        today_submissions = supabase.table("sample_submissions") \
            .select("sample_code, product_name") \
            .gte("created_at", start_of_day) \
            .execute()
        
        existing_records = today_submissions.data or []
        
        # Cari urutan produk BERBEDA hari ini untuk nentuin nilai X
        distinct_products = list(dict.fromkeys([r['product_name'] for r in existing_records]))
        
        if final_product_name in distinct_products:
            x_index = distinct_products.index(final_product_name) + 1
        else:
            x_index = len(distinct_products) + 1
            
        # Cari total trial untuk produk yang SAMA khusus hari ini untuk nentuin nilai Y
        same_product_trials = [r for r in existing_records if r['product_name'] == final_product_name]
        y_index = len(same_product_trials) + 1
        
        sample_code = f"FSP/{today_str}/{x_index}.{y_index}" #[cite: 1]
        
        # Hitung nomor revisi kumulatif (all-time) untuk produk ini[cite: 1]
        all_time_trials = supabase.table("sample_submissions") \
            .select("id") \
            .eq("product_name", final_product_name) \
            .execute()
        
        revision_number = (len(all_time_trials.data) or 0) + 1 #[cite: 1]

    except Exception as e:
        print(f"Gagal hitung logic kode FSP otomatis: {e}")
        sample_code = f"FSP/{today_str}/1.1"
        revision_number = 1
    
    # --- 2. PENANGANAN AUTO-SAVE DRAFT KE MASTER PRODUSEN/MERK ---
    if brand_id == "new":
        try:
            # 2a. Cek dulu apakah nama produsen ini udah ada di master (biar ga duplikat)
            prod_check = supabase.table("producers") \
                .select("id") \
                .ilike("name", custom_producer.strip()) \
                .execute()
            
            if prod_check.data:
                producer_id = prod_check.data[0]['id']
            else:
                # Kalau belum ada, insert produsen baru ke master
                new_prod = supabase.table("producers") \
                    .insert({"name": custom_producer.strip()}) \
                    .execute()
                producer_id = new_prod.data[0]['id']
            
            # 2b. Cek apakah brand ini udah ada di bawah produsen tersebut
            brand_check = supabase.table("brands") \
                .select("id") \
                .eq("producer_id", producer_id) \
                .ilike("name", custom_brand.strip()) \
                .execute()
                
            if brand_check.data:
                final_brand_id = brand_check.data[0]['id']
            else:
                # Kalau belum ada, insert brand baru dengan relasi producer_id
                new_brnd = supabase.table("brands") \
                    .insert({
                        "producer_id": producer_id,
                        "name": custom_brand.strip()
                    }) \
                    .execute()
                final_brand_id = new_brnd.data[0]['id']
                
            # Tetap simpan log teks ketikan pertamanya di kolom draft buat backup histori
            draft_prod = custom_producer
            draft_brnd = custom_brand

        except Exception as e:
            print(f"Gagal auto-save master brand/producer: {e}")
            # Fallback aman jika query master gagal, tetep lolos sebagai draft murni
            final_brand_id = None
            draft_prod = custom_producer
            draft_brnd = custom_brand
    else:
        # Jika user milih brand resmi dari dropdown
        final_brand_id = brand_id
        draft_prod = None
        draft_brnd = None
    
    # --- 3. BUNGKUS JSON UNTUK CATATAN TAMBAHAN ---
    additional_notes = {
        "ph": ph_value,
        "viscosity": viscosity_value,
        "color": color_value
    }

    # 4. INSERT KE SUPABASE
    try:
        data_to_insert = {
            # ... data_to_insert lu yang lama tetep biarkan ...
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
        
        # Tambahkan .execute() dan tangkap hasilnya buat ambil ID dokumen baru
        result = supabase.table("sample_submissions").insert(data_to_insert).execute()
        new_id = result.data[0]['id']
        
    except Exception as e:
        print(f"Eror saat simpan form sample: {e}")
        raise HTTPException(status_code=500, detail="Gagal menyimpan dokumen.")
        
    # UBAH REDIRECT KE HALAMAN PREVIEW BERDASARKAN ID BARU
    return RedirectResponse(url=f"/sample-submissions/preview/{new_id}", status_code=303)

@app.get("/sample-submissions", response_class=HTMLResponse)
async def sample_submissions_list(request: Request, search: str = None):
    try:
        # Inisialisasi query dasar
        query = supabase.table("sample_submissions").select("*, brands(*, producers(*))")
        
        # Jika ada input di searchbar, filter berdasarkan kode dokumen atau nama produk
        if search:
            search_term = f"%{search}%"
            # Melakukan filter OR pada sample_code atau product_name
            query = query.or_(f"sample_code.ilike.{search_term},product_name.ilike.{search_term}")
        
        # Urutkan dari yang terbaru
        result = query.order("created_at", desc=True).execute()
        submissions = result.data or []
    except Exception as e:
        print(f"Gagal ambil list sample dengan search: {e}")
        submissions = []
        
    return templates.TemplateResponse(
        request=request,
        name="sample_list.html",
        context={"submissions": submissions, "search_value": search or ""}
    )

@app.get("/sample-submissions/form", response_class=HTMLResponse)
async def sample_submission_form(request: Request):
    try:
        brand_query = supabase.table("brands").select("*, producers(*)").execute()
        brands = brand_query.data or []
        
        # Kolom di tabel products namanya "perusahaan", bukan "company" (bug #2)
        product_query = supabase.table("products").select("id, nama_produk, netto, sediaan, kemasan, perusahaan").execute()
        products = product_query.data or []
    except Exception as e:
        print(f"Gagal ambil data pendukung form: {e}")
        brands, products = [], []
        
    return templates.TemplateResponse(
        request=request,
        name="sample_form.html",
        # Key "existing_products" harus sama persis kayak yang dipakai template (bug #1)
        context={"brands": brands, "existing_products": products}
    )


@app.get("/sample-submissions/preview/{submission_id}", response_class=HTMLResponse)
async def sample_submission_preview(request: Request, submission_id: str):
    try:
        # Ambil data submission spesifik beserta join brand & produsen
        query = supabase.table("sample_submissions") \
            .select("*, brands(*, producers(*))") \
            .eq("id", submission_id) \
            .execute()
            
        if not query.data:
            raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")
            
        submission = query.data[0]
    except Exception as e:
        print(f"Gagal ambil data preview: {e}")
        raise HTTPException(status_code=500, detail="Gagal memuat preview dokumen.")
        
    return templates.TemplateResponse(
        request=request,
        name="sample_preview.html",
        context={"s": submission}
    )

    # =====================================================================
#                     MODUL MANAJEMEN USER (ADMIN ONLY)
# =====================================================================

# 1. TAMPILAN HALAMAN UTAMA USER & REGISTER
@app.get("/admin/users", response_class=HTMLResponse)
async def manage_users_page(request: Request, current_user: dict = Depends(get_current_user)):
    # Proteksi: Cuma admin yang boleh masuk page ini
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Super Admin.")
        
    try:
        # Tarik semua data dari tabel profiles
        profiles_res = supabase.table("profiles").select("*").order("full_name").execute()
        users_list = profiles_res.data or []
    except Exception as e:
        print(f"Gagal ambil data profiles: {e}")
        users_list = []
        
    return templates.TemplateResponse(
        request=request,
        name="admin_users.html",
        context={"request": request, "user": current_user, "users": users_list}
    )

# CATATAN: Self-register publik (GET/POST /register) sengaja DIHAPUS.
# Alasan: app internal perusahaan dengan data sensitif (formula, harga, dokumen regulasi).
# Pembuatan akun sekarang cuma bisa lewat admin, lihat POST /admin/users/create di bawah.

# 1. PROSES ADMIN BIKIN AKUN USER BARU (KHUSUS ADMIN)
@app.post("/admin/users/create")
async def admin_create_user(
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("staff"),
    current_user: dict = Depends(get_current_user)
):
    # Proteksi: cuma admin yang boleh bikin akun baru
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Super Admin.")

    try:
        clean_username = username.strip().lower()
        clean_email = email.strip().lower()

        # Daftarin ke Supabase Auth Service, langsung confirmed (dibuat admin, bukan self-register)
        auth_res = supabase.auth.admin.create_user({
            "email": clean_email,
            "password": password,
            "email_confirm": True
        })

        new_uid = auth_res.user.id

        # Inject ke tabel profiles dengan role yang dipilih admin (default staff)
        supabase.table("profiles").insert({
            "id": new_uid,
            "full_name": clean_username,
            "role": role if role in ("staff", "admin") else "staff",
            "updated_at": "now()"
        }).execute()

        return RedirectResponse(url="/admin/users?status=create_success", status_code=303)

    except Exception as e:
        print(f"Gagal bikin user baru (admin): {e}")
        return RedirectResponse(url="/admin/users?error=create_failed", status_code=303)

# 3. PROSES UPDATE ROLE USER (POST)
@app.post("/admin/users/update-role")
async def update_user_role(
    target_uid: str = Form(...),
    new_role: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Akses ditolak!")
        
    try:
        # Update kolom role di tabel profiles berdasarkan UUID user yang dipilih
        supabase.table("profiles").update({"role": new_role, "updated_at": "now()"}).eq("id", target_uid).execute()
        return RedirectResponse(url="/admin/users?status=update_success", status_code=303)
    except Exception as e:
        print(f"Gagal update role: {e}")
        return RedirectResponse(url="/admin/users?error=update_failed", status_code=303)