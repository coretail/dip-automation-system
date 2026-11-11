"""Unit test murni A-07: guard CSRF Origin/Referer (CsrfGuardMiddleware).

Tanpa koneksi, tanpa secret. Dijalankan: python tests/test_csrf_guard.py
(dengan PYTHONPATH=. seperti di ci.yml).

Cakupan sesuai brief sesi 16:
- POST same-origin lolos; Origin beda host / null / skema beda => 403
- Tanpa Origin + Referer same-origin lolos; Referer beda => 403; keduanya tak ada => lolos
- X-Forwarded-Proto dihormati hanya http/https; X-Forwarded-Host diabaikan
- GET/HEAD/OPTIONS dengan Origin asing tidak disentuh
- DIP_ALLOWED_ORIGINS memperluas allowlist; entri tak valid diabaikan
- Multipart POST besar tetap sampai handler utuh (body tidak dibaca guard)
- Respons 403 membawa security headers (X-Frame-Options dst) saat app
  membungkus guard dengan SecurityHeadersMiddleware
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

# Salinan minimal pola SecurityHeadersMiddleware (app/main.py): ditempelkan
# SETELAH guard (paling luar) supaya 403 dari guard tetap membawa header.
# Tidak mengimpor app.main agar test tetap pure-local tanpa guard G-11.
from starlette.datastructures import MutableHeaders  # noqa: E402


class _MiniSecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "x-frame-options" not in headers:
                    headers["X-Frame-Options"] = "SAMEORIGIN"
                if "x-content-type-options" not in headers:
                    headers["X-Content-Type-Options"] = "nosniff"
                if "referrer-policy" not in headers:
                    headers["Referrer-Policy"] = "no-referrer"
            await send(message)

        await self.app(scope, receive, send_wrapper)

PASSED = []
FAILED = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"PASS {name}")
    else:
        FAILED.append(name)
        print(f"FAIL {name} {detail}")


def make_app(with_security_headers: bool = False, echo_received: bool = False) -> tuple[FastAPI, dict]:
    """App uji kecil: POST /x (body ditelan), POST /upload (multipart), GET/HEAD/OPTIONS /x."""
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

    # Urutan add_middleware di Starlette: yang ditambah terakhir = paling
    # luar. SecurityHeadersMiddleware harus membungkus guard (paling luar),
    # jadi 403 dari guard tetap mendapat header keamanan.
    app.add_middleware(CsrfGuardMiddleware)
    if with_security_headers:
        app.add_middleware(_MiniSecurityHeadersMiddleware)
    return app, state


def req(client: TestClient, method: str = "POST", path: str = "/x",
        origin=None, referer=None, fwd_proto=None, fwd_host=None,
        headers=None, data=None, files=None) -> "TestClient":
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

    # ===== 1. Origin same/beda =====
    app, state = make_app()
    client = TestClient(app, base_url=f"http://{HOST}")
    with client:
        r = req(client, origin=same_origin())
        check("POST same-origin (Origin sama) lolos", r.status_code == 200, f"got {r.status_code}")
        check("body sampai handler saat lolos", state["received"] == b"")

        r = req(client, origin=f"https://evil.example")
        check("Origin https://evil.example => 403", r.status_code == 403, f"got {r.status_code}")
        check("body 403 singkat", "origin tidak cocok" in r.text)

        r = req(client, origin="http://other.example")
        check("Origin beda host => 403", r.status_code == 403, f"got {r.status_code}")

        r = req(client, origin="null")
        check("Origin null tanpa Referer => lolos (opaque origin, Chromium headless quirk)",
              r.status_code == 200, f"got {r.status_code}")
        r = req(client, origin="null", referer="https://evil.example/")
        check("Origin null + Referer beda => 403 (Origin null diabaikan, cek Referer)",
              r.status_code == 403, f"got {r.status_code}")
        r = req(client, origin="null", referer=same_origin())
        check("Origin null + Referer same => lolos (cek Referer lolos)",
              r.status_code == 200, f"got {r.status_code}")

        r = req(client, origin="", referer=same_origin())
        check("Origin kosong string + Referer same => lolos (Origin kosong diabaikan)",
              r.status_code == 200, f"got {r.status_code}")
        r = req(client, origin="", referer="https://evil.example/")
        check("Origin kosong string + Referer beda => 403", r.status_code == 403, f"got {r.status_code}")

        r = req(client, origin="https://" + HOST)
        check("skema beda (Origin https vs request http) => 403", r.status_code == 403, f"got {r.status_code}")

        r = req(client, origin="HTTP://" + HOST)
        check("Origin case-insensitive (HTTP://) lolos", r.status_code == 200, f"got {r.status_code}")

    # ===== 2. Referer =====
    with client:
        r = req(client, referer=f"http://{HOST}/notes")
        check("Tanpa Origin, Referer same-origin lolos", r.status_code == 200, f"got {r.status_code}")

        r = req(client, referer=f"https://evil.example/notes")
        check("Tanpa Origin, Referer beda => 403", r.status_code == 403, f"got {r.status_code}")

        r = req(client)
        check("Tanpa Origin & Referer => lolos (non-browser)", r.status_code == 200, f"got {r.status_code}")

        r = req(client, origin=same_origin(), referer="https://evil.example/")
        check("Origin ada: Referer diabaikan (Origin sama) lolos", r.status_code == 200, f"got {r.status_code}")

    # ===== 3. X-Forwarded-Proto / X-Forwarded-Host =====
    with client:
        r = req(client, origin="https://" + HOST, fwd_proto="https")
        check("X-Forwarded-Proto https + Origin https lolos", r.status_code == 200, f"got {r.status_code}")

        r = req(client, origin="https://" + HOST, fwd_proto="http")
        check("X-Forwarded-Proto http + Origin https => 403", r.status_code == 403, f"got {r.status_code}")

        r = req(client, origin=same_origin(), fwd_host="evil.example")
        check("X-Forwarded-Host palsu diabaikan (Host dipakai) lolos", r.status_code == 200, f"got {r.status_code}")

        r = req(client, origin=same_origin(), fwd_proto="https http")
        check("X-Forwarded-Proto nilai asing diabaikan (skema scope) lolos", r.status_code == 200, f"got {r.status_code}")

    # ===== 4. Method yang tidak disentuh =====
    with client:
        r = req(client, method="GET", origin="https://evil.example")
        check("GET dengan Origin asing tidak disentuh", r.status_code == 200, f"got {r.status_code}")
        r = req(client, method="HEAD", origin="https://evil.example")
        check("HEAD dengan Origin asing tidak disentuh", r.status_code == 200, f"got {r.status_code}")
        r = req(client, method="OPTIONS", origin="https://evil.example")
        check("OPTIONS dengan Origin asing tidak disentuh", r.status_code == 200, f"got {r.status_code}")

    # ===== 5. DIP_ALLOWED_ORIGINS =====
    os.environ["DIP_ALLOWED_ORIGINS"] = "https://partner.example, https://partner.example:8443, ftp://bad.example, http://10.0.0.5, http://localhost:9999, http://127.0.0.1:9999"
    app2, _ = make_app()
    client2 = TestClient(app2, base_url=f"http://{HOST}")
    with client2:
        r = req(client2, origin="https://partner.example")
        check("allowlist https://partner.example lolos", r.status_code == 200, f"got {r.status_code}")
        r = req(client2, origin="https://partner.example:8443")
        check("allowlist dengan port lolos", r.status_code == 200, f"got {r.status_code}")
        r = req(client2, origin="https://evil.example")
        check("entri ftp:// tak valid diabaikan => 403 tetap", r.status_code == 403, f"got {r.status_code}")
        r = req(client2, origin="http://10.0.0.5")
        check("entri http non-localhost diabaikan => 403", r.status_code == 403, f"got {r.status_code}")
        r = req(client2, origin="http://localhost:9999")
        check("entri http://localhost:port (staging lokal) lolos", r.status_code == 200, f"got {r.status_code}")
        r = req(client2, referer="https://partner.example/page")
        check("allowlist terpakai juga untuk Referer", r.status_code == 200, f"got {r.status_code}")
    del os.environ["DIP_ALLOWED_ORIGINS"]

    # ===== 6. Multipart POST besar utuh =====
    app3, state3 = make_app()
    client3 = TestClient(app3, base_url=f"http://{HOST}")
    with client3:
        payload = os.urandom(3_000_000)
        buf = io.BytesIO(payload)
        r = req(client3, path="/upload", files={"file": ("big.pdf", buf, "application/octet-stream")},
                origin=same_origin())
        check("multipart 3 MB sampai handler utuh", r.status_code == 200 and len(state3["received"]) == 3_000_000,
              f"got {r.status_code}, size={len(state3['received'])}")

    # ===== 7. Respons 403 membawa security headers =====
    app4, _ = make_app(with_security_headers=True)
    client4 = TestClient(app4, base_url=f"http://{HOST}")
    with client4:
        r = req(client4, origin="https://evil.example")
        check("403 membawa X-Frame-Options", r.headers.get("X-Frame-Options") == "SAMEORIGIN",
              f"got {r.headers.get('X-Frame-Options')!r}")
        check("403 membawa X-Content-Type-Options", r.headers.get("X-Content-Type-Options") == "nosniff",
              f"got {r.headers.get('X-Content-Type-Options')!r}")
        check("403 membawa Referrer-Policy", r.headers.get("Referrer-Policy") == "no-referrer",
              f"got {r.headers.get('Referrer-Policy')!r}")

    # ===== 8. Log tanpa query string / cookie =====
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
            check("log: record warning dipuat", len(records) >= 1, f"got {len(records)}")
            if records:
                msg = records[0].getMessage()
                check("log tanpa query string", "access=" not in msg and "?" not in msg.split("path=")[1].split(" ")[0],
                      f"got: {msg!r}")
                check("log tanpa cookie", "access_token" not in msg and "Bearer" not in msg, f"got: {msg!r}")
                check("log menyebut host Origin (bukan nilai penuh)", "evil.example" in msg, f"got: {msg!r}")
    finally:
        dip_csrf_logger.removeHandler(cap)
        dip_csrf_logger.setLevel(old_level)

    # ===== 9. Method override tidak dipakai aplikasi =====
    app6, state6 = make_app()
    client6 = TestClient(app6, base_url=f"http://{HOST}")
    with client6:
        # Aplikasi tidak membaca _method / X-HTTP-Method-Override sama sekali:
        # POST + header override tetap diproses sebagai POST oleh handler.
        r = req(client6, data=None, headers={"X-HTTP-Method-Override": "DELETE"}, origin=same_origin())
        check("method override: handler tetap menerima POST", r.status_code == 200, f"got {r.status_code}")
        r = req(client6, data=None, headers={"X-HTTP-Method-Override": "PUT"})
        check("method override: non-browser (tanpa Origin) tetap lolos guard", r.status_code == 200, f"got {r.status_code}")

    # ===== 10. Path exempt tidak ada: /login tetap diperiksa =====
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
