"""Live-input PO/batch produksi untuk tim QC."""
from __future__ import annotations
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from app.database import supabase
WIB = ZoneInfo("Asia/Jakarta")

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

def register_po_routes(app, get_current_user, log_activity, templates, get_ed_notification_count=None):
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
        pos = []
        q1 = supabase.table("purchase_orders").select("id, no_po, tanggal_po, qty_pcs").order("tanggal_po", desc=True).limit(100)
        if qq:
            qs = _sanitize_ilike(qq)
            if qs:
                q1 = q1.ilike("no_po", f"%{qs}%")
        try:
            pos = (q1.execute().data or [])
        except Exception as ex:
            print(f"[PO] list gagal: {ex}")
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
        ctx = {"current_user": current_user, "pos": pos, "q": qq, "sel_po": sel_po, "items": items, "next_urutan": next_urutan, "success_msg": s_msg, "error_msg": e_msg, "ed_notification_count": await _ed_count()}
        resp = templates.TemplateResponse(request=request, name="purchase_orders.html", context=ctx)
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
        currow = None
        try:
            cur = supabase.table("purchase_order_items").select("id, purchase_order_id").eq("id", item_id).limit(1).execute()
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
        log_activity(current_user, "update", "purchase_order_item", item_id, f"item {item_id[:8]}")
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
