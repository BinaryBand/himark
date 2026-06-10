"""Tests for utils/alphabet.py — named alphabets and helpers."""

from marky.utils.alphabet import (
    NAMED_ALPHABETS,
    alpha_value,
    is_named_alpha,
)


def test_named_alphabets_present():
    for name in ("dec", "hex", "HEX", "b32", "b58", "b64", "b85", "ascii", "uni"):
        assert name in NAMED_ALPHABETS


def test_virtual_alphabets_are_none():
    assert NAMED_ALPHABETS["ascii"] is None
    assert NAMED_ALPHABETS["uni"] is None
    assert NAMED_ALPHABETS["hexi"] is None


def test_is_named_alpha():
    assert is_named_alpha("dec")
    assert is_named_alpha("hex")
    assert is_named_alpha("HEX")
    assert is_named_alpha("b58")
    assert not is_named_alpha("alpha")
    assert not is_named_alpha("b16")


def test_alpha_value_dec():
    alph = NAMED_ALPHABETS["dec"]
    assert alpha_value("0", alph) == 0
    assert alpha_value("9", alph) == 9
    assert alpha_value("10", alph) == 10
    assert alpha_value("255", alph) == 255


def test_alpha_value_hex():
    alph = NAMED_ALPHABETS["hex"]
    assert alpha_value("0", alph) == 0
    assert alpha_value("f", alph) == 15
    assert alpha_value("ff", alph) == 255
    assert alpha_value("100", alph) == 256


def test_alpha_value_HEX():
    alph = NAMED_ALPHABETS["HEX"]
    assert alpha_value("FF", alph) == 255


def test_b58_excludes_ambiguous():
    alph = NAMED_ALPHABETS["b58"]
    assert "I" not in alph
    assert "O" not in alph
    assert "l" not in alph
    assert "1" in alph
    assert "z" in alph
