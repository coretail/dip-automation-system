"""Audit storage: bandingkan referensi URL di DB vs objek yang benar-benar ada.

REPORT-ONLY: tidak pernah menulis/menghapus apa pun. Mengungkap:
  - MISSING : URL di kolom DB menunjuk objek yang tidak ada di storage (link rusak).
  - ORPHAN  : objek di storage yang tidak direferensikan kolom DB mana pun.

Matching decode-aware: `%20` di URL dibandingkan terhadap nama objek ber-spasi.

Jalankan (dari root repo):
    py migration/audit_storage.py --env prod
    py migration/audit_storage.py --env staging
Opsi: --bucket <name> (batasi), --sample <n> (jumlah contoh, default 20).
"""
from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import unquote

from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.object_store import parse_storage_url  # noqa: E402

# (tabel, kolom) berisi URL publik Supabase/R2. product_attachments.file_path
# disimpan terpisah karena berisi path mentah (bukan URL) di bucket privat.
URL_COLUMNS = [
    ("brand_legal_documents", "hak_lisensi_merk_file_url"),
    ("brands", "hak_merk_file_url"),
    ("brands", "lisensi_merk_file_url"),
    ("company_sop_documents", "cv_safety_assessor_url"),
    ("company_sop_documents", "protap_no_batch_url"),
    ("company_sop_documents", "protap_pemeriksaan_fg_url"),
    ("cpkb_raw_material", "file_url"),
    ("nib_documents", "file_url"),
    ("product_batches", "coa_file_url"),
    ("products", "cara_pembuatan_file_url"),
    ("products", "data_klaim_file_url"),
    ("products", "desain_primer_file_url"),
    ("products", "desain_sekunder_file_url"),
    ("products", "hasil_stabilitas_file_url"),
    ("products", "laporan_keamanan_file_url"),
    ("products", "laporan_uji_sig_file_url"),
    ("products", "monitoring_efek_samping_file_url"),
    ("products", "no_notifikasi_file_url"),
    ("products", "protokol_stabilitas_file_url"),
    ("products", "sistem_penomoran_batch_file_url"),
    ("products", "spek_pengemas_file_url"),
    ("products", "spek_produk_jadi_file_url"),
    ("profiles", "signature_file_url"),
    ("raw_material_batches", "coa_file_url"),
    ("raw_material_batches", "halal_batch_file_url"),
    ("raw_material_batches", "qc_report_file_url"),
    ("raw_material_company_docs", "msds_file_url"),
    ("raw_material_company_docs", "spec_sheet_file_url"),
    ("raw_materials", "msds_file_url"),
    ("sertifikat_cpkb_documents", "file_url"),
    ("surat_tidak_pidana_documents", "file_url"),
]
PATH_COLUMNS = [("product_attachments", "file_path", "product-attachments")]
PAGE = 1000


def fetch_column(client, table, column):
    """-> list nilai kolom, atau None bila tabel/kolom tidak ada di env ini."""
    out, start = [], 0
    while True:
        try:
            rows = (client.table(table).select(column).range(start, start + PAGE - 1).execute().data) or []
        except Exception as exc:
            text = str(exc)
            if "PGRST205" in text or "PGRST204" in text or "Could not find" in text or "does not exist" in text:
                return None
            raise
        out.extend(r.get(column) for r in rows)
        if len(rows) < PAGE:
            return out
        start += PAGE


def list_bucket(client, bucket, prefix=""):
    storage = client.storage.from_(bucket)
    names, offset = [], 0
    while True:
        items = storage.list(prefix, {"limit": PAGE, "offset": offset}) or []
        for it in items:
            name = it.get("name")
            full = f"{prefix}/{name}" if prefix else name
            if it.get("id") is None and not it.get("metadata"):
                names.extend(list_bucket(client, bucket, full))
            else:
                names.append(full)
        if len(items) < PAGE:
            return names
        offset += PAGE


def norm(path):
    return unquote(str(path)).replace("\\", "/").lstrip("/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", choices=["prod", "staging"], default="prod")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--sample", type=int, default=20)
    args = ap.parse_args()

    envfile = ".env" if args.env == "prod" else ".env.staging"
    if args.env == "staging":
        os.environ.setdefault("DIP_APP_ENV", "staging")
    values = dotenv_values(envfile)
    url = (values.get("SUPABASE_URL") or "").strip().strip('"')
    key = (values.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip().strip('"')
    if not url or not key:
        print(f"[audit] {envfile} tidak punya SUPABASE_URL/SERVICE_ROLE_KEY.")
        return 2

    from supabase import create_client

    client = create_client(url, key)
    print(f"[audit] env={args.env} ({envfile})  project={url}")

    # 1) Kumpulkan referensi (bucket, path) yang dinormalkan + asalnya.
    refs: dict[str, dict[str, list[str]]] = {}
    broken_format = []
    skipped = []
    total_refs = 0
    for table, column in URL_COLUMNS:
        values = fetch_column(client, table, column)
        if values is None:
            skipped.append(f"{table}.{column}")
            continue
        for raw in values:
            if not raw:
                continue
            total_refs += 1
            bucket, path = parse_storage_url(str(raw))
            if not bucket or not path:
                broken_format.append((table, column, str(raw)[:90]))
                continue
            refs.setdefault(bucket, {}).setdefault(norm(path), []).append(f"{table}.{column}")
    for table, column, bucket in PATH_COLUMNS:
        values = fetch_column(client, table, column)
        if values is None:
            skipped.append(f"{table}.{column}")
            continue
        for raw in values:
            if not raw:
                continue
            total_refs += 1
            refs.setdefault(bucket, {}).setdefault(norm(raw), []).append(f"{table}.{column}")

    # 2) Kumpulkan objek per bucket.
    buckets = sorted(refs) if not args.bucket else [args.bucket]
    objects = {b: {norm(n) for n in list_bucket(client, b)} for b in buckets}

    print(f"\n[audit] total referensi terisi: {total_refs}  | anomali format: {len(broken_format)}"
          f"  | kolom dilewati (absen di env): {len(skipped)}")
    for s in skipped[: args.sample]:
        print(f"  SKIP (kolom/tabel absen) {s}")
    for t, c, u in broken_format[: args.sample]:
        print(f"  FORMAT? {t}.{c}: {u}")

    grand_missing = grand_orphan = 0
    for b in buckets:
        rset = refs.get(b, {})
        oset = objects.get(b, set())
        missing = sorted(p for p in rset if p not in oset)
        orphan = sorted(p for p in oset if p not in rset)
        grand_missing += len(missing)
        grand_orphan += len(orphan)
        print(f"\n== {b} ==")
        print(f"  referensi unik={len(rset)}  objek={len(oset)}  MISSING={len(missing)}  ORPHAN={len(orphan)}")
        for p in missing[: args.sample]:
            print(f"    MISSING {p}  <- {', '.join(sorted(set(rset[p])))[:80]}")
        for p in orphan[: args.sample]:
            print(f"    ORPHAN  {p}")

    print(f"\n[audit] TOTAL MISSING={grand_missing}  ORPHAN={grand_orphan}  (report-only, tanpa mutasi)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
