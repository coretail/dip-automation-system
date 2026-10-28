"""Helper murni untuk preview komposisi varian bahan baku.

Modul ini dipakai oleh halaman edit produk dan endpoint daftar varian supaya
urutan komponen, pemilihan varian tampilan, dan bentuk preview konsisten.
Tidak ada akses database/jaringan di sini.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

PREVIEW_LIMIT = 5
ZERO = Decimal("0")


def as_component_list(value) -> list:
    """Normalisasi embed komponen PostgREST (dict, list, None) jadi list of dict."""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def as_variant_list(value) -> list:
    """Normalisasi embed varian PostgREST (dict, list, None) jadi list of dict."""
    return as_component_list(value)


def percent_value(value) -> Decimal:
    """Konversi persentase ke Decimal tanpa melempar error.

    None/string kosong dianggap 0; string numerik dan tipe numerik diterima.
    Nilai yang tidak bisa diparse juga dianggap 0 supaya halaman tetap tampil.
    """
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ZERO
        value = text
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return ZERO
    return parsed if parsed.is_finite() else ZERO


def sort_components(components) -> list:
    """Urutkan komponen: percent_internal descending, lalu inci_name ascending."""
    rows = as_component_list(components)
    return sorted(
        rows,
        key=lambda comp: (
            -percent_value(comp.get("percent_internal")),
            str(comp.get("inci_name") or ""),
        ),
    )


def normalize_components(components) -> list:
    """Return komponen terurut dengan field preview yang aman.

    Field database dipertahankan apa adanya; hanya urutan yang diubah.
    """
    return sort_components(components)


def normalize_variants(raw_variants) -> list:
    """Normalisasi varian beserta komponennya.

    Setiap varian mendapat kunci ``components`` (list terurut) dan
    ``component_count``. Urutan daftar varian TIDAK diubah di sini; pemanggil
    yang mengurutkan sesuai urutan dropdown (default dulu, lalu nama).
    """
    variants = []
    for raw in as_variant_list(raw_variants):
        variant = dict(raw)
        raw_components = variant.get("raw_material_components")
        if raw_components is None:
            raw_components = variant.get("components")
        components = normalize_components(raw_components)
        variant.pop("raw_material_components", None)
        variant["components"] = components
        variant["component_count"] = len(components)
        variants.append(variant)
    return variants


def dropdown_variants(variants) -> list:
    """Urutan dropdown: varian default lebih dulu, lalu nama varian."""
    return sorted(
        normalize_variants(variants),
        key=lambda variant: (
            not bool(variant.get("is_default")),
            str(variant.get("nama_varian") or ""),
        ),
    )


def choose_display_variant(variants, variant_id):
    """Aturan pemilihan varian yang ditampilkan pada preview.

    1. variant_id eksplisit kalau cocok.
    2. Varian is_default.
    3. Varian pertama pada urutan dropdown.
    4. None kalau tidak ada varian.

    Catatan: ``_resolve_variant_components`` di main.py memakai urutan embed
    mentah, sedangkan dropdown dan preview memakai urutan tampilan (default
    dulu, lalu nama). Perbedaannya hanya terlihat pada data korup yang tidak
    punya varian default.
    """
    if not variants:
        return None
    if variant_id:
        for variant in variants:
            if str(variant.get("id")) == str(variant_id):
                return variant
    for variant in variants:
        if variant.get("is_default"):
            return variant
    return variants[0]


def _preview_block(components) -> dict:
    ordered = normalize_components(components)
    return {
        "components": ordered[:PREVIEW_LIMIT],
        "component_count": len(ordered),
        "remaining_count": max(len(ordered) - PREVIEW_LIMIT, 0),
    }


def prepare_line_preview(raw_material, variant_id):
    """Normalisasi embed raw_materials satu baris formula jadi (variants, preview).

    Komponen langsung hanya dipakai kalau bahan baku belum punya varian.
    """
    rm = raw_material
    if isinstance(rm, list):
        rm = rm[0] if rm else None
    if not isinstance(rm, dict):
        rm = {}

    variants = dropdown_variants(rm.get("raw_material_composition_variants"))
    direct_components = normalize_components(rm.get("raw_material_components"))
    legacy_components = []
    if not variants:
        legacy_components = [
            comp for comp in direct_components
            if comp.get("variant_id") is None
        ]
    return variants, build_preview(variants, legacy_components, variant_id)


def build_preview(variants, legacy_components, variant_id) -> dict:
    """Bangun struktur preview yang dipakai template dan JavaScript.

    ``variants`` harus sudah berupa list varian hasil :func:`normalize_variants`
    (boleh belum terurut; fungsi ini mengurutkan ulang sesuai dropdown).
    ``legacy_components`` hanya dipakai bila tidak ada varian sama sekali.
    """
    ordered_variants = dropdown_variants(variants)
    chosen = choose_display_variant(ordered_variants, variant_id)

    if chosen is not None:
        block = _preview_block(chosen.get("components"))
        return {
            "has_variants": True,
            "variant_count": len(ordered_variants),
            "selected_variant_id": chosen.get("id"),
            "selected_variant_name": chosen.get("nama_varian"),
            "selected_is_default": bool(chosen.get("is_default")),
            "preview_components": block["components"],
            "component_count": block["component_count"],
            "remaining_count": block["remaining_count"],
            "uses_legacy": False,
            "legacy_components": [],
            "legacy_count": 0,
            "legacy_remaining_count": 0,
        }

    legacy = normalize_components(legacy_components)
    return {
        "has_variants": False,
        "variant_count": 0,
        "selected_variant_id": None,
        "selected_variant_name": None,
        "selected_is_default": False,
        "preview_components": [],
        "component_count": 0,
        "remaining_count": 0,
        "uses_legacy": True,
        "legacy_components": legacy[:PREVIEW_LIMIT],
        "legacy_count": len(legacy),
        "legacy_remaining_count": max(len(legacy) - PREVIEW_LIMIT, 0),
    }
