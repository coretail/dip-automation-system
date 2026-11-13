"""Logika notifikasi ED/NA — MURNI, tanpa import supabase/DB.

Satu sumber kebenaran untuk badge (main.get_ed_notification_count) dan
endpoint (/api/ed-notifications di presence_routes.py).

Diterima sebagai parameter:
- ``rows_batch``: baris raw_material_batches (id, tanggal_ed, status_ed,
  no_batch, perusahaan, raw_materials embed) — hasil paginate_all.
- ``rows_product``: baris products (id, nama_produk, no_na_produk,
  tanggal_aktif_na, status_na) — hasil paginate_all.
- ``today``: date WIB hari ini.
- ``compute_status_na``: fungsi (tanggal_aktif_na, fallback_status) ->
  (status, days_remaining). Di-inject karena import dari app.main memicu
  env_guard; caller sudah punya referensi fungsi ini.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable, Optional, Tuple


def critical_ed_items(rows_batch: list, today: date) -> list[dict]:
    """Filter batch dengan tanggal_ed <= 180 hari dan status_ed != Dimusnahkan.

    Status_ed di-derivasikan:
    - days <= 0 dan status_ed == "Active" -> "Expired"
    - 0 < days <= 180 dan status_ed == "Active" -> "Kritis (<= 180 hari)"
    - selain itu pakai status_ed yang ada (fallback "Active" jika kosong).

    Filter Dimusnahkan dilakukan di sini (sisi Python) supaya caller bisa
    mengirim baris tanpa .neq() di query — satu sumber kebenaran dengan
    endpoint /api/ed-notifications.
    """
    items = []
    for batch in rows_batch or []:
        if str(batch.get("status_ed") or "").strip() == "Dimusnahkan":
            continue
        tanggal_ed = batch.get("tanggal_ed")
        if not tanggal_ed:
            continue
        try:
            if isinstance(tanggal_ed, str):
                ed_date = datetime.strptime(tanggal_ed[:10], "%Y-%m-%d").date()
            elif isinstance(tanggal_ed, datetime):
                ed_date = tanggal_ed.date()
            elif isinstance(tanggal_ed, date):
                ed_date = tanggal_ed
            else:
                continue
        except Exception:
            continue
        days_remaining = (ed_date - today).days
        if days_remaining > 180:
            continue
        status_ed = batch.get("status_ed") or "Active"
        if days_remaining <= 0 and status_ed == "Active":
            status_ed = "Expired"
        elif status_ed == "Active":
            status_ed = "Kritis (<= 180 hari)"
        rm_embed = batch.get("raw_materials")
        if isinstance(rm_embed, list):
            rm_embed = rm_embed[0] if rm_embed else None
        items.append({
            "id": batch.get("id"),
            "raw_material_id": batch.get("raw_material_id"),
            "no_batch": batch.get("no_batch"),
            "perusahaan": batch.get("perusahaan"),
            "tanggal_ed": tanggal_ed,
            "days_remaining": days_remaining,
            "status_ed": status_ed,
            "nama_dagang": (rm_embed or {}).get("nama_dagang", "Unknown"),
            "kode_bahan_baku": (rm_embed or {}).get("kode_bahan_baku", ""),
        })
    items.sort(key=lambda x: x["days_remaining"])
    return items


def critical_na_items(rows_product: list,
                      compute_status_na: Callable) -> list[dict]:
    """Filter produk dengan status NA akan_expired/expired via compute_status_na.

    TANPA filter status_na di query (keputusan N-02): compute_status_na bisa
    menghitung dari tanggal_aktif_na meski status_na manual berbeda.
    """
    items = []
    for p in rows_product or []:
        status_na, days_remaining = compute_status_na(
            p.get("tanggal_aktif_na"), p.get("status_na") or "belum_terdaftar"
        )
        if status_na in ("akan_expired", "expired"):
            items.append({
                "id": p.get("id"),
                "nama_produk": p.get("nama_produk"),
                "no_na_produk": p.get("no_na_produk"),
                "days_remaining": days_remaining if days_remaining is not None else 0,
                "status_na": status_na,
            })
    return items


def ed_notifications(rows_batch: list, rows_product: list, today: date,
                    compute_status_na: Callable) -> Tuple[list, list]:
    """Gabungan: return (critical_batches, na_items). Satu sumber kebenaran."""
    return critical_ed_items(rows_batch, today), critical_na_items(rows_product, compute_status_na)
