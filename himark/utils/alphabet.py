"""Alphabet utilities for alternate-base matching used by the engine.

This module centralizes alphabet definitions and small helpers so the
engine can focus on matching semantics.
"""

from typing import Dict, FrozenSet


ALPHABETS: Dict[str, str] = {
    "b10": "0123456789",
    "dec": "0123456789",
    "hex": "0123456789abcdef",
    "b16": "0123456789abcdef",
    "b32": "0123456789abcdefghijklmnopqrstuv",
    "b58": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
    "b64": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",
}

# Alphabets that are treated case-agnostic by convention (stored lowercase)
CASE_AGNOSTIC_ALPHABETS: FrozenSet[str] = frozenset({"hex", "b16", "b32"})


def alpha_value(s: str, alphabet: str) -> int:
    """Convert a string `s` in `alphabet` to its integer value.

    The alphabet is treated as a positional numeral system where the leftmost
    character is the most-significant digit.
    """
    v = 0
    base = len(alphabet)
    for c in s:
        v = v * base + alphabet.index(c)
    return v


def all_in_alphabet(s: str, alphabet: str) -> bool:
    """Return True if every character in `s` appears in `alphabet`.

    This is a tiny helper used by the engine to validate multi-character
    endpoints and candidate strings.
    """
    return all(c in alphabet for c in s)
