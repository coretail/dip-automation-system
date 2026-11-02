"""Pure-local tests: penulis catatan Team Notes dicocokkan lewat author_id.

Dijalankan CI sebagai ``python tests/test_notes_author_resolution.py`` dengan
env dummy Supabase (``app.notes_routes`` mengimpor ``app.database``).
"""

import sys

from app.notes_routes import _render_note_html, _resolve_author_profile

BUDI = {"id": "id-budi", "full_name": "budi", "display_name": "Budi Santoso"}
IMPOSTER = {"id": "id-imposter", "full_name": "budi", "display_name": "Orang Lain"}


def test_author_id_wins_over_name_snapshot():
    # Dua profil berbagi full_name "budi": id harus menentukan, bukan nama.
    by_id = {"id-budi": BUDI, "id-imposter": IMPOSTER}
    by_name = {"budi": IMPOSTER}  # last-write-wins pada pencocokan nama
    note = {"author_id": "id-budi", "author_name": "budi"}
    assert _resolve_author_profile(note, by_id, by_name) is BUDI


def test_unresolved_author_id_does_not_borrow_another_profile_by_name():
    # Akun penulis sudah dihapus; nama "budi" kini dipakai profil lain.
    by_id = {"id-imposter": IMPOSTER}
    by_name = {"budi": IMPOSTER}
    note = {"author_id": "id-deleted", "author_name": "budi"}
    assert _resolve_author_profile(note, by_id, by_name) == {}


def test_note_without_author_id_falls_back_to_name_snapshot():
    by_name = {"budi": BUDI}
    for missing in (None, ""):
        note = {"author_id": missing, "author_name": "  Budi "}
        assert _resolve_author_profile(note, {}, by_name) is BUDI


def test_note_without_author_id_and_unknown_name_returns_empty():
    note = {"author_id": None, "author_name": "tidak-ada"}
    assert _resolve_author_profile(note, {"id-budi": BUDI}, {"budi": BUDI}) == {}


def test_author_id_is_compared_as_string():
    note = {"author_id": 42, "author_name": "x"}
    profile = {"id": "42", "full_name": "x", "display_name": "X"}
    assert _resolve_author_profile(note, {"42": profile}, {}) is profile


def test_mention_display_name_is_html_escaped():
    evil = '<img src=x onerror=alert(1)> "q"'
    out = _render_note_html("halo @budi", set(), set(), set(), {"budi": evil})
    assert "<img" not in out, out
    assert "&lt;img" in out and "&quot;q&quot;" in out, out


def test_mention_shows_display_name_only_when_different():
    out = _render_note_html("@budi @siti", set(), set(), set(), {"budi": "Budi S", "siti": "Siti"})
    assert "@budi (Budi S)" in out, out
    assert "@siti</span>" in out, out


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failures = []
    for name, func in tests:
        try:
            func()
        except Exception as exc:  # noqa: BLE001 - laporkan semua jenis kegagalan
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        return 1
    print(f"PASS {len(tests)} pemeriksaan resolusi penulis catatan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
