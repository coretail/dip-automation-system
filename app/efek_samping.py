"""Generate otomatis laporan monitoring efek samping (cosmetovigilance) per produk."""
from __future__ import annotations

import asyncio
import io
import os
import re
from datetime import date, datetime
from typing import List
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, Form
from fastapi.responses import RedirectResponse
from pypdf import PdfReader, PdfWriter
from xhtml2pdf import pisa

_EFEK_PERIOD_RE = re.compile(r"^(\d{4})-H([12])$")
APT_SIGNATURE_URI = "/static/images/apt.png"
WIB = ZoneInfo("Asia/Jakarta")

_BULAN_ID = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
    9: "September", 10: "Oktober", 11: "November", 12: "Desember",
}


def _format_sign_date_id(value: date) -> str:
    """Tanggal TTD gaya referensi: '03 Januari 2026' (hari 2 digit)."""
    try:
        return f"{value.day:02d} {_BULAN_ID[value.month]} {value.year}"
    except Exception:
        return str(value)

# Kunci per-produk untuk mencegah race condition (lost update) saat dua
# request generate bersamaan untuk produk yang sama.
_generate_locks: dict[str, asyncio.Lock] = {}
_generate_locks_guard = asyncio.Lock()


def _current_efek_semester(now: datetime | None = None) -> tuple[int, int]:
    now = now or datetime.now(WIB)
    half = 1 if now.month <= 6 else 2
    return now.year, half


def _format_efek_period(year: int, half: int) -> str:
    return f"{year}-H{half}"


def _parse_efek_period(text) -> tuple[int, int] | None:
    if not text:
        return None
    m = _EFEK_PERIOD_RE.match(str(text).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _next_efek_semester(last_text) -> tuple[int, int]:
    parsed = _parse_efek_period(last_text)
    if not parsed:
        return _current_efek_semester()
    year, half = parsed
    if half == 1:
        return year, 2
    return year + 1, 1


def _efek_period_label(year: int, half: int) -> str:
    if half == 1:
        return f"Januari - Juni {year}"
    return f"Juli - Desember {year}"


def _efek_period_range(year: int, half: int) -> tuple[date, date]:
    if half == 1:
        return date(year, 1, 1), date(year, 6, 30)
    return date(year, 7, 1), date(year, 12, 31)


def _efek_signature_date(year: int, half: int) -> date:
    if half == 1:
        return date(year, 7, 3)
    return date(year + 1, 1, 3)

def _slugify(text: str) -> str:
    text = (text or "produk").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "produk"


def _apt_signature_uri() -> str | None:
    local = os.path.join("app", "static", "images", "apt.png")
    if not os.path.isfile(local):
        return None
    try:
        import base64
        with open(local, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/png;base64,{data}"
    except Exception as e:
        print(f"[EFEK SAMPING] Gagal encode TTD apt.png: {e}")
        return APT_SIGNATURE_URI


def _efek_samping_meta(product: dict) -> dict:
    last = product.get("last_efek_samping_period") if product else None
    last_parsed = _parse_efek_period(last)
    ny, nh = _next_efek_semester(last)
    return {
        "last": last,
        "last_label": _efek_period_label(*last_parsed) if last_parsed else None,
        "next": _format_efek_period(ny, nh),
        "next_label": _efek_period_label(ny, nh),
    }


def _collect_efek_kasus_rows(
    kasus_nama,
    kasus_jenis_kelamin,
    kasus_usia,
    kasus_jenis_efek,
    kasus_manifestasi,
    kasus_tanggal,
    format_date_id,
) -> list[dict]:
    names = kasus_nama or []
    genders = kasus_jenis_kelamin or []
    ages = kasus_usia or []
    effects = kasus_jenis_efek or []
    manifests = kasus_manifestasi or []
    dates = kasus_tanggal or []
    n = max(len(names), len(genders), len(ages), len(effects), len(manifests), len(dates), 0)
    rows = []
    for i in range(n):
        def _at(seq, idx):
            if idx >= len(seq) or seq[idx] is None:
                return ""
            return str(seq[idx]).strip()
        nama = _at(names, i)
        gender = _at(genders, i)
        usia = _at(ages, i)
        jenis = _at(effects, i)
        manif = _at(manifests, i)
        tgl = _at(dates, i)
        if not any((nama, gender, usia, jenis, manif, tgl)):
            continue
        if tgl:
            tgl = format_date_id(tgl)
        rows.append({
            "nama": nama or "-",
            "jenis_kelamin": gender or "-",
            "usia": usia or "-",
            "jenis_efek": jenis or "-",
            "manifestasi": manif or "-",
            "tanggal_mulai": tgl or "-",
        })
    return rows


def register_efek_samping_routes(
    app,
    *,
    get_current_user,
    templates,
    supabase,
    get_company_info,
    format_date_id,
    log_activity,
    pdf_link_callback,
):
    @app.post("/products/{product_id}/monitoring-efek-samping/generate")
    async def generate_monitoring_efek_samping(
        product_id: str,
        ada_kasus: str = Form("0"),
        kasus_nama: List[str] = Form(None),
        kasus_jenis_kelamin: List[str] = Form(None),
        kasus_usia: List[str] = Form(None),
        kasus_jenis_efek: List[str] = Form(None),
        kasus_manifestasi: List[str] = Form(None),
        kasus_tanggal: List[str] = Form(None),
        current_user: dict = Depends(get_current_user),
    ):
        # Serialize request generate per produk: read-modify-write PDF lama
        # + upload + update DB jadi atomik, tidak ada hasil yang tertimpa.
        async with _generate_locks_guard:
            lock = _generate_locks.setdefault(product_id, asyncio.Lock())
        async with lock:
            return await _generate_monitoring_efek_samping_inner(
                product_id,
                ada_kasus,
                kasus_nama,
                kasus_jenis_kelamin,
                kasus_usia,
                kasus_jenis_efek,
                kasus_manifestasi,
                kasus_tanggal,
                current_user,
            )

    async def _generate_monitoring_efek_samping_inner(
        product_id: str,
        ada_kasus: str,
        kasus_nama: List[str] | None,
        kasus_jenis_kelamin: List[str] | None,
        kasus_usia: List[str] | None,
        kasus_jenis_efek: List[str] | None,
        kasus_manifestasi: List[str] | None,
        kasus_tanggal: List[str] | None,
        current_user: dict,
    ):
        def _redirect(msg: str, error: bool = False):
            response = RedirectResponse(
                url=f"/products/{product_id}/edit?tab=bab4", status_code=303
            )
            response.set_cookie("error_msg" if error else "success_msg", msg)
            return response

        try:
            prod_resp = (
                supabase.table("products")
                .select("*")
                .eq("id", product_id)
                .eq("is_deleted", False)
                .single()
                .execute()
            )
        except Exception as e:
            print(f"[EFEK SAMPING] Produk {product_id} tidak ditemukan: {e}")
            return RedirectResponse(url="/", status_code=303)

        if not prod_resp.data:
            return RedirectResponse(url="/", status_code=303)

        product = prod_resp.data
        year, half = _next_efek_semester(product.get("last_efek_samping_period"))
        period_key = _format_efek_period(year, half)
        period_label = _efek_period_label(year, half)
        start_d, end_d = _efek_period_range(year, half)
        sign_d = _efek_signature_date(year, half)
        sign_label = _format_sign_date_id(sign_d)

        company = get_company_info(product.get("perusahaan"))

        has_cases = str(ada_kasus).strip().lower() in ("1", "true", "on", "yes")
        cases = (
            _collect_efek_kasus_rows(
                kasus_nama,
                kasus_jenis_kelamin,
                kasus_usia,
                kasus_jenis_efek,
                kasus_manifestasi,
                kasus_tanggal,
                format_date_id,
            )
            if has_cases
            else []
        )
        if has_cases and not cases:
            return _redirect("Centang 'ada kasus' tapi detail kasus masih kosong.", error=True)

        html = templates.env.get_template("monitoring_efek_samping_block.html").render({
            "product": product,
            "company": company,
            "period_label": period_label,
            "period_start": format_date_id(start_d),
            "period_end": format_date_id(end_d),
            "cases": cases,
            "signature_place": "Bogor",
            "signature_date": sign_label,
            "apt_signature_uri": _apt_signature_uri(),
        })

        dest = io.BytesIO()
        pdf_status = pisa.CreatePDF(
            src=io.BytesIO(html.encode("UTF-8")),
            dest=dest,
            link_callback=pdf_link_callback,
        )
        if pdf_status.err:
            print(f"[EFEK SAMPING] pisa error: {pdf_status.err}")
            return _redirect("Gagal merender PDF laporan efek samping.", error=True)
        new_pdf = dest.getvalue()

        merged = io.BytesIO()
        writer = PdfWriter()
        existing_url = product.get("monitoring_efek_samping_file_url")
        if existing_url:
            try:
                async with httpx.AsyncClient() as client:
                    res = await client.get(existing_url, timeout=30.0)
                if res.status_code == 200 and res.content[:4] == b"%PDF":
                    old_reader = PdfReader(io.BytesIO(res.content))
                    for page in old_reader.pages:
                        writer.add_page(page)
                else:
                    print(
                        f"[EFEK SAMPING] PDF lama tidak terbaca (status {res.status_code}), generate blok baru saja."
                    )
            except Exception as e:
                print(f"[EFEK SAMPING] Gagal unduh PDF lama, lanjut blok baru: {e}")
        try:
            new_reader = PdfReader(io.BytesIO(new_pdf))
            for page in new_reader.pages:
                writer.add_page(page)
            writer.write(merged)
        except Exception as e:
            print(f"[EFEK SAMPING] Gagal merge PDF: {e}")
            return _redirect("Gagal menggabungkan PDF laporan.", error=True)

        path = f"products/{product_id}/monitoring_efek_samping_{_slugify(product.get('nama_produk'))}.pdf"
        try:
            supabase.storage.from_("raw-material-docs").upload(
                path=path,
                file=merged.getvalue(),
                file_options={"content-type": "application/pdf", "upsert": "true"},
            )
            file_url = supabase.storage.from_("raw-material-docs").get_public_url(path)
        except Exception as e:
            print(f"[EFEK SAMPING] Gagal upload PDF: {e}")
            return _redirect("Gagal mengunggah PDF laporan ke storage.", error=True)

        update_payload = {
            "monitoring_efek_samping_file_url": file_url,
            "last_efek_samping_period": period_key,
        }
        try:
            supabase.table("products").update(update_payload).eq("id", product_id).execute()
        except Exception as e:
            print(f"[EFEK SAMPING] Update period gagal, coba URL saja: {e}")
            try:
                supabase.table("products").update({
                    "monitoring_efek_samping_file_url": file_url,
                }).eq("id", product_id).execute()
                return _redirect(
                    f"PDF {period_label} tersimpan, tapi kolom last_efek_samping_period belum ada di Supabase. Tambah kolom text itu di tabel products.",
                    error=True,
                )
            except Exception as e2:
                print(f"[EFEK SAMPING] Update URL juga gagal: {e2}")
                return _redirect("PDF terbuat tapi gagal menyimpan URL ke produk.", error=True)

        log_activity(
            current_user,
            "generate",
            "product",
            product_id,
            product.get("nama_produk") or product_id,
            [{"field": "Laporan Monitoring Efek Samping", "note": period_label}],
        )
        return _redirect(f"Laporan monitoring efek samping {period_label} berhasil digenerate.")

    @app.post("/products/{product_id}/monitoring-efek-samping/delete")
    async def delete_monitoring_efek_samping(
        product_id: str,
        current_user: dict = Depends(get_current_user),
    ):
        def _redirect(msg: str, error: bool = False):
            response = RedirectResponse(
                url=f"/products/{product_id}/edit?tab=bab4", status_code=303
            )
            response.set_cookie("error_msg" if error else "success_msg", msg)
            return response

        try:
            prod_resp = (
                supabase.table("products")
                .select("nama_produk, monitoring_efek_samping_file_url")
                .eq("id", product_id)
                .single()
                .execute()
            )
        except Exception as e:
            print(f"[EFEK SAMPING] Produk {product_id} tidak ditemukan: {e}")
            return _redirect("Produk tidak ditemukan.", error=True)

        product = prod_resp.data
        if not product:
            return _redirect("Produk tidak ditemukan.", error=True)

        file_url = product.get("monitoring_efek_samping_file_url")
        if file_url:
            try:
                # Ekstrak path dari URL lalu VALIDASI kepemilikan: path harus
                # berada di dalam folder produk ini. Mencegah penghapusan file
                # arbitrer (path traversal) jika kolom DB berisi URL tak terduga.
                # Struktur URL:
                # https://.../storage/v1/object/public/raw-material-docs/products/{id}/...
                marker = "/raw-material-docs/"
                if marker not in file_url:
                    raise ValueError("URL tidak mengandung bucket raw-material-docs")
                path = file_url.split(marker, 1)[1]
                if not path.startswith(f"products/{product_id}/"):
                    raise ValueError(f"Path {path!r} bukan milik produk {product_id}")
                supabase.storage.from_("raw-material-docs").remove([path])
            except ValueError as e:
                # Path tidak valid: jangan hapus apa pun, tetap lanjut reset DB.
                print(f"[EFEK SAMPING] URL file mencurigakan, tidak dihapus: {e}")
            except Exception as e:
                print(f"[EFEK SAMPING] Gagal hapus file {file_url}: {e}")

        try:
            supabase.table("products").update({
                "monitoring_efek_samping_file_url": None,
                "last_efek_samping_period": None,
            }).eq("id", product_id).execute()
        except Exception as e:
            print(f"[EFEK SAMPING] Gagal reset data produk: {e}")
            return _redirect("Gagal mereset data produk.", error=True)

        log_activity(
            current_user,
            "delete",
            "product",
            product_id,
            product.get("nama_produk") or product_id,
            [{"field": "Laporan Monitoring Efek Samping", "note": "Deleted"}],
        )
        return _redirect("Laporan monitoring efek samping berhasil dihapus.")
