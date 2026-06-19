"""Tests for parser/phase2.py — tokenizer."""

import pytest

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError
from himark.parser.phase2 import parse

_HAS_CONTENT = (t.LeafNode, t.BraceGroupNode)


def children_types(pattern):
    return [c.type for c in parse(pattern).children]


def content_at(tree: t.RootNode, i: int) -> str:
    node = tree.children[i]
    assert isinstance(node, _HAS_CONTENT)
    return node.content


def count_src_at(tree: t.RootNode, i: int) -> str | None:
    node = tree.children[i]
    assert isinstance(node, t.BraceGroupNode)
    return node.count_src


def test_leaf_only():
    tree = parse("hello world")
    assert len(tree.children) == 1
    assert tree.children[0].type == "leaf"
    assert content_at(tree, 0) == "hello world"


def test_brace_group_basic():
    tree = parse("{a..z}")
    assert children_types("{a..z}") == ["brace_group"]
    assert content_at(tree, 0) == "a..z"


def test_brace_group_with_leaf():
    tree = parse("foo{bar}baz")
    types = [c.type for c in tree.children]
    assert types == ["leaf", "brace_group", "leaf"]
    assert content_at(tree, 1) == "bar"


def test_nested_brace_group():
    tree = parse("{{@d}..255}")
    assert children_types("{{@d}..255}") == ["brace_group"]
    assert content_at(tree, 0) == "{@d}..255"


def test_brace_group_count():
    tree = parse("{a..z}[3]")
    node = tree.children[0]
    assert node.type == "brace_group"
    assert node.count_src == "3"


def test_brace_group_count_range():
    tree = parse("{a..z}[2..5]")
    assert count_src_at(tree, 0) == "2..5"


def test_brace_group_count_open():
    tree = parse("{a..z}[..]")
    assert count_src_at(tree, 0) == ".."


def test_quoted_literal_is_leaf():
    tree = parse('"hi {0}"')
    assert tree.children[0].type == "leaf"
    assert content_at(tree, 0) == "hi {0}"


def test_nested_double_brace_is_one_group():
    # {{a,A},{b,B}} is a single brace group (no template refs anymore).
    assert children_types("{{a,A},{b,B}}") == ["brace_group"]


def test_escape_newline():
    tree = parse(r"\n")
    assert tree.children[0].type == "leaf"
    assert content_at(tree, 0) == "\n"


def test_escape_brace():
    tree = parse(r"\{hello\}")
    # All leaf content
    contents = [c.content for c in tree.children if isinstance(c, t.LeafNode)]
    assert "{" in contents
    assert "}" in contents


def test_multiple_groups():
    assert children_types("{a}{b}{c}") == ["brace_group", "brace_group", "brace_group"]


def test_unclosed_brace_raises():
    with pytest.raises(CompileError):
        parse("{unclosed")
