"""Tests for parser/phase3.py — τ/α semantic resolver."""

import pytest

from marky.models import nodes_typed as t
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
    return first_brace(pattern).semantic


# ── τ forms ──────────────────────────────────────────────────────────────────


def test_literal():
    node = first_semantic("{hello}")
    assert node.type == "literal"
    assert node.content == "hello"


def test_char_range():
    node = first_semantic("{a..z}")
    assert node.type == "char_range"
    assert node.start == "a"
    assert node.end == "z"


# ── α forms ──────────────────────────────────────────────────────────────────


def test_upper_bound():
    # phase3 sees the expanded macro text (@d -> 0..9), not the @ ref.
    node = first_semantic("{{0..9}..255}")
    assert node.type == "upper_bound"
    assert node.upper == "255"
    assert node.alpha.type == "char_range"


def test_lower_bound():
    node = first_semantic("{128..{0..9}}")
    assert node.type == "lower_bound"
    assert node.lower == "128"
    assert node.alpha.type == "char_range"


def test_bounded_range():
    node = first_semantic("{aa..{a..z}..zz}")
    assert node.type == "bounded_range"
    assert node.lower == "aa"
    assert node.upper == "zz"
    assert node.alpha.type == "char_range"


def test_zip_range():
    node = first_semantic("{{a..z}<->{A..Z}}")
    assert node.type == "zip_range"
    assert node.left.type == "char_range"
    assert node.right.type == "char_range"


def test_congruence_single_pair():
    # {a<->A} — one enumerated congruence group.
    node = first_semantic("{a<->A}")
    assert node.type == "group_class"
    assert node.groups == [["a", "A"]]


def test_congruence_range_of_pairs():
    # {a<->A..z<->Z} — range of congruence pairs steps both columns (zip).
    node = first_semantic("{a<->A..z<->Z}")
    assert node.type == "zip_range"
    assert node.left.type == "union"
    assert node.right.type == "union"


def test_congruence_enumerated_groups():
    node = first_semantic("{{a<->A},{b<->B}}")
    assert node.type == "group_class"
    assert node.groups == [["a", "A"], ["b", "B"]]


def test_full_alpha():
    # {α} full range. Written with a space to avoid the {{...}} template-ref form.
    node = first_semantic("{ {a..z} }")
    assert node.type == "full_alpha"
    assert node.inner.type == "char_range"


# ── Singleton constructors (cardinality-1 {…} as τ) ──────────────────────────


def test_singleton_value_helper():
    from marky.parser.phase3 import _singleton_value

    # Singletons (τ): bare literals and {literal}[N] with exact count.
    assert _singleton_value("hello") == "hello"
    assert _singleton_value("{a}") == "a"
    assert _singleton_value("{a}[3]") == "aaa"
    assert _singleton_value("{hello}[2]") == "hellohello"
    assert _singleton_value("{ {a}[2] }[3]") == "aaaaaa"  # nested singletons

    # A bare name is now literal text — a singleton, not an alphabet.
    assert _singleton_value("dec") == "dec"

    # Non-singletons (α) → None.
    assert _singleton_value("{a..z}") is None  # range
    assert _singleton_value("{a..z}[3]") is None  # range inner
    assert _singleton_value("{a,b}") is None  # union
    assert _singleton_value("{a}[2..4]") is None  # range count


def test_singleton_bounded_range_synonym():
    # {z}[3] is a singleton τ, equivalent to writing the literal 'zzz'.
    node = first_semantic("{{1}[3]..{a..z}..{z}[3]}")
    assert node.type == "bounded_range"
    assert node.lower == "111"
    assert node.upper == "zzz"
    assert node.alpha.type == "char_range"


def test_singleton_upper_bound():
    # α..τ where τ is a singleton constructor.
    node = first_semantic("{{0..9}..{9}[3]}")
    assert node.type == "upper_bound"
    assert node.upper == "999"


def test_singleton_lower_bound():
    node = first_semantic("{{0}[3]..{0..9}}")
    assert node.type == "lower_bound"
    assert node.lower == "000"


def test_singleton_single_part_is_literal():
    # A standalone singleton {…} resolves to a literal, not a full_alpha.
    node = first_semantic("{{ab}[2]}")
    assert node.type == "literal"
    assert node.content == "abab"


# ── Union / token_set / group_class ─────────────────────────────────────────


def test_union_chars():
    node = first_semantic("{a,b,c}")
    assert node.type == "union"
    assert len(node.options) == 3


def test_token_set():
    node = first_semantic("{cat,dog}")
    assert node.type == "token_set"
    assert node.tokens == ["cat", "dog"]


def test_group_class():
    node = first_semantic("{{a<->A},{b<->B}}")
    assert node.type == "group_class"
    assert node.groups == [["a", "A"], ["b", "B"]]


# ── Complement ───────────────────────────────────────────────────────────────


def test_complement():
    node = first_semantic("{!\\n}")
    assert node.type == "complement"


# ── Padding ──────────────────────────────────────────────────────────────────


def test_fixed_padding():
    node = first_semantic("{3: {@d}..255}")
    assert node.type == "padded"
    assert node.min_width == 3
    assert node.max_width == 3


def test_width_range_padding():
    node = first_semantic("{2..3: {@d}..255}")
    assert node.type == "padded"
    assert node.min_width == 2
    assert node.max_width == 3


def test_variable_padding():
    node = first_semantic("{: {@d}..255}")
    assert node.type == "padded"
    assert node.min_width == 1
    assert node.max_width is None


# ── Count ────────────────────────────────────────────────────────────────────


def test_count_exact():
    bg = first_brace("{a..z}[3]")
    assert bg.count == t.CountRange(min=3, max=3)


def test_count_range():
    bg = first_brace("{a..z}[2..5]")
    assert bg.count == t.CountRange(min=2, max=5)


def test_count_open_ended():
    bg = first_brace("{a..z}[1..]")
    assert bg.count == t.CountRange(min=1, max=None)


def test_count_zero_or_more():
    bg = first_brace("{a..z}[..]")
    assert bg.count == t.CountRange(min=0, max=None)


# ── Template expressions ──────────────────────────────────────────────────────


def test_template_full_match():
    tree = resolve("{{.}}")
    node = tree.children[0]
    assert node.type == "full_match"


def test_template_group_ref():
    tree = resolve("{{0}}")
    node = tree.children[0]
    assert node.type == "group_ref"
    assert node.index == [0]


def test_template_span_ref():
    tree = resolve("{{0..2}}")
    node = tree.children[0]
    assert node.type == "span_ref"


def test_template_count_ref():
    tree = resolve("{{#0}}")
    node = tree.children[0]
    assert node.type == "count_ref"
    assert node.group == 0


# ── Error cases ───────────────────────────────────────────────────────────────


def test_char_range_multi_char_produces_string_range():
    node = first_semantic("{cat..dog}")
    assert node.type == "string_range"
    assert node.start == "cat"
    assert node.end == "dog"


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
    assert node.sep_value == "\n"
    assert node.sep_class is None


def test_separator_tau_punctuation_comma():
    # A lone comma is a punctuation constant, not an empty union.
    node = first_separator("<<,>>")
    assert node.sep_value == ","


def test_separator_tau_singleton_constructor():
    node = first_separator("<<{a}[3]>>")
    assert node.sep_value == "aaa"


def test_separator_alpha_bounded_range():
    node = first_separator("<<a..{a..z}..zz>>")
    assert node.sep_class.type == "bounded_range"
    assert node.sep_value is None


def test_separator_alpha_full_alpha():
    node = first_separator("<<{a..z}>>")
    assert node.sep_class.type == "full_alpha"


def test_separator_empty_unconstrained():
    node = first_separator("<<>>")
    assert node.sep_value is None
    assert node.sep_class is None


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


def test_separator_count_raises():
    # A count on <<...>> is a compile error; the syntax is reserved.
    with pytest.raises(CompileError):
        resolve("<<,>>[2]")


def test_group_class_non_singleton_member_raises():
    # Group members must be singletons; ranges of groups use <-> ranges.
    with pytest.raises(CompileError):
        resolve("{{a..z},{A..Z}}")


def test_full_alpha_disambiguation_space_allowed():
    # { {a..z} } — surrounding space is syntactically necessary to prevent
    # {{...}} being parsed as a template ref; it is stripped silently.
    node = first_semantic("{ {a..z} }")
    assert node.type == "full_alpha"
    assert node.inner.type == "char_range"
