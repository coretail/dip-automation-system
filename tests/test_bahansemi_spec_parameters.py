"""Unit test kontrak spec_parameters -> masterRawMaterials (pure-local).

Mengunci perilaku route GET /raw-materials: `raw_material_company_docs` milik
Erfi/Heka disalin ke `rm["spec_parameters"]` sebagai list (string JSON
dinormalisasi), supaya modal `+ Batch` membangun Parameter Uji Laboratorium
Aktual dari spesifikasi master data yang sudah terisi per perusahaan.
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

from app.raw_materials_routes import _NormalizeSpecs, _apply_company_doc_specs  # noqa: E402


def main():
    # 1) list sudah benar -> dipakai apa adanya
    specs = [{"key": "Pemerian", "value": "Serbuk Putih", "metode": "Visual"}]
    assert _NormalizeSpecs.normalize(specs) == specs
    print("[PASS] normalize: list dipakai apa adanya")

    # 2) string JSON -> list (kondisi JSONB legacy yang menyebabkan
    #    `specs.forEach is not a function`)
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
            {"perusahaan": "PT Erfi", "spec_parameters": specs,
             "spec_sheet_file_url": "https://x/spec.pdf", "msds_file_url": None},
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
            {"perusahaan": "PT Heka", "spec_parameters": '[{"key":"Aroma","value":"-"}]',
             "spec_sheet_file_url": None, "msds_file_url": None},
        ],
    }
    _apply_company_doc_specs(rm2)
    assert rm2["spec_parameters_erfi"] == []
    assert rm2["spec_parameters_heka"] == [{"key": "Aroma", "value": "-"}]
    assert rm2["spec_parameters"] == [{"key": "Aroma", "value": "-"}]
    print("[PASS] apply: fallback ke Heka bila Erfi kosong")

    print("\nSemua test spec_parameters -> masterRawMaterials LULUS.")


if __name__ == "__main__":
    main()
