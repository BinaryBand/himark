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
    node = first_semantic("{{a..z}<->{A..Z}}")
    assert node.type == "zip_range"
    assert node.metadata["left"].type == "char_range"
    assert node.metadata["right"].type == "char_range"


def test_congruence_single_pair():
    # {a<->A} — one enumerated congruence group.
    node = first_semantic("{a<->A}")
    assert node.type == "group_class"
    assert node.metadata["groups"] == [["a", "A"]]


def test_congruence_range_of_pairs():
    # {a<->A..z<->Z} — range of congruence pairs steps both columns (zip).
    node = first_semantic("{a<->A..z<->Z}")
    assert node.type == "zip_range"
    assert node.metadata["left"].type == "union"
    assert node.metadata["right"].type == "union"


def test_congruence_enumerated_groups():
    node = first_semantic("{{a<->A},{b<->B}}")
    assert node.type == "group_class"
    assert node.metadata["groups"] == [["a", "A"], ["b", "B"]]


def test_full_alpha():
    # {α} full range. Written with a space to avoid the {{...}} template-ref form.
    node = first_semantic("{ {a..z} }")
    assert node.type == "full_alpha"
    assert node.children[0].type == "char_range"


# ── Singleton constructors (cardinality-1 {…} as τ) ──────────────────────────


def test_singleton_value_helper():
    from marky.parser.phase3 import _singleton_value

    # Singletons (τ): bare literals and {literal}[N] with exact count.
    assert _singleton_value("hello") == "hello"
    assert _singleton_value("{a}") == "a"
    assert _singleton_value("{a}[3]") == "aaa"
    assert _singleton_value("{hello}[2]") == "hellohello"
    assert _singleton_value("{ {a}[2] }[3]") == "aaaaaa"  # nested singletons

    # Non-singletons (α) → None.
    assert _singleton_value("dec") is None  # named alphabet
    assert _singleton_value("{a..z}") is None  # range
    assert _singleton_value("{a..z}[3]") is None  # range inner
    assert _singleton_value("{a,b}") is None  # union
    assert _singleton_value("{a}[2..4]") is None  # range count


def test_singleton_bounded_range_synonym():
    # {z}[3] is a singleton τ, equivalent to writing the literal 'zzz'.
    node = first_semantic("{{1}[3]..{a..z}..{z}[3]}")
    assert node.type == "bounded_range"
    assert node.metadata["lower"] == "111"
    assert node.metadata["upper"] == "zzz"
    assert node.metadata["alpha"].type == "char_range"


def test_singleton_upper_bound():
    # α..τ where τ is a singleton constructor.
    node = first_semantic("{{dec}..{9}[3]}")
    assert node.type == "upper_bound"
    assert node.metadata["upper"] == "999"


def test_singleton_lower_bound():
    node = first_semantic("{{0}[3]..{dec}}")
    assert node.type == "lower_bound"
    assert node.metadata["lower"] == "000"


def test_singleton_single_part_is_literal():
    # A standalone singleton {…} resolves to a literal, not a full_alpha.
    node = first_semantic("{{ab}[2]}")
    assert node.type == "literal"
    assert node.content == "abab"


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
    node = first_semantic("{{a<->A},{b<->B}}")
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


def test_char_range_multi_char_produces_string_range():
    node = first_semantic("{cat..dog}")
    assert node.type == "string_range"
    assert node.metadata["start"] == "cat"
    assert node.metadata["end"] == "dog"


def test_invalid_count_raises():
    with pytest.raises(CompileError):
        from marky.parser.phase3 import _parse_count

        _parse_count("abc")


# ── Whitespace enforcement ────────────────────────────────────────────────────


def test_space_after_comma_raises():
    with pytest.raises(CompileError):
        first_semantic("{a, b}")


def test_space_before_comma_raises():
    with pytest.raises(CompileError):
        first_semantic("{a ,b}")


def test_space_around_dots_raises():
    with pytest.raises(CompileError):
        first_semantic("{a .. z}")


def test_space_after_dots_raises():
    with pytest.raises(CompileError):
        first_semantic("{a.. z}")


def test_space_in_exclusion_raises():
    with pytest.raises(CompileError):
        first_semantic("{a..z, !d..f}")


def test_pure_whitespace_arm_is_literal_space():
    # { } — lone whitespace arm is an intentional literal-space match.
    node = first_semantic("{ }")
    assert node.type == "literal"
    assert node.content == " "


# ── Separator content (τ/α cardinality dispatch) ─────────────────────────────


def first_separator(pattern):
    tree = resolve(pattern)
    return next(c for c in tree.children if c.type == "separator")


def test_separator_tau_constant():
    node = first_separator("<<\n>>")
    assert node.metadata["sep_value"] == "\n"
    assert "sep_class" not in node.metadata


def test_separator_tau_punctuation_comma():
    # A lone comma is a punctuation constant, not an empty union.
    node = first_separator("<<,>>")
    assert node.metadata["sep_value"] == ","


def test_separator_tau_singleton_constructor():
    node = first_separator("<<{a}[3]>>")
    assert node.metadata["sep_value"] == "aaa"


def test_separator_alpha_bounded_range():
    node = first_separator("<<a..{a..z}..zz>>")
    assert node.metadata["sep_class"].type == "bounded_range"
    assert "sep_value" not in node.metadata


def test_separator_alpha_full_alpha():
    node = first_separator("<<{a..z}>>")
    assert node.metadata["sep_class"].type == "full_alpha"


def test_separator_empty_unconstrained():
    node = first_separator("<<>>")
    assert "sep_value" not in node.metadata
    assert "sep_class" not in node.metadata


# ── Sequence braces (transparent sub-sequence) ───────────────────────────────


def test_sequence_brace_splices_children():
    # {**<<>>**} — top-level <<>> flips the interior to sequence context; the
    # brace is transparent and its children splice into the parent.
    tree = resolve("{**<<>>**}")
    types = [c.type for c in tree.children]
    assert types == ["leaf", "separator", "leaf"]
    assert tree.children[0].content == "**"
    assert tree.children[2].content == "**"


def test_sequence_brace_inner_groups_resolve():
    # Inner brace groups inside a sequence brace resolve normally.
    tree = resolve("{{a..z}<<,>>{0..9}}")
    types = [c.type for c in tree.children]
    assert types == ["brace_group", "separator", "brace_group"]


def test_sequence_brace_count_raises():
    with pytest.raises(CompileError):
        resolve("{**<<>>**}[2]")


def test_full_alpha_disambiguation_space_allowed():
    # { {a..z} } — surrounding space is syntactically necessary to prevent
    # {{...}} being parsed as a template ref; it is stripped silently.
    node = first_semantic("{ {a..z} }")
    assert node.type == "full_alpha"
    assert node.children[0].type == "char_range"
