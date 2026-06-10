"""Tests for parser/phase3.py — τ/α semantic resolver."""

import pytest

from marky.models.exceptions import CompileError
from marky.parser import phase2, phase3


def resolve(pattern):
    """Parse and resolve; return the root node."""
    return phase3.parse(phase2.parse(pattern))


def first_brace(pattern):
    """Return the first brace_group wrapper node from the resolved tree."""
    tree = resolve(pattern)
    return next(c for c in tree.children if c.type == "brace_group")


def first_semantic(pattern):
    """Return the semantic child of the first brace_group."""
    return first_brace(pattern).children[0]


# ── τ forms ──────────────────────────────────────────────────────────────────


def test_literal():
    node = first_semantic("{hello}")
    assert node.type == "literal"
    assert node.content == "hello"


def test_named_alpha_dec():
    node = first_semantic("{dec}")
    assert node.type == "named_alpha"
    assert node.metadata["name"] == "dec"


def test_named_alpha_hex():
    node = first_semantic("{hex}")
    assert node.type == "named_alpha"
    assert node.metadata["name"] == "hex"


def test_char_range():
    node = first_semantic("{a..z}")
    assert node.type == "char_range"
    assert node.metadata["start"] == "a"
    assert node.metadata["end"] == "z"


# ── α forms ──────────────────────────────────────────────────────────────────


def test_upper_bound():
    node = first_semantic("{{dec}..255}")
    assert node.type == "upper_bound"
    assert node.metadata["upper"] == "255"
    assert node.metadata["alpha"].type == "named_alpha"
    assert node.metadata["alpha"].metadata["name"] == "dec"


def test_lower_bound():
    node = first_semantic("{128..{dec}}")
    assert node.type == "lower_bound"
    assert node.metadata["lower"] == "128"
    assert node.metadata["alpha"].type == "named_alpha"


def test_bounded_range():
    node = first_semantic("{aa..{a..z}..zz}")
    assert node.type == "bounded_range"
    assert node.metadata["lower"] == "aa"
    assert node.metadata["upper"] == "zz"
    assert node.metadata["alpha"].type == "char_range"


def test_zip_range():
    node = first_semantic("{{a..z}..{A..Z}}")
    assert node.type == "zip_range"
    assert node.metadata["left"].type == "char_range"
    assert node.metadata["right"].type == "char_range"


def test_full_alpha():
    # {α} full range. Written with a space to avoid the {{...}} template-ref form.
    node = first_semantic("{ {a..z} }")
    assert node.type == "full_alpha"
    assert node.children[0].type == "char_range"


# ── Union / token_set / group_class ─────────────────────────────────────────


def test_union_chars():
    node = first_semantic("{a,b,c}")
    assert node.type == "union"
    assert len(node.children) == 3


def test_token_set():
    node = first_semantic("{cat,dog}")
    assert node.type == "token_set"
    assert node.metadata["tokens"] == ["cat", "dog"]


def test_group_class():
    node = first_semantic("{{a,A},{b,B}}")
    assert node.type == "group_class"
    assert node.metadata["groups"] == [["a", "A"], ["b", "B"]]


# ── Complement ───────────────────────────────────────────────────────────────


def test_complement():
    node = first_semantic("{!\\n}")
    assert node.type == "complement"


# ── Padding ──────────────────────────────────────────────────────────────────


def test_fixed_padding():
    node = first_semantic("{3: {dec}..255}")
    assert node.type == "padded"
    assert node.metadata["width"] == 3


def test_variable_padding():
    node = first_semantic("{: {dec}..255}")
    assert node.type == "padded"
    assert node.metadata["width"] is None


# ── Count ────────────────────────────────────────────────────────────────────


def test_count_exact():
    bg = first_brace("{a..z}[3]")
    assert bg.metadata["count"] == {"min": 3, "max": 3}


def test_count_range():
    bg = first_brace("{a..z}[2..5]")
    assert bg.metadata["count"] == {"min": 2, "max": 5}


def test_count_open_ended():
    bg = first_brace("{a..z}[1..]")
    assert bg.metadata["count"] == {"min": 1, "max": None}


def test_count_zero_or_more():
    bg = first_brace("{a..z}[..]")
    assert bg.metadata["count"] == {"min": 0, "max": None}


# ── Template expressions ──────────────────────────────────────────────────────


def test_template_full_match():
    tree = resolve("{{.}}")
    node = tree.children[0]
    assert node.type == "full_match"


def test_template_group_ref():
    tree = resolve("{{0}}")
    node = tree.children[0]
    assert node.type == "group_ref"
    assert node.metadata["index"] == [0]


def test_template_span_ref():
    tree = resolve("{{0..2}}")
    node = tree.children[0]
    assert node.type == "span_ref"


def test_template_count_ref():
    tree = resolve("{{#0}}")
    node = tree.children[0]
    assert node.type == "count_ref"
    assert node.metadata["group"] == 0


# ── Error cases ───────────────────────────────────────────────────────────────


def test_char_range_multi_char_raises():
    with pytest.raises(CompileError):
        first_semantic("{ab..yz}")


def test_invalid_count_raises():
    with pytest.raises(CompileError):
        from marky.parser.phase3 import _parse_count

        _parse_count("abc")
