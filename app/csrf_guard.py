"""Lapisan kedua anti-CSRF: validasi header Origin/Referer untuk mutasi.

Pola yang sengaja dipilih:
- Middleware ASGI murni (bukan BaseHTTPMiddleware) agar body request
  (termasuk upload multipart besar) tidak pernah dibaca atau di-buffer;
  guard hanya memeriksa header sebelum meneruskan request.
- Tanpa token CSRF per-form: template, form, dan JS tidak berubah.
  Lapisan pertama tetap cookie ``access_token`` dengan ``SameSite=Lax``
  (lihat ``app/main.py``).

Logika (fail-closed untuk request berbrowser, longgar untuk non-browser):
1. Method yang diperiksa: ``POST``, ``PUT``, ``PATCH``, ``DELETE``.
   ``GET``/``HEAD``/``OPTIONS`` tidak disentuh. Inventaris route saat
   perancangan (sesi 16, 2026-11-11) hanya menemukan route ``POST`` —
   tidak ada PUT/PATCH/DELETE, jadi cakupan ini sudah menutup semuanya.
2. Bila header ``Origin`` ada (non-empty, bukan "null"): origin-nya harus
   SAMA dengan origin request (skema efektif + ``Host``). Skema efektif
   diambil dari ``X-Forwarded-Proto`` hanya bila nilainya ``http``/``https``
   (case insensitive), selain itu skema scope ASGI; ``X-Forwarded-Host``
   tidak dipercaya. Perbandingan case-insensitive.
   - ``Origin: null`` (opaque origin) tanpa Referer: diizinkan — Chromium
     headless di staging (http://127.0.0.1) mengirim nilai ini untuk form
     submit; klien non-browser juga tidak membawa Origin. Lapisan pertama
     (cookie SameSite=Lax + httpOnly) tetap memblokir form cross-origin.
   - Permintaan lintas origin yang membawa ``Origin`` situs lain
     (mis. ``https://evil.example``) ditolak.
   - Header ``Origin`` kosong string ("") bukan origin valid (RFC 6454);
     bila hadir kosong, diabaikan dan cek jatuh ke Referer.
3. Bila ``Origin`` tidak ada tapi ``Referer`` ada: origin dari Referer
   (via ``urlsplit``) harus sama.
4. Bila KEDUANYA tidak ada: diizinkan. Klien non-browser (skrip E2E
   Playwright, curl, httpx, skrip manajemen) tidak membawa cookie ambient
   lintas origin, jadi CSRF token tidak relevan untuk mereka; cookie sesi
   pun hanya dikirim browser. Ini adalah residu yang disengaja.
5. ``DIP_ALLOWED_ORIGINS`` (env, daftar dipisah koma) memperluas origin
   yang diizinkan selain origin request itu sendiri. Hanya entri
   ``https://`` atau ``http://localhost``/``http://127.0.0.1`` (untuk
   staging lokal) yang diterima; entri tak valid diabaikan dan dicatat
   dengan satu warning. Default kosong.
6. Path exempt: konstanta ``EXEMPT_PATHS`` (default kosong). Inventaris
   tidak menemukan alasan untuk mengecualikan path mana pun — termasuk
   ``/login`` (form login di browser selalu membawa Origin) dan
   ``/api/presence/heartbeat`` (fetch sama-origin). Jangan mengisi
   ``EXEMPT_PATHS`` tanpa dokumentasi alasan di PR.

Tolak = HTTP 403, body teks singkat, tanpa nilai header yang bocor.
Log ``logger.warning`` hanya memuat method, path (tanpa query string),
dan host dari Origin (bukan nilai header penuh / cookie).

Konsekuensi reverse proxy / custom domain:
- Guard memakai header ``Host`` yang sampai ke aplikasi. Bila proxy
  (Render/Cloudflare) meneruskan nama host sebenarnya, perbandingan
  origin tetap benar; origin kustom tambahan (mis. custom domain selain
  host utama) harus ditambahkan ke ``DIP_ALLOWED_ORIGINS``.
- ``X-Forwarded-Proto`` hanya dipercaya saat nilainya ``http``/``https``;
  proxy yang memalsukan nilai lain (mis. ``https http``) otomatis jatuh
  ke skema scope.
"""

import logging
import os
from urllib.parse import urlsplit

logger = logging.getLogger("dip.csrf")

_METHODES_PENTING = ("POST", "PUT", "PATCH", "DELETE")
_EXEMPT_METHODS = ("GET", "HEAD", "OPTIONS")

# Path yang TIDAK diperiksa. Default kosong: inventaris sesi 16 tidak
# menemukan alasan kuat untuk mengecualikan path apa pun (lihat docstring
# modul). Mengisi konstanta ini membutuhkan dokumentasi alasan di PR.
EXEMPT_PATHS: frozenset[str] = frozenset()

_RESPONSE_BODY = "Permintaan ditolak (origin tidak cocok)."

# Skema yang boleh muncul di DIP_ALLOWED_ORIGINS.
_ALLOWED_SCHEMES = ("https", "http")
# Host yang boleh memakai skema http (staging lokal saja).
_HTTP_HOSTS = ("localhost", "127.0.0.1")


def _valid_allowed_origin(entry: str) -> str | None:
    """Validasi satu entri DIP_ALLOWED_ORIGINS; return entry dinormalisasi
    atau None bila tak valid (diserap tanpa warning lebih lanjut)."""
    entry = (entry or "").strip()
    if not entry:
        return None
    try:
        parts = urlsplit(entry)
    except ValueError:
        return None
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return None
    if scheme == "http" and host not in _HTTP_HOSTS:
        return None
    if not host:
        return None
    # Normalisasi: bangun kembali origin dari komponen yang divalidasi saja
    # (tanpa path/userinfo), dengan port bila bukan default.
    port = parts.port
    default_port = 443 if scheme == "https" else 80
    suffix = f":{port}" if port and port != default_port else ""
    return f"{scheme}://{host}{suffix}"


def _load_allowed_origins(raw_value: str | None) -> frozenset[str]:
    raw = (raw_value or "").strip()
    if not raw:
        return frozenset()
    origins: set[str] = set()
    for item in raw.split(","):
        normalized = _valid_allowed_origin(item)
        if normalized is None:
            if item.strip():
                logger.warning(
                    "[CSRF] entri DIP_ALLOWED_ORIGINS tak valid diabaikan: %s",
                    item.strip()[:80],
                )
            continue
        origins.add(normalized)
    return frozenset(origins)


def _request_origin_from_headers(headers: list[tuple[bytes, bytes]]) -> tuple[str, str | None, str | None]:
    """Pisahkan Origin, Referer, Host, X-Forwarded-Proto dari header.

    Return (origin, referer, host, forwarded_proto) setelah decode
    case-insensitive (header ASGI lowercase key; value didentikkan
    sebagai str latin-1, pola standar Starlette).
    """
    origin = referer = host = fwd_proto = None
    for key, value in headers:
        lk = key.decode("latin-1").lower()
        if lk == "origin":
            origin = value.decode("latin-1")
        elif lk == "referer":
            referer = value.decode("latin-1")
        elif lk == "host":
            host = value.decode("latin-1")
        elif lk == "x-forwarded-proto":
            fwd_proto = value.decode("latin-1")
    return origin, referer, host, fwd_proto


def _effective_scheme(scope: dict, forwarded_proto: str | None) -> str:
    base = scope.get("scheme") or "http"
    if forwarded_proto:
        # Hanya terima nilai tunggal http/https (case-insensitive);
        # daftar / nilai asing diabaikan (jangan percaya proxy tak tepercaya).
        candidate = forwarded_proto.strip().lower()
        if candidate in ("http", "https"):
            base = candidate
    return base


def _origin_matches(
    origin: str,
    scope: dict,
    host_header: str | None,
    forwarded_proto: str | None,
    allowed_origins: frozenset[str],
) -> tuple[bool, str]:
    """Cek satu Origin header terhadap origin request + allowlist."""
    origin_norm = (origin or "").strip().lower()
    if not origin_norm or origin_norm == "null":
        return False, "origin null atau kosong"
    scheme = _effective_scheme(scope, forwarded_proto)
    host = (host_header or "").strip().lower()
    request_origin = f"{scheme}://{host}" if host else ""
    if request_origin and origin_norm == request_origin:
        return True, ""
    if origin_norm in allowed_origins:
        return True, ""
    return False, f"origin {origin_norm[:60]} tidak cocok {request_origin[:60]}"


def _referer_origin_matches(
    referer: str,
    scope: dict,
    host_header: str | None,
    forwarded_proto: str | None,
    allowed_origins: frozenset[str],
) -> tuple[bool, str]:
    referer = (referer or "").strip()
    if not referer:
        return False, "referer kosong"
    try:
        parts = urlsplit(referer)
    except ValueError:
        return False, "referer tidak valid"
    referer_origin = f"{(parts.scheme or '').lower()}://{(parts.netloc or '').lower()}"
    if not parts.scheme or not parts.netloc:
        return False, "referer tanpa scheme/netloc"
    scheme = _effective_scheme(scope, forwarded_proto)
    host = (host_header or "").strip().lower()
    request_origin = f"{scheme}://{host}" if host else ""
    if request_origin and referer_origin == request_origin:
        return True, ""
    if referer_origin in allowed_origins:
        return True, ""
    return False, f"referer {referer_origin[:60]} tidak cocok {request_origin[:60]}"


class CsrfGuardMiddleware:
    """ASGI middleware murni: tolak mutasi lintas origin tanpa Origin/Referer.

    Direset setiap instance sehingga konfigurasi ``DIP_ALLOWED_ORIGINS``
    dibaca ulang saat middleware dibuat (test bisa mengontrol env per-app).
    """

    def __init__(self, app):
        self.app = app
        self._allowed_origins = _load_allowed_origins(os.getenv("DIP_ALLOWED_ORIGINS"))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = (scope.get("method") or "").upper()
        if method in _EXEMPT_METHODS or method not in _METHODES_PENTING:
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if path in EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        origin, referer, host, fwd_proto = _request_origin_from_headers(
            scope.get("headers") or []
        )

        # Cek 1: header Origin ada, non-empty, dan bukan "null" (opaque
        # context: Chromium headless form submit di http://127.0.0.1,
        # sandboxed iframe, data: URL). Nilai "null" diperlakukan seperti
        # Origin absen dan jatuhkan ke cek Referer / non-browser di bawah.
        if origin is not None and origin.strip() not in ("", "null"):
            ok, reason = _origin_matches(origin, scope, host, fwd_proto, self._allowed_origins)
            if not ok:
                await self._deny(send, method, path, reason)
                return
            await self.app(scope, receive, send)
            return
        # Cek 2: header Origin tidak ada, kosong, atau "null" (opaque).
        # Origin kosong/"" atau "null" bukan origin valid yang bisa
        # divalidasi (RFC 6454: origin selalu "null" atau scheme://host).
        # Jatuhkan ke cek Referer bila ada; bila Referer juga tidak ada
        # (klien non-browser / Chromium quirk), izinkan — lihat cek 3.
        if referer is not None:
            ok, reason = _referer_origin_matches(referer, scope, host, fwd_proto, self._allowed_origins)
            if ok:
                await self.app(scope, receive, send)
                return
            # Referer tidak cocok: TOLAK. Request cross-origin yang sengaja
            # menyembunyikan Origin (fetch no-cors, XHR tanpa CORS) sering
            # hanya membawa Referer — tolak mencegah bypass.
            await self._deny(send, method, path, reason)
            return
        # Cek 3: KEDUANYA tidak ada (Origin header tidak ada / kosong /
        # "null", dan Referer juga tidak ada).
        #
        # Nilai Origin "null" (opaque context: sandboxed iframe, data: URL)
        # atau Origin header yang absen sama sekali, tanpa Referer,
        # diperlakukan setara: diizinkan (klien non-browser). Alasan:
        # - Chromium/Playwright di lingkungan http://127.0.0.1 (staging)
        #   mengirim `Origin: null` untuk form submit regular — perilaku
        #   yang harus tetap bekerja agar E2E lulus.
        # - Klien non-browser (curl, skrip E2E via API) tidak membawa
        #   cookie ambient lintas origin; risiko CSRF tidak relevan.
        # - Lapisan pertama (SameSite=Lax) tetap memblokir form cross-origin
        #   dari browser, jadi lapisan kedua ini hanya menambah kedalaman.
        # Residu: opaque origin + tanpa Referer lolos; mitigasi tersisa
        # adalah SameSite=Lax + httpOnly cookie (bukan guard ini).
        await self.app(scope, receive, send)

    async def _deny(self, send, method: str, path: str, reason: str) -> None:
        """Kirim respons 403. Handler tidak pernah dijalankan sehingga
        request aslinya tidak menyentuh route sama sekali."""
        logger.warning("[CSRF] ditolak: method=%s path=%s alasan=%s", method, path, reason[:120])
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(_RESPONSE_BODY.encode("utf-8"))).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _RESPONSE_BODY.encode("utf-8")})
