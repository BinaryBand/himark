"""Alphabet utilities for HMK named alphabets and range matching."""

NAMED_ALPHABETS: dict[str, str | None] = {
    "dec": "0123456789",
    "hex": "0123456789abcdef",
    "HEX": "0123456789ABCDEF",
    "hexi": None,  # zip of hex + HEX; engine expands at match time
    "b32": "0123456789abcdefghijklmnopqrstuv",
    "b58": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
    "b64": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",
    "b85": "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{|}~",
    "ascii": None,  # U+0000–U+007F; engine uses ord() bounds
    "uni": None,  # U+0000–U+10FFFF; engine uses ord() bounds
}


def is_named_alpha(name: str) -> bool:
    return name in NAMED_ALPHABETS


def alpha_value(s: str, alphabet: str) -> int:
    """Convert string `s` to its integer value in the given alphabet (positional numeral system)."""
    v = 0
    base = len(alphabet)
    for c in s:
        v = v * base + alphabet.index(c)
    return v
