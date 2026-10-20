import os as _os

# Validasi mentah SEBELUM modul pembuat klien / FastAPI diimpor. Hanya aktif
# bila DIP_APP_ENV=staging. Tanpa Settings, tanpa supabase, tanpa network.
# Kontrak eksplisit: environment efektif.
if _os.getenv("DIP_APP_ENV", "").strip().lower() == "staging":
    from app.staging_preflight import validate_effective_env as _preflight_startup

    _preflight_startup(_os.environ, caller="startup")

from fastapi import FastAPI, Request, Form, HTTPException, Response, File, UploadFile, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List
from app.database import supabase
from app.object_store import parse_storage_url as _parse_storage_url


def _apply_company_specific_docs(rm: dict, perusahaan: str) -> dict:
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


async def _upload_msds_and_upsert_company_doc(rm_id, kode_bahan_baku, perusahaan, spec_parameters, msds_file, spec_sheet_file):
    uploaded_documents = []
    clean_kode = "".join(c for c in (kode_bahan_baku or "") if c.isalnum() or c in ("-", "_")).strip()
    company_slug = "erfi" if perusahaan == "PT Erfi" else "heka"
    msds_url = None
    spec_sheet_url = None

    if msds_file and getattr(msds_file, "filename", None):
        try:
            file_bytes = await msds_file.read()
            if file_bytes and file_bytes[:4] == b"%PDF" and len(file_bytes) <= 10 * 1024 * 1024:
                file_path = f"msds/msds_{clean_kode}_{company_slug}.pdf"
                object_store.upload_pdf("raw-material-docs", file_path, file_bytes, client=supabase)
                msds_url = object_store.public_url("raw-material-docs", file_path, client=supabase)
                uploaded_documents.append("MSDS")
        except Exception as e:
            print(f"Gagal upload MSDS ({perusahaan}): {e}")

    if spec_sheet_file and getattr(spec_sheet_file, "filename", None):
        try:
            file_bytes = await spec_sheet_file.read()
            if file_bytes and file_bytes[:4] == b"%PDF" and len(file_bytes) <= 10 * 1024 * 1024:
                file_path = f"spec-sheets/specsheet_{clean_kode}_{company_slug}.pdf"
                object_store.upload_pdf("raw-material-docs", file_path, file_bytes, client=supabase)
                spec_sheet_url = object_store.public_url("raw-material-docs", file_path, client=supabase)
                uploaded_documents.append("PDF Spesifikasi")
        except Exception as e:
            print(f"Gagal upload PDF Spesifikasi ({perusahaan}): {e}")

    doc_payload = {
        "raw_material_id": rm_id,
        "perusahaan": perusahaan,
        "spec_parameters": spec_parameters,
    }
    if msds_url:
        doc_payload["msds_file_url"] = msds_url
    if spec_sheet_url:
        doc_payload["spec_sheet_file_url"] = spec_sheet_url

    try:
        supabase.table("raw_material_company_docs").upsert(
            doc_payload, on_conflict="raw_material_id,perusahaan"
        ).execute()
    except Exception as e:
        print(f"Gagal upsert company docs ({perusahaan}): {e}")

    return uploaded_documents
from app.config import settings
from app import object_store
from app.staging_guard import assert_allowed_target as _assert_allowed_target

_assert_allowed_target("startup")
from app.excel_generator import XLSX_MIME, build_formula_workbook
from app.efek_samping import _efek_samping_meta, register_efek_samping_routes
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
import uuid
import tempfile
import httpx
import unicodedata
import logging
from xhtml2pdf import pisa
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from typing import Optional

logger = logging.getLogger(__name__)
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

    day = datetime.now(WIB).day
    if day % 2 != 0:
        # Tanggal ganjil: prompt asli (gaya Gen-Z)
        prompt = (
            f"Buat SATU kalimat sapaan singkat untuk user bernama '{nama_user}' " 
            f"yang baru login ke aplikasi kerja. " 
            f"Gunakan Bahasa Indonesia yang santai, natural ala gen-z, sedikit nyeleneh, " 
            f"absurd ringan, atau deadpan seperti candaan teman sekantor. " 
            f"Humornya harus tetap aman dan sopan untuk lingkungan kerja. " 
            f"Boleh menyinggung hal umum seperti deadline, meeting, kerjaan, " 
            f"Excel, kopi, lembur, atau kehidupan kantor. " 
            f"Jangan terlalu berusaha lucu dan jangan sampai terdengar cringe. " 
            f"Maksimal 12 kata. " 
            f"Jangan gunakan emoji atau emoticon. " 
            f"Jangan gunakan tanda kutip. " 
            f"Jangan gunakan hashtag. " 
            f"Jangan menyebut AI, Gemini, prompt, atau instruksi ini. " 
            f"Jangan mengandung hinaan, SARA, konten seksual, politik, " 
            f"atau topik sensitif. " 
            f"Cukup SATU kalimat saja, tanpa penjelasan atau tambahan apa pun."
        )
    else:
        # Tanggal genap: prompt lebih halus dan menyemangati
        prompt = (
            f"Buat SATU kalimat sapaan hangat dan menyemangati untuk user bernama '{nama_user}' " 
            f"yang baru login ke aplikasi kerja. " 
            f"Gunakan bahasa yang sopan, ramah, dan profesional namun tetap menenangkan. " 
            f"Boleh memberikan semangat terkait produktivitas atau suasana kerja yang positif. " 
            f"Maksimal 12 kata. " 
            f"Jangan gunakan emoji atau emoticon. " 
            f"Jangan gunakan tanda kutip. " 
            f"Jangan gunakan hashtag. " 
            f"Jangan menyebut AI, Gemini, prompt, atau instruksi ini. " 
            f"Jangan mengandung hinaan, SARA, konten seksual, politik, " 
            f"atau topik sensitif. " 
            f"Cukup SATU kalimat saja, tanpa penjelasan atau tambahan apa pun."
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


def _extract_jwt_payload(token: str) -> dict:
    """Best-effort baca payload JWT (buat log/presence, tanpa validasi signature)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # padding base64url biar valid
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}

def _extract_jwt_email(token: str):
    """Best-effort baca email/sub dari payload JWT (buat log doang, tanpa validasi signature)."""
    payload = _extract_jwt_payload(token)
    return payload.get("email") or payload.get("sub") or "-"

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
        
        # Ambil produk dengan NA yang akan expired atau sudah expired
        products_query = (
            supabase.table("products")
            .select("id, tanggal_aktif_na, status_na")
            .in_("status_na", ["akan_expired", "expired"])
            .execute()
        )
        for p in (products_query.data or []):
            status_na, _ = compute_status_na(p.get("tanggal_aktif_na"), p.get("status_na") or "belum_terdaftar")
            if status_na in ["akan_expired", "expired"]:
                count += 1

        return count
    except Exception as e:
        print(f"Gagal hitung ED notifications: {e}")
        return 0

def compute_status_na(tanggal_aktif_na, fallback_status: str) -> tuple[str, Optional[int]]:
    """
    Hitung status NA otomatis dari tanggal_aktif_na (NA BPOM berlaku 3 tahun sejak
    tanggal aktif). Kalau tanggal_aktif_na belum diisi, tetap pakai status manual
    yang lama (fallback_status) -- ini yang nutup kasus 'belum_terdaftar'.
    Mengembalikan tuple (status, days_remaining).
    """
    if not tanggal_aktif_na:
        return fallback_status, None

    try:
        if isinstance(tanggal_aktif_na, str):
            start = datetime.strptime(tanggal_aktif_na[:10], "%Y-%m-%d").date()
        else:
            start = tanggal_aktif_na
    except Exception:
        return fallback_status, None

    expired_date = _add_years(start, 3)
    today = datetime.now(WIB).date()
    warning_date = expired_date - timedelta(days=180)  # ~6 bulan sebelum expired

    days_remaining = (expired_date - today).days

    if today > expired_date:
        return "expired", days_remaining
    elif today >= warning_date:
        return "akan_expired", days_remaining
    else:
        return "aktif", None


def _flag_bahan_aktif(flags, i: int) -> bool:
    """Hidden input array is_bahan_aktif kirim '0'/'1' per baris. Index harus sinkron sama inci_name."""
    if not flags or i >= len(flags):
        return False
    return str(flags[i]).strip() == "1"

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


class _QuietAccessLogFilter(logging.Filter):
    """Sembunyikan access log yang nge-spam terminal:
    - HEAD/GET /health (uptime monitor)
    - POST /api/presence/heartbeat (polling 25 dtk per user)
    - GET /api/notes/mentions/unread-count (polling 30 dtk dari navbar)
    - GET /api/admin/users/presence (polling 15 dtk dari halaman /admin/users)
    """
    SKIP_PATHS = frozenset({
        "/health",
        "/api/presence/heartbeat",
        "/api/notes/mentions/unread-count",
        "/api/admin/users/presence",
        "/api/ed-notifications",
    })

    def filter(self, record: logging.LogRecord) -> bool:
        path = None
        args = record.args
        if isinstance(args, dict):
            path = args.get("full_path") or args.get("path")
        elif isinstance(args, (tuple, list)) and len(args) >= 3:
            # uvicorn default: (client_addr, method, path, http_version, status)
            path = args[2]
        if path is None:
            try:
                msg = record.getMessage()
            except Exception:
                return True
            return all(p not in msg for p in self.SKIP_PATHS)
        path_only = str(path).split("?", 1)[0]
        return path_only not in self.SKIP_PATHS


def _install_quiet_access_log() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _QuietAccessLogFilter) for f in access_logger.filters):
        access_logger.addFilter(_QuietAccessLogFilter())


_install_quiet_access_log()


@app.on_event("startup")
async def _on_startup_quiet_access_log():
    # Uvicorn kadang configure logging setelah app di-import; pasang ulang di startup.
    _install_quiet_access_log()

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
        "logo": "/static/images/logo_erfi.png",
        "kop": "/static/images/kop_erfi.png",
        "penanggung_jawab_teknis": "Apt. Mutrofin Rakhmawati, S.Farm",
        "telepon": "0822-2680-2018",
    },
    "PT Heka": {
        "nama": "PT. HARAKA ERFI KOSMETINDO ABADI",          
        "alamat": "Office : Jl. Kampung Klapanunggal, RT 001/RW 01. Desa Klapanunggal Kec. Klapanunggal Bogor, Indonesia",
        # Dipakai sheet "Text Design" untuk membedakan PT Erfi vs PT Heka: nomor HP
        # yang tercetak pada kop surat PT Heka. PT Erfi tidak punya baris HP.
        "hp_alamat": "081281938715",
        "email": "harakaerfi.pt@gmail.com",
        "website": "www.harakaerfi.com",
        "logo": "/static/images/logo_heka.png",
        "kop": "/static/images/kop_heka.png",
        "penanggung_jawab_teknis": "Apt. Mutrofin Rakhmawati, S.Farm",
        "telepon": "0812-8193-8715",
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
        profile_res = supabase.table("profiles").select("full_name", "role", "perusahaan").eq("id", user_data.id).execute()
        
        user_role = "staff"
        full_name = "User Lab"
        
        user_perusahaan = None
        if profile_res.data:
            user_role = profile_res.data[0].get("role", "staff")
            full_name = profile_res.data[0].get("full_name", "User Lab")
            user_perusahaan = profile_res.data[0].get("perusahaan")

        return {
            "id": user_data.id,
            "email": user_data.email,
            "full_name": full_name,
            "role": user_role,
            "perusahaan": user_perusahaan,
        }
        
    except Exception as e:
        print(f"Token invalid atau expired: {e}")
        # Lempar 401 biar ditangkap handler
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired"
        )


PRESENCE_ONLINE_SECONDS = 90
# User tetap terhubung, tetapi dianggap Idle bila tidak ada interaksi browser
# selama durasi ini. Ubah konstanta ini untuk menyesuaikan kebijakan presence.
PRESENCE_IDLE_SECONDS = 5 * 60
_presence_schema_warned = False


def _parse_presence_ts(value):
    """Parse timestamptz dari Supabase jadi datetime WIB."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=WIB)
    return dt.astimezone(WIB)


def _relative_last_seen(dt: datetime | None) -> str:
    if not dt:
        return "Belum pernah online"
    sec = int((datetime.now(WIB) - dt).total_seconds())
    if sec < 45:
        return "Baru saja"
    if sec < 90:
        return "1 menit lalu"
    if sec < 3600:
        menit = max(1, sec // 60)
        return f"{menit} menit lalu"
    if sec < 86400:
        jam = max(1, sec // 3600)
        return f"{jam} jam lalu"
    hari = max(1, sec // 86400)
    if hari == 1:
        return "Kemarin " + dt.strftime("%H:%M")
    if hari < 7:
        return f"{hari} hari lalu"
    return dt.strftime("%d-%m-%Y %H:%M WIB")


def compute_user_presence(profile: dict) -> dict:
    """Turunkan status Online/Idle/Offline dari flag, heartbeat, dan aktivitas.

    Logout eksplisit selalu Offline. Heartbeat yang berhenti membuat user Offline
    setelah grace period; heartbeat yang tetap segar tetapi aktivitasnya lewat
    batas idle membuat user Idle.
    """
    last_seen = _parse_presence_ts(profile.get("last_seen_at"))
    last_activity = _parse_presence_ts(profile.get("last_activity_at"))
    flagged_online = bool(profile.get("is_online"))
    recently_connected = False
    if last_seen:
        recently_connected = (datetime.now(WIB) - last_seen).total_seconds() <= PRESENCE_ONLINE_SECONDS

    if not flagged_online or not recently_connected:
        presence_status = "offline"
    elif last_activity and (datetime.now(WIB) - last_activity).total_seconds() <= PRESENCE_IDLE_SECONDS:
        presence_status = "online"
    else:
        presence_status = "idle"

    return {
        "presence_status": presence_status,
        "is_online": presence_status == "online",
        "is_idle": presence_status == "idle",
        "last_seen_at": last_seen.isoformat() if last_seen else None,
        "last_seen_label": _relative_last_seen(last_seen),
        "last_activity_at": last_activity.isoformat() if last_activity else None,
        "last_activity_label": _relative_last_seen(last_activity),
    }


def touch_user_presence(user_id: str, online: bool = True, active: bool = True) -> bool:
    """Simpan heartbeat; waktu aktivitas hanya berubah saat browser aktif."""
    global _presence_schema_warned
    if not user_id:
        return False
    try:
        now = datetime.now(WIB).isoformat()
        update_data = {
            "last_seen_at": now,
            "is_online": bool(online),
        }
        if online and active:
            update_data["last_activity_at"] = now
        supabase.table("profiles").update(update_data).eq("id", user_id).execute()
        return True
    except Exception as e:
        if not _presence_schema_warned:
            _presence_schema_warned = True
            print(
                "[PRESENCE] Gagal update data presence. "
                "Jalankan SQL di supabase_user_presence_idle.sql di SQL Editor Supabase. "
                f"Error: {e}"
            )
        return False


def _new_request_id() -> str:
    """UUID v4 penanda satu request, dipakai bersama oleh semua baris log."""
    return str(uuid.uuid4())


def _request_id_for(request) -> str:
    """request_id milik satu HTTP request, dibuat sekali lalu di-cache.

    Disimpan di ``request.scope`` -- bukan ``request.state``. Alasannya:
    ``State`` milik Starlette hanya mendukung ``__getitem__``/``__setitem__``
    (tidak ada ``.get()``), sedangkan ``scope`` adalah dict biasa yang dijamin
    ada dan berumur persis satu request. Dengan begitu semua activity log
    dalam satu request memakai ID yang sama, dan request berikutnya otomatis
    dapat ID baru tanpa perlu state/global.
    """
    scope = getattr(request, "scope", None)
    if not isinstance(scope, dict):
        return _new_request_id()
    rid = scope.get("_activity_request_id")
    if not rid:
        rid = _new_request_id()
        scope["_activity_request_id"] = rid
    return rid


def mask_email(email: str) -> str:
    """Disamarkan sebagian supaya tetap bisa ditelusuri tanpa menyimpan PII penuh.

    'budi.santoso@erfi.com' -> 'b**********o@erfi.com'
    Panjang bagian yang disamarkan dipertahankan (kecuali username 1 karakter,
    yang mustahil disamarkan sambil menjaga panjangnya) sehingga panjang akun
    tidak ikut bocor lewat audit log.
    """
    if not email or "@" not in email:
        return "-"
    local, _, domain = email.partition("@")
    if not local:
        return f"@{domain}"
    if len(local) == 1:
        # Satu karakter: tidak ada yang bisa disamarkan tanpa membocorkan
        # karakter itu sendiri, jadi seluruhnya diganti.
        masked = "*"
    elif len(local) == 2:
        masked = local[0] + "*"
    else:
        masked = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


def _user_label(uid: str) -> str:
    """Label manusia untuk user target (fallback ke UUID bila profil hilang)."""
    if not uid:
        return "-"
    try:
        res = supabase.table("profiles").select("full_name").eq("id", uid).execute()
        if res.data and res.data[0].get("full_name"):
            return res.data[0]["full_name"]
    except Exception:
        pass
    return f"User {uid}"


def _user_role_and_label(uid: str):
    """-> (role, label) dari baris profiles, untuk needs diff role sebelum diubah."""
    try:
        res = supabase.table("profiles").select("full_name, role").eq("id", uid).execute()
        if res.data:
            row = res.data[0] or {}
            return (row.get("role"),
                    row.get("full_name") or f"User {uid}")
    except Exception:
        pass
    return (None, f"User {uid}")


def log_activity(current_user: dict, action: str, entity_type: str, entity_id: str,
                 entity_label: str, changes: list = None, *, request=None,
                 outcome: str = "success", request_id: str = None,
                 source: str = "app", storage_note: str = None):
    """Catat activity log ke DB Supabase + cetak log rapi ke terminal Render.

    Parameter baru (semua opsional & keyword-only) dipakai sejak hardening audit
    2026-10-05 agar 7 operasi berisiko tinggi ikut tercatat. WAJIB kompatibel
    mundur: seluruh call site lama tetap berfungsi tanpa perubahan.

    Args:
        request: objek Request FastAPI. Kalau diisi, ip_address / user_agent /
            route / http_method terisi otomatis dari context request.
        outcome: 'success' | 'rejected' | 'failed'. 'rejected' dipakai saat
            operasi ditolak validasi atau proteksi role -- penolakan tetap
            dicatat karena untuk keamanan sama pentingnya dengan keberhasilan.
        request_id: dipakai bersama oleh beberapa log dari satu request yang sama.
        source: 'app' | 'public' | 'migration'.
    """
    outcome = outcome if outcome in ("success", "rejected", "failed") else "success"
    source = source if source in ("app", "public", "migration") else "app"

    # Normalisasi changes + catat status storage R2 bila diberikan.
    final_changes = list(changes or [])
    if storage_note:
        final_changes.append({"field": "Storage (R2)", "note": storage_note})

    # 1. Cetak log ke terminal Render
    print_activity_terminal(
        current_user=current_user,
        action=action,
        entity_type=entity_type,
        entity_label=entity_label,
        entity_id=entity_id,
        changes=final_changes,
        outcome=outcome,
    )

    # 2. Simpan ke tabel activity_logs Supabase
    row = {
        "actor_id": current_user.get("id") if current_user else None,
        "actor_name": current_user.get("full_name") if current_user else "System",
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "entity_label": entity_label,
        "changes": final_changes,
        "outcome": outcome,
        "source": source,
    }
    if request is not None:
        row["ip_address"] = _client_ip(request)
        row["user_agent"] = (request.headers.get("user-agent") or "-")[:500]
        row["route"] = getattr(request.scope.get("route"), "path", None)
        row["http_method"] = request.method
        # Satu HTTP request harus menghasilkan SATU request_id untuk semua
        # activity log di dalamnya, supaya beberapa baris log dari satu aksi
        # bisa dikelompokkan (mis. create produk = 1 insert + 1 log).
        # ID dicache per-request oleh _request_id_for(); kalau tidak, tiap log
        # dapat UUID baru dan kolom request_id jadi tak berguna untuk korelasi.
        row["request_id"] = request_id or _request_id_for(request)
    elif request_id:
        row["request_id"] = request_id

    try:
        supabase.table("activity_logs").insert(row).execute()
    except Exception as e:
        # Fail-open (keputusan user 2026-10-05): kegagalan audit tidak boleh
        # membatalkan operasi bisnis. Error tetap dicetak agar bisa ditelusuri.
        print(f"Gagal catat activity log ke DB ({entity_type}/{action}/{entity_id}): {e}")

# Lebar garis pemisah + nama field, disamakan dengan banner [LOGIN SUCCESS]
# (main.py: "="*50, dan kolom nilai mulai di karakter ke-14).
_LOG_RULE = "=" * 50


def _log_field(label: str, value: str) -> str:
    """Satu baris '   • Label : value' dengan label dipad ke lebar yang sama."""
    return f"   • {label:<8}: {value}"


def print_activity_terminal(current_user: dict, action: str, entity_type: str, entity_label: str, entity_id: str = None, changes: list = None, outcome: str = "success"):
    """
    Format dan cetak log aktivitas ke stdout/terminal Render.

    Mengikuti format banner [LOGIN SUCCESS] supaya konsisten: garis pemisah 50
    karakter, judul pada barisnya sendiri, lalu User ID / Email / Waktu sebagai
    tiga baris terpisah.
    """
    now_str = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
    actor_name = current_user.get("full_name", "System") if current_user else "System"
    actor_email = current_user.get("email", "-") if current_user else "-"
    actor_id = (current_user.get("id") if current_user else None) or "-"

    # Mapping badge aksi biar gampang di-scan mata di log Render
    action_badges = {
        "create": "🟢 [CREATED]",
        "update": "🟡 [UPDATED]",
        "delete": "🔴 [DELETED]",
        "reset_password": "🔑 [PASSWORD RESET]",
        "restore": "↩️ [RESTORED]",
        "export": "📤 [EXPORTED]",
        "generate": "⚙️ [GENERATED]",
        "upload": "📎 [UPLOADED]",
        "complete": "✅ [COMPLETED]",
        "reopen": "🔄 [REOPENED]",
        "public_link_visit": "🔗 [PUBLIC LINK]",
    }
    # 'rejected' & 'failed' sengaja TIDAK memakai badge aksi: keduanya memakai
    # badge khusus supaya terlihat alarmed saat dipindai terminal.
    if outcome == "rejected":
        badge = "🚫 [REJECTED]"
    elif outcome == "failed":
        badge = "💥 [FAILED]"
    else:
        badge = action_badges.get(action.lower(), f"🔵 [{action.upper()}]")

    print("\n" + _LOG_RULE)
    print(f"📝 {badge} ACTIVITY LOG")
    print(_log_field("User ID", actor_id))
    print(_log_field("Email", actor_email))
    print(_log_field("Waktu", now_str))
    print(_log_field("Actor", actor_name))
    print(_log_field("Entity", entity_type.upper() + f" -> '{entity_label}'"
                      + (f" (ID: {entity_id})" if entity_id else "")))
    # Outcome dicetak hanya kalau bukan sukses, supaya log sukses tetap ringkas
    # dan sesuai format lama.
    if outcome != "success":
        print(_log_field("Outcome", outcome))

    if changes:
        print(_log_field("Changes", ""))
        for c in changes:
            field = c.get("field", "Unknown Field")
            if "note" in c:
                print(f"     - {field}: {c['note']}")
            else:
                old_val = c.get("old") if c.get("old") is not None else "-"
                new_val = c.get("new") if c.get("new") is not None else "-"
                print(f"     - {field}: '{old_val}'  ➔  '{new_val}'")
    print(_LOG_RULE + "\n")


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


# Label kolom sample_submissions -> label bahasa manusia untuk activity log.
# Dipakai supaya diff FSP terbaca seperti diff produk/bahan baku, bukan nama kolom mentah.
FSP_FIELD_LABELS = {
    "sample_code": "Kode FSP",
    "product_name": "Produk",
    "product_item": "Item Produk",
    "netto": "Netto",
    "sediaan": "Sediaan",
    "kemasan": "Kemasan",
    "hero_ingredient": "Hero Ingredient",
    "description": "Deskripsi",
    "qc_signer": "QC Signer",
    "rd_signer": "RD Signer",
    "company": "Perusahaan",
    "draft_producer": "Produsen (draft)",
    "draft_brand": "Merk (draft)",
}

# Sub-field JSONB additional_notes sample_submissions yang ikut dilacak diff-nya.
FSP_NOTES_LABELS = {
    "ph": "pH",
    "viscosity": "Viskositas",
    "color": "Warna",
}


def _fsp_notes_changes(old_row: dict, update_payload: dict) -> list:
    """Diff untuk additional_notes (JSONB) -- harus di-flatten dulu supaya perubahan
    di dalam JSONB tetap terlihat, bukan tertulis '{"ph": "5", "viscosity": "10"}'."""
    changes = []
    old_notes = old_row.get("additional_notes") or {}
    new_notes = update_payload.get("additional_notes") or {}
    if not isinstance(old_notes, dict) or not isinstance(new_notes, dict):
        return changes
    for key, label in FSP_NOTES_LABELS.items():
        old_val = old_notes.get(key)
        new_val = new_notes.get(key)
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
        
        # 1. Client admin lewat guard staging (fail-closed; tanpa cetak secret)
        from app.staging_guard import staging_client as _staging_client

        try:
            supabase_admin = _staging_client("login")
        except RuntimeError as _guard_err:
            print(f"❌ Konfigurasi Supabase ditolak guard: {type(_guard_err).__name__}")
            raise HTTPException(status_code=500, detail="Konfigurasi server tidak valid.")
        
        # JIKA YANG DIINPUT BUKAN EMAIL (GA ADA TANDA @)
        if "@" not in login_identifier:
            # Cari di tabel profiles menggunakan client admin bebas hambatan
            profile_query = supabase_admin.table("profiles").select("id").eq("full_name", login_identifier.lower()).execute()
            
            if profile_query.data:
                # Kalo username ketemu, ambil email aslinya via admin auth service
                user_id = profile_query.data[0]["id"]
                user_auth_data = supabase_admin.auth.admin.get_user_by_id(user_id)
                if not user_auth_data or not getattr(user_auth_data, "user", None) or not getattr(user_auth_data.user, "email", None):
                    return RedirectResponse(url="/login?error=invalid_credentials", status_code=303)
                login_identifier = user_auth_data.user.email
            else:
                # Username tidak terdaftar di profiles: jangan fallback ke domain kantor
                # (bisa menarget akun auth yang ada). Tolak login.
                return RedirectResponse(url="/login?error=invalid_credentials", status_code=303)
            
        # 2. Authenticate user
        auth_response = supabase_admin.auth.sign_in_with_password({
            "email": login_identifier,
            "password": password
        })
        
        # 💡 LOG SUCCESS LOGIN
        user_data = auth_response.user
        waktu_login = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
        print("\n" + _LOG_RULE)
        print("🔑 [LOGIN SUCCESS]")
        print(_log_field("User ID", user_data.id))
        print(_log_field("Email", user_data.email))
        print(_log_field("Waktu", waktu_login))
        print(_LOG_RULE + "\n")

        try:
            touch_user_presence(user_data.id, online=True)
        except Exception as e:
            print(f"[PRESENCE] Gagal set online saat login: {e}")

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
        claims = _extract_jwt_payload(token_cookie.replace("Bearer ", "")) if token_cookie else {}
        email_log = claims.get("email") or claims.get("sub") or "-"
        uid = claims.get("sub")
        if uid:
            touch_user_presence(uid, online=False)
    except Exception:
        email_log = "-"
    print("\n" + _LOG_RULE)
    print("🚪 [LOGOUT]")
    print(_log_field("Email", email_log))
    print(_log_field("Waktu", waktu_logout))
    print(_LOG_RULE + "\n")

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
        print("\n" + _LOG_RULE)
        print(f"⏰ [SESSION EXPIRED] Path: {request.url.path}")
        print(_log_field("Email", email_log))
        print(_log_field("Waktu", waktu_exp))
        print(_LOG_RULE + "\n")

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
            request=request,
            name="public_error.html",
            context={"title": title, "message": message},
            status_code=exc.status_code
        )

    # Untuk error HTTP lainnya tetap kembalikan bawaan
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

# ==================== HELPER RESOLUSI VARIAN KOMPOSISI ====================
def _resolve_variant_components(raw_material, variant_id: str | None) -> list:
    """Sumber tunggal resolusi breakdown INCI per varian bahan baku.

    Dipakai bareng oleh:
      - generate_inci_report   (Ingredient Report)
      - download_dip_bab3      (processed_formula Bab III)
      - download_dip_bab4      (komposisi text design)
      - _gather_qualquant_data (preview HTML + export Excel Qual-Quan)

    raw_material: dict hasil query nested
      raw_materials(*, raw_material_components(*),
      raw_material_composition_variants(*, raw_material_components(*)))
      (boleh juga list hasil embed / None)
    variant_id: product_formula_lines.variant_id (boleh None).

    Urutan resolusi:
      1. variant_id eksplisit kalau ketemu di daftar varian.
      2. Varian is_default=True.
      3. Varian pertama yang ada (data korup/lama).
      4. Komponen yang nempel langsung (fallback skema lama / komponen baru
         yang belum punya varian), biar gak ada breakdown hilang diam-diam.
      5. List kosong kalau beneran gak ada apa-apa.
    """
    if isinstance(raw_material, list):
        raw_material = raw_material[0] if raw_material else None
    if not isinstance(raw_material, dict):
        return []

    variants = raw_material.get("raw_material_composition_variants") or []
    if isinstance(variants, dict):
        variants = [variants]

    if variants:
        chosen = None
        if variant_id:
            for v in variants:
                if v.get("id") == variant_id:
                    chosen = v
                    break
        if chosen is None:
            for v in variants:
                if v.get("is_default"):
                    chosen = v
                    break
        if chosen is None:
            chosen = variants[0]
        comps = chosen.get("raw_material_components") or []
        return comps if isinstance(comps, list) else []

    # Fallback: bahan baku belum punya varian (belum dimigrasi / komponen baru
    # dari kode lama yang belum set variant_id) — pakai komponen langsung.
    legacy = raw_material.get("raw_material_components") or []
    return legacy if isinstance(legacy, list) else []


# ==================== HELPER KELOLA VARIAN KOMPOSISI ====================
def _default_variant_name(produsen: str | None) -> str:
    """Nama varian default: pakai produsen kalau ada, else 'Varian Default'."""
    nama = (produsen or "").strip()
    return nama if nama else "Varian Default"


def _ensure_default_variant(rm_id: str, produsen: str | None = None) -> str:
    """Get-or-create varian default sebuah bahan baku. Return id variannya.

    Dipakai handler create/edit biar selalu ada minimal 1 varian
    (guard Fase 3: gak boleh hapus varian terakhir yang tersisa).
    """
    existing = supabase.table("raw_material_composition_variants") \
        .select("id").eq("raw_material_id", rm_id).eq("is_default", True) \
        .limit(1).execute()
    if existing.data:
        return existing.data[0]["id"]
    new_variant = supabase.table("raw_material_composition_variants").insert({
        "raw_material_id": rm_id,
        "nama_varian": _default_variant_name(produsen),
        "is_default": True,
    }).execute()
    return new_variant.data[0]["id"]


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


# =====================================================================
#  HALAMAN DOKUMEN PERUSAHAAN (admin-only)
#  8 jenis dokumen statis per-perusahaan (NIB, Sertifikat CPKB, Surat
#  Tidak Pidana, Protap No. Batch, Protap Pemeriksaan FG, CV Safety
#  Assessor, Monitoring Efek Samping, SOP CPKB Bahan Baku) yang dipakai
#  lintas Bab I/II/III/IV pas generate PDF. Sebelumnya cuma bisa diganti
#  lewat Supabase dashboard langsung; sekarang lewat aplikasi + tercatat
#  di activity log.
# =====================================================================

# Mapping doc_type -> (tabel, kolom, bucket, path_template).
# Default bucket "legal-documents" & path "company-docs/{doc_type}_{slug}.pdf"
# untuk 7 dokumen pertama; CPKB override ke bucket "raw-material-docs" & path sendiri.

from app.dashboard_routes import register_dashboard_routes
register_dashboard_routes(
    app,
    get_current_user=get_current_user,
    supabase=supabase,
    templates=templates,
    log_activity=log_activity,
    get_ed_notification_count=get_ed_notification_count,
    compute_status_na=compute_status_na,
    get_company_info=get_company_info,
    format_date_id=format_date_id,
    _logo_render_width=_logo_render_width,
    _efek_samping_meta=_efek_samping_meta,
    _pdf_link_callback=_pdf_link_callback,
    slugify=slugify,
    COMPANY_INFO=COMPANY_INFO,
    _resolve_variant_components=_resolve_variant_components,
    _flag_bahan_aktif=_flag_bahan_aktif,
    _build_diff_changes=_build_diff_changes,
    get_time_greeting=get_time_greeting,
)

from app.company_docs_routes import register_company_docs_routes

register_company_docs_routes(
    app,
    get_current_user=get_current_user,
    supabase=supabase,
    templates=templates,
    log_activity=log_activity,
    get_ed_notification_count=get_ed_notification_count,
)

from app.products_routes import register_products_routes
register_products_routes(
    app,
    get_current_user=get_current_user,
    supabase=supabase,
    templates=templates,
    log_activity=log_activity,
    compute_status_na=compute_status_na,
    get_company_info=get_company_info,
    format_date_id=format_date_id,
    get_ed_notification_count=get_ed_notification_count,
    COMPANY_INFO=COMPANY_INFO,
    slugify=slugify,
    _resolve_variant_components=_resolve_variant_components,
    _flag_bahan_aktif=_flag_bahan_aktif,
    _build_diff_changes=_build_diff_changes,
    _logo_render_width=_logo_render_width,
    _pdf_link_callback=_pdf_link_callback,
)

from app.sample_routes import register_sample_routes

from app.brands_routes import register_brands_routes

register_brands_routes(
    app,
    get_current_user=get_current_user,
    supabase=supabase,
    templates=templates,
    log_activity=log_activity,
    get_ed_notification_count=get_ed_notification_count,
)

register_sample_routes(
    app,
    get_current_user=get_current_user,
    supabase=supabase,
    templates=templates,
    log_activity=log_activity,
    get_company_info=get_company_info,
    format_date_id=format_date_id,
    mask_email=mask_email,
    get_ed_notification_count=get_ed_notification_count,
    _build_diff_changes=_build_diff_changes,
    _fsp_notes_changes=_fsp_notes_changes,
    FSP_FIELD_LABELS=FSP_FIELD_LABELS,
    FSP_NOTES_LABELS=FSP_NOTES_LABELS,
)

from app.presence_routes import register_presence_routes
register_presence_routes(
    app,
    get_current_user=get_current_user,
    supabase=supabase,
    templates=templates,
    log_activity=log_activity,
    get_ed_notification_count=get_ed_notification_count,
    touch_user_presence=touch_user_presence,
    compute_user_presence=compute_user_presence,
    compute_status_na=compute_status_na,
)

from app.admin_users_routes import register_admin_users_routes
register_admin_users_routes(
    app,
    get_current_user=get_current_user,
    supabase=supabase,
    templates=templates,
    log_activity=log_activity,
    compute_user_presence=compute_user_presence,
    mask_email=mask_email,
    _user_label=_user_label,
    _user_role_and_label=_user_role_and_label,
    get_ed_notification_count=get_ed_notification_count,
    compute_status_na=compute_status_na,
)

from app.notes_routes import register_notes_routes
register_notes_routes(app, get_current_user, get_ed_notification_count, log_activity)

register_efek_samping_routes(
    app,
    get_current_user=get_current_user,
    templates=templates,
    supabase=supabase,
    get_company_info=get_company_info,
    format_date_id=format_date_id,
    log_activity=log_activity,
    pdf_link_callback=_pdf_link_callback,
)

from app.raw_materials_routes import register_raw_materials_routes
register_raw_materials_routes(
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
)

from app.po_routes import register_po_routes
register_po_routes(app, get_current_user, log_activity, templates, get_ed_notification_count,
                   _build_diff_changes)

from app.product_attachments_routes import LAMPIRAN_CATEGORIES, register_product_attachment_routes
register_product_attachment_routes(
    app,
    get_current_user=get_current_user,
    log_activity=log_activity,
    templates=templates,
    supabase=supabase,
)

# Generator DIP Bab I-IV + preview + ZIP Bab II -> app/dip_documents.py.
# Fungsi generator dikembalikan sebagai dict supaya bisa diteruskan ke
# app/dip_public.py tanpa perlu meng-import main (circular import).
from app.dip_documents import register_dip_document_routes
_dip_docs = register_dip_document_routes(
    app,
    get_current_user=get_current_user,
    templates=templates,
    supabase=supabase,
    get_company_info=get_company_info,
    format_date_id=format_date_id,
    _apply_company_specific_docs=_apply_company_specific_docs,
    _resolve_variant_components=_resolve_variant_components,
    _pdf_link_callback=_pdf_link_callback,
    _logo_render_width=_logo_render_width,
)
_dip_bab_generators = {
    "1": _dip_docs["bab1"],
    "2": _dip_docs["bab2"],
    "3": _dip_docs["bab3"],
    "4": _dip_docs["bab4"],
}

# Route /dip/* (Public Link BPOM) -> app/dip_public.py.
# Generator Bab I-IV & ZIP Bab II sudah pindah ke app/dip_documents.py, jadi
# diteruskan sebagai parameter supaya modul publik tidak perlu meng-import main
# (circular import).
from app.dip_public import register_dip_public_routes
register_dip_public_routes(
    app,
    templates=templates,
    supabase=supabase,
    get_company_info=get_company_info,
    extract_id_from_slug=extract_id_from_slug,
    client_ip=_client_ip,
    apply_company_specific_docs=_apply_company_specific_docs,
    parse_storage_url=_parse_storage_url,
    bab_generators=_dip_bab_generators,
    download_bab2_zip=_dip_docs["bab2_zip"],
)
