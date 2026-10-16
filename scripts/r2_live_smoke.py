"""Live R2 smoke test - HANYA bucket staging (-stg).

Membaca .env.staging; memakai boto3; TIDAK menyentuh bucket produksi, Supabase,
atau DB. Semua objek uji memakai prefix ``_smoke/<timestamp>/`` dan dihapus di
blok ``finally`` (termasuk saat tes gagal).

Jalankan: py scripts/r2_live_smoke.py
"""
from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import boto3  # noqa: E402
from botocore.config import Config  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

ENV_FILE = ROOT / ".env.staging"
LOGICAL_BUCKETS = ("raw-material-docs", "legal-documents", "product-attachments")
PUBLIC_BUCKETS = ("raw-material-docs", "legal-documents")
RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def mask(value, keep=4):
    value = value or ""
    if len(value) <= keep * 2:
        return "***"
    return f"{value[:keep]}...{value[-keep:]}"


def safe(name, fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        record(name, False, f"exception {type(exc).__name__}: {exc}")


def main():
    cfg = dotenv_values(str(ENV_FILE))

    # ------------------------------ Guard ------------------------------
    problems = []
    if (cfg.get("DIP_APP_ENV") or "").strip() != "staging":
        problems.append("DIP_APP_ENV != 'staging'")
    suffix = (cfg.get("R2_BUCKET_SUFFIX") or "").strip()
    if suffix != "-stg":
        problems.append("R2_BUCKET_SUFFIX != '-stg'")
    for key in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_PUBLIC_BASES"):
        if not (cfg.get(key) or "").strip():
            problems.append(f"{key} kosong")
    physical = {b: f"{b}{suffix}" for b in LOGICAL_BUCKETS}
    for b, phys in physical.items():
        if not phys.endswith("-stg"):
            problems.append(f"bucket fisik '{phys}' tidak berakhiran -stg (BAHAYA prod!)")
    try:
        bases = {k: str(v).rstrip("/") for k, v in json.loads(cfg.get("R2_PUBLIC_BASES") or "{}").items() if v}
    except Exception as exc:  # noqa: BLE001
        bases = {}
        problems.append(f"R2_PUBLIC_BASES JSON invalid: {exc}")

    if problems:
        print("[GUARD] GAGAL - berhenti tanpa menyentuh apa pun:")
        for p in problems:
            print("  -", p)
        return 2

    print("=== Konfigurasi (tanpa rahasia) ===")
    print("  env           :", (cfg.get("DIP_APP_ENV") or "").strip(), f"({ENV_FILE.name})")
    print("  suffix        :", repr(suffix))
    print("  account_id    :", mask(cfg.get("R2_ACCOUNT_ID", "")))
    print("  access_key_id :", mask(cfg.get("R2_ACCESS_KEY_ID", "")))
    print("  bucket fisik  :", ", ".join(physical.values()))
    for b in PUBLIC_BUCKETS:
        base = bases.get(physical[b]) or bases.get(b) or ""
        print(f"  base publik {b:<20}: {base.split('//')[-1] or '(none)'}")

    account = cfg["R2_ACCOUNT_ID"].strip()
    endpoint = f"https://{account}.r2.cloudflarestorage.com"
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=cfg["R2_ACCESS_KEY_ID"].strip(),
        aws_secret_access_key=cfg["R2_SECRET_ACCESS_KEY"].strip(),
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"_smoke/{ts}/"
    created = defaultdict(list)

    def track(bucket, key):
        if not bucket.endswith("-stg"):
            raise RuntimeError(f"refuse non-staging bucket: {bucket}")
        created[bucket].append(key)

    from app import object_store  # lazy

    class Stub:
        def __init__(self, backend, secret):
            self.storage_backend = backend
            self.r2_bucket_suffix = suffix
            self.r2_account_id = account
            self.r2_access_key_id = cfg["R2_ACCESS_KEY_ID"].strip()
            self.r2_secret_access_key = secret
            self.r2_public_bases = cfg["R2_PUBLIC_BASES"]

    def install(backend="r2", secret=None):
        object_store._settings = lambda: Stub(backend, secret or cfg["R2_SECRET_ACCESS_KEY"].strip())
        object_store._R2_CLIENTS.clear()

    print(f"\nobjek uji prefix: {prefix}")
    try:
        # ------------------------------ Tes 1 ------------------------------
        def t1():
            b1 = physical["raw-material-docs"]
            k1 = prefix + "cond.pdf"
            body1 = b"%PDF-1.4\nfirst\n"
            body2 = b"%PDF-1.4\nsecond-different\n"
            s3.put_object(Bucket=b1, Key=k1, Body=body1, ContentType="application/pdf", IfNoneMatch="*")
            track(b1, k1)
            record("1a. put pertama IfNoneMatch=*", True, "sukses")
            err = None
            try:
                s3.put_object(Bucket=b1, Key=k1, Body=body2, ContentType="application/pdf", IfNoneMatch="*")
            except ClientError as exc:
                err = exc
            if err is None:
                record("1b. put kedua IfNoneMatch=* ditolak", False,
                       "put kedua BERHASIL (IfNoneMatch tidak dihormati / isi berpotensi tertimpa)")
            else:
                code = err.response.get("Error", {}).get("Code")
                status = err.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                record("1b. put kedua IfNoneMatch=* ditolak", True, f"code={code} http={status}")
            got = s3.get_object(Bucket=b1, Key=k1)["Body"].read()
            record("1c. isi tetap yang pertama", got == body1, f"len={len(got)}")
        safe("1. conditional put", t1)

        # ------------------------------ Tes 2 ------------------------------
        def t2():
            install("r2")
            k2 = prefix + "file uji.pdf"
            data2 = b"%PDF-1.4\n% spaced dua\n"
            object_store.upload_pdf("raw-material-docs", k2, data2)
            track(physical["raw-material-docs"], k2)
            url = object_store.public_url("raw-material-docs", k2)
            with httpx.Client(timeout=30, follow_redirects=True) as c:
                r = c.get(url)
            ok = (r.status_code == 200 and r.headers.get("content-type") == "application/pdf"
                  and bool(r.headers.get("cache-control")) and r.content == data2)
            record("2. key ber-spasi via r2.dev", ok,
                   f"http={r.status_code} ct={r.headers.get('content-type')} cc={r.headers.get('cache-control')} url={url}")
        safe("2. key ber-spasi + r2.dev", t2)

        # ------------------------------ Tes 3 ------------------------------
        b3 = physical["product-attachments"]
        k3 = prefix + "private.pdf"
        data3 = b"%PDF-1.4\n% private\n"
        signed = {"url": None}

        def t3a():
            s3.put_object(Bucket=b3, Key=k3, Body=data3, ContentType="application/pdf")
            track(b3, k3)
            signed["url"] = object_store._r2_signed_url("product-attachments", k3, 60)
            if not signed["url"]:
                record("3a. presigned GET", False, "presign mengembalikan None")
                return
            with httpx.Client(timeout=30, follow_redirects=True) as c:
                r = c.get(signed["url"])
            record("3a. presigned GET", r.status_code == 200 and r.content == data3,
                   f"http={r.status_code} bytes={len(r.content)}")
        safe("3a. presigned GET", t3a)

        def t3b():
            # R2 menjawab request anonim ke endpoint S3 dengan 400 InvalidArgument
            # (Authorization), BUKAN 403. Yang dibuktikan: tidak ada akses anonim
            # (status ditolak DAN body tidak memuat isi objek uji).
            with httpx.Client(timeout=30) as c:
                r = c.get(f"{endpoint}/{b3}/{k3}")
            code = msg = ""
            try:
                import xml.etree.ElementTree as ET

                root = ET.fromstring(r.content)
                code = (root.findtext("Code") or "").strip()
                msg = (root.findtext("Message") or "").strip()
            except Exception:  # noqa: BLE001
                pass
            denied = r.status_code in (400, 401, 403) and data3 not in r.content
            detail = f"http={r.status_code}"
            if code or msg:
                detail += f" {code}/{msg}"
            record("3b. unsigned GET ke S3 ditolak (bucket privat)", denied, detail)
        safe("3b. unsigned GET", t3b)

        def t3c():
            no_pub = "product-attachments" not in bases and b3 not in bases
            record("3c. bucket privat tanpa base publik", no_pub, f"bases={sorted(bases)}")
        safe("3c. tanpa akses publik", t3c)

        def t3d():
            if not signed["url"]:
                record("3d. presigned kedaluwarsa -> 403", False, "tidak ada presigned URL")
                return
            print("    menunggu TTL presigned lewat (70 dtk)...")
            time.sleep(70)
            with httpx.Client(timeout=30) as c:
                r = c.get(signed["url"])
            record("3d. presigned kedaluwarsa -> 403", r.status_code == 403, f"http={r.status_code}")
        safe("3d. presigned kedaluwarsa", t3d)

        # ------------------------------ Tes 4 ------------------------------
        def t4():
            install("dual", secret="wrong-secret-for-smoke")
            lines = []

            class Cap(logging.Handler):
                def emit(self, rec):
                    lines.append(rec.getMessage())

            cap = Cap()
            lg = logging.getLogger("app.object_store")
            lg.addHandler(cap)
            lg.setLevel(logging.WARNING)

            class _Up:
                def upload(self, **kw):
                    return {"ok": True}

            class _Storage:
                def from_(self, b):
                    return _Up()

            class _FakeClient:
                storage = _Storage()

            raised = None
            try:
                object_store.upload_pdf("raw-material-docs", prefix + "dual.pdf", b"%PDF-1.4\n", client=_FakeClient())
            except Exception as exc:  # noqa: BLE001
                raised = exc
            finally:
                lg.removeHandler(cap)

            record("4a. dual write gagal TIDAK raise", raised is None,
                   f"raised={type(raised).__name__ if raised else None}")
            repair = [m for m in lines if "storage_repair" in m]
            record("4b. tercatat log storage_repair", bool(repair), repair[0] if repair else "(tidak ada baris storage_repair)")
        safe("4. dual write failure", t4)

        # ------------------------------ Tes 5 ------------------------------
        def t5():
            print("\n=== Tes 5: CORS bucket -stg (read-only) ===")
            outcomes = []
            for b in physical.values():
                try:
                    r = s3.get_bucket_cors(Bucket=b)
                    outcomes.append(f"{b}=OK")
                    print(f"  {b}: {json.dumps(r.get('CORSRules'))}")
                except ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code")
                    outcomes.append(f"{b}={code}")
                    print(f"  {b}: tidak dapat dibaca ({code})")
            record("5. get_bucket_cors (read-only)", True, "; ".join(outcomes))
        safe("5. CORS read-only", t5)

    finally:
        print("\n=== Cleanup ===")
        for bucket, keys in created.items():
            for k in keys:
                try:
                    s3.delete_object(Bucket=bucket, Key=k)
                    print(f"  deleted {bucket}/{k}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  GAGAL hapus {bucket}/{k}: {exc}")
        leftover = []
        for b in physical.values():
            try:
                resp = s3.list_objects_v2(Bucket=b, Prefix="_smoke/")
                leftover += [f"{b}/{o['Key']}" for o in resp.get("Contents", [])]
            except Exception as exc:  # noqa: BLE001
                print(f"  list {b} error: {exc}")
        record("cleanup: tidak ada sisa _smoke/", not leftover,
               "bersih" if not leftover else f"tersisa: {leftover}")

    failed = [r for r in RESULTS if not r[1]]
    print("\n=== Ringkasan ===")
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} lulus.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
