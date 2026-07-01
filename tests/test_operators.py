"""Template value operators (docs/ALGEBRA.md, TODO Step 2).

Arithmetic and bitwise operators inside `{{ ... }}`, evaluated over universe
**values**: integer op on the operands' values, LHS alphabet+band win, then
normalize onto the band and encode. Operators are total -- they never trap.
"""

from himark import parser
from himark.engine import execute


def ex(pattern, text):
    return execute(parser.parse(pattern), text)


# A group under a closed value band carries `(lo, hi)` -> operators wrap mod n.
BAND = "{@d::0..255} => "


# ── Arithmetic over a band ─────────────────────────────────────────────────────


def test_add_keeps_lhs_width():
    # 9 + 1 = 10; the LHS operand's width (2) is kept -> "10", not "010".
    assert ex(BAND + '"{{ $0 + 1 }}"', "09") == ["10"]


def test_add_wraps_on_band_overflow():
    # 255 + 1 = 256 == 0 (mod 256), at the LHS width (3) -> "000".
    assert ex(BAND + '"{{ $0 + 1 }}"', "255") == ["000"]


def test_sub_multiply_divide_modulo():
    assert ex(BAND + '"{{ $0 - 4 }}"', "09") == ["05"]
    assert ex(BAND + '"{{ $0 * 3 }}"', "09") == ["27"]
    assert ex(BAND + '"{{ $0 / 2 }}"', "09") == ["04"]  # floor
    assert ex(BAND + '"{{ $0 % 5 }}"', "09") == ["04"]


def test_sub_wraps_below_zero_on_a_band():
    # 0 - 1 wraps mod 256 to 255 (floored mod, never a signed result).
    assert ex(BAND + '"{{ $0 - 1 }}"', "000") == ["255"]


# ── Totality: /0 and %0 are defined, not errors ────────────────────────────────


def test_division_and_modulo_by_zero_are_zero():
    assert ex(BAND + '"{{ $0 / 0 }}"', "09") == ["00"]
    assert ex(BAND + '"{{ $0 % 0 }}"', "09") == ["00"]


# ── Bitwise ────────────────────────────────────────────────────────────────────


def test_bitwise_and_or_xor():
    assert ex(BAND + '"{{ $0 & 10 }}"', "12") == ["08"]  # 1100 & 1010 = 1000
    assert ex(BAND + '"{{ $0 `1 }}"', "12") == ["13"]  # backtick is or
    assert ex(BAND + '"{{ $0 ^ 10 }}"', "12") == ["06"]  # 1100 ^ 1010 = 0110


def test_shifts():
    assert ex(BAND + '"{{ $0 << 2 }}"', "03") == ["12"]  # 3 << 2 = 12
    assert ex(BAND + '"{{ $0 >> 1 }}"', "12") == ["06"]  # 12 >> 1 = 6


def test_unary_not_wraps_onto_band():
    # ~0 = -1, normalized onto [0, 255] -> 255.
    assert ex(BAND + '"{{ ~$0 }}"', "00") == ["255"]


# ── Precedence, grouping, and the filter pipe ──────────────────────────────────


def test_multiplicative_binds_tighter_than_additive():
    assert ex('!{x}[1..] => "{{ 2 + 3 * 4 }}"', "z") == ["14"]


def test_parentheses_override_precedence():
    assert ex('!{x}[1..] => "{{ (2 + 3) * 4 }}"', "z") == ["20"]


def test_filter_pipe_is_loosest():
    # `$0 + 1` evaluates first, then `| trim` -- so a whitespace-free result.
    assert ex(BAND + '"{{ $0 + 1 | trim }}"', "09") == ["10"]


def test_left_associative_chain():
    # ((1 - 2) - 3) over a plain @uni result renders as a signed decimal (-4);
    # no band is in force for bare literals, so no wrap.
    assert ex('!{x}[1..] => "{{ 1 - 2 - 3 }}"', "z") == ["-4"]


# ── Unbanded (plain-literal) arithmetic renders as decimal ─────────────────────


def test_bare_literals_render_decimal():
    assert ex('!{x}[1..] => "{{ 6 * 7 }}"', "z") == ["42"]
