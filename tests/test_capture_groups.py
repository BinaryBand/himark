import pytest

pytest.importorskip("hypothesis")
from hypothesis import given
from hypothesis import strategies as st

from marky.parser import parse


@given(
    st.lists(
        st.text(
            min_size=1,
            max_size=5,
            alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        ),
        min_size=1,
        max_size=6,
    )
)
def test_sequence_of_bracketed_tokens_preserves_order(tokens):
    # Build a pattern consisting of adjacent single-bracket groups like [a][b][c]
    pattern = "".join(f"[{t}]" for t in tokens)
    tree = parse(pattern)[0]

    bracket_children = [
        c
        for c in tree.children
        if c.type
        in ("single_brackets", "double_brackets", "double_chevrons", "double_braces")
    ]

    assert len(bracket_children) == len(tokens)
    contents = [c.content for c in bracket_children]
    assert contents == tokens


def test_group_numbering_basic():
    from marky.engine import execute

    results = execute(parse("[0..9](1..)[px||em||rem] => {{ 1 }}"), "12px solid")
    assert results == ["12"]
