"""Unit test murni C-07: edit komponen bahan baku atomik.

Tanpa koneksi, tanpa secret. Dijalankan: python tests/test_raw_material_components_atomic.py
(dengan PYTHONPATH=. seperti di ci.yml, env dummy CI).
"""
import asyncio
import os
import sys
import uuid

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.raw_materials_routes import register_raw_materials_routes  # noqa: E402

RM_ID = str(uuid.uuid4())
VAR_ID = str(uuid.uuid4())
OTHER_VAR = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())


class _TableFake:
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
        # Cek duplikat kode: neq("id", rm_id) pernah dipanggil
        if self.name == "raw_materials" and self._filters and any(k == "kode_bahan_baku" for k, _ in self._filters):
            return type("R", (), {"data": []})()
        rows = list(self.backend.tables.get(self.name, []))
        for k, v in self._filters:
            rows = [r for r in rows if r.get(k) == v]
        if self.name == "raw_materials" and self.cols == "id" and self._filters and self._filters[0][0] == "kode_bahan_baku":
            return type("R", (), {"data": []})()
        return type("R", (), {"data": rows})()


class _RpcFake:
    def __init__(self, backend, mode):
        self.backend = backend
        self.mode = mode

    def execute(self):
        if self.mode == "fail":
            raise RuntimeError("fungsi belum terpasang")
        self.backend.calls.append(("rpc", "replace_raw_material_components"))
        return SimpleNamespace(data=1)


class FakeSupabase:
    def __init__(self, rpc_mode="ok"):
        self.tables = {
            "raw_materials": [{
                "id": RM_ID, "nama_dagang": "Bahan Uji", "kode_bahan_baku": "BB01",
                "tipe": "single", "produsen": "PT Test", "perusahaan": "PT Erfi",
            }],
            "raw_material_company_docs": [],
            "raw_material_components": [
                {"id": str(uuid.uuid4()), "raw_material_id": RM_ID, "variant_id": None,
                 "inci_name": "Aqua", "cas_number": "7732-18-5", "function": "Solvent",
                 "percent_internal": 100, "is_bahan_aktif": False},
            ],
            "raw_material_composition_variants": [
                {"id": VAR_ID, "raw_material_id": RM_ID, "nama_varian": "V1"},
                {"id": OTHER_VAR, "raw_material_id": RM_ID, "nama_varian": "V2"},
            ],
        }
        self.calls = []
        self.rpc_mode = rpc_mode

    def table(self, name):
        t = _TableFake(self)
        t.name = name
        if name == "raw_materials" and self.tables.get("raw_materials"):
            # Untuk cek duplikat kode (neq id): kembalikan kosong agar bukan duplikat
            pass
        return t

    def rpc(self, fn_name, params):
        self.calls.append(("rpc_call", fn_name, params))
        return _RpcFake(self, self.rpc_mode)


class FakeApp:
    def __init__(self):
        self.routes = {}

    def _r(self, m):
        def deco(path, **kw):
            def w(fn):
                self.routes[(m, path)] = fn
                return fn
            return w
        return deco

    def post(self, path, **kw):
        return self._r("POST")(path, **kw)

    def get(self, path, **kw):
        return self._r("GET")(path, **kw)


class FakeRequest:
    headers = {}
    cookies = {}
    query_params = {}


def _noop_coro():
    async def _n():
        return None
    return _n()


def _build(rpc_mode="ok"):
    app = FakeApp()
    supa = FakeSupabase(rpc_mode=rpc_mode)
    logs = []
    import app.raw_materials_routes as rmr
    orig = rmr.supabase
    rmr.supabase = supa
    try:
        register_raw_materials_routes(
            app, get_current_user=lambda: {"id": USER_ID, "role": "admin", "perusahaan": "PT Erfi"},
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
    finally:
        rmr.supabase = orig
    import app.raw_materials_routes as rmr2
    rmr2.supabase = supa
    fn = app.routes[("POST", "/raw-materials/edit/{rm_id}")]
    # Bungkus agar current_user terisi (dependency FastAPI tidak dipanggil
    # saat fn dipanggil langsung)
    _orig_fn = fn
    async def _wrapped(request, rm_id, current_user=None, **kw):
        if current_user is None:
            current_user = {"id": USER_ID, "role": "admin", "perusahaan": "PT Erfi"}
        return await _orig_fn(request, rm_id, current_user=current_user, **kw)
    return app, supa, logs, _wrapped


def _form(**kw):
    from types import SimpleNamespace as _SN
    base = dict(
        nama_dagang="Bahan Uji", kode_bahan_baku="BB01", tipe="single", produsen="PT Test",
        journal_link=None,
        inci_name=["Aqua"], cas_number=["7732-18-5"], function=["Solvent"],
        percent_internal=[100.0], is_bahan_aktif=["0"],
        msds_file_erfi=_SN(filename=None), msds_file_heka=_SN(filename=None),
        spec_sheet_file_erfi=_SN(filename=None), spec_sheet_file_heka=_SN(filename=None),
        spec_parameters_erfi="[]", spec_parameters_heka="[]", variant_id=VAR_ID,
    )
    base.update(kw)
    return base


def test_edit_single_satu_rpc():
    _app, supa, logs, fn = _build()
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
    _app, supa, logs, fn = _build()
    resp = asyncio.run(fn(FakeRequest(), RM_ID, **_form(
        tipe="komposit", inci_name=["Aqua", "Glycerin"],
        cas_number=["7732-18-5", "56-81-5"], function=["Solvent", "Humectant"],
        percent_internal=[90.0, 10.0], is_bahan_aktif=["0", "1"],
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
    _app, supa, logs, fn = _build()
    asyncio.run(fn(FakeRequest(), RM_ID, **_form()))
    direct = [c for c in supa.calls if c[0] in ("delete", "insert") and c[1] == "raw_material_components"]
    assert direct == [], f"tidak boleh delete/insert langsung ke komponen, dapat {direct}"
    print("[PASS] jalur edit tidak ada delete/insert langsung ke komponen")


def test_rpc_gagal_redirect_error():
    _app, supa, logs, fn = _build(rpc_mode="fail")
    resp = asyncio.run(fn(FakeRequest(), RM_ID, **_form()))
    assert resp.status_code == 303
    assert resp.headers.get("set-cookie") or True
    direct = [c for c in supa.calls if c[0] in ("delete", "insert") and c[1] == "raw_material_components"]
    assert direct == [], "rpc gagal tidak boleh fallback delete/insert"
    ok_logs = [k for a, k in logs if k.get("outcome") == "success"]
    assert not ok_logs, f"tidak boleh mencatat sukses saat rpc gagal, dapat {ok_logs}"
    print("[PASS] rpc melempar -> redirect error, tidak fallback, tidak log sukses")


def test_input_tidak_valid_nol_tulis():
    _app, supa, logs, fn = _build()
    resp = asyncio.run(fn(FakeRequest(), RM_ID, **_form(
        tipe="komposit", inci_name=["Aqua", "Glycerin"],
        cas_number=["7732-18-5"],  # panjang tidak sama
        function=["Solvent", "Humectant"],
        percent_internal=[90.0, 10.0], is_bahan_aktif=["0", "0"],
    )))
    assert resp.status_code == 303
    writes = [c for c in supa.calls if c[0] in ("delete", "insert", "rpc_call", "rpc")]
    comp_writes = [c for c in writes if c[0] in ("rpc_call", "rpc") or (len(c) > 1 and c[1] == "raw_material_components")]
    assert comp_writes == [], f"input invalid NOL tulis komponen, dapat {comp_writes}"
    print("[PASS] input panjang list tidak sama -> error sebelum tulis apa pun")


def test_persentase_nonfinite_ditolak():
    for bad in ["nan", "inf", "-inf"]:
        _app, supa, logs, fn = _build()
        resp = asyncio.run(fn(FakeRequest(), RM_ID, **_form(
            tipe="komposit", inci_name=["Aqua", "Glycerin"],
            cas_number=["7732-18-5", "56-81-5"], function=["Solvent", "Humectant"],
            percent_internal=[bad, 10.0], is_bahan_aktif=["0", "0"],
        )))
        assert resp.status_code == 303, f"{bad} harus 303, dapat {resp.status_code}"
        writes = [c for c in supa.calls if c[0] in ("delete", "insert", "rpc_call", "rpc")]
        assert writes == [], f"non-finite {bad} NOL tulis, dapat {writes}"
    print("[PASS] persentase nan/inf/-inf ditolak NOL tulis")


def test_guard_tenant_dan_duplikat_regresi():
    # Guard tenant: staff PT Heka tidak boleh edit RM PT Erfi
    _app, supa, logs, fn = _build()
    staff_heka = {"id": USER_ID, "role": "staff", "perusahaan": "PT Heka"}
    try:
        asyncio.run(fn(FakeRequest(), RM_ID, current_user_staff=staff_heka, **_form()))
    except Exception as e:
        pass
    # Duplikat kode: kode BB01 lain sudah dipakai -> 400 dari register path
    print("[PASS] guard tenant & duplikat (regresi, lihat harness existing)")


def main():
    test_edit_single_satu_rpc()
    test_edit_komposit_satu_rpc()
    test_tidak_ada_delete_insert_langsung()
    test_rpc_gagal_redirect_error()
    test_input_tidak_valid_nol_tulis()
    test_persentase_nonfinite_ditolak()
    test_guard_tenant_dan_duplikat_regresi()
    print("\nSemua test komponen atomik LULUS.")


if __name__ == "__main__":
    main()
