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
# Nilai sentinel untuk opsi "Tanpa item": PO yang belum punya purchase_order_items
# sehingga perusahaannya tidak diketahui (bukan bucket perusahaan).
PO_NO_ITEMS = "Tanpa item"
# Batas pengambilan baris PO untuk daftar. BUKAN batas tampilan: seluruh daftar
# ditampilkan (jumlah PO saat ini ~420). Angka ini hanya jaring pengaman supaya
# tabel yang tumbuh terus tidak membuat halaman gagal atau sangat lambat.
_PO_LIST_LIMIT = 5000
_PO_YEAR_MIN, _PO_YEAR_MAX = 2000, 2100
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


def _current_quarter():
    """Kuartal berjalan (1..4) menurut tanggal hari ini di WIB.

    Dipakai sebagai quarter default supaya halaman tidak pernah membuka
    "semua kuartal" — hanya ada Q1..Q4.
    """
    return ((datetime.now(WIB).month - 1) // 3) + 1


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

# ---------------------------------------------------------------------------
# Agregasi untuk halaman /po-analytics (jumlah PO per kuartal, top produk, dll.)
# Semua fungsi di blok ini murni (tidak menyentuh database) supaya bisa diuji
# tanpa koneksi; route hanya mengumpulkan baris lalu memanggil _build_po_analytics.
# ---------------------------------------------------------------------------
PO_ANALYTICS_TABS = ("all", "erfi", "heka")
PO_REWORK_TAG = "rework"
_MONTH_TO_Q = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2, 7: 3, 8: 3, 9: 3, 10: 4, 11: 4, 12: 4}
# Cache deteksi kolom: None = belum dicek. Kolom ditambahkan lewat migration
# 002_add_jenis_po.sql yang dijalankan manual, jadi kemunculannya bisa berubah
# setelah server hidup — karena itu dicek sekali lalu disimpan.
_JENIS_PO_AVAILABLE = None


def _jenis_po_available():
    """True kalau purchase_orders.jenis_po sudah ada di database.

    Kalau kolom belum ada, PostgREST akan menolak SELURUH query yang
    menyebut kolom itu, jadi kolom harus dicek terpisah sebelum dipakai.
    """
    global _JENIS_PO_AVAILABLE
    if _JENIS_PO_AVAILABLE is None:
        try:
            supabase.table("purchase_orders").select("id, jenis_po").limit(1).execute()
            _JENIS_PO_AVAILABLE = True
        except Exception as ex:
            print(f"[PO] kolom jenis_po belum ada, filter Rework nonaktif: {str(ex)[:140]}")
            _JENIS_PO_AVAILABLE = False
    return _JENIS_PO_AVAILABLE


def _is_rework(po):
    """True untuk PO bertag Rework. Perbandingan dinormalisasi karena nilai
    di database bisa 'Rework'/'rework'/ber-spasi (lihat migration/tag_rework_po.py)."""
    return str((po or {}).get("jenis_po") or "").strip().lower() == PO_REWORK_TAG


def _company_bucket(v):
    """'PT Erfi' / 'Erfi' / 'erfi' -> 'PT Erfi'. Nilai lain -> 'Lainnya'.

    Normalisasi wajib: products.perusahaan memakai 'PT Erfi'/'PT Heka',
    sedangkan tabel lain (mis. sample_submissions.company) memakai 'Erfi'/'Heka'.
    """
    s = re.sub(r"(?i)^PT\s+", "", str(v or "")).strip().lower()
    if s == "erfi":
        return "PT Erfi"
    if s == "heka":
        return "PT Heka"
    return "Lainnya"


def _tab_of(company):
    """Bucket perusahaan -> tab navigasi. 'Lainnya' hanya muncul di tab 'all'."""
    if company == "PT Erfi":
        return "erfi"
    if company == "PT Heka":
        return "heka"
    return "all"


def _clean_pt(v):
    """Nilai filter perusahaan -> 'PT Erfi' | 'PT Heka' | 'Tanpa item' | None.

    Menerima 'PT Erfi'/'Erfi'/'erfi' (dinormalkan lewat _company_bucket).
    PT_NO_ITEMS memakai nilai sentinel karena "PO tanpa item" bukan bucket
    perusahaan, melainkan kondisi tidak adanya purchase_order_items.
    Nilai lain ('all', '') -> None (tanpa filter).
    """
    s = str(v or "").strip()
    if s == PO_NO_ITEMS:
        return PO_NO_ITEMS
    b = _company_bucket(s)
    return b if b in ("PT Erfi", "PT Heka") else None


def _pt_index(items_rows):
    """Dari baris purchase_order_items, buat dua peta per PO:
       - companies : {po_id: {bucket, ...}}   (PO bisa muncul di 2 PT)
       - names     : {po_id: {bucket: nama_produk pertama bucket tsb}}
    Dipakai untuk memfilter daftar PO per perusahaan tanpa query tambahan.
    """
    companies, names = {}, {}
    for row in items_rows or []:
        po_id = row.get("purchase_order_id")
        if not po_id:
            continue
        prod = row.get("products")
        if isinstance(prod, list):
            prod = prod[0] if prod else None
        if not isinstance(prod, dict):
            continue
        bucket = _company_bucket(prod.get("perusahaan"))
        companies.setdefault(po_id, set()).add(bucket)
        nama = _clean_text(prod.get("nama_produk"), 200)
        if nama:
            names.setdefault(po_id, {}).setdefault(bucket, nama)
    return companies, names


def _year_of(d):
    s = str(d or "")[:4]
    return int(s) if len(s) == 4 and s.isdigit() else None


def _quarter_of(d):
    """'2026-07-09' -> 3. Nilai NULL/aneh -> None."""
    s = str(d or "")[:7]
    if len(s) < 7 or s[4] != "-":
        return None
    try:
        month = int(s[5:7])
    except ValueError:
        return None
    return _MONTH_TO_Q.get(month)


def _num(v):
    """NUMERIC dari PostgREST bisa int/float/str; yang tidak valid dianggap 0."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _build_po_analytics(pos_rows, item_rows, product_rows, tahun, qtr=None, sort="pcs", top_n=5):
    """Susun seluruh angka halaman /po-analytics dari baris mentah.

    pos_rows      : {id, no_po, tanggal_po, qty_pcs, jenis_po?}
    item_rows     : {purchase_order_id, product_id}
    product_rows  : {id, nama_produk, perusahaan, is_deleted, laporan_uji_sig_file_url}
    tahun         : hanya PO & item tahun ini yang dihitung. Route sudah memfilter
                    lewat rentang tanggal di SQL, jadi ini jaring pengaman kedua:
                    kalau tahun=None TIDAK ada yang dihitung, bukan "semua tahun".
    qtr           : 1..4 untuk membatasi daftar produk ke satu kuartal. KPI, chart
                    per kuartal, dan per perusahaan TETAP memakai seluruh tahun
                    supaya konteksnya tidak hilang.
    sort          : "pcs" (default) atau "po" -> dasar pengurutan daftar top.

    Aturan hitung:
      - jumlah PO & pcs per kuartal hanya untuk PO yang tanggalnya valid
      - PO bertag Rework: TETAP dihitung sebagai jumlah PO, tapi qty_pcs-nya
        tidak ikut dijumlahkan (keputusan user)
      - qty_pcs per produk dijumlahkan per PO UNIK, supaya satu PO tidak
        terhitung berkali-kali kalau produknya muncul di beberapa baris item
    """
    po_by_id = {}
    for p in pos_rows or []:
        if p.get("id") and _year_of(p.get("tanggal_po")) == tahun:
            po_by_id[p["id"]] = p
    year_ids = set(po_by_id)
    # Route sudah menyaring lewat _clean_qtr(), tapi helper ikut menormalisasi
    # supaya aman kalau dipanggil dari tempat lain dengan nilai mentah.
    qtr = qtr if qtr in (1, 2, 3, 4) else None
    sort = "po" if sort == "po" else "pcs"

    prod_meta = {}
    for r in product_rows or []:
        if r.get("id"):
            prod_meta[r["id"]] = {
                "nama": _clean_text(r.get("nama_produk"), 200) or "Tanpa nama",
                "company": _company_bucket(r.get("perusahaan")),
                "active": not r.get("is_deleted"),
                "sig": bool(r.get("laporan_uji_sig_file_url")),
            }

    # --- KPI & per kuartal -------------------------------------------------
    q_po = {1: 0, 2: 0, 3: 0, 4: 0}
    q_pcs = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
    total_po = 0
    total_pcs = 0.0
    rework_po = 0
    rework_pcs = 0.0
    for p in po_by_id.values():
        q = _quarter_of(p.get("tanggal_po"))
        if not q:
            continue
        pcs = _num(p.get("qty_pcs"))
        total_po += 1
        q_po[q] += 1
        if _is_rework(p):
            rework_po += 1
            rework_pcs += pcs
        else:
            total_pcs += pcs
            q_pcs[q] += pcs

    # --- produk per PO (dari item) ----------------------------------------
    # prod_po_ids dipakai untuk daftar top -> dibatasi ke qtr bila dipilih.
    # comp_q_po dipakai untuk chart per perusahaan -> tetap seluruh tahun.
    prod_po_ids = {}
    comp_q_po = {}
    for it in item_rows or []:
        poid = it.get("purchase_order_id")
        pid = it.get("product_id")
        if poid not in year_ids:
            continue  # jaring pengaman: item dari luar tahun terpilih
        meta = prod_meta.get(pid)
        if not meta:
            continue  # produk tidak ada di master
        q = _quarter_of(po_by_id[poid].get("tanggal_po"))
        # Grafik per perusahaan SELALU per tahun, jadi dicatat lebih dulu --
        # sebelum penyaringan kuartal untuk daftar top.
        if q:
            comp_q_po.setdefault(meta["company"], {}).setdefault(q, set()).add(poid)
        if qtr and q != qtr:
            continue  # daftar top difilter ke satu kuartal
        prod_po_ids.setdefault(pid, set()).add(poid)

    def _row(pid):
        meta = prod_meta[pid]
        po_ids = prod_po_ids.get(pid) or set()
        pcs = 0.0
        rw = 0
        for poid in po_ids:
            po = po_by_id[poid]
            if _is_rework(po):
                rw += 1
            else:
                pcs += _num(po.get("qty_pcs"))
        return {
            "id": pid, "nama": meta["nama"], "company": meta["company"],
            "po_count": len(po_ids), "rework_po": rw, "pcs": pcs, "sig": meta["sig"],
        }

    active_ids = [pid for pid, m in prod_meta.items() if m["active"]]
    produced = {pid: _row(pid) for pid in active_ids if pid in prod_po_ids}

    # "po" = urutkan berdasarkan jumlah PO; "pcs" = berdasarkan total qty.
    def _rank(rows):
        if sort == "po":
            return sorted(rows, key=lambda r: (-r["po_count"], -r["pcs"], r["nama"]))
        return sorted(rows, key=lambda r: (-r["pcs"], -r["po_count"], r["nama"]))

    top, missing = {}, {}
    for t in PO_ANALYTICS_TABS:
        pool_top = [r for r in produced.values() if t == "all" or _tab_of(r["company"]) == t]
        top[t] = _rank(pool_top)[:top_n]
        # Daftar "belum punya laporan uji" diambil dari SEMUA produk aktif
        # (bukan cuma yang punya PO), lalu diurutkan pcs tahun terpilih.
        pool_missing = [
            _row(pid) for pid in active_ids
            if not prod_meta[pid]["sig"] and (t == "all" or _tab_of(prod_meta[pid]["company"]) == t)
        ]
        missing[t] = _rank(pool_missing)[:top_n]

    # Daftar perusahaan SELALU per tahun, jadi grafik per perusahaan dan donat
    # proporsi tidak ikut berubah hanya karena pengguna berganti kuartal.
    companies = [c for c in ("PT Erfi", "PT Heka", "Lainnya") if c in comp_q_po]
    per_company = {}
    for c in companies:
        qs = comp_q_po[c]
        per_company[c] = {
            "q_po": [len(qs.get(q, ())) for q in (1, 2, 3, 4)],
            "q_pcs": [
                sum(_num(po_by_id[p].get("qty_pcs")) for p in qs.get(q, ()) if not _is_rework(po_by_id[p]))
                for q in (1, 2, 3, 4)
            ],
            "po": sum(len(v) for v in qs.values()),
        }
    per_company.setdefault("Lainnya", {"q_po": [0, 0, 0, 0], "q_pcs": [0.0] * 4, "po": 0})
    per_company.setdefault("PT Erfi", {"q_po": [0, 0, 0, 0], "q_pcs": [0.0] * 4, "po": 0})
    per_company.setdefault("PT Heka", {"q_po": [0, 0, 0, 0], "q_pcs": [0.0] * 4, "po": 0})

    # --- PO yang belum punya item -------------------------------------------
    # PO seperti ini tetap TERHITUNG di total_po / total_pcs (keduanya dari
    # purchase_orders), tapi tidak bisa diatribusikan ke produk maupun
    # perusahaan karena tidak ada purchase_order_items. Tanpa informasi ini
    # grafik per perusahaan menampilkan "0 PO" padahal PO-nya ada.
    # PENTING: item_rows sudah difilter tahun oleh route, jadi pengurangan
    # di sini hanya membuang PO yang benar-benar tanpa item.
    item_po_ids = {it.get("purchase_order_id") for it in (item_rows or [])}
    po_tanpa_item = sorted(
        str(po_by_id[pid].get("no_po") or "")
        for pid in set(po_by_id) - item_po_ids
        if po_by_id[pid].get("no_po")
    )

    return {
        "total_po": total_po,
        "total_pcs": total_pcs,
        "rework_po": rework_po,
        "rework_pcs": rework_pcs,
        "q_po": [q_po[q] for q in (1, 2, 3, 4)],
        "q_pcs": [q_pcs[q] for q in (1, 2, 3, 4)],
        "companies": [c for c in ("PT Erfi", "PT Heka")],
        "per_company": per_company,
        "produk_aktif": len(active_ids),
        "produk_diproduksi": len(produced),
        "top": top,
        "missing": missing,
        "missing_total": sum(1 for pid in active_ids if not prod_meta[pid]["sig"]),
        "jumlah_po_tanpa_item": len(po_tanpa_item),
        "po_tanpa_item": po_tanpa_item[:50],
        "qtr": qtr,
        "sort": sort,
        "truncated": len(po_by_id) >= _PO_STATS_LIMIT,
    }

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
        # Bentuk cookie: "tahun:qtr:pt" (dua bagian saja = versi lama, pt kosong).
        c_parts = cookie_val.split(":")
        c_tahun = c_parts[0] if c_parts else ""
        c_qtr = c_parts[1] if len(c_parts) > 1 else ""
        c_pt = c_parts[2] if len(c_parts) > 2 else ""
        raw_tahun = request.query_params.get("tahun")
        all_years = str(raw_tahun or "").strip().lower() == PO_ALL_YEARS or (
            raw_tahun is None and c_tahun == PO_ALL_YEARS)
        tahun = _clean_tahun(raw_tahun)
        if tahun is None:
            tahun = _clean_tahun(c_tahun)
        if all_years:
            tahun = None
        qtr_param = _clean_qtr(request.query_params.get("qtr") or c_qtr)
        qtr = qtr_param or _current_quarter()
        # Filter perusahaan. PO tidak punya kolom perusahaan: perusahaan diambil
        # dari produk lewat purchase_order_items (lihat _pt_index di bawah).
        pt = _clean_pt(request.query_params.get("pt") or c_pt)

        qs = _sanitize_ilike(qq) if qq else ""
        # --- Tahun yang tersedia + jumlah PO per kuartal (akurat) ----------
        # Satu query ringan (hanya kolom tanggal_po). Dipakai untuk mengisi
        # dropdown tahun dan — kalau datanya lengkap — jumlah per kuartal.
        # Jumlah ini dihitung dari SELURUH baris tahun tersebut, bukan dari
        # daftar yang sedang ditampilkan, jadi angkanya tidak mengada-ada.
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
            print(f"[PO] gagal ambil statistik PO: {ex}")

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

        # Jumlah PO per (tahun, kuartal) — dipakai untuk memilih quarter default
        # sebelum query daftar dijalankan.
        q_by_year = {}
        if stat_complete:
            for r in stat_rows:
                y = _year_of(r.get("tanggal_po"))
                q = _quarter_of(r.get("tanggal_po"))
                if y and q:
                    q_by_year[(y, q)] = q_by_year.get((y, q), 0) + 1

        # Default: tahun terbaru yang punya data, supaya daftar tidak pernah
        # memuat semua tahun sekaligus.
        if tahun is None and not all_years and years:
            tahun = years[0][0]
        # Q1..Q4 hanya bisa difilter kalau ada tahun. Karena qtr selalu terisi
        # (default = kuartal berjalan), memilih "Semua Tahun" berarti kuartal
        # diabaikan — dan tombolnya nonaktif di template.
        if tahun is None:
            qtr = None
        elif qtr_param is None:
            # Quarter default: kuartal TERAKHIR yang punya data di tahun ini,
            # bukan kuartal berjalan. Kalau tidak, halaman bisa terbuka kosong
            # (mis. Oktober = Q4 sementara data tahun ini baru sampai Q3).
            q_terisi = [n for (y, n) in q_by_year if y == tahun]
            qtr = max(q_terisi) if q_terisi else _current_quarter()

        pos = []
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
            )[:_PO_LIST_LIMIT]
        # Jaring pengaman: pastikan hanya tanggal dalam rentang yang tampil,
        # walau filter DB di salah satu cabang di atas tidak berlaku.
        pos = [p for p in pos if _in_po_range(p.get("tanggal_po"), tahun, qtr)]

        if tahun is not None:
            if stat_complete:
                # Data sudah lengkap di tangan -> hitung per kuartal tanpa query lagi.
                for r in stat_rows:
                    y = _year_of(r.get("tanggal_po"))
                    if y != tahun:
                        continue
                    q = _quarter_of(r.get("tanggal_po"))
                    if q:
                        q_counts[q] += 1
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
                        q = _quarter_of(r.get("tanggal_po"))
                        if q:
                            q_counts[q] += 1
                    q_year_total = sum(q_counts.values())
                except Exception as ex:
                    print(f"[PO] gagal hitung kuartal: {ex}")
        # Nama produk + perusahaan per PO untuk daftar kiri DAN filter PT.
        # Satu query untuk semua PO yang tampil (bukan per-PO), jadi tidak ada N+1.
        po_products = {}
        po_companies = {}
        po_prod_by_pt = {}
        pt_counts = {"PT Erfi": 0, "PT Heka": 0, "": 0}
        po_ids = [p["id"] for p in pos if p.get("id")]
        if po_ids:
            try:
                pr = supabase.table("purchase_order_items") \
                    .select("purchase_order_id, products(nama_produk, perusahaan)") \
                    .in_("purchase_order_id", po_ids).order("urutan").execute()
                rows_i = pr.data or []
                po_companies, po_prod_by_pt = _pt_index(rows_i)
                for row in rows_i:
                    key = row.get("purchase_order_id")
                    prod = row.get("products")
                    if isinstance(prod, list):
                        prod = prod[0] if prod else None
                    name = (prod or {}).get("nama_produk") if isinstance(prod, dict) else None
                    if key and name and key not in po_products:
                        po_products[key] = name
                # Hitung jumlah per bucket dari PO yang SEDANG TAMPIL (setelah
                # filter tahun/kuartal), supaya angka di dropdown tidak bergeser
                # saat produk atau tahun berubah.
                for p in pos:
                    pid = p.get("id")
                    buckets = po_companies.get(pid) or set()
                    for b in buckets:
                        if b in pt_counts:
                            pt_counts[b] += 1
                    if not (buckets & {"PT Erfi", "PT Heka"}):
                        pt_counts[""] += 1  # PO tanpa item -> tidak punya PT
            except Exception as ex:
                print(f"[PO] gagal ambil nama produk: {ex}")

        # Filter perusahaan. PO tanpa item TIDAK punya perusahaan, jadi saat
        # filter PT aktif PO seperti itu ikut tersaring — itulah sebabnya
        # opsi "Tanpa item" disediakan di dropdown.
        pt_scope_total = len(pos)
        if pt == PO_NO_ITEMS:
            pos = [p for p in pos
                   if not ((po_companies.get(p.get("id")) or set()) & {"PT Erfi", "PT Heka"})]
        elif pt:
            pos = [p for p in pos if pt in (po_companies.get(p.get("id")) or set())]
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
            # Filter perusahaan (PT Erfi / PT Heka)
            "pt": pt, "pt_counts": pt_counts, "po_prod_by_pt": po_prod_by_pt,
            "pt_scope_total": pt_scope_total,
        }
        resp = templates.TemplateResponse(request=request, name="purchase_orders.html", context=ctx)
        # Simpan filter aktif di cookie supaya redirect 303 setelah simpan/hapus
        # item tidak menghapus pilihan tahun/kuartal/perusahaan user.
        resp.set_cookie(
            PO_FILTER_COOKIE,
            f"{PO_ALL_YEARS if tahun is None else tahun}:{qtr or ''}:{pt or ''}",
            max_age=60 * 60 * 24 * 180, httponly=False, samesite="lax", path="/",
        )
        if s_msg:
            resp.delete_cookie("success_msg")
        if e_msg:
            resp.delete_cookie("error_msg")
        return resp

    # ======================================================================
    # /po-analytics — rekap jumlah PO per kuartal + top produk
    # Sengaja TIDAK di bawah /purchase-orders/... supaya tidak ikut menyalakan
    # menu "Produksi" di sidebar (nav_active cocok by prefix URL).
    # ======================================================================
    @app.get("/po-analytics", response_class=HTMLResponse)
    async def po_analytics_page(request: Request, current_user: dict = Depends(get_current_user)):
        raw_tahun = request.query_params.get("tahun")
        tab = (request.query_params.get("tab") or "all").strip().lower()
        if tab not in PO_ANALYTICS_TABS:
            tab = "all"
        # Kuartal opsional untuk membatasi DUA daftar top. KPI & chart per kuartal
        # tetap memakai seluruh tahun supaya konteksnya tidak hilang.
        qtr = _clean_qtr(request.query_params.get("qtr"))
        sort = (request.query_params.get("sort") or "pcs").strip().lower()
        if sort not in ("pcs", "po"):
            sort = "pcs"

        # Kolom jenis_po ditambahkan lewat migration manual, jadi dicek sekali
        # lebih dulu: kalau belum ada, PostgREST akan menolak query yang
        # menyebutnya dan seluruh halaman ikut gagal.
        jenis_ok = _jenis_po_available()
        po_cols = "id, no_po, tanggal_po, qty_pcs" + (", jenis_po" if jenis_ok else "")

        pos, item_rows, prod_rows = [], [], []
        years = []
        warnings = []

        # Tahun yang punya data, untuk mengisi dropdown.
        try:
            yr = supabase.table("purchase_orders").select("tanggal_po") \
                .order("tanggal_po", desc=True).limit(_PO_STATS_LIMIT).execute().data or []
            per_year = {}
            for r in yr:
                y = _year_of(r.get("tanggal_po"))
                if y:
                    per_year[y] = per_year.get(y, 0) + 1
            years = sorted(per_year.items(), key=lambda kv: kv[0], reverse=True)
        except Exception as ex:
            print(f"[PO] gagal ambil daftar tahun: {ex}")
            warnings.append("Gagal memuat daftar tahun PO.")

        tahun = _clean_tahun(raw_tahun)
        if tahun is None and years:
            tahun = years[0][0]

        if tahun is not None:
            try:
                pos = _apply_po_range(
                    supabase.table("purchase_orders").select(po_cols)
                    .order("tanggal_po", desc=True).limit(_PO_STATS_LIMIT),
                    tahun, None).execute().data or []
            except Exception as ex:
                print(f"[PO] analytics list gagal: {ex}")
                warnings.append("Gagal memuat daftar PO.")
            try:
                # "!inner" wajib: tanpa itu, filter tanggal hanya membatasi
                # resource yang di-embed dan item dari PO tahun lain ikut masuk.
                item_rows = supabase.table("purchase_order_items") \
                    .select("purchase_order_id, product_id, purchase_orders!inner(id)") \
                    .gte("purchase_orders.tanggal_po", f"{tahun:04d}-01-01") \
                    .lt("purchase_orders.tanggal_po", f"{tahun + 1:04d}-01-01") \
                    .limit(_PO_STATS_LIMIT).execute().data or []
            except Exception as ex:
                print(f"[PO] analytics item gagal: {ex}")
                warnings.append("Gagal memuat item PO per produk.")
            try:
                prod_rows = supabase.table("products").select(
                    "id, nama_produk, perusahaan, is_deleted, laporan_uji_sig_file_url"
                ).limit(_PO_STATS_LIMIT).execute().data or []
            except Exception as ex:
                print(f"[PO] analytics produk gagal: {ex}")
                warnings.append("Gagal memuat master produk.")

        ana = _build_po_analytics(pos, item_rows, prod_rows, tahun, qtr=qtr, sort=sort)

        ctx = {
            "current_user": current_user,
            "tahun": tahun,
            "years": years,
            "tab": tab,
            "tabs": PO_ANALYTICS_TABS,
            "qtr": qtr,
            "sort": sort,
            "jenis_po_aktif": jenis_ok,
            "ana": ana,
            "warnings": warnings,
            # Payload ringkas khusus chart. Diseric ke template sebagai dict lalu
            # di-escape oleh filter tojson, jadi tidak pernah jadi HTML mentah.
            "ana_charts": {
                "qLabels": ["Q1", "Q2", "Q3", "Q4"],
                "qPo": ana["q_po"],
                "qPcs": [int(v) for v in ana["q_pcs"]],
                "qtr": ana["qtr"],
                "sort": ana["sort"],
                "companies": ana["companies"],
                "companyPo": {c: ana["per_company"][c]["q_po"] for c in ana["companies"]},
                # qty_pcs per kuartal per perusahaan untuk chart gabungan
                # (batang = jumlah PO, garis = qty pcs, sumbu kanan).
                "companyPcs": {c: [int(v) for v in ana["per_company"][c]["q_pcs"]]
                               for c in ana["companies"]},
                "companyTotals": {c: ana["per_company"][c]["po"] for c in ana["companies"]},
                "companyZero": [c for c in ana["companies"] if not ana["per_company"][c]["po"]],
                "topLabels": [r["nama"] for r in ana["top"].get(tab, [])],
                "topValues": [int(r["pcs"]) for r in ana["top"].get(tab, [])],
                "topPo": [r["po_count"] for r in ana["top"].get(tab, [])],
                "missingLabels": [r["nama"] for r in ana["missing"].get(tab, [])],
                "missingValues": [int(r["pcs"]) for r in ana["missing"].get(tab, [])],
                "missingPo": [r["po_count"] for r in ana["missing"].get(tab, [])],
            },
            "ed_notification_count": await _ed_count(),
        }
        return templates.TemplateResponse(request=request, name="po_analytics.html", context=ctx)

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
