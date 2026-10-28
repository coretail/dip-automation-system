"""Pure-local tests for raw-material variant component previews; no Supabase network."""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

from fastapi.testclient import TestClient

from app.main import app, get_current_user
from app import raw_materials_routes


class FakeQuery:
    def __init__(self, table_name):
        self.table_name = table_name
        self.null_filter = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def is_(self, *_args, **_kwargs):
        self.null_filter = True
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self.table_name == "raw_material_composition_variants":
            return SimpleNamespace(data=[
                {
                    "id": "v-default",
                    "nama_varian": "Default",
                    "is_default": True,
                    "raw_material_components": [
                        {"inci_name": "Water", "function": "Solvent", "percent_internal": None, "is_bahan_aktif": False},
                        {"inci_name": "Active", "function": "Active", "percent_internal": "5", "is_bahan_aktif": True},
                        {"inci_name": "Base", "function": "Base", "percent_internal": 10, "is_bahan_aktif": False},
                    ],
                },
                {
                    "id": "v-second",
                    "nama_varian": "Second",
                    "is_default": False,
                    "raw_material_components": {"inci_name": "Solo", "function": "F", "percent_internal": 1, "is_bahan_aktif": False},
                },
            ])
        if self.table_name == "raw_material_components":
            if self.null_filter:
                return SimpleNamespace(data=[
                    {"inci_name": "Legacy Null", "function": "F", "percent_internal": 2, "is_bahan_aktif": False, "variant_id": None},
                    {"inci_name": "Attached", "function": "F", "percent_internal": 3, "is_bahan_aktif": False, "variant_id": "v-default"},
                ])
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[])


class FakeSupabase:
    def table(self, name):
        return FakeQuery(name)


def run_tests():
    raw_materials_routes.supabase = FakeSupabase()
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-1", "role": "staff", "perusahaan": None}
    client = TestClient(app, follow_redirects=False)
    rm_id = "rm-1"

    default_resp = client.get(f"/raw-materials/{rm_id}/variants")
    assert default_resp.status_code == 200
    default_data = default_resp.json()
    assert default_data["success"] is True
    assert set(default_data["variants"][0].keys()) == {"id", "nama_varian", "is_default"}
    assert "components" not in default_data["variants"][0]
    assert "legacy_components" not in default_data

    include_resp = client.get(f"/raw-materials/{rm_id}/variants?include=components")
    assert include_resp.status_code == 200
    include_data = include_resp.json()
    assert include_data["success"] is True
    default_variant = include_data["variants"][0]
    assert [c["inci_name"] for c in default_variant["components"]] == ["Base", "Active", "Water"]
    assert default_variant["components"][0]["percent_internal"] == 10
    assert default_variant["components"][1]["percent_internal"] == "5"
    assert default_variant["components"][2]["percent_internal"] is None
    # legacy_components are empty when variants exist.
    assert include_data["legacy_components"] == []

    # helper sorting handles None/string/number and is deterministic.
    sorted_components = raw_materials_routes._sort_rm_components([
        {"inci_name": "B", "percent_internal": None},
        {"inci_name": "A", "percent_internal": "10"},
        {"inci_name": "C", "percent_internal": 5},
    ])
    assert [c["inci_name"] for c in sorted_components] == ["A", "C", "B"]

    app.dependency_overrides.clear()
    print("[PASS] raw-material variant endpoint and component sorting")


if __name__ == "__main__":
    run_tests()
    print("All raw-material variant tests passed.")