import pytest

from himark.parser import parse


@pytest.mark.parametrize(
    "text,expected_first_child_type,expected_first_child_content",
    [
        ("[a]", "single_brackets", "a"),
        ("[[a]]", "double_brackets", "a"),
        ("<<foo>>", "double_chevrons", "foo"),
        ("{{var}}", "double_braces", "var"),
        ("hello", "leaf", "hello"),
    ],
)
def test_basic_tokenization_shapes(text, expected_first_child_type, expected_first_child_content):
    trees = parse(text)
    pattern_tree = trees[0]

    assert pattern_tree.type == "root"
    first = pattern_tree.children[0]
    assert first.type == expected_first_child_type
    assert first.content == expected_first_child_content
    assert len(trees) == 1
