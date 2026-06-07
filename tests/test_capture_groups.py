import pytest
pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st

from himark.parser import parse


@given(st.lists(st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=("Ll","Lu","Nd"))), min_size=1, max_size=6))
def test_sequence_of_bracketed_tokens_preserves_order(tokens):
    # Build a pattern consisting of adjacent single-bracket groups like [a][b][c]
    pattern = "".join(f"[{t}]" for t in tokens)
    tree, _ = parse(pattern)

    # Extract bracket-like children (single_brackets / double_brackets / chevrons / braces)
    bracket_children = [c for c in tree.children if c.type in ("single_brackets", "double_brackets", "double_chevrons", "double_braces")]

    assert len(bracket_children) == len(tokens)
    contents = [c.content for c in bracket_children]
    assert contents == tokens


def test_group_numbering_placeholder_xfail():
    # Placeholder for future group-numbering semantics described in docs/HMK.md
    import pytest

    pytest.xfail("Phase 3 (group numbering) not implemented yet; placeholder test.")
