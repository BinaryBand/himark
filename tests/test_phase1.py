"""Tests for parser/phase1.py — macro expansion and implicit root wrapping."""

from marky import parser
from marky.engine import find_matches
from marky.parser import phase1


def matches(pattern, text):
    return [m.text for m in find_matches(parser.parse(pattern)[0], text)]


# ── Macro expansion (text level) ──────────────────────────────────────────────


# The 26 case-fold congruence groups @i expands to.
I_GROUPS = ",".join(f"{{{c}<->{c.upper()}}}" for c in "abcdefghijklmnopqrstuvwxyz")


def test_macro_simple_range():
    assert phase1.preprocess("{@d}") == "{0..9}"
    assert phase1.preprocess("{@l}") == "{a..z}"
    assert phase1.preprocess("{@u}") == "{A..Z}"


def test_macro_congruence():
    # @i expands to the 26 enumerated case-fold congruence groups.
    assert phase1.preprocess("{@i}") == "{" + I_GROUPS + "}"


def test_macro_nested_expansion():
    # @hex references @d and @i; expansion repeats until stable.
    assert phase1.preprocess("{@hex}") == "{{0..9},{{" + I_GROUPS + "}..f}}"
    assert phase1.preprocess("{@w}") == "{{" + I_GROUPS + "},_}"


def test_macro_whitespace_set():
    # @s expands to a comma-union of real control chars, not backslash escapes.
    assert phase1.preprocess("{@s}") == "{\n,\r, ,\t}"


def test_macro_b58_skip_ranges():
    # b58 expands to skip-ranges that bake in the 0/O/I/l omissions.
    assert phase1.preprocess("{@b58}") == "{1..9,A..H,J..N,P..Z,a..k,m..z}"


def test_macro_word_boundary():
    # @ before a non-macro word is left untouched.
    assert phase1.preprocess("{x@bar}") == "{x@bar}"


# ── Implicit wrapping ─────────────────────────────────────────────────────────


def test_implicit_wrap_bare_expression():
    assert phase1.preprocess("a..z") == "{a..z}"


def test_implicit_wrap_after_macro_expansion():
    assert phase1.preprocess("@d") == "{0..9}"


def test_no_wrap_when_already_braced():
    assert phase1.preprocess("{x}.{y}") == "{x}.{y}"


def test_no_wrap_separator_step():
    assert phase1.preprocess("<<\n>>") == "<<\n>>"


def test_no_wrap_template_step():
    assert phase1.preprocess("<h{{#0}}>{{1}}</h>") == "<h{{#0}}>{{1}}</h>"


# ── End-to-end through the full pipeline ──────────────────────────────────────


def test_macro_dec_matches_digits():
    assert matches("{@d}", "a1b2c3") == ["1", "2", "3"]


def test_macro_dec_value_bound():
    result = matches("{{@d}..255}", "192 300 10")
    assert "192" in result and "10" in result
    assert "300" not in result


def test_macro_w_case_insensitive_word():
    # @w is a union of the case-fold letter class and '_'; a union does not
    # merge arms into one alphabet, so letter-runs and '_' match separately.
    assert matches("{@w}", "Ab9") == ["Ab"]  # digits are not word chars
    assert matches("{@w}", "xyz") == ["xyz"]  # case-fold letters as one run
    assert matches("{@w}", "a_b") == ["a", "_", "b"]
    assert matches("{@w}", "!.?") == []


def test_macro_x_matches_non_whitespace():
    # @x is the complement of @s: greedy runs of non-whitespace.
    assert matches("{@x}", "ab cd\tef") == ["ab", "cd", "ef"]


def test_macro_s_matches_whitespace():
    result = matches("{@s}[1..]", "a   b\tc")
    assert "   " in result
    assert "\t" in result


def test_implicit_wrap_end_to_end():
    # Bare `a..z` is wrapped and read as a char range, not literal text.
    assert matches("a..z", "h e y 9") == ["h", "e", "y"]


def test_b58_symbol_order_preserved():
    # @b58 must keep the 58-symbol order for value arithmetic: '1' is value 0,
    # '9' is value 8, 'A' is value 9 — so {{@b58}..9} admits '9' but not 'A'.
    result = matches("{{@b58}..9}", "9 A")
    assert "9" in result
    assert "A" not in result
