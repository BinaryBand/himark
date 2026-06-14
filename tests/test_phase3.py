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


def test_char_range_is_unbounded_full_alpha():
    # {a..z} is an unbounded alphabet (any lowercase string), so it is a full
    # alpha wrapping the char range.
    node = first_semantic("{a..z}")
    assert node.type == "full_alpha"
    assert node.inner.type == "char_range"
    assert node.inner.start == "a"
    assert node.inner.end == "z"


# ── α forms ──────────────────────────────────────────────────────────────────


def test_upper_bound():
    # phase3 sees the expanded macro text (@d -> 0..9), not the @ ref.
    node = first_semantic("{{0..9}..255}")
    assert node.type == "value_range"
    assert node.lower is None  # open below (floor)
    assert node.upper == "255"
    assert node.alpha.inner.type == "char_range"


def test_lower_bound():
    node = first_semantic("{128..{0..9}}")
    assert node.type == "value_range"
    assert node.lower == "128"
    assert node.upper is None  # open above (unbounded)
    assert node.alpha.inner.type == "char_range"


def test_bounded_range():
    node = first_semantic("{aa..{a..z}..zz}")
    assert node.type == "value_range"
    assert node.lower == "aa"
    assert node.upper == "zz"
    assert node.alpha.inner.type == "char_range"


def test_class_to_class_zip():
    # {{a..z}<->{A..Z}} — zip two classes position-wise into one folded alphabet.
    node = first_semantic("{{a..z}<->{A..Z}}")
    assert node.type == "zip"
    assert len(node.tracks) == 2


def test_congruence_single_pair():
    # {a<->A} — the cardinality-1 zip: one position, two spellings.
    node = first_semantic("{a<->A}")
    assert node.type == "zip"
    assert [tr.content for tr in node.tracks] == ["a", "A"]


def test_congruence_n_ary():
    # {a<->A<->b} — an n-ary zip carries three tracks.
    node = first_semantic("{a<->A<->b}")
    assert node.type == "zip"
    assert [tr.content for tr in node.tracks] == ["a", "A", "b"]


def test_congruence_escaped_space_member():
    # '\ ' is a literal space in a track; raw whitespace around '<->' is rejected.
    node = first_semantic("{-\\ <->-}")
    assert node.type == "zip"
    assert [tr.content for tr in node.tracks] == ["- ", "-"]
    with pytest.raises(CompileError):
        resolve("{- <->-}")


def test_congruence_enumerated_is_union_of_zips():
    # The enumerated form is a union of single-position zips.
    node = first_semantic("{{a<->A},{b<->B}}")
    assert node.type == "union"
    assert [o.type for o in node.options] == ["zip", "zip"]


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
    assert node.type == "value_range"
    assert node.lower == "111"
    assert node.upper == "zzz"
    assert node.alpha.inner.type == "char_range"


def test_singleton_upper_bound():
    # α..τ where τ is a singleton constructor.
    node = first_semantic("{{0..9}..{9}[3]}")
    assert node.type == "value_range"
    assert node.lower is None
    assert node.upper == "999"


def test_singleton_lower_bound():
    node = first_semantic("{{0}[3]..{0..9}}")
    assert node.type == "value_range"
    assert node.lower == "000"
    assert node.upper is None


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


# ── Brace grouping (sequence vs. alphabet) ────────────────────────────────────


def types(pattern):
    """Top-level child node types of the resolved tree."""
    return [c.type for c in resolve(pattern).children]


def test_pure_alphabet_braces_stay_arithmetic():
    # Genuine σ expressions must NOT be mistaken for sequences.
    assert first_semantic("{a..z}").type == "full_alpha"
    assert first_semantic("{cat,dog}").type == "token_set"
    assert first_semantic("{aa..{a..z}..zz}").type == "value_range"
    assert first_semantic("{ {a..z} }").type == "full_alpha"
    assert first_semantic("{{a<->A},{b<->B}}").type == "union"


def test_class_congruence_is_a_zip_not_a_sequence():
    # {{a..z}<->{A..Z}} is σ (a zip of two classes), so it resolves to one
    # folded alphabet.
    assert first_semantic("{{a..z}<->{A..Z}}").type == "zip"


# ── Template expressions ──────────────────────────────────────────────────────


def test_template_full_match():
    tree = resolve("{{.}}")
    node = tree.children[0]
    assert node.type == "full_match"


def test_template_refs_resolve():
    # The full capture vocabulary: numbered, sub, span, and count references.
    assert resolve("{{0}}").children[0].type == "group_ref"
    assert resolve("{{0.1}}").children[0].type == "group_ref"
    assert resolve("{{0..2}}").children[0].type == "span_ref"
    assert resolve("{{#0}}").children[0].type == "count_ref"


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


def test_braced_class_arms_form_a_union():
    # {{a..z},{A..Z}} is not a congruence — it is a plain union of two classes.
    node = first_semantic("{{a..z},{A..Z}}")
    assert node.type == "union"
    assert len(node.options) == 2


def test_full_alpha_disambiguation_space_allowed():
    # { {a..z} } — surrounding space is syntactically necessary to prevent
    # {{...}} being parsed as a template ref; it is stripped silently.
    node = first_semantic("{ {a..z} }")
    assert node.type == "full_alpha"
    assert node.inner.type == "char_range"
