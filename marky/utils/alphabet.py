"""Positional value arithmetic over an alphabet string.

Named alphabets themselves live in macros.toml; this module only converts a
string to its integer value within a given (materialized) alphabet.
"""


def alpha_value(s: str, alphabet: str) -> int:
    """Convert string `s` to its integer value in the given alphabet (positional numeral system)."""
    v = 0
    base = len(alphabet)
    for c in s:
        v = v * base + alphabet.index(c)
    return v
