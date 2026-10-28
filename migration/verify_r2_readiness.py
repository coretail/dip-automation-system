"""Verify R2 readiness as the primary storage for the production database.

This script is strictly read-only: it never updates DB rows, writes/deletes
objects, or uploads/deletes from Supabase Storage or R2.

Examples::

    py migration/verify_r2_readiness.py --env prod --expect-suffix ""
    py migration/verify_r2_readiness.py --env staging --expect-suffix "-stg" --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from migration.audit_storage import PAGE, URL_COLUMNS, norm  # noqa: E402
from migration.backfill_r2_urls import build_extractor, fetch_rows, load_env, make_target  # noqa: E402

BUCKETS = ("raw-material-docs", "legal-documents", "product-attachments")
MAX_EXAMPLES = 20
RETRIES = 3
HTTP_TIMEOUT = 15


def parse_bases(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw or "{}")
        if not isinstance(value, dict):
            return {}
        return {str(k): str(v).rstrip("/") for k, v in value.items() if v}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def r2_client(cfg):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=f"https://{cfg['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=cfg["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=cfg["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def physical(bucket: str, suffix: str) -> str:
    return f"{bucket}{suffix}" if suffix else bucket


def retry_call(fn):
    last = None
    for attempt in range(RETRIES):
        try:
            return fn()
        except Exception as exc:  # network/client errors are retried uniformly
            last = exc
            if attempt + 1 < RETRIES:
                time.sleep(0.25 * (2**attempt))
    raise last


def supabase_bucket_exists(client, bucket: str) -> bool:
    """Check that the Supabase Storage bucket actually exists (read-only).
    A missing bucket makes storage.list() raise; without this explicit check
    the inventory failure is easy to misread, and a missing bucket would only
    surface as a generic 'inventory failed' FAIL instead of a clear one."""
    try:
        client.storage.from_(bucket).list("", {"limit": 1, "offset": 0})
        return True
    except Exception:
        return False


def supabase_objects(client, bucket: str) -> dict[str, int]:
    """Recursively list objects and retain metadata sizes (read-only)."""
    storage = client.storage.from_(bucket)
    result: dict[str, int] = {}

    def walk(prefix=""):
        offset = 0
        while True:
            items = storage.list(prefix, {"limit": PAGE, "offset": offset}) or []
            for item in items:
                name = item.get("name")
                if not name:
                    continue
                key = f"{prefix}/{name}" if prefix else name
                if item.get("id") is None and not item.get("metadata"):
                    walk(key)
                else:
                    metadata = item.get("metadata") or {}
                    try:
                        result[norm(key)] = int(metadata.get("size", 0) or 0)
                    except (TypeError, ValueError):
                        result[norm(key)] = 0
            if len(items) < PAGE:
                break
            offset += PAGE

    walk()
    return result


def r2_objects(s3, bucket: str) -> dict[str, int]:
    result: dict[str, int] = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for item in page.get("Contents", []):
            result[norm(item.get("Key", ""))] = int(item.get("Size", 0) or 0)
    return result


def examples(values):
    return [list(v) if isinstance(v, tuple) else v for v in list(values)[:MAX_EXAMPLES]]


def http_request(url, method="HEAD", headers=None):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; dip-r2-verify/1.0)", **(headers or {})}
    request = Request(url, method=method, headers=headers)
    started = time.monotonic()
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, time.monotonic() - started, None
    except HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, time.monotonic() - started, None
    except (URLError, OSError) as exc:
        return 0, {}, time.monotonic() - started, str(exc)


def http_probe(url, headers=None, allow_range_fallback=False):
    def request():
        result = http_request(url, "HEAD", headers)
        if result[3]:
            raise OSError(result[3])
        return result

    try:
        result = retry_call(request)
        if allow_range_fallback and result[0] not in (200, 206):
            def range_request():
                ranged = http_request(url, "GET", {**(headers or {}), "Range": "bytes=0-0"})
                if ranged[3]:
                    raise OSError(ranged[3])
                return ranged

            result = retry_call(range_request)
        return result
    except Exception as exc:
        return 0, {}, 0.0, str(exc)


def add_check(report, name, status, message, **data):
    item = {"name": name, "status": status, "message": message, **data}
    report["checks"].append(item)
    print(f"{status}: {name} - {message}")
    return item


def finish_report(report, args, conclusion=None):
    fails = [c["name"] for c in report["checks"] if c["status"] == "FAIL"]
    warns = [c["name"] for c in report["checks"] if c["status"] == "WARN"]
    infos = [c["name"] for c in report["checks"] if c["status"] == "INFO"]
    report["conclusion"] = conclusion or ("BELUM SIAP" if fails else "SIAP")
    report["blockers"] = fails
    report["warnings"] = warns
    report["info"] = infos
    print("\nRINGKASAN")
    for check in report["checks"]:
        print(f"{check['status']}: {check['name']}")
    print(f"KESIMPULAN: {report['conclusion']} untuk STORAGE_BACKEND=r2; FAIL={len(fails)}; WARN={len(warns)}")
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=True)
    return 1 if fails else 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=("prod", "staging"), default="prod")
    parser.add_argument("--expect-suffix", required=True)
    parser.add_argument("--sample", type=int, default=15)
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--origin")
    args = parser.parse_args(argv)
    if args.sample < 0:
        parser.error("--sample must be non-negative")

    envfile = ".env" if args.env == "prod" else ".env.staging"
    cfg = load_env(envfile)
    suffix = cfg.get("R2_BUCKET_SUFFIX", "")
    if suffix != args.expect_suffix:
        print(f"FAIL: R2_BUCKET_SUFFIX mismatch (expected {args.expect_suffix!r}, env has {suffix!r})")
        return 2

    report = {"env": args.env, "env_file": envfile, "suffix": suffix, "checks": [], "started_at": datetime.now(timezone.utc).isoformat()}
    missing_cfg = [key for key in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY") if not cfg.get(key)]
    bases = parse_bases(cfg.get("R2_PUBLIC_BASES", ""))
    public_physical_buckets = [physical(bucket, suffix) for bucket in BUCKETS[:2]]
    missing_bases = [name for name in public_physical_buckets if not bases.get(name)]
    invalid_bases = [
        name for name in public_physical_buckets
        if bases.get(name)
        and (urlparse(bases[name]).scheme not in ("http", "https") or not urlparse(bases[name]).netloc)
    ]
    config_status = "FAIL" if missing_cfg or missing_bases or invalid_bases or not bases else "PASS"
    add_check(report, "KONFIGURASI", config_status, f"missing credentials={len(missing_cfg)}, missing public bases={len(missing_bases)}, invalid public bases={len(invalid_bases)}", storage_backend=cfg.get("STORAGE_BACKEND", ""), missing_credentials=missing_cfg, missing_bases=missing_bases, invalid_bases=invalid_bases)
    print(f"INFO: STORAGE_BACKEND={cfg.get('STORAGE_BACKEND', '')}")
    if config_status == "FAIL":
        return finish_report(report, args, "BELUM SIAP")

    try:
        from supabase import create_client
        db = create_client(cfg.get("SUPABASE_URL", ""), cfg.get("SUPABASE_SERVICE_ROLE_KEY", ""))
        s3 = r2_client(cfg)
    except Exception as exc:
        add_check(report, "KONFIGURASI CLIENT", "FAIL", f"client initialization failed: {type(exc).__name__}")
        return finish_report(report, args, "BELUM SIAP")

    inventories = {}
    for logical in BUCKETS:
        physical_name = physical(logical, suffix)
        try:
            retry_call(lambda p=physical_name: s3.head_bucket(Bucket=p))
        except Exception as exc:
            add_check(report, f"KEBERADAAN BUCKET R2 {physical_name}", "FAIL", f"head_bucket failed: {type(exc).__name__}")
            continue
        if not retry_call(lambda b=logical: supabase_bucket_exists(db, b)):
            # Eksplisit: bucket Supabase sumber tidak ada -> bandingkan isi tidak
            # bermakna, dan cutover tidak boleh dianggap SIAP.
            add_check(report, f"KEBERADAAN BUCKET SUPABASE {logical}", "FAIL", "bucket tidak ditemukan di Supabase Storage")
            continue
        try:
            r2 = retry_call(lambda p=physical_name: r2_objects(s3, p))
            supa = retry_call(lambda b=logical: supabase_objects(db, b))
            missing = sorted(set(supa) - set(r2))
            extra = sorted(set(r2) - set(supa))
            mismatch = sorted(k for k in set(supa) & set(r2) if supa[k] != r2[k])
            inventories[logical] = {"supabase": supa, "r2": r2}
            status = "FAIL" if missing or mismatch else ("WARN" if extra else "PASS")
            add_check(report, f"KESAMAAN ISI {logical}", status, f"Supabase={len(supa)} objek/{sum(supa.values())} bytes; R2={len(r2)} objek/{sum(r2.values())} bytes; MISSING_IN_R2={len(missing)}; EXTRA_IN_R2={len(extra)}; SIZE_MISMATCH={len(mismatch)}", missing_in_r2=examples(missing), extra_in_r2=examples(extra), size_mismatch=examples(mismatch))
        except Exception as exc:
            add_check(report, f"KESAMAAN ISI {logical}", "FAIL", f"inventory failed: {type(exc).__name__}")

    extract = build_extractor(bases, suffix)
    refs = []
    skipped = []
    for table, column in URL_COLUMNS:
        rows = fetch_rows(db, table, column)
        if rows is None:
            skipped.append(f"{table}.{column}")
            continue
        filled = r2_count = supa_count = unknown = 0
        for row in rows:
            value = row.get(column)
            if not value:
                continue
            filled += 1
            bucket, path = extract(value)
            if bucket and path:
                if str(value).find("/storage/v1/object/public/") >= 0:
                    supa_count += 1
                else:
                    r2_count += 1
                    refs.append((bucket, norm(path)))
            else:
                unknown += 1
        status = "WARN" if supa_count else ("WARN" if unknown else "PASS")
        suggestion = "; saran: jalankan ulang backfill_r2_urls.py --target r2 (dry-run dulu)" if supa_count else ""
        add_check(report, f"REFERENSI {table}.{column}", status, f"terisi={filled}; R2={r2_count}; STILL_SUPABASE={supa_count}; tidak dikenali={unknown}{suggestion}", filled=filled, r2=r2_count, still_supabase=supa_count, unknown=unknown)

    try:
        from botocore.exceptions import ClientError
    except ImportError:
        ClientError = ()

    def head_ref(item):
        bucket, key = item
        try:
            retry_call(lambda: s3.head_object(Bucket=physical(bucket, suffix), Key=norm(key)))
            return None, None
        except Exception as exc:
            if ClientError and isinstance(exc, ClientError):
                code = str((exc.response or {}).get("Error", {}).get("Code", ""))
                if code in ("404", "NoSuchKey", "NotFound"):
                    return item, None
            return None, exc

    unique_refs = sorted(set(refs))
    missing_refs = []
    unchecked_refs = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for future in as_completed([pool.submit(head_ref, item) for item in unique_refs]):
            missing, error = future.result()
            if missing:
                missing_refs.append(missing)
            if error:
                unchecked_refs.append(type(error).__name__)
    add_check(report, "REFERENSI DB -> R2 HEAD", "FAIL" if missing_refs else ("WARN" if unchecked_refs else "PASS"), f"unik={len(unique_refs)}; REF_MISSING={len(missing_refs)}; UNCHECKED={len(unchecked_refs)}", ref_missing=examples(sorted(missing_refs)), unchecked=unchecked_refs[:MAX_EXAMPLES])

    build_url, _ = make_target(cfg, "r2", bases, suffix, cfg.get("SUPABASE_URL", ""))
    changes = 0
    for table, column in URL_COLUMNS:
        rows = fetch_rows(db, table, column)
        if rows:
            for row in rows:
                old = row.get(column)
                if old:
                    bucket, path = extract(old)
                    if bucket and path:
                        new = build_url(bucket, path)
                        changes += bool(new and new != str(old))
    add_check(report, "IDEMPOTENSI BACKFILL", "WARN" if changes else "PASS", f"dry-run internal changes={changes}", changes=changes)

    attachment_rows = fetch_rows(db, "product_attachments", "file_path") or []
    attachment_paths = sorted({norm(row.get("file_path")) for row in attachment_rows if row.get("file_path")})
    attachment_missing = []
    attachment_unchecked = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(head_ref, ("product-attachments", path)) for path in attachment_paths]
        for future in as_completed(futures):
            missing, error = future.result()
            if missing:
                attachment_missing.append(missing)
            if error:
                attachment_unchecked.append(type(error).__name__)
    add_check(report, "PRODUCT-ATTACHMENTS HEAD", "FAIL" if attachment_missing else ("WARN" if attachment_unchecked else "PASS"), f"path unik={len(attachment_paths)}; ATTACH_MISSING={len(attachment_missing)}; UNCHECKED={len(attachment_unchecked)}", attach_missing=examples(sorted(attachment_missing)), unchecked=attachment_unchecked[:MAX_EXAMPLES])

    presigned_results = []
    for key in random.sample(attachment_paths, min(args.sample, len(attachment_paths))):
        try:
            signed = s3.generate_presigned_url("head_object", Params={"Bucket": physical("product-attachments", suffix), "Key": key}, ExpiresIn=60)
            status, _, elapsed, error = http_probe(signed, allow_range_fallback=False)
            endpoint = f"https://{cfg['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com/{physical('product-attachments', suffix)}/{quote(key)}"
            unsigned_status, _, _, unsigned_error = http_probe(endpoint, allow_range_fallback=False)
            private_base = bases.get(physical("product-attachments", suffix))
            base_status = None
            base_error = None
            if private_base:
                base_status, _, _, base_error = http_probe(f"{private_base.rstrip('/')}/{quote(key, safe='/')}", allow_range_fallback=False)
            presigned_results.append({"key": key, "status": status, "unsigned_status": unsigned_status, "base_status": base_status, "seconds": elapsed, "error": error, "unsigned_error": unsigned_error, "base_error": base_error})
        except Exception as exc:
            presigned_results.append({"key": key, "status": 0, "unsigned_status": 0, "error": type(exc).__name__})
    bad_signed = [r for r in presigned_results if r.get("status") != 200]
    public_private = [r for r in presigned_results if r.get("unsigned_status") == 200 or r.get("base_status") == 200]
    unsigned_unexpected = [r for r in presigned_results if r.get("unsigned_status") not in (200, 401, 403, 404)]
    base_unexpected = [r for r in presigned_results if r.get("base_status") not in (None, 200, 401, 403, 404)]
    add_check(report, "PRODUCT-ATTACHMENTS PRESIGNED", "FAIL" if bad_signed or public_private else ("WARN" if unsigned_unexpected or base_unexpected else "PASS"), f"sample={len(presigned_results)}; signed_non_200={len(bad_signed)}; public={len(public_private)}; unexpected_unsigned={len(unsigned_unexpected)}", samples=presigned_results)

    origin = args.origin or cfg.get("APP_URL") or cfg.get("PUBLIC_APP_URL") or cfg.get("SITE_URL")
    public_samples = []
    for logical in BUCKETS[:2]:
        keys = list((inventories.get(logical, {}).get("r2") or {}).keys())
        for key in random.sample(keys, min(args.sample, len(keys))):
            public_base = bases.get(physical(logical, suffix))
            if not public_base:
                continue
            url = f"{public_base.rstrip('/')}/{quote(key, safe='/')}"
            headers = {"Origin": origin} if origin else {}
            status, response_headers, elapsed, error = http_probe(url, headers, True)
            expected_size = (inventories.get(logical, {}).get("r2") or {}).get(key)
            content_length = response_headers.get("content-length")
            if status == 206 and response_headers.get("content-range"):
                content_length = response_headers["content-range"].rsplit("/", 1)[-1]
            size_match = content_length is not None and str(content_length) == str(expected_size)
            public_samples.append({"bucket": logical, "key": key, "status": status, "content_length": content_length, "expected_size": expected_size, "size_match": size_match, "content_type": response_headers.get("content-type", ""), "seconds": elapsed, "cors": bool(response_headers.get("access-control-allow-origin")), "error": error})
    bad_public = [r for r in public_samples if r["status"] not in (200, 206) or not r["content_type"] or not r["size_match"]]
    no_cors = [r for r in public_samples if not r["cors"]]
    if not origin:
        # Tanpa --origin, CORS memang tidak diuji (header Origin tidak dikirim)
        # -> laporkan INFO, bukan WARN, agar tidak salah dibaca sebagai drift.
        public_status = "INFO" if public_samples and not bad_public else ("FAIL" if bad_public else "WARN")
        cors_note = "CORS tidak diuji (tanpa --origin)"
    else:
        public_status = "WARN" if not public_samples else ("FAIL" if bad_public else ("WARN" if no_cors else "PASS"))
        cors_note = f"tanpa CORS={len(no_cors)}"
    public_message = "tidak ada sampel" if not public_samples else f"sample={len(public_samples)}; non_200_or_no_type={len(bad_public)}; {cors_note}"
    add_check(report, "AKSES PUBLIK", public_status, public_message, samples=public_samples, avg_seconds=(sum(r["seconds"] for r in public_samples) / len(public_samples) if public_samples else 0))
    add_check(report, "HAK AKSES KREDENSIAL", "INFO", "Hanya verifikasi baca/list. Verifikasi hak tulis dilakukan lewat upload uji manual di mode dual.")

    return finish_report(report, args)


if __name__ == "__main__":
    sys.exit(main())
