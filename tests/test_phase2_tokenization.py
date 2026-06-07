import pytest

pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st

from himark.parser import parse, phase2


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

    t2 = parse("{{bar}}")[0].children[0]
    assert t2.type == "double_braces" and t2.content == "bar"
