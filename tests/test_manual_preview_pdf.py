"""Unit test preview PDF input manual raw materials (pure-local).

Mengunci kontrak route GET preview manual:
- 404 untuk data manual kosong (spesifikasi & QC)
- 403 untuk tenant lain
- 200 application/pdf dengan header %PDF untuk data terisi

Tanpa koneksi Supabase/jaringan; supabase dan template dirender lewat fake.
Dijalankan: ``python tests/test_manual_preview_pdf.py``.
"""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import raw_materials_routes  # noqa: E402
from app.raw_materials_routes import register_raw_materials_routes  # noqa: E402

RM_ID = "rm-erfi"
BATCH_ID = "batch-1"


class Query:
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

    # Supabase builder also calls `.order`, `.in_`, `.is_`, dll. di route lain;
    # halaman panel tidak dipakai oleh test ini, tapi sediakan untuk kompatibilitas.
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


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        if name == "raw_materials":
            return Query(self.tables.get(name, []))
        if name == "raw_material_company_docs":
            return Query(self.tables.get(name, []))
        if name == "raw_material_batches":
            return Query(self.tables.get(name, []))
        if name in ("product_formula_lines", "activity_logs"):
            return Query([])
        raise AssertionError(f"Unexpected table: {name}")


class FakeTemplates:
    # Konteks render terakhir per template, supaya test bisa memeriksa data
    # yang benar-benar dikirim ke template.
    last_ctx = {}

    def get_template(self, name):
        from jinja2 import Environment
        env = Environment(loader=None)

        def make(html):
            def render(**ctx):
                FakeTemplates.last_ctx[name] = ctx
                return html
            return type("T", (), {"render": staticmethod(render)})()

        if name == "bab2_spec_block.html":
            return make("<html><body>spec-ok</body></html>")
        if name == "bab2_qc_section.html":
            return make("<html><body>qc-ok</body></html>")
        raise AssertionError(f"Unexpected template: {name}")


def build_client(tables):
    fake = FakeSupabase(tables)
    app = FastAPI()

    async def get_current_user(request=None):
        return {"id": "user-1", "role": "staff", "perusahaan": "PT Erfi"}

    raw_materials_routes.supabase = fake
    register_raw_materials_routes(
        app, get_current_user, lambda *a, **k: None, FakeTemplates(), None, None, None, None,
        None, None, None,
    )
    return TestClient(app, raise_server_exceptions=False)


def test_spec_preview_404_when_empty():
    fake = FakeSupabase({
        "raw_materials": [{"id": RM_ID, "nama_dagang": "Air", "kode_bahan_baku": "A-01", "produsen": "X", "perusahaan": "PT Erfi"}],
        "raw_material_company_docs": [],
    })
    client = build_client(fake.tables)
    resp = client.get(f"/raw-materials/{RM_ID}/spec-manual-preview?perusahaan=PT%20Erfi")
    assert resp.status_code == 404, f"spesifikasi kosong harus 404, dapat {resp.status_code}"
    print("[PASS] spec manual preview: data kosong -> 404")


def test_spec_preview_403_other_tenant():
    fake = FakeSupabase({
        "raw_materials": [{"id": RM_ID, "nama_dagang": "Air", "kode_bahan_baku": "A-01", "produsen": "X", "perusahaan": "PT Heka"}],
        "raw_material_company_docs": [{"raw_material_id": RM_ID, "perusahaan": "PT Heka",
                                        "spec_parameters": [{"key": "pH", "value": "7"}]}],
    })
    client = build_client(fake.tables)
    # Pertahankan konteks aktif. Route memakai dependency; user tenant di override local.
    resp = client.get(f"/raw-materials/{RM_ID}/spec-manual-preview?perusahaan=PT%20Heka",
                      cookies={})
    # User aktif di fake adalah PT Erfi, bahan baku adalah PT Heka -> 403
    assert resp.status_code == 403, f"tenant lain harus 403, dapat {resp.status_code}"
    print("[PASS] spec manual preview: beda tenant -> 403")


def test_spec_preview_200_pdf():
    fake = FakeSupabase({
        "raw_materials": [{"id": RM_ID, "nama_dagang": "Air", "kode_bahan_baku": "A-01", "produsen": "X", "perusahaan": "PT Erfi"}],
        "raw_material_company_docs": [{"raw_material_id": RM_ID, "perusahaan": "PT Erfi",
                                        "spec_parameters": [{"key": "pH", "value": "7"}]}],
    })
    client = build_client(fake.tables)
    resp = client.get(f"/raw-materials/{RM_ID}/spec-manual-preview?perusahaan=PT%20Erfi")
    assert resp.status_code == 200, f"data terisi harus 200, dapat {resp.status_code} {resp.text[:200]}"
    assert resp.headers.get("content-type") == "application/pdf"
    assert resp.headers.get("content-disposition") == "inline"
    assert resp.content[:4] == b"%PDF"
    print("[PASS] spec manual preview: data terisi -> 200 application/pdf")


def test_spec_preview_200_legacy_json_string():
    # Baris lama menyimpan spec_parameters sebagai string JSON; harus tetap
    # terbaca (konsisten dengan spec_text_ok di halaman daftar).
    fake = FakeSupabase({
        "raw_materials": [{"id": RM_ID, "nama_dagang": "Air", "kode_bahan_baku": "A-01", "produsen": "X", "perusahaan": "PT Erfi"}],
        "raw_material_company_docs": [{"raw_material_id": RM_ID, "perusahaan": "PT Erfi",
                                        "spec_parameters": '[{"key": "pH", "value": "7"}]'}],
    })
    client = build_client(fake.tables)
    resp = client.get(f"/raw-materials/{RM_ID}/spec-manual-preview?perusahaan=PT%20Erfi")
    assert resp.status_code == 200, f"string JSON harus dibaca, dapat {resp.status_code}"
    sent = FakeTemplates.last_ctx["bab2_spec_block.html"]["item"]["material"]["spec_parameters"]
    assert sent == [{"key": "pH", "value": "7"}], sent
    print("[PASS] spec manual preview: spec_parameters string JSON -> 200")


def test_qc_preview_legacy_json_string_normalized():
    fake = FakeSupabase({
        "raw_material_batches": [{"id": BATCH_ID, "no_batch": "B1", "perusahaan": "PT Erfi",
                                  "qc_results": '[{"key": "pH", "value": "7"}]',
                                  "raw_materials": {"nama_dagang": "Air", "perusahaan": "PT Erfi"}}],
    })
    client = build_client(fake.tables)
    resp = client.get(f"/raw-materials/batches/{BATCH_ID}/qc-manual-preview")
    assert resp.status_code == 200, f"dapat {resp.status_code}"
    sent = FakeTemplates.last_ctx["bab2_qc_section.html"]["batch"]["qc_results"]
    assert sent == [{"key": "pH", "value": "7"}], sent
    print("[PASS] qc manual preview: qc_results string JSON dinormalkan jadi list")


def test_qc_preview_404_when_empty():
    fake = FakeSupabase({
        "raw_material_batches": [],
    })
    client = build_client(fake.tables)
    resp = client.get(f"/raw-materials/batches/{BATCH_ID}/qc-manual-preview")
    assert resp.status_code == 404, f"batch tidak ditemukan/kosong harus 404, dapat {resp.status_code}"
    print("[PASS] qc manual preview: data kosong -> 404")


def test_qc_preview_403_other_tenant():
    fake = FakeSupabase({
        "raw_material_batches": [{"id": BATCH_ID, "no_batch": "B1", "perusahaan": "PT Heka",
                                  "raw_materials": {"nama_dagang": "Air", "perusahaan": "PT Heka"}}],
    })
    client = build_client(fake.tables)
    resp = client.get(f"/raw-materials/batches/{BATCH_ID}/qc-manual-preview")
    assert resp.status_code == 403, f"tenant lain harus 403, dapat {resp.status_code}"
    print("[PASS] qc manual preview: beda tenant -> 403")


def test_qc_preview_200_pdf():
    fake = FakeSupabase({
        "raw_material_batches": [{"id": BATCH_ID, "no_batch": "B1", "supplier": "S", "kesimpulan": "ok",
                                  "perusahaan": "PT Erfi",
                                  "raw_materials": {"nama_dagang": "Air", "perusahaan": "PT Erfi"}}],
    })
    client = build_client(fake.tables)
    resp = client.get(f"/raw-materials/batches/{BATCH_ID}/qc-manual-preview")
    assert resp.status_code == 200, f"data terisi harus 200, dapat {resp.status_code} {resp.text[:200]}"
    assert resp.headers.get("content-type") == "application/pdf"
    assert resp.headers.get("content-disposition") == "inline"
    assert resp.content[:4] == b"%PDF"
    print("[PASS] qc manual preview: data terisi -> 200 application/pdf")


def main():
    test_spec_preview_404_when_empty()
    test_spec_preview_403_other_tenant()
    test_spec_preview_200_pdf()
    test_spec_preview_200_legacy_json_string()
    test_qc_preview_legacy_json_string_normalized()
    test_qc_preview_404_when_empty()
    test_qc_preview_403_other_tenant()
    test_qc_preview_200_pdf()
    print("\nSemua test manual preview PDF LULUS.")


if __name__ == "__main__":
    main()
