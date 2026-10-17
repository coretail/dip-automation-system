"""Unit test object_store: dispatch supabase/dual/r2 + log storage_repair/storage_r2_ok.

Tanpa jaringan: klien R2 dan transport Supabase di-fake. Jalankan:
`py tests/test_object_store_r2.py`.
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import object_store  # noqa: E402

BUCKETS = {
    "raw-material-docs": "https://pub-rmd.r2.dev",
    "legal-documents": "https://pub-legal.r2.dev",
}

failures = 0


def check(label, cond, detail=""):
    global failures
    if not cond:
        failures += 1
        print(f"FAIL {label}: {detail}")


class FakeSettings:
    def __init__(self, backend, suffix="", bases=None):
        self.storage_backend = backend
        self.r2_bucket_suffix = suffix
        self.r2_public_bases = json.dumps(BUCKETS if bases is None else bases)
        self.r2_account_id = "acct"
        self.r2_access_key_id = "kid"
        self.r2_secret_access_key = "secret"


class FakeS3:
    def __init__(self):
        self.puts = []
        self.deletes = []
        self.fail_put = False
        self.fail_delete = False

    def put_object(self, **kw):
        if self.fail_put:
            raise RuntimeError("r2 put boom")
        self.puts.append(kw)
        return {"ETag": "etag"}

    def delete_object(self, **kw):
        if self.fail_delete:
            raise RuntimeError("r2 delete boom")
        self.deletes.append(kw)
        return {}

    def head_object(self, **kw):
        raise RuntimeError("not found")

    def generate_presigned_url(self, op, Params=None, ExpiresIn=None):
        return f"https://signed.r2/{Params['Bucket']}/{Params['Key']}?exp={ExpiresIn}"


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


def install(backend, s3, suffix="", bases=None):
    object_store._settings = lambda: FakeSettings(backend, suffix, bases)
    object_store._r2_client = lambda: s3
    object_store._supabase_upload = lambda *a, **k: "SB_UPLOAD"
    object_store._supabase_public_url = lambda bucket, path, client=None: f"SB:/{bucket}/{path}"
    object_store._supabase_signed_url = lambda bucket, path, expires=3600, client=None: {
        "signedURL": f"SB_SIGN:/{bucket}/{path}"
    }
    object_store._supabase_signed_urls = lambda bucket, paths, expires=3600, client=None: [
        {"path": p, "signedURL": f"SB_SIGN:/{bucket}/{p}"} for p in paths
    ]
    object_store._supabase_remove = lambda bucket, path, client=None: None


def main():
    cap = Capture()
    logging.getLogger("app.object_store").addHandler(cap)
    logging.getLogger("app.object_store").setLevel(logging.WARNING)

    # ---------------- mode r2 ----------------
    s3 = FakeS3()
    install("r2", s3)
    check("r2 backend", object_store.storage_backend() == "r2")

    object_store.upload_pdf("raw-material-docs", "coa/a.pdf", b"%PDF-")
    check("r2 upload called", len(s3.puts) == 1, s3.puts)
    if s3.puts:
        p = s3.puts[0]
        check("r2 upload content-type", p["ContentType"] == "application/pdf", p.get("ContentType"))
        check("r2 upload cache public", p.get("CacheControl") == "public, max-age=86400", p.get("CacheControl"))
        check("r2 upload no IfNoneMatch by default", "IfNoneMatch" not in p, p.keys())

    s3.puts.clear()
    object_store.upload_pdf("product-attachments", "p/x.pdf", b"%PDF-", upsert=False)
    check("r2 upload private no cache", "CacheControl" not in s3.puts[0])
    check("r2 upsert=False -> IfNoneMatch", s3.puts[0].get("IfNoneMatch") == "*", s3.puts[0].keys())

    check("r2 public_url",
          object_store.public_url("raw-material-docs", "coa/a.pdf") == "https://pub-rmd.r2.dev/coa/a.pdf")
    check("r2 public_url encode spasi",
          object_store.public_url("raw-material-docs", "brands/hak lisensi.pdf")
          == "https://pub-rmd.r2.dev/brands/hak%20lisensi.pdf")
    try:
        object_store.public_url("product-attachments", "x.pdf")
        check("r2 public_url missing base raises", False, "tidak raise")
    except RuntimeError:
        check("r2 public_url missing base raises", True)

    check("r2 signed_url", object_store.signed_url("product-attachments", "x.pdf", 60)
          == "https://signed.r2/product-attachments/x.pdf?exp=60")
    got = object_store.signed_urls("product-attachments", ["a.pdf", "b.pdf"], 30)
    check("r2 signed_urls", got == {
        "a.pdf": "https://signed.r2/product-attachments/a.pdf?exp=30",
        "b.pdf": "https://signed.r2/product-attachments/b.pdf?exp=30",
    }, got)

    res = object_store.remove("product-attachments", "x.pdf")
    check("r2 remove has only r2 key", set(res) == {"r2"}, res)
    check("r2 primary_result -> r2", object_store.primary_result(res).get("ok") is True, res)

    # ---------------- mode dual ----------------
    s3 = FakeS3()
    install("dual", s3)
    out = object_store.upload_pdf("raw-material-docs", "coa/a.pdf", b"%PDF-")
    check("dual upload supabase authoritative", out == "SB_UPLOAD", out)
    check("dual upload also writes r2", len(s3.puts) == 1, s3.puts)

    cap.records.clear()
    object_store.upload_pdf("raw-material-docs", "coa/a2.pdf", b"%PDF-")
    check("dual upload r2 sukses -> storage_r2_ok", any("storage_r2_ok" in m for m in cap.records), cap.records)

    cap.records.clear()
    s3.fail_put = True
    out = object_store.upload_pdf("raw-material-docs", "coa/b.pdf", b"%PDF-")
    check("dual upload r2 failure tidak raise", out == "SB_UPLOAD", out)
    check("dual upload r2 failure -> storage_repair", any("storage_repair" in m for m in cap.records), cap.records)

    check("dual public_url tetap Supabase",
          object_store.public_url("raw-material-docs", "coa/a.pdf") == "SB:/raw-material-docs/coa/a.pdf")
    check("dual signed_url tetap Supabase",
          object_store.signed_url("product-attachments", "x.pdf") == "SB_SIGN:/product-attachments/x.pdf")

    cap.records.clear()
    s3.fail_delete = True
    res = object_store.remove("raw-material-docs", "coa/a.pdf")
    check("dual remove punya dua key", set(res) == {"supabase", "r2"}, res)
    check("dual remove r2 gagal -> storage_repair", any("storage_repair" in m for m in cap.records), cap.records)
    check("dual primary_result -> supabase ok", object_store.primary_result(res).get("ok") is True, res)

    # ---------------- mode supabase (tak berubah) ----------------
    s3 = FakeS3()
    install("supabase", s3)
    out = object_store.upload_pdf("raw-material-docs", "coa/a.pdf", b"%PDF-")
    check("supabase upload no r2", out == "SB_UPLOAD" and not s3.puts, (out, s3.puts))
    check("supabase public_url", object_store.public_url("raw-material-docs", "a.pdf") == "SB:/raw-material-docs/a.pdf")
    res = object_store.remove("raw-material-docs", "coa/a.pdf")
    check("supabase remove only supabase", set(res) == {"supabase"}, res)

    # ---------------- suffix environment (staging "-stg") ----------------
    s3 = FakeS3()
    stg_bases = {"raw-material-docs-stg": "https://pub-rmd-stg.r2.dev"}
    install("r2", s3, suffix="-stg", bases=stg_bases)
    object_store.upload_pdf("raw-material-docs", "coa/a.pdf", b"%PDF-")
    check("suffix upload pakai bucket fisik",
          s3.puts[0]["Bucket"] == "raw-material-docs-stg", s3.puts[0]["Bucket"])
    check("suffix public_url pakai base fisik",
          object_store.public_url("raw-material-docs", "coa/a.pdf") == "https://pub-rmd-stg.r2.dev/coa/a.pdf")
    check("suffix signed pakai bucket fisik",
          object_store.signed_url("raw-material-docs", "a.pdf") == "https://signed.r2/raw-material-docs-stg/a.pdf?exp=3600")
    check("suffix parse kembali ke bucket logis",
          object_store.parse_storage_url("https://pub-rmd-stg.r2.dev/coa/a.pdf") == ("raw-material-docs", "coa/a.pdf"),
          object_store.parse_storage_url("https://pub-rmd-stg.r2.dev/coa/a.pdf"))

    # ---------------- backend tak dikenal ----------------
    object_store._settings = lambda: FakeSettings("gcs")
    try:
        object_store.upload_pdf("raw-material-docs", "a.pdf", b"%PDF-")
        check("backend tak dikenal raise", False, "tidak raise")
    except RuntimeError:
        check("backend tak dikenal raise", True)

    if failures:
        print(f"\n{failures} GAGAL.")
        return 1
    print("object_store dispatch r2/dual: semua kasus LULUS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
