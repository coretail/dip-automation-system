"""Automated E2E showcase screenshot script for DIP Automation System (STAGING ONLY).

Targets http://127.0.0.1:8017 (or localhost via --base-url), validates .env.staging
via app.staging_preflight, authenticates with STAGING_ADMIN_EMAIL / STAGING_ADMIN_PASSWORD,
captures 18 high-DPI (1440x900 @2x) screenshots to screenshots/showcase/, verifies HTTP 200,
zero console/page/5xx errors, non-blank PNGs, and outputs a sanitized read-only data audit.

NEVER touches production .env, NEVER prints secrets/credentials, NEVER performs destructive mutations.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.staging"
OUT_DIR = ROOT / "screenshots" / "showcase"

ERROR_MARKERS = (
    "Internal Server Error",
    "Traceback (most recent call last)",
    "NameError",
)

UUID_RE = re.compile(r"^/products/([0-9a-fA-F-]{8,})/")


@dataclass
class ShotResult:
    filename: str
    route: str
    status: int
    console_errors: int
    page_errors: int
    size_bytes: int
    dimensions: tuple[int, int]
    non_blank: bool
    note: str = ""

    @property
    def ok(self) -> bool:
        return (
            self.status == 200
            and self.console_errors == 0
            and self.page_errors == 0
            and self.non_blank
        )


def load_and_guard(base_url: str) -> dict[str, str]:
    """Fail-closed staging guard: localhost only + .env.staging preflight."""
    host = (urlparse(base_url).hostname or "").lower()
    if host not in ("127.0.0.1", "localhost"):
        sys.exit(f"[ABORT] base URL '{base_url}' bukan localhost (staging lokal saja).")
    if not ENV_FILE.exists():
        sys.exit(f"[ABORT] {ENV_FILE.name} tidak ditemukan di root repo.")
    sys.path.insert(0, str(ROOT))
    from app.staging_preflight import parse_dotenv_file, validate_staging_file

    cfg = parse_dotenv_file(str(ENV_FILE))
    try:
        validate_staging_file(cfg, caller="capture-showcase")
    except RuntimeError as exc:
        sys.exit(f"[ABORT] guard staging gagal: {exc}")
    return cfg


def check_health(base_url: str) -> None:
    """Pastikan server staging merespons sehat pada GET /health."""
    url = base_url.rstrip("/") + "/health"
    try:
        resp = httpx.get(url, timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"[ABORT] Gagal menghubungi {url}: {type(exc).__name__}: {exc}")
    if resp.status_code != 200:
        sys.exit(f"[ABORT] GET /health mengembalikan HTTP {resp.status_code} (harus 200).")


def apply_theme_and_close_menus(page, theme: str) -> None:
    """Set tema pada localStorage + data-theme dan pastikan semua dropdown/tombol scroll tertutup."""
    page.evaluate(
        """(theme) => {
            try { localStorage.setItem('heka-theme', theme); } catch (e) {}
            try { localStorage.removeItem('sidebarCollapsed'); } catch (e) {}
            const root = document.documentElement;
            if (!root.classList.contains('force-light')) {
                root.setAttribute('data-theme', theme);
            }
            root.classList.remove('sidebar-collapsed');

            const themeMenu = document.getElementById('themeMenu');
            if (themeMenu) themeMenu.classList.remove('is-open');
            const themeToggle = document.getElementById('theme-toggle');
            if (themeToggle) themeToggle.setAttribute('aria-expanded', 'false');

            const edDrop = document.getElementById('ed-notification-dropdown');
            if (edDrop) edDrop.classList.add('hidden');
            const edBtn = document.getElementById('ed-notification-btn');
            if (edBtn) edBtn.setAttribute('aria-expanded', 'false');

            const userDrop = document.getElementById('user-menu-dropdown');
            if (userDrop) userDrop.classList.add('hidden');
            const userBtn = document.getElementById('user-menu-btn');
            if (userBtn) userBtn.setAttribute('aria-expanded', 'false');

            // Sync theme icon & aria-checked state if darkmode.js elements exist
            const opts = document.querySelectorAll('[data-theme-opt]');
            opts.forEach(btn => {
                const on = btn.getAttribute('data-theme-opt') === theme;
                btn.setAttribute('aria-checked', on ? 'true' : 'false');
            });

            window.scrollTo(0, 0);
            const jumpBtn = document.getElementById('jumpToTopBtn');
            if (jumpBtn) jumpBtn.classList.add('hidden');
        }""",
        theme,
    )


def wait_ready(page, wait_charts: bool = False, extra_ms: int = 650) -> None:
    """Tunggu load, networkidle, fonts, dan optional Chart.js selesai render."""
    page.wait_for_load_state("load", timeout=20000)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:  # noqa: BLE001
        print("[WARN] networkidle timeout (melanjutkan setelah load + delay)")

    try:
        page.evaluate("() => (document.fonts ? document.fonts.ready : Promise.resolve())")
    except Exception:  # noqa: BLE001
        pass

    if wait_charts:
        try:
            page.wait_for_function(
                """() => {
                    const dataEl = document.getElementById('poAnalyticsData');
                    if (!dataEl) return true;
                    if (!window.Chart) return false;
                    const canvases = Array.from(document.querySelectorAll('canvas'));
                    const visible = canvases.filter(c => {
                        const cs = getComputedStyle(c);
                        const ps = c.parentElement ? getComputedStyle(c.parentElement) : null;
                        return cs.display !== 'none' && (!ps || ps.display !== 'none');
                    });
                    if (visible.length === 0) return true;
                    const primaryIds = ['chartQuarter', 'chartCompany', 'chartQuarterCompany'];
                    for (const id of primaryIds) {
                        const el = document.getElementById(id);
                        if (el && visible.includes(el)) {
                            const ch = window.Chart.getChart(el);
                            if (!ch || el.width <= 0 || el.height <= 0) return false;
                        }
                    }
                    return true;
                }""",
                timeout=15000,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Menunggu Chart.js timeout: {type(exc).__name__}: {exc}")
        page.wait_for_timeout(800)
    else:
        page.wait_for_timeout(extra_ms)

    # Pastikan 2 animation frame selesai agar layout & paint stabil
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )


def verify_png_not_blank(path: Path, full_page: bool) -> tuple[bool, int, tuple[int, int], str]:
    """Verifikasi file PNG ada, cukup besar, dimensi sesuai, dan memiliki variasi piksel."""
    if not path.exists():
        return False, 0, (0, 0), "file tidak ditemukan"
    size = path.stat().st_size
    if size < 15_000:
        return False, size, (0, 0), f"ukuran terlalu kecil ({size} bytes)"
    try:
        with Image.open(path) as img:
            dims = img.size
            if not full_page and dims != (2880, 1800):
                return False, size, dims, f"dimensi tak terduga {dims} (diharapkan 2880x1800)"
            rgb = img.convert("RGB")
            stat = ImageStat.Stat(rgb)
            max_std = max(stat.stddev)
            thumb = rgb.resize((64, 64))
            distinct_colors = len(set(thumb.getdata()))
            if max_std <= 5.0 or distinct_colors <= 10:
                return (
                    False,
                    size,
                    dims,
                    f"terindikasi blank (stddev={max_std:.2f}, colors={distinct_colors})",
                )
            return True, size, dims, f"stddev={max_std:.1f}, colors={distinct_colors}"
    except Exception as exc:  # noqa: BLE001
        return False, size, (0, 0), f"gagal baca PNG: {exc}"


def pick_best_product_id(page) -> str:
    """Pilih 1 product_id valid dari tabel Dashboard (utamakan yang punya Bab II & lampiran)."""
    candidates = page.evaluate(
        """() => {
            const found = new Map();
            // Cek tab checklist DIP untuk mengetahui kelengkapan Bab II
            const dipRows = document.querySelectorAll('#tab-checklist-dip tbody tr.product-row');
            dipRows.forEach(tr => {
                const editLink = tr.querySelector("a[href^='/products/']");
                if (!editLink) return;
                const href = editLink.getAttribute('href') || '';
                const m = href.match(/^\\/products\\/([0-9a-fA-F-]{8,})\\//);
                if (!m) return;
                const pid = m[1];
                const bab2Link = tr.querySelector("a[href*='tab=bab2']");
                const hasBab2 = !!(bab2Link && (bab2Link.querySelector('.fa-circle-check') || bab2Link.innerHTML.includes('bg-emerald-100')));
                const titleEl = editLink.querySelector('div');
                const name = titleEl ? titleEl.textContent.trim() : '';
                found.set(pid, { id: pid, name, hasBab2, hasAttach: false });
            });

            // Cek tab master produk untuk attachment count & fallback
            const masterRows = document.querySelectorAll('#tab-master-produk tbody tr.product-row');
            masterRows.forEach(tr => {
                const links = tr.querySelectorAll("a[href^='/products/']");
                let pid = null;
                links.forEach(a => {
                    const m = (a.getAttribute('href') || '').match(/^\\/products\\/([0-9a-fA-F-]{8,})\\//);
                    if (m && !pid) pid = m[1];
                });
                if (!pid) return;
                const attLink = tr.querySelector("a[href$='/lampiran']");
                const hasAttach = !!(attLink && attLink.querySelector('span'));
                if (found.has(pid)) {
                    found.get(pid).hasAttach = hasAttach;
                } else {
                    const titleEl = tr.querySelector('td div');
                    found.set(pid, { id: pid, name: titleEl ? titleEl.textContent.trim() : '', hasBab2: false, hasAttach });
                }
            });

            // Fallback umum link produk apa saja di halaman
            if (found.size === 0) {
                document.querySelectorAll("a[href^='/products/']").forEach(a => {
                    const m = (a.getAttribute('href') || '').match(/^\\/products\\/([0-9a-fA-F-]{8,})\\//);
                    if (m && !found.has(m[1])) {
                        found.set(m[1], { id: m[1], name: '', hasBab2: false, hasAttach: false });
                    }
                });
            }

            return Array.from(found.values());
        }"""
    )
    if not candidates:
        sys.exit("[ABORT] Tidak ditemukan product_id valid di Dashboard staging.")
    candidates.sort(key=lambda c: (bool(c.get("hasBab2")), bool(c.get("hasAttach"))), reverse=True)
    chosen = candidates[0]
    print(
        f"[INFO] Product terpilih untuk detail: id={chosen['id']} "
        f"(hasBab2={chosen.get('hasBab2')}, hasAttach={chosen.get('hasAttach')})"
    )
    return chosen["id"]


def collect_sanitized_audit(page, route: str, audit: dict) -> None:
    """Kumpulkan observasi data staging secara read-only dan tersanitasi (tanpa kredensial)."""
    try:
        if route == "/":
            info = page.evaluate(
                """() => {
                    const rows = Array.from(document.querySelectorAll('#tab-master-produk tbody tr.product-row'));
                    const samples = rows.slice(0, 8).map(tr => {
                        const tds = tr.querySelectorAll('td');
                        const prod = tds[0] ? tds[0].innerText.trim().replace(/\\s+/g, ' ') : '';
                        const cust = tds[1] ? tds[1].innerText.trim().replace(/\\s+/g, ' ') : '';
                        const status = tds[3] ? tds[3].innerText.trim().replace(/\\s+/g, ' ') : '';
                        return { prod, cust, status };
                    });
                    return { count: rows.length, samples };
                }"""
            )
            audit["dashboard"] = info
        elif route == "/raw-materials":
            info = page.evaluate(
                """() => {
                    const rows = Array.from(document.querySelectorAll('table tbody tr'));
                    const samples = rows.slice(0, 6).map(tr => tr.innerText.trim().replace(/\\s+/g, ' ').slice(0, 140));
                    return { rowCount: rows.length, samples };
                }"""
            )
            audit["raw_materials"] = info
        elif route == "/purchase-orders":
            info = page.evaluate(
                """() => {
                    const rows = Array.from(document.querySelectorAll('table tbody tr'));
                    const samples = rows.slice(0, 6).map(tr => tr.innerText.trim().replace(/\\s+/g, ' ').slice(0, 140));
                    return { rowCount: rows.length, samples };
                }"""
            )
            audit["purchase_orders"] = info
        elif route == "/brands":
            info = page.evaluate(
                """() => {
                    const rows = Array.from(document.querySelectorAll('tr[data-brand-id], table tbody tr'));
                    const names = rows.slice(0, 10).map(tr => {
                        const td = tr.querySelector('td');
                        return td ? td.innerText.trim().replace(/\\s+/g, ' ') : '';
                    }).filter(Boolean);
                    return { rowCount: rows.length, sampleNames: names };
                }"""
            )
            audit["brands"] = info
        elif route == "/notes":
            info = page.evaluate(
                """() => {
                    const cards = document.querySelectorAll('[data-note-id], .note-card, article, main ul li');
                    const h = document.body.innerText.slice(0, 400).replace(/\\s+/g, ' ');
                    return { itemCount: cards.length, textSample: h.slice(0, 180) };
                }"""
            )
            audit["notes"] = info
        elif route == "/admin/company-documents":
            info = page.evaluate(
                """() => {
                    const headings = Array.from(document.querySelectorAll('main h2, main h3')).map(e => e.innerText.trim());
                    const links = Array.from(document.querySelectorAll('main a[href]')).map(a => a.getAttribute('href') || '');
                    const docUrls = links.filter(h => h.includes('supabase') || h.includes('r2.dev') || h.includes('.pdf'));
                    return { headings: headings.slice(0, 10), docLinkCount: docUrls.length };
                }"""
            )
            audit["company_documents"] = info
        elif route == "/admin/users":
            info = page.evaluate(
                """() => {
                    const rows = Array.from(document.querySelectorAll('table tbody tr'));
                    const text = rows.map(r => r.innerText).join('\\n');
                    const emailMatches = text.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}/g) || [];
                    const domainCounts = {};
                    emailMatches.forEach(em => {
                        const dom = em.split('@')[1].toLowerCase();
                        domainCounts[dom] = (domainCounts[dom] || 0) + 1;
                    });
                    const names = rows.slice(0, 10).map(r => {
                        const td = r.querySelector('td');
                        return td ? td.innerText.trim().replace(/\\s+/g, ' ').slice(0, 60) : '';
                    }).filter(Boolean);
                    return { rowCount: rows.length, domainCounts, sampleFirstCols: names };
                }"""
            )
            audit["admin_users"] = info
        elif route == "/profile":
            info = page.evaluate(
                """() => {
                    const text = (document.querySelector('main') || document.body).innerText;
                    const masked = text.replace(/[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\\.[A-Za-z]{2,})/g, '***@$1');
                    return { snippet: masked.replace(/\\s+/g, ' ').slice(0, 220) };
                }"""
            )
            audit["profile"] = info
    except Exception as exc:  # noqa: BLE001
        audit[route] = {"audit_error": f"{type(exc).__name__}: {exc}"}


def run_capture(base_url: str, full_page: bool) -> int:
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    email = os.getenv("STAGING_ADMIN_EMAIL", "").strip()
    password = os.getenv("STAGING_ADMIN_PASSWORD", "").strip()
    if not (email and password):
        sys.exit("[ABORT] Set env STAGING_ADMIN_EMAIL dan STAGING_ADMIN_PASSWORD terlebih dahulu.")

    load_and_guard(base_url)
    check_health(base_url)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    server_errors: list[tuple[int, str]] = []
    results: list[ShotResult] = []
    audit: dict = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            base_url=base_url,
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
            locale="id-ID",
        )
        # Defaultkan heka-theme ke midnight-teal hanya jika belum ada di localStorage,
        # sehingga switch ke "light" untuk shot 18 bertahan saat navigasi/reload.
        ctx.add_init_script(
            """() => {
                try {
                    if (localStorage.getItem('heka-theme') === null) {
                        localStorage.setItem('heka-theme', 'midnight-teal');
                    }
                    localStorage.removeItem('sidebarCollapsed');
                } catch (e) {}
            }"""
        )

        page = ctx.new_page()
        page.set_default_timeout(25000)

        active_console_errors: list[str] = []
        active_page_errors: list[str] = []

        def on_console(msg) -> None:
            if msg.type == "error":
                active_console_errors.append(msg.text)

        def on_pageerror(err) -> None:
            active_page_errors.append(str(err))

        def on_response(resp) -> None:
            if resp.status >= 500:
                server_errors.append((resp.status, resp.url))

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("response", on_response)

        def capture_visit(
            filename: str,
            route: str,
            theme: str = "midnight-teal",
            wait_charts: bool = False,
            allow_login_url: bool = False,
        ) -> ShotResult:
            active_console_errors.clear()
            active_page_errors.clear()
            out_path = OUT_DIR / filename

            resp = page.goto(route, wait_until="load")
            status = resp.status if resp else 0
            wait_ready(page, wait_charts=wait_charts)
            apply_theme_and_close_menus(page, theme)
            page.wait_for_timeout(150)

            body_head = page.content()[:20000]
            marker = next((m for m in ERROR_MARKERS if m in body_head), None)
            if not allow_login_url and "/login" in urlparse(page.url).path:
                status = 401
            if marker and status < 500:
                status = 500

            note_parts = []
            if active_console_errors:
                note_parts.append(f"console_err={active_console_errors[:2]}")
            if active_page_errors:
                note_parts.append(f"page_err={active_page_errors[:2]}")
            if marker:
                note_parts.append(f"marker={marker}")

            # Cek apakah tema diterapkan pada <html>
            applied_theme = page.evaluate(
                "() => document.documentElement.getAttribute('data-theme') || ''"
            )
            menu_open = page.evaluate(
                "() => { const m = document.getElementById('themeMenu'); return !!(m && m.classList.contains('is-open')); }"
            )
            if menu_open:
                note_parts.append("themeMenu_still_open")
            if route == "/login":
                has_theme_css = page.evaluate(
                    "() => Array.from(document.styleSheets).some(s => (s.href || '').includes('theme.css'))"
                )
                if not has_theme_css:
                    note_parts.append(f"data-theme={applied_theme} (login.html standalone tanpa theme.css)")

            collect_sanitized_audit(page, route, audit)
            page.screenshot(path=str(out_path), full_page=full_page)
            non_blank, fsize, dims, bnote = verify_png_not_blank(out_path, full_page)
            if not non_blank:
                note_parts.append(bnote)

            res = ShotResult(
                filename=filename,
                route=route,
                status=status,
                console_errors=len(active_console_errors),
                page_errors=len(active_page_errors),
                size_bytes=fsize,
                dimensions=dims,
                non_blank=non_blank,
                note="; ".join(note_parts),
            )
            results.append(res)
            tag = "PASS" if res.ok else "FAIL"
            print(
                f"[{tag}] {filename} | {route} | HTTP {res.status} | "
                f"console={res.console_errors} page_err={res.page_errors} | "
                f"{dims[0]}x{dims[1]} ({fsize} B)"
                + (f" | {res.note}" if res.note else "")
            )
            return res

        try:
            # 1. /login sebelum login (tema midnight-teal)
            capture_visit(
                "01-login.png",
                "/login",
                theme="midnight-teal",
                allow_login_url=True,
            )

            # Login dengan akun testing staging (tanpa mencetak kredensial)
            page.fill("input[name=email]", email)
            page.fill("input[name=password]", password)
            page.click("#login-submit-btn")
            try:
                page.wait_for_url(lambda u: "/login" not in urlparse(u).path, timeout=30000)
            except PWTimeout:
                sys.exit(f"[ABORT] Login staging gagal atau timeout (URL akhir: {page.url}).")

            # Pastikan localStorage heka-theme = midnight-teal sebelum buka dashboard
            page.evaluate("() => localStorage.setItem('heka-theme', 'midnight-teal')")

            # 2. Dashboard tab Master Produk Terbaru
            capture_visit("02-dashboard-products.png", "/", theme="midnight-teal")

            # 3. Dashboard tab Checklist Kelengkapan DIP Bab I-IV
            active_console_errors.clear()
            active_page_errors.clear()
            page.click("button[onclick*='tab-checklist-dip']")
            page.wait_for_function(
                "() => { const el = document.getElementById('tab-checklist-dip'); return el && !el.classList.contains('hidden'); }",
                timeout=10000,
            )
            page.wait_for_timeout(400)
            apply_theme_and_close_menus(page, "midnight-teal")
            page.evaluate(
                "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
            )
            shot3_path = OUT_DIR / "03-dashboard-dip-checklist.png"
            page.screenshot(path=str(shot3_path), full_page=full_page)
            nb3, sz3, dm3, bn3 = verify_png_not_blank(shot3_path, full_page)
            res3 = ShotResult(
                filename="03-dashboard-dip-checklist.png",
                route="/ (tab-checklist-dip)",
                status=200,
                console_errors=len(active_console_errors),
                page_errors=len(active_page_errors),
                size_bytes=sz3,
                dimensions=dm3,
                non_blank=nb3,
                note="" if nb3 else bn3,
            )
            results.append(res3)
            print(
                f"[{'PASS' if res3.ok else 'FAIL'}] {res3.filename} | {res3.route} | HTTP 200 | "
                f"console={res3.console_errors} page_err={res3.page_errors} | "
                f"{dm3[0]}x{dm3[1]} ({sz3} B)" + (f" | {res3.note}" if res3.note else "")
            )

            # Pilih 1 product_id valid dari tabel Dashboard
            product_id = pick_best_product_id(page)

            # 4..17 Halaman-halaman dalam tema Midnight Teal
            pages_mt = [
                ("04-product-edit.png", f"/products/{product_id}/edit", False),
                ("05-qualitative-quantitative.png", f"/products/{product_id}/qualitative-quantitative", False),
                ("06-inci-report.png", f"/products/{product_id}/inci-breakdown/report", False),
                ("07-finished-spec.png", f"/products/{product_id}/finished-spec", False),
                ("08-product-attachments.png", f"/products/{product_id}/lampiran", False),
                ("09-raw-materials.png", "/raw-materials", False),
                ("10-purchase-orders.png", "/purchase-orders", False),
                ("11-po-analytics.png", "/po-analytics", True),
                ("12-sample-submissions.png", "/sample-submissions", False),
                ("13-brands.png", "/brands", False),
                ("14-notes.png", "/notes", False),
                ("15-company-documents.png", "/admin/company-documents", False),
                ("16-admin-users.png", "/admin/users", False),
                ("17-profile.png", "/profile", False),
            ]
            for fname, route, wait_ch in pages_mt:
                capture_visit(fname, route, theme="midnight-teal", wait_charts=wait_ch)

            # 18. Bonus: Dashboard dalam tema "light"
            page.evaluate("() => localStorage.setItem('heka-theme', 'light')")
            capture_visit("18-dashboard-light-theme.png", "/", theme="light")

        finally:
            browser.close()

    print("\n=== RINGKASAN SCREENSHOT ===")
    passed = sum(1 for r in results if r.ok)
    print(f"Lolos: {passed}/{len(results)} halaman")
    if server_errors:
        print(f"[FAIL] Terdeteksi {len(server_errors)} respons HTTP >= 500:")
        for st, u in server_errors[:10]:
            print(f"  - {st} {u}")
    else:
        print("[PASS] 0 respons HTTP >= 500 selama sesi.")

    print("\n=== [DATA AUDIT] (READ-ONLY, TERSANITASI) ===")
    for k, v in audit.items():
        print(f"- {k}: {v}")

    if passed != len(results) or server_errors:
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture E2E showcase screenshots from staging.")
    ap.add_argument(
        "--base-url",
        default=os.getenv("STAGING_BASE_URL", "http://127.0.0.1:8017"),
        help="Base URL server staging lokal (default: http://127.0.0.1:8017)",
    )
    ap.add_argument(
        "--full-page",
        action="store_true",
        help="Ambil full_page=True alih-alih viewport 1440x900 @2x",
    )
    args = ap.parse_args()
    return run_capture(args.base_url, full_page=args.full_page)


if __name__ == "__main__":
    sys.exit(main())
