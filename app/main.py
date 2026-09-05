from fastapi import FastAPI, Request, Form, HTTPException, Response, File, UploadFile, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List
from app.database import supabase
from app.config import settings
from app.excel_generator import XLSX_MIME, build_formula_workbook
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from supabase import create_client
import random
import os
import io
import re
import json
import base64
import sys
import tempfile
import zipfile
import httpx
import unicodedata
from xhtml2pdf import pisa
from pypdf import PdfReader, PdfWriter
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from typing import Optional
from slugify import slugify

from dotenv import load_dotenv
load_dotenv()
# Pastikan stdout/stderr selalu UTF-8 biar log emoji aman di semua terminal
# (Windows console default cp1252 gak support emoji, terutama pas output di-redirect/pipe).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Zona waktu bisnis (WIB) — dipakai buat semua logika berbasis "hari ini"
# (kode FSP, hitungan revisi) biar gak geser gara-gara server jalan di UTC.
WIB = ZoneInfo("Asia/Jakarta")

_CASUAL_PHRASES = [
    "Santai aja, kerjaan gak kemana kok.",
    "Yuk, beresin satu-satu.",
    "Semoga harimu lancar!",
    "Alon-alon asal kelakon.",
    "Alon-alon asal marathon.",
    "Jangan lupa istirahat sebentar.",
    "Satu langkah kecil, tetap langkah.",
    "Hari yang baik buat beresin dokumen.",
]

def get_time_greeting() -> dict:
    """Greeting berbasis jam WIB (tanpa phrase AI). Dipakai di halaman
    login (sebelum ada nama user) dan sebagai fallback di dashboard
    kalau cache AI greeting gagal/hilang."""
    hour = datetime.now(WIB).hour
    if 5 <= hour < 11:
        base = {"text": "Selamat Pagi", "icon": "fa-solid fa-sun", "color": "text-amber-400"}
    elif 11 <= hour < 15:
        base = {"text": "Selamat Siang", "icon": "fa-solid fa-sun", "color": "text-yellow-500"}
    elif 15 <= hour < 18:
        base = {"text": "Selamat Sore", "icon": "fa-solid fa-cloud-sun", "color": "text-orange-400"}
    else:
        base = {"text": "Selamat Malam", "icon": "fa-solid fa-moon", "color": "text-indigo-400"}
    base["phrase"] = random.choice(_CASUAL_PHRASES)
    return base

_GEMINI_MODELS_FALLBACK = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
]

async def _generate_ai_greeting_phrase(nama_user: str) -> str | None:
    """Coba generate 1 kalimat sapaan santai gaya gen-Z pakai Gemini API,
    nyoba beberapa model flash-lite berurutan (kalau satu limit/gagal,
    lanjut ke model berikutnya). Return None kalau semua model gagal --
    caller WAJIB fallback ke _CASUAL_PHRASES, jangan sampai proses login
    gagal gara-gara fitur dekoratif ini."""
    api_key = settings.gemini_api_key
    if not api_key:
        return None

    prompt = (
        f"Buatkan SATU kalimat sapaan singkat (maksimal 12 kata) dalam Bahasa "
        f"Indonesia gaya santai/gen-Z buat user bernama '{nama_user}' yang baru "
        f"login ke aplikasi kerja. Jangan pakai tanda kutip di jawaban. Jangan "
        f"pakai emoji. Cukup 1 kalimat saja, tanpa basa-basi/penjelasan tambahan."
    )

    async with httpx.AsyncClient(timeout=4.0) as client:
        for model in _GEMINI_MODELS_FALLBACK:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                resp = await client.post(url, json={
                    "contents": [{"parts": [{"text": prompt}]}]
                })
                if resp.status_code != 200:
                    print(f"[AI GREETING] Model {model} gagal (status {resp.status_code}), coba model berikutnya.")
                    continue
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text:
                    return text
            except Exception as e:
                print(f"[AI GREETING] Model {model} error: {e}, coba model berikutnya.")
                continue
    return None


def _extract_jwt_email(token: str):
    """Best-effort baca email/sub dari payload JWT (buat log doang, tanpa validasi signature)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # padding base64url biar valid
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("email") or payload.get("sub") or "-"
    except Exception:
        return "-"

def _add_years(d: date, years: int) -> date:
    """Tambah tahun ke tanggal, aman buat kasus 29 Feb kena tahun non-kabisat."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)

async def get_ed_notification_count():
    """Helper to fetch ED notification count for template context."""
    from datetime import datetime as _dt
    today = _dt.now(WIB).date()
    try:
        ed_query = (
            supabase.table("raw_material_batches")
            .select("id, tanggal_ed, status_ed")
            .neq("status_ed", "Dimusnahkan")
            .execute()
        )
        count = 0
        for batch in (ed_query.data or []):
            tanggal_ed = batch.get("tanggal_ed")
            if not tanggal_ed:
                continue
            try:
                if isinstance(tanggal_ed, str):
                    ed_date = _dt.strptime(tanggal_ed[:10], "%Y-%m-%d").date()
                else:
                    ed_date = tanggal_ed
                days_remaining = (ed_date - today).days
                if days_remaining <= 180:
                    count += 1
            except Exception:
                continue
        return count
    except Exception as e:
        print(f"Gagal hitung ED notifications: {e}")
        return 0

def compute_status_na(tanggal_aktif_na, fallback_status: str) -> str:
    """
    Hitung status NA otomatis dari tanggal_aktif_na (NA BPOM berlaku 3 tahun sejak
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

    expired_date = _add_years(start, 3)
    today = datetime.now(WIB).date()
    warning_date = expired_date - timedelta(days=180)  # ~6 bulan sebelum expired

    if today > expired_date:
        return "expired"
    elif today >= warning_date:
        return "akan_expired"
    else:
        return "aktif"

def _client_ip(request: Request) -> str:
    """Ekstrak alamat IP client.
    Prioritas: X-Forwarded-For (saat app di belakang proxy seperti Render/nginx)
    -> X-Real-IP -> request.client.host (IP langsung)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "-"


app = FastAPI(title="DIP Kosmetik Automation")

# Rate limiter (proteksi brute-force di /login, dibatasi per-IP)
limiter = Limiter(key_func=_client_ip)
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    # Redirect balik ke login dengan pesan, biar konsisten sama flow warning/error yang lain
    # (bukan JSON mentah), dan gak bocorin detail rate limit ke user.
    print(f"\n🚫 [RATE LIMIT] Terlalu banyak percobaan login dari IP: {_client_ip(request)}\n")
    return RedirectResponse(url="/login?error=too_many_attempts", status_code=303)

# Setup static files (Tailwind CSS) dan Jinja2 Templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def slugify(text: str) -> str:
    """
    Mengubah teks menjadi slug URL-friendly.
    - Lowercase
    - Ganti spasi & karakter khusus dengan strip (-)
    - Hapus karakter non-alphanumeric (kecuali strip)
    - Hilangkan strip berulang & di awal/akhir
    Contoh: "Sunscreen Serum SPF 50+" -> "sunscreen-serum-spf-50"
    """
    if not text:
        return ""
    # Normalize unicode (NFKD) untuk memisahkan karakter composed
    text = unicodedata.normalize('NFKD', text)
    # Hapus karakter non-ASCII (seperti tanda baca khusus, emoji, dll)
    text = text.encode('ascii', 'ignore').decode('ascii')
    # Lowercase
    text = text.lower()
    # Ganti karakter non-alphanumeric dengan strip
    text = re.sub(r'[^a-z0-9]+', '-', text)
    # Hapus strip di awal/akhir dan berulang
    text = re.sub(r'-+', '-', text).strip('-')
    return text


def extract_id_from_slug(slug_id: str) -> str:
    """
    Ekstrak UUID dari string slug-ID.
    Format: [slug]-[uuid]
    UUID panjangnya 36 karakter (dengan hyphen: 8-4-4-4-12).
    Jadi ambil 36 karakter terakhir sebagai kandidat UUID.
    Jika bukan UUID valid (misal hanya UUID tanpa slug), return asli.
    """
    if not slug_id:
        return slug_id
    
    # Cek apakah 36 karakter terakhir adalah UUID valid
    if len(slug_id) >= 36:
        candidate = slug_id[-36:]
        # UUID regex pattern
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        if re.match(uuid_pattern, candidate, re.IGNORECASE):
            return candidate
    
    # Fallback: return asli (mungkin UUID saja tanpa slug)
    return slug_id


# Register slugify as Jinja2 filter
templates.env.filters["slugify"] = slugify

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
        "email": "erfikaryaabadi@gmail.com",
        "website": "www.erfikaryaabadi.com",
        "logo": "/static/images/logo_erfi.png"
    },
    "PT Heka": {
        "nama": "PT. HARAKA ERFI KOSMETINDO ABADI",          
        "alamat": "Office : Jl. Kampung Klapanunggal, RT 001/RW 01. Desa Klapanunggal Kec. Klapanunggal Bogor, Indonesia",
        "email": "harakaerfi.pt@gmail.com",
        "website": "www.harakaerfi.com",
        "logo": "/static/images/logo_heka.png"
    }
}

def get_company_info(perusahaan_key: str) -> dict:
    """Helper buat narik detail perusahaan resmi berdasarkan key DB ('PT Erfi' / 'PT Heka')"""
    if not perusahaan_key:
        return COMPANY_INFO["PT Erfi"]
    return COMPANY_INFO.get(perusahaan_key, COMPANY_INFO["PT Erfi"])

def _logo_render_width(uri: str, target_height_px: int = 60) -> int:
    """Lebar (px) logo saat dirender dengan tinggi target_height_px.

    Dipakai buat nyetel lebar kolom logo di kop surat Bab III sesuai proporsi
    asli tiap perusahaan (logo Erfi lebar/lanskap, logo Heka potret/tinggi),
    supaya jarak antara logo dan teks perusahaan tetap rapat & konsisten
    tanpa perlu hardcode lebar cell.
    """
    try:
        if not uri or not uri.startswith("/static/"):
            return target_height_px
        local_path = os.path.join("app", uri.lstrip("/").replace("/", os.sep))
        if not os.path.exists(local_path):
            return target_height_px
        from PIL import Image
        w, h = Image.open(local_path).size
        if h <= 0:
            return target_height_px
        return round(w * target_height_px / h)
    except Exception as e:
        print(f"[KOP SURAT] Gagal hitung lebar logo {uri}: {e}")
        return target_height_px

def _pdf_link_callback(uri: str, rel: str) -> str:
    """link_callback untuk pisa.CreatePDF: resolve path /static/... ke file lokal.

    PNG transparan (RGBA/LA/P) di-flatten ke background putih dulu karena
    xhtml2pdf sering merender PNG RGBA dengan background hitam.
    """
    if not uri.startswith("/static/"):
        return uri
    local_path = os.path.join("app", uri.lstrip("/").replace("/", os.sep))
    if not os.path.exists(local_path):
        return local_path
    try:
        from PIL import Image
        img = Image.open(local_path)
        if img.mode in ("RGBA", "LA", "P"):
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            alpha = img.split()[-1]
            canvas = Image.new("RGB", img.size, (255, 255, 255))
            canvas.paste(img.convert("RGB"), mask=alpha)
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            canvas.save(tmp.name, format="PNG")
            return tmp.name
    except Exception as e:
        print(f"[PDF LINK CALLBACK] Gagal flatten logo {uri}: {e}")
    return local_path

templates.env.filters["clean_pct"] = clean_pct


MONTH_NAMES_ID = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April", 5: "Mei", 6: "Juni",
    7: "Juli", 8: "Agustus", 9: "September", 10: "Oktober", 11: "November", 12: "Desember"
}

def format_date_id(value: Optional[date]) -> str:
    """Format tanggal ke format Indonesia (e.g., 29 Mei 2026)."""
    if not value:
        return "-"
    try:
        # Ensure it's a date object
        if isinstance(value, str):
            dt = datetime.strptime(value, "%Y-%m-%d").date()
        else:
            dt = value
        return f"{dt.day} {MONTH_NAMES_ID[dt.month]} {dt.year}"
    except Exception as e:
        print(f"[FORMAT DATE ID] Gagal format tanggal {value}: {e}")
        return str(value)

def format_date_dd_mm_yyyy(value):
    """Konversi format tanggal dari YYYY-MM-DD ke dd-mm-yyyy."""
    if not value:
        return "-"
    try:
        # Coba parse format ISO (YYYY-MM-DD)
        dt = datetime.strptime(str(value)[:10], "%Y-%m-%d")
        return dt.strftime("%d-%m-%Y")
    except Exception:
        # Kalau format sudah dd-mm-yyyy atau tidak dikenal, kembalikan aslinya
        return str(value)

templates.env.filters["format_date_dd_mm_yyyy"] = format_date_dd_mm_yyyy

@app.head("/health")
@app.get("/health")
async def health_check():
    return {"status": "i know i'm strong, but ya Allah tolong"}

# ================= FUNCTION Login (REPLACEMENT) =================
async def get_current_user(request: Request):
    # 1. Ambil cookie token dari browser
    token_cookie = request.cookies.get("access_token")
    if not token_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak ditemukan"
        )
    
    try:
        # 2. Ekstrak token aslinya
        token = token_cookie.replace("Bearer ", "")
        
        # 3. Minta data user ke Supabase Auth
        user_auth = supabase.auth.get_user(token)
        user_data = user_auth.user
        
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User tidak valid"
            )
        
        # 4. Tarik info nama & role dari tabel profiles
        profile_res = supabase.table("profiles").select("full_name", "role").eq("id", user_data.id).execute()
        
        user_role = "staff"
        full_name = "User Lab"
        
        if profile_res.data:
            user_role = profile_res.data[0].get("role", "staff")
            full_name = profile_res.data[0].get("full_name", "User Lab")
            
        return {
            "id": user_data.id,
            "email": user_data.email,
            "full_name": full_name,
            "role": user_role
        }
        
    except Exception as e:
        print(f"Token invalid atau expired: {e}")
        # Lempar 401 biar ditangkap handler
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired"
        )


def log_activity(current_user: dict, action: str, entity_type: str, entity_id: str, entity_label: str, changes: list = None):
    """Catat activity log ke DB Supabase + cetak log rapi ke terminal Render."""
    # 1. Cetak log ke terminal Render
    print_activity_terminal(
        current_user=current_user,
        action=action,
        entity_type=entity_type,
        entity_label=entity_label,
        entity_id=entity_id,
        changes=changes
    )

    # 2. Simpan ke tabel activity_logs Supabase
    try:
        supabase.table("activity_logs").insert({
            "actor_id": current_user.get("id") if current_user else None,
            "actor_name": current_user.get("full_name") if current_user else "System",
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_label": entity_label,
            "changes": changes or [],
        }).execute()
    except Exception as e:
        print(f"Gagal catat activity log ke DB ({entity_type}/{action}/{entity_id}): {e}")

def print_activity_terminal(current_user: dict, action: str, entity_type: str, entity_label: str, entity_id: str = None, changes: list = None):
    """
    Format dan cetak log aktivitas ke stdout/terminal Render.
    """
    now_str = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
    actor_name = current_user.get("full_name", "System") if current_user else "System"
    actor_email = current_user.get("email", "-") if current_user else "-"
    
    # Mapping badge aksi biar gampang di-scan mata di log Render
    action_badges = {
        "create": "🟢 [CREATED]",
        "update": "🟡 [UPDATED]",
        "delete": "🔴 [DELETED]"
    }
    badge = action_badges.get(action.lower(), f"🔵 [{action.upper()}]")

    print("\n" + "="*60)
    print(f"📝 {badge} ACTIVITY LOG | {now_str}")
    print(f"   • Actor    : {actor_name} ({actor_email})")
    print(f"   • Entity   : {entity_type.upper()} -> '{entity_label}'" + (f" (ID: {entity_id})" if entity_id else ""))
    
    if changes:
        print("   • Changes  :")
        for c in changes:
            field = c.get("field", "Unknown Field")
            if "note" in c:
                print(f"     - {field}: {c['note']}")
            else:
                old_val = c.get("old") if c.get("old") is not None else "-"
                new_val = c.get("new") if c.get("new") is not None else "-"
                print(f"     - {field}: '{old_val}'  ➔  '{new_val}'")
    print("="*60 + "\n")


def _build_diff_changes(old_row: dict, update_payload: dict, field_labels: dict, file_fields: set = None) -> list:
    """Bandingin old_row (data sebelum update) vs update_payload (data yang mau disimpen),
    return list perubahan buat activity log. Field yang gak berubah di-skip.
    Field jenis file (file_fields) cuma dicatet 'File diganti' tanpa link lama, soalnya
    upload sekarang overwrite in-place (url lama = url baru abis di-upsert -> percuma dicatet)."""
    file_fields = file_fields or set()
    changes = []
    for field, label in field_labels.items():
        if field not in update_payload:
            continue
        if field in file_fields:
            changes.append({"field": label, "note": "File diganti"})
            continue
        old_val = old_row.get(field)
        new_val = update_payload.get(field)
        if (old_val or None) != (new_val or None):
            changes.append({"field": label, "old": old_val, "new": new_val})
    return changes


# ================= 1. ROUTE TAMPILAN LOGIN =================
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, warning: str = None, error: str = None):
    # Cek kalau token ada di cookie DAN gak lagi dapet warning/error, langsung ke dashboard
    if request.cookies.get("access_token") and not warning and not error:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "warning": warning,
            "error": error,
            "greeting": get_time_greeting()
        }
    )

# ================= 2. ROUTE PROSES LOGIN (POST) =================
# Rate limit: maks 5 percobaan login per menit per IP, biar gak gampang di-brute-force.
@app.post("/login")
@limiter.limit("5/minute")
async def login_submit(
    request: Request,
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
        waktu_login = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
        print("\n" + "="*50)
        print("🔑 [LOGIN SUCCESS]")
        print(f"   • User ID : {user_data.id}")
        print(f"   • Email   : {user_data.email}")
        print(f"   • Waktu   : {waktu_login}")
        print("="*50 + "\n")

        # Generate greeting (waktu + kalimat AI) sekali di sini, dipakai terus
        # sepanjang sesi (gak manggil AI lagi tiap buka dashboard)
        import json
        profile_resp = supabase_admin.table("profiles").select("full_name").eq("id", user_data.id).execute()
        nama_user = profile_resp.data[0]["full_name"] if profile_resp.data else "Kamu"

        greeting = get_time_greeting()
        ai_phrase = await _generate_ai_greeting_phrase(nama_user)
        if ai_phrase:
            greeting["phrase"] = ai_phrase

        session_token = auth_response.session.access_token
        redirect = RedirectResponse(url="/", status_code=303)
        redirect.set_cookie(
            key="access_token",
            value=f"Bearer {session_token}",
            httponly=True,
            max_age=86400,
            samesite="lax"
        )
        redirect.set_cookie(
            key="greeting_cache",
            value=json.dumps(greeting),
            httponly=True,
            max_age=14400,  # samain sama masa berlaku JWT asli (4 jam), bukan 86400-nya cookie access_token
            samesite="lax"
        )
        return redirect

    except Exception as e:
        # 💡 LOG FAILED LOGIN
        waktu_gagal = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
        print(f"\n❌ [LOGIN FAILED] Input: '{email}' | Waktu: {waktu_gagal} | Error: {e}\n")
        return RedirectResponse(url="/login?error=invalid_credentials", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=303)
    # Hapus cookie token yang tersimpan di browser
    response.delete_cookie(key="access_token")
    response.delete_cookie(key="greeting_cache")

    # 💡 LOG LOGOUT
    waktu_logout = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
    try:
        token_cookie = request.cookies.get("access_token")
        email_log = _extract_jwt_email(token_cookie.replace("Bearer ", "")) if token_cookie else "-"
    except Exception:
        email_log = "-"
    print("\n" + "="*50)
    print("🚪 [LOGOUT]")
    print(f"   • User  : {email_log}")
    print(f"   • Waktu : {waktu_logout}")
    print("="*50 + "\n")

    return response

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    # Kalau error-nya 401 (Unauthorized / Sesi Habis)
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        # 💡 LOG SESSION EXPIRED / UNAUTHORIZED (token sudah kadaluarsa, email dibaca
        # dari payload JWT best-effort tanpa validasi signature)
        waktu_exp = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
        try:
            token_cookie = request.cookies.get("access_token")
            email_log = _extract_jwt_email(token_cookie.replace("Bearer ", "")) if token_cookie else "-"
        except Exception:
            email_log = "-"
        print("\n" + "="*50)
        print(f"⏰ [SESSION EXPIRED] Path: {request.url.path}")
        print(f"   • User  : {email_log}")
        print(f"   • Waktu : {waktu_exp}")
        print("="*50 + "\n")

        return RedirectResponse(
            url="/login?warning=session_expired", 
            status_code=status.HTTP_303_SEE_OTHER
        )
    
    # Untuk error 413 (Payload Too Large) terkait upload file
    if exc.status_code == status.HTTP_413_CONTENT_TOO_LARGE:
        print(f"\n⚠️ [FILE TOO LARGE] Path: {request.url.path}")
        print(f"   • Detail: {exc.detail}")
        print("=" * 50 + "\n")
        # Redirect balik ke halaman edit dengan pesan error
        referer = request.headers.get("referer")
        if referer and "/edit" in referer:
            redirect_url = referer
        else:
            redirect_url = "/"
        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie("error_msg", str(exc.detail))
        return response

    # Untuk error HTTP lainnya tetap kembalikan bawaan
    # Untuk rute publik /dip/{slug}/..., tampilkan halaman error yang rapi, bukan JSON mentah
    if request.url.path.startswith("/dip/"):
        title = "Dokumen Tidak Ditemukan" if exc.status_code == 404 else "Terjadi Kesalahan"
        message = exc.detail if isinstance(exc.detail, str) else "Silakan hubungi admin jika masalah berlanjut."
        return templates.TemplateResponse(
            "public_error.html",
            {"request": request, "title": title, "message": message},
            status_code=exc.status_code
        )

    # Untuk error HTTP lainnya tetap kembalikan bawaan
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.get("/raw-materials", response_class=HTMLResponse)
async def raw_materials_page(request: Request, current_user: dict = Depends(get_current_user)):
    rm_resp = supabase.table("raw_materials").select("*, raw_material_components(*), raw_material_company_docs(*)").order("nama_dagang").execute()
    
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
                    raw_material_components (
                        inci_name,
                        cas_number
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
            .select("raw_material_id, product_id").execute()
        usage_sets = {}
        for ln in (usage_lines.data or []):
            rm_id_ln = ln.get("raw_material_id")
            prod_id_ln = ln.get("product_id")
            if rm_id_ln and prod_id_ln:
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
            .select("percent_in_formula, products(id, nama_produk, perusahaan)") \
            .eq("raw_material_id", rm_id).execute()

        products_map = {}
        for ln in (lines_resp.data or []):
            product = ln.get("products")
            if not product or not product.get("id"):
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


# ==================== API: ED NOTIFICATIONS ====================
@app.get("/api/ed-notifications")
async def get_ed_notifications(current_user: dict = Depends(get_current_user)):
    """API endpoint untuk mengambil notifikasi ED bahan baku (sisa ED <= 180 hari atau expired)"""
    WIB = ZoneInfo("Asia/Jakarta")
    today = datetime.now(WIB).date()
    warning_date = today + timedelta(days=180)  # 180 hari ke depan
    
    try:
        # Ambil semua batch dengan tanggal_ed <= warning_date atau status_ed bukan 'Dimusnahkan'
        query = supabase.table("raw_material_batches") \
            .select("""
                *,
                raw_materials (
                    nama_dagang,
                    kode_bahan_baku
                )
            """) \
            .neq("status_ed", "Dimusnahkan") \
            .execute()
        
        batches = query.data or []
        critical_batches = []
        
        for batch in batches:
            tanggal_ed = batch.get("tanggal_ed")
            if not tanggal_ed:
                continue
            
            try:
                if isinstance(tanggal_ed, str):
                    ed_date = datetime.strptime(tanggal_ed[:10], "%Y-%m-%d").date()
                else:
                    ed_date = tanggal_ed
            except Exception:
                continue
            
            days_remaining = (ed_date - today).days
            
            # Filter: hanya yang sisa ED <= 180 hari atau sudah expired
            if days_remaining <= 180:
                status_ed = batch.get("status_ed") or "Active"
                
                # Auto-update status jika expired tapi masih 'Active'
                if days_remaining <= 0 and status_ed == "Active":
                    status_ed = "Expired"
                elif days_remaining <= 180 and status_ed == "Active":
                    status_ed = "Kritis (<= 180 hari)"
                
                critical_batches.append({
                    "id": batch.get("id"),
                    "raw_material_id": batch.get("raw_material_id"),
                    "no_batch": batch.get("no_batch"),
                    "perusahaan": batch.get("perusahaan"),
                    "tanggal_ed": tanggal_ed,
                    "days_remaining": days_remaining,
                    "status_ed": status_ed,
                    "nama_dagang": batch.get("raw_materials", {}).get("nama_dagang", "Unknown"),
                    "kode_bahan_baku": batch.get("raw_materials", {}).get("kode_bahan_baku", "")
                })
        
        # Sort by days_remaining (expired first, then closest to expiry)
        critical_batches.sort(key=lambda x: x["days_remaining"])
        
        return {
            "count": len(critical_batches),
            "items": critical_batches[:20]  # Limit to 20 items in dropdown
        }
        
    except Exception as e:
        print(f"Error fetching ED notifications: {e}")
        return {"count": 0, "items": []}


async def _upload_msds_and_upsert_company_doc(rm_id: str, kode_bahan_baku: str, perusahaan: str, spec_parameters_raw: str, msds_file: UploadFile, spec_sheet_file: UploadFile = None):
    """Helper: parse spec_parameters (JSON), upload MSDS & PDF Spesifikasi Asli Supplier
    (kalau ada file baru), lalu upsert 1 baris ke raw_material_company_docs buat
    kombinasi (rm_id, perusahaan) tersebut.
    Kalau spec kosong semua & gak ada file MSDS/spec sheet (baik baru maupun lama),
    gak perlu insert apa-apa."""
    import json
    try:
        parsed_specs = json.loads(spec_parameters_raw) if spec_parameters_raw else []
    except Exception as e:
        print(f"Gagal parsing spec_parameters ({perusahaan}): {e}")
        parsed_specs = []

    has_spec_content = any((item.get("value") or "").strip() for item in parsed_specs if isinstance(item, dict))

    company_slug = "erfi" if perusahaan == "PT Erfi" else "heka"
    clean_kode = "".join(c for c in kode_bahan_baku if c.isalnum() or c in ('-', '_')).strip()

    msds_url = None
    if msds_file and msds_file.filename:
        try:
            file_bytes = await msds_file.read()
            file_path = f"msds/msds_{clean_kode}_{company_slug}.pdf"
            supabase.storage.from_("raw-material-docs").upload(
                path=file_path,
                file=file_bytes,
                file_options={"content-type": "application/pdf", "upsert": "true"}
            )
            msds_url = supabase.storage.from_("raw-material-docs").get_public_url(file_path)
        except Exception as e:
            print(f"Gagal upload MSDS ({perusahaan}): {e}")

    spec_sheet_url = None
    if spec_sheet_file and spec_sheet_file.filename:
        try:
            file_bytes = await spec_sheet_file.read()
            file_path = f"spec-sheets/specsheet_{clean_kode}_{company_slug}.pdf"
            supabase.storage.from_("raw-material-docs").upload(
                path=file_path,
                file=file_bytes,
                file_options={"content-type": "application/pdf", "upsert": "true"}
            )
            spec_sheet_url = supabase.storage.from_("raw-material-docs").get_public_url(file_path)
        except Exception as e:
            print(f"Gagal upload Spesifikasi Asli Supplier ({perusahaan}): {e}")

    if not has_spec_content and not msds_url and not spec_sheet_url:
        # Belum ada data sama sekali buat company ini -> jangan bikin baris kosong.
        # Kalau kebetulan baris lama (sisa data sebelum guard ini ada) juga kosong
        # total, hapus biar badge kelengkapan gak salah ke-centang.
        try:
            existing_resp = (
                supabase.table("raw_material_company_docs")
                .select("spec_parameters, msds_file_url, spec_sheet_file_url")
                .eq("raw_material_id", rm_id)
                .eq("perusahaan", perusahaan)
                .execute()
            )
            existing = existing_resp.data[0] if existing_resp.data else None
            if existing:
                old_specs = existing.get("spec_parameters") or []
                old_spec_filled = any((item.get("value") or "").strip() for item in old_specs if isinstance(item, dict))
                if not old_spec_filled and not existing.get("msds_file_url") and not existing.get("spec_sheet_file_url"):
                    supabase.table("raw_material_company_docs").delete() \
                        .eq("raw_material_id", rm_id).eq("perusahaan", perusahaan).execute()
        except Exception as e:
            print(f"Gagal bersihkan baris kosong company_docs ({perusahaan}): {e}")
        return

    doc_payload = {
        "raw_material_id": rm_id,
        "perusahaan": perusahaan,
        "spec_parameters": parsed_specs,
    }
    if msds_url:
        doc_payload["msds_file_url"] = msds_url
    if spec_sheet_url:
        doc_payload["spec_sheet_file_url"] = spec_sheet_url

    supabase.table("raw_material_company_docs").upsert(
        doc_payload, on_conflict="raw_material_id,perusahaan"
    ).execute()

@app.post("/raw-materials/{rm_id}/quick-upload-company-doc")
async def quick_upload_company_doc(
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

    rm_resp = supabase.table("raw_materials").select("kode_bahan_baku").eq("id", rm_id).single().execute()
    if not rm_resp.data:
        response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
        response.set_cookie("error_msg", "Bahan baku tidak ditemukan.")
        return response
    kode_bahan_baku = rm_resp.data["kode_bahan_baku"]

    existing_resp = supabase.table("raw_material_company_docs") \
        .select("spec_parameters") \
        .eq("raw_material_id", rm_id).eq("perusahaan", perusahaan).execute()
    existing_specs = existing_resp.data[0]["spec_parameters"] if existing_resp.data else []
    spec_parameters_raw = json.dumps(existing_specs or [])

    try:
        await _upload_msds_and_upsert_company_doc(
            rm_id, kode_bahan_baku, perusahaan, spec_parameters_raw, msds_file, spec_sheet_file
        )
        log_activity(current_user, "edit", "raw_material_company_doc", rm_id, f"Upload cepat dokumen {perusahaan}")
        response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
        response.set_cookie("success_msg", "Dokumen berhasil diupload.")
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

    log_activity(current_user, "create", "raw_material", new_rm_id, nama_dagang)

    # --- Simpan spec + MSDS per perusahaan (kalau diisi) ---
    try:
        await _upload_msds_and_upsert_company_doc(new_rm_id, kode_check, "PT Erfi", spec_parameters_erfi, msds_file_erfi, spec_sheet_file_erfi)
        await _upload_msds_and_upsert_company_doc(new_rm_id, kode_check, "PT Heka", spec_parameters_heka, msds_file_heka, spec_sheet_file_heka)

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

    except Exception as e:
        print(f"\n🔴 [ERROR add_raw_material] Bahan baku '{nama_dagang}' (id={new_rm_id}) sudah tersimpan, tapi data pendukung (komponen INCI/dokumen) gagal: {e}")
        response = RedirectResponse(url="/raw-materials", status_code=303)
        response.set_cookie("error_msg", f"Bahan baku '{nama_dagang}' tersimpan, tapi ada data pendukung yang gagal disimpan. Silakan cek dan lengkapi lewat menu Edit.")
        return response

@app.post("/raw-materials/quick-add")
async def quick_add_raw_material(
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
        log_activity(current_user, "create", "raw_material", new_rm["id"], nama_dagang)

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

@app.post("/brands/quick-add")
async def quick_add_brand(
    brand_name: str = Form(...),
    producer_name: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    brand_name = brand_name.strip()
    producer_name = producer_name.strip()
    
    if not brand_name or not producer_name:
        return JSONResponse(status_code=400, content={"success": False, "error": "Nama Merk dan Nama Produsen wajib diisi."})
    
    try:
        # 1. Cek/get-or-create Produsen
        prod_check = supabase.table("producers").select("id").ilike("name", producer_name).execute()
        if prod_check.data:
            producer_id = prod_check.data[0]["id"]
        else:
            new_prod = supabase.table("producers").insert({"name": producer_name}).execute()
            producer_id = new_prod.data[0]["id"]
        
        # 2. Cek duplikat brand
        brand_check = supabase.table("brands") \
            .select("id") \
            .eq("producer_id", producer_id) \
            .ilike("name", brand_name) \
            .execute()
        
        if brand_check.data:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"Merk '{brand_name}' sudah terdaftar di bawah produsen '{producer_name}'."}
            )
        
        # 3. Insert brand
        new_brand_resp = supabase.table("brands").insert({
            "producer_id": producer_id,
            "name": brand_name
        }).execute()
        
        new_brand = new_brand_resp.data[0]
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True, 
                "id": new_brand["id"], 
                "name": new_brand["name"], 
                "producer_name": producer_name
            }
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/raw-materials/edit/{rm_id}")
async def edit_raw_material(
    rm_id: str,
    nama_dagang: str = Form(...),
    kode_bahan_baku: str = Form(...),
    tipe: str = Form(...),
    produsen: str = Form(None),
    inci_name: List[str] = Form(None),
    cas_number: List[str] = Form(None),
    function: List[str] = Form(None),
    percent_internal: List[float] = Form(None),
    msds_file_erfi: UploadFile = File(None),
    msds_file_heka: UploadFile = File(None),
    spec_sheet_file_erfi: UploadFile = File(None),
    spec_sheet_file_heka: UploadFile = File(None),
    spec_parameters_erfi: str = Form("[]"),
    spec_parameters_heka: str = Form("[]"),
    current_user: dict = Depends(get_current_user)
):
    kode_check = kode_bahan_baku.strip()
    existing_rm = supabase.table("raw_materials").select("id").eq("kode_bahan_baku", kode_check).neq("id", rm_id).execute()
    
    if existing_rm.data:
        raise HTTPException(status_code=400, detail=f"Gagal Edit! Kode '{kode_check}' sudah dipakai oleh bahan baku lain.")

    # --- Ambil data LAMA dulu sebelum diubah, buat dibandingin di activity log ---
    old_rm_resp = supabase.table("raw_materials").select("*").eq("id", rm_id).single().execute()
    old_rm = old_rm_resp.data or {}
    old_company_docs_resp = supabase.table("raw_material_company_docs").select("*").eq("raw_material_id", rm_id).execute()
    old_company_docs = {d["perusahaan"]: d for d in (old_company_docs_resp.data or [])}

    # 1. UPDATE IDENTITAS DI RAW_MATERIALS (spec & MSDS udah pindah ke raw_material_company_docs)
    update_data = {
        "nama_dagang": nama_dagang,
        "kode_bahan_baku": kode_bahan_baku,
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
    changes = _build_diff_changes(old_rm, update_data, field_labels)

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
        log_activity(current_user, "update", "raw_material", rm_id, nama_dagang, changes)

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

@app.post("/raw-materials/delete/{rm_id}")
async def delete_raw_material(rm_id: str, current_user: dict = Depends(get_current_user)):
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
        # Hapus komponen internal dulu (kalau bahan komposit)
        supabase.table("raw_material_components").delete().eq("raw_material_id", rm_id).execute()
        supabase.table("raw_materials").delete().eq("id", rm_id).execute()
    except Exception as e:
        return RedirectResponse(url=f"/raw-materials?error=Gagal+menghapus:+{str(e)}", status_code=303)

    log_activity(current_user, "delete", "raw_material", rm_id, nama_sebelum_hapus)

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
                file_options={"content-type": "application/pdf", "upsert": "true"}
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
                file_options={"content-type": "application/pdf", "upsert": "true"}
            )
            halal_url = supabase.storage.from_("raw-material-docs").get_public_url(halal_path)
            print(f"--> Sukses upload Halal ke: {halal_url}")
        except Exception as e:
            print(f"Gagal upload Halal Cert: {e}")

    # 3b. Proses Upload Laporan Pemeriksaan Aktual (opsional) -- kalau QC punya dokumen
    # fisik/scan hasil pemeriksaan, ini dipake nanti jadi prioritas dibanding versi generate dari qc_results
    qc_report_url = None
    if qc_report_file and qc_report_file.filename:
        try:
            qc_report_bytes = await qc_report_file.read()
            qc_report_path = f"qc-reports/qcreport_{clean_batch}.pdf"

            supabase.storage.from_("raw-material-docs").upload(
                path=qc_report_path,
                file=qc_report_bytes,
                file_options={"content-type": "application/pdf", "upsert": "true"}
            )
            qc_report_url = supabase.storage.from_("raw-material-docs").get_public_url(qc_report_path)
            print(f"--> Sukses upload Laporan Pemeriksaan Aktual ke: {qc_report_url}")
        except Exception as e:
            print(f"Gagal upload Laporan Pemeriksaan Aktual: {e}")

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
        supabase.table("raw_material_batches").insert(batch_data).execute()
        print("--> Data Batch berhasil masuk ke Database!")
    except Exception as e:
        print(f"Gagal insert ke DB: {e}")

    # Redirect balik ke halaman utama bahan baku
    return RedirectResponse(url="/raw-materials", status_code=303)



@app.post("/raw-materials/batches/edit/{batch_id}")
async def edit_material_batch(
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
    # 1. Ambil data lama untuk handle file upload
    old_batch = supabase.table("raw_material_batches").select("*").eq("id", batch_id).single().execute().data
    
    clean_batch = "".join(c for c in no_batch if c.isalnum() or c in ('-', '_')).strip()
    
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

    # 2. Update Files if provided
    if coa_file and coa_file.filename:
        try:
            coa_bytes = await coa_file.read()
            coa_path = f"coa/coa_{clean_batch}.pdf"
            supabase.storage.from_("raw-material-docs").upload(
                path=coa_path, file=coa_bytes, file_options={"content-type": "application/pdf", "upsert": "true"}
            )
            update_data["coa_file_url"] = supabase.storage.from_("raw-material-docs").get_public_url(coa_path)
        except Exception as e:
            print(f"Gagal update CoA: {e}")

    if halal_file and halal_file.filename:
        try:
            halal_bytes = await halal_file.read()
            halal_path = f"halal/halal_{clean_batch}.pdf"
            supabase.storage.from_("raw-material-docs").upload(
                path=halal_path, file=halal_bytes, file_options={"content-type": "application/pdf", "upsert": "true"}
            )
            update_data["halal_batch_file_url"] = supabase.storage.from_("raw-material-docs").get_public_url(halal_path)
        except Exception as e:
            print(f"Gagal update Halal: {e}")

    if qc_report_file and qc_report_file.filename:
        try:
            qc_report_bytes = await qc_report_file.read()
            qc_report_path = f"qc-reports/qcreport_{clean_batch}.pdf"
            supabase.storage.from_("raw-material-docs").upload(
                path=qc_report_path, file=qc_report_bytes, file_options={"content-type": "application/pdf", "upsert": "true"}
            )
            update_data["qc_report_file_url"] = supabase.storage.from_("raw-material-docs").get_public_url(qc_report_path)
        except Exception as e:
            print(f"Gagal update QC Report: {e}")

    try:
        supabase.table("raw_material_batches").update(update_data).eq("id", batch_id).execute()
        log_activity(current_user, "edit", "raw_material_batch", batch_id, f"Update batch {no_batch}")
    except Exception as e:
        print(f"Gagal update batch: {e}")

    return RedirectResponse(url="/raw-materials?tab=batch-tab", status_code=303)


@app.post("/raw-materials/batches/{batch_id}/quick-upload-doc")
async def quick_upload_batch_doc(
    batch_id: str,
    coa_file: UploadFile = File(None),
    halal_file: UploadFile = File(None),
    qc_report_file: UploadFile = File(None),
    current_user: dict = Depends(get_current_user)
):
    # Route ini CUMA nyentuh kolom file URL, tidak menyentuh field lain
    # (no_batch, supplier, tanggal, kesimpulan, dll) di baris batch tersebut.
    batch_resp = supabase.table("raw_material_batches").select("no_batch").eq("id", batch_id).single().execute()
    if not batch_resp.data:
        response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
        response.set_cookie("error_msg", "Batch tidak ditemukan.")
        return response

    no_batch = batch_resp.data["no_batch"]
    clean_batch = "".join(c for c in no_batch if c.isalnum() or c in ("-", "_")).strip()

    update_data = {}

    if coa_file and coa_file.filename:
        try:
            coa_bytes = await coa_file.read()
            coa_path = f"coa/coa_{clean_batch}.pdf"
            supabase.storage.from_("raw-material-docs").upload(
                path=coa_path, file=coa_bytes, file_options={"content-type": "application/pdf", "upsert": "true"}
            )
            update_data["coa_file_url"] = supabase.storage.from_("raw-material-docs").get_public_url(coa_path)
        except Exception as e:
            print(f"Gagal quick-upload CoA: {e}")

    if halal_file and halal_file.filename:
        try:
            halal_bytes = await halal_file.read()
            halal_path = f"halal/halal_{clean_batch}.pdf"
            supabase.storage.from_("raw-material-docs").upload(
                path=halal_path, file=halal_bytes, file_options={"content-type": "application/pdf", "upsert": "true"}
            )
            update_data["halal_batch_file_url"] = supabase.storage.from_("raw-material-docs").get_public_url(halal_path)
        except Exception as e:
            print(f"Gagal quick-upload Halal: {e}")

    if qc_report_file and qc_report_file.filename:
        try:
            qc_report_bytes = await qc_report_file.read()
            qc_report_path = f"qc-reports/qcreport_{clean_batch}.pdf"
            supabase.storage.from_("raw-material-docs").upload(
                path=qc_report_path, file=qc_report_bytes, file_options={"content-type": "application/pdf", "upsert": "true"}
            )
            update_data["qc_report_file_url"] = supabase.storage.from_("raw-material-docs").get_public_url(qc_report_path)
        except Exception as e:
            print(f"Gagal quick-upload QC Report: {e}")

    if update_data:
        try:
            supabase.table("raw_material_batches").update(update_data).eq("id", batch_id).execute()
            log_activity(current_user, "edit", "raw_material_batch", batch_id, f"Upload cepat dokumen batch {no_batch}")
            response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
            response.set_cookie("success_msg", "Dokumen berhasil diupload.")
        except Exception as e:
            print(f"Gagal simpan quick-upload batch doc: {e}")
            response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
            response.set_cookie("error_msg", "Gagal upload dokumen. Coba lagi.")
    else:
        response = RedirectResponse(url="/raw-materials?tab=docs-tab", status_code=303)
        response.set_cookie("error_msg", "Tidak ada file yang dipilih.")
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
        
        log_activity(current_user, "acc_dipakai", "raw_material_batch", batch_id, f"ED diperpanjang ke {new_expiry_date}")
        
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
        
        log_activity(current_user, "acc_dimusnahkan", "raw_material_batch", batch_id, "Batch dimusnahkan (dispose)")
        
        response = RedirectResponse(url="/raw-materials?tab=ed-tab", status_code=303)
        response.set_cookie("success_msg", "Batch berhasil dimusnahkan (ACC Dimusnahkan).")
        return response
        
    except Exception as e:
        print(f"Gagal ACC Dimusnahkan: {e}")
        response = RedirectResponse(url="/raw-materials?tab=ed-tab", status_code=303)
        response.set_cookie("error_msg", f"Gagal memusnahkan batch: {str(e)}")
        return response


@app.post("/raw-materials/cpkb/update")
async def update_cpkb_document(
    request: Request,
    perusahaan: str = Form(...),
    cpkb_file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    # Validasi perusahaan (hanya 2 PT yang didukung di app ini)
    if perusahaan not in ("PT Erfi", "PT Heka"):
        response = RedirectResponse(url="/raw-materials", status_code=303)
        response.set_cookie("error_msg", "Perusahaan tidak valid.")
        return response

    if not cpkb_file or not cpkb_file.filename:
        response = RedirectResponse(url="/raw-materials", status_code=303)
        response.set_cookie("error_msg", "File dokumen SOP CPKB wajib dipilih.")
        return response

    try:
        file_bytes = await cpkb_file.read()
        company_slug = "erfi" if perusahaan == "PT Erfi" else "heka"
        path = f"sop-cpkb/sop_cpkb_{company_slug}.pdf"

        # Upload (overwrite in-place) ke bucket raw-material-docs
        supabase.storage.from_("raw-material-docs").upload(
            path=path,
            file=file_bytes,
            file_options={"content-type": "application/pdf", "upsert": "true"}
        )
        file_url = supabase.storage.from_("raw-material-docs").get_public_url(path)

        # Upsert 1 baris per perusahaan di tabel cpkb_raw_material (dibaca generator Bab II)
        existing = supabase.table("cpkb_raw_material") \
            .select("id").eq("perusahaan", perusahaan).limit(1).execute()
        if existing.data:
            supabase.table("cpkb_raw_material").update({"file_url": file_url}).eq("perusahaan", perusahaan).execute()
        else:
            supabase.table("cpkb_raw_material").insert({"perusahaan": perusahaan, "file_url": file_url}).execute()

        log_activity(current_user, "update", "cpkb_raw_material", perusahaan, f"SOP CPKB {perusahaan}")

        response = RedirectResponse(url="/raw-materials", status_code=303)
        response.set_cookie("success_msg", f"SOP CPKB {perusahaan} berhasil diperbarui.")
        return response

    except Exception as e:
        print(f"Gagal update SOP CPKB ({perusahaan}): {e}")
        response = RedirectResponse(url="/raw-materials", status_code=303)
        response.set_cookie("error_msg", "Gagal upload SOP CPKB. Coba lagi.")
        return response

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
async def restore_product(product_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Akses ditolak")
        
    try:
        supabase.table("products").update({"is_deleted": False, "deleted_at": None}).eq("id", product_id).execute()
        # Perlu fungsi log_activity yang sudah ada di main.py
        log_activity(current_user, "restore", "product", product_id, "Restore produk dari sampah")
        return RedirectResponse(url="/admin/trash?success=Produk berhasil dikembalikan", status_code=303)
    except Exception as e:
        print(f"Gagal restore produk: {e}")
        return RedirectResponse(url="/admin/trash?error=Gagal mengembalikan produk", status_code=303)

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
        "brand_id": brand_id if brand_id else None
    }
    
    try:
        new_product_resp = supabase.table("products").insert(product_data).execute()
        new_product_id = new_product_resp.data[0]["id"] if new_product_resp.data else None
        if not new_product_id:
            raise Exception("Insert produk tidak mengembalikan data")
        log_activity(current_user, "create", "product", new_product_id, nama_produk)
        return RedirectResponse(url="/", status_code=303)
    except Exception as e:
        print(f"\n🔴 [ERROR add_product] Gagal menyimpan produk '{nama_produk}': {e}")
        # Redirect balik ke halaman dashboard dengan pesan error, supaya user tahu harus input ulang
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie("error_msg", f"Gagal menyimpan produk '{nama_produk}'. Silakan coba lagi.")
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
            inci_name_raw = (comp["inci_name"] or "").strip()
            # Normalisasi key: hapus spasi berlebih & samakan besar-kecil huruf,
            inci_key = inci_name_raw.lower()
            if inci_key not in grouped_pure:
                grouped_pure[inci_key] = {
                    "inci_name": inci_name_raw,
                    "function": comp["function"],
                    # Gunakan Decimal('0.0') sebagai inisialisasi awal agar presisi
                    "pct_ww_decimal": Decimal('0.0')
                }
            # Jumlahkan dengan tipe data Decimal murni
            grouped_pure[inci_key]["pct_ww_decimal"] += Decimal(str(comp["pct_ww"]))

    # KUNCI PERBAIKAN: Konversi hasil akhir ke float yang bersih setelah selesai dijumlahkan
    pure_breakdown = []
    for item in grouped_pure.values():
        clean_sum = float(item["pct_ww_decimal"].normalize())
        pure_breakdown.append({
            "inci_name": item["inci_name"],
            "function": item["function"],
            "pct_ww": clean_sum
        })
    pure_breakdown.sort(key=lambda x: x["pct_ww"], reverse=True)

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
async def export_qualquant_xlsx(product_id: str, current_user: dict = Depends(get_current_user)):
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

    log_activity(current_user, "export", "product_qualquan_xlsx", product_id, filename)

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

    # 5. Render Checklist (halaman pembuka) jadi PDF sendiri
    checklist_html = templates.env.get_template("bab2_checklist.html").render(
        product=product,
        company=company
        )
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

            # Render blok Spesifikasi (selalu di-generate dari text -- versi PDF gabungan
            # sengaja gak pake logic PDF-priority biar layout dokumen tetap seragam)
            spec_html = templates.env.get_template("bab2_spec_block.html").render(
                item=item,
                index=idx,
                company=company
            )
            spec_buffer = io.BytesIO()
            spec_status = pisa.CreatePDF(src=spec_html, dest=spec_buffer)
            if spec_status.err:
                print(f"Gagal generate blok Spesifikasi bahan baku {nama_bahan}")
            else:
                spec_buffer.seek(0)
                for page in PdfReader(spec_buffer).pages:
                    writer.add_page(page)

            # Render blok Catatan Pemeriksaan Aktual (selalu di-generate dari data batch)
            qc_html = templates.env.get_template("bab2_qc_block.html").render(
                item=item,
                index=idx,
                company=company
            )
            qc_buffer = io.BytesIO()
            qc_status = pisa.CreatePDF(src=qc_html, dest=qc_buffer)
            if qc_status.err:
                print(f"Gagal generate blok Catatan Pemeriksaan bahan baku {nama_bahan}")
            else:
                qc_buffer.seek(0)
                for page in PdfReader(qc_buffer).pages:
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



def _safe_zip_name(name: str) -> str:
    """Bersihin nama biar aman dipakai sebagai nama file/folder di dalam ZIP
    (buang karakter yang gak diizinkan di Windows/macOS: < > : " / \\ | ? *)."""
    name = (name or "").strip()
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "Tanpa_Nama"


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

    log_activity(current_user, "update", "product_finished_specs", product_id, f"Spesifikasi Produk Jadi - {product['nama_produk']}")

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
        raise HTTPException(status_code=400, detail="Spesifikasi produk jadi belum diisi, silakan isi form terlebih dahulu.")
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
    resp = await download_finished_spec(product_id, current_user)
    resp.headers["Content-Disposition"] = resp.headers["Content-Disposition"].replace("attachment", "inline")
    return resp

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

    # NEW: Fetch Finished Product Specification (for dynamic PDF generation and checklist status)
    finished_spec = None
    try:
        spec_res = supabase.table("product_finished_specs").select("*").eq("product_id", product_id).execute()
        if spec_res.data:
            finished_spec = spec_res.data[0]
    except Exception as e:
        print(f"[WARNING] Gagal/belum ada data product_finished_specs: {e}")

    # 5. RENDER COVER & FORMULA VIA TEMPLATE HTML
    template = templates.get_template("bab3_checklist.html")
    rendered_html = template.render({
        "product": product,
        "perusahaan": perusahaan,
        "company": {**company, "logo_width": _logo_render_width(company.get("logo"))},
        "company_sop": company_sop,
        "latest_batch": latest_batch,
        "processed_formula": processed_formula,
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
        poin6a_spj = product.get("spek_produk_jadi_file_url")

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
            .select("percent_in_formula, raw_materials(nama_dagang, raw_material_components(*))") \
            .eq("product_id", product_id) \
            .execute()
        
        grouped_pure = {}
        for line in (formula_resp.data or []):
            pct_in_formula = float(line.get("percent_in_formula") or 0)
            rm = line.get("raw_materials") or {}
            components = rm.get("raw_material_components") or []
            
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
        company_sop.get("monitoring_efek_samping_file_url") or product.get("monitoring_efek_samping_file_url"), # Poin 3
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

# =====================================================================
#  PUBLIC LINK BPOM - PERMALINK UNTUK VERIFIKATOR BPOM
#  Route /dip/[slug-nama-produk]-[id] bersifat PUBLIK (tanpa login) & permanen
#  (tidak ada masa expired) supaya bisa dilampirkan ke portal
#  e-registration BPOM dan tetap hidup bertahun-tahun.
#  Contoh: /dip/sunscreen-serum-spf-50-e623d2e4-1234-5678-9abc-def012345678
#
#  Keamanan akses file:
#   - PDF gabungan tiap Bab (I, II, III, IV) -> di-stream lewat backend
#     (proxy), browser tidak pernah menyentuh storage langsung.
#   - File individu di Supabase Storage (CoA, Halal, MSDS, Spesifikasi)
#     -> short-lived signed URL (default 1 jam) yang di-generate otomatis
#     tiap kali halaman hub dibuka.
# =====================================================================

def _parse_storage_url(url: str):
    """Ekstrak (bucket, path) dari public URL Supabase Storage.
    Contoh:
      https://xxxx.supabase.co/storage/v1/object/public/raw-material-docs/products/123/a.pdf
      -> ('raw-material-docs', 'products/123/a.pdf')
    Kalau formatnya bukan public storage URL, return (None, None)."""
    if not url:
        return None, None
    marker = "/storage/v1/object/public/"
    if marker not in url:
        return None, None
    rest = url.split(marker, 1)[1].split("?", 1)[0]
    if "/" not in rest:
        return None, None
    bucket, path = rest.split("/", 1)
    return bucket, path


def _storage_signed_url(public_url: str, expires_in: int = 3600):
    """Generate short-lived signed URL dari public URL Supabase Storage.
    URL asli storage tidak dibocorkan ke browser; yang dikirim cuma signed URL
    sementara (default 1 jam). Kalau parsing/generate gagal, fallback ke URL
    asli supaya link tetap jalan di halaman publik."""
    if not public_url:
        return None
    bucket, path = _parse_storage_url(public_url)
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
        ip_address=_client_ip(request),
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
            _apply_company_specific_docs(rm, perusahaan)

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


_DIP_BAB_GENERATORS = {
    "1": download_bab1_document,
    "2": download_bab2_document,
    "3": download_dip_bab3,
    "4": download_dip_bab4,
}


async def _dip_stream_bab(product_id: str, bab_num: str, as_attachment: bool):
    """Stream PDF gabungan Bab I-IV lewat backend (proxy), tanpa login."""
    if not _dip_public_check_product(product_id):
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")
    gen = _DIP_BAB_GENERATORS.get(bab_num)
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
        return await download_bab2_document_zip(product_id, None)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"\n🔴 [PUBLIC DIP ZIP ERROR] Gagal generate ZIP Bab 2 untuk product_id={product_id}")
        print(f"   Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Dokumen sedang tidak dapat diproses. Silakan coba beberapa saat lagi.")


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
            .select("*, raw_materials(nama_dagang, kode_bahan_baku)") \
            .eq("product_id", product_id) \
            .order("created_at").execute()
        formula = formula_resp.data or []

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

    # Get error message from cookie (if any)
    error_msg = request.cookies.get("error_msg")

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
            "error_msg": error_msg,
            "current_user": current_user,
        }
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
                
                # Check file size (10 MB limit)
                max_size = 10 * 1024 * 1024  # 10 MB
                if len(file_bytes) > max_size:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Ukuran file terlalu besar! Maksimal ukuran file adalah 10 MB. Silakan kompres PDF Anda terlebih dahulu."
                    )
                
                path = f"products/{product_id}/{path_suffix}.pdf"
                supabase.storage.from_(bucket_name).upload(
                    path=path,
                    file=file_bytes,
                    file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                return supabase.storage.from_(bucket_name).get_public_url(path)
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
                lines = []
                for i in range(len(raw_material_id)):
                    rm_id = (raw_material_id[i] or "").strip()
                    if rm_id:
                        try:
                            pct = float(percentage[i]) if percentage and i < len(percentage) else 0.0
                        except (TypeError, ValueError):
                            pct = 0.0
                        lines.append({
                            "product_id": product_id,
                            "raw_material_id": rm_id,
                            "percent_in_formula": pct,
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
        log_activity(current_user, "update", "product", product_id, nama_produk, product_changes)
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie("success_msg", f"Data & dokumen DIP produk '{nama_produk}' berhasil diperbarui!")
    return response

@app.post("/products/delete/{product_id}")
async def delete_product(product_id: str, current_user: dict = Depends(get_current_user)):
    # Ambil nama-nya dulu sebelum dihapus, biar activity log masih kebaca gak "id doang"
    product_before = supabase.table("products").select("nama_produk").eq("id", product_id).single().execute()
    nama_sebelum_hapus = product_before.data.get("nama_produk") if product_before.data else product_id

    try:
        # Soft Delete: cuma tandai is_deleted=True + deleted_at, JANGAN hapus formula
        # Baru hapus produknya (Soft Delete) - set deleted_at ke waktu sekarang (WIB)
        deleted_at = datetime.now(WIB).isoformat()
        supabase.table("products").update({"is_deleted": True, "deleted_at": deleted_at}).eq("id", product_id).execute()
    except Exception as e:
        print(f"Gagal hapus produk {product_id}: {e}")
        return RedirectResponse(url="/", status_code=303)

    log_activity(current_user, "delete", "product", product_id, nama_sebelum_hapus)
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
    color_value: str = Form(None),
    current_user: dict = Depends(get_current_user)
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
async def edit_sample_submission_page(request: Request, submission_id: str, current_user: dict = Depends(get_current_user)):
    try:
        sub_resp = supabase.table("sample_submissions").select("*").eq("id", submission_id).single().execute()
        submission = sub_resp.data
        if not submission:
            raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")

        brand_query = supabase.table("brands").select("*, producers(*)").execute()
        brands = brand_query.data or []
        
        product_query = supabase.table("products").select("id, nama_produk, netto, sediaan, kemasan, perusahaan").eq("is_deleted", False).execute()
        products = product_query.data or []
    except Exception as e:
        print(f"Gagal muat data edit sample: {e}")
        raise HTTPException(status_code=500, detail="Gagal memuat form edit")

    return templates.TemplateResponse(
        request=request,
        name="sample_form.html",
        context={
            "brands": brands,
            "existing_products": products,
            "submission": submission,
            "current_user": current_user,
            "ed_notification_count": await get_ed_notification_count()
        }
    )


# 3. PROSES POST UPDATE SAMPLE
@app.post("/sample-submissions/edit/{submission_id}")
async def update_sample_submission(
    submission_id: str,
    sample_prefix: str = Form("FSP"),   
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
    color_value: str = Form(None),
    current_user: dict = Depends(get_current_user)
):
    # 1. Ambil data lama buat nemuin suffix /TGL/X.Y aslinya
    try:
        sub_resp = supabase.table("sample_submissions").select("sample_code").eq("id", submission_id).single().execute()
        old_code = sub_resp.data.get("sample_code", "FSP/01-01-2026/1.1") if sub_resp.data else "FSP/01-01-2026/1.1"
    except Exception:
        raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")

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

    # AUTO-SAVE BRAND BARU saat edit, supaya konsisten dgn create:
    # kalau user pilih "New", produsen & merk langsung dibuat/diambil di DB
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

    update_payload = {
        "sample_code": new_sample_code,  
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
@app.post("/sample-submissions/delete/{submission_id}")
async def delete_sample_submission(submission_id: str, current_user: dict = Depends(get_current_user)):
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

    # Fetch legal documents for all brands from brand_legal_documents table
    if brands:
        brand_ids = [b["id"] for b in brands]
        try:
            docs_resp = supabase.table("brand_legal_documents").select("brand_id, perusahaan, hak_lisensi_merk_file_url").in_("brand_id", brand_ids).execute()
            docs_by_brand = {}
            for doc in docs_resp.data or []:
                bid = doc["brand_id"]
                if bid not in docs_by_brand:
                    docs_by_brand[bid] = {
                        "PT Erfi": {"hak_lisensi_merk_file_url": None},
                        "PT Heka": {"hak_lisensi_merk_file_url": None},
                    }
                docs_by_brand[bid][doc["perusahaan"]] = {"hak_lisensi_merk_file_url": doc.get("hak_lisensi_merk_file_url")}
            
            # Attach to each brand
            for b in brands:
                # Pastikan selalu ada struktur default, meski merk baru
                b["legal_docs"] = docs_by_brand.get(b["id"], {
                    "PT Erfi": {"hak_lisensi_merk_file_url": None},
                    "PT Heka": {"hak_lisensi_merk_file_url": None},
                })
        except Exception as e:
            print(f"Gagal ambil dokumen legal brand: {e}")
            for b in brands:
                b["legal_docs"] = {
                    "PT Erfi": {"hak_lisensi_merk_file_url": None},
                    "PT Heka": {"hak_lisensi_merk_file_url": None},
                }
    else:
        # Tambahkan fallback untuk kasus merk ada tapi docs_by_brand kosong
        for b in brands:
            b["legal_docs"] = {
                "PT Erfi": {"hak_lisensi_merk_file_url": None},
                "PT Heka": {"hak_lisensi_merk_file_url": None},
            }

    success_msg = request.cookies.get("success_msg")
    error_msg = request.cookies.get("error_msg")

    response = templates.TemplateResponse(
        request=request,
        name="brands.html",
        context={
            "brands": brands,
            "success_msg": success_msg,
            "error_msg": error_msg,
            "ed_notification_count": await get_ed_notification_count(),
            "current_user": current_user
        }
    )
    response.delete_cookie("success_msg")
    response.delete_cookie("error_msg")
    return response


@app.post("/brands/{brand_id}/update-documents")
async def update_brand_documents(
    brand_id: str,
    perusahaan: str = Form(...),
    hak_lisensi_merk_file: UploadFile = File(None),
    current_user: dict = Depends(get_current_user)
):
    # Validasi perusahaan
    if perusahaan not in ["PT Erfi", "PT Heka"]:
        response = RedirectResponse(url="/brands", status_code=303)
        response.set_cookie("error_msg", "Perusahaan tidak valid. Harus PT Erfi atau PT Heka.")
        return response

    # Map perusahaan to slug for file path
    perusahaan_slug = "erfi" if perusahaan == "PT Erfi" else "heka"

    try:
        update_data = {}
        
        if hak_lisensi_merk_file and hak_lisensi_merk_file.filename:
            file_bytes = await hak_lisensi_merk_file.read()
            # Path includes perusahaan_slug to avoid conflicts
            path = f"brands/hak_lisensi_merk_{brand_id}_{perusahaan_slug}.pdf"
            supabase.storage.from_("legal-documents").upload(
                path=path,
                file=file_bytes,
                file_options={"content-type": "application/pdf", "upsert": "true"}
            )
            update_data["hak_lisensi_merk_file_url"] = supabase.storage.from_("legal-documents").get_public_url(path)

        if update_data:
            # Check if row exists for this brand_id + perusahaan
            existing_resp = supabase.table("brand_legal_documents").select("id").eq("brand_id", brand_id).eq("perusahaan", perusahaan).limit(1).execute()
            
            if existing_resp.data:
                # Update existing row
                supabase.table("brand_legal_documents").update({
                    "hak_lisensi_merk_file_url": update_data["hak_lisensi_merk_file_url"],
                    "updated_at": "now()"
                }).eq("brand_id", brand_id).eq("perusahaan", perusahaan).execute()
            else:
                # Insert new row
                supabase.table("brand_legal_documents").insert({
                    "brand_id": brand_id,
                    "perusahaan": perusahaan,
                    "hak_lisensi_merk_file_url": update_data["hak_lisensi_merk_file_url"]
                }).execute()

        response = RedirectResponse(url="/brands", status_code=303)
        response.set_cookie("success_msg", f"Dokumen Hak/Lisensi Merk untuk {perusahaan} berhasil diperbarui.")
        return response

    except Exception as e:
        print(f"Gagal update dokumen brand {brand_id} untuk {perusahaan}: {e}")
        response = RedirectResponse(url="/brands", status_code=303)
        response.set_cookie("error_msg", "Gagal upload dokumen. Coba lagi.")
        return response

@app.get("/sample-submissions", response_class=HTMLResponse)
async def sample_submissions_list(request: Request, search: str = None, current_user: dict = Depends(get_current_user)):
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
        context={
            "submissions": submissions,
            "search_value": search or "",
            "ed_notification_count": await get_ed_notification_count(),
            "current_user": current_user
        }
    )

@app.get("/sample-submissions/form", response_class=HTMLResponse)
async def sample_submission_form(request: Request, current_user: dict = Depends(get_current_user)):
    try:
        brand_query = supabase.table("brands").select("*, producers(*)").execute()
        brands = brand_query.data or []
        
        # Kolom di tabel products namanya "perusahaan", bukan "company" (bug #2)
        product_query = supabase.table("products").select("id, nama_produk, netto, sediaan, kemasan, perusahaan").eq("is_deleted", False).execute()
        products = product_query.data or []
    except Exception as e:
        print(f"Gagal ambil data pendukung form: {e}")
        brands, products = [], []
        
    return templates.TemplateResponse(
        request=request,
        name="sample_form.html",
        # Key "existing_products" harus sama persis kayak yang dipakai template (bug #1)
        context={
            "brands": brands,
            "current_user": current_user,
            "existing_products": products,
            "ed_notification_count": await get_ed_notification_count()
        }
    )


@app.get("/sample-submissions/preview/{submission_id}", response_class=HTMLResponse)
async def sample_submission_preview(request: Request, submission_id: str, current_user: dict = Depends(get_current_user)):
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
        context={
            "current_user": current_user,
            "s": submission,
            "ed_notification_count": await get_ed_notification_count()
        }
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

        # Sembunyikan akun yang di-protect dari admin lain -- akun itu cuma bisa
        # lihat dirinya sendiri di list, admin lain sama sekali gak lihat baris ini
        users_list = [
            u for u in users_list
            if not u.get("is_protected") or u["id"] == current_user["id"]
        ]
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

        # VALIDASI: Username wajib unik (case-insensitive). Login via username memakai
        # kolom full_name di tabel profiles, jadi kalau dobel, login bisa ambigu.
        existing_profiles = supabase.table("profiles").select("full_name").execute()
        existing_usernames = {str(pf.get("full_name") or "").strip().lower() for pf in (existing_profiles.data or [])}
        if clean_username in existing_usernames:
            print(f"Tolak buat akun: username '{clean_username}' sudah dipakai.")
            return RedirectResponse(url="/admin/users?error=username_exists", status_code=303)

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
            # Jangan pakai string "now()" (PostgREST simpan sebagai literal & bisa gagal cast ke timestamptz).
            # Kirim timestamp ISO nyata dari Python.
            "updated_at": datetime.now(WIB).isoformat()
        }).execute()

        return RedirectResponse(url="/admin/users?status=create_success", status_code=303)

    except Exception as e:
        print(f"Gagal bikin user baru (admin): {e}")
        error_str = str(e).lower()
        if "already been registered" in error_str or "already registered" in error_str or "user already exists" in error_str:
            return RedirectResponse(url="/admin/users?error=email_exists", status_code=303)
        return RedirectResponse(url="/admin/users?error=create_failed", status_code=303)

# 2. PROSES RESET PASSWORD USER (KHUSUS ADMIN)
@app.post("/admin/users/reset-password")
async def admin_reset_password(
    target_uid: str = Form(...),
    new_password: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    # Proteksi: cuma admin yang boleh reset password user
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Super Admin.")

    # Validasi minimal: password baru minimal 6 karakter (sama kayak minlength di form modal)
    if len(new_password.strip()) < 6:
        return RedirectResponse(url="/admin/users?error=password_too_short", status_code=303)

    # Cek apakah target akun terproteksi -- kalau iya dan yang minta bukan akun itu sendiri, tolak
    if target_uid != current_user["id"]:
        target_check = supabase.table("profiles").select("is_protected").eq("id", target_uid).execute()
        if target_check.data and target_check.data[0].get("is_protected"):
            return RedirectResponse(url="/admin/users?error=protected_account", status_code=303)

    try:
        # Ambil nama user target buat activity log
        target_res = supabase.table("profiles").select("full_name").eq("id", target_uid).execute()
        target_name = target_res.data[0].get("full_name") if target_res.data else None

        # Update password di Supabase Auth Service.
        # Dipakai update_user_by_id karena di supabase-py v2 method update_user sudah dihapus.
        supabase.auth.admin.update_user_by_id(target_uid, {"password": new_password})

        # Catat activity log
        log_activity(
            current_user,
            "reset_password",
            "user",
            target_uid,
            target_name or f"User {target_uid}"
        )

        return RedirectResponse(url="/admin/users?status=reset_success", status_code=303)

    except Exception as e:
        print(f"Gagal reset password user {target_uid}: {e}")
        return RedirectResponse(url="/admin/users?error=reset_failed", status_code=303)

# 3. PROSES UPDATE ROLE USER (POST)
@app.post("/admin/users/update-role")
async def update_user_role(
    target_uid: str = Form(...),
    new_role: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Akses ditolak!")

    # Cek apakah target akun terproteksi -- kalau iya dan yang minta bukan akun itu sendiri, tolak
    if target_uid != current_user["id"]:
        target_check = supabase.table("profiles").select("is_protected").eq("id", target_uid).execute()
        if target_check.data and target_check.data[0].get("is_protected"):
            return RedirectResponse(url="/admin/users?error=protected_account", status_code=303)

    try:
        # Update kolom role di tabel profiles berdasarkan UUID user yang dipilih
        # (updated_at pakai timestamp ISO asli, bukan string "now()" biar gak gagal cast di PostgREST)
        supabase.table("profiles").update({"role": new_role, "updated_at": datetime.now(WIB).isoformat()}).eq("id", target_uid).execute()
        return RedirectResponse(url="/admin/users?status=update_success", status_code=303)
    except Exception as e:
        print(f"Gagal update role: {e}")
        return RedirectResponse(url="/admin/users?error=update_failed", status_code=303)

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

        # 2. Ambil ID produk yang udah punya formula (Bab 2)
        prods_with_formula = set()
        try:
            formula_prods_resp = supabase.table("product_formula_lines").select("product_id").execute()
            prods_with_formula = set([item["product_id"] for item in (formula_prods_resp.data or []) if item.get("product_id")])
        except Exception as e:
            print(f"Gagal tarik formula lines: {e}")

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
                "b4_ok": False,
                "b4_ratio": "0/5",
                "progress_pct": 0,
                "is_complete": False
            }

            try:
                p["status_na"] = compute_status_na(p.get("tanggal_aktif_na"), p.get("status_na") or "belum_terdaftar")
                
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
                
                total_checks = len(b1_items) + 1 + len(b3_files) + len(b4_files)
                current_checks = b1_count + (1 if b2_ok else 0) + b3_count + b4_count
                progress_pct = int((current_checks / total_checks) * 100)
                
                p["dip_summary"] = {
                    "b1_ok": b1_ok,
                    "b1_ratio": f"{b1_count}/{len(b1_items)}",
                    "b1_missing": b1_missing,
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
            "success_msg": success_msg
        }
    )

@app.post("/admin/users/delete")
async def delete_user(
    target_uid: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    # Proteksi: cuma admin yang boleh hapus user
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Akses ditolak! Khusus Super Admin.")

    # Cek biar admin gak ketidaksengajaan ngapus akunnya sendiri
    if target_uid == current_user["id"]:
        return RedirectResponse(url="/admin/users?error=cannot_delete_self", status_code=303)

    # Cek apakah target akun terproteksi (dan bukan dirinya sendiri -- walau baris di atas
    # sudah menangkap kasus itu, ini sebagai lapis proteksi tambahan)
    target_check = supabase.table("profiles").select("is_protected").eq("id", target_uid).execute()
    if target_check.data and target_check.data[0].get("is_protected"):
        return RedirectResponse(url="/admin/users?error=protected_account", status_code=303)

    try:
        # Inisialisasi admin client buat hapus user dari Supabase Auth
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        supabase_admin = create_client(supabase_url, supabase_service_key)

        # 1. Hapus dari Supabase Auth Service
        supabase_admin.auth.admin.delete_user(target_uid)

        # 2. Hapus dari tabel profiles
        supabase.table("profiles").delete().eq("id", target_uid).execute()

        return RedirectResponse(url="/admin/users?status=delete_success", status_code=303)

    except Exception as e:
        print(f"Gagal hapus user: {e}")
        return RedirectResponse(url="/admin/users?error=delete_failed", status_code=303)
