"""Tests for utils/alphabet.py and the macros.toml alphabet definitions."""

from marky.macros import MACROS
from marky.utils.alphabet import alpha_value


def test_macros_present():
    for name in ("dec", "hex", "HEX", "b32", "b58", "b64", "b85", "ascii", "uni"):
        assert name in MACROS


def test_dec_expands_to_range():
    assert MACROS["dec"] == "0..9"


def test_b58_omits_ambiguous_via_ranges():
    # Skip-ranges bake in the 0/O/I/l exclusions without a value-corrupting `!`.
    assert "I" not in MACROS["b58"] or ".." in MACROS["b58"]
    assert MACROS["b58"] == "1..9,A..H,J..N,P..Z,a..k,m..z"


def test_alpha_value_dec():
    alph = "0123456789"
    assert alpha_value("0", alph) == 0
    assert alpha_value("9", alph) == 9
    assert alpha_value("10", alph) == 10
    assert alpha_value("255", alph) == 255


def test_alpha_value_hex():
    alph = "0123456789abcdef"
    assert alpha_value("f", alph) == 15
    assert alpha_value("ff", alph) == 255
    assert alpha_value("100", alph) == 256
