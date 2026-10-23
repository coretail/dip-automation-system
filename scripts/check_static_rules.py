"""Static checks for recurring FastAPI, Jinja, HTML, and JavaScript mistakes.

The checker is intentionally dependency-light so it can run before the full test
suite.  It imports the application with safe dummy settings, but does not make
network calls.  Supabase/R2 clients must remain lazy at import time.

Exit code 0 means all checks passed.  Any finding, including a missing Node.js
executable for inline JavaScript syntax checks, returns exit code 1.
"""
from __future__ import annotations

import ast
import html.parser
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TEMPLATES_DIR = ROOT / "app" / "templates"


def _fail(findings: list[str], message: str) -> None:
    findings.append(message)


def _safe_import_app(findings: list[str]):
    """Import app.main while blocking network/client creation.

    CI must not need a live service merely to verify routes and templates.
    """
    dummy_env = {
        "SUPABASE_URL": "https://ci.invalid.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "ci-dummy-service-role-key",
        "SUPABASE_KEY": "ci-dummy-anon-key",
        "STORAGE_BACKEND": "supabase",
        "DIP_APP_ENV": "",
    }
    previous = {key: os.environ.get(key) for key in dummy_env}
    for key, value in dummy_env.items():
        os.environ[key] = value

    import socket
    import supabase as supabase_package
    import boto3
    import dotenv

    original_load_dotenv = dotenv.load_dotenv
    original_dotenv_values = dotenv.dotenv_values
    dotenv.load_dotenv = lambda *args, **kwargs: False
    dotenv.dotenv_values = lambda *args, **kwargs: {}
    original_socket = socket.socket
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    original_create = supabase_package.create_client
    original_boto3_client = boto3.client
    calls: list[str] = []

    def blocked_socket(*args, **kwargs):
        calls.append("socket.socket")
        raise AssertionError("network socket created while importing app.main")

    def blocked_create(*args, **kwargs):
        calls.append("supabase.create_client")
        raise AssertionError("Supabase client created while importing app.main")

    def blocked_boto3(*args, **kwargs):
        calls.append("boto3.client")
        raise AssertionError("R2 client created while importing app.main")

    socket.socket = blocked_socket
    socket.create_connection = blocked_socket
    socket.getaddrinfo = blocked_socket
    supabase_package.create_client = blocked_create
    boto3.client = blocked_boto3
    try:
        # Make repeated local runs deterministic without requiring a subprocess.
        for name in list(sys.modules):
            if name == "app.main" or name.startswith("app."):
                del sys.modules[name]
        import app.main as main_module
        if calls:
            _fail(findings, "app.main import created external clients/network: " + ", ".join(calls))
        return main_module
    except Exception as exc:
        _fail(findings, f"app.main import failed with safe dummy environment: {type(exc).__name__}: {exc}")
        return None
    finally:
        socket.socket = original_socket
        socket.create_connection = original_create_connection
        socket.getaddrinfo = original_getaddrinfo
        supabase_package.create_client = original_create
        boto3.client = original_boto3_client
        dotenv.load_dotenv = original_load_dotenv
        dotenv.dotenv_values = original_dotenv_values
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _route_duplicates(app, findings: list[str]) -> None:
    grouped: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path:
            continue
        for method in methods:
            grouped[(method.upper(), path)].append(type(route).__name__)

    duplicates = {key: names for key, names in grouped.items() if len(names) > 1}
    for (method, path), names in sorted(duplicates.items()):
        _fail(findings, f"duplicate FastAPI route {method} {path} ({', '.join(names)})")


def _compile_templates(findings: list[str]) -> None:
    try:
        app_module = sys.modules.get("app.main")
        if app_module is None:
            _fail(findings, "cannot compile templates without imported app.main environment")
            return
        env = app_module.templates.env
        for path in sorted(TEMPLATES_DIR.rglob("*.html")):
            try:
                env.get_template(path.relative_to(TEMPLATES_DIR).as_posix())
            except Exception as exc:
                _fail(findings, f"Jinja template compile failed {path.relative_to(ROOT)}: {type(exc).__name__}: {exc}")
    except Exception as exc:
        _fail(findings, f"Jinja environment setup failed: {type(exc).__name__}: {exc}")


def _check_script_tags(findings: list[str]) -> list[tuple[Path, str, int]]:
    class ScriptParser(html.parser.HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.current: tuple[bool, bool, int, list[str]] | None = None
            self.tags: list[tuple[bool, bool, str, int]] = []

        def handle_starttag(self, tag, attrs):
            if tag.lower() == "script":
                attrs = {name.lower(): value for name, value in attrs if name}
                has_src = "src" in attrs
                script_type = (attrs.get("type") or "").lower().split(";", 1)[0].strip()
                is_javascript = not script_type or script_type == "module" or script_type in {"text/javascript", "application/javascript", "text/ecmascript", "application/ecmascript"}
                self.current = (has_src, is_javascript, self.getpos()[0], [])

        def handle_data(self, data):
            if self.current is not None:
                self.current[3].append(data)

        def handle_endtag(self, tag):
            if tag.lower() == "script" and self.current is not None:
                has_src, is_javascript, line, body = self.current
                self.tags.append((has_src, is_javascript, "".join(body), line))
                self.current = None

    inline_scripts: list[tuple[Path, str, int]] = []
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        try:
            text = path.read_text(encoding="utf-8")
            text = re.sub(r"\{#[\s\S]*?#\}", lambda match: "".join("\n" if char == "\n" else " " for char in match.group()), text)
            parser = ScriptParser()
            parser.feed(text)
            parser.close()
        except (OSError, UnicodeError, ValueError) as exc:
            _fail(findings, f"HTML read/parse failed {path.relative_to(ROOT)}: {type(exc).__name__}: {exc}")
            continue
        for has_src, is_javascript, body, line in parser.tags:
            if has_src and body.strip():
                _fail(findings, f"script tag has src and inline code {path.relative_to(ROOT)}:{line}")
            elif not has_src and is_javascript and body.strip():
                inline_scripts.append((path, body, line))
    return inline_scripts


def _strip_jinja_for_node(source: str) -> str:
    """Replace template expressions/statements with whitespace for node --check.

    Keeping line breaks makes Node's reported line numbers useful while avoiding
    false syntax errors from Jinja delimiters embedded in JavaScript.
    """
    def blank(match: re.Match[str]) -> str:
        return "".join("\n" if char == "\n" else " " for char in match.group())

    source = re.sub(r"\{\{[\s\S]*?\}\}", lambda match: "null" + "".join("\n" for char in match.group() if char == "\n"), source)
    source = re.sub(r"\{%[\s\S]*?%\}", blank, source)
    source = re.sub(r"\{#[\s\S]*?#\}", blank, source)
    return source


def _check_inline_javascript(inline_scripts: Iterable[tuple[Path, str, int]], findings: list[str]) -> None:
    try:
        subprocess.run(["node", "--version"], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        _fail(findings, f"Node.js is required for inline JavaScript checks: {exc}")
        return

    for path, body, line in inline_scripts:
        source = _strip_jinja_for_node(body)
        source = "\n" * (line - 1) + source
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".js", delete=False) as handle:
            handle.write(source)
            temp_path = Path(handle.name)
        try:
            proc = subprocess.run(["node", "--check", str(temp_path)], capture_output=True, text=True)
            if proc.returncode:
                detail = (proc.stderr or proc.stdout).strip().splitlines()
                relevant = next((entry for entry in detail if "SyntaxError" in entry or "Error:" in entry), "node --check failed")
                _fail(findings, f"inline JavaScript syntax failed {path.relative_to(ROOT)}:{line}: {relevant}")
        finally:
            temp_path.unlink(missing_ok=True)


def _check_python_syntax(findings: list[str]) -> None:
    for path in sorted((ROOT / "app").glob("*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            _fail(findings, f"Python syntax failed {path.relative_to(ROOT)}: {exc}")


def main() -> int:
    findings: list[str] = []
    _check_python_syntax(findings)
    app_module = _safe_import_app(findings)
    if app_module is not None:
        _route_duplicates(app_module.app, findings)
    _compile_templates(findings)
    inline_scripts = _check_script_tags(findings)
    _check_inline_javascript(inline_scripts, findings)

    if findings:
        for finding in findings:
            print(f"[FAIL] {finding}")
        print(f"[FAIL] {len(findings)} static rule violation(s).")
        return 1

    print("[OK] static rules passed: Python syntax, app import, routes, Jinja templates, HTML scripts, inline JavaScript")
    return 0


if __name__ == "__main__":
    sys.exit(main())
