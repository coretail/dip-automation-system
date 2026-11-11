"""Unit test app/journal_link.py (standalone, tanpa pytest/framework).

Jalankan: python tests/test_journal_link.py
(atau dari CI: python tests/test_journal_link.py)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.journal_link import JOURNAL_LINK_MAX_LEN, normalize_journal_link, safe_journal_href

# (input, hasil normalize_journal_link yang diharapkan)
CASES_OK = [
    (None, None),
    ("", None),
    ("   ", None),
    ("\t\n  ", None),
    ("https://example.com", "https://example.com"),
    ("http://example.com/kepala-qc", "http://example.com/kepala-qc"),
    ("  https://example.com/x  ", "https://example.com/x"),
    ("HTTPS://EXAMPLE.COM/A", "HTTPS://EXAMPLE.COM/A"),
    ("https://example.com/a?b=c#d", "https://example.com/a?b=c#d"),
    # Batas panjang: tepat 2048 karakter masih valid.
    ("https://example.com/" + "a" * (JOURNAL_LINK_MAX_LEN - len("https://example.com/")),
     "https://example.com/" + "a" * (JOURNAL_LINK_MAX_LEN - len("https://example.com/"))),
]

# Input yang harus raise ValueError (dan safe_journal_href -> None).
CASES_BAD = [
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "data:text/html,<x>",
    "ftp://example.com/file",
    "example.com/tanpa-scheme",
    "/tanpa-scheme",
    "https://",
    "https:///path-saja",
    "HTTP://",
    "http://",
    "https://a b.com",
    "https://a\tb.com",
    "https://a\nb.com",
    "https://example.com/" + "a" * (JOURNAL_LINK_MAX_LEN + 1 - len("https://example.com/")),
]


def main() -> int:
    failed = 0
    for value, expected in CASES_OK:
        got = normalize_journal_link(value)
        if got != expected:
            print(f"GAGAL normalize_journal_link({value!r}) -> {got!r} (dugaan {expected!r})")
            failed += 1
            continue
        safe = safe_journal_href(value)
        if safe != expected:
            print(f"GAGAL safe_journal_href({value!r}) -> {safe!r} (dugaan {expected!r})")
            failed += 1
    for value in CASES_BAD:
        try:
            normalize_journal_link(value)
        except ValueError as exc:
            msg = str(exc)
            if not msg.strip():
                print(f"GAGAL: ValueError untuk {value[:40]!r} punya pesan kosong")
                failed += 1
                continue
        else:
            print(f"GAGAL normalize_journal_link({value[:40]!r}) tidak raise ValueError")
            failed += 1
            continue
        safe = safe_journal_href(value)
        if safe is not None:
            print(f"GAGAL safe_journal_href({value[:40]!r}) -> {safe!r} (dugaan None)")
            failed += 1
    if failed:
        print(f"FAIL: {failed} kasus gagal")
        return 1
    print(f"OK: {len(CASES_OK)} kasus valid + {len(CASES_BAD)} kasus invalid lulus")
    return 0


if __name__ == "__main__":
    sys.exit(main())
