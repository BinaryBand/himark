"""Tests for marky.tools.precompiled — parse-once, dump/load, apply a pipeline."""

import pytest

from marky.tools import precompiled
from marky.engine import splice
from marky.parser import parse

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
