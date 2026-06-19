"""Tests for himark.tools.precompiled — parse-once, dump/load, apply a pipeline."""

import pytest

from himark.tools import precompiled
from himark.engine import splice
from himark.parser import parse

# A small Markdown → HTML-ish pipeline: escape &, then <, then >.
STATEMENTS = [
    r"{\&} => &amp;",
    r"{\<} => &lt;",
    r"{\>} => &gt;",
]


def test_apply_matches_statement_by_statement():
    pipe = precompiled.compile_pipeline(STATEMENTS)
    doc = "a & b < c > d"
    # apply() must equal splicing each statement in turn by hand.
    expected = doc
    for s in STATEMENTS:
        expected = splice(parse(s), expected)
    assert precompiled.apply(pipe, doc) == expected
    assert precompiled.apply(pipe, doc) == "a &amp; b &lt; c &gt; d"


def test_roundtrip_through_file(tmp_path):
    art = tmp_path / "md.hmkc"
    precompiled.dump(precompiled.compile_pipeline(STATEMENTS), art)
    loaded = precompiled.load(art)
    assert precompiled.apply(loaded, "x < y & z") == "x &lt; y &amp; z"


def test_dump_excludes_engine_objects(tmp_path):
    # The artifact holds only the AST — the lowered program is not serialised, so
    # the compile cache is empty after load and recompiles lazily on first use.
    pipe = precompiled.compile_pipeline(STATEMENTS)
    precompiled.apply(pipe, "&")  # warm the compile cache
    art = tmp_path / "md.hmkc"
    precompiled.dump(pipe, art)
    loaded = precompiled.load(art)
    assert all(tree._compiled is None for steps in loaded for tree in steps)
    assert precompiled.apply(loaded, "&") == "&amp;"  # still works (recompiles)


def test_load_rejects_foreign_file(tmp_path):
    bad = tmp_path / "nope.hmkc"
    bad.write_bytes(b"not a pipeline")
    with pytest.raises(ValueError, match="not an HMK compiled pipeline"):
        precompiled.load(bad)


# ── .hmk script splitting ─────────────────────────────────────────────────────


def test_split_groups_leading_arrow_continuations():
    # Continuation lines keep their cosmetic indentation; phase0 strips each step.
    src = '{a}\n  => "x"\n  => {b}\n{c} => "y"\n'
    assert precompiled.split_statements(src) == [
        '{a}\n  => "x"\n  => {b}',
        '{c} => "y"',
    ]


def test_split_skips_blank_and_comment_lines():
    src = "// header\n\n{a} => b\n\n  // mid\n{c} => d\n"
    assert precompiled.split_statements(src) == ["{a} => b", "{c} => d"]


def test_split_strips_trailing_comment_outside_braces_and_quotes():
    # `//` in a quoted template (a URL) or a brace is content, not a comment.
    src = '{a} => "http://x"  // real comment\n{//} => "y"\n'
    assert precompiled.split_statements(src) == ['{a} => "http://x"', '{//} => "y"']


def test_split_keeps_arrow_inside_quotes_as_one_statement():
    # A `=>` inside a quoted template must not be read as a step boundary, and a
    # brace spanning lines stays one logical line.
    src = '{a} => "x => y"\n'
    assert precompiled.split_statements(src) == ['{a} => "x => y"']


def test_load_script_roundtrips_through_compile(tmp_path):
    script = tmp_path / "s.hmk"
    script.write_text("{\\&} => &amp;   // escape\n{\\<} => &lt;\n", "utf-8")
    pipe = precompiled.compile_pipeline(precompiled.load_script(script))
    assert precompiled.apply(pipe, "a & b < c") == "a &amp; b &lt; c"
