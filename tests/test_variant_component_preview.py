"""Pure-local tests for variant composition preview helpers and endpoint.

Jalankan: `python tests/test_variant_component_preview.py`.
Tidak ada koneksi Supabase/jaringan; route memakai fake client.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.variant_components import (  # noqa: E402
    build_preview,
    normalize_components,
    normalize_variants,
    prepare_line_preview,
    sort_components,
)
import app.raw_materials_routes as raw_materials_routes  # noqa: E402


class FakeApp:
    def __init__(self):
        self.routes = {}

    def get(self, path, **kwargs):
        def decorator(fn):
            self.routes[("GET", path)] = fn
            return fn
        return decorator

    def post(self, path, **kwargs):
        def decorator(fn):
            self.routes[("POST", path)] = fn
            return fn
        return decorator


class Query:
    def __init__(self, data):
        self.data = data
        self.select_args = None
        self.filters = []
        self.order_args = None
        self.is_args = []
        self.executed = False

    def select(self, *args):
        self.select_args = args
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, *args, **kwargs):
        self.order_args = (args, kwargs)
        return self

    def is_(self, key, value):
        self.is_args.append((key, value))
        return self

    def execute(self):
        self.executed = True
        return SimpleNamespace(data=self.data)


class FakeSupabase:
    def __init__(self, variant_rows, legacy_rows=None):
        self.variant_query = Query(variant_rows)
        self.legacy_query = Query(legacy_rows or [])
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        if name == "raw_material_composition_variants":
            return self.variant_query
        if name == "raw_material_components":
            return self.legacy_query
        raise AssertionError(f"Unexpected table: {name}")


def build_app(fake_supabase):
    async def get_current_user(_request=None):
        return {"id": "user-1"}

    app = FakeApp()
    raw_materials_routes.supabase = fake_supabase
    raw_materials_routes.register_raw_materials_routes(
        app,
        get_current_user,
        lambda *args, **kwargs: None,
        SimpleNamespace(TemplateResponse=lambda **kwargs: kwargs),
        lambda *args, **kwargs: None,
        lambda raw_material, variant_id: [],
        lambda *args, **kwargs: None,
        lambda *args, **kwargs: False,
        lambda *args, **kwargs: None,
        lambda url: (None, None),
        None,
    )
    return app


def call_variants_endpoint(fake_supabase, include=None):
    app = build_app(fake_supabase)
    endpoint = app.routes[("GET", "/raw-materials/{rm_id}/variants")]
    response = asyncio.run(endpoint("rm-1", include, {"id": "user-1"}))
    return json.loads(response.body)


def test_endpoint_without_include_is_unchanged():
    variant_rows = [
        {"id": "v1", "nama_varian": "Default", "is_default": True},
        {"id": "v2", "nama_varian": "Produsen B", "is_default": False},
    ]
    fake = FakeSupabase(variant_rows)
    payload = call_variants_endpoint(fake)

    assert payload == {"success": True, "variants": variant_rows}
    assert fake.variant_query.select_args == ("id, nama_varian, is_default",)
    assert fake.legacy_query.executed is False
    assert fake.variant_query.filters == [("raw_material_id", "rm-1")]
    print("[PASS] endpoint tanpa include mempertahankan respons lama")


def test_endpoint_with_include_returns_sorted_components():
    variant_rows = [
        {
            "id": "v2",
            "nama_varian": "B",
            "is_default": False,
            "raw_material_components": [
                {"inci_name": "Water", "function": "Solvent", "percent_internal": 70, "is_bahan_aktif": False},
                {"inci_name": "Glycerin", "function": "Humectant", "percent_internal": "30.0", "is_bahan_aktif": True},
            ],
        },
        {
            "id": "v1",
            "nama_varian": "A",
            "is_default": True,
            "raw_material_components": {
                "inci_name": "Only",
                "function": None,
                "percent_internal": None,
                "is_bahan_aktif": False,
            },
        },
    ]
    fake = FakeSupabase(variant_rows, [{"inci_name": "ignored", "percent_internal": 1}])
    payload = call_variants_endpoint(fake, "components")

    assert payload["success"] is True
    assert payload["legacy_components"] == []
    assert fake.legacy_query.executed is False
    assert [v["id"] for v in payload["variants"]] == ["v2", "v1"]
    assert [c["inci_name"] for c in payload["variants"][0]["components"]] == ["Water", "Glycerin"]
    assert payload["variants"][0]["component_count"] == 2
    assert payload["variants"][1]["components"][0]["inci_name"] == "Only"
    assert "raw_material_components" not in payload["variants"][0]
    print("[PASS] endpoint include=components mengembalikan komponen terurut")


def test_endpoint_legacy_components_only_without_variants():
    legacy_rows = [
        {"inci_name": "B", "function": None, "percent_internal": "5.0", "is_bahan_aktif": False},
        {"inci_name": "A", "function": None, "percent_internal": 10, "is_bahan_aktif": True},
    ]
    fake = FakeSupabase([], legacy_rows)
    payload = call_variants_endpoint(fake, "components")

    assert payload["variants"] == []
    assert [c["inci_name"] for c in payload["legacy_components"]] == ["A", "B"]
    assert fake.legacy_query.executed is True
    assert fake.legacy_query.is_args == [("variant_id", None)]
    print("[PASS] legacy_components hanya diambil saat bahan baku tanpa varian")


def test_component_sorting_is_none_safe_and_numeric():
    components = [
        {"inci_name": "B", "percent_internal": None},
        {"inci_name": "A", "percent_internal": "10.5"},
        {"inci_name": "C", "percent_internal": 10.5},
        {"inci_name": "D", "percent_internal": Decimal("20.25")},
    ]
    ordered = sort_components(components)
    assert [c["inci_name"] for c in ordered] == ["D", "A", "C", "B"]
    print("[PASS] urutan komponen deterministik untuk None/string/numeric")


def test_dict_and_list_embed_normalization():
    raw_material = {
        "raw_material_composition_variants": {
            "id": "v1",
            "nama_varian": "Tunggal",
            "is_default": True,
            "raw_material_components": {
                "inci_name": "Water",
                "function": "Solvent",
                "percent_internal": 100,
                "is_bahan_aktif": False,
            },
        },
        "raw_material_components": {"inci_name": "Legacy", "variant_id": None, "percent_internal": 1},
    }
    variants, preview = prepare_line_preview(raw_material, None)

    assert len(variants) == 1
    assert variants[0]["component_count"] == 1
    assert variants[0]["components"][0]["inci_name"] == "Water"
    assert preview["has_variants"] is True
    assert preview["selected_variant_name"] == "Tunggal"
    assert preview["uses_legacy"] is False
    assert preview["legacy_count"] == 0

    list_form = [raw_material]
    variants_list, preview_list = prepare_line_preview(list_form, "v1")
    assert variants_list[0]["id"] == "v1"
    assert preview_list["selected_variant_id"] == "v1"

    assert normalize_components({"inci_name": "X"} )[0]["inci_name"] == "X"
    assert normalize_variants([{"id": "v9", "components": [{"inci_name": "Y"}]}])[0]["components"][0]["inci_name"] == "Y"
    print("[PASS] normalisasi embed dict/list untuk varian dan komponen")


def test_legacy_fallback_only_without_variants_and_filters_variant_rows():
    direct = [
        {"inci_name": "Langsung", "variant_id": None, "percent_internal": 60},
        {"inci_name": "Milik varian", "variant_id": "v1", "percent_internal": 40},
    ]
    variants, preview = prepare_line_preview(
        {
            "raw_material_composition_variants": [],
            "raw_material_components": direct,
        },
        None,
    )
    assert variants == []
    assert preview["uses_legacy"] is True
    assert preview["legacy_count"] == 1
    assert preview["legacy_components"][0]["inci_name"] == "Langsung"

    variants_with_data, preview_with_data = prepare_line_preview(
        {
            "raw_material_composition_variants": [
                {"id": "v1", "nama_varian": "A", "is_default": True, "raw_material_components": []},
            ],
            "raw_material_components": direct,
        },
        None,
    )
    assert len(variants_with_data) == 1
    assert preview_with_data["uses_legacy"] is False
    assert preview_with_data["legacy_components"] == []

    legacy_preview = build_preview([], direct, None)
    assert legacy_preview["legacy_count"] == 2
    print("[PASS] fallback komponen langsung hanya saat tidak ada varian")


def test_selected_variant_rule_matches_dropdown_order():
    variants = [
        {"id": "v2", "nama_varian": "Zeta", "is_default": False, "raw_material_components": []},
        {"id": "v1", "nama_varian": "Alpha", "is_default": True, "raw_material_components": []},
    ]
    _, explicit = prepare_line_preview(
        {"raw_material_composition_variants": variants}, "v2"
    )
    _, defaulted = prepare_line_preview(
        {"raw_material_composition_variants": variants}, None
    )
    no_default = [
        {"id": "v3", "nama_varian": "Beta", "is_default": False, "raw_material_components": []},
        {"id": "v4", "nama_varian": "Alpha", "is_default": False, "raw_material_components": []},
    ]
    _, first = prepare_line_preview(
        {"raw_material_composition_variants": no_default}, None
    )

    assert explicit["selected_variant_id"] == "v2"
    assert defaulted["selected_variant_id"] == "v1"
    assert first["selected_variant_id"] == "v4"
    print("[PASS] varian terpilih mengikuti variant_id -> default -> urutan dropdown")


def test_server_template_escapes_component_text():
    source = (ROOT / "app" / "templates" / "edit_product.html").read_text(encoding="utf-8")
    match = re.search(
        r"\{% macro variant_preview_card\(preview\) %\}.*?\{% endmacro %\}",
        source,
        flags=re.DOTALL,
    )
    assert match, "macro variant_preview_card tidak ditemukan"
    macro_source = match.group(0)

    from jinja2 import Environment
    env = Environment(autoescape=True)
    template = env.from_string(macro_source + "\n{{ variant_preview_card(preview) }}")

    variants = [
        {
            "id": "v1",
            "nama_varian": "<script>alert('varian')</script>",
            "is_default": True,
            "raw_material_components": [
                {
                    "inci_name": "<script>alert('inci')</script>",
                    "function": "<b>fungsi</b>",
                    "percent_internal": 100,
                    "is_bahan_aktif": True,
                }
            ],
        }
    ]
    _, preview = prepare_line_preview(
        {"raw_material_composition_variants": variants}, "v1"
    )
    rendered = template.render(preview=preview)

    assert "<script>" not in rendered
    assert "<b>fungsi</b>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "&lt;b&gt;fungsi&lt;/b&gt;" in rendered
    print("[PASS] teks komponen di-escape oleh autoescape Jinja")


def main() -> int:
    test_endpoint_without_include_is_unchanged()
    test_endpoint_with_include_returns_sorted_components()
    test_endpoint_legacy_components_only_without_variants()
    test_component_sorting_is_none_safe_and_numeric()
    test_dict_and_list_embed_normalization()
    test_legacy_fallback_only_without_variants_and_filters_variant_rows()
    test_selected_variant_rule_matches_dropdown_order()
    test_server_template_escapes_component_text()
    print("All variant composition preview tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
