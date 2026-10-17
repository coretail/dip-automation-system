"""Satu-satunya jalur akses object storage (Supabase Storage + Cloudflare R2).

Fase 3 migrasi = backend R2 + mode ``dual``. Perilaku dipilih via
``STORAGE_BACKEND`` (``app/config.py``):

- ``supabase`` (default): hanya Supabase Storage; perilaku lama tak berubah.
- ``dual``: TULIS ke Supabase dan R2; BACA tetap dari Supabase (URL di kolom DB
  tetap Supabase sampai cutover Fase 5). Kegagalan tulis/hapus R2 TIDAK
  menggagalkan request -- hanya dicatat sebagai log ``storage_repair`` supaya
  ``rclone sync`` final bisa merekonsiliasi. Tulis R2 yang sukses di-log
  ``storage_r2_ok`` (sinyal positif pemantauan, level WARNING).
- ``r2``: hanya R2 (dipakai saat cutover Fase 5). URL publik dibangun dari
  ``R2_PUBLIC_BASES``; presigned memakai endpoint S3 R2 (tak butuh domain).

Modul ini sengaja TIDAK meng-import config/supabase/boto3 di level modul, supaya
fungsi murni (:func:`parse_storage_url`) bisa diuji tanpa dependency aplikasi.
Semua impor berat dilakukan lazy di dalam fungsi.

Pemanggil yang sudah menerima klien Supabase via injeksi (modul route) harus
meneruskan ``client=supabase`` agar test-double tetap bekerja dan perilaku sama
dengan sebelumnya. Bila ``client`` tidak diberikan, dipakai klien tunggal dari
``app.database``.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Marker public URL Supabase Storage (sama dengan yang dipakai main.py lama).
SUPABASE_PUBLIC_MARKER = "/storage/v1/object/public/"

STORAGE_BACKENDS = ("supabase", "dual", "r2")

# Upload PDF ke R2: content-type eksplisit + cache untuk bucket publik.
R2_PDF_CONTENT_TYPE = "application/pdf"
R2_PUBLIC_CACHE_CONTROL = "public, max-age=86400"

# Cache klien boto3 per (account, access_key, secret) supaya Settings yang
# berubah (mis. test) membangun klien baru tanpa state basi.
_R2_CLIENTS: dict = {}


def _settings():
    from app.config import settings

    return settings


def storage_backend() -> str:
    """Backend aktif dari Settings (default ``supabase``)."""
    raw = getattr(_settings(), "storage_backend", "supabase") or "supabase"
    return str(raw).strip().lower()


def _active_backend() -> str:
    """Backend aktif yang tervalidasi (fail loud bila nilainya tak dikenal)."""
    backend = storage_backend()
    if backend not in STORAGE_BACKENDS:
        raise RuntimeError(
            f"[STORAGE] STORAGE_BACKEND='{backend}' tidak dikenal "
            f"(pilih: {', '.join(STORAGE_BACKENDS)})."
        )
    return backend


def _primary_backend() -> str:
    """Backend yang menentukan sukses/gagal pemanggil (mode dual -> Supabase)."""
    return "r2" if storage_backend() == "r2" else "supabase"


def primary_result(result) -> dict:
    """Ambil hasil backend utama dari nilai balik :func:`remove`.

    Di ``dual`` yang otoritatif adalah Supabase (baca tetap Supabase); di ``r2``
    otoritatif adalah R2. Dipakai pemanggil supaya kontrak hasil tidak perlu
    tahu daftar backend.
    """
    if not isinstance(result, dict):
        return {}
    return result.get(_primary_backend()) or {}


def _log_storage_repair(op: str, bucket: str, path: str, backend: str, error) -> None:
    """Log terstruktur untuk kegagalan R2 yang tidak menggagalkan request."""
    logger.warning(
        "storage_repair op=%s bucket=%s path=%s backend=%s error=%s",
        op, bucket, path, backend, error,
    )


def _log_r2_ok(op: str, bucket: str, physical: str, path: str) -> None:
    """Sinyal positif tulis R2 sukses (pasangan token ``storage_repair``).

    Sengaja level WARNING: root logger tanpa konfigurasi berlevel efektif
    WARNING, jadi ``logger.info`` tidak akan terlihat di konsol staging/prod.
    Token pencarian: ``storage_r2_ok``.
    """
    logger.warning(
        "storage_r2_ok op=%s bucket=%s physical=%s path=%s",
        op, bucket, physical, path,
    )


def _supabase_client():
    from app.database import supabase

    return supabase


def _client(client=None):
    return client if client is not None else _supabase_client()


def r2_public_bases() -> dict:
    """Baca ``R2_PUBLIC_BASES`` (JSON ``{bucket: base_url}``) dari Settings.

    Mengembalikan dict dengan base tanpa trailing slash. Nilai tak valid
    diabaikan (di-log) supaya parser tetap aman.
    """
    raw = getattr(_settings(), "r2_public_bases", "{}") or "{}"
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except Exception:
            logger.warning("[STORAGE] R2_PUBLIC_BASES bukan JSON valid; diabaikan.")
            return {}
    if not isinstance(data, dict):
        return {}
    bases = {}
    for bucket, base in data.items():
        if base:
            bases[str(bucket)] = str(base).rstrip("/")
    return bases


def r2_bucket_suffix() -> str:
    """Suffix nama bucket R2 per-environment (mis. ``-stg`` untuk staging).

    Staging dan prod memakai AKUN R2 yang sama, jadi bucket fisik staging wajib
    berbeda (ber-suffix). Kosong = tanpa suffix (prod). Tanpa ini, mode ``dual``
    di staging akan menulis ke bucket R2 PRODUKSI.
    """
    raw = getattr(_settings(), "r2_bucket_suffix", "") or ""
    return str(raw).strip()


def _r2_physical_bucket(bucket: str) -> str:
    """Nama bucket R2 fisik = nama logis + suffix environment."""
    suffix = r2_bucket_suffix()
    return f"{bucket}{suffix}" if suffix else bucket


def _r2_public_base(bucket: str):
    """Base publik untuk bucket logis (cari nama fisik dulu, lalu nama logis)."""
    bases = r2_public_bases()
    return bases.get(_r2_physical_bucket(bucket)) or bases.get(bucket)


def parse_storage_url(url: str, public_bases: dict | None = None):
    """Ekstrak ``(bucket, path)`` dari public URL storage.

    Mengenali dua format:
      - Supabase: ``https://<ref>.supabase.co/storage/v1/object/public/<bucket>/<path>``
      - R2      : ``<base publik>`` + ``/`` + ``<path>`` (base per bucket dari
        ``R2_PUBLIC_BASES``).
    Query string diabaikan. Kalau bukan format yang dikenal -> ``(None, None)``.
    """
    if not url:
        return None, None

    if SUPABASE_PUBLIC_MARKER in url:
        rest = url.split(SUPABASE_PUBLIC_MARKER, 1)[1].split("?", 1)[0]
        if "/" not in rest:
            return None, None
        bucket, path = rest.split("/", 1)
        return bucket, path

    if public_bases is None:
        bases, suffix = r2_public_bases(), r2_bucket_suffix()
    else:
        bases, suffix = public_bases, ""
    # Base terpanjang lebih dulu supaya prefix yang mirip tidak salah cocok.
    for base, bucket in sorted(
        ((b, bk) for bk, b in (bases or {}).items() if b),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        logical = bucket[: -len(suffix)] if suffix and bucket.endswith(suffix) else bucket
        if url == base:
            return logical, None
        if url.startswith(base + "/"):
            rest = url[len(base) + 1:].split("?", 1)[0]
            if not rest:
                return logical, None
            return logical, rest
    return None, None


# ============================ Transport Supabase =============================
# Dipisah dari API publik supaya probe guard read-only (tests/snapshot_dip.py)
# tetap menguji pemanggilan storage yang sebenarnya.


def _supabase_upload(bucket: str, path: str, data: bytes, upsert: bool = True, client=None):
    return _client(client).storage.from_(bucket).upload(
        path=path,
        file=data,
        file_options={"content-type": "application/pdf", "upsert": "true" if upsert else "false"},
    )


def _supabase_remove(bucket: str, path: str, client=None):
    return _client(client).storage.from_(bucket).remove([path])


def _supabase_public_url(bucket: str, path: str, client=None):
    return _client(client).storage.from_(bucket).get_public_url(path)


def _supabase_signed_url(bucket: str, path: str, expires: int = 3600, client=None):
    return _client(client).storage.from_(bucket).create_signed_url(path, expires)


def _supabase_signed_urls(bucket: str, paths, expires: int = 3600, client=None):
    return _client(client).storage.from_(bucket).create_signed_urls(list(paths), expires)


# ============================== Transport R2 =================================


def _r2_client():
    """Klien S3 R2 (boto3) dari Settings; di-cache per kredensial."""
    import boto3
    from botocore.config import Config

    settings = _settings()
    account = str(getattr(settings, "r2_account_id", "") or "").strip()
    access = str(getattr(settings, "r2_access_key_id", "") or "").strip()
    secret = str(getattr(settings, "r2_secret_access_key", "") or "").strip()
    if not (account and access and secret):
        raise RuntimeError(
            "[STORAGE] konfigurasi R2 belum lengkap "
            "(R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY)."
        )
    cache_key = (account, access, secret)
    client = _R2_CLIENTS.get(cache_key)
    if client is None:
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )
        _R2_CLIENTS[cache_key] = client
    return client


def _r2_error(exc):
    """-> (kode, status_http) untuk ClientError boto3, selain itu (None, None)."""
    try:
        from botocore.exceptions import ClientError
    except Exception:
        return None, None
    if isinstance(exc, ClientError):
        response = getattr(exc, "response", {}) or {}
        code = (response.get("Error", {}) or {}).get("Code")
        status = (response.get("ResponseMetadata", {}) or {}).get("HTTPStatusCode")
        return code, status
    return None, None


def _r2_is_missing(exc) -> bool:
    """True bila error menandakan objek tidak ada (bukan bucket tidak ada)."""
    code, status = _r2_error(exc)
    if code == "NoSuchBucket":
        return False
    return status == 404 or code in {"404", "NoSuchKey", "NotFound"}


def _r2_object_exists(s3, bucket: str, path: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=path)
        return True
    except Exception as exc:
        if _r2_is_missing(exc):
            return False
        raise


def _r2_upload(bucket: str, path: str, data: bytes, upsert: bool = True):
    """Upload PDF ke R2. Exception naik ke pemanggil.

    ``upsert=False`` memakai conditional put ``IfNoneMatch='*'``; bila botocore
    tidak mendukung parameter itu, fallback memeriksa ``head_object`` dulu.
    Sukses di-log ``storage_r2_ok`` (sinyal positif pemantauan).
    """
    s3 = _r2_client()
    physical = _r2_physical_bucket(bucket)
    kwargs = {
        "Bucket": physical,
        "Key": path,
        "Body": data,
        "ContentType": R2_PDF_CONTENT_TYPE,
    }
    if _r2_public_base(bucket):
        kwargs["CacheControl"] = R2_PUBLIC_CACHE_CONTROL
    if upsert:
        resp = s3.put_object(**kwargs)
    else:
        try:
            resp = s3.put_object(IfNoneMatch="*", **kwargs)
        except Exception as exc:
            try:
                from botocore.exceptions import ParamValidationError
            except Exception:
                ParamValidationError = ()  # type: ignore[assignment]
            if not isinstance(exc, ParamValidationError):
                raise
            if _r2_object_exists(s3, physical, path):
                raise RuntimeError(
                    f"[STORAGE] objek sudah ada (upsert=False): {physical}/{path}"
                )
            resp = s3.put_object(**kwargs)
    _log_r2_ok("upload", bucket, physical, path)
    return resp


def _r2_remove(bucket: str, path: str) -> dict:
    try:
        _r2_client().delete_object(Bucket=_r2_physical_bucket(bucket), Key=path)
        return {"ok": True, "missing": False, "error": None}
    except Exception as exc:
        if _r2_is_missing(exc):
            logger.info("[STORAGE] remove R2: objek sudah tidak ada (%s/%s).", bucket, path)
            return {"ok": False, "missing": True, "error": None}
        logger.warning("[STORAGE] remove R2 gagal (%s/%s): %s", bucket, path, exc)
        return {"ok": False, "missing": False, "error": str(exc)}


def _r2_public_url(bucket: str, path: str) -> str:
    base = _r2_public_base(bucket)
    if not base:
        raise RuntimeError(
            f"[STORAGE] bucket '{bucket}' (suffix '{r2_bucket_suffix()}') tidak punya "
            "base publik di R2_PUBLIC_BASES."
        )
    # Encode path (spasi -> %20) agar konsisten dengan Supabase get_public_url.
    return base.rstrip("/") + "/" + quote(str(path).lstrip("/"), safe="/")


def _r2_signed_url(bucket: str, path: str, expires: int = 3600):
    try:
        return _r2_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": _r2_physical_bucket(bucket), "Key": path},
            ExpiresIn=int(expires),
        )
    except Exception as exc:
        logger.warning("[STORAGE] presign R2 gagal (%s/%s): %s", bucket, path, exc)
        return None


# =============================== API publik ==================================


def upload_pdf(bucket: str, path: str, data: bytes, upsert: bool = True, client=None):
    """Upload PDF (ContentType=application/pdf).

    ``supabase``: hanya Supabase (exception naik). ``dual``: Supabase dulu
    (otoritatif, exception naik), lalu R2 best-effort (kegagalan -> log
    ``storage_repair``, request tetap sukses). ``r2``: hanya R2 (exception naik).
    """
    backend = _active_backend()
    if backend == "r2":
        return _r2_upload(bucket, path, data, upsert)
    result = _supabase_upload(bucket, path, data, upsert, client=client)
    if backend == "dual":
        try:
            _r2_upload(bucket, path, data, upsert)
        except Exception as exc:
            _log_storage_repair("upload", bucket, path, "r2", exc)
    return result


def public_url(bucket: str, path: str, client=None) -> str:
    """URL publik objek pada bucket publik.

    ``dual`` ikut Supabase (URL kolom DB tetap Supabase sampai cutover).
    """
    if _active_backend() == "r2":
        return _r2_public_url(bucket, path)
    return _supabase_public_url(bucket, path, client=client)


def signed_url(bucket: str, path: str, expires: int = 3600, client=None):
    """Signed URL tunggal (string) atau ``None`` bila gagal."""
    if not path:
        return None
    if _active_backend() == "r2":
        return _r2_signed_url(bucket, path, expires)
    resp = _supabase_signed_url(bucket, path, expires, client=client)
    if isinstance(resp, dict):
        return resp.get("signedURL") or resp.get("signedUrl")
    return None


def signed_urls(bucket: str, paths, expires: int = 3600, client=None) -> dict:
    """Batch signed URL -> ``{path: url|None}``.

    Hanya URL ``https://`` tanpa ``error`` yang dipakai. Kegagalan batch tidak
    menggagalkan pemanggil (dikembalikan sebagai ``None`` per path) dan di-log.
    """
    result: dict = {p: None for p in paths if p}
    if not result:
        return result
    if _active_backend() == "r2":
        for p in result:
            result[p] = _r2_signed_url(bucket, p, expires)
        return result
    try:
        response = _supabase_signed_urls(bucket, list(result), expires, client=client) or []
    except Exception as exc:
        logger.warning("[STORAGE] signed URLs batch gagal (%s): %s", bucket, exc)
        return result
    if isinstance(response, dict):
        response = response.get("data") or response.get("signedURLs") or []
    for item in response or []:
        if not isinstance(item, dict):
            continue
        path = item.get("path") or item.get("name")
        url = item.get("signedURL") or item.get("signedUrl")
        if path in result and isinstance(url, str) and url.startswith("https://") and not item.get("error"):
            result[path] = url
    return result


def _is_missing_object_error(exc: Exception) -> bool:
    text = str(exc).lower()
    status_code = getattr(exc, "status", None)
    code = str(getattr(exc, "code", "")).lower()
    missing = status_code in (404, "404") and "bucket" not in text
    missing = missing or code in {"not_found", "object_not_found", "notfound"}
    missing = missing or "object not found" in text or "file not found" in text
    return missing


def _remove_supabase(bucket: str, path: str, client=None) -> dict:
    try:
        _supabase_remove(bucket, path, client=client)
        return {"ok": True, "missing": False, "error": None}
    except Exception as exc:
        missing = _is_missing_object_error(exc)
        if missing:
            logger.info("[STORAGE] remove: objek sudah tidak ada (%s/%s).", bucket, path)
        else:
            logger.warning("[STORAGE] remove gagal (%s/%s): %s", bucket, path, exc)
        return {"ok": False, "missing": missing, "error": str(exc)}


def remove(bucket: str, path: str, client=None) -> dict:
    """Hapus satu objek; kembalikan hasil per-backend (tidak di-swallow).

    Objek yang sudah tidak ada dianggap sukses idempoten (``missing=True``).
    ``dual`` menghapus di dua backend; kegagalan R2 di-log ``storage_repair``
    dan tidak menggagalkan pemanggil. Pemanggil memakai :func:`primary_result`
    untuk menentukan sukses/gagal (Supabase di ``dual``, R2 di ``r2``).

    Bentuk hasil: ``{"supabase": {...}, "r2": {...}}`` (hanya backend yang
    dijalankan yang muncul).
    """
    if not path:
        return {"supabase": {"ok": False, "missing": False, "error": "path kosong"}}
    backend = _active_backend()
    result: dict = {}
    if backend in ("supabase", "dual"):
        result["supabase"] = _remove_supabase(bucket, path, client=client)
    if backend in ("r2", "dual"):
        r2_result = _r2_remove(bucket, path)
        result["r2"] = r2_result
        if backend == "dual" and not r2_result["ok"] and not r2_result["missing"]:
            _log_storage_repair("remove", bucket, path, "r2", r2_result["error"])
    return result
