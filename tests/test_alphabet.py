"""Tests for the Alphabet value object and the macros.toml definitions."""

import pytest

from himark.engine.backend import Alphabet
from himark.parser.macros import MACROS
from himark.models.exceptions import CompileError

try:
    from hypothesis import given
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False


# ── Macro definitions ─────────────────────────────────────────────────────────


def test_macros_present():
    for name in (
        "d",
        "l",
        "u",
        "s",
        "w",
        "hex",
        "ascii",
        "uni",
    ):
        assert name in MACROS


def test_dec_expands_to_range():
    assert MACROS["d"] == "0..9"


# ── Positional value arithmetic ───────────────────────────────────────────────


def test_value_dec():
    dec = Alphabet("0123456789")
    assert dec.value("0") == 0
    assert dec.value("9") == 9
    assert dec.value("10") == 10
    assert dec.value("255") == 255


def test_value_hex():
    hexa = Alphabet("0123456789abcdef")
    assert hexa.value("f") == 15
    assert hexa.value("ff") == 255
    assert hexa.value("100") == 256


def test_zero_and_contains():
    a = Alphabet("0123456789")
    assert a.is_zero("0")
    assert not a.is_zero("5")
    assert "5" in a
    assert "x" not in a


def test_group_alphabet_folds_congruent_spellings():
    # One position per group: 'f' and 'F' share index 5, so values fold.
    hexa = Alphabet([[c] for c in "0123456789"] + [[c, c.upper()] for c in "abcdef"])
    assert hexa.value("ff") == hexa.value("FF") == hexa.value("fF") == 255
    assert hexa.is_zero("0")
    assert "F" in hexa


def test_group_alphabet_distinct_rejects_cross_group_duplicates():
    with pytest.raises(CompileError):
        Alphabet([["a", "A"], ["b", "a"]], distinct=True)


def test_multichar_group_member_rejected():
    # Positional values need single-character symbols.
    with pytest.raises(CompileError):
        Alphabet([["a", "bc"]])


def test_canonical_len():
    dec = Alphabet("0123456789")
    assert dec.canonical_len(0) == 1
    assert dec.canonical_len(9) == 1
    assert dec.canonical_len(10) == 2
    assert dec.canonical_len(99) == 2
    assert dec.canonical_len(100) == 3


def test_distinct_rejects_duplicate_symbols():
    Alphabet("0123456789abcdef", distinct=True)  # ok
    with pytest.raises(CompileError):
        Alphabet("0123456789abcdef0123456789ABCDEF", distinct=True)


# ── Property: value/canonical_len are mutually consistent across bases ─────────

if HAS_HYPOTHESIS:
    _ALPHABETS = ["0123456789", "0123456789abcdef", "01", "abcdefghijklmnopqrstuvwxyz"]

    @given(st.sampled_from(_ALPHABETS), st.integers(min_value=0, max_value=10**6))
    def test_value_roundtrips_with_canonical_rendering(symbols, n):
        alph = Alphabet(symbols)
        # Render n canonically in this base, then read it back: must equal n,
        # and its width must match canonical_len.
        base = len(symbols)
        digits = []
        v = n
        while True:
            digits.append(symbols[v % base])
            v //= base
            if v == 0:
                break
        rendered = "".join(reversed(digits))
        assert alph.value(rendered) == n
        assert len(rendered) == alph.canonical_len(n)

    @given(st.sampled_from(_ALPHABETS), st.integers(0, 10**4), st.integers(0, 10**4))
    def test_value_is_monotonic_at_fixed_width(symbols, a, b):
        # Equal-width canonical strings order the same as their values.
        alph = Alphabet(symbols)
        base = len(symbols)
        width = max(alph.canonical_len(a), alph.canonical_len(b))

        def render(n):
            out = []
            for _ in range(width):
                out.append(symbols[n % base])
                n //= base
            return "".join(reversed(out))

        sa, sb = render(a), render(b)
        assert (a < b) == (sa < sb)
