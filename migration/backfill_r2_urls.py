"""Backfill URL kolom storage ke base target (idempoten) — Fase 5 migrasi.

Mengubah URL absolut di 31 kolom DB dari base aktif ke base target:
  - ``--target r2``        : base publik R2 dari ``R2_PUBLIC_BASES`` (per bucket,
                             termasuk suffix env seperti ``-stg``).
  - ``--target supabase``  : base ``<SUPABASE_URL>/storage/v1/object/public/<bucket>``.

Idempoten: URL dibangun ulang dari ``(bucket, path)`` hasil ekstraksi (dua format
dikenali), bukan string-replace. Menjalankan ulang = no-op bila sudah di base target.

DEFAULT = DRY-RUN (hanya laporan before/after, tidak menulis DB). Penulisan hanya
dengan ``--apply``. Sebelum ``--apply``, tiap ``(bucket,path)`` hasil ekstraksi
WAJIB ada di storage target (HEAD/list); bila ada yang hilang -> BERHENTI tanpa mutasi.

Contoh:
    py migration/backfill_r2_urls.py --env prod --target r2
    py migration/backfill_r2_urls.py --env prod --target r2 --apply
    py migration/backfill_r2_urls.py --env prod --target supabase --apply   # rollback
"""
from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import quote, unquote

from dotenv import dotenv_values

# Kolom URL publik (sinkron dengan migration/audit_storage.py).
# `product_attachments.file_path` SENGAJA tidak disertakan: isinya path mentah
# (bukan URL) dan tetap dipakai apa adanya di backend mana pun (presigned).
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
SUPABASE_MARKER = "/storage/v1/object/public/"
PAGE = 1000


def load_env(path):
    v = dotenv_values(path)
    return {k: (val or "").strip().strip('"') for k, val in v.items()}


def build_extractor(bases, suffix):
    """Kembalikan fungsi extract(url) -> (bucket_logis, path_verbatim) | (None, None)."""
    r2 = sorted(bases.items(), key=lambda kv: len(kv[1]), reverse=True)

    def extract(url):
        u = str(url)
        if SUPABASE_MARKER in u:
            rest = u.split(SUPABASE_MARKER, 1)[1].split("?", 1)[0]
            if "/" not in rest:
                return None, None
            b, p = rest.split("/", 1)
            return b, p
        for phys, base in r2:
            if base and (u == base or u.startswith(base + "/")):
                if u == base:
                    continue
                logical = phys[: -len(suffix)] if suffix and phys.endswith(suffix) else phys
                return logical, u[len(base) + 1:].split("?", 1)[0]
        return None, None

    return extract


def fetch_rows(client, table, column):
    """-> list {id, value} atau None bila tabel/kolom absen di env ini."""
    out, start = [], 0
    while True:
        try:
            rows = (client.table(table).select(f"id,{column}").range(start, start + PAGE - 1).execute().data) or []
        except Exception as exc:
            text = str(exc)
            if "PGRST205" in text or "PGRST204" in text or "Could not find" in text or "does not exist" in text:
                return None
            raise
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        start += PAGE


def make_target(cfg, target, bases, suffix, supabase_url):
    """-> (build_url(bucket, path) -> str|None, exists(bucket, key) -> bool)."""
    if target == "r2":
        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{cfg.get('R2_ACCOUNT_ID', '')}.r2.cloudflarestorage.com",
            aws_access_key_id=cfg.get("R2_ACCESS_KEY_ID", ""),
            aws_secret_access_key=cfg.get("R2_SECRET_ACCESS_KEY", ""),
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

        def physical(bucket):
            return f"{bucket}{suffix}" if suffix else bucket

        def build_url(bucket, path):
            base = bases.get(physical(bucket)) or bases.get(bucket)
            return None if not base else f"{base.rstrip('/')}/{path}"

        def exists(bucket, key):
            try:
                s3.head_object(Bucket=physical(bucket), Key=key)
                return True
            except Exception:
                return False

        return build_url, exists

    def build_url(bucket, path):
        return f"{supabase_url.rstrip('/')}{SUPABASE_MARKER}{bucket}/{path}"

    from supabase import create_client

    client = create_client(supabase_url, cfg.get("SUPABASE_SERVICE_ROLE_KEY", ""))

    def exists(bucket, key):
        try:
            return bool(client.storage.from_(bucket).exists(key))
        except Exception:
            return False

    return build_url, exists


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", choices=["prod", "staging"], default="prod")
    ap.add_argument("--target", choices=["r2", "supabase"], required=True)
    ap.add_argument("--apply", action="store_true", help="tulis ke DB (default dry-run)")
    ap.add_argument("--precheck", action="store_true", help="jalankan pre-check walau dry-run")
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--bucket", default=None, help="batasi ke satu bucket (opsional)")
    args = ap.parse_args()

    envfile = ".env" if args.env == "prod" else ".env.staging"
    cfg = load_env(envfile)
    supabase_url = cfg.get("SUPABASE_URL", "")
    if not supabase_url or not cfg.get("SUPABASE_SERVICE_ROLE_KEY"):
        print(f"[backfill] {envfile} tidak lengkap (SUPABASE_URL/SERVICE_ROLE_KEY).")
        return 2

    suffix = cfg.get("R2_BUCKET_SUFFIX", "")
    import json
    try:
        bases = {k: str(v).rstrip("/") for k, v in json.loads(cfg.get("R2_PUBLIC_BASES") or "{}").items() if v}
    except Exception:
        bases = {}
    if args.target == "r2" and not bases:
        print("[backfill] R2_PUBLIC_BASES kosong/tidak valid; target r2 tak bisa dibangun.")
        return 2

    extract = build_extractor(bases, suffix)
    build_url, exists = make_target(cfg, args.target, bases, suffix, supabase_url)

    from supabase import create_client

    db = create_client(supabase_url, cfg["SUPABASE_SERVICE_ROLE_KEY"])

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[backfill] env={args.env} ({envfile})  target={args.target}  mode={mode}  suffix='{suffix}'")

    changes = []          # (table, column, id, old, new)
    unparseable = []      # (table, column, id, url)
    no_base = []          # (bucket, table, column, id)
    total = 0
    for table, column in URL_COLUMNS:
        rows = fetch_rows(db, table, column)
        if rows is None:
            continue
        for row in rows:
            old = row.get(column)
            if not old:
                continue
            total += 1
            bucket, path = extract(old)
            if not bucket or not path:
                unparseable.append((table, column, row.get("id"), str(old)))
                continue
            if args.bucket and bucket != args.bucket:
                continue
            new = build_url(bucket, path)
            if new is None:
                no_base.append((bucket, table, column, row.get("id")))
                continue
            if new != old:
                changes.append((table, column, row.get("id"), old, new))

    print(f"[backfill] referensi terisi: {total}  | akan berubah: {len(changes)}"
          f"  | tidak dikenali: {len(unparseable)}  | bucket tanpa base: {len(no_base)}")
    for t, c, i, u in unparseable[: args.sample]:
        print(f"  SKIP (format?) {t}.{c} id={i}: {u[:80]}")
    for b, t, c, i in no_base[: args.sample]:
        print(f"  SKIP (tanpa base) bucket={b} {t}.{c} id={i}")
    for t, c, i, old, new in changes[: args.sample]:
        print(f"  {t}.{c} id={i}\n      - {old}\n      + {new}")

    if not changes:
        print("[backfill] tidak ada perubahan (idempoten: sudah di base target).")
        return 0

    if not (args.apply or args.precheck):
        print("[backfill] DRY-RUN selesai (tidak menulis). Jalankan dengan --apply untuk menerapkan.")
        return 0

    # --- Pre-check: setiap (bucket, path) harus ADA di storage target ---
    distinct = {}
    for t, c, i, old, new in changes:
        bucket, path = extract(old)
        if bucket and path:
            distinct.setdefault((bucket, unquote(path)), []).append(f"{t}.{c}")
    missing = []
    for (bucket, key) in sorted(distinct):
        if not exists(bucket, key):
            missing.append((bucket, key))
    print(f"[backfill] pre-check: {len(distinct)} objek unik di target, MISSING={len(missing)}")
    for b, k in missing[: args.sample]:
        print(f"  MISSING {b}/{k}")
    if missing:
        print("[backfill] ADA OBJEK HILANG di target -> BERHENTI tanpa mutasi.")
        return 3

    if not args.apply:
        print("[backfill] pre-check lolos (dry-run; tidak menulis).")
        return 0

    # --- Apply ---
    updated = 0
    for t, c, i, old, new in changes:
        db.table(t).update({c: new}).eq("id", i).execute()
        updated += 1
    print(f"[backfill] APPLIED: {updated} baris diperbarui ke base target '{args.target}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
