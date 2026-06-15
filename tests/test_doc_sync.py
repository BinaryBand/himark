"""Guards against drift between docs/HMK.md and the implementation."""

import re
from pathlib import Path

from marky import parser
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
    # Spec headline: {a,A}[2] accepts 'aa', 'aA', 'Aa', 'AA' (comma folds a class).
    assert matches("{a,A}[2]", "aa aA Aa AA ab") == ["aa", "aA", "Aa", "AA"]


def test_doc_captures_example():
    # The Captures section: {#}[1..]{Sphinx}{of{black}{quartz}} numbers groups
    # 0,1,2 left-to-right, with {black}/{quartz} as sub-captures of group 2.
    ms = find_matches(
        parser.parse("{#}[1..]{Sphinx}{of{black}{quartz}}")[0],
        "###Sphinxofblackquartz",
    )
    assert len(ms) == 1
    assert ms[0].groups == ["###", "Sphinx", "ofblackquartz"]
    assert ms[0].sub_groups[2] == ["black", "quartz"]
