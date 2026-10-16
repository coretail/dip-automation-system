"""Unit test murni object_store.parse_storage_url (tanpa koneksi/dependency app).

Menguji pengenalan prefix Supabase Storage DAN base publik R2 (per bucket),
termasuk path ber-spasi (mentah) dan ter-encode (%20), query string, serta
format tak dikenal. Jalankan: `py tests/test_parse_storage_url.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.object_store import parse_storage_url

SUPABASE = "https://dytuprmoorvrugutozwv.supabase.co"
BASES = {
    "raw-material-docs": "https://pub-rmd.r2.dev",
    "legal-documents": "https://pub-legal.r2.dev",
    "product-attachments": "https://pub-att.r2.dev",
}


def main():
    cases = [
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
         ("raw-material-docs", "coa/file%20name.pdf")),
        # bucket kosong path -> None
        (f"{SUPABASE}/storage/v1/object/public/raw-material-docs",
         (None, None)),
        # --- R2 (base per bucket) ---
        ("https://pub-rmd.r2.dev/coa/coa_B1.pdf", ("raw-material-docs", "coa/coa_B1.pdf")),
        ("https://pub-legal.r2.dev/brands/hak lisensi.pdf", ("legal-documents", "brands/hak lisensi.pdf")),
        ("https://pub-legal.r2.dev/brands/hak%20lisensi.pdf", ("legal-documents", "brands/hak%20lisensi.pdf")),
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

    failures = 0
    for url, expected in cases:
        got = parse_storage_url(url, BASES)
        label = (url or "")[:70]
        if got != expected:
            failures += 1
            print(f"FAIL {label!r}: got={got!r} expected={expected!r}")

    # Base terpanjang menang saat ada prefix mirip (bukan crash/salah bucket).
    bases_overlap = dict(BASES)
    bases_overlap["legal-documents"] = "https://pub-rmd.r2.dev/legal"
    got = parse_storage_url("https://pub-rmd.r2.dev/legal/brands/x.pdf", bases_overlap)
    if got != ("legal-documents", "brands/x.pdf"):
        failures += 1
        print(f"FAIL longest-base-precedence: got={got!r}")

    if failures:
        print(f"\n{len(cases)} kasus, {failures} GAGAL.")
        return 1
    print(f"parse_storage_url: {len(cases) + 1} kasus LULUS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
