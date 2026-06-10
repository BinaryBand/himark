"""Tests for parser/phase2.py — tokenizer."""

import pytest

from marky.models.exceptions import CompileError
from marky.parser.phase2 import parse


def children_types(pattern):
    return [c.type for c in parse(pattern).children]


def test_leaf_only():
    tree = parse("hello world")
    assert len(tree.children) == 1
    assert tree.children[0].type == "leaf"
    assert tree.children[0].content == "hello world"


def test_brace_group_basic():
    tree = parse("{a..z}")
    assert children_types("{a..z}") == ["brace_group"]
    assert tree.children[0].content == "a..z"


def test_brace_group_with_leaf():
    tree = parse("foo{bar}baz")
    types = [c.type for c in tree.children]
    assert types == ["leaf", "brace_group", "leaf"]
    assert tree.children[1].content == "bar"


def test_nested_brace_group():
    tree = parse("{{dec}..255}")
    assert children_types("{{dec}..255}") == ["brace_group"]
    assert tree.children[0].content == "{dec}..255"


def test_brace_group_count():
    tree = parse("{a..z}[3]")
    node = tree.children[0]
    assert node.type == "brace_group"
    assert node.metadata["count_src"] == "3"


def test_brace_group_count_range():
    tree = parse("{a..z}[2..5]")
    assert tree.children[0].metadata["count_src"] == "2..5"


def test_brace_group_count_open():
    tree = parse("{a..z}[..]")
    assert tree.children[0].metadata["count_src"] == ".."


def test_separator_basic():
    tree = parse("<<\\n>>")
    assert children_types("<<\\n>>") == ["separator"]
    # Escape is not processed here; sep content is raw
    assert tree.children[0].content == "\\n"


def test_separator_with_count():
    tree = parse("<<,>>[2]")
    node = tree.children[0]
    assert node.type == "separator"
    assert node.metadata["count_src"] == "2"


def test_template_ref_double_brace():
    tree = parse("{{0}}")
    assert children_types("{{0}}") == ["double_braces"]
    assert tree.children[0].content == "0"


def test_template_ref_full_match():
    tree = parse("{{.}}")
    assert tree.children[0].content == "."


def test_escape_newline():
    tree = parse(r"\n")
    assert tree.children[0].type == "leaf"
    assert tree.children[0].content == "\n"


def test_escape_brace():
    tree = parse(r"\{hello\}")
    # All leaf content
    contents = [c.content for c in tree.children if c.type == "leaf"]
    assert "{" in contents
    assert "}" in contents


def test_multiple_groups():
    tree = parse("{a}{b}{c}")
    assert children_types("{a}{b}{c}") == ["brace_group", "brace_group", "brace_group"]


def test_unclosed_brace_raises():
    with pytest.raises(CompileError):
        parse("{unclosed")
