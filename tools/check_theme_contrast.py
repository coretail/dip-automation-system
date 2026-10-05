"""Cek kontras WCAG 2.1 untuk setiap tema dari token di app/static/theme.css.

Pakai:
    python tools/check_theme_contrast.py

Keluar dengan kode 1 bila ada pasangan teks < 4.5:1 atau non-teks < 3:1.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "app" / "static" / "theme.css"

# (foreground, background, ambang, keterangan)
PAIRS = [
    ("--t-text", "--t-page", 4.5, "teks utama di atas latar"),
    ("--t-text", "--t-surface", 4.5, "teks utama di atas kartu"),
    ("--t-text-2", "--t-surface", 4.5, "sub-teks"),
    ("--t-muted", "--t-page", 4.5, "teks muted di atas latar"),
    ("--t-muted", "--t-surface", 4.5, "teks muted di atas kartu"),
    ("--t-placeholder", "--t-surface", 4.5, "placeholder"),
    ("--t-link", "--t-page", 4.5, "link di atas latar"),
    ("--t-link", "--t-surface", 4.5, "link di atas kartu"),
    ("--t-text", "--t-brand-soft-1", 4.5, "teks di atas badge lembut"),
    ("--t-text", "--t-brand-soft-4", 4.5, "teks di atas badge sedang"),
    ("--t-text", "--t-surface-2", 4.5, "teks di atas permukaan 2"),
    ("--t-white", "--t-brand-strong", 4.5, "putih di atas CTA"),
    ("--t-white", "--t-nav-bg", 4.5, "putih di atas navbar"),
    ("--t-border-2", "--t-surface", 3.0, "border input (WCAG 1.4.11)"),
    ("--t-brand", "--t-surface", 3.0, "aksen non-teks"),
    ("--t-divider", "--t-surface", 1.0, "divider dekoratif"),
]

# Pasangan tambahan khusus Rose (lihat .kilo/plans/rose-theme.md §4.1).
ROSE_PAIRS = [
    ("--t-text-2", "--t-page", 4.5, "sub-teks di atas latar rose"),
    ("--t-link", "--t-page", 4.5, "link di atas latar rose"),
    ("--t-text", "--t-brand-soft-1", 4.5, "teks di atas badge rose"),
    ("--t-text", "--t-brand-soft-4", 4.5, " teks di atas badge rose sedang"),
    ("--t-text", "--t-surface-2", 4.5, "teks di atas header tabel rose"),
    ("--t-brand", "--t-surface", 3.0, "garis bawah tab aktif di atas kartu"),
    ("--t-brand", "--t-page", 3.0, "garis bawah tab aktif di atas latar"),
    ("--t-rose-text-800", "--t-surface", 4.5, "pesan error rose-800 di atas kartu"),
    ("--t-rose-text-800", "--t-page", 4.5, "pesan error rose-800 di atas latar"),
    ("--t-rose-text-600", "--t-surface", 4.5, "ikon pesan error rose-600"),
    ("--t-rose-bg-50", "--t-surface", 1.0, "latar kotak error rose-50 (dekoratif)"),
]

# pasangan yang HARUS gagal â€” dokumentasi aturan tema Terra
FORBIDDEN = [
    ("--t-white", "--t-brand", 4.5, "putih di atas aksen #DA6556"),
    ("--t-white", "--t-brand-soft-4", 4.5, "putih di atas warna terang"),
    ("--t-text", "--t-brand-strong", 4.5, "teks gelap di atas brick solid"),
]


def parse_blocks(css: str) -> dict[str, dict[str, str]]:
    """Ambil blok token per tema.

    Hanya blok yang benar-benar mendeklarasikan token (`--t-page:`) yang
    diambil. File ini juga punya rule non-token seperti
    `[data-theme="dark"] { background-color: var(--t-page) }`; kalau ikut
    dibaca, nilainya akan menimpa token dengan `var(--…)` dan hasil hitungan
    kontras jadi tidak bermakna.
    """
    out: dict[str, dict[str, str]] = {}
    pattern = re.compile(r"(:root,\s*\[data-theme=\"light\"\]|\[data-theme=\"(\w+)\"\])\s*\{(.*?)\n\}", re.S)
    for m in pattern.finditer(css):
        theme = m.group(2) or "light"
        body = m.group(3)
        if "--t-page:" not in body:
            continue  # rule non-token (mis. aturan <html> di lapisan mapping)
        vars_found = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))
        if theme in out:
            out[theme].update(vars_found)
        else:
            out[theme] = vars_found
    return out


def _oklab_to_rgb(L: float, a: float, b: float) -> tuple[int, int, int]:
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return r, g, bl


def _gamma(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 12.92 * x if x <= 0.0031308 else 1.055 * (x ** (1 / 2.4)) - 0.055


def to_rgb(value: str) -> tuple[int, int, int] | None:
    """Konversi ke sRGB 8-bit. Mendukung #hex, rgb()/rgba(), oklch(), oklab().

    Nilai oklch/oklab Tailwind v4 ikut dihitung supaya light bisa diverifikasi
    juga; hasil dijepit ke [0,255] seperti yang dilakukan browser.
    """
    v = value.strip()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        return None
    if v.startswith("rgb"):
        nums = re.findall(r"[\d.]+", v)
        return tuple(int(float(x)) for x in nums[:3])  # type: ignore[return-value]

    m = re.match(r"oklch\(\s*([\d.]+%?)\s+([\d.]+)\s+([\d.]+)", v)
    if m:
        L = float(m.group(1).rstrip("%")) / 100 if m.group(1).endswith("%") else float(m.group(1))
        C, H = float(m.group(2)), float(m.group(3))
        h = math.radians(H)
        return tuple(round(_gamma(c) * 255) for c in _oklab_to_rgb(L, C * math.cos(h), C * math.sin(h)))  # type: ignore[return-value]

    m = re.match(r"oklab\(\s*([\d.]+%?)\s+([-\d.]+)\s+([-\d.]+)", v)
    if m:
        L = float(m.group(1).rstrip("%")) / 100 if m.group(1).endswith("%") else float(m.group(1))
        return tuple(round(_gamma(c) * 255) for c in _oklab_to_rgb(L, float(m.group(2)), float(m.group(3))))  # type: ignore[return-value]
    return None


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# Nilai yang sudah gagal SEBELUM refactor (nilai stock Tailwind untuk light,
# nilai darkmode.css lama untuk dark) dan sengaja dibiarkan supaya light & dark
# tetap pixel-identical. Dilaporkan sebagai PERINGATAN, bukan kegagalan baru.
# Menghapus salah satu berarti mengubah tampilan light/dark â€” perlu keputusan
# visual tersendiri.
ACCEPTED = {
    ("dark", "--t-white", "--t-brand-strong"):
        "solid indigo-600 dipertahankan dari darkmode.css lama (putih 4.47:1, kurang 0.03)",
    ("dark", "--t-border-2", "--t-surface"):
        "border input gelap #475569 di atas #1e293b = 1.93:1, sama seperti sebelumnya",
    ("light", "--t-placeholder", "--t-surface"):
        "placeholder stock Tailwind gray-400 = 2.60:1, sama seperti sebelum refactor",
    ("light", "--t-border-2", "--t-surface"):
        "border input stock Tailwind gray-300 di atas kartu putih = 1.47:1, sama seperti sebelum refactor",
}


def main() -> int:
    blocks = parse_blocks(CSS.read_text(encoding="utf-8"))
    themes = [t for t in ("light", "terra", "rose", "dark") if t in blocks]
    if not themes:
        print("GAGAL: tidak ada blok token yang terbaca di", CSS)
        return 1

    print(f"WCAG contrast check - {CSS}")
    print("Token terbaca: " + ", ".join(f"{t}={len(blocks[t])}" for t in themes))
    print()

    failures: list[str] = []
    accepted: list[str] = []
    skipped = 0
    for theme in themes:
        tok = dict(blocks[theme])
        tok["--t-white"] = "#ffffff"
        print(f"--- {theme} ---")
        pairs = list(PAIRS) + (list(ROSE_PAIRS) if theme == "rose" else [])
        for fg, bg, min_ratio, note in pairs:
            if fg not in tok or bg not in tok:
                skipped += 1
                continue
            c1, c2 = to_rgb(tok[fg]), to_rgb(tok[bg])
            if c1 is None or c2 is None:
                skipped += 1
                continue
            ratio = contrast(c1, c2)
            ok = ratio >= min_ratio
            key = (theme, fg, bg)
            tag = "OK  " if ok else "FAIL"
            if not ok and key in ACCEPTED:
                tag = "WARN"
                accepted.append(f"{theme}: {fg} on {bg} = {ratio:.2f}:1 - {ACCEPTED[key]}")
            print(f"  {tag} {ratio:6.2f}:1  (min {min_ratio})  {fg} on {bg}  - {note}")
            if not ok and key not in ACCEPTED:
                failures.append(f"{theme}: {fg} on {bg} = {ratio:.2f}:1 (min {min_ratio}) - {note}")

    print()
    print("--- pasangan yang DILARANG (hanya relevan untuk terra) ---")
    terra = blocks.get("terra")
    if terra:
        tok = dict(terra)
        tok["--t-white"] = "#ffffff"
        for fg, bg, min_ratio, note in FORBIDDEN:
            if fg not in tok or bg not in tok:
                continue
            c1, c2 = to_rgb(tok[fg]), to_rgb(tok[bg])
            if c1 is None or c2 is None:
                continue
            ratio = contrast(c1, c2)
            ok = ratio >= min_ratio
            print(f"  {'OK  ' if ok else 'DILARANG (dokumentasi)'} {ratio:6.2f}:1  {note}")

    print()
    if skipped:
        print(f"Catatan: {skipped} pasangan dilewati karena nilainya tidak bisa diparse.")
    if accepted:
        print()
        print("PERINGATAN (diwarisi dari darkmode.css lama, bukan regresi baru):")
        for a in accepted:
            print("  -", a)
    print(f"TOTAL GAGAL BARU: {len(failures)}")
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())