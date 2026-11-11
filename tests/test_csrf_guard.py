"""Unit test murni A-07 koreksi: guard CSRF Origin/Referer (CsrfGuardMiddleware).

Tanpa koneksi, tanpa secret. Dijalankan: python tests/test_csrf_guard.py
(dengan PYTHONPATH=. seperti di ci.yml).

Cakupan sesuai brief sesi 16 koreksi:
- POST same-origin lolos; Origin beda host / null / skema beda => 403
- Origin null (dengan atau tanpa Referer) => 403
- Tanpa Origin + Referer same-origin lolos; Referer beda => 403;
  keduanya tak ada => lolos (residu non-browser)
- X-Forwarded-Proto dihormati hanya http/https; X-Forwarded-Host diabaikan
- GET/HEAD/OPTIONS dengan Origin asing tidak disentuh
- DIP_ALLOWED_ORIGINS memperluas allowlist; entri tak valid diabaikan
- Multipart POST besar tetap sampai handler utuh (body tidak dibaca guard)
- Respons 403 di app NYATA (from app.main import app) membawa
  X-Frame-Options, X-Content-Type-Options, Referrer-Policy: same-origin
- SecurityHeadersMiddleware unit test: nilai Referrer-Policy == same-origin
- Log tidak memuat query string / cookie
- Method override tidak dipakai aplikasi (dikonfirmasi, diuji)
"""
import io
import logging
import os
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, File, Request, UploadFile  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.csrf_guard import CsrfGuardMiddleware, EXEMPT_PATHS  # noqa: E402

HOST = "localhost:8017"

PASSED = []
FAILED = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"PASS {name}")
    else:
        FAILED.append(name)
        print(f"FAIL {name} {detail}")


def make_app() -> tuple[FastAPI, dict]:
    """App uji kecil: POST /x (body ditelan), POST /upload (multipart),
    GET/HEAD/OPTIONS /x. Pasang CsrfGuardMiddleware saja (tanpa
    SecurityHeaders) agar test cepat dan tidak butuh env lengkap."""
    state: dict = {"received": b"", "received_headers": None}

    app = FastAPI()

    @app.post("/x")
    async def post_x(request: Request):
        body = await request.body()
        state["received"] = body
        state["received_headers"] = dict(request.headers)
        return {"ok": True, "echo": state["received"].decode("utf-8", "replace")[:40]}

    @app.post("/upload")
    async def post_upload(request: Request, file: UploadFile = File(...)):
        data = await file.read()
        state["received"] = data
        state["received_headers"] = dict(request.headers)
        return {"ok": True, "filename": file.filename, "size": len(data)}

    @app.get("/x")
    async def get_x():
        return {"ok": True}

    @app.head("/x")
    async def head_x():
        return {"ok": True}

    @app.options("/x")
    async def options_x():
        return {"ok": True}

    app.add_middleware(CsrfGuardMiddleware)
    return app, state


def req(client: TestClient, method: str = "POST", path: str = "/x",
        origin=None, referer=None, fwd_proto=None, fwd_host=None,
        headers=None, data=None, files=None) -> object:
    h = {}
    if origin is not None:
        h["Origin"] = origin
    if referer is not None:
        h["Referer"] = referer
    if fwd_proto is not None:
        h["X-Forwarded-Proto"] = fwd_proto
    if fwd_host is not None:
        h["X-Forwarded-Host"] = fwd_host
    if headers:
        h.update(headers)
    return client.request(method, path, headers=h, data=data, files=files)


def same_origin(fwd_proto: str | None = None) -> str:
    scheme = fwd_proto if fwd_proto in ("http", "https") else "http"
    return f"{scheme}://{HOST}"


def main() -> int:
    # ===== 0. Inventaris & konstanta =====
    check("EXEMPT_PATHS kosong (inventaris sesi 16)", EXEMPT_PATHS == frozenset())

    # ===== 1. Origin same/beda/null =====
    app, state = make_app()
    client = TestClient(app, base_url=f"http://{HOST}")
    with client:
        r = req(client, origin=same_origin())
        check("POST same-origin (Origin sama) lolos", r.status_code == 200, f"got {r.status_code}")
        check("body sampai handler saat lolos", state["received"] == b"")

        r = req(client, origin="https://evil.example")
        check("Origin https://evil.example => 403", r.status_code == 403, f"got {r.status_code}")
        check("body 403 singkat", "origin tidak cocok" in r.text)

        r = req(client, origin="http://other.example")
        check("Origin beda host => 403", r.status_code == 403, f"got {r.status_code}")

        r = req(client, origin="null")
        check("Origin null tanpa Referer => 403 (opaque origin)", r.status_code == 403,
              f"got {r.status_code}")
        r = req(client, origin="null", referer="https://evil.example/")
        check("Origin null + Referer beda => 403", r.status_code == 403, f"got {r.status_code}")
        r = req(client, origin="null", referer=same_origin())
        check("Origin null + Referer same => 403 (Origin null tidak di-bypass)",
              r.status_code == 403, f"got {r.status_code}")

        r = req(client, origin="", referer=same_origin())
        check("Origin kosong string + Referer same => lolos (Origin kosong diabaikan)",
              r.status_code == 200, f"got {r.status_code}")
        r = req(client, origin="", referer="https://evil.example/")
        check("Origin kosong string + Referer beda => 403", r.status_code == 403,
              f"got {r.status_code}")

        r = req(client, origin="https://" + HOST)
        check("skema beda (Origin https vs request http) => 403",
              r.status_code == 403, f"got {r.status_code}")

        r = req(client, origin="HTTP://" + HOST)
        check("Origin case-insensitive (HTTP://) lolos", r.status_code == 200,
              f"got {r.status_code}")

    # ===== 2. Referer =====
    with client:
        r = req(client, referer=f"http://{HOST}/notes")
        check("Tanpa Origin, Referer same-origin lolos", r.status_code == 200,
              f"got {r.status_code}")

        r = req(client, referer="https://evil.example/notes")
        check("Tanpa Origin, Referer beda => 403", r.status_code == 403,
              f"got {r.status_code}")

        r = req(client)
        check("Tanpa Origin & Referer => lolos (non-browser, residu)",
              r.status_code == 200, f"got {r.status_code}")

        r = req(client, origin=same_origin(), referer="https://evil.example/")
        check("Origin ada: Referer diabaikan (Origin sama) lolos",
              r.status_code == 200, f"got {r.status_code}")

    # ===== 3. X-Forwarded-Proto / X-Forwarded-Host =====
    with client:
        r = req(client, origin="https://" + HOST, fwd_proto="https")
        check("X-Forwarded-Proto https + Origin https lolos",
              r.status_code == 200, f"got {r.status_code}")

        r = req(client, origin="https://" + HOST, fwd_proto="http")
        check("X-Forwarded-Proto http + Origin https => 403",
              r.status_code == 403, f"got {r.status_code}")

        r = req(client, origin=same_origin(), fwd_host="evil.example")
        check("X-Forwarded-Host palsu diabaikan (Host dipakai) lolos",
              r.status_code == 200, f"got {r.status_code}")

        r = req(client, origin=same_origin(), fwd_proto="https http")
        check("X-Forwarded-Proto nilai asing diabaikan (skema scope) lolos",
              r.status_code == 200, f"got {r.status_code}")

    # ===== 4. Method yang tidak disentuh =====
    with client:
        r = req(client, method="GET", origin="https://evil.example")
        check("GET dengan Origin asing tidak disentuh", r.status_code == 200,
              f"got {r.status_code}")
        r = req(client, method="HEAD", origin="https://evil.example")
        check("HEAD dengan Origin asing tidak disentuh", r.status_code == 200,
              f"got {r.status_code}")
        r = req(client, method="OPTIONS", origin="https://evil.example")
        check("OPTIONS dengan Origin asing tidak disentuh", r.status_code == 200,
              f"got {r.status_code}")

    # ===== 5. DIP_ALLOWED_ORIGINS =====
    os.environ["DIP_ALLOWED_ORIGINS"] = (
        "https://partner.example, https://partner.example:8443, "
        "ftp://bad.example, http://10.0.0.5, "
        "http://localhost:9999, http://127.0.0.1:9999"
    )
    app2, _ = make_app()
    client2 = TestClient(app2, base_url=f"http://{HOST}")
    with client2:
        r = req(client2, origin="https://partner.example")
        check("allowlist https://partner.example lolos", r.status_code == 200,
              f"got {r.status_code}")
        r = req(client2, origin="https://partner.example:8443")
        check("allowlist dengan port lolos", r.status_code == 200,
              f"got {r.status_code}")
        r = req(client2, origin="https://evil.example")
        check("entri ftp:// tak valid diabaikan => 403 tetap",
              r.status_code == 403, f"got {r.status_code}")
        r = req(client2, origin="http://10.0.0.5")
        check("entri http non-localhost diabaikan => 403",
              r.status_code == 403, f"got {r.status_code}")
        r = req(client2, origin="http://localhost:9999")
        check("entri http://localhost:port (staging lokal) lolos",
              r.status_code == 200, f"got {r.status_code}")
        r = req(client2, referer="https://partner.example/page")
        check("allowlist terpakai juga untuk Referer", r.status_code == 200,
              f"got {r.status_code}")
        r = req(client2, origin="null")
        check("Origin null tetap 403 walau allowlist ada (null bukan origin valid)",
              r.status_code == 403, f"got {r.status_code}")
    del os.environ["DIP_ALLOWED_ORIGINS"]

    # ===== 6. Multipart POST besar utuh =====
    app3, state3 = make_app()
    client3 = TestClient(app3, base_url=f"http://{HOST}")
    with client3:
        payload = os.urandom(3_000_000)
        buf = io.BytesIO(payload)
        r = req(client3, path="/upload",
                files={"file": ("big.pdf", buf, "application/octet-stream")},
                origin=same_origin())
        check("multipart 3 MB sampai handler utuh",
              r.status_code == 200 and len(state3["received"]) == 3_000_000,
              f"got {r.status_code}, size={len(state3['received'])}")

    # ===== 7. App nyata: 403 membawa security headers + Referrer-Policy same-origin =====
    # Pola sama seperti test_auth_matrix.py: import app.main dengan env dummy.
    # Di working tree lokal yang punya file .env, guard G-11 menolak import
    # (kondisi terduga; bukan kegagalan test) — di-skip dengan catatan.
    # Di clone bersih (CI, tanpa .env) test ini JALAN.
    try:
        from app.main import app as real_app  # noqa: E402
        real_client = TestClient(real_app, base_url=f"http://{HOST}", follow_redirects=False)
        with real_client:
            r = real_client.post(
                "/login",
                data={"username": "admin", "password": "x"},
                headers={"Origin": "https://evil.example"},
            )
            check("app nyata: POST /login Origin asing => 403", r.status_code == 403,
                  f"got {r.status_code}")
            check("app nyata: 403 membawa X-Frame-Options: SAMEORIGIN",
                  r.headers.get("X-Frame-Options") == "SAMEORIGIN",
                  f"got {r.headers.get('X-Frame-Options')!r}")
            check("app nyata: 403 membawa X-Content-Type-Options: nosniff",
                  r.headers.get("X-Content-Type-Options") == "nosniff",
                  f"got {r.headers.get('X-Content-Type-Options')!r}")
            check("app nyata: 403 membawa Referrer-Policy: same-origin",
                  r.headers.get("Referrer-Policy") == "same-origin",
                  f"got {r.headers.get('Referrer-Policy')!r}")

            r = real_client.post(
                "/login",
                data={"username": "admin", "password": "x"},
                headers={"Origin": "null"},
            )
            check("app nyata: POST /login Origin null => 403", r.status_code == 403,
                  f"got {r.status_code}")

            r = real_client.post(
                "/login",
                data={"username": "admin", "password": "x"},
                headers={"Origin": "http://localhost:8017", "Referer": "http://localhost:8017/login"},
            )
            check("app nyata: POST /login Origin same => lolos guard (bukan 403)",
                  r.status_code != 403,
                  f"got {r.status_code} (harus bukan 403 guard)")
    except RuntimeError as exc:
        if "DIP_APP_ENV" in str(exc) or ".env" in str(exc):
            print(f"SKIP app-nyata tests: {exc} (file .env lokal; test jalan di clone bersih/CI)")
        else:
            raise

    # ===== 8. Unit test SecurityHeadersMiddleware: nilai Referrer-Policy =====
    # SecurityHeadersMiddleware diimpor dari app.main (sama dengan section 7).
    # Di working tree lokal yang punya .env, di-skip dengan catatan; di CI jalan.
    try:
        from starlette.testclient import TestClient as _STC  # noqa: E402
        from app.main import SecurityHeadersMiddleware  # noqa: E402

        hdr_app = FastAPI()

        @hdr_app.post("/probe")
        async def probe():
            return {"ok": True}

        hdr_app.add_middleware(SecurityHeadersMiddleware)
        hdr_client = _STC(hdr_app, base_url=f"http://{HOST}")
        with hdr_client:
            r = hdr_client.post("/probe")
            check("SecurityHeaders: Referrer-Policy == same-origin",
                  r.headers.get("Referrer-Policy") == "same-origin",
                  f"got {r.headers.get('Referrer-Policy')!r}")
            check("SecurityHeaders: X-Frame-Options == SAMEORIGIN",
                  r.headers.get("X-Frame-Options") == "SAMEORIGIN",
                  f"got {r.headers.get('X-Frame-Options')!r}")
            check("SecurityHeaders: X-Content-Type-Options == nosniff",
                  r.headers.get("X-Content-Type-Options") == "nosniff",
                  f"got {r.headers.get('X-Content-Type-Options')!r}")
    except RuntimeError as exc:
        if "DIP_APP_ENV" in str(exc) or ".env" in str(exc):
            print(f"SKIP SecurityHeaders tests: {exc} (file .env lokal; test jalan di clone bersih/CI)")
        else:
            raise

    # ===== 9. Log tanpa query string / cookie =====
    records: list[logging.LogRecord] = []

    class _Cap(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    cap = _Cap(level=logging.WARNING)
    dip_csrf_logger = logging.getLogger("dip.csrf")
    old_level = dip_csrf_logger.level
    dip_csrf_logger.addHandler(cap)
    dip_csrf_logger.setLevel(logging.WARNING)
    try:
        app5, _ = make_app()
        client5 = TestClient(app5, base_url=f"http://{HOST}")
        with client5:
            r = client5.post("/x?access=TOKENRAHASIA", headers={
                "Origin": "https://evil.example",
                "Cookie": "access_token=Bearersessionsecret; greeting_cache=abc",
            })
            check("log: request ditolak 403", r.status_code == 403)
            check("log: record warning dibuat", len(records) >= 1, f"got {len(records)}")
            if records:
                msg = records[0].getMessage()
                path_part = msg.split("path=")[1].split(" ")[0] if "path=" in msg else ""
                check("log tanpa query string",
                      "access=" not in msg and "?" not in path_part,
                      f"got: {msg!r}")
                check("log tanpa cookie",
                      "access_token" not in msg and "Bearer" not in msg,
                      f"got: {msg!r}")
                check("log menyebut host Origin (bukan nilai penuh)",
                      "evil.example" in msg, f"got: {msg!r}")
    finally:
        dip_csrf_logger.removeHandler(cap)
        dip_csrf_logger.setLevel(old_level)

    # ===== 10. Method override tidak dipakai aplikasi =====
    app6, _ = make_app()
    client6 = TestClient(app6, base_url=f"http://{HOST}")
    with client6:
        r = req(client6, headers={"X-HTTP-Method-Override": "DELETE"}, origin=same_origin())
        check("method override: handler tetap menerima POST",
              r.status_code == 200, f"got {r.status_code}")
        r = req(client6, headers={"X-HTTP-Method-Override": "PUT"})
        check("method override: non-browser (tanpa Origin) tetap lolos guard",
              r.status_code == 200, f"got {r.status_code}")

    # ===== 11. Path exempt tidak ada: /login dan heartbeat tetap diperiksa =====
    check("inventaris: /login tidak ada di EXEMPT_PATHS", "/login" not in EXEMPT_PATHS)
    check("inventaris: /api/presence/heartbeat tidak ada di EXEMPT_PATHS",
          "/api/presence/heartbeat" not in EXEMPT_PATHS)

    print()
    if FAILED:
        print(f"CSRF GUARD: {len(PASSED)} PASS, {len(FAILED)} FAIL")
        return 1
    print(f"CSRF GUARD: semua {len(PASSED)} kasus LULUS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
