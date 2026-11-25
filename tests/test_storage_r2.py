"""Unit test gabungan storage & R2 (pure-local, tanpa koneksi/secret):
  1. object_store.parse_storage_url (Supabase Storage, R2 bases, spasi/%20, prefix overlap)
  2. object_store dispatch (supabase/dual/r2, log storage_repair/storage_r2_ok, suffix -stg)
  3. Helper murni migration/verify_r2_readiness.py (E-12)

Digabungkan pada Task 9 dari:
  - test_parse_storage_url.py
  - test_object_store_r2.py
  - test_verify_r2_readiness_logic.py

Jalankan: python tests/test_storage_r2.py
"""
import json
import logging
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app import object_store  # noqa: E402
from app.object_store import parse_storage_url  # noqa: E402
from migration.verify_r2_readiness import (  # noqa: E402
    parse_bases,
    physical,
    supabase_bucket_exists,
)

# =====================================================================
# Bagian 1: object_store.parse_storage_url
# =====================================================================

SUPABASE = "https://dytuprmoorvrugutozwv.supabase.co"
BASES = {
    "raw-material-docs": "https://pub-rmd.r2.dev",
    "legal-documents": "https://pub-legal.r2.dev",
    "product-attachments": "https://pub-att.r2.dev",
}

PARSE_CASES = [
    # --- Supabase Storage ---
    (f"{SUPABASE}/storage/v1/object/public/raw-material-docs/coa/coa_B1.pdf",
     ("raw-material-docs", "coa/coa_B1.pdf")),
    (f"{SUPABASE}/storage/v1/object/public/legal-documents/brands/hak lisensi.pdf",
     ("legal-documents", "brands/hak lisensi.pdf")),
    (f"{SUPABASE}/storage/v1/object/public/product-attachments/products/p/2026-10-16/ab12_lampiran.pdf",
     ("product-attachments", "products/p/2026-10-16/ab12_lampiran.pdf")),
    (f"{SUPABASE}/storage/v1/object/public/product-attachments/a/b.pdf?token=xyz&t=1",
     ("product-attachments", "a/b.pdf")),
    (f"{SUPABASE}/storage/v1/object/public/raw-material-docs/coa/file%20name.pdf",
     ("raw-material-docs", "coa/file name.pdf")),
    # bucket kosong path -> None
    (f"{SUPABASE}/storage/v1/object/public/raw-material-docs",
     (None, None)),
    # --- R2 (base per bucket) ---
    ("https://pub-rmd.r2.dev/coa/coa_B1.pdf", ("raw-material-docs", "coa/coa_B1.pdf")),
    ("https://pub-legal.r2.dev/brands/hak lisensi.pdf", ("legal-documents", "brands/hak lisensi.pdf")),
    ("https://pub-legal.r2.dev/brands/hak%20lisensi.pdf", ("legal-documents", "brands/hak lisensi.pdf")),
    ("https://pub-att.r2.dev/products/p/2026-10-16/ab12_lampiran.pdf",
     ("product-attachments", "products/p/2026-10-16/ab12_lampiran.pdf")),
    ("https://pub-att.r2.dev/a/b.pdf?token=xyz", ("product-attachments", "a/b.pdf")),
    # base saja (tanpa path) -> (bucket, None)
    ("https://pub-rmd.r2.dev", ("raw-material-docs", None)),
    ("https://pub-rmd.r2.dev/", ("raw-material-docs", None)),
    # --- format tak dikenal / negatif ---
    ("https://evil.r2.dev/coa/coa_B1.pdf", (None, None)),
    # prefix-confusion: base + ".evil.com" BUKAN bucket kita
    ("https://pub-rmd.r2.dev.evil.com/coa/x.pdf", (None, None)),
    ("https://example.com/random/path.pdf", (None, None)),
    ("", (None, None)),
    (None, (None, None)),
]

ROUNDTRIP_CASES = [
    (f"{SUPABASE}/storage/v1/object/public/raw-material-docs/coa/file%20name.pdf",
     ("raw-material-docs", "coa/file name.pdf")),
    ("https://pub-legal.r2.dev/brands/hak%20lisensi.pdf",
     ("legal-documents", "brands/hak lisensi.pdf")),
    ("https://pub-legal.r2.dev/brands/100%25%20resmi.pdf",
     ("legal-documents", "brands/100% resmi.pdf")),
]


def test_parse_storage_url_cases():
    """Converted from test_parse_storage_url.py::main."""
    for url, expected in PARSE_CASES:
        got = parse_storage_url(url, BASES)
        label = (url or "")[:70]
        assert got == expected, f"FAIL {label!r}: got={got!r} expected={expected!r}"

    for url, expected in ROUNDTRIP_CASES:
        got = parse_storage_url(url, BASES)
        label = (url or "")[:70]
        assert got == expected, f"FAIL roundtrip {label!r}: got={got!r} expected={expected!r}"

    # Base terpanjang menang saat ada prefix mirip (bukan crash/salah bucket).
    bases_overlap = dict(BASES)
    bases_overlap["legal-documents"] = "https://pub-rmd.r2.dev/legal"
    got = parse_storage_url("https://pub-rmd.r2.dev/legal/brands/x.pdf", bases_overlap)
    assert got == ("legal-documents", "brands/x.pdf"), f"FAIL longest-base-precedence: got={got!r}"
    print(f"parse_storage_url: {len(PARSE_CASES) + 1} kasus LULUS.")


# =====================================================================
# Bagian 2: object_store dispatch (supabase / dual / r2)
# =====================================================================

BUCKETS = {
    "raw-material-docs": "https://pub-rmd.r2.dev",
    "legal-documents": "https://pub-legal.r2.dev",
}


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


def _install(backend, s3, suffix="", bases=None):
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


_PATCHED_ATTRS = (
    "_settings",
    "_r2_client",
    "_supabase_upload",
    "_supabase_public_url",
    "_supabase_signed_url",
    "_supabase_signed_urls",
    "_supabase_remove",
)


@contextmanager
def _isolated_object_store():
    saved = {attr: getattr(object_store, attr) for attr in _PATCHED_ATTRS}
    logger = logging.getLogger("app.object_store")
    orig_level = logger.level
    cap = Capture()
    logger.addHandler(cap)
    logger.setLevel(logging.WARNING)
    try:
        yield cap
    finally:
        for attr, orig_val in saved.items():
            setattr(object_store, attr, orig_val)
        logger.removeHandler(cap)
        logger.setLevel(orig_level)


def test_object_store_r2_dispatch():
    """Converted from test_object_store_r2.py::main with try/finally restore."""
    failures = []

    def check(label, cond, detail=""):
        if not cond:
            failures.append((label, detail))
            print(f"FAIL {label}: {detail}")

    with _isolated_object_store() as cap:
        # ---------------- mode r2 ----------------
        s3 = FakeS3()
        _install("r2", s3)
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

        # Gagal-cepat sebelum tulis bila base R2 kurang (E-06): upload_pdf harus
        # raise RuntimeError tanpa memanggil put_object.
        s3_missing = FakeS3()
        _install("r2", s3_missing, bases={})
        try:
            object_store.upload_pdf("raw-material-docs", "coa/missing-base.pdf", b"%PDF-")
            check("fail-fast before upload when base missing", False, "tidak raise")
        except RuntimeError:
            check("fail-fast before upload when base missing", True)
            check("fail-fast does not call put_object", len(s3_missing.puts) == 0, s3_missing.puts)

        # ---------------- mode dual ----------------
        s3 = FakeS3()
        _install("dual", s3)
        out = object_store.upload_pdf("raw-material-docs", "coa/a.pdf", b"%PDF-")
        check("dual upload supabase authoritative", out == "SB_UPLOAD", out)
        check("dual upload also writes r2", len(s3.puts) == 1, s3.puts)

        cap.records.clear()
        object_store.upload_pdf("raw-material-docs", "coa/a2.pdf", b"%PDF-")
        check("dual upload r2 sukses -> storage_r2_ok", any("storage_r2_ok" in m for m in cap.records), cap.records)

        cap.records.clear()
        s3.fail_put = True
        try:
            object_store.upload_pdf("raw-material-docs", "coa/b.pdf", b"%PDF-", upsert=False)
            check("dual upload r2 failure raises", False, "tidak raise")
        except RuntimeError:
            check("dual upload r2 failure raises", True)
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

        # A cross-backend cleanup must report both providers, not only the active
        # primary provider. The Supabase failure also gets a repair record.
        cap.records.clear()
        object_store._supabase_remove = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("supabase delete boom"))
        s3.fail_delete = False
        res = object_store.remove_from_all_backends("raw-material-docs", "coa/leftover.pdf")
        check("all-backends cleanup has both results", set(res) == {"supabase", "r2"}, res)
        check("all-backends cleanup detects supabase failure",
              object_store.failed_backends(res) == ["supabase"], res)
        check("all-backends cleanup is not successful",
              not object_store.all_results_ok(res), res)
        check("supabase cleanup failure -> storage_repair",
              any("backend=supabase" in m for m in cap.records), cap.records)

        object_store._supabase_remove = lambda *a, **k: None
        s3.fail_delete = True
        res = object_store.remove_from_all_backends("raw-material-docs", "coa/leftover.pdf")
        check("all-backends cleanup detects r2 failure",
              object_store.failed_backends(res) == ["r2"], res)

        # ---------------- mode supabase (tak berubah) ----------------
        s3 = FakeS3()
        _install("supabase", s3)
        out = object_store.upload_pdf("raw-material-docs", "coa/a.pdf", b"%PDF-")
        check("supabase upload no r2", out == "SB_UPLOAD" and not s3.puts, (out, s3.puts))
        check("supabase public_url", object_store.public_url("raw-material-docs", "a.pdf") == "SB:/raw-material-docs/a.pdf")
        res = object_store.remove("raw-material-docs", "coa/a.pdf")
        check("supabase remove only supabase", set(res) == {"supabase"}, res)

        # ---------------- suffix environment (staging "-stg") ----------------
        s3 = FakeS3()
        stg_bases = {"raw-material-docs-stg": "https://pub-rmd-stg.r2.dev"}
        _install("r2", s3, suffix="-stg", bases=stg_bases)
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
        raise AssertionError(f"{len(failures)} object_store check gagal: {failures}")
    print("object_store dispatch r2/dual: semua kasus LULUS.")


# =====================================================================
# Bagian 3: Helper murni migration/verify_r2_readiness.py (E-12)
# =====================================================================


class _FakeStorageRaise:
    def list(self, *_a, **_kw):
        raise RuntimeError("Bucket not found")


class _FakeStorageOk:
    def list(self, *_a, **_kw):
        return []


class _FakeFrom:
    def __init__(self, ok):
        self._ok = ok

    def from_(self, bucket):
        return _FakeStorageOk() if self._ok else _FakeStorageRaise()


def test_bucket_exists_true():
    client = type("C", (), {"storage": property(lambda self: _FakeFrom(True))})()
    assert supabase_bucket_exists(client, "legal-documents") is True
    print("[PASS] bucket Supabase ada -> True")


def test_bucket_exists_false():
    client = type("C", (), {"storage": property(lambda self: _FakeFrom(False))})()
    assert supabase_bucket_exists(client, "legal-documents") is False, \
        "bucket yang tidak ada harus False (FAIL eksplisit, bukan 'inventory failed' samar)"
    print("[PASS] bucket Supabase tidak ada -> False")


def test_physical_suffix():
    assert physical("legal-documents", "-stg") == "legal-documents-stg"
    assert physical("legal-documents", "") == "legal-documents"
    print("[PASS] physical() menempel suffix dengan benar")


def test_parse_bases_tolerant():
    assert parse_bases("not-json") == {}
    assert parse_bases('{"legal-documents": "https://pub-x.r2.dev"}') == {
        "legal-documents": "https://pub-x.r2.dev"
    }
    print("[PASS] parse_bases toleran terhadap JSON rusak")


ALL_TESTS = [
    test_parse_storage_url_cases,
    test_object_store_r2_dispatch,
    test_bucket_exists_true,
    test_bucket_exists_false,
    test_physical_suffix,
    test_parse_bases_tolerant,
]


def main(reverse: bool = False) -> int:
    tests = list(reversed(ALL_TESTS)) if reverse else list(ALL_TESTS)
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if failed:
        print(f"\n{failed} dari {len(tests)} test storage_r2 GAGAL.")
        return 1
    print(f"\nSemua {len(tests)} test storage_r2 LULUS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
