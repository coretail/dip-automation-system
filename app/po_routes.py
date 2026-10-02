"""Live-input PO/batch produksi untuk tim QC."""
from __future__ import annotations
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from app.database import supabase
WIB = ZoneInfo("Asia/Jakarta")

# Label field item PO untuk activity log (dipakai _build_diff_changes),
# supaya pesan perubahan terbaca berbahasa manusia, bukan nama kolom mentah.
PO_ITEM_FIELD_LABELS = {
    "product_id": "Produk",
    "product_batch_id": "Batch",
    "tanggal_catatan_batch": "Tgl Catatan Batch",
    "wip": "WIP",
    "netto": "Netto",
    "qty_kg": "Qty (kg)",
    "keterangan": "Keterangan",
    "qty_belum_sop": "Qty Belum SOP",
    "qty_po_kg": "Qty PO (kg)",
    "status_bpom": "Status BPOM",
    "catatan_produksi": "Catatan Produksi",
    "revisi_produksi": "Revisi Produksi",
    "temporary_reject": "Temporary Reject",
}

def _sanitize_ilike(q: str) -> str:
    return re.sub(r"[%_,()\"'\\]", " ", q or "").strip()[:80]

def _clean_text(v, max_len: int = 500):
    if v is None:
        return None
    s = " ".join(str(v).split()).strip()
    if not s:
        return None
    return s[:max_len]

def _parse_opt_float(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return "INVALID"

def _parse_opt_date(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        datetime.strptime(s[:10], "%Y-%m-%d")
        return s[:10]
    except ValueError:
        return "INVALID"

# ---------------------------------------------------------------------------
# Filter tahun & kuartal untuk halaman /purchase-orders
#
# PO disimpan per tanggal_po (ISO "YYYY-MM-DD"), jadi tahun/kuartal idealnya
# difilter di database lewat rentang [start, end) — bukan dengan menyaring
# 100 PO terbaru di Python (itu membuat Q1/Q2 tidak akurat).
# ---------------------------------------------------------------------------
PO_FILTER_COOKIE = "po_filter"
PO_ALL_YEARS = "all"
_PO_YEAR_MIN, _PO_YEAR_MAX = 2000, 2100
_PO_LIST_LIMIT = 100
# Batas baris untuk menghitung daftar tahun + jumlah per kuartal. Hanya satu
# kolom (tanggal_po) jadi murah; kalau tabel lewat batas ini, dropdown tahun
# bisa saja tidak menampilkan tahun yang paling lama.
_PO_STATS_LIMIT = 5000


def _clean_tahun(v):
    """'2026' -> 2026. Nilai lain (termasuk None/kosong) -> None."""
    s = str(v or "").strip()
    if len(s) == 4 and s.isdigit() and _PO_YEAR_MIN <= int(s) <= _PO_YEAR_MAX:
        return int(s)
    return None


def _clean_qtr(v):
    """'1'..'4' -> int. Nilai lain -> None."""
    s = str(v or "").strip()
    return int(s) if s in ("1", "2", "3", "4") else None


def _quarter_bounds(tahun, qtr):
    """Rentang [start, end) tanggal_po. None = tanpa batas tahun."""
    if tahun is None:
        return None
    if not qtr:
        return f"{tahun:04d}-01-01", f"{tahun + 1:04d}-01-01"
    m0 = (qtr - 1) * 3 + 1
    start = f"{tahun:04d}-{m0:02d}-01"
    end = f"{tahun + 1:04d}-01-01" if m0 + 3 > 12 else f"{tahun:04d}-{m0 + 3:02d}-01"
    return start, end


def _in_po_range(d, tahun, qtr):
    """Versi Python dari _quarter_bounds untuk data yang sudah di-fetch.

    Dipakai sebagai jaring pengaman: kalau filter rentang di DB gagal (atau
    tidak dipakai di salah satu cabang query), hasil akhir tetap benar.
    """
    b = _quarter_bounds(tahun, qtr)
    if not b or not d:
        return True
    s = str(d)[:10]
    return b[0] <= s < b[1]


def _apply_po_range(query, tahun, qtr, col="tanggal_po"):
    """Tambahkan filter rentang tanggal_po ke query builder Supabase."""
    b = _quarter_bounds(tahun, qtr)
    if not b:
        return query
    return query.gte(col, b[0]).lt(col, b[1])

def _redirect_po(po_id=None, ok=None, err=None):
    base = "/purchase-orders"
    if po_id:
        base += f"?po_id={po_id}"
    sep = "&" if "?" in base else "?"
    if ok:
        base += f"{sep}success={ok}"
    elif err:
        base += f"{sep}error={err}"
    resp = RedirectResponse(url=base, status_code=303)
    if ok:
        resp.set_cookie("success_msg", ok)
    if err:
        resp.set_cookie("error_msg", err)
    return resp

def register_po_routes(app, get_current_user, log_activity, templates,
                       get_ed_notification_count=None, build_diff_changes=None):
    async def _ed_count():
        try:
            if get_ed_notification_count is not None:
                return await get_ed_notification_count()
        except Exception:
            pass
        return 0
    @app.get("/purchase-orders", response_class=HTMLResponse)
    async def po_page(request: Request, current_user: dict = Depends(get_current_user)):
        qq = (request.query_params.get("q") or "").strip()[:80]
        sel_id = (request.query_params.get("po_id") or "").strip() or None
        s_msg = request.cookies.get("success_msg") or request.query_params.get("success")
        e_msg = request.cookies.get("error_msg") or request.query_params.get("error")

        # --- Filter tahun & kuartal --------------------------------------
        # Prioritas: query param -> cookie (dari render sebelumnya) -> default
        # (tahun terbaru yang punya data). Cookie dipakai supaya filter tetap
        # aktif setelah redirect 303 hasil simpan/hapus item, tanpa harus
        # menyalin parameter filter ke setiap _redirect_po().
        cookie_val = request.cookies.get(PO_FILTER_COOKIE) or ""
        c_tahun, _, c_qtr = cookie_val.partition(":")
        raw_tahun = request.query_params.get("tahun")
        all_years = str(raw_tahun or "").strip().lower() == PO_ALL_YEARS or (
            raw_tahun is None and c_tahun == PO_ALL_YEARS)
        tahun = _clean_tahun(raw_tahun)
        if tahun is None:
            tahun = _clean_tahun(c_tahun)
        if all_years:
            tahun = None
        qtr = _clean_qtr(request.query_params.get("qtr") or c_qtr)
        if tahun is None:
            qtr = None  # kuartal tanpa tahun tidak bisa difilter

        pos = []
        qs = _sanitize_ilike(qq) if qq else ""
        if not qs:
            # Tanpa pencarian: PO terbaru (dibatasi tahun/kuartal bila aktif).
            try:
                q1 = _apply_po_range(
                    supabase.table("purchase_orders")
                    .select("id, no_po, tanggal_po, qty_pcs")
                    .order("tanggal_po", desc=True).limit(_PO_LIST_LIMIT),
                    tahun, qtr)
                pos = (q1.execute().data or [])
            except Exception as ex:
                print(f"[PO] list gagal: {ex}")
        else:
            # Dengan pencarian: dua query terpisah (No. PO & nama produk), masing-masing
            # try/except sendiri supaya yang satu gagal tidak menghilangkan yang lain.
            # Dua-duanya digabung & dedup per id di bawah.
            gabung = {}
            try:
                qa = _apply_po_range(
                    supabase.table("purchase_orders")
                    .select("id, no_po, tanggal_po, qty_pcs")
                    .ilike("no_po", f"%{qs}%").limit(_PO_LIST_LIMIT),
                    tahun, qtr)
                for row in (qa.execute().data or []):
                    if row.get("id"):
                        gabung[row["id"]] = row
            except Exception as ex:
                print(f"[PO] cari No. PO gagal: {ex}")
            try:
                # "!inner" WAJIB; tanpa itu PostgREST tidak memfilter sama sekali —
                # ia mengembalikan seluruh baris tanpa error, sehingga hasilnya
                # diam-diam salah (bukan 0 hasil, tapi semua baris).
                qb = supabase.table("purchase_order_items") \
                    .select("purchase_orders(id, no_po, tanggal_po, qty_pcs), products!inner(nama_produk)") \
                    .ilike("products.nama_produk", f"%{qs}%").limit(1000)
                # Kolom embedded di-filter dengan prefix "purchase_orders.".
                qb = _apply_po_range(qb, tahun, qtr, col="purchase_orders.tanggal_po")
                for row in (qb.execute().data or []):
                    po = row.get("purchase_orders")
                    if isinstance(po, list):
                        po = po[0] if po else None
                    if po and po.get("id") and po["id"] not in gabung:
                        gabung[po["id"]] = po
            except Exception as ex:
                print(f"[PO] cari nama produk gagal: {ex}")
            pos = sorted(
                gabung.values(),
                key=lambda r: (
                    r.get("tanggal_po") is None,          # yang null paling bawah
                    str(r.get("tanggal_po") or ""),       # tanggal terbaru dulu
                    str(r.get("no_po") or ""),            # tie-break
                ),
                reverse=True,
            )[:100]
        # Jaring pengaman: pastikan hanya tanggal dalam rentang yang tampil,
        # walau filter DB di salah satu cabang di atas tidak berlaku.
        pos = [p for p in pos if _in_po_range(p.get("tanggal_po"), tahun, qtr)]

        # --- Tahun yang tersedia + jumlah PO per kuartal (akurat) ----------
        # Satu query ringan (hanya kolom tanggal_po). Dipakai untuk mengisi
        # dropdown tahun dan — kalau datanya lengkap — jumlah per kuartal.
        # Jumlah ini dihitung dari SELURUH baris tahun tersebut, bukan dari
        # 100 PO yang sedang ditampilkan, jadi angkanya tidak mengada-ada.
        years = []                 # [(tahun, jumlah_po), ...] terbaru dulu
        q_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        q_year_total = 0
        q_no_date = 0
        stat_rows = []
        try:
            dq = supabase.table("purchase_orders").select("tanggal_po") \
                .order("tanggal_po", desc=True).limit(_PO_STATS_LIMIT)
            if qs:
                dq = dq.ilike("no_po", f"%{qs}%")
            stat_rows = dq.execute().data or []
        except Exception as ex:
            print(f"[PO] gagal Ambil statistik PO: {ex}")

        def _year_of(d):
            s = str(d or "")[:4]
            return int(s) if len(s) == 4 and s.isdigit() else None

        stat_complete = len(stat_rows) < _PO_STATS_LIMIT
        per_year = {}
        for r in stat_rows:
            y = _year_of(r.get("tanggal_po"))
            if not y:
                q_no_date += 1
            else:
                per_year[y] = per_year.get(y, 0) + 1
        years = sorted(per_year.items(), key=lambda kv: kv[0], reverse=True)

        # Default: tahun terbaru yang punya data (bukan "semua"), supaya daftar
        # tidak pernah memuat semua tahun sekaligus.
        if tahun is None and not all_years and years:
            tahun = years[0][0]
            qtr = None  # kuartal tidak otomatis ikut; user yang memilih

        if tahun is not None:
            if stat_complete:
                # Data sudah lengkap di tangan -> hitung per kuartal tanpa query lagi.
                for r in stat_rows:
                    y = _year_of(r.get("tanggal_po"))
                    if y != tahun:
                        continue
                    d = str(r.get("tanggal_po") or "")[:10]
                    m = d[5:7]
                    if m.isdigit() and 1 <= int(m) <= 12:
                        q_counts[((int(m) - 1) // 3) + 1] += 1
                q_year_total = sum(q_counts.values())
            else:
                # Terlalu banyak baris untuk satu tangan -> query khusus 1 tahun.
                try:
                    cq = supabase.table("purchase_orders").select("tanggal_po") \
                        .gte("tanggal_po", f"{tahun:04d}-01-01") \
                        .lt("tanggal_po", f"{tahun + 1:04d}-01-01") \
                        .limit(_PO_STATS_LIMIT)
                    if qs:
                        cq = cq.ilike("no_po", f"%{qs}%")
                    for r in (cq.execute().data or []):
                        d = str(r.get("tanggal_po") or "")[:10]
                        m = d[5:7]
                        if m.isdigit() and 1 <= int(m) <= 12:
                            q_counts[((int(m) - 1) // 3) + 1] += 1
                    q_year_total = sum(q_counts.values())
                except Exception as ex:
                    print(f"[PO] gagal hitung kuartal: {ex}")
        # Nama produk per PO untuk ditampilkan di daftar kiri. Satu query untuk
        # semua PO yang tampil (bukan per-PO), supaya tidak ada N+1 query.
        po_products = {}
        po_ids = [p["id"] for p in pos if p.get("id")]
        if po_ids:
            try:
                pr = supabase.table("purchase_order_items") \
                    .select("purchase_order_id, products(nama_produk)") \
                    .in_("purchase_order_id", po_ids).order("urutan").execute()
                for row in (pr.data or []):
                    key = row.get("purchase_order_id")
                    prod = row.get("products")
                    if isinstance(prod, list):
                        prod = prod[0] if prod else None
                    name = (prod or {}).get("nama_produk") if isinstance(prod, dict) else None
                    if key and name and key not in po_products:
                        po_products[key] = name
            except Exception as ex:
                print(f"[PO] gagal ambil nama produk: {ex}")
        sel_po = None
        items = []
        next_urutan = 1
        if sel_id:
            try:
                rr = supabase.table("purchase_orders").select("id, no_po, tanggal_po, qty_pcs").eq("id", sel_id).limit(1).execute()
                sel_po = (rr.data or [None])[0]
            except Exception as ex:
                print(f"[PO] get gagal: {ex}")
            if sel_po:
                try:
                    ir = supabase.table("purchase_order_items").select("*, products(id, nama_produk, no_na_produk), product_batches(id, no_batch)").eq("purchase_order_id", sel_id).order("urutan").execute()
                    items = ir.data or []
                    if items:
                        mx = max(int(x.get("urutan") or 0) for x in items)
                        next_urutan = mx + 1
                except Exception as ex:
                    print(f"[PO] items gagal: {ex}")
        ctx = {
            "current_user": current_user, "pos": pos, "q": qq, "sel_po": sel_po,
            "items": items, "next_urutan": next_urutan, "success_msg": s_msg,
            "error_msg": e_msg, "po_products": po_products,
            "ed_notification_count": await _ed_count(),
            # Filter tahun/kuartal + statistiknya
            "tahun": tahun, "qtr": qtr, "all_years": all_years,
            "years": years, "q_counts": q_counts, "q_year_total": q_year_total,
            "q_no_date": q_no_date, "shown": len(pos), "list_limit": _PO_LIST_LIMIT,
            "total_all": sum(per_year.values()),
        }
        resp = templates.TemplateResponse(request=request, name="purchase_orders.html", context=ctx)
        # Simpan filter aktif di cookie supaya redirect 303 setelah simpan/hapus
        # item tidak menghapus pilihan tahun/kuartal user.
        resp.set_cookie(
            PO_FILTER_COOKIE,
            f"{PO_ALL_YEARS if tahun is None else tahun}:{qtr or ''}",
            max_age=60 * 60 * 24 * 180, httponly=False, samesite="lax", path="/",
        )
        if s_msg:
            resp.delete_cookie("success_msg")
        if e_msg:
            resp.delete_cookie("error_msg")
        return resp

    @app.get("/api/po/search")
    async def api_po_search(q: str = "", current_user: dict = Depends(get_current_user)):
        qn = _sanitize_ilike(q)
        rows = []
        q2 = supabase.table("purchase_orders").select("id, no_po, tanggal_po").order("tanggal_po", desc=True).limit(20)
        if qn:
            q2 = q2.ilike("no_po", f"%{qn}%")
        try:
            rows = (q2.execute().data or [])
        except Exception as ex:
            print(f"[PO] search gagal: {ex}")
        return JSONResponse({"items": rows})

    @app.get("/api/po/products")
    async def api_po_products(q: str = "", current_user: dict = Depends(get_current_user)):
        qn = _sanitize_ilike(q)
        rows = []
        q3 = supabase.table("products").select("id, nama_produk, no_na_produk").eq("is_deleted", False)
        if qn:
            q3 = q3.or_(f"no_na_produk.ilike.%{qn}%,nama_produk.ilike.%{qn}%")
        try:
            rows = (q3.order("nama_produk").limit(20).execute().data or [])
        except Exception as ex:
            print(f"[PO] products gagal: {ex}")
        if qn:
            ql = qn.lower()
            rows.sort(key=lambda r: (0 if ql in str(r.get("no_na_produk") or "").lower() else 1, str(r.get("nama_produk") or "")))
        return JSONResponse({"items": rows})

    @app.get("/api/po/batches")
    async def api_po_batches(product_id: str = "", current_user: dict = Depends(get_current_user)):
        pid = (product_id or "").strip()
        if not pid:
            return JSONResponse({"items": []})
        rows = []
        try:
            res = supabase.table("product_batches").select("id, no_batch, tanggal_produksi, tanggal_ed").eq("product_id", pid).order("tanggal_produksi", desc=True).limit(50).execute()
            rows = res.data or []
        except Exception:
            print("[PO] batches gagal.")
        return JSONResponse({"items": rows})

    @app.post("/purchase-orders")
    async def po_create(request: Request, no_po: str = Form(...), tanggal_po: str = Form(None), qty_pcs: str = Form(None), current_user: dict = Depends(get_current_user)):
        no_po_clean = _clean_text(no_po, 200)
        if not no_po_clean:
            return _redirect_po(None, err="No. PO wajib diisi.")
        tgl = _parse_opt_date(tanggal_po)
        if tgl == "INVALID":
            return _redirect_po(None, err="Format Tgl PO tidak valid.")
        qty = _parse_opt_float(qty_pcs)
        if qty == "INVALID":
            return _redirect_po(None, err="Qty (Pcs) harus angka.")
        dup = None
        try:
            dup = supabase.table("purchase_orders").select("id").eq("no_po", no_po_clean).limit(1).execute()
        except Exception as ex:
            print(f"[PO] cek dup gagal: {ex}")
        if dup and dup.data:
            return _redirect_po(dup.data[0]["id"], err="No. PO sudah ada. Pilih dari daftar.")
        new_id = None
        try:
            res = supabase.table("purchase_orders").insert({"no_po": no_po_clean, "tanggal_po": tgl, "qty_pcs": qty}).execute()
            if res.data:
                new_id = res.data[0]["id"]
        except Exception as ex:
            print(f"[PO] insert gagal: {ex}")
        if not new_id:
            return _redirect_po(None, err="Gagal membuat PO (kemungkinan duplikat).")
        log_activity(current_user, "create", "purchase_order", new_id, no_po_clean)
        return _redirect_po(new_id, ok=f"PO {no_po_clean} dibuat.")

    @app.post("/product-batches")
    async def product_batch_create(request: Request, product_id: str = Form(...), no_batch: str = Form(...), tanggal_produksi: str = Form(None), tanggal_ed: str = Form(None), po_id: str = Form(None), current_user: dict = Depends(get_current_user)):
        pid = (product_id or "").strip()
        nb = _clean_text(no_batch, 200)
        back = (po_id or "").strip() or None
        wants_json = "application/json" in (request.headers.get("accept") or "")
        if not pid or not nb:
            msg = "Produk dan No. Batch wajib diisi."
            if wants_json:
                return JSONResponse({"ok": False, "error": msg}, status_code=400)
            return _redirect_po(back, err=msg)
        ok_prod = False
        try:
            pr = supabase.table("products").select("id").eq("id", pid).eq("is_deleted", False).limit(1).execute()
            ok_prod = bool(pr.data)
        except Exception:
            ok_prod = False
        if not ok_prod:
            msg = "Produk tidak ditemukan."
            if wants_json:
                return JSONResponse({"ok": False, "error": msg}, status_code=404)
            return _redirect_po(back, err=msg)
        tprod = _parse_opt_date(tanggal_produksi)
        if tprod == "INVALID":
            msg = "Format Tgl Produksi tidak valid."
            if wants_json:
                return JSONResponse({"ok": False, "error": msg}, status_code=400)
            return _redirect_po(back, err=msg)
        if not tprod:
            tprod = datetime.now(WIB).date().isoformat()
        ted = _parse_opt_date(tanggal_ed)
        if ted == "INVALID":
            msg = "Format Tgl ED tidak valid."
            if wants_json:
                return JSONResponse({"ok": False, "error": msg}, status_code=400)
            return _redirect_po(back, err=msg)
        dupb = None
        try:
            dupb = supabase.table("product_batches").select("id").eq("product_id", pid).eq("no_batch", nb).limit(1).execute()
        except Exception as ex:
            print(f"[PO] cek dup batch gagal: {ex}")
        if dupb and dupb.data:
            msg = f"Batch {nb} sudah ada utk produk ini."
            if wants_json:
                return JSONResponse({"ok": False, "error": msg, "batch": dupb.data[0]}, status_code=409)
            return _redirect_po(back, err=msg)
        new_b = None
        try:
            res = supabase.table("product_batches").insert({"product_id": pid, "no_batch": nb, "tanggal_produksi": tprod, "tanggal_ed": ted}).execute()
            if res.data:
                new_b = res.data[0]
        except Exception as ex:
            print(f"[PO] insert batch gagal: {ex}")
        if not new_b:
            msg = "Gagal membuat batch. Coba lagi."
            if wants_json:
                return JSONResponse({"ok": False, "error": msg}, status_code=500)
            return _redirect_po(back, err=msg)
        log_activity(current_user, "create", "product_batch", new_b["id"], f"{nb}")
        if wants_json:
            return JSONResponse({"ok": True, "batch": new_b})
        return _redirect_po(back, ok=f"Batch {nb} dibuat.")

    @app.post("/purchase-orders/{po_id}/items")
    async def po_item_create(request: Request, po_id: str, product_id: str = Form(...), product_batch_id: str = Form(...), tanggal_catatan_batch: str = Form(None), wip: str = Form(None), netto: str = Form(None), qty_kg: str = Form(None), keterangan: str = Form(None), qty_belum_sop: str = Form(None), qty_po_kg: str = Form(None), status_bpom: str = Form(None), catatan_produksi: str = Form(None), revisi_produksi: str = Form(None), temporary_reject: str = Form(None), current_user: dict = Depends(get_current_user)):
        pid = (product_id or "").strip()
        bid = (product_batch_id or "").strip()
        if not pid or not bid:
            return _redirect_po(po_id, err="Produk dan Batch wajib dipilih.")
        po = None
        try:
            por = supabase.table("purchase_orders").select("id, no_po").eq("id", po_id).limit(1).execute()
            po = (por.data or [None])[0]
        except Exception:
            po = None
        if not po:
            return _redirect_po(None, err="PO tidak ditemukan.")
        ok_prod = False
        try:
            pr = supabase.table("products").select("id").eq("id", pid).eq("is_deleted", False).limit(1).execute()
            ok_prod = bool(pr.data)
        except Exception:
            return _redirect_po(po_id, err="Gagal validasi produk.")
        if not ok_prod:
            return _redirect_po(po_id, err="Produk tidak ditemukan.")
        brow = None
        try:
            br = supabase.table("product_batches").select("id, product_id").eq("id", bid).limit(1).execute()
            brow = (br.data or [None])[0]
        except Exception:
            brow = None
        if not brow:
            return _redirect_po(po_id, err="Batch tidak ditemukan.")
        if str(brow.get("product_id") or "") != pid:
            return _redirect_po(po_id, err="Batch tsb milik produk lain.")
        tgl = _parse_opt_date(tanggal_catatan_batch)
        if tgl == "INVALID":
            return _redirect_po(po_id, err="Format Tgl Catatan tidak valid.")
        wip_v = _parse_opt_float(wip)
        qkg_v = _parse_opt_float(qty_kg)
        qbs_v = _parse_opt_float(qty_belum_sop)
        qpokg_v = _parse_opt_float(qty_po_kg)
        bad = None
        for label, vv in [("WIP", wip_v), ("Qty kg", qkg_v), ("Qty Belum SOP", qbs_v), ("Qty PO kg", qpokg_v)]:
            if vv == "INVALID":
                bad = label
        if bad:
            return _redirect_po(po_id, err=f"{bad} harus angka.")
        base = {"purchase_order_id": po_id, "product_id": pid, "product_batch_id": bid, "tanggal_catatan_batch": tgl, "wip": wip_v, "netto": _clean_text(netto, 200), "qty_kg": qkg_v, "keterangan": _clean_text(keterangan, 1000), "qty_belum_sop": qbs_v, "qty_po_kg": qpokg_v, "status_bpom": _clean_text(status_bpom, 200), "catatan_produksi": _clean_text(catatan_produksi, 1000), "revisi_produksi": _clean_text(revisi_produksi, 1000), "temporary_reject": _clean_text(temporary_reject, 1000), "excel_row": None}
        saved = False
        saved_id = None
        saved_nxt = 1
        for attempt in range(2):
            nxt = 1
            try:
                mr = supabase.table("purchase_order_items").select("urutan").eq("purchase_order_id", po_id).order("urutan", desc=True).limit(1).execute()
                mrows = mr.data or []
                if mrows:
                    nxt = int(mrows[0].get("urutan") or 0) + 1
            except Exception:
                nxt = 1
            base["urutan"] = nxt
            try:
                res = supabase.table("purchase_order_items").insert(base).execute()
                if res.data:
                    saved = True
                    saved_id = res.data[0]["id"]
                    saved_nxt = nxt
                    break
                return _redirect_po(po_id, err="Gagal menyimpan item. Coba lagi.")
            except Exception as ex:
                low = str(ex).lower()
                if ("urutan" in low or "duplicate" in low or "unique" in low) and attempt == 0:
                    continue
                print(f"[PO] insert item gagal: {ex}")
                return _redirect_po(po_id, err="Gagal menyimpan item. Coba lagi.")
        if not saved:
            return _redirect_po(po_id, err="Gagal menyimpan item. Coba lagi.")
        log_activity(current_user, "create", "purchase_order_item", saved_id, f"{po.get('no_po')} #{saved_nxt}")
        return _redirect_po(po_id, ok=f"Item #{saved_nxt} tersimpan.")

    @app.post("/purchase-orders/{po_id}/items/{item_id}/update")
    async def po_item_update(request: Request, po_id: str, item_id: str, product_id: str = Form(...), product_batch_id: str = Form(...), tanggal_catatan_batch: str = Form(None), wip: str = Form(None), netto: str = Form(None), qty_kg: str = Form(None), keterangan: str = Form(None), qty_belum_sop: str = Form(None), qty_po_kg: str = Form(None), status_bpom: str = Form(None), catatan_produksi: str = Form(None), revisi_produksi: str = Form(None), temporary_reject: str = Form(None), current_user: dict = Depends(get_current_user)):
        pid = (product_id or "").strip()
        bid = (product_batch_id or "").strip()
        if not pid or not bid:
            return _redirect_po(po_id, err="Produk dan Batch wajib diisi.")
        # Ambil baris SEBELUM update supaya selisih nilainya bisa dicatat di
        # activity log (bukan cuma "ada yang berubah").
        currow = None
        try:
            cur = supabase.table("purchase_order_items").select(
                "id, purchase_order_id, urutan, product_id, product_batch_id, "
                "tanggal_catatan_batch, wip, netto, qty_kg, keterangan, qty_belum_sop, "
                "qty_po_kg, status_bpom, catatan_produksi, revisi_produksi, temporary_reject"
            ).eq("id", item_id).limit(1).execute()
            currow = (cur.data or [None])[0]
        except Exception:
            currow = None
        if not currow or str(currow.get("purchase_order_id") or "") != str(po_id):
            return _redirect_po(po_id, err="Item tidak ditemukan di PO ini.")
        tgl = _parse_opt_date(tanggal_catatan_batch)
        if tgl == "INVALID":
            return _redirect_po(po_id, err="Format Tgl Catatan tidak valid.")
        wip_v = _parse_opt_float(wip)
        qkg_v = _parse_opt_float(qty_kg)
        qbs_v = _parse_opt_float(qty_belum_sop)
        qpokg_v = _parse_opt_float(qty_po_kg)
        bad = None
        for label, vv in [("WIP", wip_v), ("Qty kg", qkg_v), ("Qty Belum SOP", qbs_v), ("Qty PO kg", qpokg_v)]:
            if vv == "INVALID":
                bad = label
        if bad:
            return _redirect_po(po_id, err=f"{bad} harus angka.")
        brow = None
        try:
            br = supabase.table("product_batches").select("id, product_id").eq("id", bid).limit(1).execute()
            brow = (br.data or [None])[0]
        except Exception:
            brow = None
        if not brow or str(brow.get("product_id") or "") != pid:
            return _redirect_po(po_id, err="Batch tidak cocok dgn produk.")
        upd = {"product_id": pid, "product_batch_id": bid, "tanggal_catatan_batch": tgl, "wip": wip_v, "netto": _clean_text(netto, 200), "qty_kg": qkg_v, "keterangan": _clean_text(keterangan, 1000), "qty_belum_sop": qbs_v, "qty_po_kg": qpokg_v, "status_bpom": _clean_text(status_bpom, 200), "catatan_produksi": _clean_text(catatan_produksi, 1000), "revisi_produksi": _clean_text(revisi_produksi, 1000), "temporary_reject": _clean_text(temporary_reject, 1000)}
        try:
            supabase.table("purchase_order_items").update(upd).eq("id", item_id).execute()
        except Exception as ex:
            print(f"[PO] update gagal: {ex}")
            return _redirect_po(po_id, err="Gagal menyimpan perubahan.")
        item_changes = []
        if build_diff_changes is not None:
            try:
                item_changes = build_diff_changes(
                    currow or {},
                    upd,
                    PO_ITEM_FIELD_LABELS,
                )
            except Exception as ex:
                print(f"[PO] gagal susun diff item: {ex}")
        log_activity(
            current_user,
            "update",
            "purchase_order_item",
            item_id,
            f"item {item_id[:8]} (urutan {currow.get('urutan')})" if currow else f"item {item_id[:8]}",
            item_changes,
        )
        return _redirect_po(po_id, ok="Perubahan item tersimpan.")

    @app.post("/purchase-orders/{po_id}/items/{item_id}/delete")
    async def po_item_delete(po_id: str, item_id: str, current_user: dict = Depends(get_current_user)):
        currow = None
        try:
            cur = supabase.table("purchase_order_items").select("id, purchase_order_id, urutan").eq("id", item_id).limit(1).execute()
            currow = (cur.data or [None])[0]
        except Exception:
            currow = None
        if not currow or str(currow.get("purchase_order_id") or "") != str(po_id):
            return _redirect_po(po_id, err="Item tidak ditemukan di PO ini.")
        try:
            supabase.table("purchase_order_items").delete().eq("id", item_id).execute()
        except Exception as ex:
            print(f"[PO] delete gagal: {ex}")
            return _redirect_po(po_id, err="Gagal menghapus item.")
        log_activity(current_user, "delete", "purchase_order_item", item_id, f"urutan {currow.get('urutan')}")
        return _redirect_po(po_id, ok="Item dihapus.")
