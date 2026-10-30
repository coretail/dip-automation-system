"""Regresi audit codebase DIP Automation (catatan 2026-10-21).

File ini mengunci hasil audit read-only `catatan/catatan_audit_codebase_2026-10-21.md`
menjadi assertion yang bisa dijalankan mesin. Tujuannya: setiap temuan yang
sudah CONFIRMED punya satu baris executable yang berubah dari [KNOWN] jadi
[PASS] begitu perbaikannya masuk, dan jadi [FAIL] kalau perilakunya mundur lagi.

Cakupan (ID audit yang dilindungi):
  - Inventaris route       : SEC-01, SEC-09, SEC-16, SEC-17
  - Header & flag cookie   : SEC-04, SEC-07
  - Kontrak error jujur    : BE-01, BE-02, BE-03, BE-08, BE-21
  - Dead code & duplikasi  : SEC-02, BE-04, BE-07, SEC-14, SEC-18
  - Template & escaping    : SEC-14, FE-05
  - Polling frontend       : FE-05, FE-06, FE-07
  - Doc-drift audit trail  : U6 (tabel entitas audit di panduan)
  - Unit pure-module       : SEC-02 (helper tenant), file_validation, object_store
  - Kejujuran hasil write  : H3.1, H3.2, H3.3, H3.4, H3.5, H3.6, H3.7, MIG-010

Perubahan status:
  - 2026-10-21: SEC-01 (route POST /products/delete/{id} hilang di commit
    5f82f94) DIPERBAIKI - route dipulihkan di app/products_routes.py, form
    dashboard di-gate untuk admin, teks konfirmasi diperbaiki (soft delete
    tidak menghapus formula). SEC-01 keluar dari KNOWN_ISSUES; registry
    KNOWN_ISSUES sekarang berisi 18 entri.
  - 2026-10-22: H3.1-H3.5 (temuan "false success report" saat write gagal)
    DIPERBAIKI:
      - H3.1 formula Bab 2: validasi total 100.0000% di server (helper murni
        _validate_formula_total di app/products_routes.py), snapshot baris lama
        sebelum delete, rollback aman (dijaga flag delete selesai), jalur gagal
        tidak menulis audit sukses.
      - H3.2/H3.3 batch bahan baku: path upload unik per operasi (sufiks
        uuid4), objek yang baru diupload dibersihkan saat DB gagal, flash
        message + audit outcome yang jujur.
      - H3.4 hapus FSP: flash error_msg + payload audit tanpa str(e).
      - H3.5 simpan note: simpan note / mention / audit dipisah jadi tiga blok
        try; kegagalan @mention memakai warning_msg (base.html sekarang
        merender warning_msg).
    BE-01, BE-02, BE-03, dan BE-21 keluar dari KNOWN_ISSUES karena sudah
    diperbaiki; registry KNOWN_ISSUES sekarang berisi 14 entri.
    Section 8 (KEJUJURAN HASIL WRITE) mengunci perbaikan tersebut.
  - 2026-10-22: jalur tulis formula Bab 2 dipindah ke fungsi transaksi
    Postgres public.replace_product_formula(uuid, jsonb) (migration 010).
    Mekanisme lama (snapshot + rollback + flag delete selesai) DIHAPUS dari
    aplikasi, jadi H3.1c, H3.1d, H3.1f, dan MIG-010 ditulis ulang untuk
    mengunci mekanisme baru (bukan lagi mengunci yang lama). Ditambah 8 check
    baru H3.6a-H3.6h untuk mengunci jalur baru: klasifikasi kegagalan RPC,
    kunci baris produk induk di migrasi, pre-read batch sebelum unggah,
    penanganan batch yang hilang, pemeriksaan referensi file lama, tiga
    kondisi upload cepat, nilai outcome yang dibatasi, dan penulisan sukses
    sebagian.

  - 2026-10-22 (P2 alur upload batch): dua temuan P2 pada alur upload batch
    diperbaiki di app/raw_materials_routes.py.
      - Upload cepat sekarang mengambil tiga kolom URL lama pada pre-read dan
        membersihkan objek yang digantikan SETELAH update terkonfirmasi sukses;
        hasil pembersihan masuk ke audit trail dan dilaporkan lewat warning_msg
        yang menyebut nomor batch.
      - Kegagalan database diklasifikasikan dari TIPE exception, bukan dari
        teks pesan: pasti ditolak (APIError dari PostgREST) -> file baru
        dihapus; ambigu (timeout/transport) -> file baru DIPERTAHANKAN dan
        dicek ulang ke database (rekonsiliasi). Hasil rekonsiliasi yang kosong
        BUKAN bukti pasti gagal, jadi file tetap disimpan dan path-nya
        dicatat di activity log untuk rekonsiliasi manual.
    Ditambah 7 check baru H3.7a-H3.7g (klasifikasi, rekonsiliasi, dan
    pembersihan objek lama).

  - 2026-10-22 (upload cepat, jumlah baris terpengaruh): route upload cepat
    dokumen batch sekarang memakai penanda exception yang sama dengan route ubah batch
    (`_BatchUpdateAffectedNoRow`), jadi UPDATE yang tidak menyentuh baris
    mana pun diperlakukan sebagai kegagalan pasti - bukan dilaporkan sukses.
    Batch yang hilang di antara pre-read dan update tidak lagi meninggalkan
    objek yatim di storage dan baris audit `outcome="success"` yang palsu.
    Ditambah 1 check baru H3.7h yang mengunci rantai `.select("id")`,
    pembacaan jumlah baris terpengaruh, cabang tanpa baris, klasifikasi
    kegagalan pasti, pesan jujur, dan pembersihan objek lama yang hanya
    boleh jalan di jalur sukses.

Sifat wajib file ini:
  - READ-ONLY. Tidak pernah menyentuh database, jaringan, atau server.
  - Tidak pernah membaca/mencetak isi .env / .env.staging.
  - Tidak mengimpor app.main (membuat FastAPI app + Supabase client saat import).
    Hanya app.security, app.file_validation, app.object_store yang diimpor
    opsional, dan semuanya dibungkus try/except -> SKIP kalau tidak tersedia.
  - Tidak butuh pytest. Semua pemeriksaan murni assert + fungsi biasa.

Prasyarat:
    pip install -r requirements.txt   (atau pakai venv repo)

Jalankan:
    python tests/test_audit_regressions.py
    python tests/test_audit_regressions.py --strict

Exit code:
    0 = tidak ada FAIL (KNOWN tetap boleh, itu baseline yang diharapkan)
    1 = ada minimal satu FAIL
    1 juga bila dijalankan dengan --strict dan ada temuan KNOWN
"""
from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
TPL_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
TESTS_DIR = ROOT / "tests"
PANDUAN_PATH = ROOT / "panduan_dip_automation_system.md"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HTTP_VERBS = ("get", "post", "put", "delete", "patch", "head", "options")

# ---------------------------------------------------------------------------
# Registry temuan yang saat ini DIHARAPKAN masih gagal.
# Entri di sini = baseline yang disengaja, BUKAN kegagalan suite.
# Key = id audit, value = ringkasan singkat temuan.
# ---------------------------------------------------------------------------
KNOWN_ISSUES: dict[str, str] = {
    "SEC-02": "assert_same_tenant tidak di-import modul mana pun; isolasi tenant praktis tidak terpasang.",
    "BE-07": "Isolasi tenant hanya sebagian; helper app/security.py masih dead code produksi.",
    "SEC-04": "Tanpa middleware security header (main.py:339). Bagian cookie access_token secure=True sudah diperbaiki (SEC-19).",
    "SEC-07": "Nol security header: tidak ada CSP/X-Frame-Options/X-Content-Type-Options/Referrer-Policy/HSTS.",
    "SEC-14": "escapeHtml punya 4 implementasi terpisah; target audit: satu helper global.",
    "SEC-16": "Logout masih dipicu via GET sehingga bisa dipaksa CSRF (main.py:1143); target: POST.",
    "SEC-18": "Artefak teks 'omniroute' masih ada di brands.html:1 sebelum blok extends.",
    "BE-04": "Query .single() di luar try -> baris tidak ada jadi HTTP 500 (bukan 'tidak ditemukan').",
    "BE-08": "str(e) bocor ke browser dan dipersistensi ke activity_logs (PostgREST message/hint/details).",
    "DUPL-01": "compute_status_na() dipanggil dua kali berturut-turut (sisa bad merge di dashboard_routes.py).",
    "FE-05": "Link logout di sidebar tidak menghentikan heartbeat presence.",
    "FE-06": "window.__adminPresenceInterval tidak pernah di-assign di admin_users.html.",
    "FE-07": "Countdown lockout tidak menjaga submit form login (submit via Enter menembus limiter).",
    "U6": "Tabel entitas audit (panduan:699-713) belum menyebut 5 nilai entity_type: "
          "product_attachment, product_file, product_batch, purchase_order, purchase_order_item.",
}

RESULTS: list[tuple[str, str, str]] = []


# ---------------------------------------------------------------------------
# Helper pelaporan
# ---------------------------------------------------------------------------
def check(name: str, ok: bool, detail: str = "", known: str | None = None) -> bool:
    """Catat satu hasil pemeriksaan dan cetak baris statusnya.

    ok=True -> [PASS]
    ok=False + `known` ada di KNOWN_ISSUES -> [KNOWN] (baseline yang diharapkan)
    ok=False + `known` tidak dikenal        -> [FAIL] (regresi / tak terduga)
    """
    if ok:
        status = "PASS"
    elif known and known in KNOWN_ISSUES:
        status = "KNOWN"
        detail = f"{detail} | {KNOWN_ISSUES[known]}" if detail else KNOWN_ISSUES[known]
    else:
        status = "FAIL"
    RESULTS.append((status, name, detail))
    if status == "PASS":
        print(f"[PASS] {name}")
    elif status == "KNOWN":
        print(f"[KNOWN] {name} - {detail} ({known})")
    else:
        print(f"[FAIL] {name} - {detail}")
    return ok


def skip(name: str, reason: str) -> None:
    """Tandai pemeriksaan yang tidak dijalankan (sudah diuji di file lain)."""
    RESULTS.append(("SKIP", name, reason))
    print(f"[SKIP] {name} - {reason}")


def section(title: str) -> None:
    print()
    print("=" * 74)
    print(title)
    print("=" * 74)


# ---------------------------------------------------------------------------
# Helper parsing (murni lokal, tanpa import modul aplikasi)
# ---------------------------------------------------------------------------
ROUTE_RE = re.compile(
    r"^[ \t]*@app\.(get|post|put|delete|patch|head|options)\(\s*[\"']([^\"']+)[\"']",
    re.MULTILINE,
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def app_py_files() -> list[Path]:
    return sorted(APP_DIR.glob("*.py"))


def template_files() -> list[Path]:
    return sorted(TPL_DIR.glob("*.html"))


def static_files() -> list[Path]:
    return sorted(STATIC_DIR.glob("*.js"))


def extract_call(text: str, open_paren: int) -> str:
    """Ambil teks panggilan fungsi mulai '(' sampai ')' pasangannya.

    Menghormati string literal supaya tanda kurung di dalam teks tidak
    menggeser pencocokan.
    """
    depth = 0
    i = open_paren
    quote = None
    n = len(text)
    while i < n:
        ch = text[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren:i + 1]
        i += 1
    return text[open_paren:]


def split_top_level_args(args_text: str) -> list[str]:
    """Pecah argumen panggilan fungsi pada koma level teratas."""
    parts: list[str] = []
    depth = 0
    quote = None
    current: list[str] = []
    for ch in args_text:
        if quote is not None:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            current.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts]


def route_signature(text: str, search_from: int) -> str:
    """Ambil signature fungsi handler yang mengikuti sebuah dekorator route."""
    m = re.compile(
        r"^[ \t]*(?:async[ \t]+)?def[ \t]+\w+[ \t]*\(", re.MULTILINE
    ).search(text, search_from)
    if not m:
        return ""
    open_paren = text.index("(", m.start())
    return extract_call(text, open_paren)


def collect_routes() -> list[dict]:
    """Parse dekorator @app.<verb> dari seluruh app/*.py tanpa meng-import modul."""
    routes: list[dict] = []
    for path in app_py_files():
        text = read_text(path)
        for m in ROUTE_RE.finditer(text):
            routes.append({
                "method": m.group(1).upper(),
                "path": m.group(2),
                "file": path.name,
                "line": text.count("\n", 0, m.start()) + 1,
                "text": text,
                "match_end": m.end(),
            })
    return routes


def is_route_decorator(node: ast.AST) -> bool:
    """True bila node punya dekorator @app.get/@app.post/... (bukan @app.mount)."""
    for dec in getattr(node, "decorator_list", []) or []:
        func = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(func, ast.Attribute) and func.attr in HTTP_VERBS:
            value = func.value
            if isinstance(value, ast.Name) and value.id == "app":
                return True
    return False


def registration_functions() -> dict[str, list[str]]:
    """Map file -> nama fungsi yang mendaftarkan route di dalamnya.

    Fungsi registrasi = fungsi level modul yang MEMBungkus handler route
    (handler-nya adalah FunctionDef bersarang dengan dekorator @app.<verb>).
    """
    found: dict[str, list[str]] = {}
    for path in app_py_files():
        try:
            tree = ast.parse(read_text(path))
        except SyntaxError:
            continue
        names: list[str] = []
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            nested = [
                child for child in ast.walk(node)
                if child is not node
                and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and is_route_decorator(child)
            ]
            if nested:
                names.append(node.name)
        if names:
            found[path.name] = names
    return found


# ---------------------------------------------------------------------------
# Helper doc-drift audit trail (U6) - bandingkan entity_type kode vs dokumen
# ---------------------------------------------------------------------------
def collect_entity_types_from_code() -> tuple[set[str], set[str]]:
    """Nilai `entity_type` yang dipancarkan kode.

    Sumber: setiap panggilan `log_activity(...)` di app/*.py. entity_type
    adalah argumen positional ke-3 ATAU keyword `entity_type=`.

    Return (statis, dinamis):
      statis  -> nilai string literal, mis. "product_attachment"
      dinamis -> nama variabel, mis. "doc_type" (nilainya himpunan whitelist)
    """
    static: set[str] = set()
    dynamic: set[str] = set()
    for path in app_py_files():
        try:
            tree = ast.parse(read_text(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id == "log_activity"):
                continue
            value = None
            if len(node.args) >= 3:
                value = node.args[2]
            for kw in node.keywords:
                if kw.arg == "entity_type":
                    value = kw.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                static.add(value.value)
            elif isinstance(value, ast.Name):
                dynamic.add(value.id)
    return static, dynamic


def resolve_dynamic_entity_types(dynamic_names: set[str]) -> set[str]:
    """Nilai konkret untuk `entity_type` yang dinamis.

    Untuk nama variabel (mis. `doc_type` di app/company_docs_routes.py) nilai
    sebenarnya adalah himpunan kunci whitelist di modul yang sama, mis.
    `COMPANY_DOC_MAP` di app/company_docs_routes.py:19-27. Modul yang memakai
    nama dinamis itu searched, lalu semua dict level-modul di dalamnya dibaca
    key-nya (hanya key berbentuk identifier lowercase, mis. "nib").
    """
    resolved: set[str] = set()
    if not dynamic_names:
        return resolved
    key_re = re.compile(r"^[a-z][a-z0-9_]*$")
    for path in app_py_files():
        try:
            tree = ast.parse(read_text(path))
        except SyntaxError:
            continue
        uses_dynamic = any(
            isinstance(node, ast.Name) and node.id in dynamic_names
            for node in ast.walk(tree)
        )
        if not uses_dynamic:
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
                continue
            for key in node.value.keys:
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and key_re.match(key.value)
                ):
                    resolved.add(key.value)
    return resolved


def documented_entity_types() -> tuple[set[str], bool]:
    """Nilai `entity_type` yang didokumentasikan di panduan.

    Membaca tabel "Cakupan Detail dalam Audit Trail"
    (panduan_dip_automation_system.md, kolom pertama berisi identifier
    backtick). Baris generik `{doc_type}` perusahaan dicatat terpisah lewat
    flag kedua: baris itu menutupi semua nilai doc_type dinamis.
    """
    documented: set[str] = set()
    generic = False
    if not PANDUAN_PATH.exists():
        return documented, generic
    lines = read_text(PANDUAN_PATH).splitlines()
    start = None
    for i, line in enumerate(lines):
        if "Jenis entitas" in line and line.strip().startswith("|"):
            start = i + 1
            break
    if start is None:
        return documented, generic
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            continue
        m = re.fullmatch(r"`([^`]+)`", cells[0])
        if not m:
            continue
        token = m.group(1)
        if "doc_type" in token:
            generic = True
            continue
        documented.add(token)
    return documented, generic


def strip_jinja_comments(text: str) -> str:
    return re.sub(r"\{#.*?#\}", "", text, flags=re.S)


def strip_js_comments(text: str) -> str:
    """Buang komentar blok dan komentar baris (hanya yang di awal baris)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^[ \t]*//[^\n]*", "", text)


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def strip_python_comments(text: str) -> str:
    """Hapus komentar Python tanpa mengubah jumlah baris maupun kolom.

    Dipakai untuk memeriksa isi KODE saja. Penjelasan di dalam komentar
    bukan mekanisme yang berjalan, jadi tidak boleh dihitung sebagai
    "mekanisme lama masih ada".
    """
    lines = text.splitlines(keepends=True)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError):
        return text
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        srow, scol = tok.start
        erow = tok.end[0]
        if srow != erow or srow - 1 >= len(lines):
            continue
        idx = srow - 1
        isi = lines[idx].rstrip("\r\n")
        akhir = lines[idx][len(isi):]
        lines[idx] = isi[:scol] + " " * max(0, len(isi) - scol) + akhir
    return "".join(lines)


def find_pattern_line(text: str, pattern: str) -> int:
    """Indeks baris kemunculan pertama sebuah regex, dihitung mulai dari nol;
    nilai -1 kalau pola tidak ditemukan.
    """
    m = re.search(pattern, text)
    if not m:
        return -1
    return text.count("\n", 0, m.start())


def handler_region(lines: list[str], decorator_needle: str) -> tuple[int, int]:
    """Batas handler sebuah route: (baris_awal, baris_akhir_exklusif).

    Baris akhir diambil dari dekorator route berikutnya, jadi isi handler
    yang dibaca benar-benar milik route yang dicari.
    """
    start = -1
    for i, l in enumerate(lines):
        if decorator_needle in l:
            start = i
            break
    if start < 0:
        return -1, -1
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^[ \t]*@app\.(get|post|put|delete|patch|head|options)\(", lines[i]):
            end = i
            break
    return start, end


def python_function_code(text: str, func_name: str) -> str:
    """Kode sebuah fungsi level modul, TANPA docstring.

    Docstring hanya penjelasan; penyebutan nama fungsi atau kode PostgREST
    di dalam docstring tidak boleh dihitung sebagai implementasi.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ""
    lines = text.splitlines()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != func_name:
            continue
        doc = node.body[0] if node.body else None
        if (
            isinstance(doc, ast.Expr)
            and isinstance(doc.value, ast.Constant)
            and isinstance(doc.value.value, str)
        ):
            return "\n".join(lines[:doc.lineno - 1] + lines[doc.end_lineno:])
        return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return ""


def python_function_body(text: str, func_name: str) -> str:
    """Kode sebuah fungsi level modul, TANPA docstring, dengan batas yang benar.

    Dipakai untuk pemeriksaan yang harus benar-benar hanya isi fungsi. Helper
    `python_function_code` mengembalikan seluruh file kalau fungsi punya
    docstring, jadi helper ini dipakai untuk check yang butuh isi fungsi saja.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ""
    lines = text.splitlines()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != func_name:
            continue
        awal = node.lineno - 1
        akhir = node.end_lineno or node.lineno
        doc = node.body[0] if node.body else None
        if (
            isinstance(doc, ast.Expr)
            and isinstance(doc.value, ast.Constant)
            and isinstance(doc.value.value, str)
        ):
            return "\n".join(lines[awal:doc.lineno - 1] + lines[doc.end_lineno:akhir])
        return "\n".join(lines[awal:akhir])
    return ""


def module_dict_keys(text: str, name: str) -> list:
    """Kunci dict konstanta di level modul (mis. DOC_FIELD_LABELS)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        if isinstance(node.value, ast.Dict):
            return [
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            ]
    return []


def call_sites_with_guard(node, func_name: str, inside_except: bool = False, guard=None):
    """Kumpulkan (baris, di_dalam_except, guard) untuk tiap pemanggilan fungsi.

    `guard` adalah sumber kondisi `if` terdekat yang membungkus pemanggilan,
    dipakai untuk memastikan cleanup hanya jalan di bawah penentu "kegagalan
    pasti" - bukan di bawah handler exception umum.
    """
    out = []
    if isinstance(node, ast.Call):
        fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fname == func_name:
            out.append((node.lineno, inside_except, guard))
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ExceptHandler):
            # Handler exception = scope baru: guard di luar tidak berlaku.
            out.extend(call_sites_with_guard(child, func_name, True, None))
        elif isinstance(child, ast.If):
            out.extend(
                call_sites_with_guard(
                    child, func_name, inside_except, ast.unparse(child.test)
                )
            )
        else:
            out.extend(call_sites_with_guard(child, func_name, inside_except, guard))
    return out


def module_call_sites(text: str, func_name: str):
    """(baris, di_dalam_except, guard) untuk tiap pemanggilan di seluruh modul."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    return sorted(call_sites_with_guard(tree, func_name))


def handler_call_sites(text: str, route_path: str, func_name: str):
    """Panggilan func_name di dalam satu handler route.

    Dipakai untuk memastikan call site tertentu ada di jalur yang benar
    (mis. di luar blok except = jalur sukses).
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        route_ok = False
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not dec.args:
                continue
            first = dec.args[0]
            if isinstance(first, ast.Constant) and first.value == route_path:
                route_ok = True
        if not route_ok:
            continue
        out.extend(call_sites_with_guard(node, func_name))
    return sorted(out)


def python_function_span(text: str, func_name: str) -> tuple[int, int]:
    """Indeks baris awal & akhir (exklusif) fungsi level modul tertentu,
    dihitung mulai dari nol.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return -1, -1
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return node.lineno - 1, (node.end_lineno or node.lineno)
    return -1, -1


# ---------------------------------------------------------------------------
# Section 1 - Inventaris route (parse statis, tanpa import)
# ---------------------------------------------------------------------------
def section_routes() -> None:
    section("SECTION 1 - INVENTARIS ROUTE (parse statis app/*.py, tanpa import)")

    routes = collect_routes()
    pairs = {(r["method"], r["path"]) for r in routes}

    # SEC-01 - tombol "Hapus Produk" di dashboard.html mem-post ke
    # /products/delete/{id}. Route-nya sempat hilang (commit 5f82f94) ->
    # tombol selalu 404. Perbaikan (2026-10-21): route HARUS terdaftar,
    # form harus admin-gated, dan teks konfirmasi harus jujur (soft delete
    # memindahkan produk ke Sampah, formula TIDAK ikut terhapus).
    delete_product = sorted(
        f"{r['method']} {r['path']} ({r['file']}:{r['line']})"
        for r in routes
        if r["method"] == "POST" and re.match(r"^/products/delete/", r["path"])
    )

    dash_text = read_text(TPL_DIR / "dashboard.html")
    gate_m = re.search(
        r"\{%-?\s*if\s+current_user\.role\s*==\s*'admin'\s*-?%\}", dash_text
    )
    form_m = re.search(r"<form[^>]*action=\"/products/delete/", dash_text)
    form_admin_gated = False
    if gate_m and form_m:
        endif_m = re.search(r"\{%-?\s*endif\s*-?%\}", dash_text[gate_m.end():])
        form_admin_gated = bool(
            endif_m and gate_m.end() <= form_m.start() < gate_m.end() + endif_m.end()
        )

    form_tag = ""
    if form_m:
        tag_end = dash_text.find(">", form_m.start())
        form_tag = dash_text[form_m.start(): tag_end if tag_end != -1 else len(dash_text)]
    claims_formula_deleted = "bakal ikut kehapus" in form_tag
    confirm_mentions_sampah = "Sampah" in form_tag
    confirm_mentions_restore = ("dikembalikan" in form_tag) or ("restore" in form_tag.lower())

    sec01_problems = []
    if not delete_product:
        sec01_problems.append(
            "tidak ada POST /products/delete/* di app/*.py (tombol dashboard masih broken)"
        )
    if not form_admin_gated:
        sec01_problems.append(
            "form /products/delete/ di dashboard.html tidak berada di dalam "
            "{% if current_user.role == 'admin' %}"
        )
    if claims_formula_deleted:
        sec01_problems.append(
            "teks konfirmasi masih mengklaim formula ikut terhapus (soft delete tidak menghapus formula)"
        )
    if not (confirm_mentions_sampah and confirm_mentions_restore):
        sec01_problems.append(
            "teks konfirmasi tidak menjelaskan perpindahan ke Sampah + kembalikan dari Sampah"
        )

    check(
        "SEC-01 route soft-delete produk + form hapus dashboard (admin-gated, teks jujur)",
        not sec01_problems,
        ("route soft-delete: " + ", ".join(delete_product))
        if delete_product and not sec01_problems
        else "; ".join(sec01_problems),
    )

    # SEC-01 (lanjutan) - parser harus tetap bisa membedakan route delete-file.
    check(
        "SEC-01 parser route membedakan /products/{id}/delete-file",
        ("POST", "/products/{product_id}/delete-file") in pairs,
        "route /products/{product_id}/delete-file tidak ditemukan di app/*.py",
    )

    # SEC-16 - /logout harusnya POST (anti CSRF); GET = forced logout.
    has_get_logout = ("GET", "/logout") in pairs
    has_post_logout = ("POST", "/logout") in pairs
    # SEC-16: /logout via GET bisa dipicu CSRF (forced logout). Perbaikannya
    # memindahkan /logout ke POST, jadi yang diminta adalah POST ada.
    check(
        "SEC-16 logout dipindah dari GET ke POST (main.py:1143)",
        has_post_logout and not has_get_logout,
        "GET /logout: %s, POST /logout: %s" % (has_get_logout, has_post_logout),
        known="SEC-16",
    )

    # SEC-09 - set route publik /dip/{slug_id} harus tetap ada TANPA auth
    # dependency. Bila auth dependency ditambahkan diam-diam, portal publik
    # untuk verifier BPOM ikut mati; minimal 8 route jadi jaring pengaman.
    public_routes = []
    for r in routes:
        if not r["path"].startswith("/dip/"):
            continue
        sig = route_signature(r["text"], r["match_end"])
        if "get_current_user" not in sig and "Depends(" not in sig:
            public_routes.append(f"{r['method']} {r['path']}")
    check(
        "SEC-09 route publik /dip/{slug_id} tetap tanpa auth dependency",
        len(public_routes) >= 8,
        "route publik tanpa auth: %d (%s)" % (len(public_routes), ", ".join(sorted(public_routes))),
    )

    # SEC-17 - rate limit wajib ada di /login, /profile/change-password,
    # dan /profile/display-name.
    # Audit: endpoint admin/upload/heartbeat tetap belum dilimit.
    limit_hits: list[str] = []
    for path in app_py_files():
        text = read_text(path)
        for m in re.finditer(r"^[ \t]*@limiter\.limit\(", text, re.MULTILINE):
            before = text[:m.start()]
            route_m = None
            for rm in re.finditer(ROUTE_RE.pattern, before, re.MULTILINE):
                route_m = rm
            method = route_m.group(1).upper() if route_m else "?"
            target = route_m.group(2) if route_m else "?"
            limit_hits.append(
                "%s:%d -> %s %s" % (path.name, line_of(text, m.start()), method, target)
            )
    check(
        "SEC-17 rate limit login, ganti password, dan display-name tetap ada",
        len(limit_hits) == 3
        and any("POST /login" in hit for hit in limit_hits)
        and any("POST /profile/change-password" in hit for hit in limit_hits)
        and any("POST /profile/display-name" in hit for hit in limit_hits),
        "dekorator @limiter.limit: %s" % ("; ".join(limit_hits) if limit_hits else "tidak ada"),
    )

    # ARCH - fungsi registrasi route harus bernama register_*_routes.
    reg = registration_functions()
    bad_names = sorted(
        f"{fname}:{name}"
        for fname, names in reg.items()
        for name in names
        if not re.match(r"^register_\w+_routes$", name)
    )
    total_reg = sum(len(v) for v in reg.values())
    check(
        "ARCH-01 semua fungsi registrasi route bernama register_*_routes",
        not bad_names,
        ("nama yang tidak sesuai: %s" % ", ".join(bad_names))
        if bad_names
        else "%d fungsi registrasi route" % total_reg,
    )

    # ARCH - setiap register_*_routes harus dipanggil dari app/main.py, kalau
    # tidak route-nya diam-diam hilang (kelas bug yang sama dengan SEC-01).
    main_text = read_text(APP_DIR / "main.py")
    not_called = sorted(
        name
        for names in reg.values()
        for name in names
        if not re.search(r"^[^#\n]*\b%s\s*\(" % re.escape(name), main_text, re.MULTILINE)
    )
    check(
        "ARCH-02 setiap register_*_routes dipanggil dari app/main.py",
        not not_called,
        ("tidak dipanggil: %s" % ", ".join(not_called))
        if not_called
        else "semua %d fungsi registrasi terpanggil dari main.py" % total_reg,
    )


# ---------------------------------------------------------------------------
# Section 2 - Security header & flag cookie
# ---------------------------------------------------------------------------
def section_security_headers() -> None:
    section("SECTION 2 - SECURITY HEADER & FLAG COOKIE (parse statis app/main.py)")

    main_path = APP_DIR / "main.py"
    main_text = read_text(main_path)

    # SEC-04 (bagian middleware) - audit: app/main.py:339 tidak punya middleware.
    middleware_calls = re.findall(r"^[ \t]*app\.add_middleware\(", main_text, re.MULTILINE)
    check(
        "SEC-04 middleware security header terpasang (main.py:339)",
        bool(middleware_calls),
        "tidak ada app.add_middleware() di app/main.py (nol security header)",
        known="SEC-04",
    )

    # SEC-07 - header defensif yang harusnya dikirim.
    headers = (
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Strict-Transport-Security",
        "Content-Security-Policy",
    )
    missing = [h for h in headers if h not in main_text]
    check(
        "SEC-07 header keamanan defensif dikirim (main.py:339)",
        not missing,
        ("header yang tidak ada: %s" % ", ".join(missing))
        if missing
        else "semua header keamanan terpasang",
        known="SEC-07",
    )

    # SEC-04 (bagian cookie) - parsing pemanggilan set_cookie untuk access_token.
    cookie_calls: list[tuple[str, int]] = []
    for m in re.finditer(r"\.set_cookie\(", main_text):
        call = extract_call(main_text, m.end() - 1)
        cookie_calls.append((call, line_of(main_text, m.start())))
    access_cookie = ""
    access_line = 0
    for call, ln in cookie_calls:
        if '"access_token"' in call or "'access_token'" in call:
            access_cookie = call
            access_line = ln
            break
    if not access_cookie:
        check(
            "SEC-04 cookie access_token memakai secure=True (main.py:1121-1134)",
            False,
            "pemanggilan set_cookie untuk access_token tidak ditemukan di app/main.py",
            known="SEC-04",
        )
    else:
        check(
            "SEC-04 cookie access_token memakai secure=True (main.py:1121-1134)",
            "secure=True" in access_cookie.replace(" ", ""),
            "set_cookie access_token (main.py:%d) tidak memuat secure=True" % access_line,
            known="SEC-04",
        )

    # httponly + samesite saat ini sudah benar -> harus PASS dan menjaga regresi.
    check(
        "SEC-04 cookie access_token tetap httponly=True (main.py:1124)",
        "httponly=True" in access_cookie.replace(" ", ""),
        "set_cookie access_token (main.py:%d) kehilangan httponly=True" % access_line,
    )
    check(
        "SEC-04 cookie access_token tetap samesite=lax (main.py:1126)",
        re.search(r"""samesite\s*=\s*["']lax["']""", access_cookie) is not None,
        "set_cookie access_token (main.py:%d) kehilangan samesite=lax" % access_line,
    )

# ---------------------------------------------------------------------------
# Section 3 - Kejujuran error handling
# ---------------------------------------------------------------------------
# Aturan diskriminasi BE-08: yang dihitung sebagai bocor HANYA str() atas
# variabel yang benar-benar di-bind sebagai exception (`except ... as <nama>`),
# karena str(e)/str(err)/str(exc) bisa memuat pesan error mentah (PostgREST
# message/hint/details) yang bocor ke browser atau dipersistensi ke
# activity_logs. str() atas variabel lain - misalnya str(old_deleted_at) yang
# merender timestamp - BUKAN bocor dan tidak boleh dihitung, kalau tidak
# pemakaian str() yang sah akan menaikkan hitungan bocor secara palsu.
#
# Fallback berbasis nama dipakai hanya kalau file gagal di-parse (SyntaxError),
# supaya deteksi bocor tidak ikut melemah.
FALLBACK_EXCEPTION_NAMES = {"e", "err", "exc", "ex", "error", "exception"}

LEAK_PATTERNS = (
    re.compile(r"JSONResponse\([^)]*?str\(([A-Za-z_]\w*)\)"),
    re.compile(r"set_cookie\([^)]*?str\(([A-Za-z_]\w*)\)"),
    re.compile(r"[\"']note[\"']\s*:\s*str\(([A-Za-z_]\w*)\)"),
)


def exception_names(text: str) -> set[str] | None:
    """Nama variabel yang di-bind sebagai exception di sebuah file.

    Sumber: `except ... as <nama>` (ast.ExceptHandler). Mengembalikan None
    kalau file tidak bisa di-parse -> pemakai memakai fallback berbasis nama.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and node.name
    }


def find_str_leaks() -> list[str]:
    """Lokasi str(<exception>) yang bocor ke browser, cookie flash, atau activity_logs."""
    hits: list[str] = []
    for path in app_py_files():
        text = read_text(path)
        exc_names = exception_names(text)
        for pat in LEAK_PATTERNS:
            for m in pat.finditer(text):
                name = m.group(1)
                if exc_names is None:
                    if name not in FALLBACK_EXCEPTION_NAMES:
                        continue
                elif name not in exc_names:
                    continue
                hits.append("%s:%d" % (path.name, line_of(text, m.start())))
    return sorted(hits)


def block_after(lines: list[str], idx: int) -> list[str]:
    """Blok terindentasi yang mengikuti baris ke-idx (idx = baris except/try)."""
    base = len(lines[idx]) - len(lines[idx].lstrip())
    out: list[str] = []
    for line in lines[idx + 1:]:
        if not line.strip():
            out.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base:
            break
        out.append(line)
    return out


def find_line(lines: list[str], needle: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if needle in lines[i]:
            return i
    return -1


def section_error_honesty() -> None:
    section("SECTION 3 - KEJUJURAN ERROR HANDLING (parse statis app/*.py)")

    # BE-08 - str(e) bocor ke user / dipersistensi ke activity_logs.
    leaks = find_str_leaks()
    check(
        "BE-08 tidak ada bocor str(e) ke user atau activity_logs",
        not leaks,
        "%d lokasi bocor str(e) (target: 0) - %s" % (len(leaks), ", ".join(leaks)),
        known="BE-08",
    )

    # BE-01 - pemanggilan fungsi transaksi formula Bab 2 ditelan except, lalu
    # user tetap dapat cookie "berhasil diperbarui" (blok simpan formula di
    # app/products_routes.py; posisi baris dihitung saat runtime).
    # Blok formula dicari lewat pemanggilan fungsi transaksi, BUKAN lewat
    # hapus baris formula (mekanisme lama sudah dibuang).
    prod_path = APP_DIR / "products_routes.py"
    prod_lines = read_text(prod_path).splitlines()
    prod_text = "\n".join(prod_lines)
    rpc_idx = find_pattern_line(
        prod_text, r"supabase\.rpc\(\s*\"replace_product_formula\""
    )
    success_idx = -1
    for i in range(max(rpc_idx, 0), len(prod_lines)):
        if "log_activity(" in prod_lines[i] and (
            'outcome="failed"' not in "\n".join(prod_lines[i:i + 5])
        ):
            success_idx = i
            break
    be01_ok = False
    be01_detail = (
        "pemanggilan fungsi transaksi formula (replace_product_formula) "
        "tidak ditemukan di app/products_routes.py"
    )
    if rpc_idx >= 0 and success_idx > rpc_idx:
        region = "\n".join(prod_lines[rpc_idx:success_idx + 1])
        be01_ok = (
            "except Exception" in region
            and 'set_cookie("error_msg"' in region
        )
        if not be01_ok:
            be01_detail = (
                "blok fungsi transaksi formula tidak punya except Exception "
                "dan/atau set_cookie error_msg (products_routes.py:%d)"
                % (rpc_idx + 1)
            )
    check(
        "BE-01 kegagalan simpan formula tidak dilaporkan sebagai sukses",
        be01_ok,
        be01_detail,
        known="BE-01",
    )

    # BE-02 / BE-03 - insert & update batch bahan baku tidak set error_msg.
    rm_path = APP_DIR / "raw_materials_routes.py"
    rm_lines = read_text(rm_path).splitlines()

    def batch_failure_reported(needle: str, label: str) -> tuple[bool, str]:
        idx = find_line(rm_lines, needle)
        if idx < 0:
            return False, "%s: pemanggilan %s tidak ditemukan" % (label, needle)
        exc_idx = next(
            (i for i in range(idx, min(idx + 40, len(rm_lines)))
             if rm_lines[i].strip().startswith("except Exception")),
            -1,
        )
        if exc_idx < 0:
            return False, (
                "%s: tidak ada except Exception setelah %s (raw_materials_routes.py:%d)"
                % (label, needle, idx + 1)
            )
        handler = "\n".join(block_after(rm_lines, exc_idx))
        ok = 'set_cookie("error_msg"' in handler or "raise" in handler
        return ok, "%s: handler gagal (raw_materials_routes.py:%d) tidak set error_msg" % (
            label, exc_idx + 1)

    be02_ok, be02_detail = batch_failure_reported('raw_material_batches").insert(', "BE-02")
    check(
        "BE-02 kegagalan insert batch bahan baku dilaporkan ke user",
        be02_ok,
        be02_detail,
        known="BE-02",
    )

    be03_ok, be03_detail = batch_failure_reported('raw_material_batches").update(', "BE-03")
    check(
        "BE-03 kegagalan update batch bahan baku dilaporkan ke user",
        be03_ok,
        be03_detail,
        known="BE-03",
    )

    # BE-21 - cookie warning_msg harus dibaca minimal satu template.
    readers = []
    for path in template_files():
        if "warning_msg" in read_text(path):
            readers.append(path.name)
    warn_idx = find_line(prod_lines, 'set_cookie("warning_msg"')
    check(
        "BE-21 cookie warning_msg dirender minimal satu template",
        bool(readers),
        ("tidak ada template yang membaca warning_msg "
         "(produsennya products_routes.py:%d)" % (warn_idx + 1))
        if warn_idx >= 0
        else "tidak ada template yang membaca warning_msg "
             "(produsennya tidak ditemukan di app/products_routes.py)",
        known="BE-21",
    )


# ---------------------------------------------------------------------------
# Section 4 - Dead code & duplikasi
# ---------------------------------------------------------------------------
def section_dead_code() -> None:
    section("SECTION 4 - DEAD CODE & DUPILIKASI (parse statis app/*.py)")

    # SEC-02 / BE-07 - assert_same_tenant harus punya call site di app/.
    call_sites = []
    for path in app_py_files():
        if path.name == "security.py":
            continue
        text = read_text(path)
        for m in re.finditer(r"\bassert_same_tenant\b", text):
            call_sites.append("%s:%d" % (path.name, line_of(text, m.start())))
    check(
        "SEC-02 / BE-07 assert_same_tenant dipakai di route mutating",
        bool(call_sites),
        "0 call site di app/ (helper app/security.py:9 masih dead code produksi)"
        if not call_sites
        else "call site: %s" % ", ".join(call_sites),
        known="SEC-02",
    )

    # BE-04 - .single() di luar try -> HTTP 500 saat baris tidak ada.
    # Dipakai AST supaya tahan geser baris: yang dicek adalah panggilan
    # di dalam blok try/except, bukan nomor baris.
    rm_path = APP_DIR / "raw_materials_routes.py"
    rm_text = read_text(rm_path)
    try:
        tree = ast.parse(rm_text)
    except SyntaxError as exc:
        check(
            "BE-04 tidak ada .single() di luar try pada handler POST raw_materials (AST-based)",
            False,
            "gagal parse AST app/raw_materials_routes.py: %s" % exc,
        )
    else:
        guarded: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for stmt in list(node.body) + list(node.handlers):
                    guarded.append((stmt.lineno, stmt.end_lineno or stmt.lineno))
        unguarded: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "single"):
                continue
            ln = node.lineno
            if not any(lo <= ln <= hi for lo, hi in guarded):
                unguarded.append(ln)
        unguarded.sort()
        check(
            "BE-04 tidak ada .single() di luar try pada handler POST raw_materials (AST-based)",
            not unguarded,
            "%d pemanggilan .single() tanpa try/except (baris %s) -> HTTP 500, bukan 'tidak ditemukan'"
            % (len(unguarded), ", ".join(str(x) for x in unguarded)),
            known="BE-04",
        )

    # Duplikasi - compute_status_na() dua kali berturut-turut.
    dash_path = APP_DIR / "dashboard_routes.py"
    dash_calls = [
        " ".join(line.split())
        for line in read_text(dash_path).splitlines()
        if "compute_status_na(" in line and not line.strip().startswith("def ")
    ]
    dup_pairs = [
        (dash_calls[i], dash_calls[i + 1])
        for i in range(len(dash_calls) - 1)
        if dash_calls[i] == dash_calls[i + 1]
    ]
    check(
        "DUPL-01 tidak ada compute_status_na() ganda berturut-turut (dashboard_routes.py:177-178)",
        not dup_pairs,
        "%d pasangan panggilan identik berturut-turut" % len(dup_pairs),
        known="DUPL-01",
    )

    # SEC-18 - artefak teks sebelum blok extends di brands.html.
    brands = read_text(TPL_DIR / "brands.html")
    first_line = next((l for l in brands.splitlines() if l.strip()), "")
    check(
        "SEC-18 brands.html bersih dari artefak teks sebelum extends (brands.html:1)",
        "omniroute" not in first_line,
        "baris pertama brands.html masih memuat 'omniroute'",
        known="SEC-18",
    )

# ---------------------------------------------------------------------------
# Section 5 - Invarian template & escaping
# ---------------------------------------------------------------------------
SAFE_ALLOWLIST = {
    ("notes.html", "n.body_html"),
    ("notes.html", "n.completion_note_html"),
    ("raw_materials.html", "tojson"),
    ("finished_spec_form.html", "tojson"),
}

DANGEROUS_JS = ("eval(", "new Function(", "document.write(", "insertAdjacentHTML(", "outerHTML")


def section_templates() -> None:
    section("SECTION 5 - INVARIAN TEMPLATE & ESCAPING (parse statis templates + static)")

    # Autoescape global harus tetap menyala.
    offenders = []
    for path in template_files():
        text = strip_jinja_comments(read_text(path))
        if re.search(r"\{%-?\s*autoescape\s+false\s*-?%\}", text):
            offenders.append(path.name)
    check(
        "XSS-01 tidak ada blok autoescape false di template",
        not offenders,
        ("autoescape false dipakai di: %s" % ", ".join(offenders))
        if offenders
        else "0 autoescape false di seluruh template",
    )

    # | safe hanya boleh di allowlist (4 lokasi terverifikasi aman oleh audit).
    unsafe = []
    safe_hits = 0
    for path in template_files():
        text = strip_jinja_comments(read_text(path))
        for i, line in enumerate(text.splitlines(), start=1):
            if not re.search(r"\|\s*safe\b", line):
                continue
            safe_hits += 1
            allowed = any(
                fname == path.name and frag in line
                for (fname, frag) in SAFE_ALLOWLIST
            )
            if not allowed:
                unsafe.append("%s:%d" % (path.name, i))
    check(
        "XSS-02 setiap filter safe ada di allowlist terverifikasi (notes/raw_materials/finished_spec)",
        not unsafe,
        ("filter safe di luar allowlist: %s" % ", ".join(unsafe))
        if unsafe
        else "%d pemakaian filter safe, semuanya di allowlist" % safe_hits,
    )

    # SEC-14 - helper escaping harus satu global, bukan 4 implementasi terpisah.
    esc_defs: list[str] = []
    esc_re = re.compile(r"function\s+((?:um)?[Ee]scapeHtml\w*)\s*\(")
    for path in template_files() + static_files():
        text = strip_jinja_comments(read_text(path))
        for m in esc_re.finditer(text):
            esc_defs.append("%s:%d (%s)" % (path.name, line_of(text, m.start()), m.group(1)))
    check(
        "SEC-14 helper escaping tunggal (audit: 4 implementasi terpisah)",
        len(esc_defs) <= 1,
        "%d implementasi terpisah: %s | target: 1 helper global"
        % (len(esc_defs), ", ".join(esc_defs)),
        known="SEC-14",
    )

    # po_analytics.html harus mengirim data chart lewat script type application/json.
    pa = read_text(TPL_DIR / "po_analytics.html")
    pa_clean = strip_jinja_comments(pa)
    has_json_block = re.search(
        r"""<script[^>]*type=["']application/json["']""", pa_clean
    ) is not None
    has_tojson = "|tojson" in pa_clean.replace("| tojson", "|tojson")
    check(
        "XSS-03 po_analytics.html kirim data chart via script application/json + tojson",
        has_json_block and has_tojson,
        "json block: %s, tojson: %s" % (has_json_block, has_tojson),
    )

    # JS berbahaya di template + static.
    dangerous = []
    for path in template_files() + static_files():
        text = strip_jinja_comments(strip_js_comments(read_text(path)))
        for token in DANGEROUS_JS:
            if token in text:
                dangerous.append("%s (%s)" % (path.name, token))
    check(
        "XSS-04 tidak ada eval/new Function/document.write/insertAdjacentHTML/outerHTML",
        not dangerous,
        ("ditemukan: %s" % ", ".join(dangerous))
        if dangerous
        else "0 pola berbahaya di template dan app/static/*.js",
    )

    # Konvensi textContent-only untuk file yang sudah diaudit.
    for filename in ("lampiran.js", "po-analytics.js"):
        path = STATIC_DIR / filename
        if not path.exists():
            skip("XSS-05 %s 100%% textContent" % filename, "file %s tidak ada" % filename)
            continue
        code = strip_js_comments(read_text(path))
        count = code.count("innerHTML")
        check(
            "XSS-05 %s 100%% textContent (nol innerHTML)" % filename,
            count == 0,
            "%s masih punya %d pemakaian innerHTML" % (filename, count),
        )

    # Semua rujukan /static/... harus benar-benar ada di disk.
    broken = []
    refs = 0
    for path in template_files() + [APP_DIR / "main.py"]:
        text = read_text(path)
        for m in re.finditer(r"/static/[A-Za-z0-9_./-]+", text):
            ref = m.group(0)
            if "..." in ref:
                continue
            rel = ref[len("/static/"):].split("?")[0].split("#")[0]
            if not rel:
                continue
            refs += 1
            if not (STATIC_DIR / rel).exists():
                broken.append("%s -> %s" % (path.name, ref))
    check(
        "ASSET-01 semua rujukan /static/... resolve ke file yang ada",
        not broken,
        ("rusak: %s" % ", ".join(broken))
        if broken
        else "%d rujukan /static/... semuanya ada" % refs,
    )

    # FE-05 - link logout di sidebar harus menghentikan heartbeat.
    def logout_link_stops_heartbeat(path: Path) -> bool:
        lines = read_text(path).splitlines()
        for i, line in enumerate(lines):
            if "/logout" not in line:
                continue
            window = "\n".join(lines[max(0, i - 5):i + 12])
            if "stopPresenceHeartbeat" in window:
                return True
        return False

    base_ok = logout_link_stops_heartbeat(TPL_DIR / "base.html")
    sidebar_ok = logout_link_stops_heartbeat(TPL_DIR / "_sidebar.html")
    sidebar_js = STATIC_DIR / "sidebar.js"
    sidebar_js_ok = sidebar_js.exists() and "stopPresenceHeartbeat" in read_text(sidebar_js)
    check(
        "FE-05 link logout sidebar menghentikan heartbeat (base.html:169 vs _sidebar.html:115)",
        base_ok and (sidebar_ok or sidebar_js_ok),
        "base.html: %s, _sidebar.html: %s, sidebar.js: %s"
        % (base_ok, sidebar_ok, sidebar_js_ok),
        known="FE-05",
    )

    # U6 - doc-drift tabel entitas audit: setiap entity_type yang dipancarkan
    # kode harus ada di tabel entitas audit panduan (sekitar baris 699-713).
    # Nilai doc_type dinamis (company_docs_routes.py:124) dihitung dari
    # whitelist COMPANY_DOC_MAP (company_docs_routes.py:19-27) dan ditutupi
    # baris generik `{doc_type}` perusahaan -> tidak boleh jadi false positive.
    code_static, code_dynamic = collect_entity_types_from_code()
    dynamic_values = resolve_dynamic_entity_types(code_dynamic)
    documented, generic_doc_type_row = documented_entity_types()
    missing = sorted(
        value
        for value in (code_static | dynamic_values)
        if value not in documented
        and not (generic_doc_type_row and value in dynamic_values)
    )
    check(
        "U6 setiap entity_type di kode terdokumentasi di tabel entitas audit "
        "(panduan:699-713)",
        not missing,
        ("%d entity_type belum terdokumentasi: %s"
         % (len(missing), ", ".join(missing)))
        if missing
        else ("%d entity_type statis + %d nilai doc_type dinamis semuanya "
              "terdokumentasi" % (len(code_static), len(dynamic_values))),
        known="U6",
    )


# ---------------------------------------------------------------------------
# Section 6 - Invarian polling frontend
# ---------------------------------------------------------------------------
def resolve_interval(args_text: str, source: str) -> int | None:
    """Nilai milidetik dari argumen terakhir setInterval (literal atau konstanta)."""
    parts = split_top_level_args(args_text)
    if not parts:
        return None
    last = parts[-1].strip()
    if re.fullmatch(r"\d+", last):
        return int(last)
    m = re.fullmatch(r"([A-Za-z_]\w*)", last)
    if m:
        const = re.search(
            r"(?:var|let|const)\s+%s\s*=\s*(\d+)" % re.escape(m.group(1)), source
        )
        if const:
            return int(const.group(1))
    return None


def collect_intervals() -> list[tuple[str, int | None]]:
    """Kumpulkan semua setInterval di template + static beserta intervalnya."""
    found: list[tuple[str, int | None]] = []
    for path in template_files() + static_files():
        text = read_text(path)
        for m in re.finditer(r"\bsetInterval\s*\(", text):
            call = extract_call(text, m.end() - 1)
            args = call[1:-1] if call.startswith("(") else call
            found.append((
                "%s:%d" % (path.name, line_of(text, m.start())),
                resolve_interval(args, text),
            ))
    return found


def extract_js_function(text: str, name: str) -> str:
    """Ambil isi badan fungsi JS dengan nama tertentu (brace matching)."""
    m = re.search(r"function\s+%s\s*\(" % re.escape(name), text)
    if not m:
        return ""
    try:
        open_brace = text.index("{", m.end())
    except ValueError:
        return ""
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace:i + 1]
    return text[open_brace:]

def section_frontend() -> None:
    section("SECTION 6 - INVARIAN POLLING FRONTEND (parse statis template + static)")

    intervals = collect_intervals()
    values = [v for _, v in intervals]
    unknown = [loc for loc, v in intervals if v is None]

    # Tidak boleh ada interval ganda (audit 5.1: tidak ada interval ganda).
    seen: dict[int, list[str]] = {}
    for loc, value in intervals:
        if value is not None:
            seen.setdefault(value, []).append(loc)
    duplicates = {v: locs for v, locs in seen.items() if len(locs) > 1}
    check(
        "FRONTEND-01 tidak ada interval setInterval ganda",
        not duplicates and not unknown,
        ("interval ganda: %s" % "; ".join(
            "%d ms -> %s" % (v, ", ".join(l)) for v, l in duplicates.items()))
        if duplicates
        else (("interval tidak bisa diresolve: %s" % ", ".join(unknown)) if unknown else ""),
    )

    # Matriks interval harus sesuai audit: 30000/15000/1000 + heartbeat 25000.
    expected = {1000, 15000, 25000, 30000}
    actual = {v for v in values if v is not None}
    check(
        "FRONTEND-02 matriks interval polling sesuai audit (30000/15000/1000 + 25000)",
        actual == expected,
        "interval yang ditemukan: %s" % ", ".join(
            "%d ms (%s)" % (v, ", ".join(seen.get(v, []))) for v in sorted(actual)
        ),
    )

    # presence.js harus skip heartbeat saat tab hidden.
    presence_path = STATIC_DIR / "presence.js"
    presence_text = read_text(presence_path) if presence_path.exists() else ""
    presence_calls = [
        extract_call(presence_text, m.end() - 1)
        for m in re.finditer(r"\bsetInterval\s*\(", presence_text)
    ]
    heartbeat_call = next(
        (c for c in presence_calls if "HEARTBEAT_MS" in c),
        presence_calls[0] if presence_calls else "",
    )
    hidden_guard = "visibilityState" in heartbeat_call and "hidden" in heartbeat_call
    check(
        "FRONTEND-03 presence.js skip heartbeat saat tab hidden (presence.js:84)",
        hidden_guard,
        "guard document.visibilityState hidden tidak ada di blok setInterval heartbeat",
    )

    # presence.js harus menghentikan heartbeat saat 401.
    ping_body = extract_js_function(presence_text, "ping")
    handles_401 = "401" in ping_body and "stopHeartbeat" in ping_body
    check(
        "FRONTEND-04 presence.js stop heartbeat saat respons 401 (presence.js:43-47)",
        handles_401,
        "penanganan 401 di fungsi ping() tidak memanggil stopHeartbeat()",
    )

    # FE-06 - window.__adminPresenceInterval harus pernah di-assign.
    admin_users = read_text(TPL_DIR / "admin_users.html")
    assigned = re.search(r"window\.__adminPresenceInterval\s*=", admin_users) is not None
    check(
        "FE-06 window.__adminPresenceInterval di-assign di admin_users.html (base.html:44)",
        assigned,
        "hanya di-clear di base.html:44, tidak pernah di-assign di admin_users.html",
        known="FE-06",
    )

    # FE-07 - submit form login harus ditahan selama countdown lockout.
    login_text = read_text(TPL_DIR / "login.html")
    handler = extract_js_function(login_text, "handleLoginSubmit")
    blocks_submit = ("return false" in handler) or ("preventDefault" in handler)
    check(
        "FE-07 submit form login ditahan saat countdown lockout (login.html:64,128)",
        blocks_submit,
        "handleLoginSubmit() tidak pernah mengembalikan false / preventDefault",
        known="FE-07",
    )


# ---------------------------------------------------------------------------
# Section 7 - Unit pure-module (import opsional, tanpa DB)
# ---------------------------------------------------------------------------
def security_fail_open_covered() -> bool:
    """True kalau test_security_helpers.py sudah menguji fail-open + new_company."""
    path = TESTS_DIR / "test_security_helpers.py"
    if not path.exists():
        return False
    try:
        tree = ast.parse(read_text(path))
    except SyntaxError:
        return False

    # Analisis per fungsi: nama variabel bisa di-shadow antar fungsi, jadi
    # pemetaan "user tanpa perusahaan" harus dicek per scope fungsi.
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        none_company_names: set[str] = set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or not isinstance(node.value, ast.Dict):
                continue
            for k, v in zip(node.value.keys, node.value.values):
                if (
                    isinstance(k, ast.Constant) and k.value == "perusahaan"
                    and isinstance(v, ast.Constant) and v.value is None
                ):
                    none_company_names.add(target.id)

        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id == "assert_same_tenant"):
                continue
            if not node.args:
                continue
            user = node.args[0]
            fail_open_user = False
            if isinstance(user, ast.Dict):
                fail_open_user = any(
                    isinstance(k, ast.Constant) and k.value == "perusahaan"
                    and isinstance(v, ast.Constant) and v.value is None
                    for k, v in zip(user.keys, user.values)
                )
            elif isinstance(user, ast.Name):
                fail_open_user = user.id in none_company_names
            if fail_open_user and any(kw.arg == "new_company" for kw in node.keywords):
                return True
    return False


def section_pure_modules() -> None:
    section("SECTION 7 - UNIT PURE-MODULE (import lokal, tanpa DB/jaringan)")

    # --- SEC-02: helper tenant --------------------------------------------
    try:
        from app.security import assert_same_tenant  # noqa: PLC0415
    except Exception as exc:
        skip(
            "SEC-02 helper assert_same_tenant fail-open",
            "app.security tidak bisa diimpor: %s" % exc,
        )
    else:
        if security_fail_open_covered():
            skip(
                "SEC-02 helper assert_same_tenant fail-open",
                "sudah diuji di tests/test_security_helpers.py",
            )
        else:
            # Menempelkan perilaku fail-open yang MASIH berlaku: user tanpa
            # `perusahaan` lolos ke data badan hukum lain, termasuk saat
            # new_company justru bertentangan. Ini RISIKO DESAIN yang sengaja
            # dipin di sini, BUKAN end state yang desirable: mengubahnya jadi
            # penolakan = perubahan merusak, butuh migrasi user lama.
            fail_open = assert_same_tenant(
                {"role": "staff", "perusahaan": None},
                {"perusahaan": "PT Heka"},
                new_company="PT Erfi",
            )
            check(
                "SEC-02 helper assert_same_tenant fail-open untuk user tanpa perusahaan",
                fail_open is True,
                "perilaku fail-open berubah: user tanpa perusahaan kini ditolak (perlu migrasi user legacy)",
            )

    # --- Validasi upload PDF ----------------------------------------------
    up_path = TESTS_DIR / "test_upload_validation.py"
    up_text = read_text(up_path) if up_path.exists() else ""
    covers = {
        "kosong": 'b""' in up_text,
        "bukan PDF": ('b"not a pdf"' in up_text or 'b"XPDF"' in up_text),
        "lebih 10 MB": "MAX_PDF_SIZE + 1" in up_text,
    }
    if up_path.exists() and all(covers.values()):
        skip(
            "VAL-01 validate_pdf_bytes tolak non-PDF/kosong/lebih 10MB",
            "sudah diuji di tests/test_upload_validation.py",
        )
    else:
        try:
            from app.file_validation import MAX_PDF_SIZE, validate_pdf_bytes  # noqa: PLC0415
        except Exception as exc:
            skip(
                "VAL-01 validate_pdf_bytes tolak non-PDF/kosong/lebih 10MB",
                "app.file_validation tidak bisa diimpor: %s" % exc,
            )
        else:
            if not covers["kosong"]:
                check(
                    "VAL-01a validate_pdf_bytes menolak data kosong",
                    validate_pdf_bytes(b"", "doc.pdf") is not None,
                    "file kosong tidak ditolak",
                )
            if not covers["bukan PDF"]:
                check(
                    "VAL-01b validate_pdf_bytes menolak magic bytes non-PDF",
                    validate_pdf_bytes(b"not a pdf", "doc.pdf") is not None,
                    "file non-PDF tidak ditolak",
                )
            if not covers["lebih 10 MB"]:
                check(
                    "VAL-01c validate_pdf_bytes menolak file lebih dari 10 MB",
                    validate_pdf_bytes(
                        b"%PDF-1.4\n" + b"x" * (MAX_PDF_SIZE + 1), "doc.pdf"
                    ) is not None,
                    "file lebih dari 10 MB tidak ditolak",
                )

    # Celah nyata yang belum ditutup test_upload_validation.py: is_pdf_bytes.
    try:
        from app.file_validation import is_pdf_bytes  # noqa: PLC0415
    except Exception as exc:
        skip(
            "VAL-02 is_pdf_bytes mencerminkan validate_pdf_bytes",
            "app.file_validation tidak bisa diimpor: %s" % exc,
        )
    else:
        ok = (
            is_pdf_bytes(b"%PDF-1.4\n" + b"x" * 10) is True
            and is_pdf_bytes(b"") is False
            and is_pdf_bytes(b"not a pdf") is False
        )
        check(
            "VAL-02 is_pdf_bytes mencerminkan validate_pdf_bytes",
            ok,
            "is_pdf_bytes tidak konsisten dengan validate_pdf_bytes",
        )

    # --- parse_storage_url -------------------------------------------------
    ps_path = TESTS_DIR / "test_parse_storage_url.py"
    ps_text = read_text(ps_path) if ps_path.exists() else ""
    ps_covers = {
        "sampah": "(None, None)" in ps_text,
        "supabase": "storage/v1/object/public" in ps_text,
    }
    if ps_path.exists() and all(ps_covers.values()):
        skip(
            "STORAGE-01 parse_storage_url parsing URL Supabase dan input sampah",
            "sudah diuji di tests/test_parse_storage_url.py",
        )
    else:
        try:
            from app.object_store import parse_storage_url  # noqa: PLC0415
        except Exception as exc:
            skip(
                "STORAGE-01 parse_storage_url parsing URL Supabase dan input sampah",
                "app.object_store tidak bisa diimpor: %s" % exc,
            )
        else:
            if not ps_covers["sampah"]:
                garbage = parse_storage_url("https://contoh.example.com/bukan-storage.pdf", {})
                check(
                    "STORAGE-01a parse_storage_url mengembalikan (None, None) untuk input sampah",
                    garbage == (None, None),
                    "hasil: %r" % (garbage,),
                )
            if not ps_covers["supabase"]:
                url = (
                    "https://dytuprmoorvrugutozwv.supabase.co/storage/v1/object/public/"
                    "raw-material-docs/coa/coa_B1.pdf"
                )
                check(
                    "STORAGE-01b parse_storage_url parsing URL publik Supabase",
                    parse_storage_url(url, {}) == ("raw-material-docs", "coa/coa_B1.pdf"),
                    "URL publik Supabase tidak ter-parse jadi (bucket, path)",
                )


# ---------------------------------------------------------------------------
# Section 8 - Kontrak kejujuran hasil write (H3.1 - H3.5)
# ---------------------------------------------------------------------------
# Section ini mengunci perbaikan temuan audit H3.1-H3.5: aplikasi tidak boleh
# lagi melaporkan "berhasil" padahal ada write yang gagal, dan file yang baru
# diupload tidak boleh jadi yatim ketika database gagal menyimpan.
# Semua check di sini READ-ONLY (hanya membaca source code repo).
def section_write_honesty() -> None:
    """Kunci kontrak kejujuran hasil write (H3.1 - H3.5)."""

    def nows(text: str) -> str:
        """Buang seluruh whitespace supaya pencarian needle multi-baris tetap cocok."""
        return re.sub(r"\s+", "", text)

    # Cookie flash boleh ditulis satu baris atau multi-baris -> dinormalisasi dulu.
    cookie_error = nows('set_cookie("error_msg"')
    cookie_warning = nows('set_cookie("warning_msg"')

    prod_lines = read_text(APP_DIR / "products_routes.py").splitlines()
    prod_text = "\n".join(prod_lines)
    rm_lines = read_text(APP_DIR / "raw_materials_routes.py").splitlines()
    rm_text = "\n".join(rm_lines)
    sample_lines = read_text(APP_DIR / "sample_routes.py").splitlines()
    notes_lines = read_text(APP_DIR / "notes_routes.py").splitlines()
    notes_text = "\n".join(notes_lines)

    # --- H3.1a: helper validasi total 100% (murni, Decimal, toleransi) -----
    helper_idx = find_line(prod_lines, "def _validate_formula_total(")
    register_idx = find_line(prod_lines, "def register_products_routes(")
    h31a_ok = helper_idx >= 0 and (register_idx < 0 or helper_idx < register_idx)
    h31a_detail = "def _validate_formula_total() tidak ditemukan di app/products_routes.py"
    if h31a_ok:
        helper_body = "\n".join(prod_lines[helper_idx:register_idx])
        h31a_ok = (
            "Decimal(" in helper_body
            and 'FORMULA_TOTAL_TARGET = Decimal("100")' in prod_text
            and 'FORMULA_TOTAL_TOLERANCE = Decimal("0.0001")' in prod_text
        )
        if not h31a_ok:
            h31a_detail = (
                "helper _validate_formula_total tidak memakai Decimal + target 100 + toleransi 0.0001"
            )
    check(
        "H3.1a validasi total formula Bab 2 ada di server (helper murni, Decimal)",
        h31a_ok,
        h31a_detail,
    )

    # --- H3.1b: validasi total jalan SEBELUM update baris produk -------------
    val_idx = find_line(prod_lines, "_validate_formula_total(formula_rows_pct)")
    upd_idx = find_line(prod_lines, 'supabase.table("products").update(update_payload)')
    h31b_ok = val_idx >= 0 and upd_idx > val_idx
    check(
        "H3.1b validasi total formula dijalankan sebelum update baris produk",
        h31b_ok,
        "validasi total tidak ditemukan / dijalankan setelah update produk",
    )

    # --- H3.1c: baris formula TIDAK boleh ditulis langsung oleh aplikasi -
    # Baris formula Bab 2 sekarang hanya ditulis lewat fungsi transaksi
    # Postgres public.replace_product_formula(uuid, jsonb). Aplikasi tidak
    # boleh lagi menghapus atau menyisipkan baris formula secara langsung.
    prod_nows = nows(prod_text)
    prod_code = strip_python_comments(prod_text)
    rpc_call_nows = nows('supabase.rpc("replace_product_formula"')
    formula_rpc_only = (
        rpc_call_nows in prod_nows
        and 'product_formula_lines").delete()' not in prod_text
        and 'product_formula_lines").insert(' not in prod_text
    )
    if 'product_formula_lines").delete()' in prod_text:
        h31c_detail = "aplikasi masih menghapus baris formula secara langsung"
    elif 'product_formula_lines").insert(' in prod_text:
        h31c_detail = "aplikasi masih menyisipkan baris formula secara langsung"
    elif rpc_call_nows not in prod_nows:
        h31c_detail = "pemanggilan fungsi transaksi replace_product_formula tidak ditemukan"
    else:
        h31c_detail = "baris formula masih ditulis langsung oleh aplikasi"
    check(
        "H3.1c baris formula tidak ditulis langsung aplikasi (pakai fungsi transaksi)",
        formula_rpc_only,
        h31c_detail,
    )

    # --- H3.1d: mekanisme lama (snapshot + rollback) harus dibuang -------
    # Kode dibaca TANPA komentar: penjelasan "rollback" di dalam komentar
    # bukan mekanisme yang berjalan. Yang dicek adalah kode yang benar-benar
    # menjalankan snapshot/rollback manual di sisi aplikasi.
    sisa_mekanisme = [
        token for token in ("delete_done", "old_formula_rows", "rollback")
        if token in prod_code.lower()
    ]
    h31d_ok = not sisa_mekanisme and rpc_call_nows in prod_nows
    if sisa_mekanisme:
        h31d_detail = "mekanisme lama masih ada di kode aplikasi: %s" % ", ".join(sisa_mekanisme)
    else:
        h31d_detail = "pemanggilan fungsi transaksi replace_product_formula tidak ditemukan"
    check(
        "H3.1d mekanisme snapshot/rollback lama dibuang (tulis formula lewat fungsi transaksi)",
        h31d_ok,
        h31d_detail,
    )

    # --- H3.1e: kegagalan formula tidak boleh jatuh ke audit sukses ---------
    fail_idx = find_line(prod_lines, "if formula_failed:")
    fail_region = nows("\n".join(prod_lines[fail_idx:fail_idx + 25])) if fail_idx >= 0 else ""
    prod_logs = [
        i for i, l in enumerate(prod_lines)
        if 'log_activity(current_user, "update", "product"' in l
    ]
    ok_log_idx = -1
    for i in prod_logs:
        if 'outcome="failed"' not in "\n".join(prod_lines[i:i + 4]):
            ok_log_idx = i
    h31e_ok = (
        fail_idx >= 0
        and 'outcome="failed"' in fail_region
        and cookie_error in fail_region
        and nows("return response") in fail_region
        and ok_log_idx > fail_idx
    )
    check(
        "H3.1e kegagalan formula tidak jatuh ke audit sukses (partial success)",
        h31e_ok,
        "cabang 'if formula_failed:' tidak menulis audit outcome=failed + error_msg lalu return",
    )

    # --- H3.1f: pesan kegagalan formula harus jujur ----------------------
    # Pesan ke user wajib menyatakan komposisi tidak berubah, menyebut fungsi
    # transaksi yang dipakai, dan mengarahkan admin ke migration 010.
    h31f_ok = (
        "Komposisi produk tidak berubah" in prod_text
        and "replace_product_formula" in prod_text
        and "migration/010_replace_product_formula.sql" in prod_text
    )
    check(
        "H3.1f pesan kegagalan formula jujur: komposisi tidak berubah + arahkan ke migrasi 010",
        h31f_ok,
        "pesan kegagalan formula tidak menyebut komposisi tidak berubah / "
        "fungsi transaksi / migration 010",
    )

    # --- H3.2a: path upload batch WAJIB unik per operasi -------------------
    shared_paths = [
        p for p in (
            "coa/coa_{clean_batch}.pdf",
            "halal/halal_{clean_batch}.pdf",
            "qc-reports/qcreport_{clean_batch}.pdf",
        ) if p in rm_text
    ]
    h32a_ok = (
        not shared_paths
        and "coa/coa_{clean_batch}_{upload_uid}.pdf" in rm_text
        and "halal/halal_{clean_batch}_{upload_uid}.pdf" in rm_text
        and "qc-reports/qcreport_{clean_batch}_{upload_uid}.pdf" in rm_text
        and "uuid4().hex[:8]" in rm_text
    )
    check(
        "H3.2a path upload batch punya sufiks unik per operasi (tidak menimpa file lama)",
        h32a_ok,
        "masih ada path upload bersama antar batch: %s" % ", ".join(shared_paths)
        if shared_paths
        else "sufiks uuid4 per operasi tidak ditemukan di path upload batch",
    )

    # --- H3.2b: DB gagal saat tambah batch -> file diupload dibersihkan -----
    add_idx = find_line(rm_lines, 'raw_material_batches").insert(')
    add_region = nows("\n".join(rm_lines[add_idx:add_idx + 45])) if add_idx >= 0 else ""
    h32b_ok = (
        add_idx >= 0
        and "_cleanup_uploaded_objects(uploaded_paths)" in add_region
        and cookie_error in add_region
        and 'outcome="failed"' in add_region
    )
    check(
        "H3.2b gagal simpan batch: file diupload dibersihkan + flash error + audit failed",
        h32b_ok,
        "jalur gagal insert batch tidak membersihkan file / tidak set error_msg",
    )

    # --- H3.3a: DB gagal saat ubah batch -> file diupload dibersihkan -------
    upd_idx = find_line(rm_lines, 'raw_material_batches").update(update_data)')
    exc_idx = next(
        (i for i in range(upd_idx, min(upd_idx + 40, len(rm_lines)))
         if rm_lines[i].strip().startswith("except Exception")),
        -1,
    )
    edit_region = nows("\n".join(rm_lines[upd_idx:upd_idx + 60])) if upd_idx >= 0 else ""
    h33a_ok = (
        upd_idx >= 0
        and exc_idx > upd_idx
        and "_cleanup_uploaded_objects(uploaded_paths)" in edit_region
        and cookie_error in edit_region
        and 'outcome="failed"' in edit_region
    )
    check(
        "H3.3a gagal ubah batch: file diupload dibersihkan + flash error + audit failed",
        h33a_ok,
        "jalur gagal update batch tidak membersihkan file / tidak set error_msg",
    )

    # --- H3.3b: audit sukses update batch ditulis DI LUAR try database ------
    logs_after = [
        i for i in range(exc_idx + 1, min(exc_idx + 120, len(rm_lines)))
        if "log_activity(" in rm_lines[i]
    ] if exc_idx >= 0 else []
    ok_log = logs_after[1] if len(logs_after) > 1 else -1
    h33b_ok = False
    if ok_log >= 0:
        base_indent = len(rm_lines[exc_idx]) - len(rm_lines[exc_idx].lstrip())
        ok_indent = len(rm_lines[ok_log]) - len(rm_lines[ok_log].lstrip())
        h33b_ok = ok_indent <= base_indent
    check(
        "H3.3b audit sukses update batch ditulis di luar try database (bukan hilang saat gagal)",
        h33b_ok,
        "log_activity sukses masih berada di dalam blok except database",
    )

    # --- H3.4: hapus FSP gagal -> flash error, TANPA str(e) ke audit -------
    sample_idx = next(
        (i for i, l in enumerate(sample_lines)
         if 'print(f"Gagal hapus sample submission' in l),
        -1,
    )
    sample_region = nows("\n".join(sample_lines[sample_idx:sample_idx + 20])) if sample_idx >= 0 else ""
    h34_ok = (
        sample_idx >= 0
        and cookie_error in sample_region
        and nows("str(e)") not in sample_region
    )
    check(
        "H3.4 gagal hapus FSP: ada flash error_msg dan tidak ada str(e) di payload audit",
        h34_ok,
        "handler hapus FSP tidak set error_msg atau masih menaruh str(e) di activity_logs",
    )

    # --- H3.5a: simpan note / mention / audit dipisah ----------------------
    note_idx = find_line(notes_lines, 'ins = supabase.table("team_notes").insert(')
    note_region = nows("\n".join(notes_lines[note_idx:note_idx + 120])) if note_idx >= 0 else ""
    h35a_ok = (
        note_idx >= 0
        and note_region.count(nows("except Exception")) >= 3
        and cookie_error in note_region
        and cookie_warning in note_region
        and 'outcome="failed"' in note_region
        and nows('"success"') in note_region
    )
    check(
        "H3.5a simpan note / mention / audit dipisah jadi blok try terpisah",
        h35a_ok,
        "blok simpan note belum memisahkan note / mention / audit",
    )

    # --- H3.5b: kegagalan mention = warning, BUKAN error --------------------
    mention_idxs = [
        i for i, l in enumerate(notes_lines) if l.strip() == "if mention_failed:"
    ]
    mention_region = (
        nows("\n".join(notes_lines[mention_idxs[-1]:mention_idxs[-1] + 15])) if mention_idxs else ""
    )
    h35b_ok = (
        bool(mention_idxs)
        and cookie_warning in mention_region
        and cookie_error not in mention_region
    )
    check(
        "H3.5b kegagalan @mention memakai warning_msg (note tetap tersimpan, bukan error)",
        h35b_ok,
        "jalur gagal @mention tidak memakai warning_msg atau bahkan set error_msg",
    )

    # --- H3.5c: base.html merender + membersihkan warning_msg --------------
    base_text = read_text(TPL_DIR / "base.html")
    h35c_ok = (
        "request.cookies.get('warning_msg')" in base_text
        and "warning_msg=;" in base_text
        and "_warning_msg" in base_text
    )
    check(
        "H3.5c base.html merender warning_msg dan membersihkannya setelah tampil",
        h35c_ok,
        "warning_msg belum dirender / belum dibersihkan di base.html",
    )

    # Data migrasi 010 dibaca sekali di sini supaya dipakai bersama oleh
    # H3.6b (urutan kunci baris) dan MIG-010 (isi file migrasi).
    mig_path = ROOT / "migration" / "010_replace_product_formula.sql"
    mig_text = read_text(mig_path) if mig_path.exists() else ""
    app_refs = []
    app_rpc_refs = []
    for path in app_py_files():
        isi_app = read_text(path)
        if "replace_product_formula" in isi_app:
            app_refs.append(path.name)
        # Rujukan yang dihitung = pemanggilan RPC sungguhan, bukan sekadar
        # sebut nama fungsi di komentar atau di pesan.
        if re.search(r"rpc\(\s*\"replace_product_formula\"", isi_app):
            app_rpc_refs.append(path.name)

    # --- H3.6a: fungsi transaksi belum terpasang -> pesan jujur, tanpa
    #     jalur cadangan yang menulis baris formula secara langsung -------
    # Diskriminator wajib ada di DALAM fungsi klasifikasi (bukan hanya
    # disebut di docstring), dan pesan ke user wajib dibangun di fungsi
    # pembentuk pesan.
    klas_body = python_function_code(prod_text, "_classify_formula_rpc_error")
    klas_body_lower = klas_body.lower()
    klasifikasi_hilang = (
        bool(klas_body)
        and "pgrst202" in klas_body_lower
        and (
            "could not find the function" in klas_body_lower
            or "not found" in klas_body_lower
            or "does not exist" in klas_body_lower
        )
    )
    pesan_body = python_function_code(prod_text, "_formula_failure_message")
    h36a_ok = (
        klasifikasi_hilang
        and "migration/010_replace_product_formula.sql" in pesan_body
        and formula_rpc_only
    )
    check(
        "H3.6a fungsi transaksi belum ada: pesan arahkan ke migrasi 010, tanpa jalur tulis langsung",
        h36a_ok,
        "kegagalan fungsi transaksi belum diklasifikasikan / pesan tidak "
        "menunjuk migration 010 / masih ada jalur tulis baris formula langsung",
    )

    # --- H3.6b: kunci baris produk induk harus mendahului penghapusan ----
    mig_lock_m = re.search(
        r"FROM\s+public\.products\b[^;]*?FOR\s+UPDATE", mig_text, re.S
    )
    mig_lock_pos = mig_lock_m.start() if mig_lock_m else -1
    mig_del_pos = mig_text.find("DELETE FROM public.product_formula_lines")
    mig_lock_window = mig_lock_m.group(0) if mig_lock_m else ""
    h36b_ok = (
        mig_lock_pos >= 0
        and mig_del_pos >= 0
        and mig_lock_pos < mig_del_pos
        and "public.products" in mig_lock_window
        and "p_product_id" in mig_lock_window
    )
    check(
        "H3.6b kunci baris produk induk (FOR UPDATE) mendahuli penghapusan baris formula",
        h36b_ok,
        "kunci FOR UPDATE tidak ditemukan / tidak mendahuli penghapusan baris "
        "formula / tidak memakai p_product_id",
    )

    # --- H3.6c: batch tidak ditemukan harus dicek SEBELUM unggah file -----
    edit_start, edit_end = handler_region(
        rm_lines, '@app.post("/raw-materials/batches/edit/{batch_id}")'
    )
    edit_lines = rm_lines[edit_start:edit_end] if edit_start >= 0 else []
    edit_norm = nows("\n".join(edit_lines))
    preread_pos = edit_norm.find('.eq("id",batch_id).limit(1)')
    upload_pos = edit_norm.find("upload_pdf")
    preread_window = (
        edit_norm[max(0, preread_pos - 260):preread_pos] if preread_pos >= 0 else ""
    )
    h36c_ok = (
        edit_start >= 0
        and preread_pos >= 0
        and upload_pos >= 0
        and preread_pos < upload_pos
        and "raw_material_batches" in preread_window
        and 'outcome="rejected"' in edit_norm
    )
    check(
        "H3.6c batch tidak ditemukan: pre-read .limit(1) sebelum unggah file + cabang rejected",
        h36c_ok,
        "pre-read batch dengan .limit(1) tidak ditemukan / tidak mendahuli "
        "unggahan file / tidak ada cabang outcome rejected",
    )

    # --- H3.6d: batch hilang antara pre-read dan update harus jadi gagal ---
    update_chain = (
        'supabase.table("raw_material_batches").update(update_data)'
        '.eq("id",batch_id).select("id").execute()'
    )
    nol_baris_idx = next(
        (i for i, l in enumerate(edit_lines) if "if not affected_rows:" in l), -1
    )
    exc_idx = next(
        (
            i for i in range(nol_baris_idx + 1, len(edit_lines))
            if edit_lines[i].strip().startswith("except Exception")
        ),
        -1,
    ) if nol_baris_idx >= 0 else -1
    gagal_idx = next(
        (
            i for i in range(exc_idx + 1, len(edit_lines))
            if 'outcome="failed"' in edit_lines[i]
        ),
        -1,
    ) if exc_idx >= 0 else -1
    ada_raise = (
        any("raise " in edit_lines[i] for i in range(nol_baris_idx + 1, exc_idx))
        if 0 <= nol_baris_idx < exc_idx
        else False
    )
    h36d_ok = (
        update_chain in edit_norm
        and nol_baris_idx >= 0
        and ada_raise
        and gagal_idx > exc_idx
    )
    check(
        "H3.6d batch hilang saat update: UPDATE pakai .select(id) + cabang tanpa baris jadi kegagalan",
        h36d_ok,
        "rantai UPDATE tidak mengembalikan id / cabang tanpa baris terpengaruh "
        "tidak ada / tidak diperlakukan sebagai kegagalan",
    )

    # --- H3.6e: file lama yang masih dirujuk TIDAK boleh dihapus ---------
    ref_start, ref_end = python_function_span(rm_text, "_count_url_references")
    clean_start, clean_end = python_function_span(rm_text, "_cleanup_replaced_objects")
    ref_body = "\n".join(rm_lines[ref_start:ref_end]) if ref_start >= 0 else ""
    clean_body = "\n".join(rm_lines[clean_start:clean_end]) if clean_start >= 0 else ""
    clean_norm = nows(clean_body)
    pos_ref_bahan = clean_norm.find('_count_url_references("raw_material_batches"')
    pos_ref_produk = clean_norm.find('_count_url_references("product_batches"')
    pos_simpan = clean_norm.find("ifrefs>0:")
    pos_lewati = clean_norm.find("continue", pos_simpan) if pos_simpan >= 0 else -1
    pos_hapus = clean_norm.find("remove_from_all_backends")
    h36e_ok = (
        ref_start >= 0
        and clean_start >= 0
        and '.neq("id"' in ref_body
        and "exclude_id" in ref_body
        and pos_ref_bahan >= 0
        and pos_ref_produk >= 0
        and pos_simpan > pos_ref_produk
        and pos_lewati > pos_simpan
        and pos_hapus > pos_lewati
    )
    check(
        "H3.6e file lama yang masih dirujuk tidak dihapus (cek raw_material_batches + product_batches)",
        h36e_ok,
        "pemeriksaan referensi / cabang mempertahankan file lama / penghapusan "
        "objek tidak ditemukan",
    )

    # --- H3.6f: upload cepat harus membedakan tiga kondisi ---------------
    quick_start, quick_end = handler_region(
        rm_lines, '@app.post("/raw-materials/batches/{batch_id}/quick-upload-doc")'
    )
    quick_lines = rm_lines[quick_start:quick_end] if quick_start >= 0 else []
    quick_norm = nows("\n".join(quick_lines))
    idx_kosong = next(
        (i for i, l in enumerate(quick_lines) if l.strip() == "if not files_selected:"), -1
    )
    idx_gagal_semua = next(
        (i for i, l in enumerate(quick_lines) if l.strip() == "if not update_data:"), -1
    )
    win_kosong = (
        nows("\n".join(quick_lines[idx_kosong:idx_kosong + 15])) if idx_kosong >= 0 else ""
    )
    win_gagal_semua = (
        nows("\n".join(quick_lines[idx_gagal_semua:idx_gagal_semua + 30]))
        if idx_gagal_semua >= 0 else ""
    )
    idx_peringatan = next(
        (i for i, l in enumerate(quick_lines) if l.strip().startswith('"warning_msg"')), -1
    )
    win_peringatan = (
        nows("\n".join(quick_lines[max(0, idx_peringatan - 2):idx_peringatan + 8]))
        if idx_peringatan >= 0 else ""
    )
    h36f_ok = (
        idx_kosong >= 0
        and idx_gagal_semua >= 0
        and idx_kosong != idx_gagal_semua
        and "Tidakadafileyangdipilih." in win_kosong
        and 'outcome="rejected"' in win_kosong
        and "Semuafilegagaldiunggah." not in win_kosong
        and "Semuafilegagaldiunggah." in win_gagal_semua
        and "Tidakadadokumenyangtersimpan." in win_gagal_semua
        and 'outcome="failed"' in win_gagal_semua
        and "_cleanup_uploaded_objects(" in win_gagal_semua
        and "Tidakadafileyangdipilih." not in win_gagal_semua
        and 'set_cookie("warning_msg"' in quick_norm
        and '",".join(upload_errors)' in win_peringatan
    )
    check(
        "H3.6f upload cepat: tiga kondisi dibedakan (tidak ada file / semua gagal / sebagian)",
        h36f_ok,
        "cabang upload cepat tidak memisahkan kondisi tidak ada file, semua "
        "file gagal, dan sebagian file gagal",
    )

    # --- H3.6g: nilai outcome yang dipakai harus terbatas -----------------
    outcome_re = re.compile(r"""outcome\s*=\s*["']([^"']+)["']""")
    nilai_outcome = set(outcome_re.findall(rm_text))
    nilai_outcome |= set(outcome_re.findall(notes_text))
    ada_partial = bool(
        re.search(r"\bpartial\b", rm_text, re.IGNORECASE)
        or re.search(r"\bpartial\b", notes_text, re.IGNORECASE)
    )
    h36g_ok = (
        nilai_outcome == {"success", "rejected", "failed"}
        and "partial" not in nilai_outcome
        and not ada_partial
    )
    check(
        "H3.6g nilai outcome dibatasi success/rejected/failed (tanpa nilai partial)",
        h36g_ok,
        "nilai outcome yang dipakai: %s%s"
        % (", ".join(sorted(nilai_outcome)), " / ada nilai partial" if ada_partial else ""),
    )

    # --- H3.6h: sukses sebagian tetap ditulis sebagai success -------------
    idx_mention = next(
        (i for i, l in enumerate(notes_lines) if l.strip() == "if mention_failed:"), -1
    )
    win_mention = (
        nows("\n".join(notes_lines[idx_mention:idx_mention + 25])) if idx_mention >= 0 else ""
    )
    h36h_notes_ok = (
        idx_mention >= 0
        and '"field":"Mention"' in win_mention
        and 'outcome="success"' in win_mention
    )
    h36h_rm_ok = False
    for i, l in enumerate(quick_lines):
        if 'outcome="success"' not in l:
            continue
        j = i
        while j >= 0 and "log_activity(" not in quick_lines[j]:
            j -= 1
        if j < 0:
            continue
        blok = "\n".join(quick_lines[j:i + 2])
        m = re.search(r"changes=([A-Za-z_][A-Za-z0-9_]*)", blok)
        if not m:
            continue
        var = m.group(1)
        idx_var = next(
            (k for k in range(j, -1, -1) if var + ".append(" in quick_lines[k]), -1
        )
        if idx_var < 0:
            continue
        if "upload_errors" in "\n".join(quick_lines[idx_var:idx_var + 8]):
            h36h_rm_ok = True
            break
    h36h_ok = h36h_notes_ok and h36h_rm_ok
    check(
        "H3.6h sukses sebagian tetap outcome success dan rincian yang gagal disebut di changes",
        h36h_ok,
        "catatan tersimpan tapi @mention gagal tidak ditulis sebagai success, "
        "atau file yang gagal tidak disebut di changes",
    )

    # --- MIG-010: kontrak fungsi transaksi + status eksekusi terdokumentasi -----
    wajib_mig = [
        "abs(v_total - 100) > 0.0001",
        "v_pct < 0",
        r"^-?[0-9]+(\.[0-9]+)?$",
        "REVOKE ALL ON FUNCTION public.replace_product_formula(uuid, jsonb) FROM PUBLIC;",
        "REVOKE ALL ON FUNCTION public.replace_product_formula(uuid, jsonb) FROM anon, authenticated;",
        "GRANT EXECUTE ON FUNCTION public.replace_product_formula(uuid, jsonb) TO service_role;",
        "STATUS EKSEKUSI",
        "DELETE FROM public.product_formula_lines",
        "DROP FUNCTION IF EXISTS public.replace_product_formula(uuid, jsonb);",
        "CREATE FUNCTION public.replace_product_formula(",
    ]
    mig_hilang = [w for w in wajib_mig if w not in mig_text]
    mig_pakai_lama = "CREATE OR REPLACE FUNCTION public.replace_product_formula" in mig_text
    # Kunci baris produk induk harus benar-benar ada sebagai pernyataan
    # SQL (bukan sekadar sebutan di komentar kepala file).
    mig_pakai_kunci = bool(
        re.search(r"FROM\s+public\.products\b[^;]*?FOR\s+UPDATE", mig_text, re.S)
    )
    h_mig_ok = (
        mig_path.exists()
        and not mig_hilang
        and mig_pakai_kunci
        and not mig_pakai_lama
        and "products_routes.py" in app_rpc_refs
    )
    mig_catatan = []
    if not mig_path.exists():
        mig_catatan.append("file migrasi 010 tidak ditemukan")
    if mig_hilang:
        mig_catatan.append("isi wajib hilang: %s" % ", ".join(mig_hilang))
    if mig_pakai_lama:
        mig_catatan.append("masih memakai CREATE OR REPLACE FUNCTION")
    if not mig_pakai_kunci:
        mig_catatan.append("tidak ada kunci FOR UPDATE pada baris produk induk")
    if "products_routes.py" not in app_rpc_refs:
        mig_catatan.append(
            "aplikasi tidak memanggil fungsi transaksi lewat RPC (ditemukan: %s)"
            % (", ".join(app_rpc_refs) or "tidak ada")
        )
    check(
        "MIG-010 migration/010_replace_product_formula.sql di-harden, status eksekusi terdokumentasi, dipakai lewat fungsi transaksi",
        h_mig_ok,
        "; ".join(mig_catatan) or "isi migrasi 010 lengkap dan aplikasi memakainya",
    )

    add_start, add_end = handler_region(rm_lines, '@app.post("/raw-materials/batches/add")')

    # --- H3.7a: upload cepat ambil URL lama + cleanup setelah update sukses -
    # Pre-read harus mengambil tiga kolom URL dokumen, dan objek lama yang
    # digantikan harus dibersihkan SETELAH update terkonfirmasi sukses.
    idx_preread_q = next(
        (i for i, l in enumerate(quick_lines) if ".select(" in l), -1
    )
    jendela_preread_q = (
        "\n".join(quick_lines[idx_preread_q:idx_preread_q + 6])
        if idx_preread_q >= 0
        else ""
    )
    idx_update_q = next(
        (
            i for i, l in enumerate(quick_lines)
            if 'raw_material_batches").update(update_data)' in l
        ),
        -1,
    )
    idx_cleanup_q = next(
        (i for i, l in enumerate(quick_lines) if "_cleanup_replaced_objects(" in l),
        -1,
    )
    sites_cleanup_q = handler_call_sites(
        rm_text,
        "/raw-materials/batches/{batch_id}/quick-upload-doc",
        "_cleanup_replaced_objects",
    )
    h37a_ok = (
        idx_preread_q >= 0
        and "coa_file_url" in jendela_preread_q
        and "halal_batch_file_url" in jendela_preread_q
        and "qc_report_file_url" in jendela_preread_q
        and "old_doc_urls" in "\n".join(quick_lines)
        and idx_update_q >= 0
        and idx_cleanup_q > idx_update_q
        and any(not di_except for _, di_except, _ in sites_cleanup_q)
    )
    check(
        "H3.7a upload cepat: pre-read ambil tiga kolom URL lama + cleanup objek lama setelah update sukses",
        h37a_ok,
        "pre-read upload cepat tidak mengambil tiga kolom URL lama / cleanup "
        "objek lama tidak dipanggil di jalur sukses",
    )

    # --- H3.7b: objek lama yang masih dirujuk tidak boleh dihapus ---------
    # Pemeriksaan referensi harus menutup dua tabel (raw_material_batches dan
    # product_batches) dan semua kolom dokumen, dan harus mendahului
    # penghapusan objek.
    label_dokumen = set(module_dict_keys(rm_text, "DOC_FIELD_LABELS"))
    isi_cleanup = (
        "\n".join(rm_lines[clean_start:clean_end]) if clean_start >= 0 else ""
    )
    isi_ref = "\n".join(rm_lines[ref_start:ref_end]) if ref_start >= 0 else ""
    norma_cleanup = nows(isi_cleanup)
    pos_ref_bahan = norma_cleanup.find('_count_url_references("raw_material_batches"')
    pos_ref_produk = norma_cleanup.find('_count_url_references("product_batches"')
    pos_simpan = norma_cleanup.find("ifrefs>0:")
    pos_lewati = norma_cleanup.find("continue", pos_simpan) if pos_simpan >= 0 else -1
    pos_hapus = norma_cleanup.find("remove_from_all_backends")
    pos_gagal_cek = norma_cleanup.find("ifref_error:")
    pos_lewati_gagal = (
        norma_cleanup.find("continue", pos_gagal_cek) if pos_gagal_cek >= 0 else -1
    )
    h37b_ok = (
        ref_start >= 0
        and clean_start >= 0
        and label_dokumen
        == {"coa_file_url", "halal_batch_file_url", "qc_report_file_url"}
        and "DOC_FIELD_LABELS" in isi_cleanup
        and ".in_(column, [url])" in isi_ref
        and pos_ref_bahan >= 0
        and pos_ref_produk >= 0
        and 'column=="coa_file_url"' in norma_cleanup
        and pos_simpan > pos_ref_produk
        and pos_lewati > pos_simpan
        and pos_hapus > pos_lewati
        and pos_gagal_cek >= 0
        and pos_lewati_gagal > pos_gagal_cek
        and pos_lewati_gagal < pos_hapus
    )
    check(
        "H3.7b objek lama yang masih dirujuk tidak dihapus; cek referensi raw_material_batches + product_batches",
        h37b_ok,
        "pemeriksaan referensi tidak menutup semua kolom dokumen / tabel "
        "product_batches / cabang 'masih dirujuk' atau 'cek gagal' tidak "
        "mendahului penghapusan objek",
    )

    # --- H3.7c: respons hilang tapi URL baru ditemukan -> file dipertahankan -
    isi_rek = python_function_body(rm_text, "_rekonsiliasi_setelah_gagal")
    isi_balas = python_function_body(rm_text, "_balas_gagal_ambigu")
    tambah_region = nows("\n".join(rm_lines[add_start:add_end])) if add_start >= 0 else ""
    ubah_region = nows("\n".join(rm_lines[edit_start:edit_end])) if edit_start >= 0 else ""
    cepat_region = nows("\n".join(quick_lines))
    h37c_ok = (
        "REKONSILIASI_DITEMUKAN" in isi_rek
        and '"outcome": "success"' in isi_rek
        and "respons database tidak diterima" in isi_rek
        and "terverifikasi ada" in isi_rek
        and "dipertahankan" in isi_rek
        and 'outcome="success"' in isi_balas
        and 'set_cookie("success_msg"' in isi_balas
        and "_cleanup_uploaded_objects" not in isi_balas
        and all(
            "_rekonsiliasi_setelah_gagal(" in reg
            and "_balas_gagal_ambigu(" in reg
            for reg in (tambah_region, ubah_region, cepat_region)
        )
    )
    check(
        "H3.7c commit database dengan respons hilang: URL baru ditemukan -> file dipertahankan, outcome success",
        h37c_ok,
        "jalur 'respons hilang tapi URL ditemukan' tidak menulis outcome "
        "success / tidak mempertahankan file / tidak dipakai di ketiga handler",
    )

    # --- H3.7d: query rekonsiliasi gagal -> file dipertahankan, path dicatat -
    h37d_ok = (
        "REKONSILIASI_GAGAL_CEK" in isi_rek
        and "query rekonsiliasi juga gagal" in isi_rek
        and "hasil penyimpanan belum pasti" in isi_rek
        and "rekonsiliasi manual" in isi_rek
        and "daftar_path" in isi_rek
        and "uploaded_paths" in isi_rek
        and 'outcome="failed"' in isi_balas
        and 'set_cookie("error_msg"' in isi_balas
        and "_cleanup_uploaded_objects" not in isi_balas
    )
    check(
        "H3.7d query rekonsiliasi gagal: file dipertahankan, hasil belum pasti, path dicatat",
        h37d_ok,
        "kegagalan query rekonsiliasi tidak dilaporkan sebagai belum pasti / "
        "path objek tidak dicatat / file ikut dihapus",
    )

    # --- H3.7e: hasil query kosong BUKAN bukti pasti gagal -----------------
    isi_rek_url = python_function_body(rm_text, "_rekonsiliasi_url_baru")
    h37e_ok = (
        "REKONSILIASI_TIDAK_DITEMUKAN" in isi_rek_url
        and "URL baru belum ditemukan di database" in isi_rek
        and '"status": "belum_pasti"' in isi_rek
        and '"outcome": "failed"' in isi_rek
        and "_cleanup_uploaded_objects" not in isi_rek
        and "_cleanup_uploaded_objects" not in isi_balas
    )
    check(
        "H3.7e hasil query kosong setelah timeout bukan bukti pasti gagal: file dipertahankan",
        h37e_ok,
        "hasil rekonsiliasi yang kosong diperlakukan sebagai bukti gagal / "
        "file baru ikut dihapus",
    )

    # --- H3.7f: kegagalan PASTI -> file baru dihapus, outcome failed -------
    isi_klasifikasi = python_function_body(rm_text, "_klasifikasi_kegagalan_db")
    h37f_ok = (
        all(
            '_cleanup_uploaded_objects(uploaded_paths)' in reg
            and 'outcome="failed"' in reg
            and 'set_cookie("error_msg"' in reg
            for reg in (tambah_region, ubah_region, cepat_region)
        )
        and "isinstance(exc, (APIError, HTTPStatusError))" in isi_klasifikasi
        and "KEGAGALAN_PASTI_DITOLAK" in isi_klasifikasi
        and "str(exc)" not in isi_klasifikasi
    )
    check(
        "H3.7f kegagalan pasti: file baru dihapus, outcome failed (klasifikasi dari tipe exception)",
        h37f_ok,
        "kegagalan pasti tidak menghapus file baru / outcome tidak failed / "
        "klasifikasi tidak memakai tipe exception",
    )

    # --- H3.7f2: 5xx dari gateway (body bukan JSON PostgREST) = AMBIGU -----
    # Dieksekusi sungguhan di namespace terisolasi dengan exception pengganti
    # (tanpa mengimpor app, karena import app membuka client Supabase).
    class _APIErrorStub(Exception):
        def __init__(self, code):
            super().__init__(f"code={code}")
            self.code = code

    class _ResponseStub:
        def __init__(self, status_code):
            self.status_code = status_code

    class _HTTPStatusErrorStub(Exception):
        def __init__(self, status_code):
            super().__init__(f"status={status_code}")
            self.response = _ResponseStub(status_code)

    ns_klasifikasi = {
        "APIError": _APIErrorStub,
        "HTTPStatusError": _HTTPStatusErrorStub,
        "KEGAGALAN_PASTI_DITOLAK": "pasti_ditolak",
        "KEGAGALAN_AMBIGU": "ambigu",
    }
    try:
        # Ambil sumber fungsi persis lewat ast (python_function_code
        # mengembalikan seluruh modul untuk fungsi ber-docstring).
        pohon_rm = ast.parse(rm_text)
        for nama_fn in ("_status_http_dari_exception", "_klasifikasi_kegagalan_db"):
            node_fn = next(
                n for n in pohon_rm.body
                if isinstance(n, ast.FunctionDef) and n.name == nama_fn
            )
            exec(ast.get_source_segment(rm_text, node_fn), ns_klasifikasi)
        klasifikasi_fn = ns_klasifikasi["_klasifikasi_kegagalan_db"]
        kasus_klasifikasi = [
            (_APIErrorStub("23505"), "pasti_ditolak"),       # SQLSTATE: rollback
            (_APIErrorStub("PGRST116"), "pasti_ditolak"),    # error PostgREST asli
            (_APIErrorStub("57014"), "pasti_ditolak"),       # statement timeout: rollback
            (_APIErrorStub(400), "pasti_ditolak"),           # 4xx generik
            (_APIErrorStub(429), "pasti_ditolak"),
            (_APIErrorStub(502), "ambigu"),                  # gateway, body bukan JSON
            (_APIErrorStub(504), "ambigu"),
            (_APIErrorStub("503"), "ambigu"),
            (_HTTPStatusErrorStub(404), "pasti_ditolak"),
            (_HTTPStatusErrorStub(504), "ambigu"),
            (TimeoutError("read timeout"), "ambigu"),        # transport
        ]
        h37f2_ok = all(klasifikasi_fn(exc) == harapan for exc, harapan in kasus_klasifikasi)
    except Exception:
        h37f2_ok = False
    check(
        "H3.7f2 klasifikasi: 5xx dari gateway dan timeout ambigu, error PostgREST asli dan 4xx pasti ditolak",
        h37f2_ok,
        "5xx gateway masih dianggap pasti ditolak (file baru bisa terhapus padahal "
        "database sudah commit) / error PostgREST asli salah diklasifikasi",
    )

    # --- H3.7g: tidak ada jalur ambigu yang langsung menghapus objek baru --
    sites_cleanup = module_call_sites(rm_text, "_cleanup_uploaded_objects")
    sites_dalam_except = [s for s in sites_cleanup if s[1]]
    h37g_ok = (
        bool(sites_cleanup)
        and len(sites_dalam_except) >= 3
        and all(
            guard and "KEGAGALAN_PASTI_DITOLAK" in guard
            for _, _, guard in sites_dalam_except
        )
        and all(
            bool(guard)
            for _, di_except, guard in sites_cleanup
            if not di_except
        )
    )
    check(
        "H3.7g tidak ada jalur exception ambigu yang langsung menghapus objek baru",
        h37g_ok,
        "ada call site _cleanup_uploaded_objects yang tidak berada di bawah "
        "penentu 'kegagalan pasti'",
    )

    # --- H3.7h: upload cepat wajib cek jumlah baris yang terpengaruh ----
    # Rantai UPDATE upload cepat harus mengembalikan baris yang terpengaruh
    # (.select("id")) dan jumlah baris itu dibaca dari respons. Kalau tidak
    # ada baris yang terpengaruh (batch hilang di antara pre-read dan
    # update), tulisan tidak terjadi -> harus diklasifikasikan sebagai
    # kegagalan pasti, bukan dilaporkan sukses.
    quick_teks = "\n".join(quick_lines)
    chain_quick = (
        'supabase.table("raw_material_batches").update(update_data)'
        '.eq("id",batch_id).select("id").execute()'
    )
    idx_affected_quick = next(
        (
            i for i, l in enumerate(quick_lines)
            if "affected_rows" in l and ".data" in l
        ),
        -1,
    )
    idx_nol_baris_quick = next(
        (i for i, l in enumerate(quick_lines) if "if not affected_rows:" in l), -1
    )
    idx_raise_quick = next(
        (
            i for i, l in enumerate(quick_lines)
            if "raise _BatchUpdateAffectedNoRow(" in l
        ),
        -1,
    )
    idx_sentinel_quick = next(
        (
            i for i, l in enumerate(quick_lines)
            if "isinstance(e, _BatchUpdateAffectedNoRow)" in l
        ),
        -1,
    )
    sites_ganti_quick = handler_call_sites(
        rm_text,
        "/raw-materials/batches/{batch_id}/quick-upload-doc",
        "_cleanup_replaced_objects",
    )
    sites_baru_quick = handler_call_sites(
        rm_text,
        "/raw-materials/batches/{batch_id}/quick-upload-doc",
        "_cleanup_uploaded_objects",
    )
    h37h_ok = (
        # Lokasi route wajib ditemukan: kalau route upload cepat hilang atau
        # berubah nama, check ini harus FAIL - bukan lolos diam-diam
        # karena bagian yang dibaca kosong.
        quick_start >= 0
        # 1. rantai UPDATE mengembalikan baris yang terpengaruh
        and chain_quick in quick_norm
        # 2. jumlah baris terpengaruh dibaca dari respons
        and idx_affected_quick >= 0
        # 3. cabang tanpa baris melempar penanda exception yang sama dengan route ubah batch
        and idx_nol_baris_quick >= 0
        and idx_raise_quick >= 0
        and "_BatchUpdateAffectedNoRow" in quick_teks
        # 4. penanda exception dikenali dan diklasifikasikan sebagai kegagalan pasti
        and idx_sentinel_quick >= 0
        and "KEGAGALAN_PASTI_DITOLAK" in quick_teks
        # 5. pesan yang jujur untuk kasus batch hilang
        and "Batch tidak ditemukan. Perubahan tidak disimpan." in quick_teks
        # 6. pembersihan objek lama hanya boleh jalan di jalur sukses
        and bool(sites_ganti_quick)
        and not any(di_except for _, di_except, _ in sites_ganti_quick)
        and any(
            guard and "KEGAGALAN_PASTI_DITOLAK" in guard
            for _, di_except, guard in sites_baru_quick
            if di_except
        )
    )
    check(
        "H3.7h upload cepat: jumlah baris terpengaruh dicek, batch hilang jadi kegagalan pasti",
        h37h_ok,
        "rantai UPDATE upload cepat tidak mengembalikan id / jumlah baris "
        "terpengaruh tidak dibaca dari respons / batch hilang tidak "
        "diklasifikasikan sebagai kegagalan pasti / pesan tidak jujur / "
        "pembersihan objek lama bisa jalan di jalur gagal",
    )

    # --- UNIT: helper validasi total 100% (murni, tanpa DB) ----------------
    try:
        from app.products_routes import _validate_formula_total  # noqa: PLC0415
    except Exception as exc:
        skip(
            "UNIT-01 helper _validate_formula_total menolak total != 100 & menerima total 100",
            "app.products_routes tidak bisa diimpor: %s" % exc,
        )
    else:
        unit_ok = (
            _validate_formula_total(["50", "50"])[0] is True
            and _validate_formula_total(["33.3333", "33.3333", "33.3334"])[0] is True
            and _validate_formula_total(["50", "40"])[0] is False
            and _validate_formula_total(["abc", "100"])[0] is False
            and _validate_formula_total(["-1", "101"])[0] is False
            and _validate_formula_total([])[0] is True
        )
        check(
            "UNIT-01 helper _validate_formula_total menolak total != 100 & menerima total 100",
            unit_ok,
            "perilaku _validate_formula_total tidak sesuai kontrak (100 harus lolos, selain itu ditolak)",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regresi audit codebase DIP Automation (2026-10-21).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Perlakukan temuan KNOWN sebagai FAIL (untuk CI setelah perbaikan selesai).",
    )
    args = parser.parse_args(argv)

    print("Regresi audit codebase DIP Automation - baseline 2026-10-21")
    print("READ-ONLY: tanpa database, tanpa jaringan, tanpa membaca .env*")

    section_routes()
    section_security_headers()
    section_error_honesty()
    section_dead_code()
    section_templates()
    section_frontend()
    section_pure_modules()
    section_write_honesty()

    counts = {"PASS": 0, "KNOWN": 0, "FAIL": 0, "SKIP": 0}
    for status, _, _ in RESULTS:
        counts[status] = counts.get(status, 0) + 1

    print()
    print("=" * 74)
    print("RINGKASAN")
    print("=" * 74)
    print("  PASS  : %d" % counts["PASS"])
    print("  KNOWN : %d  (temuan audit yang belum diperbaiki)" % counts["KNOWN"])
    print("  FAIL  : %d" % counts["FAIL"])
    print("  SKIP  : %d" % counts["SKIP"])

    fails = [r for r in RESULTS if r[0] == "FAIL"]
    if fails:
        print()
        print("Temuan FAIL (wajib beres):")
        for _, name, detail in fails:
            print("  - %s - %s" % (name, detail))

    knowns = [r for r in RESULTS if r[0] == "KNOWN"]
    if knowns and args.strict:
        print()
        print("Temuan KNOWN (diperlakukan sebagai FAIL karena --strict):")
        for _, name, detail in knowns:
            print("  - %s - %s" % (name, detail))

    hard_fail = bool(fails) or (args.strict and bool(knowns))
    print()
    if hard_fail:
        print("Exit code 1 (ada FAIL%s)." % (" atau KNOWN dengan --strict" if args.strict else ""))
    else:
        print("Exit code 0 (tidak ada FAIL).")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
