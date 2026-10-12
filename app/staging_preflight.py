"""Preflight staging standalone (stdlib + dotenv saja).

Sumber otoritatif tunggal: file .env.staging. Mode ditetapkan launcher via
argumen file, bukan shell kebetulan. Tidak impor app.* atau supabase agar
dapat jalan sebelum Settings()/create_client(). Tidak mencetak nilai
variabel/secret. Tidak mengklaim key valid untuk project.

Revisi 3:
- SUPABASE_URL validasi hostname EKSAK via urlparse (tolak substring-host,
  path-trick, skema non-https, port non-443, userinfo, query/fragment,
  path non-root).
- Key: klaim terbatas — JWT ter-decode dicek klaim 'ref', opaque lolos
  presence saja. Lihat LIMITS.
"""
import base64
import json
from urllib.parse import urlparse

STAGING_REF = "odtfppboyjlbatajncgj"
PROD_REF = "dytuprmoorvrugutozwv"
STAGING_HOST = STAGING_REF + ".supabase.co"
PROD_HOST = PROD_REF + ".supabase.co"
REQUIRED_KEYS = ("DIP_APP_ENV", "SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_ROLE_KEY")
KEY_BINDING_KEYS = ("SUPABASE_KEY", "SUPABASE_SERVICE_ROLE_KEY")


def parse_dotenv_file(path):
    try:
        from dotenv import dotenv_values
        vals = dotenv_values(path) or {}
        return {str(k).strip(): ("" if v is None else str(v).strip()) for k, v in vals.items()}
    except Exception:
        vals = {}
        with open(path, encoding="utf-8-sig") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
                    v = v[1:-1].strip()
                vals[k] = v
        return vals


def _strip(v):
    v = (v or "").strip()
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        v = v[1:-1].strip()
    return v


def validate_staging_url(url_raw, caller="preflight", source="file"):
    """Validator URL tunggal: hostname eksak. Raise/pass saja, tanpa nilai."""
    url = _strip(url_raw)
    if not url:
        raise RuntimeError("[%s] SUPABASE_URL kosong (%s). Dibatalkan." % (caller, source))
    try:
        parts = urlparse(url)
    except Exception:
        raise RuntimeError("[%s] SUPABASE_URL tidak terparse (%s). Dibatalkan." % (caller, source))
    scheme = (parts.scheme or "").lower()
    if scheme != "https":
        raise RuntimeError("[%s] SUPABASE_URL harus skema https (%s). Dibatalkan." % (caller, source))
    host = (parts.hostname or "").lower()
    if not host:
        raise RuntimeError("[%s] SUPABASE_URL tanpa hostname valid (%s). Dibatalkan." % (caller, source))
    if host == PROD_HOST:
        raise RuntimeError("[%s] SUPABASE_URL menunjuk produksi (%s). Dibatalkan." % (caller, source))
    if host != STAGING_HOST:
        raise RuntimeError("[%s] SUPABASE_URL bukan host staging yang diharapkan (%s). Dibatalkan." % (caller, source))
    if parts.username or parts.password:
        raise RuntimeError("[%s] SUPABASE_URL tidak boleh memuat userinfo (%s). Dibatalkan." % (caller, source))
    if parts.query or parts.fragment:
        raise RuntimeError("[%s] SUPABASE_URL tidak boleh memuat query/fragment (%s). Dibatalkan." % (caller, source))
    if parts.path not in ("", "/"):
        raise RuntimeError("[%s] SUPABASE_URL path tidak didukung (%s). Dibatalkan." % (caller, source))
    try:
        port = parts.port
    except ValueError:
        raise RuntimeError("[%s] SUPABASE_URL port tidak valid (%s). Dibatalkan." % (caller, source))
    if port is not None and port != 443:
        raise RuntimeError("[%s] SUPABASE_URL port tidak standar (%s). Dibatalkan." % (caller, source))
    if PROD_REF in url:
        raise RuntimeError("[%s] ref produksi terdeteksi pada SUPABASE_URL (%s). Dibatalkan." % (caller, source))
    return True


def _b64url_decode_json(seg):
    pad = "=" * (-len(seg) % 4)
    return json.loads(base64.urlsafe_b64decode(seg + pad).decode("utf-8"))


def jwt_ref(key_raw):
    """-> (is_jwt, ref|None). Tidak pernah kembalikan key."""
    k = _strip(key_raw)
    parts = k.split(".")
    if len(parts) != 3 or not all(parts):
        return (False, None)
    try:
        payload = _b64url_decode_json(parts[1])
    except Exception:
        return (True, None)
    if not isinstance(payload, dict):
        return (True, None)
    ref = payload.get("ref")
    if isinstance(ref, str) and ref.strip():
        return (True, ref.strip())
    return (True, None)


def check_key_binding(mapping, caller="preflight", source="file"):
    """Pemeriksaan binding TERBATAS (lokal, tanpa network, tanpa validitas).

    - JWT ter-decode: klaim 'ref' HARUS == STAGING_REF, tolak == PROD_REF /
      hilang / mismatch (fail-closed).
    - Non-JWT/opaque: TIDAK terverifikasi lokal; lolos presence saja.
    - Substring mentah PROD_REF tetap ditolak defense-in-depth.
    """
    for name in KEY_BINDING_KEYS:
        raw = _strip(mapping.get(name))
        if not raw:
            continue
        if PROD_REF in raw:
            raise RuntimeError("[%s] ref produksi terdeteksi pada %s (%s). Dibatalkan." % (caller, name, source))
        is_jwt, ref = jwt_ref(raw)
        if not is_jwt:
            continue
        if ref == PROD_REF:
            raise RuntimeError("[%s] klaim ref %s menunjuk produksi (%s). Dibatalkan." % (caller, name, source))
        if ref != STAGING_REF:
            raise RuntimeError("[%s] klaim ref %s bukan staging atau hilang (%s). Dibatalkan." % (caller, name, source))
    return True


LIMITS = (
    "Batas validasi key: (1) hanya memeriksa kehadiran + klaim 'ref' pada payload "
    "JWT yang dapat di-decode secara lokal, TANPA verifikasi signature dan TANPA "
    "memastikan key aktif/valid untuk project; (2) key format non-JWT/opaque "
    "tidak dapat diverifikasi binding-nya secara lokal; (3) single-source "
    ".env.staging mengurangi risiko campur-sumber tetapi tidak menjamin isi file "
    "konsisten; (4) satu-satunya bukti key valid adalah panggilan live ke "
    "Supabase (di luar cakupan, tidak dilakukan)."
)


def validate_mapping(mapping, source, caller="preflight"):
    if source not in ("file", "effective-env"):
        raise RuntimeError("[%s] sumber validasi tak dikenal: %s. Dibatalkan." % (caller, source))
    missing = [k for k in REQUIRED_KEYS if not _strip(mapping.get(k))]
    if missing:
        raise RuntimeError("[%s] konfigurasi %s tidak lengkap (hilang: %s). Dibatalkan." % (caller, source, ",".join(missing)))
    mode = _strip(mapping.get("DIP_APP_ENV")).lower()
    if mode != "staging":
        raise RuntimeError("[%s] DIP_APP_ENV %s bukan 'staging'. Dibatalkan." % (caller, source))
    validate_staging_url(mapping.get("SUPABASE_URL"), caller=caller, source=source)
    check_key_binding(mapping, caller=caller, source=source)
    return True


def validate_staging_file(file_vals, caller="preflight"):
    return validate_mapping(dict(file_vals), source="file", caller=caller)


def validate_effective_env(env, caller="preflight"):
    mapping = {
        "DIP_APP_ENV": env.get("DIP_APP_ENV", ""),
        "SUPABASE_URL": env.get("SUPABASE_URL", ""),
        "SUPABASE_KEY": env.get("SUPABASE_KEY", ""),
        "SUPABASE_SERVICE_ROLE_KEY": env.get("SUPABASE_SERVICE_ROLE_KEY", ""),
    }
    return validate_mapping(mapping, source="effective-env", caller=caller)


def check_shell_clean(shell_env, caller="preflight"):
    conflicts = [k for k in REQUIRED_KEYS if _strip(shell_env.get(k))]
    if conflicts:
        raise RuntimeError("[%s] shell membawa %s; kosongkan shell atau jalankan via launcher bersih. Dibatalkan." % (caller, ",".join(conflicts)))
    return True
