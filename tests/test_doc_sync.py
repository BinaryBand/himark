"""Guards against drift between docs/HMK.md and the implementation."""

import re
from pathlib import Path

from marky import parser
from marky.engine import execute
from marky.engine import find_matches
from marky.macros import MACROS

DOC = (Path(__file__).parent.parent / "docs" / "HMK.md").read_text("utf-8")


def matches(pattern, text):
    trees = parser.parse(pattern)
    return [m.text for m in find_matches(trees[0], text)]


def test_doc_macro_table_matches_macros_toml():
    doc_names = set(re.findall(r"^\| `@(\w+)`", DOC, re.MULTILINE))
    assert doc_names == set(MACROS)


def test_doc_congruence_pair_repetition():
    # Spec headline: {a<->A}[2] accepts 'aa', 'aA', 'Aa', 'AA'.
    assert matches("{a<->A}[2]", "aa aA Aa AA ab") == ["aa", "aA", "Aa", "AA"]


