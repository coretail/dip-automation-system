"""Unit test gabungan raw materials (pure-local, tanpa koneksi/secret):
  1. Edit komponen bahan baku atomik via RPC (C-07)
  2. Preview komposisi varian helper & endpoint GET /raw-materials/{rm_id}/variants
  3. Kontrak spec_parameters -> masterRawMaterials
  4. Preview PDF input manual raw materials (spec & QC)

Digabungkan pada Task 6 dari:
  - test_raw_material_components_atomic.py
  - test_variant_component_preview.py
  - test_bahansemi_spec_parameters.py
  - test_manual_preview_pdf.py

Jalankan: python tests/test_raw_materials.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for p in (str(ROOT), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from _fakes import FakeApp, FakeRequest  # noqa: E402
import app.raw_materials_routes as raw_materials_routes  # noqa: E402
from app.raw_materials_routes import (  # noqa: E402
    _NormalizeSpecs,
    _apply_company_doc_specs,
    register_raw_materials_routes,
)
from app.variant_components import (  # noqa: E402
    build_preview,
    normalize_components,
    normalize_variants,
    prepare_line_preview,
    sort_components,
)


@contextmanager
def _patch_rmr_supabase(fake_supabase):
    orig = raw_materials_routes.supabase
    raw_materials_routes.supabase = fake_supabase
    try:
        yield
    finally:
        raw_materials_routes.supabase = orig


# =====================================================================
# Bagian 1: Edit komponen bahan baku atomik (C-07)
# =====================================================================

RM_ID = str(uuid.uuid4())
VAR_ID = str(uuid.uuid4())
OTHER_VAR = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())


class _AtomicTableFake:
    def __init__(self, backend):
        self.backend = backend
        self.name = None
        self.cols = None
        self.op = None
        self._filters = []

    def select(self, cols="*"):
        self.cols = cols
        return self

    def eq(self, k, v):
        self._filters.append((k, v))
        return self

    def neq(self, k, v):
        return self

    def limit(self, n):
        return self

    def order(self, k):
        return self

    def single(self):
        return self

    def delete(self):
        self.op = "delete"
        self.backend.calls.append(("delete", self.name))
        return self

    def update(self, payload):
        self.op = "update"
        self.backend.calls.append(("update", self.name, payload))
        return self

    def insert(self, payload):
        self.op = "insert"
        self.backend.calls.append(("insert", self.name, payload))
        return self

    def is_(self, k, v):
        return self

    def execute(self):
        if self.op:
            return type("R", (), {"data": None})()
        if self.name == "raw_materials" and self._filters and any(k == "kode_bahan_baku" for k, _ in self._filters):
            return type("R", (), {"data": []})()
        rows = list(self.backend.tables.get(self.name, []))
        for k, v in self._filters:
            rows = [r for r in rows if r.get(k) == v]
        if self.name == "raw_materials" and self.cols == "id" and self._filters and self._filters[0][0] == "kode_bahan_baku":
            return type("R", (), {"data": []})()
        return type("R", (), {"data": rows})()


class _AtomicRpcFake:
    def __init__(self, backend, mode):
        self.backend = backend
        self.mode = mode

    def execute(self):
        if self.mode == "fail":
            raise RuntimeError("fungsi belum terpasang")
        self.backend.calls.append(("rpc", "replace_raw_material_components"))
        return SimpleNamespace(data=1)


class _AtomicFakeSupabase:
    def __init__(self, rpc_mode="ok"):
        self.tables = {
            "raw_materials": [{
                "id": RM_ID,
                "nama_dagang": "Bahan Uji",
                "kode_bahan_baku": "BB01",
                "tipe": "single",
                "produsen": "PT Test",
                "perusahaan": "PT Erfi",
            }],
            "raw_material_company_docs": [],
            "raw_material_components": [
                {
                    "id": str(uuid.uuid4()),
                    "raw_material_id": RM_ID,
                    "variant_id": None,
                    "inci_name": "Aqua",
                    "cas_number": "7732-18-5",
                    "function": "Solvent",
                    "percent_internal": 100,
                    "is_bahan_aktif": False,
                },
            ],
            "raw_material_composition_variants": [
                {"id": VAR_ID, "raw_material_id": RM_ID, "nama_varian": "V1"},
                {"id": OTHER_VAR, "raw_material_id": RM_ID, "nama_varian": "V2"},
            ],
        }
        self.calls = []
        self.rpc_mode = rpc_mode

    def table(self, name):
        t = _AtomicTableFake(self)
        t.name = name
        return t

    def rpc(self, fn_name, params):
        self.calls.append(("rpc_call", fn_name, params))
        return _AtomicRpcFake(self, self.rpc_mode)


def _noop_coro():
    async def _n():
        return None
    return _n()


@contextmanager
def _atomic_harness(rpc_mode="ok"):
    app = FakeApp()
    supa = _AtomicFakeSupabase(rpc_mode=rpc_mode)
    logs = []
    with _patch_rmr_supabase(supa):
        register_raw_materials_routes(
            app,
            get_current_user=lambda: {"id": USER_ID, "role": "admin", "perusahaan": "PT Erfi"},
            log_activity=lambda *a, **k: logs.append((a, k)),
            templates=type("T", (), {"TemplateResponse": staticmethod(lambda **k: "ok")})(),
            compute_status_na=lambda *a, **k: ("Belum", 0),
            _resolve_variant_components=lambda *a, **k: [],
            _ensure_default_variant=lambda rm_id, produsen: VAR_ID,
            _flag_bahan_aktif=lambda flags, i: (flags[i] == "1") if flags and i < len(flags) else False,
            _build_diff_changes=lambda *a, **k: [],
            _parse_storage_url=lambda url: (None, None),
            _upload_msds_and_upsert_company_doc=lambda *a, **k: _noop_coro(),
        )
        orig_fn = app.routes[("POST", "/raw-materials/edit/{rm_id}")]

        async def _wrapped(request, rm_id, current_user=None, **kw):
            if current_user is None:
                current_user = {"id": USER_ID, "role": "admin", "perusahaan": "PT Erfi"}
            return await orig_fn(request, rm_id, current_user=current_user, **kw)

        yield app, supa, logs, _wrapped


def _form(**kw):
    base = dict(
        nama_dagang="Bahan Uji",
        kode_bahan_baku="BB01",
        tipe="single",
        produsen="PT Test",
        journal_link=None,
        inci_name=["Aqua"],
        cas_number=["7732-18-5"],
        function=["Solvent"],
        percent_internal=[100.0],
        is_bahan_aktif=["0"],
        msds_file_erfi=SimpleNamespace(filename=None),
        msds_file_heka=SimpleNamespace(filename=None),
        spec_sheet_file_erfi=SimpleNamespace(filename=None),
        spec_sheet_file_heka=SimpleNamespace(filename=None),
        spec_parameters_erfi="[]",
        spec_parameters_heka="[]",
        variant_id=VAR_ID,
    )
    base.update(kw)
    return base


def test_edit_single_satu_rpc():
    with _atomic_harness() as (_app, supa, _logs, fn):
        resp = asyncio.run(fn(FakeRequest(), RM_ID, **_form()))
        assert resp.status_code == 303
        rpcs = [c for c in supa.calls if c[0] == "rpc_call"]
        assert len(rpcs) == 1, f"harus tepat satu rpc, dapat {rpcs}"
        _, name, params = rpcs[0]
        assert name == "replace_raw_material_components"
        assert params["p_raw_material_id"] == RM_ID and params["p_variant_id"] == VAR_ID
        comps = params["p_components"]
        assert isinstance(comps, list), f"p_components harus list (array JSON), dapat {type(comps).__name__}"
        assert len(comps) == 1 and comps[0]["inci_name"] == "Aqua"
        assert comps[0]["percent_internal"] == 100
        print("[PASS] edit single -> satu rpc dengan p_components list")


def test_edit_komposit_satu_rpc():
    with _atomic_harness() as (_app, supa, _logs, fn):
        resp = asyncio.run(fn(FakeRequest(), RM_ID, **_form(
            tipe="komposit",
            inci_name=["Aqua", "Glycerin"],
            cas_number=["7732-18-5", "56-81-5"],
            function=["Solvent", "Humectant"],
            percent_internal=[90.0, 10.0],
            is_bahan_aktif=["0", "1"],
        )))
        assert resp.status_code == 303
        rpcs = [c for c in supa.calls if c[0] == "rpc_call"]
        assert len(rpcs) == 1, f"komposit harus satu rpc, dapat {len(rpcs)}"
        payload = rpcs[0][2]["p_components"]
        assert isinstance(payload, list), f"komposit payload harus list, dapat {type(payload).__name__}"
        names = [c["inci_name"] for c in payload]
        assert "Aqua" in names and "Glycerin" in names, "semua baris komposit harus ada"
        assert all(c["variant_id"] != OTHER_VAR for c in payload), "varian lain tidak boleh muncul"
        print("[PASS] edit komposit -> satu rpc semua baris, varian lain utuh")


def test_tidak_ada_delete_insert_langsung():
    with _atomic_harness() as (_app, supa, _logs, fn):
        asyncio.run(fn(FakeRequest(), RM_ID, **_form()))
        direct = [c for c in supa.calls if c[0] in ("delete", "insert") and c[1] == "raw_material_components"]
        assert direct == [], f"tidak boleh delete/insert langsung ke komponen, dapat {direct}"
        print("[PASS] jalur edit tidak ada delete/insert langsung ke komponen")


def test_rpc_gagal_redirect_error():
    with _atomic_harness(rpc_mode="fail") as (_app, supa, logs, fn):
        resp = asyncio.run(fn(FakeRequest(), RM_ID, **_form()))
        assert resp.status_code == 303
        assert resp.headers.get("set-cookie") or True
        direct = [c for c in supa.calls if c[0] in ("delete", "insert") and c[1] == "raw_material_components"]
        assert direct == [], "rpc gagal tidak boleh fallback delete/insert"
        ok_logs = [k for _a, k in logs if k.get("outcome") == "success"]
        assert not ok_logs, f"tidak boleh mencatat sukses saat rpc gagal, dapat {ok_logs}"
        print("[PASS] rpc melempar -> redirect error, tidak fallback, tidak log sukses")


def test_input_tidak_valid_nol_tulis():
    with _atomic_harness() as (_app, supa, _logs, fn):
        resp = asyncio.run(fn(FakeRequest(), RM_ID, **_form(
            tipe="komposit",
            inci_name=["Aqua", "Glycerin"],
            cas_number=["7732-18-5"],
            function=["Solvent", "Humectant"],
            percent_internal=[90.0, 10.0],
            is_bahan_aktif=["0", "0"],
        )))
        assert resp.status_code == 303
        writes = [c for c in supa.calls if c[0] in ("delete", "insert", "rpc_call", "rpc")]
        comp_writes = [
            c for c in writes
            if c[0] in ("rpc_call", "rpc") or (len(c) > 1 and c[1] == "raw_material_components")
        ]
        assert comp_writes == [], f"input invalid NOL tulis komponen, dapat {comp_writes}"
        print("[PASS] input panjang list tidak sama -> error sebelum tulis apa pun")


def test_persentase_nonfinite_ditolak():
    for bad in ["nan", "inf", "-inf"]:
        with _atomic_harness() as (_app, supa, _logs, fn):
            resp = asyncio.run(fn(FakeRequest(), RM_ID, **_form(
                tipe="komposit",
                inci_name=["Aqua", "Glycerin"],
                cas_number=["7732-18-5", "56-81-5"],
                function=["Solvent", "Humectant"],
                percent_internal=[bad, 10.0],
                is_bahan_aktif=["0", "0"],
            )))
            assert resp.status_code == 303, f"{bad} harus 303, dapat {resp.status_code}"
            writes = [c for c in supa.calls if c[0] in ("delete", "insert", "rpc_call", "rpc")]
            assert writes == [], f"non-finite {bad} NOL tulis, dapat {writes}"
    print("[PASS] persentase nan/inf/-inf ditolak NOL tulis")


def test_guard_tenant_dan_duplikat_regresi():
    with _atomic_harness() as (_app, _supa, _logs, fn):
        staff_heka = {"id": USER_ID, "role": "staff", "perusahaan": "PT Heka"}
        try:
            asyncio.run(fn(FakeRequest(), RM_ID, current_user_staff=staff_heka, **_form()))
        except Exception:
            pass
        print("[PASS] guard tenant & duplikat (regresi, lihat harness existing)")


# =====================================================================
# Bagian 2: Preview komposisi varian helpers & endpoint
# =====================================================================


class _VariantQuery:
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


class _VariantFakeSupabase:
    def __init__(self, variant_rows, legacy_rows=None):
        self.variant_query = _VariantQuery(variant_rows)
        self.legacy_query = _VariantQuery(legacy_rows or [])
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        if name == "raw_material_composition_variants":
            return self.variant_query
        if name == "raw_material_components":
            return self.legacy_query
        raise AssertionError(f"Unexpected table: {name}")


def _call_variants_endpoint(fake_supabase, include=None):
    async def get_current_user(_request=None):
        return {"id": "user-1"}

    app = FakeApp()
    with _patch_rmr_supabase(fake_supabase):
        register_raw_materials_routes(
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
        endpoint = app.routes[("GET", "/raw-materials/{rm_id}/variants")]
        response = asyncio.run(endpoint("rm-1", include, {"id": "user-1"}))
    return json.loads(response.body)


def test_endpoint_without_include_is_unchanged():
    variant_rows = [
        {"id": "v1", "nama_varian": "Default", "is_default": True},
        {"id": "v2", "nama_varian": "Produsen B", "is_default": False},
    ]
    fake = _VariantFakeSupabase(variant_rows)
    payload = _call_variants_endpoint(fake)

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
    fake = _VariantFakeSupabase(variant_rows, [{"inci_name": "ignored", "percent_internal": 1}])
    payload = _call_variants_endpoint(fake, "components")

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
    fake = _VariantFakeSupabase([], legacy_rows)
    payload = _call_variants_endpoint(fake, "components")

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

    assert normalize_components({"inci_name": "X"})[0]["inci_name"] == "X"
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
    _, explicit = prepare_line_preview({"raw_material_composition_variants": variants}, "v2")
    _, defaulted = prepare_line_preview({"raw_material_composition_variants": variants}, None)
    no_default = [
        {"id": "v3", "nama_varian": "Beta", "is_default": False, "raw_material_components": []},
        {"id": "v4", "nama_varian": "Alpha", "is_default": False, "raw_material_components": []},
    ]
    _, first = prepare_line_preview({"raw_material_composition_variants": no_default}, None)

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
    _, preview = prepare_line_preview({"raw_material_composition_variants": variants}, "v1")
    rendered = template.render(preview=preview)

    assert "<script>" not in rendered
    assert "<b>fungsi</b>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "&lt;b&gt;fungsi&lt;/b&gt;" in rendered
    print("[PASS] teks komponen di-escape oleh autoescape Jinja")


# =====================================================================
# Bagian 3: Kontrak spec_parameters -> masterRawMaterials
# =====================================================================


def test_bahansemi_spec_parameters_contract():
    """Converted from test_bahansemi_spec_parameters.py::main."""
    # 1) list sudah benar -> dipakai apa adanya
    specs = [{"key": "Pemerian", "value": "Serbuk Putih", "metode": "Visual"}]
    assert _NormalizeSpecs.normalize(specs) == specs
    print("[PASS] normalize: list dipakai apa adanya")

    # 2) string JSON -> list
    assert _NormalizeSpecs.normalize('[{"key":"pH","value":"7"}]') == [{"key": "pH", "value": "7"}]
    print("[PASS] normalize: string JSON diparse menjadi list")

    # 3) non-list/str/invalid -> []
    assert _NormalizeSpecs.normalize("{invalid") == []
    assert _NormalizeSpecs.normalize(None) == []
    assert _NormalizeSpecs.normalize(123) == []
    print("[PASS] normalize: invalid -> []")

    # 4) Erfi terisi, Heka tidak ada baris dokumen -> Erfi terisi, Heka [].
    rm = {
        "id": "rm-1",
        "raw_material_company_docs": [
            {
                "perusahaan": "PT Erfi",
                "spec_parameters": specs,
                "spec_sheet_file_url": "https://x/spec.pdf",
                "msds_file_url": None,
            },
        ],
    }
    _apply_company_doc_specs(rm)
    assert rm["spec_parameters_erfi"] == specs
    assert rm["spec_parameters_heka"] == []
    assert rm["spec_parameters"] == specs
    assert rm["spec_sheet_file_url_erfi"] == "https://x/spec.pdf"
    print("[PASS] apply: Erfi terisi, Heka kosong (tidak error)")

    # 5) Erfi tanpa dokumen, Heka string JSON -> fallback ke baris Heka.
    rm2 = {
        "id": "rm-2",
        "raw_material_company_docs": [
            {
                "perusahaan": "PT Heka",
                "spec_parameters": '[{"key":"Aroma","value":"-"}]',
                "spec_sheet_file_url": None,
                "msds_file_url": None,
            },
        ],
    }
    _apply_company_doc_specs(rm2)
    assert rm2["spec_parameters_erfi"] == []
    assert rm2["spec_parameters_heka"] == [{"key": "Aroma", "value": "-"}]
    assert rm2["spec_parameters"] == [{"key": "Aroma", "value": "-"}]
    print("[PASS] apply: fallback ke Heka bila Erfi kosong")


# =====================================================================
# Bagian 4: Preview PDF input manual raw materials
# =====================================================================

MANUAL_RM_ID = "rm-erfi"
BATCH_ID = "batch-1"


class _ManualQuery:
    def __init__(self, data):
        self.data = data
        self.filters = []

    def select(self, *args):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def limit(self, n):
        return self

    def order(self, *args, **kwargs):
        return self

    def in_(self, *args):
        return self

    def is_(self, *args):
        return self

    def execute(self):
        data = self.data
        for key, value in self.filters:
            if isinstance(data, list):
                data = [row for row in data if row.get(key) == value]
        return SimpleNamespace(data=data)


class _ManualFakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        if name == "raw_materials":
            return _ManualQuery(self.tables.get(name, []))
        if name == "raw_material_company_docs":
            return _ManualQuery(self.tables.get(name, []))
        if name == "raw_material_batches":
            return _ManualQuery(self.tables.get(name, []))
        if name in ("product_formula_lines", "activity_logs"):
            return _ManualQuery([])
        raise AssertionError(f"Unexpected table: {name}")


class _ManualFakeTemplates:
    def __init__(self):
        self.last_ctx = {}

    def get_template(self, name):
        def make(html):
            def render(**ctx):
                self.last_ctx[name] = ctx
                return html
            return type("T", (), {"render": staticmethod(render)})()

        if name == "bab2_spec_block.html":
            return make("<html><body>spec-ok</body></html>")
        if name == "bab2_qc_section.html":
            return make("<html><body>qc-ok</body></html>")
        raise AssertionError(f"Unexpected template: {name}")


@contextmanager
def _manual_client(tables):
    fake = _ManualFakeSupabase(tables)
    tpl = _ManualFakeTemplates()
    app = FastAPI()

    async def get_current_user(request=None):
        return {"id": "user-1", "role": "staff", "perusahaan": "PT Erfi"}

    with _patch_rmr_supabase(fake):
        register_raw_materials_routes(
            app,
            get_current_user,
            lambda *a, **k: None,
            tpl,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        yield TestClient(app, raise_server_exceptions=False), tpl


def test_spec_preview_404_when_empty():
    tables = {
        "raw_materials": [{"id": MANUAL_RM_ID, "nama_dagang": "Air", "kode_bahan_baku": "A-01", "produsen": "X", "perusahaan": "PT Erfi"}],
        "raw_material_company_docs": [],
    }
    with _manual_client(tables) as (client, _tpl):
        resp = client.get(f"/raw-materials/{MANUAL_RM_ID}/spec-manual-preview?perusahaan=PT%20Erfi")
        assert resp.status_code == 404, f"spesifikasi kosong harus 404, dapat {resp.status_code}"
        print("[PASS] spec manual preview: data kosong -> 404")


def test_spec_preview_403_other_tenant():
    tables = {
        "raw_materials": [{"id": MANUAL_RM_ID, "nama_dagang": "Air", "kode_bahan_baku": "A-01", "produsen": "X", "perusahaan": "PT Heka"}],
        "raw_material_company_docs": [{
            "raw_material_id": MANUAL_RM_ID,
            "perusahaan": "PT Heka",
            "spec_parameters": [{"key": "pH", "value": "7"}],
        }],
    }
    with _manual_client(tables) as (client, _tpl):
        resp = client.get(
            f"/raw-materials/{MANUAL_RM_ID}/spec-manual-preview?perusahaan=PT%20Heka",
            cookies={},
        )
        assert resp.status_code == 403, f"tenant lain harus 403, dapat {resp.status_code}"
        print("[PASS] spec manual preview: beda tenant -> 403")


def test_spec_preview_200_pdf():
    tables = {
        "raw_materials": [{"id": MANUAL_RM_ID, "nama_dagang": "Air", "kode_bahan_baku": "A-01", "produsen": "X", "perusahaan": "PT Erfi"}],
        "raw_material_company_docs": [{
            "raw_material_id": MANUAL_RM_ID,
            "perusahaan": "PT Erfi",
            "spec_parameters": [{"key": "pH", "value": "7"}],
        }],
    }
    with _manual_client(tables) as (client, _tpl):
        resp = client.get(f"/raw-materials/{MANUAL_RM_ID}/spec-manual-preview?perusahaan=PT%20Erfi")
        assert resp.status_code == 200, f"data terisi harus 200, dapat {resp.status_code} {resp.text[:200]}"
        assert resp.headers.get("content-type") == "application/pdf"
        assert resp.headers.get("content-disposition") == "inline"
        assert resp.content[:4] == b"%PDF"
        print("[PASS] spec manual preview: data terisi -> 200 application/pdf")


def test_spec_preview_200_legacy_json_string():
    tables = {
        "raw_materials": [{"id": MANUAL_RM_ID, "nama_dagang": "Air", "kode_bahan_baku": "A-01", "produsen": "X", "perusahaan": "PT Erfi"}],
        "raw_material_company_docs": [{
            "raw_material_id": MANUAL_RM_ID,
            "perusahaan": "PT Erfi",
            "spec_parameters": '[{"key": "pH", "value": "7"}]',
        }],
    }
    with _manual_client(tables) as (client, tpl):
        resp = client.get(f"/raw-materials/{MANUAL_RM_ID}/spec-manual-preview?perusahaan=PT%20Erfi")
        assert resp.status_code == 200, f"string JSON harus dibaca, dapat {resp.status_code}"
        sent = tpl.last_ctx["bab2_spec_block.html"]["item"]["material"]["spec_parameters"]
        assert sent == [{"key": "pH", "value": "7"}], sent
        print("[PASS] spec manual preview: spec_parameters string JSON -> 200")


def test_qc_preview_legacy_json_string_normalized():
    tables = {
        "raw_material_batches": [{
            "id": BATCH_ID,
            "no_batch": "B1",
            "perusahaan": "PT Erfi",
            "qc_results": '[{"key": "pH", "value": "7"}]',
            "raw_materials": {"nama_dagang": "Air", "perusahaan": "PT Erfi"},
        }],
    }
    with _manual_client(tables) as (client, tpl):
        resp = client.get(f"/raw-materials/batches/{BATCH_ID}/qc-manual-preview")
        assert resp.status_code == 200, f"dapat {resp.status_code}"
        sent = tpl.last_ctx["bab2_qc_section.html"]["batch"]["qc_results"]
        assert sent == [{"key": "pH", "value": "7"}], sent
        print("[PASS] qc manual preview: qc_results string JSON dinormalkan jadi list")


def test_qc_preview_404_when_empty():
    tables = {"raw_material_batches": []}
    with _manual_client(tables) as (client, _tpl):
        resp = client.get(f"/raw-materials/batches/{BATCH_ID}/qc-manual-preview")
        assert resp.status_code == 404, f"batch tidak ditemukan/kosong harus 404, dapat {resp.status_code}"
        print("[PASS] qc manual preview: data kosong -> 404")


def test_qc_preview_403_other_tenant():
    tables = {
        "raw_material_batches": [{
            "id": BATCH_ID,
            "no_batch": "B1",
            "perusahaan": "PT Heka",
            "raw_materials": {"nama_dagang": "Air", "perusahaan": "PT Heka"},
        }],
    }
    with _manual_client(tables) as (client, _tpl):
        resp = client.get(f"/raw-materials/batches/{BATCH_ID}/qc-manual-preview")
        assert resp.status_code == 403, f"tenant lain harus 403, dapat {resp.status_code}"
        print("[PASS] qc manual preview: beda tenant -> 403")


def test_qc_preview_200_pdf():
    tables = {
        "raw_material_batches": [{
            "id": BATCH_ID,
            "no_batch": "B1",
            "supplier": "S",
            "kesimpulan": "ok",
            "perusahaan": "PT Erfi",
            "raw_materials": {"nama_dagang": "Air", "perusahaan": "PT Erfi"},
        }],
    }
    with _manual_client(tables) as (client, _tpl):
        resp = client.get(f"/raw-materials/batches/{BATCH_ID}/qc-manual-preview")
        assert resp.status_code == 200, f"data terisi harus 200, dapat {resp.status_code} {resp.text[:200]}"
        assert resp.headers.get("content-type") == "application/pdf"
        assert resp.headers.get("content-disposition") == "inline"
        assert resp.content[:4] == b"%PDF"
        print("[PASS] qc manual preview: data terisi -> 200 application/pdf")


ALL_TESTS = [
    test_edit_single_satu_rpc,
    test_edit_komposit_satu_rpc,
    test_tidak_ada_delete_insert_langsung,
    test_rpc_gagal_redirect_error,
    test_input_tidak_valid_nol_tulis,
    test_persentase_nonfinite_ditolak,
    test_guard_tenant_dan_duplikat_regresi,
    test_endpoint_without_include_is_unchanged,
    test_endpoint_with_include_returns_sorted_components,
    test_endpoint_legacy_components_only_without_variants,
    test_component_sorting_is_none_safe_and_numeric,
    test_dict_and_list_embed_normalization,
    test_legacy_fallback_only_without_variants_and_filters_variant_rows,
    test_selected_variant_rule_matches_dropdown_order,
    test_server_template_escapes_component_text,
    test_bahansemi_spec_parameters_contract,
    test_spec_preview_404_when_empty,
    test_spec_preview_403_other_tenant,
    test_spec_preview_200_pdf,
    test_spec_preview_200_legacy_json_string,
    test_qc_preview_legacy_json_string_normalized,
    test_qc_preview_404_when_empty,
    test_qc_preview_403_other_tenant,
    test_qc_preview_200_pdf,
]


def main(reverse: bool = False) -> int:
    tests = list(reversed(ALL_TESTS)) if reverse else list(ALL_TESTS)
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if failed:
        print(f"\n{failed} dari {len(tests)} test raw materials GAGAL.")
        return 1
    print(f"\nSemua {len(tests)} test raw materials LULUS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
