"""Unit test murni C-01/A-17: akun tanpa profil -> fail-closed.

Tanpa koneksi, tanpa secret. Dijalankan: python tests/test_auth_profile_fail_closed.py
(dengan PYTHONPATH=. seperti di ci.yml, env dummy CI).
"""
import asyncio
import os
import sys
import uuid
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

USER_ID = str(uuid.uuid4())
USER_EMAIL = "tester@example.com"
ADMIN_ROW = {"full_name": "Admin Erfi", "display_name": "Admin", "role": "admin", "perusahaan": "PT Erfi"}
STAFF_ROW = {"full_name": "Staff Erfi", "display_name": None, "role": "staff", "perusahaan": "PT Erfi"}


class _AuthUser:
    def __init__(self, uid=USER_ID, email=USER_EMAIL):
        self.id = uid
        self.email = email


class _ProfilesBuilder:
    def __init__(self, mode, row=None):
        self.mode = mode
        self.row = row

    def select(self, cols):
        self._cols = cols
        return self

    def eq(self, k, v):
        return self

    def execute(self):
        if self.mode == "ok":
            return SimpleNamespace(data=[self.row] if self.row else [])
        if self.mode == "first_fails_second_ok":
            if "display_name" in (self._cols or ""):
                raise RuntimeError("kolom display_name tidak ada")
            return SimpleNamespace(data=[self.row] if self.row else [])
        if self.mode == "both_fail":
            raise RuntimeError("gangguan Supabase")
        if self.mode == "no_row":
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[])


class FakeSupabase:
    def __init__(self, mode="ok", row=ADMIN_ROW, has_user=True):
        self.mode = mode
        self.row = row
        self.has_user = has_user

    class _Auth:
        def __init__(self, outer):
            self.outer = outer

        def get_user(self, token):
            if token == "valid-token" and self.outer.has_user:
                return SimpleNamespace(user=_AuthUser())
            return SimpleNamespace(user=None)

    def table(self, name):
        if name == "profiles":
            return _ProfilesBuilder(self.mode, self.row)
        return _ProfilesBuilder("no_row", None)

    @property
    def auth(self):
        inner = type("A", (), {})()
        inner.get_user = lambda token: (
            SimpleNamespace(user=_AuthUser()) if (token == "valid-token" and self.has_user) else SimpleNamespace(user=None)
        )
        return inner


class FakeRequest:
    def __init__(self, cookies=None):
        self.cookies = cookies or {}
        self.headers = {}
        self.query_params = {}


def _load_module():
    import app.main as main_mod
    return main_mod


def _get_user(main_mod, supabase):
    orig = main_mod.supabase
    main_mod.supabase = supabase
    try:
        req = FakeRequest(cookies={"access_token": "Bearer valid-token"})
        return asyncio.run(main_mod.get_current_user(req))
    finally:
        main_mod.supabase = orig


def test_admin_profile_identik():
    main_mod = _load_module()
    u = _get_user(main_mod, FakeSupabase(mode="ok", row=ADMIN_ROW))
    assert u["id"] == USER_ID and u["email"] == USER_EMAIL and u["full_name"] == "Admin Erfi"
    assert u["display_name"] == "Admin" and u["role"] == "admin" and u["perusahaan"] == "PT Erfi"
    print("[PASS] profil admin ada -> dict identik")


def test_staff_profile_identik():
    main_mod = _load_module()
    u = _get_user(main_mod, FakeSupabase(mode="ok", row=STAFF_ROW))
    assert u["full_name"] == "Staff Erfi" and u["display_name"] is None
    assert u["role"] == "staff" and u["perusahaan"] == "PT Erfi"
    print("[PASS] profil staff ada -> dict identik")


def test_no_row_403():
    main_mod = _load_module()
    try:
        _get_user(main_mod, FakeSupabase(mode="no_row"))
        raise AssertionError("harus 403")
    except HTTPException as e:
        assert e.status_code == 403, f"tanpa baris harus 403, dapat {e.status_code}"
        assert "Profil akun tidak ditemukan" in str(e.detail)
    print("[PASS] baris profil tidak ada -> 403 (bukan dict default)")


def test_first_fails_second_ok():
    main_mod = _load_module()
    u = _get_user(main_mod, FakeSupabase(mode="first_fails_second_ok", row=STAFF_ROW))
    assert u["full_name"] == "Staff Erfi" and u["role"] == "staff"
    print("[PASS] query pertama gagal, kedua berhasil -> sukses seperti dulu")


def test_both_fail_503():
    main_mod = _load_module()
    try:
        _get_user(main_mod, FakeSupabase(mode="both_fail"))
        raise AssertionError("harus 503")
    except HTTPException as e:
        assert e.status_code == 503, f"query gagal harus 503, dapat {e.status_code}"
        assert "sementara" in str(e.detail).lower()
    print("[PASS] kedua query melempar -> 503 (bukan 401/403/staff)")


def test_no_cookie_401():
    main_mod = _load_module()
    orig = main_mod.supabase
    main_mod.supabase = FakeSupabase(mode="ok", row=ADMIN_ROW)
    try:
        try:
            asyncio.run(main_mod.get_current_user(FakeRequest(cookies={})))
            raise AssertionError("harus 401")
        except HTTPException as e:
            assert e.status_code == 401
    finally:
        main_mod.supabase = orig
    print("[PASS] tanpa cookie -> 401")


def test_invalid_user_401():
    main_mod = _load_module()
    orig = main_mod.supabase
    main_mod.supabase = FakeSupabase(mode="ok", row=ADMIN_ROW, has_user=False)
    try:
        try:
            asyncio.run(main_mod.get_current_user(FakeRequest(cookies={"access_token": "Bearer valid-token"})))
            raise AssertionError("harus 401")
        except HTTPException as e:
            assert e.status_code == 401 and "User tidak valid" in str(e.detail)
    finally:
        main_mod.supabase = orig
    print("[PASS] user tidak valid -> 401 tetap")


def test_login_no_profile_rejected_both_paths():
    main_mod = _load_module()
    client, orig = _login_client(main_mod, profile_rows=[])
    try:
        for identifier in [USER_EMAIL, "testeruser"]:
            r = client.post("/login", data={"email": identifier, "password": "pw123456"},
                            follow_redirects=False)
            assert r.status_code == 303, f"{identifier} harus 303, dapat {r.status_code}"
            assert "/login?error=profile_missing" in r.headers.get("location", ""), f"{identifier} location {r.headers.get('location')}"
            assert "access_token" not in r.headers.get("set-cookie", ""), "tidak boleh Set-Cookie access_token"
        print("[PASS] login benar tanpa profil -> ditolak 303 tanpa cookie (username DAN email)")
    finally:
        _restore_login(main_mod, orig)


def test_login_profile_error_service_unavailable():
    main_mod = _load_module()
    client, orig = _login_client(main_mod, profile_rows=[], fail_login_profile=True)
    try:
        for identifier in [USER_EMAIL, "testeruser"]:
            r = client.post("/login", data={"email": identifier, "password": "pw123456"},
                            follow_redirects=False)
            assert r.status_code == 303, f"{identifier} harus 303, dapat {r.status_code}"
            assert "/login?error=service_unavailable" in r.headers.get("location", ""), f"{identifier} location {r.headers.get('location')}"
            assert "access_token" not in r.headers.get("set-cookie", ""), "tidak boleh Set-Cookie access_token"
        print("[PASS] login cek profil gagal -> service_unavailable tanpa cookie (username DAN email)")
    finally:
        _restore_login(main_mod, orig)


def test_login_with_profile_succeeds():
    main_mod = _load_module()
    client, orig = _login_client(main_mod, profile_rows=[], has_profile=True)
    try:
        r = client.post("/login", data={"email": USER_EMAIL, "password": "pw123456"},
                        follow_redirects=False)
        assert r.status_code == 303, f"profil ada harus sukses 303, dapat {r.status_code}"
        loc = r.headers.get("location", "")
        assert loc == "/", f"profil ada harus redirect /, dapat {loc}"
        assert "access_token" in r.headers.get("set-cookie", ""), "profil ada harus set cookie"
        print("[PASS] login profil ada -> sukses seperti sebelumnya")
    finally:
        _restore_login(main_mod, orig)


def _login_client(main_mod, profile_rows, fail_login_profile=False, has_profile=False):
    import app.staging_guard as sg
    orig_supabase = main_mod.supabase
    orig_sg = sg.staging_client
    fake = FakeSupabaseAdmin(profile_rows)
    fake.admin = _FakeAdminAuth(profile_rows + ([{"id": USER_ID, "full_name": "testeruser", "email": USER_EMAIL}] if not profile_rows else []))
    fake.auth = _FakeClientAuth()
    fake.auth.admin = fake.admin
    if fail_login_profile:
        old_table = fake.table
        def _fail_table(name):
            return _FakeFailTable(fail_on_full_name=False)
        fake.table = _fail_table
    elif has_profile:
        fake.table = lambda name: _FakeProfilesTable([{"id": USER_ID, "full_name": "testeruser", "email": USER_EMAIL}], has_profile_id=True)
    sg.staging_client = lambda caller: fake
    main_mod.supabase = fake
    return TestClient(main_mod.app, raise_server_exceptions=False), (orig_supabase, orig_sg)


class _FakeFailTable:
    def __init__(self, fail_on_full_name=True):
        self.fail_on_full_name = fail_on_full_name

    def select(self, cols):
        self._cols = cols
        return self

    def eq(self, k, v):
        self._k, self._v = k, v
        return self

    def execute(self):
        # Jalur username (lookup full_name) harus menemukan baris agar login
        # lanjut ke cek profil; cek profil id yang gagal:
        if getattr(self, "_k", None) == "full_name" and not self.fail_on_full_name:
            return SimpleNamespace(data=[{"id": USER_ID, "full_name": "testeruser", "email": USER_EMAIL}])
        raise RuntimeError("gangguan Supabase simulasi")


def _restore_login(main_mod, stored):
    orig_supabase, orig_sg = stored
    main_mod.supabase = orig_supabase
    import app.staging_guard as sg
    sg.staging_client = orig_sg


class FakeSupabaseAdmin:
    def __init__(self, profile_rows):
        self.profile_rows = profile_rows
        self.admin = _FakeAdminAuth(profile_rows)
        self.auth = _FakeClientAuth()

    def table(self, name):
        return _FakeProfilesTable(self.profile_rows)


class _FakeAdminAuth:
    def __init__(self, profile_rows):
        self.profile_rows = profile_rows

    def get_user_by_id(self, uid):
        for r in self.profile_rows:
            if r.get("id") == uid:
                return SimpleNamespace(user=SimpleNamespace(id=uid, email=r.get("email", USER_EMAIL)))
        return SimpleNamespace(user=SimpleNamespace(id=uid, email=USER_EMAIL))

    def sign_in_with_password(self, creds):
        return SimpleNamespace(
            user=SimpleNamespace(id=USER_ID, email=creds.get("email", USER_EMAIL)),
            session=SimpleNamespace(access_token="sess-token"),
        )


class _FakeClientAuth:
    def sign_in_with_password(self, creds):
        return SimpleNamespace(
            user=SimpleNamespace(id=USER_ID, email=creds.get("email", USER_EMAIL)),
            session=SimpleNamespace(access_token="sess-token"),
        )


class _FakeProfilesTable:
    def __init__(self, profile_rows, has_profile_id=False):
        # Untuk jalur username (lookup full_name) sediakan baris berikut agar
        # lookup menemukan, tetapi check profil id pada login post-auth
        # harus tetap kosong (sesuai kasus: tanpa profil).
        self.rows = list(profile_rows) + [{"id": USER_ID, "full_name": "testeruser", "email": USER_EMAIL}]
        self.has_profile_id = has_profile_id

    def select(self, cols):
        self._cols = cols
        return self

    def eq(self, k, v):
        self._k, self._v = k, v
        return self

    def execute(self):
        if getattr(self, "_k", None) == "full_name":
            data = [r for r in self.rows if str(r.get("full_name") or "").lower() == str(self._v).lower()]
        elif getattr(self, "_k", None) == "id" and getattr(self, "_cols", "") == "id":
            # Check profil pasca-auth: kosong kecuali kasus has_profile
            data = ([{"id": self._v}] if self.has_profile_id else [])
        elif getattr(self, "_k", None) == "id":
            data = [r for r in self.rows if r.get("id") == self._v]
        else:
            data = list(self.rows)
        return SimpleNamespace(data=data)


def test_protected_route_403_no_data():
    main_mod = _load_module()
    orig = main_mod.supabase
    main_mod.supabase = FakeSupabaseAdmin(profile_rows=[])
    client = TestClient(main_mod.app, raise_server_exceptions=False)
    try:
        # cookie fiktif; get_current_user akan 401 sebelum query data (fail-closed)
        # yang penting: user tanpa profil tidak memperoleh dict staff.
        r = client.get("/products/" + USER_ID + "/edit", cookies={"access_token": "Bearer valid-token"}, follow_redirects=False)
        assert r.status_code in (401, 403, 303), f"route terlindungi harus 401/403/303, dapat {r.status_code}"
        loc = r.headers.get("location", "")
        assert "session_expired" in loc or "Profil akun tidak ditemukan" in r.text, "harus redirect sesi atau pesan profil 403"
        assert r.status_code != 200
        print("[PASS] route terlindungi untuk user tanpa profil tidak 200")
    finally:
        main_mod.supabase = orig


def main():
    test_admin_profile_identik()
    test_staff_profile_identik()
    test_no_row_403()
    test_first_fails_second_ok()
    test_both_fail_503()
    test_no_cookie_401()
    test_invalid_user_401()
    test_login_no_profile_rejected_both_paths()
    test_login_profile_error_service_unavailable()
    test_login_with_profile_succeeds()
    test_protected_route_403_no_data()
    print("\nSemua test profil fail-closed LULUS.")


if __name__ == "__main__":
    main()
