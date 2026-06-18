"""Tests for parser/phase1.py — macro expansion and implicit root wrapping."""

from marky import parser
from marky.engine import find_matches
from marky.parser import phase1


def matches(pattern, text):
    return [m.text for m in find_matches(parser.parse(pattern)[0], text)]


# ── Macro expansion (text level) ──────────────────────────────────────────────


def test_macro_simple_range():
    assert phase1.preprocess("{@d}") == "{0..9}"
    assert phase1.preprocess("{@l}") == "{a..z}"
    assert phase1.preprocess("{@u}") == "{A..Z}"


# The expanded value of @w: 26 case-fold pairs in one brace, then ',_'.
_W = (
    "{" + ",".join(f"{{{c},{c.upper()}}}" for c in "abcdefghijklmnopqrstuvwxyz") + "},_"
)


def test_macro_w_case_fold_pairs():
    # @w folds case by enumerating each letter and its capital as a congruence
    # class ({a,A}, …), plus '_'.
    assert phase1.preprocess("{@w}") == "{" + _W + "}"


def test_macro_nested_expansion():
    # @hex references @d and @w; expansion repeats until stable. @w slices into a
    # `:` value bound ({:@w:f}), so the expansion is {{0..9},{:…@w…:f}}.
    assert phase1.preprocess("{@hex}") == "{{0..9},{:" + _W + ":f}}"


def test_macro_whitespace_set():
    # @s expands to a comma-union of real control chars, not backslash escapes.
    assert phase1.preprocess("{@s}") == "{\n,\r, ,\t}"


def test_macro_b58_complement():
    # b58 = digits, upper, lower, minus the four ambiguous glyphs.
    assert phase1.preprocess("{@b58}") == "{{0..9},{A..Z},{a..z},!{0,l,I,O}}"


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


def test_no_wrap_template_step():
    assert phase1.preprocess("<h>{{.}}</h>") == "<h>{{.}}</h>"


# ── End-to-end through the full pipeline ──────────────────────────────────────


def test_macro_dec_matches_digits():
    assert matches("{@d}", "a1b2c3") == ["1", "2", "3"]


def test_macro_dec_value_bound():
    result = matches("{:@d:255}", "192 300 10")
    assert "192" in result and "10" in result
    assert "300" not in result


def test_macro_w_case_insensitive_word():
    # @w is an ordered folded alphabet (case-fold letters plus '_'), so a word is
    # a value bounded over it: {a:@w:zzzzz}. Digits are not word symbols.
    assert matches("{a:@w:zzzzz}", "Ab9") == ["Ab"]
    assert matches("{a:@w:zzzzz}", "xyz") == ["xyz"]
    assert matches("{a:@w:zzzzz}", "a_b") == ["a_b"]
    assert matches("{a:@w:zzzzz}", "!.?") == []


def test_macro_x_matches_non_whitespace():
    # @x is the complement of @s; a run of non-whitespace is [1..] (heterogeneous).
    assert matches("{@x}[1..]", "ab cd\tef") == ["ab", "cd", "ef"]


def test_macro_s_matches_whitespace():
    result = matches("{@s}[1..]", "a   b\tc")
    assert "   " in result
    assert "\t" in result


def test_implicit_wrap_end_to_end():
    # Bare `a..z` is wrapped and read as a char range, not literal text.
    assert matches("a..z", "h e y 9") == ["h", "e", "y"]


def test_b58_symbol_order_preserved():
    # @b58 must keep the 58-symbol order for value arithmetic: '1' is value 0,
    # '9' is value 8, 'A' is value 9 — so {:@b58:9} admits '9' but not 'A'.
    result = matches("{:@b58:9}", "9 A")
    assert "9" in result
    assert "A" not in result


# ── Advanced rewrites: the TOML-described [#] self-binding count ───────────────


def test_self_binding_count_unrolls():
    from marky.parser.rewrites import apply

    # {ROW[#]}[1..] -> free first ROW ([#]->[..]) then repeats bound via [#0].
    src = r"{{{|}{!|,\n}}[#]{|\n}}[1..]"
    assert apply(src) == r"{{|}{!|,\n}}[..]{|\n}{{{|}{!|,\n}}[#0]{|\n}}[1..]"


def test_self_binding_count_noop_without_hash():
    from marky.parser.rewrites import apply

    assert apply("{a..z}[1..]") == "{a..z}[1..]"


def test_self_binding_count_group_offset():
    from marky.parser.rewrites import apply

    # A leading group shifts the bound index: the free copy's group is [#1].
    assert apply(r"{x}{{a}[#]}[2..]") == r"{x}{a}[..]{{a}[#1]}[2..]"


def test_self_binding_count_bounds():
    from marky.parser.rewrites import apply

    # Bounds around the # constrain the establishing copy and collapse into it.
    assert apply(r"{{a}[2..#]}[1..]") == r"{a}[2..]{{a}[#0]}[1..]"
    assert apply(r"{{a}[#..5]}[1..]") == r"{a}[..5]{{a}[#0]}[1..]"
    assert apply(r"{{a}[2..#..5]}[1..]") == r"{a}[2..5]{{a}[#0]}[1..]"


def test_self_binding_count_leaves_count_ref_alone():
    from marky.parser.rewrites import apply

    # [#0] is a count-reference, not the self-binding marker — never rewritten.
    assert apply(r"{{a}[#0]}[1..]") == r"{{a}[#0]}[1..]"


def test_rewrite_tool_is_parameterized():
    # The tool is generic — marker/free/bound come from data, so a different
    # marker drives the same unroll.
    from marky.parser.rewrites import unroll_on_marker

    out = unroll_on_marker(r"{{a}[~]}[1..]", marker="[~]", free="[..]", bound="[#@]")
    assert out == r"{a}[..]{{a}[#0]}[1..]"


def test_substitute_pipe_repeat_shortcut():
    # The TOML-described substitution: {|..} is sugar for {|}[..].
    from marky.parser.rewrites import apply

    assert apply("{|..}") == "{|}[..]"
    assert apply("x{|..}y") == "x{|}[..]y"
