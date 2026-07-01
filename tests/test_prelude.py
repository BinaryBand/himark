"""Tests for the `std.hmk` prelude loader (`himark/prelude.py`).

The prelude replaces the former `variables.toml`/`variables.py`: alphabets are declared
in Himark's own file, parsed once at import.
"""

import pytest

from himark import prelude
from himark.models.exceptions import CompileError


def test_shipped_prelude_loads():
    # The shipped prelude populates the variable registry.
    assert prelude.VARIABLES["d"] == "0..9"


def _load(text, tmp_path, monkeypatch):
    """Parse `text` as a prelude by pointing the loader at a temp file. `_load` now
    returns `(variables, filter_srcs)`; these tests only assert on the alphabets."""
    path = tmp_path / "p.hmk"
    path.write_text(text, "utf-8")
    monkeypatch.setattr(prelude, "PRELUDE_PATH", path)
    variables, _filters, _anchors = prelude._load()
    return variables


def test_parses_alphabet_declarations(tmp_path, monkeypatch):
    variables = _load(
        "@d = 0..9\n"
        "@hex = {@d},{@w::..f}   // a comment rides along\n"
        "\n"
        "// a full-line comment\n",
        tmp_path,
        monkeypatch,
    )
    assert variables == {"d": "0..9", "hex": "{@d},{@w::..f}"}


def test_comment_inside_value_survives(tmp_path, monkeypatch):
    # A `//` inside a brace is content, not a comment (depth-aware strip).
    variables = _load("@u = {http://x}\n", tmp_path, monkeypatch)
    assert variables == {"u": "{http://x}"}


def test_non_declaration_line_is_an_error(tmp_path, monkeypatch):
    with pytest.raises(CompileError):
        _load("{a..z} => x\n", tmp_path, monkeypatch)


def test_bare_filter_keyword_is_rejected(tmp_path, monkeypatch):
    # A filter is declared with the `@name =` sigil, not a `filter …` keyword; a
    # bare keyword line is still not a declaration.
    with pytest.raises(CompileError):
        _load("filter trimmed = $ | trim\n", tmp_path, monkeypatch)


def test_pipeline_body_is_classified_as_a_filter(tmp_path, monkeypatch):
    # `@name = <pipeline>` (an arrow body or a leading template) is a declared
    # filter, held apart from the textual alphabets by body shape.
    path = tmp_path / "p.hmk"
    path.write_text(
        '@d = 0..9\n@rstrip = {{@s}}[1..]{@>>} => ""\n@double = "{{ $ * 2 }}"\n',
        "utf-8",
    )
    monkeypatch.setattr(prelude, "PRELUDE_PATH", path)
    variables, filter_srcs, anchors = prelude._load()
    assert variables == {"d": "0..9"}
    assert set(filter_srcs) == {"rstrip", "double"}
    assert anchors == set()
