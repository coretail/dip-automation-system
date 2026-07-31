from fastapi import FastAPI, Request, Form, HTTPException, Response, File, UploadFile, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List
from app.database import supabase
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
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
        # Kalo tokennya ngaco/expired, hapus cookie dan tendang balik ke login
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(key="access_token")
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
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
@app.post("/login")
async def login_submit(
    response: Response,
    email: str = Form(...), # Ini nangkep input username/email dari form
    password: str = Form(...)
):
    try:
        login_identifier = email.strip()
        
        # JIKA YANG DIINPUT BUKAN EMAIL (GA ADA TANDA @)
        if "@" not in login_identifier:
            # Cari di tabel profiles berdasarkan nama/username
            profile_query = supabase.table("profiles").select("id").eq("full_name", login_identifier).execute()
            
            if profile_query.data:
                # Kalo username ketemu, kita cari email aslinya via admin auth di Supabase
                # Catatan: Ini cara paling dinamis & aman tanpa hardcode email
                user_id = profile_query.data[0]["id"]
                user_auth_data = supabase.auth.admin.get_user_by_id(user_id)
                login_identifier = user_auth_data.user.email
            else:
                # Kalo ga ketemu di profiles, fallback otomatis pake domain kantor
                login_identifier = f"{login_identifier}@erfi.com"
            
        # Tembak ke Supabase Auth pake email asli yang udah dapet dari DB
        auth_response = supabase.auth.sign_in_with_password({
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
    # Gunakan Form(None) untuk data list agar FastAPI dinamis
    inci_name: list[str] = Form(None),
    cas_number: list[str] = Form(None),
    function: list[str] = Form(None),
    percent_internal: list[float] = Form(None),
    current_user: dict = Depends(get_current_user)
):
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
    
    # 2. SIAPKAN DICTIONARY DATA UNTUK UPDATE TABLE RAW_MATERIALS
    update_data = {
        "nama_dagang": nama_dagang,
        "kode_bahan_baku": kode_bahan_baku,
        "tipe": tipe
    }
    
    # 3. LOGIKA PROSES UPLOAD FILE MSDS (JIKA USER UPLOAD FILE BARU)
    if msds_file and msds_file.filename:
        try:
            file_contents = await msds_file.read()
            # Bersihkan nama file biar aman di URL
            clean_filename = f"msds_{rm_id}_{msds_file.filename.replace(' ', '_')}"
            storage_path = f"msds/{clean_filename}"
            
            # Upload file biner ke bucket raw-material-docs
            supabase.storage.from_("raw-material-docs").upload(
                path=storage_path,
                file=file_contents,
                file_options={"content-type": msds_file.content_type, "upsert": "true"}
            )
            
            # Dapatkan URL publik dari file yang berhasil di-upload
            msds_url = supabase.storage.from_("raw-material-docs").get_public_url(storage_path)
            
            # Masukkan URL ke data update (Pastikan nama kolom 'msds_file_url' sesuai DB lu ya!)
            update_data["msds_file_url"] = msds_url
            print(f"Sukses upload MSDS baru ke: {msds_url}")
            
        except Exception as e:
            print(f"Gagal proses upload MSDS: {e}")
            # Opsional: lu bisa throw eror atau biarkan lanjut tanpa ganti file lama
    
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
    harga_per_kg: float = Form(...),
    tanggal_terima_sampel: str = Form(...),
    hasil_pemerian: str = Form(...),
    # Tangkap file dokumen baru
    coa_file: UploadFile = File(None),
    halal_file: UploadFile = File(None)
):
    clean_batch = "".join(c for c in no_batch if c.isalnum() or c in ('-', '_')).strip()
    
    coa_url = None
    halal_url = None

    # 1. Proses Upload CoA jika ada filenya
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

    # 2. Proses Upload Halal Cert jika ada filenya
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

    # 3. Simpan record data ke tabel raw_material_batches
    batch_data = {
        "raw_material_id": raw_material_id,
        "no_batch": no_batch,
        "supplier": supplier,
        "harga_per_kg": harga_per_kg,
        "tanggal_terima_sampel": tanggal_terima_sampel,
        "hasil_pemerian": hasil_pemerian,
        "coa_file_url": coa_url,       # Nilainya akan string URL atau NULL jika tidak upload
        "halal_batch_file_url": halal_url    # Nilainya akan string URL atau NULL jika tidak upload
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
        prod_master = supabase.table("products").select("nama_produk", "company").eq("id", final_product_id).execute()
        if prod_master.data:
            final_product_name = prod_master.data[0]['nama_produk']
            final_company = prod_master.data[0]['company']
    else:
        # Jalur manual: Pakai inputan ketikan dari form
        final_product_name = product_name
        final_company = company

    today_str = datetime.now().strftime("%d-%m-%Y")
    
    # --- 1. LOGIKAHITUNG X.Y (OTOMATIS) ---
    # Cari tahu total produk berbeda hari ini untuk menentukan X
    # Cari tahu total percobaan untuk produk yang sama hari ini untuk menentukan Y
    # Untuk sementara lu bisa pakai dummy increment atau query count dari DB.
    try:
        # Ambil data submission khusus yang dibuat dari awal hari ini (WIB)
        start_of_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        today_submissions = supabase.table("sample_submissions") \
            .select("sample_code, product_name") \
            .gte("created_at", start_of_day) \
            .execute()
        
        existing_records = today_submissions.data or []
        
        # Cari urutan produk BERBEDA hari ini untuk nentuin nilai X
        distinct_products = list(dict.fromkeys([r['product_name'] for r in existing_records]))
        
        if product_name in distinct_products:
            x_index = distinct_products.index(product_name) + 1
        else:
            x_index = len(distinct_products) + 1
            
        # Cari total trial untuk produk yang SAMA khusus hari ini untuk nentuin nilai Y
        same_product_trials = [r for r in existing_records if r['product_name'] == product_name]
        y_index = len(same_product_trials) + 1
        
        sample_code = f"FSP/{today_str}/{x_index}.{y_index}" #[cite: 1]
        
        # Hitung nomor revisi kumulatif (all-time) untuk produk ini[cite: 1]
        all_time_trials = supabase.table("sample_submissions") \
            .select("id") \
            .eq("product_name", product_name) \
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
            "company": company,
            "brand_id": final_brand_id,
            "product_name": product_name,
            "product_item": product_item if product_item else product_name,
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
        
        product_query = supabase.table("products").select("id, nama_produk, netto, sediaan, kemasan").execute()
        products = product_query.data or []
    except Exception as e:
        print(f"Gagal ambil data pendukung form: {e}")
        brands, products = [], []
        
    return templates.TemplateResponse(
        request=request,
        name="sample_form.html",
        context={"brands": brands, "products": products}
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

# 1. TAMPILAN HALAMAN REGISTER PUBLIK (TANPA GEMBOK LOGIN)
@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")

# 2. PROSES DAFTAR AKUN MANDIRI (TANPA GEMBOK LOGIN)
@app.post("/register")
async def register_user_submit(
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    try:
        # 1. Validasi kecocokan password
        if password != confirm_password:
            return RedirectResponse(url="/register?error=password_mismatch", status_code=303)
            
        clean_username = username.strip().lower()
        clean_email = email.strip().lower()
        
        # 2. Daftarin ke Supabase Auth Service pake email asli yang diinput user
        auth_res = supabase.auth.admin.create_user({
            "email": clean_email,
            "password": password,
            "email_confirm": True
        })
        
        new_uid = auth_res.user.id
        
        # 3. Inject ke tabel profiles, full_name kita isi username biar sinkron sama login murni username
        supabase.table("profiles").insert({
            "id": new_uid,
            "full_name": clean_username, 
            "role": "staff",
            "updated_at": "now()"
        }).execute()
        
        return RedirectResponse(url="/login?status=register_success", status_code=303)
        
    except Exception as e:
        print(f"Gagal registrasi mandiri: {e}")
        return RedirectResponse(url="/register?error=failed", status_code=303)

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