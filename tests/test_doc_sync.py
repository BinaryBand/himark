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
    # Spec headline: a bare class repeats homogeneously ({a,A}[2] = aa/AA); the
    # heterogeneous (every-casing) form is the nested {{a,A}}[2].
    assert matches("{a,A}[2]", "aa aA Aa AA ab") == ["aa", "AA"]
    assert matches("{{a,A}}[2]", "aa aA Aa AA ab") == ["aa", "aA", "Aa", "AA"]


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


def test_doc_fuzzy_bridge_alphabet_example():
    # The Fuzzy section: a bare {cat}~1 is over ambient Unicode, so any character
    # may bridge an edit; {cat:@l:cat}~1 narrows the bridge to lowercase letters
    # and so rejects a span like 'c@t'.
    assert matches("{cat}~1", "c@t") == ["c@t"]
    assert matches("{cat:@l:cat}~1", "c@t") == []
    assert matches("{cat:@l:cat}~1", "cot") == ["cot"]


def test_doc_subtractive_universe_examples():
    # The Subtraction section writes the subtractive universe `!{X}` with the
    # bang *outside* the brace, standalone: `!{a}` is any char except 'a',
    # `!{|,\n}` any char except '|' or newline.
    assert matches("!{a}", "abc") == ["b", "c"]
    assert matches("!{|,\\n}", "a|b") == ["a", "b"]


def test_doc_primitives_vs_objects():
    # Headline model: a comma-list is ordered primitives; nesting makes an object
    # whose faces are interchangeable. So `{a,A}[2]` stays in one point (aa/AA),
    # `{{a,A}}[2]` frees the faces (all four), and a run over an alphabet of
    # objects repeats one object without flattening (`{{a,A},{c,C}}[2]` = 8).
    assert matches("{a,A}[2]", "aa aA Aa AA") == ["aa", "AA"]
    assert matches("{{a,A}}[2]", "aa aA Aa AA") == ["aa", "aA", "Aa", "AA"]
    assert len(matches("{{a,A},{c,C}}[2]", "aa aA Aa AA cc cC Cc CC")) == 8
    # `{a,b}` is `{a..b}`: ordered, so a bound is value-ordered, not folded.
    assert matches("{a:{a,b,c}:b}", "a b c") == ["a", "b"]
