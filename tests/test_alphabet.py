"""Tests for utils/alphabet.py — named alphabets and helpers."""

from marky.utils.alphabet import (
    NAMED_ALPHABETS,
    all_in_alphabet,
    alpha_index,
    alpha_len,
    alpha_value,
    is_named_alpha,
    named_alphabet,
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
    alph = named_alphabet("dec")
    assert alpha_value("0", alph) == 0
    assert alpha_value("9", alph) == 9
    assert alpha_value("10", alph) == 10
    assert alpha_value("255", alph) == 255


def test_alpha_value_hex():
    alph = named_alphabet("hex")
    assert alpha_value("0", alph) == 0
    assert alpha_value("f", alph) == 15
    assert alpha_value("ff", alph) == 255
    assert alpha_value("100", alph) == 256


def test_alpha_value_HEX():
    alph = named_alphabet("HEX")
    assert alpha_value("FF", alph) == 255


def test_alpha_index():
    alph = named_alphabet("dec")
    assert alpha_index("0", alph) == 0
    assert alpha_index("5", alph) == 5
    assert alpha_index("9", alph) == 9


def test_alpha_len():
    assert alpha_len(named_alphabet("dec")) == 10
    assert alpha_len(named_alphabet("hex")) == 16
    assert alpha_len(named_alphabet("b58")) == 58
    assert alpha_len(named_alphabet("b64")) == 64


def test_all_in_alphabet_dec():
    alph = named_alphabet("dec")
    assert all_in_alphabet("123", alph)
    assert not all_in_alphabet("12a", alph)


def test_b58_excludes_ambiguous():
    alph = named_alphabet("b58")
    assert "I" not in alph
    assert "O" not in alph
    assert "l" not in alph
    assert "1" in alph
    assert "z" in alph


def test_named_alphabet_virtual_raises():
    import pytest

    with pytest.raises(ValueError):
        named_alphabet("uni")
