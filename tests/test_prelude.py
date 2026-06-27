"""Tests for the `std.hmk` prelude loader (`himark/prelude.py`).

The prelude replaces the former `macros.toml`/`macros.py`: alphabets are declared
in Himark's own file, parsed once at import.
"""

import pytest

from himark import prelude
from himark.models.exceptions import CompileError


def test_shipped_prelude_loads():
    # The shipped prelude populates the macro registry.
    assert prelude.MACROS["d"] == "0..9"


def _load(text, tmp_path, monkeypatch):
    """Parse `text` as a prelude by pointing the loader at a temp file."""
    path = tmp_path / "p.hmk"
    path.write_text(text, "utf-8")
    monkeypatch.setattr(prelude, "PRELUDE_PATH", path)
    return prelude._load()


def test_parses_alphabet_declarations(tmp_path, monkeypatch):
    macros = _load(
        "@d = 0..9\n"
        "@hex = {@d},{@w::..f}   // a comment rides along\n"
        "\n"
        "// a full-line comment\n",
        tmp_path,
        monkeypatch,
    )
    assert macros == {"d": "0..9", "hex": "{@d},{@w::..f}"}


def test_comment_inside_value_survives(tmp_path, monkeypatch):
    # A `//` inside a brace is content, not a comment (depth-aware strip).
    macros = _load("@u = {http://x}\n", tmp_path, monkeypatch)
    assert macros == {"u": "{http://x}"}


def test_non_declaration_line_is_an_error(tmp_path, monkeypatch):
    with pytest.raises(CompileError):
        _load("{a..z} => x\n", tmp_path, monkeypatch)


def test_filter_declaration_is_now_rejected(tmp_path, monkeypatch):
    # Derived filters were removed; a `filter …` line is no longer a declaration.
    with pytest.raises(CompileError):
        _load("filter trimmed = . | trim\n", tmp_path, monkeypatch)
