import pytest
pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st

from himark.parser import parse


@given(st.text(min_size=1, max_size=30, alphabet=st.characters(blacklist_characters="[]{}<>", min_codepoint=32, max_codepoint=126)))
def test_plain_text_becomes_leaf(s):
    tree, _ = parse(s)
    # If there are no bracket/chevron/brace matches, the root should contain a single leaf
    # Note: phase2 returns a root with either children or a single leaf child
    assert tree.type == "root"
    # The concatenation of leaf children should equal input when no special tokens are present
    reconstructed = "".join(c.content for c in tree.children)
    assert reconstructed == s


def test_double_chevrons_and_double_braces_tokenized():
    tree, _ = parse("<<sep>><{x}>>")
    # Ensure chevrons and braces are detected when properly formed
    t1 = parse("<<foo>>")[0].children[0]
    assert t1.type == "double_chevrons" and t1.content == "foo"

    t2 = parse("{{bar}}")[0].children[0]
    assert t2.type == "double_braces" and t2.content == "bar"
