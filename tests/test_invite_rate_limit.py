"""Pure-local tests rate limit /activate (429 + Retry-After) & /admin/users/invite (Task 4).

Dijalankan: python tests/test_invite_rate_limit.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

os.environ.setdefault("SUPABASE_URL", "https://ci.invalid.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "ci-dummy-service-role-key")
os.environ.setdefault("SUPABASE_KEY", "ci-dummy-anon-key")
os.environ.setdefault("STORAGE_BACKEND", "supabase")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app.admin_users_routes as aur  # noqa: E402
from app.activate_routes import (  # noqa: E402
    ACTIVATE_GET_LIMIT,
    ACTIVATE_POST_LIMIT,
    activate_rate_limit_response,
    register_activate_routes,
)
from app.admin_users_routes import register_admin_users_routes  # noqa: E402
from app.client_ip import client_ip_from  # noqa: E402
from app.mailer import mask_email  # noqa: E402

FAILURES = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def _client_ip(request):
    client_host = request.client.host if request.client else "-"
    return client_ip_from(request.headers, client_host, trusted_hops=1)


def _limit_num(spec: str) -> int:
    m = re.search(r"(\d+)", spec)
    return int(m.group(1)) if m else 10


def _build_app():
    app = FastAPI()
    limiter = Limiter(key_func=_client_ip)
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def _handler(request, _exc):
        if request.url.path == "/activate":
            return activate_rate_limit_response(request)
        return JSONResponse(status_code=429, content={"detail": "rate_limited"}, headers={"Retry-After": "60"})

    sb = SimpleNamespace()
    templates = Jinja2Templates(directory="app/templates")
    register_activate_routes(
        app,
        supabase=sb,
        templates=templates,
        log_activity=lambda *a, **k: None,
        mask_email=mask_email,
        limiter=limiter,
        verify_client_factory=lambda: SimpleNamespace(),
    )

    aur.settings = SimpleNamespace(app_base_url="")

    async def _fake_admin(_request: Request):
        return {"id": "admin-1", "role": "admin", "full_name": "admin", "email": "a@b.com"}

    register_admin_users_routes(
        app,
        get_current_user=_fake_admin,
        supabase=sb,
        templates=templates,
        log_activity=lambda *a, **k: None,
        compute_user_presence=lambda _p: {},
        mask_email=mask_email,
        _user_label=lambda uid: uid,
        _user_role_and_label=lambda uid: ("staff", uid),
        get_ed_notification_count=lambda: 0,
        compute_status_na=None,
        limiter=limiter,
    )
    return TestClient(app, follow_redirects=False)


def test_activate_get_rate_limit():
    client = _build_app()
    n = _limit_num(ACTIVATE_GET_LIMIT)
    tok = "secret-tok-get-429"
    for _ in range(n):
        r = client.get(
            f"/activate?token_hash={tok}&type=invite",
            headers={"x-forwarded-for": "10.10.1.1", "accept": "text/html"},
        )
        check("GET di bawah limit -> 200", r.status_code == 200) if _ == 0 else None
    r_429 = client.get(
        f"/activate?token_hash={tok}&type=invite",
        headers={"x-forwarded-for": "10.10.1.1", "accept": "text/html"},
    )
    check("GET ke-21 -> 429", r_429.status_code == 429, str(r_429.status_code))
    check("GET 429 -> Retry-After: 60", r_429.headers.get("retry-after") == "60")
    check("GET 429 -> Cache-Control: no-store", r_429.headers.get("cache-control") == "no-store")
    check("GET 429 -> X-Robots-Tag: noindex, nofollow", r_429.headers.get("x-robots-tag") == "noindex, nofollow")
    check("GET 429 -> bukan redirect /login", "/login" not in str(r_429.headers.get("location", "")))
    check("GET 429 -> token tidak bocor di body", tok not in r_429.text)


def test_activate_post_rate_limit():
    client = _build_app()
    n = _limit_num(ACTIVATE_POST_LIMIT)
    tok = "secret-tok-post-429"
    for i in range(n):
        r = client.post(
            "/activate",
            data={"token_hash": tok, "type": "invite", "password": "123", "confirm_password": "123"},
            headers={"x-forwarded-for": "10.10.2.2", "accept": "text/html"},
        )
        if i == 0:
            check("POST validasi gagal di bawah limit -> 400", r.status_code == 400)
    r_429 = client.post(
        "/activate",
        data={"token_hash": tok, "type": "invite", "password": "123", "confirm_password": "123"},
        headers={"x-forwarded-for": "10.10.2.2", "accept": "text/html"},
    )
    check("POST ke-11 -> 429", r_429.status_code == 429, str(r_429.status_code))
    check("POST 429 -> Retry-After: 60", r_429.headers.get("retry-after") == "60")
    check("POST 429 -> bukan redirect /login", "/login" not in str(r_429.headers.get("location", "")))
    check("POST 429 -> token tidak bocor di body", tok not in r_429.text)

    r_other_ip = client.post(
        "/activate",
        data={"token_hash": tok, "type": "invite", "password": "123", "confirm_password": "123"},
        headers={"x-forwarded-for": "10.10.2.99", "accept": "application/json"},
    )
    check("POST IP berbeda tidak ikut terkunci", r_other_ip.status_code == 400, str(r_other_ip.status_code))


def test_invite_endpoint_rate_limit():
    client = _build_app()
    for i in range(3):
        r = client.post(
            "/admin/users/invite",
            data={"email": "x@example.com"},
            headers={"x-forwarded-for": "10.10.3.3"},
        )
        if i == 0:
            check("invite ke-1 lolos limit (303)", r.status_code == 303, str(r.status_code))
    r_4 = client.post(
        "/admin/users/invite",
        data={"email": "x@example.com"},
        headers={"x-forwarded-for": "10.10.3.3"},
    )
    check("invite ke-4 -> 429", r_4.status_code == 429, str(r_4.status_code))


def test_main_rate_limit_handler_routes_activate():
    src = Path("app/main.py").read_text(encoding="utf-8")
    seg = src[src.index("async def rate_limit_handler"):]
    seg = seg[:seg.index("\n\n") + 1]
    check("main rate_limit_handler menangani /activate",
          'request.url.path == "/activate"' in seg and "activate_rate_limit_response" in seg)
    check("main rate_limit_handler tetap mempertahankan /dip/ dan /login",
          'startswith("/dip/")' in seg and '/login?error=too_many_attempts' in seg)


def main():
    test_activate_get_rate_limit()
    test_activate_post_rate_limit()
    test_invite_endpoint_rate_limit()
    test_main_rate_limit_handler_routes_activate()

    print()
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} pemeriksaan")
        sys.exit(1)
    print("OK: semua pemeriksaan rate limit invite/activate lolos")


if __name__ == "__main__":
    main()
