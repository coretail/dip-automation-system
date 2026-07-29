from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List
from app.database import supabase
from decimal import Decimal, ROUND_HALF_UP

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

templates.env.filters["clean_pct"] = clean_pct

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    response = supabase.table("products").select("*").order("created_at", desc=True).execute()
    products = response.data
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html", 
        context={"products": products}
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
    return templates.TemplateResponse(
        request=request,
        name="raw_materials.html",
        context={"raw_materials": rm_resp.data}
    )

@app.post("/raw-materials/add")
async def add_raw_material(
    nama_dagang: str = Form(...),
    kode_bahan_baku: str = Form(...),
    tipe: str = Form(...),
    inci_name: List[str] = Form(None),
    cas_number: List[str] = Form(None),
    function: List[str] = Form(None),
    percent_internal: List[float] = Form(None)
):
    kode_check = kode_bahan_baku.strip()
    existing_rm = supabase.table("raw_materials").select("id").eq("kode_bahan_baku", kode_check).execute()
    
    if existing_rm.data:
        raise HTTPException(status_code=400, detail=f"Amsyong! Kode bahan baku '{kode_check}' sudah terdaftar di sistem. Gunakan kode lain.")
        
    rm_resp = supabase.table("raw_materials").insert({
        "nama_dagang": nama_dagang,
        "kode_bahan_baku": kode_bahan_baku,
        "tipe": tipe
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

    return RedirectResponse(url="/raw-materials", status_code=303)

@app.post("/raw-materials/edit/{rm_id}")
async def edit_raw_material(
    rm_id: str,
    nama_dagang: str = Form(...),
    kode_bahan_baku: str = Form(...),
    tipe: str = Form(...),
    inci_name: List[str] = Form(None),
    cas_number: List[str] = Form(None),
    function: List[str] = Form(None),
    percent_internal: List[float] = Form(None)
):
    kode_check = kode_bahan_baku.strip()
    existing_rm = supabase.table("raw_materials").select("id").eq("kode_bahan_baku", kode_check).neq("id", rm_id).execute()
    
    if existing_rm.data:
        raise HTTPException(status_code=400, detail=f"Gagal Edit! Kode '{kode_check}' sudah dipakai oleh bahan baku lain.")
    
    supabase.table("raw_materials").update({
        "nama_dagang": nama_dagang,
        "kode_bahan_baku": kode_bahan_baku,
        "tipe": tipe
    }).eq("id", rm_id).execute()

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
    status_na: str = Form("belum_terdaftar")
):
    product_data = {
        "nama_produk": nama_produk,
        "perusahaan": perusahaan,
        "nama_customer": nama_customer,
        "sediaan": sediaan,
        "warna": warna,
        "kemasan": kemasan,
        "netto": netto,
        "no_na_produk": no_na_produk,
        "status_na": status_na
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

    # Urutkan berdasarkan persentase terbesar
    pure_breakdown = sorted(pure_breakdown, key=lambda x: x["pct_ww"], reverse=True)

    clean_product = {}
    if isinstance(product, list) and len(product) > 0:
        clean_product = product[0]
    elif isinstance(product, dict):
        clean_product = product
        
    final_product = {str(k): (str(v) if v is not None else "") for k, v in clean_product.items()}

    return templates.TemplateResponse(
        request=request,
        name="qualitative_quantitative.html",
        context={
            "product": final_product,
            "trade_breakdown": trade_breakdown,
            "pure_breakdown": pure_breakdown
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
    status_na: str = Form("aktif")
):
    supabase.table("products").update({
        "nama_produk": nama_produk,
        "perusahaan": perusahaan,
        "nama_customer": nama_customer,
        "sediaan": sediaan,
        "warna": warna,
        "netto": netto,          
        "kemasan": kemasan,
        "no_na_produk": no_na_produk,
        "status_na": status_na
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