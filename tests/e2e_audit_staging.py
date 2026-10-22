"""E2E audit staging: verifikasi temuan audit 2026-10-21 lewat browser nyata.

HANYA untuk staging lokal. Menolak jalan bila base URL bukan localhost atau
.env.staging gagal preflight (`app.staging_preflight.validate_staging_file`).
TIDAK menyentuh prod (kecuali subset read-only eksplisit via --allow-production).
Tidak mencetak secret.

Sumber kebenaran: `catatan/catatan_audit_codebase_2026-10-21.md`
  - Sec. 4 Security (SEC-01..SEC-18), Sec. 5 Frontend/polling (FE-01..FE-17),
  - Sec. 6 Backend (BE-01..BE-26), Sec. 10 Prioritas.
Skrip ini hanya menguji hal yang bisa diamati dari browser: markup/cookie,
request jaringan, navigasi, dan respons endpoint. Isi kode tidak diuji.

Kredensial (JANGAN di-hardcode, JANGAN di-commit, JANGAN dicetak):
    STAGING_ADMIN_EMAIL / STAGING_ADMIN_PASSWORD  -> akun admin staging
    E2E_EMAIL / E2E_PASSWORD                      -> alias untuk akun di atas
    E2E_HEKA_EMAIL / E2E_HEKA_PASSWORD            -> akun tenant PT Heka (opsional;
                                                      mengaktifkan grup D multi-tenant)
    STAGING_BASE_URL                               -> default http://127.0.0.1:8017
Password tidak pernah dicetak; identitas ditampilkan tersamar (huruf pertama
local-part + domain), password ditampilkan sebagai "***".
Nilai kredensial admin ada di LOGIN.md di root repo (git-ignored): export jadi env var di shell yang menjalankan skrip ini, jangan di-hardcode; kredensial tenant opsional E2E_HEKA_* tidak ada di LOGIN.md.

Exit code:
    0 = tidak ada FAIL (KNOWN yang masih diharapkan tidak dianggap kegagalan)
    1 = ada minimal satu FAIL (atau ada KNOWN bila --strict)
    2 = lingkungan tidak bisa dipakai: server mati / kredensial tidak ada /
        chromium tidak terpasang / base URL non-lokal tanpa --allow-production /
        guard preflight .env.staging gagal.

Mekanisme hasil (dua tier, supaya suite hijau sejak hari pertama):
    [PASS]   sesuai harapan
    [KNOWN]  temuan audit yang memang masih gagal -> baseline, BUKAN kegagalan
    [FAIL]   regresi, atau temuan yang seharusnya sudah benar
    [SKIP]   tidak dijalankan (mis. kredensial tenant kedua tidak tersedia)
--strict menjadikan KNOWN ikut dihitung sebagai FAIL.

Ringkasan yang diuji:
    A. Autentikasi & sesi        (FE-11, FE-12, FE-13, SEC-04, SEC-16)
    B. Polling & presence         (FE-01..FE-07, FE-11, FE-15)
    C. Halaman & rute bermasalah  (SEC-01, BE-04, BE-21, SEC-15, SEC-09, SEC-12)
       C1 (SEC-01) sekarang READ-ONLY: route soft-delete dicek dengan probe GET
       pada UUID acak (harus 405), form hapus dicek hanya dari HTML dashboard,
       dan form TIDAK PERNAH di-submit - tidak ada data yang dibuat/diubah/dihapus.
    D. Multi-tenant               (SEC-02, BE-07, BE-18, BE-19) - opsional
    E. XSS regression             (Sec. 4.1 "pemeriksaan nihil")
    F. Polling setelah sesi expired (FE-12, FE-13)

Prasyarat (sekali):
    pip install playwright supabase python-dotenv httpx
    playwright install chromium

Jalankan (staging harus hidup, mis. scripts/run_staging_8017.py):
    $env:STAGING_ADMIN_EMAIL="akun@staging"; $env:STAGING_ADMIN_PASSWORD="rahasia"
    venv\Scripts\python.exe tests\e2e_audit_staging.py [--quick|--full] [--strict]

Runtime:
    --full (default)  ~4 menit  (jeda polling 65s + 30s + 30s + 35s)
    --quick           ~1,5 menit (jeda polling panjang dilewati: B1-B3, F1)

Catatan teknis (ditemukan saat eksekusi 2026-10-21): headless Chromium
menunda timer halaman yang tidak terlihat sehingga interval polling 25/30
detik bisa baru menyala setelah ~40 detik. Semua jeda polling panjang memakai
helper keep_alive() yang evaluates berkala supaya cadence bisa diukur akurat.

Catatan rate limit: POST /login dibatasi 5/menit per IP (app/main.py:1051).
Karena itu skrip login SATU KALI, menyimpan storage_state, lalu memakai
BrowserContext BARU (dengan storage_state yang sama) untuk tiap grup sehingga
cookie tidak bocor antar grup tapi tidak ada login berulang.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlparse

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.staging"

RESULTS: list[tuple[str, str, str]] = []      # (nama, status, detail)
CONSOLE_ERRORS: list[tuple[str, str]] = []    # (label, teks)
PAGE_ERRORS: list[tuple[str, str]] = []       # (label, teks)
DIALOGS: list[str] = []

# Temuan audit yang saat ini memang masih gagal -> baseline [KNOWN], bukan FAIL.
KNOWN_ISSUES = {
    "SEC-02": "Isolasi tenant nyaris tidak ada: assert_same_tenant tidak di-import modul "
              "mana pun -> daftar & tulis lintas badan hukum lolos.",
    "SEC-04": "Cookie sesi access_token (dan greeting_cache) diset tanpa secure=True.",
    "SEC-12": "login.html & public_error.html memuat Tailwind Play CDN v3 (EOL) sementara "
              "halaman aplikasi memuat Tailwind v4 (browser build).",
    "BE-04": ".single() dijalankan di luar try pada 4 route raw-materials -> HTTP 500 "
             "untuk baris yang tidak ada, bukan pesan 'tidak ditemukan'.",
    "BE-21": "Cookie warning_msg diset oleh route tetapi tidak pernah dirender di template "
             "mana pun (grep app/ hanya menemukan 1 kemunculan = produsernya).",
    "FE-05": "Link logout di sidebar tidak memanggil stopPresenceHeartbeat -> heartbeat "
             "in-flight bisa menulis is_online=true setelah /logout.",
    "FE-06": "window.__adminPresenceInterval tidak pernah di-assign -> jalur cleanup di "
             "base.html:44 mati.",
}

ERROR_MARKERS = ("Internal Server Error", "Traceback (most recent call last)", "NameError")


# --------------------------------------------------------------------------- #
# Helper hasil
# --------------------------------------------------------------------------- #
def check(name: str, ok: bool, detail: str = "", known: str | None = None) -> bool:
    """Catat satu hasil: [PASS] / [KNOWN] (baseline) / [FAIL].

    `known` diisi bila kegagalan yang diharapkan memang sudah didokumentasikan
    di audit -> hasilnya [KNOWN] (tidak dianggap kegagalan), bukan [FAIL].
    """
    if ok:
        status, label, out = "PASS", "PASS", detail
    elif known:
        status, label = "KNOWN", "KNOWN"
        out = f"{detail} | known: {known}" if detail else f"known: {known}"
    else:
        status, label, out = "FAIL", "FAIL", detail
    RESULTS.append((name, status, out))
    print(f"[{label}] {name}" + (f" - {out}" if out else ""))
    return bool(ok)


def skip(name: str, why: str) -> None:
    RESULTS.append((name, "SKIP", why))
    print(f"[SKIP] {name} - {why}")


def info(name: str, detail: str) -> None:
    print(f"[INFO] {name} - {detail}")


def mask_email(email: str) -> str:
    """Tampilkan identitas tersamar: huruf pertama local-part + domain."""
    raw = (email or "").strip()
    if "@" not in raw:
        return (raw[:1] + "***") if raw else "***"
    local, _, domain = raw.partition("@")
    return f"{local[:1] or '*'}***@{domain}"


def summarize(strict: bool) -> int:
    counts = {"PASS": 0, "KNOWN": 0, "FAIL": 0, "SKIP": 0}
    for _, status, _ in RESULTS:
        counts[status] = counts.get(status, 0) + 1
    print("\n=== RINGKASAN ===")
    for name, status, detail in RESULTS:
        if status in ("KNOWN", "FAIL"):
            print(f"  {status}: {name}" + (f" - {detail[:160]}" if detail else ""))
    print(f"PASS={counts['PASS']} KNOWN={counts['KNOWN']} "
          f"FAIL={counts['FAIL']} SKIP={counts['SKIP']}")
    bad = counts["FAIL"] + (counts["KNOWN"] if strict else 0)
    if strict and counts["KNOWN"]:
        print(f"--strict: {counts['KNOWN']} temuan KNOWN dihitung sebagai kegagalan")
    return 1 if bad else 0

# --------------------------------------------------------------------------- #
# Guard: staging-only + kredensial
# --------------------------------------------------------------------------- #
def is_local(base_url: str) -> bool:
    return (urlparse(base_url).hostname or "") in ("127.0.0.1", "localhost")


def load_staging_cfg(base_url: str) -> dict:
    """Muat .env.staging lewat preflight resmi (fail-closed)."""
    if not ENV_FILE.exists():
        print(f"[ABORT] {ENV_FILE.name} tidak ditemukan -> exit 2")
        sys.exit(2)
    sys.path.insert(0, str(ROOT))
    from app.staging_preflight import parse_dotenv_file, validate_staging_file

    cfg = parse_dotenv_file(str(ENV_FILE))
    try:
        validate_staging_file(cfg, caller="e2e-audit-staging")
    except RuntimeError as exc:
        print(f"[ABORT] guard staging gagal: {exc} -> exit 2")
        sys.exit(2)
    print(f"[INFO] preflight .env.staging PASS (host staging, tanpa secret). base URL {base_url}")
    return cfg


def db_client(cfg: dict):
    """Klien Supabase service-role. HANYA dipakai untuk SELECT read-only."""
    from supabase import create_client

    return create_client(cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_ROLE_KEY"])


def load_credentials() -> tuple[str, str]:
    email = (os.getenv("STAGING_ADMIN_EMAIL") or os.getenv("E2E_EMAIL") or "").strip()
    password = os.getenv("STAGING_ADMIN_PASSWORD") or os.getenv("E2E_PASSWORD") or ""
    if not (email and password):
        print("[SKIP] credential tidak tersedia")
        print("       set STAGING_ADMIN_EMAIL + STAGING_ADMIN_PASSWORD "
              "(atau E2E_EMAIL + E2E_PASSWORD) -> exit 2")
        sys.exit(2)
    print(f"[INFO] identitas login: {mask_email(email)} / password: ***")
    return email, password


def second_tenant_credentials() -> tuple[str, str] | None:
    email = (os.getenv("E2E_HEKA_EMAIL") or "").strip()
    password = os.getenv("E2E_HEKA_PASSWORD") or ""
    if not (email and password):
        return None
    return email, password


# --------------------------------------------------------------------------- #
# Helper browser
# --------------------------------------------------------------------------- #
def new_page(ctx, label: str):
    """Page baru dengan timeout eksplisit + penangkap error console/page."""
    page = ctx.new_page()
    page.set_default_timeout(15000)
    page.on("console", lambda m: CONSOLE_ERRORS.append((label, m.text))
            if m.type == "error" else None)
    page.on("pageerror", lambda e: PAGE_ERRORS.append((label, str(e))))

    def _dialog(dialog):
        DIALOGS.append(f"{label}: [{dialog.type}] {dialog.message}")
        try:
            if dialog.type == "confirm":
                dialog.accept()
            else:
                dialog.dismiss()
        except Exception:  # noqa: BLE001
            pass

    page.on("dialog", _dialog)
    return page


def wait_idle(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:  # noqa: BLE001
        pass


def keep_alive(page, seconds: int, step: float = 3.0) -> None:
    """Jaga renderer tetap aktif selama `seconds` detik.

    Headless Chromium menunda timer halaman yang tidak terlihat (timer di-align
    ke batas menit), sehingga interval polling 25/30 detik bisa baru menyala
    setelah ~40 detik - atau tidak sama sekali. evaluate() berkala memaksa
    renderer memproses antrean timer, sehingga cadence polling bisa diukur
    akurat. Tanpa ini, B1/B2/F1 akan salah menyimpulkan polling mati.
    """
    end = time.time() + seconds
    while time.time() < end:
        try:
            page.evaluate("() => 1")
        except Exception:  # noqa: BLE001
            pass
        remaining = end - time.time()
        if remaining <= 0:
            break
        time.sleep(min(step, remaining))


def set_cookie_attrs(raw: str, name: str) -> dict | None:
    """Parse atribut satu Set-Cookie dari header mentah (multi-header join newline)."""
    for line in (raw or "").split("\n"):
        line = line.strip()
        if not line.startswith(name + "="):
            continue
        parts = [p.strip() for p in line.split(";")]
        attrs: dict = {}
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                attrs[k.strip().lower()] = v.strip()
            else:
                attrs[part.lower()] = True
        return attrs
    return None


def decode_jwt_claims(raw: str) -> dict:
    """Decode payload JWT tanpa verifikasi signature (persis seperti app)."""
    token = (raw or "").replace("Bearer ", "").strip()
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    try:
        pad = "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(parts[1] + pad).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def login_via_form(browser, base_url: str, email: str, password: str, label: str):
    """Login lewat form /login. Return (ctx, page, header_set_cookie)."""
    ctx = browser.new_context(base_url=base_url)
    page = new_page(ctx, label)
    page.goto("/login")
    wait_idle(page)
    page.fill("input[name=email]", email)
    page.fill("input[name=password]", password)
    raw_cookie = ""
    try:
        with page.expect_response(
            lambda r: r.request.method == "POST" and urlparse(r.url).path == "/login",
            timeout=20000,
        ) as resp_info:
            page.click("#login-submit-btn")
        resp = resp_info.value
        raw_cookie = (resp.all_headers() or {}).get("set-cookie", "")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] tidak menangkap respons POST /login: {type(exc).__name__}: {exc}")
    try:
        page.wait_for_url(lambda u: "/login" not in u, timeout=30000)
        wait_idle(page)
    except Exception:  # noqa: BLE001
        pass
    return ctx, page, raw_cookie


def do_login(browser, base_url: str, email: str, password: str, label: str) -> dict:
    """Login sekali lalu simpan storage_state + fakta cookie untuk grup lain.

    Mengembalikan dict: state, raw_cookie, claims, url, is_admin.
    """
    ctx, page, raw_cookie = login_via_form(browser, base_url, email, password, label)
    if "/login" in page.url:
        reason = "rate limit login aktif" if "too_many_attempts" in page.url else "gagal login"
        print(f"[ABORT] {reason} (cek kredensial; rate limit 5/menit per IP) -> exit 2")
        ctx.close()
        sys.exit(2)
    state = ctx.storage_state()
    cookies = {c["name"]: c for c in state.get("cookies", [])}
    claims = decode_jwt_claims(cookies.get("access_token", {}).get("value", ""))
    try:
        is_admin = page.locator('a[href="/admin/users"]').count() > 0
    except Exception:  # noqa: BLE001
        is_admin = False
    url = page.url
    ctx.close()
    return {"state": state, "raw_cookie": raw_cookie, "claims": claims,
            "url": url, "is_admin": is_admin}

# --------------------------------------------------------------------------- #
# A. Autentikasi & sesi
# --------------------------------------------------------------------------- #
def group_auth(browser, base_url: str, email: str, password: str, login: dict) -> None:
    """A1..A7. Login sudah dilakukan oleh do_login() (satu kali, lalu di-reuse)."""
    state = login["state"]

    # --- A1/A2/A3: cookie sesi hasil login ---------------------------------
    ctx = browser.new_context(base_url=base_url, storage_state=state)
    cookies = {c["name"]: c for c in ctx.cookies()}
    tok = cookies.get("access_token") or {}
    check("A1 login staging -> redirect ke /", urlparse(login["url"]).path == "/",
          f"url={login['url']}")
    ok_a1 = bool(tok) and tok.get("httpOnly") is True and (tok.get("sameSite") or "").lower() == "lax"
    check("A1b cookie access_token HttpOnly=True & SameSite=Lax", ok_a1,
          f"httpOnly={tok.get('httpOnly')} sameSite={tok.get('sameSite')}")

    check("A2 cookie access_token punya atribut Secure", bool(tok.get("secure")),
          f"secure={tok.get('secure')} (diharapkan True)",
          known=KNOWN_ISSUES["SEC-04"])

    greet = cookies.get("greeting_cache") or {}
    attrs = set_cookie_attrs(login["raw_cookie"], "greeting_cache") or {}
    max_age = attrs.get("max-age")
    try:
        max_age_int = int(max_age) if max_age is not None else None
    except (TypeError, ValueError):
        max_age_int = None
    if max_age_int is None and greet.get("expires", -1) > 0:
        max_age_int = int(greet["expires"] - time.time())
    ok_a3 = (bool(greet) and greet.get("httpOnly") is True and max_age_int is not None
             and abs(max_age_int - 14400) <= 120)
    check("A3 cookie greeting_cache ada, HttpOnly, max_age ~ 14400 dtk (4 jam)", ok_a3,
          f"ada={bool(greet)} httpOnly={greet.get('httpOnly')} max_age={max_age_int}")
    ctx.close()

    # --- A4: sesi dicabut -> endpoint polling redirect 303 ke /login --------
    ctx = browser.new_context(base_url=base_url, storage_state=state)
    ctx.clear_cookies(name="access_token")
    r = ctx.request.get(base_url + "/api/notes/mentions/unread-count")
    body = r.text()
    ctype = (r.headers.get("content-type") or "").lower()
    is_html = "text/html" in ctype or "<html" in body.lower()
    is_json = ctype.startswith("application/json")
    ok_a4 = r.status == 200 and "/login" in r.url and is_html and not is_json
    check("A4 endpoint polling tanpa sesi -> redirect ke /login (bukan JSON 401)", ok_a4,
          f"status={r.status} final_url={r.url} content-type={ctype[:40]} "
          f"html={is_html} json={is_json}")
    ctx.close()

    # --- A5: konteks benar-benar tanpa cookie ------------------------------
    ctx = browser.new_context(base_url=base_url)
    r5 = ctx.request.get(base_url + "/api/notes/mentions/unread-count")
    ctype5 = (r5.headers.get("content-type") or "").lower()
    ok_a5 = r5.status == 200 and "/login" in r5.url and "application/json" not in ctype5
    check("A5 tanpa sesi sama sekali -> konfirmasi redirect (bukan JSON 401)", ok_a5,
          f"status={r5.status} final_url={r5.url} content-type={ctype5[:40]}")
    ctx.close()

    # --- A6: logout -> cookie access_token dihapus, halaman ke /login ------
    ctx = browser.new_context(base_url=base_url, storage_state=state)
    page = new_page(ctx, "A:logout")
    page.goto("/logout")
    wait_idle(page)
    after = {c["name"] for c in ctx.cookies()}
    ok_a6 = "access_token" not in after and "/login" in page.url
    check("A6 logout -> cookie access_token dihapus & halaman ke /login", ok_a6,
          f"url={page.url} sisa_cookie={sorted(after)}")
    ctx.close()

    # --- A7: pesan login gagal seragam (tidak membocorkan email terdaftar) --
    ctx = browser.new_context(base_url=base_url)
    page = new_page(ctx, "A:login-gagal")
    wrong = "E2E-" + uuid.uuid4().hex[:12] + "-salah"
    msgs: list[bool] = []
    urls: list[str] = []
    for candidate in (email, f"e2e-tidak-ada-{uuid.uuid4().hex[:8]}@example.invalid"):
        page.goto("/login")
        wait_idle(page)
        page.fill("input[name=email]", candidate)
        page.fill("input[name=password]", wrong)
        page.click("#login-submit-btn")
        try:
            page.wait_for_url(
                lambda u: "invalid_credentials" in u or "too_many_attempts" in u, timeout=20000)
        except Exception:  # noqa: BLE001
            pass
        wait_idle(page)
        urls.append(page.url)
        msgs.append(page.locator("text=Email/Username atau password salah!").count() > 0)
    uniform = (len(set(urls)) == 1 and all(msgs) and "invalid_credentials" in urls[0])
    check("A7 pesan login gagal seragam (tidak membocorkan email terdaftar)", uniform,
          f"kasus_1={urls[0].split('?')[-1] if urls else '-'} "
          f"kasus_2={urls[1].split('?')[-1] if len(urls) > 1 else '-'} "
          f"pesan_sama={msgs}")
    ctx.close()


# --------------------------------------------------------------------------- #
# B. Polling & presence
# --------------------------------------------------------------------------- #
def group_polling(browser, base_url: str, state: dict, quick: bool, is_admin: bool) -> None:
    """B1..B6."""
    # --- B1/B2/B3: hitung request polling dalam satu jendela 65 detik -----
    if quick:
        for label in ("B1 heartbeat berjalan otomatis tiap ~25 dtk",
                      "B2 badge mention terpolling tiap ~30 dtk",
                      "B3 tidak ada interval ganda heartbeat (<=3 per 60 dtk)"):
            skip(label, "mode --quick: jeda polling panjang dilewati")
    else:
        ctx = browser.new_context(base_url=base_url, storage_state=state)
        page = new_page(ctx, "B:polling")
        hb: list[str] = []
        mn: list[str] = []
        page.on("request", lambda r: hb.append(r.url) if "/api/presence/heartbeat" in r.url else None)
        page.on("request", lambda r: mn.append(r.url)
                if "/api/notes/mentions/unread-count" in r.url else None)
        page.goto("/")
        wait_idle(page)
        base_hb, base_mn = len(hb), len(mn)
        keep_alive(page, 65)
        d_hb, d_mn = len(hb) - base_hb, len(mn) - base_mn
        check("B1 heartbeat berjalan otomatis tiap ~25 dtk", d_hb >= 1,
              f"{d_hb} request /api/presence/heartbeat dalam 65 dtk")
        check("B2 badge mention terpolling tiap ~30 dtk", d_mn >= 1,
              f"{d_mn} request /api/notes/mentions/unread-count dalam 65 dtk")
        check("B3 tidak ada interval ganda heartbeat (<=3 per 60 dtk)", d_hb <= 3,
              f"{d_hb} request heartbeat dalam 65 dtk (batas <=3; 5-6 berarti dobel)")
        ctx.close()

    # --- B4: tab tidak terlihat -> heartbeat berhenti ----------------------
    ctx = browser.new_context(base_url=base_url, storage_state=state)
    page = new_page(ctx, "B:hidden")
    hb: list[str] = []
    page.on("request", lambda r: hb.append(r.url) if "/api/presence/heartbeat" in r.url else None)
    page.goto("/")
    wait_idle(page)
    page.evaluate(
        "() => Object.defineProperty(document, 'visibilityState', "
        "{value: 'hidden', configurable: true})")
    page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
    base_hb = len(hb)
    keep_alive(page, 30)
    d_hidden = len(hb) - base_hb
    check("B4 tab tidak terlihat -> heartbeat berhenti", d_hidden == 0,
          f"{d_hidden} request heartbeat selama 30 dtk setelah visibilityState='hidden'")
    ctx.close()

    # --- B5: logout lewat link sidebar -> heartbeat harus berhenti ---------
    ctx = browser.new_context(base_url=base_url, storage_state=state)
    page = new_page(ctx, "B:sidebar-logout")
    try:
        page.set_viewport_size({"width": 1400, "height": 900})
    except Exception:
        pass
    stop_calls: list[int] = []
    console_msgs: list[str] = []
    hb: list[str] = []
    page.on("request", lambda r: hb.append(r.url) if "/api/presence/heartbeat" in r.url else None)
    page.on("console", lambda m: console_msgs.append(m.text))
    try:
        page.expose_binding("__e2eNoteStop", lambda source: stop_calls.append(1))
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] expose_binding gagal: {type(exc).__name__}: {exc}")
    page.goto("/")
    wait_idle(page)
    page.evaluate(
        """() => {
          const orig = window.stopPresenceHeartbeat;
          if (typeof orig === 'function') {
            window.stopPresenceHeartbeat = function () {
              try { console.log('__E2E_STOP_HEARTBEAT__'); } catch (e) {}
              try { window.__e2eNoteStop(); } catch (e) {}
              return orig.apply(this, arguments);
            };
          }
        }"""
    )
    sidebar = page.locator("#app-sidebar a[data-logout]")
    if sidebar.count() == 0:
        skip("B5 logout via link sidebar memanggil stopPresenceHeartbeat",
             "link sidebar #app-sidebar a[data-logout] tidak ada di DOM "
             "(hanya link navbar yang memanggil stopPresenceHeartbeat)")
    else:
        handlers = page.eval_on_selector_all(
            "a[data-logout]",
            "els => els.map(e => ({sidebar: !!e.closest('#app-sidebar'), "
            "onclick: e.getAttribute('onclick') || ''}))")
        base_hb = len(hb)
        try:
            sidebar.first.click(timeout=5000)
        except Exception:  # noqa: BLE001
            page.evaluate(
                "() => { const a = document.querySelector('#app-sidebar a[data-logout]');"
                " if (a) a.click(); }")
        try:
            page.wait_for_url(lambda u: "/login" in u, timeout=20000)
        except Exception:  # noqa: BLE001
            pass
        wait_idle(page)
        d_after = len(hb) - base_hb
        called = bool(stop_calls) or any("__E2E_STOP_HEARTBEAT__" in m for m in console_msgs)
        check("B5 logout via link sidebar memanggil stopPresenceHeartbeat", called,
              f"stop_dipanggil={called} url={page.url} "
              f"heartbeat_setelah_logout={d_after} (interval ikut mati karena unload) "
              f"handler_per_link={handlers}",
              known=KNOWN_ISSUES["FE-05"])
    ctx.close()

    # --- B6: window.__adminPresenceInterval di /admin/users -----------------
    if not is_admin:
        skip("B6 window.__adminPresenceInterval ter-assign di /admin/users",
             "akun bukan admin -> /admin/users tidak bisa diakses")
    else:
        ctx = browser.new_context(base_url=base_url, storage_state=state)
        page = new_page(ctx, "B:admin-users")
        page.goto("/admin/users")
        wait_idle(page)
        if "/admin/users" not in page.url:
            skip("B6 window.__adminPresenceInterval ter-assign di /admin/users",
                 f"redirect ke {page.url}")
        else:
            val = page.evaluate("() => typeof window.__adminPresenceInterval")
            check("B6 window.__adminPresenceInterval ter-assign di /admin/users",
                  val != "undefined", f"typeof={val} (diharapkan 'number')",
                  known=KNOWN_ISSUES["FE-06"])
        ctx.close()

# --------------------------------------------------------------------------- #
# C. Halaman & rute bermasalah
# --------------------------------------------------------------------------- #
def group_pages(browser, base_url: str, state: dict, is_admin: bool = False) -> None:
    """C1..C7."""
    ctx = browser.new_context(base_url=base_url, storage_state=state)
    page = new_page(ctx, "C:rut")

    # --- C1: route soft-delete produk terdaftar (READ-ONLY) ---------------
    # Skenario ini TIDAK PERNAH submit form hapus dan TIDAK PERNAH membuat,
    # mengubah, atau menghapus produk. Route dicek dengan probe GET pada
    # UUID acak: 405 = route ADA (metodenya POST, jadi GET ditolak), sedangkan
    # 404 = route TIDAK terdaftar (gejala tombol "Hapus Produk" rusak).
    r_delete = ctx.request.get(
        base_url + f"/products/delete/{uuid.uuid4()}", max_redirects=0)
    check("C1 route POST /products/delete/{id} terdaftar (probe GET -> 405, bukan 404)",
          r_delete.status == 405,
          f"GET /products/delete/<uuid-acak> -> HTTP {r_delete.status} "
          f"(405 = route ada, method-nya POST; 404 = route tidak terdaftar)")

    # --- C1b: form hapus produk hanya untuk admin ------------------------
    page.goto("/")
    wait_idle(page)
    admin_html = page.content()
    form_marker = 'action="/products/delete/'
    admin_forms = admin_html.count(form_marker)
    product_rows = len(re.findall(r'href="/products/[0-9a-fA-F-]{36}/edit"', admin_html))
    creds2 = second_tenant_credentials()

    if creds2 is None:
        # Tanpa kredensial tenant kedua: buktikan gate admin dari template.
        tpl_path = ROOT / "app" / "templates" / "dashboard.html"
        tpl_text = tpl_path.read_text(encoding="utf-8") if tpl_path.exists() else ""
        gate_ok = re.search(
            r"\{%\s*if\s+current_user\.role\s*==\s*'admin'\s*%\}.{0,800}?"
            r"action=\"/products/delete/", tpl_text, re.S) is not None
        check("C1b form hapus di-gate untuk admin (kredensial tenant kedua tidak tersedia)",
              gate_ok,
              "gate {% if current_user.role == 'admin' %} tidak membungkus form hapus "
              "di app/templates/dashboard.html" if not gate_ok else
              "gate {% if current_user.role == 'admin' %} membungkus form hapus di template")
    else:
        ctx2, page2, _ = login_via_form(
            browser, base_url, creds2[0], creds2[1], "C:tenant2")
        try:
            second_is_admin = False
            try:
                second_is_admin = page2.locator('a[href="/admin/users"]').count() > 0
            except Exception:  # noqa: BLE001
                second_is_admin = False
            if second_is_admin:
                skip("C1b form 'Hapus Produk' tidak tampil untuk non-admin",
                     "akun tenant kedua ternyata punya role admin "
                     "-> tidak bisa dipakai sebagai non-admin")
            else:
                page2.goto("/")
                wait_idle(page2)
                nonadmin_forms = page2.content().count(form_marker)
                check("C1b form 'Hapus Produk' tidak tampil untuk non-admin",
                      nonadmin_forms == 0,
                      f"form hapus ditemukan {nonadmin_forms} kali di dashboard non-admin "
                      f"(harus 0)")
        finally:
            ctx2.close()

    if is_admin:
        if product_rows > 0:
            check("C1b2 form 'Hapus Produk' tampil untuk admin di dashboard",
                  admin_forms == product_rows,
                  f"form hapus muncul {admin_forms}x untuk {product_rows} baris produk")
        else:
            skip("C1b2 form 'Hapus Produk' tampil untuk admin di dashboard",
                 "tidak ada produk aktif di dashboard -> form tidak dirender, tidak ada yang diuji")
    else:
        skip("C1b2 form 'Hapus Produk' tampil untuk admin di dashboard",
             "sesi yang dipakai bukan admin -> varian admin tidak diuji")

    # --- C1c: teks konfirmasi jujur (soft delete bukan hapus formula) ----
    m_confirm = re.search(
        r"<form[^>]*action=\"/products/delete/[^>]*>", admin_html)
    confirm_text = m_confirm.group(0) if m_confirm else ""
    claims_formula_deleted = "bakal ikut kehapus" in confirm_text
    mentions_sampah = "Sampah" in confirm_text
    mentions_restore = ("dikembalikan" in confirm_text) or ("restore" in confirm_text.lower())
    check("C1c teks konfirmasi hapus jujur (Sampah + bisa dikembalikan, formula tidak ikut terhapus)",
          (not claims_formula_deleted) and mentions_sampah and mentions_restore,
          "form tidak ditemukan di HTML dashboard" if not confirm_text else
          f"klaim 'formula ikut terhapus'={claims_formula_deleted} "
          f"sebut Sampah={mentions_sampah} sebut bisa dikembalikan={mentions_restore}")

    # --- C2: route dengan UUID acak -> bukan 500 ---------------------------
    r = ctx.request.get(base_url + f"/products/{uuid.uuid4()}/edit", max_redirects=0)
    loc = (r.headers.get("location") or "")[:60]
    check("C2 GET /products/<uuid-acak>/edit -> 404/redirect ramah, bukan 500",
          r.status != 500 and r.status in (303, 302, 404),
          f"HTTP {r.status} location={loc!r}",
          known=KNOWN_ISSUES["BE-04"])

    # --- C3: cookie warning_msg tidak pernah dirender ---------------------
    canary = "E2E_WARNING_MSG_CANARY"
    rendered: dict[str, bool] = {}
    for label, value in (("json", json.dumps({"message": canary})), ("teks", canary)):
        ctx.clear_cookies(name="warning_msg")
        ctx.add_cookies([{"name": "warning_msg", "value": value, "url": base_url}])
        page.goto("/")
        wait_idle(page)
        rendered[label] = canary in page.content()
    check("C3 cookie warning_msg dirender di halaman", any(rendered.values()),
          f"canary={canary} terlihat={rendered} "
          f"(producer di products_routes.py:1167, tidak ada di template mana pun)",
          known=KNOWN_ISSUES["BE-21"])
    ctx.clear_cookies(name="warning_msg")

    # --- C4: greeting_cache bebas suntik kelas CSS (tanpa XSS) ------------
    payload = {"icon": "fa-solid fa-bug", "color": "text-red-500",
               "text": "X", "phrase": "Y"}
    ctx.add_cookies([{"name": "greeting_cache", "value": json.dumps(payload),
                      "url": base_url}])
    page.goto("/")
    wait_idle(page)
    res = page.evaluate(
        """() => {
          const i = document.querySelector('i.fa-bug');
          const cls = i ? (i.getAttribute('class') || '') : '';
          return {
            found: !!i,
            cls: cls,
            html: i ? i.outerHTML.slice(0, 200) : '',
            textShown: document.body ? document.body.innerText.includes('X') : false,
            breakout: /["'<>]/.test(cls)
          };
        }"""
    )
    check("C4 greeting_cache suntikan kelas CSS tanpa breakout atribut (bukan XSS)",
          not res.get("breakout"),
          f"i.fa-bug ditemukan={res.get('found')} class={res.get('cls')!r} "
          f"breakout={res.get('breakout')} teks_asing_tampil={res.get('textShown')} "
          f"(SEC-15: cookie greeting_cache tidak ditandatangani)")
    ctx.clear_cookies(name="greeting_cache")

    # --- C5: /health GET & HEAD -------------------------------------------
    hg = ctx.request.get(base_url + "/health")
    try:
        hjson = hg.json()
    except Exception:  # noqa: BLE001
        hjson = None
    check("C5 GET /health -> 200 + body JSON", hg.status == 200 and isinstance(hjson, dict),
          f"HTTP {hg.status} json={isinstance(hjson, dict)}")
    hh = ctx.request.fetch(base_url + "/health", method="HEAD")
    check("C5b HEAD /health -> 200", hh.status == 200, f"HTTP {hh.status}")

    # --- C6: portal publik /dip/<uuid acak> -> 404 ramah -------------------
    rd = ctx.request.get(base_url + f"/dip/{uuid.uuid4()}")
    rbody = rd.text()
    check("C6 /dip/<uuid-acak> -> 404 'Dokumen tidak ditemukan.' (bukan 500)",
          rd.status == 404 and "Dokumen tidak ditemukan" in rbody,
          f"HTTP {rd.status} pesan_ada={'Dokumen tidak ditemukan' in rbody}")

    # --- C7: Tailwind v3 (login) vs v4 (app) ------------------------------
    login_ctx = browser.new_context(base_url=base_url)
    login_page = new_page(login_ctx, "C:login-page")
    login_page.goto("/login")
    wait_idle(login_page)
    login_srcs = login_page.eval_on_selector_all("script[src]", "els => els.map(e => e.src)")
    v3 = any("cdn.tailwindcss.com" in s for s in login_srcs)
    login_ctx.close()
    page.goto("/")
    wait_idle(page)
    app_srcs = page.eval_on_selector_all("script[src]", "els => els.map(e => e.src)")
    v4 = any("cdn.jsdelivr.net/npm/@tailwindcss/browser@4" in s for s in app_srcs)
    check("C7 login pakai Tailwind v3 Play CDN sementara app pakai v4 (SEC-12)",
          bool(v3 and v4), f"login_v3={v3} app_v4={v4}",
          known=KNOWN_ISSUES["SEC-12"])
    ctx.close()


# --------------------------------------------------------------------------- #
# D. Multi-tenant (opsional)
# --------------------------------------------------------------------------- #
def group_tenant(browser, base_url: str, db, creds: tuple[str, str] | None) -> None:
    """D1: kebocoran tenant antar badan hukum. HANYA baca; probe tulis memakai
    payload yang pasti ditolak validasi lebih dulu sehingga tidak mengubah data."""
    if creds is None:
        skip("D1 isolasi tenant (daftar produk/bahan baku & tulis lintas badan hukum)",
             "kredensial tenant kedua tidak tersedia "
             "(set E2E_HEKA_EMAIL + E2E_HEKA_PASSWORD untuk mengaktifkan)")
        return
    if db is None:
        skip("D1 isolasi tenant (daftar produk/bahan baku & tulis lintas badan hukum)",
             "klien service-role tidak tersedia (butuh .env.staging lengkap)")
        return
    heka_email, heka_password = creds
    ctx, page, _ = login_via_form(browser, base_url, heka_email, heka_password, "D:heka")
    if "/login" in page.url:
        skip("D1 isolasi tenant (daftar produk/bahan baku & tulis lintas badan hukum)",
             f"login akun tenant kedua gagal (url={page.url})")
        ctx.close()
        return

    tok = next((c for c in ctx.cookies() if c["name"] == "access_token"), {})
    claims = decode_jwt_claims(tok.get("value", ""))
    user_id = claims.get("sub")
    own_company = ""
    try:
        prof = (db.table("profiles").select("id,role,perusahaan").eq("id", user_id)
                .execute().data or [{}])[0]
        own_company = (prof.get("perusahaan") or "").strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] baca profil tenant gagal: {type(exc).__name__}: {exc}")
    info("D1 tenant", f"akun kedua company={own_company!r} (dibaca dari profiles)")

    # D1a: /api/po/products -> apakah mengembalikan produk badan hukum lain?
    try:
        rp = ctx.request.get(base_url + "/api/po/products")
        items = (rp.json() or {}).get("items") or []
    except Exception as exc:  # noqa: BLE001
        items = []
        print(f"[WARN] /api/po/products gagal: {type(exc).__name__}: {exc}")
    leak_products = []
    if items:
        ids = [i.get("id") for i in items if i.get("id")]
        try:
            rows = (db.table("products").select("id,nama_produk,perusahaan").in_("id", ids)
                    .execute().data or [])
            leak_products = [r for r in rows
                             if own_company and (r.get("perusahaan") or "") != own_company]
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] cross-check produk gagal: {type(exc).__name__}: {exc}")
    check("D1a /api/po/products tidak membocorkan produk badan hukum lain",
          not leak_products,
          f"{len(items)} produk dikembalikan, {len(leak_products)} milik badan hukum lain "
          f"(contoh: {[r.get('perusahaan') for r in leak_products[:3]]})",
          known=KNOWN_ISSUES["SEC-02"])

    # D1b: halaman daftar bahan baku -> apakah baris badan hukum lain terlihat?
    try:
        rm_rows = (db.table("raw_materials").select("id,nama_dagang,kode_bahan_baku,perusahaan")
                   .execute().data or [])
    except Exception as exc:  # noqa: BLE001
        rm_rows = []
        print(f"[WARN] baca raw_materials gagal: {type(exc).__name__}: {exc}")
    foreign = [r for r in rm_rows
               if own_company and (r.get("perusahaan") or "") != own_company
               and (r.get("nama_dagang") or "")]
    page.goto("/raw-materials")
    wait_idle(page)
    html = page.content()
    seen = [r["nama_dagang"] for r in foreign if r["nama_dagang"] in html]
    check("D1b daftar bahan baku tidak menampilkan baris badan hukum lain", not seen,
          f"{len(seen)} baris milik badan hukum lain terlihat di /raw-materials "
          f"(dari {len(foreign)} kandidat)",
          known=KNOWN_ISSUES["SEC-02"])

    # D1c: tulis lintas tenant harus DITOLAK 403.
    # Payload dijamin ditolak validasi lebih dulu (kode bahan baku bentrok),
    # jadi tidak ada baris yang benar-benar berubah.
    target = foreign[0] if foreign else None
    donor = None
    if target:
        for r in rm_rows:
            if r.get("id") != target.get("id") and (r.get("kode_bahan_baku") or "").strip():
                donor = r
                break
    if not target or not donor:
        skip("D1c tulis lintas tenant ditolak 403",
             "tidak ada pasangan baris (target + kode donor) untuk uji tanpa mengubah data")
    else:
        before = (db.table("raw_materials").select("nama_dagang,kode_bahan_baku")
                  .eq("id", target["id"]).execute().data or [{}])[0]
        try:
            rw = ctx.request.post(
                base_url + f"/raw-materials/edit/{target['id']}",
                form={
                    "nama_dagang": target.get("nama_dagang") or "E2E",
                    "kode_bahan_baku": donor.get("kode_bahan_baku"),
                    "tipe": "single",
                },
            )
            status = rw.status
        except Exception as exc:  # noqa: BLE001
            status = 0
            print(f"[WARN] POST uji tulis gagal: {type(exc).__name__}: {exc}")
        after = (db.table("raw_materials").select("nama_dagang,kode_bahan_baku")
                 .eq("id", target["id"]).execute().data or [{}])[0]
        unchanged = (before.get("nama_dagang") == after.get("nama_dagang")
                     and before.get("kode_bahan_baku") == after.get("kode_bahan_baku"))
        check("D1c tulis lintas tenant ditolak 403 (tidak ada cek tenant)", status == 403,
              f"HTTP {status} untuk baris milik badan hukum lain "
              f"(probe memakai kode bentrok -> validasi menolak sebelum update)",
              known=KNOWN_ISSUES["SEC-02"])
        check("D1c-2 data uji tidak berubah setelah probe tulis", unchanged,
              f"nama_dagang sama={before.get('nama_dagang') == after.get('nama_dagang')} "
              f"kode sama={before.get('kode_bahan_baku') == after.get('kode_bahan_baku')}")
    ctx.close()

# --------------------------------------------------------------------------- #
# E. XSS regression
# --------------------------------------------------------------------------- #
XSS_JS = """() => {
  const LEGIT = ['onclick', 'onsubmit', 'oninput', 'onchange', 'onkeydown',
                 'onkeyup', 'onblur', 'onfocus', 'onmouseenter', 'onmouseleave',
                 'onload'];
  const imgs = document.querySelectorAll('img[src="x"]').length;
  const onErrAlert = document.querySelectorAll('img[onerror*="alert("]').length;
  const dataScripts = document.querySelectorAll('script[src^="data:"]').length;
  const unknown = [];
  document.querySelectorAll('*').forEach((el) => {
    for (const a of el.attributes) {
      const n = a.name.toLowerCase();
      if (n.indexOf('on') !== 0) continue;
      if (LEGIT.indexOf(n) >= 0) continue;
      if (n === 'onerror' && a.value.indexOf("display='none'") >= 0) continue;
      unknown.push(el.tagName + '@' + a.name);
    }
  });
  return {imgs, onErrAlert, dataScripts, unknown: unknown.slice(0, 5),
          unknownCount: unknown.length};
}"""


def group_xss(browser, base_url: str, state: dict) -> None:
    """E1..E3."""
    payload = '"><img src=x onerror=alert(1)>'
    ctx = browser.new_context(base_url=base_url, storage_state=state)
    page = new_page(ctx, "E:xss")

    # --- E1: form Pencarian PO (/purchase-orders) -------------------------
    page.goto("/purchase-orders")
    wait_idle(page)
    field = 'form[method="get"][action="/purchase-orders"] input[name="q"]'
    if page.locator(field).count() == 0:
        skip("E1 payload XSS pada form Pencarian PO tidak tersuntik",
             "input pencarian PO (name=q) tidak ditemukan di /purchase-orders")
    else:
        dlg_before = len(DIALOGS)
        page.fill(field, payload)
        try:
            with page.expect_navigation(timeout=20000):
                page.click('form[method="get"][action="/purchase-orders"] button')
        except Exception:  # noqa: BLE001
            pass
        wait_idle(page)
        res = page.evaluate(XSS_JS)
        dlg = len(DIALOGS) - dlg_before
        ok = (res["imgs"] == 0 and res["onErrAlert"] == 0 and res["dataScripts"] == 0
              and res["unknownCount"] == 0 and dlg == 0)
        check("E1 payload XSS pada form Pencarian PO tidak tersuntik", ok,
              f"payload={payload!r} img[src=x]={res['imgs']} "
              f"img[onerror*=alert]={res['onErrAlert']} script[data:]={res['dataScripts']} "
              f"on*_asing={res['unknownCount']} dialog_baru={dlg}")

    # --- E2: pencarian /sample-submissions ---------------------------------
    dlg_before = len(DIALOGS)
    page.goto("/sample-submissions?search=" + urlencode({"search": payload}))
    wait_idle(page)
    res2 = page.evaluate(XSS_JS)
    dlg2 = len(DIALOGS) - dlg_before
    ok2 = (res2["imgs"] == 0 and res2["onErrAlert"] == 0 and res2["dataScripts"] == 0
           and res2["unknownCount"] == 0 and dlg2 == 0)
    check("E2 payload XSS pada pencarian /sample-submissions tidak tersuntik", ok2,
          f"img[src=x]={res2['imgs']} img[onerror*=alert]={res2['onErrAlert']} "
          f"script[data:]={res2['dataScripts']} on*_asing={res2['unknownCount']} "
          f"dialog_baru={dlg2}")

    # --- E3: cek global pada halaman terakhir -----------------------------
    res3 = page.evaluate(XSS_JS)
    check("E3 cek global: tidak ada img[onerror]/script[data:]/on* asing",
          res3["imgs"] == 0 and res3["onErrAlert"] == 0 and res3["dataScripts"] == 0
          and res3["unknownCount"] == 0,
          f"img[src=x]={res3['imgs']} img[onerror*=alert]={res3['onErrAlert']} "
          f"script[data:]={res3['dataScripts']} on*_asing={res3['unknownCount']} "
          f"{res3['unknown']}")
    ctx.close()


# --------------------------------------------------------------------------- #
# F. Polling setelah sesi expired
# --------------------------------------------------------------------------- #
def group_expired(browser, base_url: str, state: dict, quick: bool) -> None:
    """F1."""
    if quick:
        skip("F1 redirect session_expired terjadi tepat satu kali (bukan loop)",
             "mode --quick: jeda polling panjang dilewati")
        return
    ctx = browser.new_context(base_url=base_url, storage_state=state)
    page = new_page(ctx, "F:expired")
    navs: list[str] = []
    page.on("framenavigated", lambda f: navs.append(f.url))
    page.goto("/")
    wait_idle(page)
    base_nav = len(navs)
    ctx.clear_cookies(name="access_token")
    keep_alive(page, 35)
    url = page.url
    delta = len(navs) - base_nav
    ok = "/login" in url and "session_expired" in url and delta == 1
    check("F1 redirect session_expired terjadi tepat satu kali (bukan loop)", ok,
          f"url={url} navigasi_setelah_hapus_cookie={delta} "
          f"(heartbeat 25 dtk + badge 30 dtk bisa memicu 2x redirect bila guard hilang)")
    ctx.close()


# --------------------------------------------------------------------------- #
# Mode produksi: subset read-only saja
# --------------------------------------------------------------------------- #
def run_production_subset(browser, base_url: str) -> None:
    """Hanya GET read-only: /health, struktur /login, 404 portal publik.

    TIDAK ada login, tidak ada POST, tidak ada upload, tidak ada tulis, dan
    tidak ada klien database.
    """
    ctx = browser.new_context(base_url=base_url)
    page = new_page(ctx, "PROD:read-only")
    r = ctx.request.get(base_url + "/health")
    try:
        hjson = r.json()
    except Exception:  # noqa: BLE001
        hjson = None
    check("PROD GET /health -> 200 + JSON", r.status == 200 and isinstance(hjson, dict),
          f"HTTP {r.status} json={isinstance(hjson, dict)}")

    resp = page.goto("/login")
    wait_idle(page)
    status = resp.status if resp else 0
    has_form = (page.locator("input[name=email]").count() > 0
                and page.locator("input[name=password]").count() > 0)
    has_btn = page.locator("#login-submit-btn").count() > 0
    srcs = page.eval_on_selector_all("script[src]", "els => els.map(e => e.src)")
    v3 = any("cdn.tailwindcss.com" in s for s in srcs)
    check("PROD GET /login -> 200 + struktur form login utuh",
          status == 200 and has_form and has_btn,
          f"HTTP {status} input_login={has_form} tombol={has_btn} tailwind_v3={v3}")

    rd = ctx.request.get(base_url + f"/dip/{uuid.uuid4()}")
    body = rd.text()
    check("PROD GET /dip/<uuid-acak> -> 404 'Dokumen tidak ditemukan.'",
          rd.status == 404 and "Dokumen tidak ditemukan" in body,
          f"HTTP {rd.status} pesan_ada={'Dokumen tidak ditemukan' in body}")
    ctx.close()


# --------------------------------------------------------------------------- #
# Laporan error console
# --------------------------------------------------------------------------- #
def report_console_errors() -> None:
    """Laporkan error JS - NameError/ReferenceError/TypeError adalah regresi
    klasik repo ini (scripts/check_undefined_names.py)."""
    suspicious = [(lbl, txt) for lbl, txt in PAGE_ERRORS
                  if re.search(r"NameError|ReferenceError|TypeError", txt)]
    for lbl, txt in suspicious:
        print(f"[WARN] page error ({lbl}): {txt[:300]}")
    check("Tidak ada NameError/ReferenceError/TypeError di browser", not suspicious,
          "; ".join(f"{lbl}: {t[:120]}" for lbl, t in suspicious[:3]))
    if CONSOLE_ERRORS:
        print(f"[INFO] {len(CONSOLE_ERRORS)} console error tercatat (10 pertama):")
        for lbl, txt in CONSOLE_ERRORS[:10]:
            print(f"       ({lbl}) {txt[:200]}")
    if DIALOGS:
        print(f"[WARN] {len(DIALOGS)} dialog browser muncul: {DIALOGS[:3]}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="E2E audit staging: verifikasi temuan audit 2026-10-21 lewat browser nyata.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--base-url", default=os.getenv("STAGING_BASE_URL", "http://127.0.0.1:8017"),
                    help="base URL staging (default: env STAGING_BASE_URL atau "
                         "http://127.0.0.1:8017)")
    ap.add_argument("--headed", action="store_true", help="tampilkan browser")
    ap.add_argument("--quick", action="store_true",
                    help="lewati jeda polling panjang (B1-B3, F1)")
    ap.add_argument("--full", action="store_true",
                    help="jalankan semua jeda polling (default)")
    ap.add_argument("--strict", action="store_true", help="KNOWN dihitung sebagai FAIL")
    ap.add_argument("--allow-production", action="store_true",
                    help="izinkan base URL non-lokal; hanya subset read-only (health, "
                         "struktur login, 404 portal publik) - tanpa POST/tulis/upload")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    base_url = (args.base_url or "").rstrip("/")
    if not base_url:
        print("[ABORT] base URL kosong -> exit 2")
        return 2
    quick = bool(args.quick)
    if args.quick and args.full:
        print("[WARN] --quick dan --full dipakai bersamaan -> yang dipakai: --quick")

    prod_mode = not is_local(base_url)
    db = None
    state: dict = {}
    email = password = ""

    if prod_mode:
        if not args.allow_production:
            print(f"[ABORT] base URL '{base_url}' bukan localhost.")
            print("       Staging-only by default. Tambahkan --allow-production untuk "
                  "subset read-only (tidak ada POST/tulis/upload).")
            return 2
        print("=" * 72)
        print("  MODE PRODUKSI READ-ONLY - TIDAK ADA POST / TULIS / UPLOAD / LOGIN")
        print("  Hanya: /health, struktur halaman /login, dan 404 portal publik /dip/.")
        print("  Tidak ada kredensial yang dipakai dan tidak ada database yang diakses.")
        print("=" * 72)
    else:
        cfg = load_staging_cfg(base_url)
        try:
            db = db_client(cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] klien service-role tidak bisa dibuat: {type(exc).__name__}: {exc}")
            db = None
        email, password = load_credentials()
        try:
            import httpx

            hr = httpx.get(base_url + "/health", timeout=5)
            if hr.status_code != 200:
                print(f"[ABORT] staging tidak hidup (/health HTTP {hr.status_code}) -> exit 2")
                return 2
        except Exception as exc:  # noqa: BLE001
            print(f"[ABORT] staging tidak hidup: {type(exc).__name__}: {exc} -> exit 2")
            return 2

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(headless=not args.headed)
            except Exception as exc:  # noqa: BLE001
                print(f"[ABORT] chromium tidak bisa dijalankan: "
                      f"{type(exc).__name__}: {exc} -> exit 2")
                return 2
            try:
                if prod_mode:
                    run_production_subset(browser, base_url)
                else:
                    login = do_login(browser, base_url, email, password, "A:login")
                    state = login["state"]
                    print("[INFO] login sekali, storage_state dipakai ulang per grup "
                          "(rate limit POST /login = 5/menit per IP)")
                    steps = (
                        ("A", lambda: group_auth(browser, base_url, email, password, login)),
                        ("B", lambda: group_polling(browser, base_url, state, quick,
                                                   login["is_admin"])),
                        ("C", lambda: group_pages(browser, base_url, state, login["is_admin"])),
                        ("D", lambda: group_tenant(browser, base_url, db,
                                                   second_tenant_credentials())),
                        ("E", lambda: group_xss(browser, base_url, state)),
                        ("F", lambda: group_expired(browser, base_url, state, quick)),
                    )
                    for label, step in steps:
                        try:
                            step()
                        except Exception as exc:  # noqa: BLE001
                            check(f"grup {label} selesai tanpa exception", False,
                                  f"{type(exc).__name__}: {exc}")
                    try:
                        report_console_errors()
                    except Exception as exc:  # noqa: BLE001
                        print(f"[WARN] laporan console error gagal: {exc}")
            finally:
                browser.close()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"[ABORT] eksekusi gagal: {type(exc).__name__}: {exc} -> exit 2")
        return 2

    return summarize(bool(args.strict))


if __name__ == "__main__":
    sys.exit(main())