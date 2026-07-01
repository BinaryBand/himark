"""The `Alphabet` value object — an ordered set of symbol groups with
positional value arithmetic.

A bound like `{{a..z}::aa..zz}` is positional numbering in base |alphabet|:
each symbol contributes its index, most-significant first. A symbol may be a
*group* of congruent surface forms (`{f,F}`): every member maps to the same
index, so values fold across spellings. This object owns that arithmetic so
matchers never re-derive it.
"""

from __future__ import annotations

from himark.models.exceptions import CompileError

# Largest code-point span materialized into a symbol string. ascii (128) fits;
# uni (1.1M) does not and is rejected when used as a value bound.
MAX_SYMBOLS = 0x10000


class Alphabet:
    """An ordered set of symbol groups. A plain string is shorthand for one
    singleton group per character. `distinct=True` rejects a surface form that
    appears twice (across or within groups), which would make positional
    values ambiguous (used for `..`-endpoint alphabets)."""

    __slots__ = ("groups", "base", "_index")

    def __init__(
        self, groups: list[list[str]] | str, *, distinct: bool = False
    ) -> None:
        if isinstance(groups, str):
            groups = [[c] for c in groups]
        members = [m for grp in groups for m in grp]
        if any(len(m) != 1 for m in members):
            raise CompileError(
                "A value alphabet needs single-character symbols; "
                "multi-character group members have no positional value"
            )
        if distinct and len(set(members)) != len(members):
            raise CompileError(
                "Alphabet has duplicate symbols — symbol values would be "
                "ambiguous; enumerate a congruence class (e.g. {f,F}) instead"
            )
        self.groups = groups
        self.base = len(groups)
        self._index = {m: i for i, grp in enumerate(groups) for m in grp}

    def __contains__(self, ch: str) -> bool:
        return ch in self._index

    def is_zero(self, ch: str) -> bool:
        """True if `ch` spells the zero-valued symbol (a leading-pad char)."""
        return self._index[ch] == 0

    def value(self, s: str) -> int:
        """Positional value of `s` in this alphabet (most-significant first).
        Congruent spellings yield the same value."""
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

    def encode(self, value: int, width: int) -> str:
        """Format `value` as `width` symbols, most-significant first, left-padded
        with the zero symbol. The inverse of `value` (a congruence class renders as
        its first member). `value` must be non-negative."""
        chars = [self.groups[0][0]] * width
        v, pos = value, width - 1
        while v > 0 and pos >= 0:
            chars[pos] = self.groups[v % self.base][0]
            v //= self.base
            pos -= 1
        return "".join(chars)


class RangeAlphabet:
    """A virtual positional alphabet over a contiguous code-point range too large
    to materialize (e.g. `@uni`, U+0000–U+10FFFF). Value is ord-positional in base
    `hi - lo + 1`, the zero symbol is `lo`. Duck-types `Alphabet` for the matcher
    (`in`, `is_zero`, `value`, `canonical_len`) without building a group table."""

    __slots__ = ("lo", "hi", "base")

    def __init__(self, lo: int, hi: int) -> None:
        self.lo, self.hi, self.base = lo, hi, hi - lo + 1

    def __contains__(self, ch: str) -> bool:
        return self.lo <= ord(ch) <= self.hi

    def is_zero(self, ch: str) -> bool:
        return ord(ch) == self.lo

    def value(self, s: str) -> int:
        v = 0
        for c in s:
            v = v * self.base + (ord(c) - self.lo)
        return v

    def canonical_len(self, value: int) -> int:
        length, ceiling = 1, self.base
        while value >= ceiling:
            ceiling *= self.base
            length += 1
        return length

    def encode(self, value: int, width: int) -> str:
        chars = [chr(self.lo)] * width
        v, pos = value, width - 1
        while v > 0 and pos >= 0:
            chars[pos] = chr(self.lo + v % self.base)
            v //= self.base
            pos -= 1
        return "".join(chars)
