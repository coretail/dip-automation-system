"""Guard checks ensuring test files, CI workflow, and .gitignore stay synchronized.

Lightweight stdlib-only check run during CI static checks (and optionally in
`.githooks/pre-push`). Exit code 0 means clean; exit code 1 means one or more
synchronization violations were found.
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
GITIGNORE = ROOT / ".gitignore"
TESTS_DIR = ROOT / "tests"

ALLOWED_CI_VERIFY_SCRIPTS = frozenset(
    {
        "tests/verify_po_analytics_detail.py",
        "tests/verify_product_attachments.py",
    }
)

_CI_PYTHON_RE = re.compile(r"\bpython\s+(tests/[^\s;'\"#]+\.py)")
_GITIGNORE_WHITELIST_RE = re.compile(r"^!/tests/([^/\s]+\.py)\s*$")


def _collect_repo_test_files() -> set[str]:
    """Return active repo test files directly under tests/ (excluding local gitignored scratch)."""
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "tests/*.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "tests/*.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        paths: set[str] = set()
        for raw in tracked.stdout.splitlines() + untracked.stdout.splitlines():
            norm = raw.strip().replace("\\", "/")
            if not norm:
                continue
            p = Path(norm)
            if p.parent == Path("tests") and (ROOT / p).is_file():
                paths.add(norm)
        return paths
    except Exception:
        return {f"tests/{p.name}" for p in TESTS_DIR.glob("*.py") if p.is_file()}


def _parse_ci_entries(ci_path: Path) -> list[str]:
    """Extract all `python tests/*.py` entries from ci.yml in order (preserving duplicates)."""
    entries: list[str] = []
    for raw in ci_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        code_part = raw.split("#", 1)[0]
        for match in _CI_PYTHON_RE.finditer(code_part):
            entries.append(match.group(1).replace("\\", "/"))
    return entries


def _parse_gitignore_whitelists(gitignore_path: Path) -> list[str]:
    """Extract all `!/tests/*.py` whitelist entries from .gitignore (preserving duplicates)."""
    entries: list[str] = []
    for raw in gitignore_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _GITIGNORE_WHITELIST_RE.match(stripped)
        if match:
            entries.append(f"tests/{match.group(1)}")
    return entries


def check_tests_registered() -> list[str]:
    """Run all 7 synchronization checks and return a list of failure messages."""
    findings: list[str] = []
    if not CI_YML.is_file():
        return [f"Missing CI workflow file: {CI_YML}"]
    if not GITIGNORE.is_file():
        return [f"Missing .gitignore file: {GITIGNORE}"]

    repo_test_files = _collect_repo_test_files()
    ci_entries = _parse_ci_entries(CI_YML)
    ci_counts = Counter(ci_entries)
    ci_set = set(ci_entries)

    gitignore_entries = _parse_gitignore_whitelists(GITIGNORE)
    gitignore_counts = Counter(gitignore_entries)
    gitignore_set = set(gitignore_entries)

    # 1 & 2. Duplicates in ci.yml
    for path, count in sorted(ci_counts.items()):
        if count > 1:
            findings.append(f"Duplicate CI entry in .github/workflows/ci.yml: {path} ({count}x)")

    # 3. Dangling CI entries
    for path in sorted(ci_set):
        if not (ROOT / path).is_file():
            findings.append(f"Dangling CI entry (file missing on disk): {path}")

    # 4. Forbidden entries in ci.yml (helpers, E2E, non-allowlisted verify/other scripts)
    for path in sorted(ci_set):
        name = Path(path).name
        if name.startswith("_"):
            findings.append(f"Helper module must not be registered in ci.yml: {path}")
        elif name.startswith("e2e_"):
            findings.append(f"E2E script must not be registered in ci.yml: {path}")
        elif name.startswith("verify_") and path not in ALLOWED_CI_VERIFY_SCRIPTS:
            findings.append(f"Non-allowlisted verify script must not be registered in ci.yml: {path}")
        elif not name.startswith("test_") and path not in ALLOWED_CI_VERIFY_SCRIPTS:
            findings.append(f"Non-test script is not allowed in ci.yml: {path}")

    # 5. Unregistered unit tests & required pure-local verify scripts
    for path in sorted(repo_test_files):
        name = Path(path).name
        if name.startswith("test_") and path not in ci_set:
            findings.append(f"Unregistered unit test missing from ci.yml: {path}")

    for path in sorted(ALLOWED_CI_VERIFY_SCRIPTS):
        if not (ROOT / path).is_file():
            findings.append(f"Allowlisted pure-local verify script missing on disk: {path}")
        elif path not in ci_set:
            findings.append(f"Allowlisted pure-local verify script missing from ci.yml: {path}")

    # 6 & 7. .gitignore synchronization
    for path, count in sorted(gitignore_counts.items()):
        if count > 1:
            findings.append(f"Duplicate .gitignore whitelist entry: !/{path} ({count}x)")

    for path in sorted(repo_test_files):
        if path not in gitignore_set:
            findings.append(f"Test file missing .gitignore whitelist entry: !/{path}")

    for path in sorted(gitignore_set):
        if not (ROOT / path).is_file():
            findings.append(f"Orphaned .gitignore whitelist entry (file missing on disk): !/{path}")

    if not findings:
        print(
            "[OK] check_tests_registered passed: "
            f"{len(ci_entries)} CI tests, {len(repo_test_files)} repo test files, "
            f"{len(gitignore_entries)} .gitignore whitelists"
        )
    return findings


def main() -> int:
    findings = check_tests_registered()
    if findings:
        for item in findings:
            print(f"[FAIL] {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
