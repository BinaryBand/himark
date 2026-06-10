import pytest

pytest.importorskip("hypothesis")
from hypothesis import given
from hypothesis import strategies as st

from marky.parser import parse, phase2


@given(
    st.text(
        min_size=1,
        max_size=30,
        alphabet=st.characters(
            blacklist_characters="[]{}<>\\", min_codepoint=32, max_codepoint=126
        ),
    )
)
def test_plain_text_becomes_leaf(s):
    # Tests phase2 in isolation — bypasses phase1 stripping.
    # (The full parse() pipeline strips outer whitespace per spec, so strings like '0 ' can't round-trip.)
    tree = phase2.parse(s)
    assert tree.type == "root"
    reconstructed = "".join(c.content for c in tree.children)
    assert reconstructed == s


def test_double_chevrons_and_double_braces_tokenized():
    t1 = parse("<<foo>>")[0].children[0]
    assert t1.type == "double_chevrons" and t1.content == "foo"

    t2 = parse("{{ . }}")[0].children[0]
    assert t2.type == "double_braces" and t2.content == " . "


def test_bracket_with_options_has_metadata():
    tree = parse("[a..z](1..)")[0]
    bracket = tree.children[0]
    assert bracket.type == "single_brackets"
    assert bracket.metadata.get("options"), "options metadata should be non-empty"


def test_two_paren_groups_both_stored_in_options():
    # [a](hex)(1..) — two separate paren groups both end up in the options list
    tree = parse("[a..f](hex)(1..)")[0]
    bracket = tree.children[0]
    from marky.parser.phase3 import _flatten

    opts = _flatten(bracket.metadata.get("options", []))
    opt_contents = [o.content for o in opts if o.type == "option"]
    assert "hex" in opt_contents


def test_chain_arrow_produces_two_trees():
    trees = parse("[a] => {{ . }}")
    assert len(trees) == 2


def test_chain_arrow_produces_three_trees():
    trees = parse("[a] => [b] => {{ . }}")
    assert len(trees) == 3


def test_chain_first_tree_is_pattern():
    trees = parse("[a..z](1..) => {{ . }}")
    assert trees[0].children[0].type == "single_brackets"


def test_chain_last_tree_is_template():
    trees = parse("[a] => {{ . }}")
    assert trees[-1].children[0].type == "double_braces"


# ---------------------------------------------------------------------------
# Negation with count modifiers
# ---------------------------------------------------------------------------


def test_negation_with_count_modifier_parses():
    # Previously raised CompileError; should now succeed
    trees = parse("[[a]](1..)")
    bracket = trees[0].children[0]
    assert bracket.type == "double_brackets"
    assert bracket.metadata.get("options"), "count modifier should be in options"


def test_negation_exact_count_parses():
    trees = parse("[[a]](3)")
    bracket = trees[0].children[0]
    assert bracket.type == "double_brackets"


def test_negation_zero_or_more_parses():
    trees = parse("[[a]](0..)")
    bracket = trees[0].children[0]
    assert bracket.type == "double_brackets"


def test_negation_newline_with_count_parses():
    # The heading use case: [[\n]](0..)
    trees = parse(r"[[\n]](0..)")
    bracket = trees[0].children[0]
    assert bracket.type == "double_brackets"
