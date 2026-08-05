from fastapi import FastAPI, Request, Form, HTTPException, Response, File, UploadFile, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List
from app.database import supabase
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date, timedelta
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

def _add_years(d: date, years: int) -> date:
    """Tambah tahun ke tanggal, aman buat kasus 29 Feb kena tahun non-kabisat."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)

def compute_status_na(tanggal_aktif_na, fallback_status: str) -> str:
    """
    Hitung status NA otomatis dari tanggal_aktif_na (NA BPOM berlaku 5 tahun sejak
    tanggal aktif). Kalau tanggal_aktif_na belum diisi, tetap pakai status manual
    yang lama (fallback_status) -- ini yang nutup kasus 'belum_terdaftar'.
    """
    if not tanggal_aktif_na:
        return fallback_status

    try:
        if isinstance(tanggal_aktif_na, str):
            start = datetime.strptime(tanggal_aktif_na[:10], "%Y-%m-%d").date()
        else:
            start = tanggal_aktif_na
    except Exception:
        return fallback_status

    expired_date = _add_years(start, 5)
    today = datetime.now(WIB).date()
    warning_date = expired_date - timedelta(days=180)  # ~6 bulan sebelum expired

    if today > expired_date:
        return "expired"
    elif today >= warning_date:
        return "akan_expired"
    else:
        return "aktif"

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
            
        # 2. Authenticate user
        auth_response = supabase_admin.auth.sign_in_with_password({
            "email": login_identifier,
            "password": password
        })
        
        # 💡 LOG SUCCESS LOGIN
        user_data = auth_response.user
        waktu_login = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("\n" + "="*50)
        print(f"🔑 [LOGIN SUCCESS]")
        print(f"   • User ID : {user_data.id}")
        print(f"   • Email   : {user_data.email}")
        print(f"   • Waktu   : {waktu_login}")
        print("="*50 + "\n")

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
        # 💡 LOG FAILED LOGIN
        waktu_gagal = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n❌ [LOGIN FAILED] Input: '{email}' | Waktu: {waktu_gagal} | Error: {e}\n")
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

        # 1b. Hitung ulang status_na otomatis dari tanggal_aktif_na (NA berlaku 5 tahun).
        # Kalau tanggal_aktif_na belum diisi, tetap pakai status_na manual yang lama.
        for p in products:
            p["status_na"] = compute_status_na(p.get("tanggal_aktif_na"), p.get("status_na") or "belum_terdaftar")
        
        # 2. Tambahan: Tarik 5 data pengajuan sample (FSP) paling baru
        response_sample = supabase.table("sample_submissions") \
            .select("id, sample_code, product_name, company, created_at, revision_number") \
            .order("created_at", desc=True) \
            .limit(5) \
            .execute()
        recent_samples = response_sample.data or []

        # 3. Tambahan: Data brands buat dropdown Merk di modal Tambah Produk
        response_brands = supabase.table("brands").select("id, name, producers(name)").order("name").execute()
        brands = response_brands.data or []
        
    except Exception as e:
        print(f"Gagal ambil data dashboard: {e}")
        products = []
        recent_samples = []
        brands = []
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html", 
        # Oper variabel 'products' dan 'recent_samples' ke HTML
        context={
            "request": request, 
            "products": products, 
            "recent_samples": recent_samples,
            "user": current_user,
            "brands": brands
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

@app.get("/products/{product_id}/bab3", response_class=HTMLResponse)
async def product_bab3_detail(
    request: Request,
    product_id: str,
    current_user: dict = Depends(get_current_user)
):
    # 1. Ambil data produk
    prod_resp = supabase.table("products").select("*, brands(name)").eq("id", product_id).single().execute()
    product = prod_resp.data
    
    if not product:
        raise HTTPException(status_code=404, detail="Produk kagak ketemu men!")
    
    perusahaan = product.get("perusahaan", "PT Erfi")

    # 2. Ambil dokumen SOP Master Perusahaan (Poin 3 & Poin 8)
    sop_resp = supabase.table("company_sop_documents").select("*").eq("perusahaan", perusahaan).execute()
    company_sop = sop_resp.data[0] if sop_resp.data else {}

    # 3. Ambil riwayat batch produk jadi (Poin 5)
    batches_resp = supabase.table("product_batches").select("*").eq("product_id", product_id).order("created_at", desc=True).execute()
    batches = batches_resp.data if batches_resp.data else []

    # 4. Ambil pesan notifikasi dari cookie
    success_msg = request.cookies.get("success_msg")
    error_msg = request.cookies.get("error_msg")

    response = templates.TemplateResponse(
        "product_detail.html",
        {
            "request": request,
            "product": product,
            "company_sop": company_sop,
            "batches": batches,
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
    spec_parameters: str = Form("[]"), 
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
    insert_payload["msds_file_url"] = msds_url
    rm_resp = supabase.table("raw_materials").insert(insert_payload).execute()
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
async def delete_raw_material(rm_id: str, current_user: dict = Depends(get_current_user)):
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
    tanggal_aktif_na: str = Form(None),
    acc_sampel: str = Form(None),
    tanggal_text_design: str = Form(None),
    teks_marketing: str = Form(None),
    cara_pakai: str = Form(None),
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
        "brand_id": brand_id if brand_id else None
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

    # 5. Render Checklist (halaman pembuka) jadi PDF sendiri
    checklist_html = templates.env.get_template("bab2_checklist.html").render(product=product)
    checklist_buffer = io.BytesIO()
    checklist_status = pisa.CreatePDF(src=checklist_html, dest=checklist_buffer)
    if checklist_status.err:
        raise HTTPException(status_code=500, detail="Gagal generate halaman Checklist Bab II.")
    checklist_buffer.seek(0)

    # 6. Gabungin PDF sesuai urutan request BPOM:
    # Checklist -> SOP CPKB -> per bahan baku: (Spesifikasi + Catatan -> CoA -> Halal -> MSDS)
    writer = PdfWriter()

    for page in PdfReader(checklist_buffer).pages:
        writer.add_page(page)

    async def append_pdf_from_url(client: httpx.AsyncClient, url: str, label: str):
        """Ambil PDF dari URL Supabase Storage dan tempelin ke writer. Gagal ambil 1 file gak boleh gagalin seluruh dokumen -> di-skip aja + di-print ke log."""
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
        # 6a. SOP CPKB (tetap di depan, setelah Checklist)
        await append_pdf_from_url(client, sop_url, f"SOP CPKB ({perusahaan})")

        # 6b. Per bahan baku, jadi 1 paket berurutan:
        # Spesifikasi + Catatan Pemeriksaan (di-generate) -> CoA -> Halal -> MSDS
        for idx, item in enumerate(materials_data, start=1):
            material = item["material"]
            batch = item["batch"]
            nama_bahan = material.get("nama_dagang", "?")

            # Render blok spesifikasi + catatan pemeriksaan khusus bahan baku ini
            material_html = templates.env.get_template("bab2_material_block.html").render(
                item=item, index=idx
            )
            material_buffer = io.BytesIO()
            material_status = pisa.CreatePDF(src=material_html, dest=material_buffer)
            if material_status.err:
                print(f"Gagal generate blok Spesifikasi+Catatan bahan baku {nama_bahan}")
            else:
                material_buffer.seek(0)
                for page in PdfReader(material_buffer).pages:
                    writer.add_page(page)

            coa_url = batch.get("coa_file_url") if batch else None
            halal_url = batch.get("halal_batch_file_url") if batch else None
            msds_url = material.get("msds_file_url")

            await append_pdf_from_url(client, coa_url, f"CoA bahan baku {nama_bahan}")
            await append_pdf_from_url(client, halal_url, f"Sertifikat Halal bahan baku {nama_bahan}")
            await append_pdf_from_url(client, msds_url, f"MSDS bahan baku {nama_bahan}")

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

# =====================================================================
#           GENERATOR DOKUMEN BAB I (DATA ADMINISTRATIF, PDF GABUNGAN)
# =====================================================================
@app.get("/products/{product_id}/bab1/download")
async def download_bab1_document(product_id: str):
    # 1. Ambil data produk
    product_resp = supabase.table("products").select("*").eq("id", product_id).single().execute()
    product = product_resp.data
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan.")

    perusahaan = product.get("perusahaan") or "PT Erfi"
    brand_id = product.get("brand_id")

    # 2. NIB & Sertifikat CPKB & Surat Tidak Pidana -> statis per PT
    nib_resp = supabase.table("nib_documents").select("file_url").eq("perusahaan", perusahaan).limit(1).execute()
    nib_url = nib_resp.data[0]["file_url"] if nib_resp.data else None

    cpkb_resp = supabase.table("sertifikat_cpkb_documents").select("file_url").eq("perusahaan", perusahaan).limit(1).execute()
    cpkb_url = cpkb_resp.data[0]["file_url"] if cpkb_resp.data else None

    pidana_resp = supabase.table("surat_tidak_pidana_documents").select("file_url").eq("perusahaan", perusahaan).limit(1).execute()
    pidana_url = pidana_resp.data[0]["file_url"] if pidana_resp.data else None

    # 3. Lisensi Merk & Hak Merk -> dari brand yang di-link ke produk (kalau ada)
    lisensi_url = None
    hak_merk_url = None
    if brand_id:
        brand_resp = supabase.table("brands").select("lisensi_merk_file_url, hak_merk_file_url").eq("id", brand_id).limit(1).execute()
        if brand_resp.data:
            lisensi_url = brand_resp.data[0].get("lisensi_merk_file_url")
            hak_merk_url = brand_resp.data[0].get("hak_merk_file_url")

    # 4. Surat No. Notifikasi BPOM -> langsung dari kolom produk
    notifikasi_url = product.get("no_notifikasi_file_url")

    status = {
        "nib": bool(nib_url),
        "cpkb": bool(cpkb_url),
        "lisensi": bool(lisensi_url),
        "hak_merk": bool(hak_merk_url),
        "tidak_pidana": bool(pidana_url),
        "notifikasi": bool(notifikasi_url)
    }

    # 5. Render Checklist jadi PDF
    checklist_html = templates.env.get_template("bab1_checklist.html").render(product=product, status=status)
    checklist_buffer = io.BytesIO()
    checklist_status = pisa.CreatePDF(src=checklist_html, dest=checklist_buffer)
    if checklist_status.err:
        raise HTTPException(status_code=500, detail="Gagal generate halaman Checklist Bab I.")
    checklist_buffer.seek(0)

    # 6. Gabung sesuai urutan: Checklist -> NIB -> Sertifikat CPKB -> Lisensi Merk -> Hak Merk -> Surat Tidak Pidana -> Surat No. Notifikasi BPOM
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
        await append_pdf_from_url(client, lisensi_url, "Lisensi Merk")
        await append_pdf_from_url(client, hak_merk_url, "Hak Merk")
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
    prod_resp = supabase.table("products").select("*, brands(name)").eq("id", product_id).single().execute()
    product = prod_resp.data
    if not product:
        raise HTTPException(status_code=404, detail="Produk kagak ketemu men!")

    perusahaan = product.get("perusahaan", "PT Erfi")

    # 2. AMBIL DATA FORMULA KUALITATIF & KUANTITATIF (POIN 1)
    # Catatan: nama tabel yang bener "raw_material_components" (bukan "compositions"),
    # dan kolom persentase-nya "percent_internal" -- ini yang dipakai konsisten di
    # seluruh app (Formula Builder, Ingredient Report, Bab II).
    formula_resp = supabase.table("product_formula_lines") \
        .select("percent_in_formula, raw_materials(*, raw_material_components(*))") \
        .eq("product_id", product_id) \
        .execute()

    raw_formula = formula_resp.data if formula_resp.data else []
    processed_formula = []

    for line in raw_formula:
        rm = line.get("raw_materials") or {}
        percent_total = float(line.get("percent_in_formula") or 0)
        compositions = rm.get("raw_material_components") or []
        
        if compositions and len(compositions) > 0:
            comp_list = []
            for comp in compositions:
                pct_in_rm = float(comp.get("percent_internal") or 100)
                calc_pct = round((pct_in_rm / 100.0) * percent_total, 4)
                comp_list.append({
                    "ingredient": comp.get("inci_name") or "-",
                    "function": comp.get("function") or "-",
                    "percent": calc_pct
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
                    "percent": percent_total
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

    # 5. RENDER COVER & FORMULA VIA TEMPLATE HTML
    template = templates.get_template("bab3_checklist.html")
    rendered_html = template.render({
        "product": product,
        "perusahaan": perusahaan,
        "company_sop": company_sop,
        "latest_batch": latest_batch,
        "processed_formula": processed_formula
    })

    cover_pdf_io = io.BytesIO()
    pisa.CreatePDF(io.StringIO(rendered_html), dest=cover_pdf_io)
    cover_pdf_io.seek(0)

    # 6. MERGE WITH ATTACHMENTS
    pdf_writer = PdfWriter()
    cover_reader = PdfReader(cover_pdf_io)
    for page in cover_reader.pages:
        pdf_writer.add_page(page)

    attachment_urls = [
        product.get("cara_pembuatan_file_url"),              # Poin 2
        company_sop.get("protap_no_batch_url"),              # Poin 3
        product.get("sistem_penomoran_batch_file_url"),      # Poin 4
        latest_batch.get("coa_file_url"),                    # Poin 5
        product.get("spek_produk_jadi_file_url"),            # Poin 6a
        product.get("spek_pengemas_file_url"),               # Poin 6b
        product.get("laporan_uji_sig_file_url"),             # Poin 7
        company_sop.get("protap_pemeriksaan_fg_url"),        # Poin 8
        product.get("protokol_stabilitas_file_url"),         # Poin 9
        product.get("hasil_stabilitas_file_url"),            # Poin 10
    ]

    async with httpx.AsyncClient() as client:
        for url in attachment_urls:
            if url:
                try:
                    res = await client.get(url, timeout=15.0)
                    if res.status_code == 200:
                        doc_reader = PdfReader(io.BytesIO(res.content))
                        for page in doc_reader.pages:
                            pdf_writer.add_page(page)
                except Exception as e:
                    print(f"[BAB 3 MERGE ERROR] Gagal mengunduh {url}: {e}")

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

@app.get("/products/{product_id}/bab4/download")
async def download_dip_bab4(
    product_id: str,
    current_user: dict = Depends(get_current_user)
):
    # 1. AMBIL DATA PRODUK
    prod_resp = supabase.table("products").select("*, brands(name)").eq("id", product_id).single().execute()
    product = prod_resp.data
    if not product:
        raise HTTPException(status_code=404, detail="Produk kagak ketemu men!")

    perusahaan = product.get("perusahaan", "PT Erfi")

    # 2. AMBIL SOP MASTER PERUSAHAAN (Poin 2 & Poin 3)
    company_sop = {}
    try:
        sop_resp = supabase.table("company_sop_documents").select("*").eq("perusahaan", perusahaan).execute()
        if sop_resp.data and len(sop_resp.data) > 0:
            company_sop = sop_resp.data[0]
    except Exception as e:
        print(f"[WARNING] Gagal/belum ada data company_sop_documents: {e}")

    # 3. RENDER CHECKLIST BAB 4 VIA TEMPLATE HTML
    template = templates.get_template("bab4_checklist.html")
    rendered_html = template.render({
        "product": product,
        "perusahaan": perusahaan,
        "company_sop": company_sop
    })

    cover_pdf_io = io.BytesIO()
    pisa.CreatePDF(io.StringIO(rendered_html), dest=cover_pdf_io)
    cover_pdf_io.seek(0)

    # 4. MERGE PDF COVER + LAMPIRAN BAB 4
    pdf_writer = PdfWriter()
    cover_reader = PdfReader(cover_pdf_io)
    for page in cover_reader.pages:
        pdf_writer.add_page(page)

    attachment_urls = [
        product.get("laporan_keamanan_file_url"),      # Poin 1
        company_sop.get("cv_safety_assessor_url"),     # Poin 2
        company_sop.get("monitoring_efek_samping_file_url"),    # Poin 3
        product.get("data_klaim_file_url"),            # Poin 4
        product.get("desain_primer_file_url"),         # Poin 5a
        product.get("desain_sekunder_file_url"),       # Poin 5b
    ]

    async with httpx.AsyncClient() as client:
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

# 1. Halaman Form Edit Produk
@app.get("/products/{product_id}/edit", response_class=HTMLResponse)
async def edit_product_page(request: Request, product_id: str):
    prod_resp = supabase.table("products").select("*").eq("id", product_id).single().execute()

    try:
        brands_resp = supabase.table("brands").select("id, name, producers(name)").order("name").execute()
        brands = brands_resp.data or []
    except Exception as e:
        print(f"Gagal ambil data brands buat dropdown: {e}")
        brands = []

    return templates.TemplateResponse(
        request=request,
        name="edit_product.html",
        context={"product": prod_resp.data, "brands": brands}
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
    tanggal_aktif_na: str = Form(None),
    acc_sampel: str = Form(None),
    tanggal_text_design: str = Form(None),
    teks_marketing: str = Form(None),
    cara_pakai: str = Form(None),
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
    current_user: dict = Depends(get_current_user)
):
    acc_sampel_val = acc_sampel.strip() if acc_sampel else None
    if acc_sampel_val == "": acc_sampel_val = None

    tgl_aktif_na_val = tanggal_aktif_na.strip() if tanggal_aktif_na else None
    if tgl_aktif_na_val == "": tgl_aktif_na_val = None

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
        "status_progress": status_progress,
        "brand_id": brand_id if brand_id else None
    }

    async def process_pdf_upload(file_obj, path_suffix, bucket_name="raw-material-docs"):
        if file_obj and file_obj.filename:
            try:
                file_bytes = await file_obj.read()
                path = f"products/{product_id}/{path_suffix}.pdf"
                supabase.storage.from_(bucket_name).upload(
                    path=path,
                    file=file_bytes,
                    file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                return supabase.storage.from_(bucket_name).get_public_url(path)
            except Exception as e:
                print(f"Gagal upload {path_suffix} produk {product_id}: {e}")
        return None

    # Upload Bab 1
    no_notif_url = await process_pdf_upload(no_notifikasi_file, "no_notifikasi", bucket_name="legal-documents")
    if no_notif_url: update_payload["no_notifikasi_file_url"] = no_notif_url

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
        uploaded_url = await process_pdf_upload(file_obj, key_suffix)
        if uploaded_url:
            update_payload[db_col] = uploaded_url

    supabase.table("products").update(update_payload).eq("id", product_id).execute()
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie("success_msg", f"Data & dokumen DIP produk '{nama_produk}' berhasil diperbarui!")
    return response

@app.get("/products/delete/{product_id}")
async def delete_product(product_id: str, current_user: dict = Depends(get_current_user)):
    try:
        # Hapus dulu baris formula terkait (kalau FK belum di-set CASCADE)
        supabase.table("product_formula_lines").delete().eq("product_id", product_id).execute()
        # Baru hapus produknya
        supabase.table("products").delete().eq("id", product_id).execute()
    except Exception as e:
        print(f"Gagal hapus produk {product_id}: {e}")
    return RedirectResponse(url="/", status_code=303)

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
    color_value: str = Form(None)
):
    final_product_id = None if not product_id else product_id
    if final_product_id:
        prod_master = supabase.table("products").select("nama_produk", "perusahaan").eq("id", final_product_id).execute()
        if prod_master.data:
            final_product_name = prod_master.data[0]['nama_produk']
            final_company = prod_master.data[0]['perusahaan']
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
    except Exception as e:
        print(f"Eror saat simpan form sample: {e}")
        raise HTTPException(status_code=500, detail="Gagal menyimpan dokumen.")

    return RedirectResponse(url=f"/sample-submissions/preview/{new_id}", status_code=303)


# 2. HALAMAN FORM EDIT SAMPLE
@app.get("/sample-submissions/edit/{submission_id}", response_class=HTMLResponse)
async def edit_sample_submission_page(request: Request, submission_id: str):
    try:
        sub_resp = supabase.table("sample_submissions").select("*").eq("id", submission_id).single().execute()
        submission = sub_resp.data
        if not submission:
            raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")

        brand_query = supabase.table("brands").select("*, producers(*)").execute()
        brands = brand_query.data or []
        
        product_query = supabase.table("products").select("id, nama_produk, netto, sediaan, kemasan, perusahaan").execute()
        products = product_query.data or []
    except Exception as e:
        print(f"Gagal muat data edit sample: {e}")
        raise HTTPException(status_code=500, detail="Gagal memuat form edit")

    return templates.TemplateResponse(
        request=request,
        name="sample_form.html",
        context={"brands": brands, "existing_products": products, "submission": submission}
    )


# 3. PROSES POST UPDATE SAMPLE
@app.post("/sample-submissions/edit/{submission_id}")
async def update_sample_submission(
    submission_id: str,
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
    color_value: str = Form(None)
):
    # 1. Ambil data lama buat nemuin suffix /TGL/X.Y aslinya
    sub_resp = supabase.table("sample_submissions").select("sample_code").eq("id", submission_id).single().execute()
    old_code = sub_resp.data.get("sample_code", "FSP/01-01-2026/1.1") if sub_resp.data else "FSP/01-01-2026/1.1"

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

    if brand_id == "new":
        final_brand_id, draft_prod, draft_brnd = None, custom_producer, custom_brand
    else:
        final_brand_id, draft_prod, draft_brnd = brand_id, None, None

    additional_notes = {"ph": ph_value, "viscosity": viscosity_value, "color": color_value}

    update_payload = {
        "sample_code": new_sample_code,   # <-- KODE TERSIMPAN DENGAN PREFIX BARU
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
        raise HTTPException(status_code=500, detail="Gagal mengupdate pengajuan sample.")

    return RedirectResponse(url=f"/sample-submissions/preview/{submission_id}", status_code=303)


# 4. PROSES HAPUS SAMPLE
@app.get("/sample-submissions/delete/{submission_id}")
async def delete_sample_submission(submission_id: str):
    try:
        supabase.table("sample_submissions").delete().eq("id", submission_id).execute()
    except Exception as e:
        print(f"Gagal hapus sample submission: {e}")
    return RedirectResponse(url="/sample-submissions", status_code=303)

# =====================================================================
#                     MODUL KELOLA MERK (BRAND)
# =====================================================================
@app.post("/brands/add")
async def add_brand(
    producer_name: str = Form(...),
    brand_name: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    producer_name = producer_name.strip()
    brand_name = brand_name.strip()

    if not producer_name or not brand_name:
        response = RedirectResponse(url="/brands", status_code=303)
        response.set_cookie("error_msg", "Nama Produsen dan Nama Merk wajib diisi.")
        return response

    try:
        # 1. Cek/get-or-create Produsen (case-insensitive, biar 'Seruni' & 'seruni' gak dobel)
        prod_check = supabase.table("producers").select("id").ilike("name", producer_name).execute()
        if prod_check.data:
            producer_id = prod_check.data[0]["id"]
        else:
            new_prod = supabase.table("producers").insert({"name": producer_name}).execute()
            producer_id = new_prod.data[0]["id"]

        # 2. Cek/get-or-create Brand di bawah produsen itu
        brand_check = supabase.table("brands") \
            .select("id") \
            .eq("producer_id", producer_id) \
            .ilike("name", brand_name) \
            .execute()

        if brand_check.data:
            response = RedirectResponse(url="/brands", status_code=303)
            response.set_cookie("error_msg", f"Merk '{brand_name}' sudah terdaftar di bawah produsen '{producer_name}'.")
            return response

        supabase.table("brands").insert({
            "producer_id": producer_id,
            "name": brand_name
        }).execute()

        response = RedirectResponse(url="/brands", status_code=303)
        response.set_cookie("success_msg", f"Merk '{brand_name}' berhasil ditambahkan.")
        return response

    except Exception as e:
        print(f"Gagal tambah brand baru: {e}")
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

    success_msg = request.cookies.get("success_msg")
    error_msg = request.cookies.get("error_msg")

    response = templates.TemplateResponse(
        request=request,
        name="brands.html",
        context={"brands": brands, "success_msg": success_msg, "error_msg": error_msg}
    )
    response.delete_cookie("success_msg")
    response.delete_cookie("error_msg")
    return response


@app.post("/brands/{brand_id}/update-documents")
async def update_brand_documents(
    brand_id: str,
    lisensi_merk_file: UploadFile = File(None),
    hak_merk_file: UploadFile = File(None),
    current_user: dict = Depends(get_current_user)
):
    update_data = {}

    try:
        if lisensi_merk_file and lisensi_merk_file.filename:
            file_bytes = await lisensi_merk_file.read()
            path = f"brands/lisensi_merk_{brand_id}.pdf"
            supabase.storage.from_("legal-documents").upload(
                path=path,
                file=file_bytes,
                file_options={"content-type": lisensi_merk_file.content_type, "upsert": "true"}
            )
            update_data["lisensi_merk_file_url"] = supabase.storage.from_("legal-documents").get_public_url(path)

        if hak_merk_file and hak_merk_file.filename:
            file_bytes = await hak_merk_file.read()
            path = f"brands/hak_merk_{brand_id}.pdf"
            supabase.storage.from_("legal-documents").upload(
                path=path,
                file=file_bytes,
                file_options={"content-type": hak_merk_file.content_type, "upsert": "true"}
            )
            update_data["hak_merk_file_url"] = supabase.storage.from_("legal-documents").get_public_url(path)

        if update_data:
            supabase.table("brands").update(update_data).eq("id", brand_id).execute()

        response = RedirectResponse(url="/brands", status_code=303)
        response.set_cookie("success_msg", "Dokumen merk berhasil diperbarui.")
        return response

    except Exception as e:
        print(f"Gagal update dokumen brand {brand_id}: {e}")
        response = RedirectResponse(url="/brands", status_code=303)
        response.set_cookie("error_msg", "Gagal upload dokumen. Coba lagi.")
        return response

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

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: dict = Depends(get_current_user)):
    products, brands = [], []
    try:
        # 1. Ambil data produk master
        response_prod = supabase.table("products").select("*, brands(name)").order("created_at", desc=True).execute()
        products = response_prod.data or []

        # 2. Ambil ID produk yang udah punya formula (Bab 2)
        prods_with_formula = set()
        try:
            formula_prods_resp = supabase.table("product_formula_lines").select("product_id").execute()
            prods_with_formula = set([item["product_id"] for item in (formula_prods_resp.data or []) if item.get("product_id")])
        except Exception as e:
            print(f"Gagal tarik formula lines: {e}")

        # 3. Hitung status NA dan matriks kelengkapan dokumen Bab I - IV per produk
        for p in products:
            # INI KUNCI UTAMA: Inisialisasi default value dulu biar Jinja2 gak bingung/crash
            p["dip_summary"] = {
                "b1_ok": False,
                "b2_ok": False,
                "b3_ok": False,
                "b3_ratio": "0/7",
                "b4_ok": False,
                "b4_ratio": "0/5",
                "progress_pct": 0,
                "is_complete": False
            }

            try:
                p["status_na"] = compute_status_na(p.get("tanggal_aktif_na"), p.get("status_na") or "belum_terdaftar")
                
                b1_ok = bool(p.get("no_notifikasi_file_url"))
                b2_ok = p.get("id") in prods_with_formula
                
                b3_files = [
                    p.get("cara_pembuatan_file_url"),
                    p.get("sistem_penomoran_batch_file_url"),
                    p.get("spek_produk_jadi_file_url"),
                    p.get("spek_pengemas_file_url"),
                    p.get("laporan_uji_sig_file_url"),
                    p.get("protokol_stabilitas_file_url"),
                    p.get("hasil_stabilitas_file_url")
                ]
                b3_count = sum(1 for f in b3_files if f)
                b3_ok = (b3_count == len(b3_files))
                
                b4_files = [
                    p.get("laporan_keamanan_file_url"),
                    p.get("monitoring_efek_samping_file_url"),
                    p.get("data_klaim_file_url"),
                    p.get("desain_primer_file_url"),
                    p.get("desain_sekunder_file_url")
                ]
                b4_count = sum(1 for f in b4_files if f)
                b4_ok = (b4_count == len(b4_files))
                
                total_checks = 1 + 1 + len(b3_files) + len(b4_files)
                current_checks = (1 if b1_ok else 0) + (1 if b2_ok else 0) + b3_count + b4_count
                progress_pct = int((current_checks / total_checks) * 100)
                
                p["dip_summary"] = {
                    "b1_ok": b1_ok,
                    "b2_ok": b2_ok,
                    "b3_ok": b3_ok,
                    "b3_ratio": f"{b3_count}/{len(b3_files)}",
                    "b4_ok": b4_ok,
                    "b4_ratio": f"{b4_count}/{len(b4_files)}",
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
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html", 
        context={
            "request": request, 
            "products": products, 
            "user": current_user,
            "brands": brands
        }
    )