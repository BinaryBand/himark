"""The `Alphabet` value object — an ordered set of symbols with positional
value arithmetic.

A range like `{aa..{a..z}..zz}` is positional numbering in base |alphabet|:
each symbol contributes its index, most-significant first. This object owns that
arithmetic so matchers never re-derive it.
"""

from __future__ import annotations

from marky.models.exceptions import CompileError

# Largest code-point span materialized into a symbol string. ascii (128) fits;
# uni (1.1M) does not and is rejected when used as a value bound.
MAX_SYMBOLS = 0x10000


class Alphabet:
    """An ordered symbol set. `distinct=True` rejects repeated symbols, which
    would make positional values ambiguous (used for `..`-endpoint alphabets)."""

    __slots__ = ("symbols", "base", "_index")

    def __init__(self, symbols: str, *, distinct: bool = False) -> None:
        if distinct and len(set(symbols)) != len(symbols):
            raise CompileError(
                "Alphabet has duplicate symbols — symbol values would be "
                "ambiguous; use congruence (<->) for case-folding"
            )
        self.symbols = symbols
        self.base = len(symbols)
        self._index = {c: i for i, c in enumerate(symbols)}

    def __contains__(self, ch: str) -> bool:
        return ch in self._index

    @property
    def zero(self) -> str:
        return self.symbols[0]

    def value(self, s: str) -> int:
        """Positional value of `s` in this alphabet (most-significant first)."""
        v = 0
        for c in s:
            v = v * self.base + self._index[c]
        return v

    def canonical_len(self, value: int) -> int:
        """Width of `value` written canonically (no leading zeros)."""
        length, ceiling = 1, self.base
        while value >= ceiling:
            ceiling *= self.base
            length += 1
        return length
