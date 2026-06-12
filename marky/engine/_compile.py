"""Compile a resolved HMK AST into executable `Matcher`s.

This is the engine's single dispatch boundary. `lower()` turns each semantic
node into a `Matcher` whose alphabet, group table, and exclusion sets are
computed **once**, here — never re-derived in the match loop. The loop
(`engine/_run.py`) then speaks only the `Matcher` interface and never inspects
node types again.

Adding a construct is three additive edits: a node class (models), a phase-3
producer (parser), and one entry in `_LOWERINGS` below.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from marky.engine.alphabet import Alphabet
from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError

# ── Matcher interface ─────────────────────────────────────────────────────────


@runtime_checkable
class Matcher(Protocol):
    def match(self, text: str, pos: int) -> int | None:
        """Greedy end (exclusive) of one matched unit at `pos`, or None."""
        ...

    def accepts(self, s: str) -> bool:
        """True if the whole of `s` is exactly one unit."""
        ...

    def equal_unit(self, text: str, pos: int, first: str) -> int | None:
        """End of the next repetition at `pos`, required to equal `first`."""
        ...


class _Base:
    """Default `accepts` (via match) and literal `equal_unit`. Concrete
    matchers override `match`; group matchers override `equal_unit`."""

    def match(self, text: str, pos: int) -> int | None:  # pragma: no cover
        raise NotImplementedError

    def accepts(self, s: str) -> bool:
        return bool(s) and self.match(s, 0) == len(s)

    def equal_unit(self, text: str, pos: int, first: str) -> int | None:
        n = len(first)
        return pos + n if text[pos : pos + n] == first else None


# ── Exclusion helpers (resolved once, at compile time) ────────────────────────


class _Excluder:
    """Compiled exclusion set — works for both single chars and multi-char strings."""

    __slots__ = ("singles", "ranges")

    def __init__(self, excl: list[str]):
        singles, ranges = [], []
        for e in excl:
            if ".." in e:
                lo, hi = e.split("..", 1)
                ranges.append((lo, hi))
            else:
                singles.append(e)
        self.singles = set(singles)
        self.ranges = ranges

    def __call__(self, s: str) -> bool:
        return s in self.singles or any(lo <= s <= hi for lo, hi in self.ranges)


class _ValueExcluder:
    __slots__ = ("singles", "ranges")

    def __init__(self, excl: list[str], alph: Alphabet):
        base = _Excluder(excl)
        self.singles = {alph.value(x) for x in base.singles}
        self.ranges = [(alph.value(lo), alph.value(hi)) for lo, hi in base.ranges]

    def __call__(self, v: int) -> bool:
        return v in self.singles or any(lo <= v <= hi for lo, hi in self.ranges)


# ── Alphabet construction from a sub-node ─────────────────────────────────────


def _symbols(node: t.SemanticNode) -> str:
    if isinstance(node, t.CharRangeNode):
        lo, hi = ord(node.start), ord(node.end)
        if hi - lo + 1 > 0x10000:
            raise CompileError(
                f"Range {node.start!r}..{node.end!r} is too large "
                f"to use as a value bound"
            )
        return "".join(chr(c) for c in range(lo, hi + 1))
    if isinstance(node, t.UnionNode):
        return "".join(_symbols(ch) for ch in node.options)
    if isinstance(node, t.LiteralNode):
        return node.content
    raise CompileError(f"Cannot use {type(node).__name__} as a value alphabet")


def _alphabet_of(node: t.SemanticNode, *, distinct: bool) -> Alphabet:
    return Alphabet(_symbols(node), distinct=distinct)


# ── Value-range view (ValueRange / FullAlpha) ─────────────────────────────────


@dataclass(slots=True)
class _ValueView:
    alphabet: Alphabet
    lo: int | None
    hi: int | None
    excluded: _ValueExcluder
    min_width: int


def _value_view(node: t.SemanticNode) -> _ValueView | None:
    """The value-arithmetic view of a node, or None if it has no value bounds.

    The min_width is the lower endpoint's written width: values are zero-padded
    to it, so `{aa..{a..z}..zz}` matches exactly the 2-char lowercase strings.
    """
    if isinstance(node, t.ValueRangeNode):
        alph = _alphabet_of(node.alpha, distinct=True)
        lo = alph.value(node.lower) if node.lower is not None else None
        hi = alph.value(node.upper) if node.upper is not None else None
        min_width = len(node.lower) if node.lower is not None else 1
        return _ValueView(
            alph, lo, hi, _ValueExcluder(node.exclusions, alph), min_width
        )
    if isinstance(node, t.FullAlphaNode):
        alph = _alphabet_of(node.inner, distinct=False)
        return _ValueView(alph, None, None, _ValueExcluder(node.exclusions, alph), 1)
    return None


# ── Concrete matchers ─────────────────────────────────────────────────────────


class _Literal(_Base):
    __slots__ = ("content",)

    def __init__(self, content: str):
        self.content = content

    def match(self, text: str, pos: int) -> int | None:
        n = len(self.content)
        return pos + n if text[pos : pos + n] == self.content else None


class _CharRange(_Base):
    __slots__ = ("start", "end", "_excl")

    def __init__(self, node: t.CharRangeNode):
        self.start, self.end = node.start, node.end
        self._excl = _Excluder(node.exclusions)

    def match(self, text: str, pos: int) -> int | None:
        if pos >= len(text):
            return None
        ch = text[pos]
        if not (self.start <= ch <= self.end) or self._excl(ch):
            return None
        return pos + 1


class _StringRange(_Base):
    """Greedy lexicographic range over multi-char endpoints; tries lengths from
    the longer endpoint down to the shorter."""

    __slots__ = ("start", "end", "_lo", "_hi")

    def __init__(self, node: t.StringRangeNode):
        self.start, self.end = node.start, node.end
        self._lo = min(len(node.start), len(node.end))
        self._hi = max(len(node.start), len(node.end))

    def match(self, text: str, pos: int) -> int | None:
        for length in range(self._hi, self._lo - 1, -1):
            s = text[pos : pos + length]
            if len(s) == length and self.start <= s <= self.end:
                return pos + length
        return None


class _FullAlpha(_Base):
    """Greedy run of characters that each match the inner alphabet node."""

    __slots__ = ("inner", "_excl")

    def __init__(self, node: t.FullAlphaNode):
        self.inner = lower(node.inner)
        self._excl = _Excluder(node.exclusions)

    def match(self, text: str, pos: int) -> int | None:
        end = pos
        while end < len(text):
            if self._excl(text[end]):
                break
            nxt = self.inner.match(text, end)
            if nxt is None or nxt == end:
                break
            end = nxt
        return end if end > pos else None


class _ValueRange(_Base):
    """Canonical-form value match: each value has exactly one representation,
    zero-padded only up to the lower endpoint's width."""

    __slots__ = ("view",)

    def __init__(self, view: _ValueView):
        self.view = view

    def match(self, text: str, pos: int) -> int | None:
        v = self.view
        end = pos
        while end < len(text) and text[end] in v.alphabet:
            end += 1
        for length in range(end - pos, v.min_width - 1, -1):
            cand = text[pos : pos + length]
            if length > v.min_width and cand[0] == v.alphabet.zero:
                continue
            value = v.alphabet.value(cand)
            if (v.lo is not None and value < v.lo) or (
                v.hi is not None and value > v.hi
            ):
                continue
            if v.excluded(value):
                continue
            return pos + length
        return None


class _Union(_Base):
    __slots__ = ("options", "_excl")

    def __init__(self, node: t.UnionNode):
        self.options = [lower(o) for o in node.options]
        self._excl = _Excluder(node.exclusions)

    def match(self, text: str, pos: int) -> int | None:
        for arm in self.options:
            end = arm.match(text, pos)
            if end is not None and not self._excl(text[pos:end]):
                return end
        return None


class _Complement(_Base):
    """Greedy run of characters that do NOT match the inner node."""

    __slots__ = ("inner",)

    def __init__(self, node: t.ComplementNode):
        self.inner = lower(node.inner)

    def match(self, text: str, pos: int) -> int | None:
        end = pos
        while end < len(text) and self.inner.match(text, end) is None:
            end += 1
        return end if end > pos else None


class _TokenSet(_Base):
    __slots__ = ("tokens", "_excl")

    def __init__(self, node: t.TokenSetNode):
        self.tokens = sorted(node.tokens, key=len, reverse=True)
        self._excl = set(node.exclusions)

    def match(self, text: str, pos: int) -> int | None:
        for tok in self.tokens:
            if tok not in self._excl and text[pos : pos + len(tok)] == tok:
                return pos + len(tok)
        return None


class _Group(_Base):
    """Equivalence-group class — the single congruence primitive. Members of a
    group are interchangeable; repetition-equality is checked against the group
    sequence, so 'a' and 'bc' count as the same unit when grouped, and 'a'/'A'
    fold together for case-insensitive repetition."""

    __slots__ = ("members",)

    def __init__(self, groups: list[list[str]]):
        # (member, group_index) longest-first so multi-char members win.
        self.members = sorted(
            ((m, i) for i, grp in enumerate(groups) for m in grp if m),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

    def match(self, text: str, pos: int) -> int | None:
        end = pos
        while end < len(text):
            for m, _ in self.members:
                if text.startswith(m, end):
                    end += len(m)
                    break
            else:
                break
        return end if end > pos else None

    def _seq(self, s: str) -> list[int] | None:
        seq: list[int] = []
        i = 0
        while i < len(s):
            for m, idx in self.members:
                if s.startswith(m, i):
                    seq.append(idx)
                    i += len(m)
                    break
            else:
                return None
        return seq

    def equal_unit(self, text: str, pos: int, first: str) -> int | None:
        seq = self._seq(first)
        if seq is None:
            return None
        cur = pos
        for gidx in seq:
            for m, idx in self.members:
                if idx == gidx and text.startswith(m, cur):
                    cur += len(m)
                    break
            else:
                return None
        return cur


class _ValueWindowPadded(_Base):
    """Fixed-width or width-range value match; leading zero-padding allowed."""

    __slots__ = ("view", "min_width", "max_width")

    def __init__(self, view: _ValueView, min_width: int, max_width: int | None):
        self.view = view
        self.min_width = min_width
        self.max_width = max_width

    def match(self, text: str, pos: int) -> int | None:
        v = self.view
        end = pos
        while end < len(text) and text[end] in v.alphabet:
            end += 1
        if self.max_width is not None:
            max_w = self.max_width
        elif v.hi is not None:
            max_w = v.alphabet.canonical_len(v.hi)
        else:
            max_w = end - pos
        for width in range(min(max_w, end - pos), self.min_width - 1, -1):
            value = v.alphabet.value(text[pos : pos + width])
            if (v.lo is not None and value < v.lo) or (
                v.hi is not None and value > v.hi
            ):
                continue
            if v.excluded(value):
                continue
            return pos + width
        return None


class _PerCharPadded(_Base):
    """Width-window over a run of single-char inner matches (non-value inner)."""

    __slots__ = ("inner", "min_width", "max_width")

    def __init__(self, inner: Matcher, min_width: int, max_width: int | None):
        self.inner = inner
        self.min_width = min_width
        self.max_width = max_width

    def match(self, text: str, pos: int) -> int | None:
        run = pos
        while run < len(text) and self.inner.match(text, run) == run + 1:
            run += 1
        max_w = self.max_width if self.max_width is not None else run - pos
        width = min(max_w, run - pos)
        return pos + width if width >= self.min_width else None


# ── Padding lowering ──────────────────────────────────────────────────────────


def _lower_padded(node: t.PaddedNode) -> Matcher:
    view = _value_view(node.inner)
    if view is not None:
        return _ValueWindowPadded(view, node.min_width, node.max_width)
    return _PerCharPadded(lower(node.inner), node.min_width, node.max_width)


def _lower_value_range(node: t.SemanticNode) -> Matcher:
    view = _value_view(node)
    assert view is not None
    return _ValueRange(view)


# ── Lowering registry ─────────────────────────────────────────────────────────

_LOWERINGS: dict[type, Callable[..., Matcher]] = {
    t.LiteralNode: lambda n: _Literal(n.content),
    t.CharRangeNode: _CharRange,
    t.StringRangeNode: _StringRange,
    t.FullAlphaNode: _FullAlpha,
    t.ValueRangeNode: _lower_value_range,
    t.GroupClassNode: lambda n: _Group(n.groups),
    t.UnionNode: _Union,
    t.ComplementNode: _Complement,
    t.TokenSetNode: _TokenSet,
    t.PaddedNode: _lower_padded,
}


def lower(node: t.SemanticNode) -> Matcher:
    """Compile a semantic node into its `Matcher`."""
    fn = _LOWERINGS.get(type(node))
    if fn is None:
        raise CompileError(f"No matcher for node type {type(node).__name__}")
    return fn(node)


# ── Element compilation (the sequence level) ──────────────────────────────────


@dataclass(slots=True)
class LiteralEl:
    text: str


@dataclass(slots=True)
class GroupEl:
    matcher: Matcher
    min_reps: int
    max_reps: int | None
    count_ref: int | None


@dataclass(slots=True)
class SepEl:
    sep_value: str | None
    sep_class: Matcher | None


Element = LiteralEl | GroupEl | SepEl


def _count_config(count: t.CountSpec | None) -> tuple[int, int | None, int | None]:
    if isinstance(count, t.CountRange):
        return count.min, count.max, None
    if isinstance(count, t.CountRef):
        return 1, 1, count.index
    return 1, 1, None


def compile_pattern(root: t.RootNode) -> list[Element]:
    """Compile a resolved pattern tree into a flat list of executable elements."""
    elements: list[Element] = []
    for child in root.children:
        if isinstance(child, t.LeafNode):
            elements.append(LiteralEl(child.content))
        elif isinstance(child, t.BraceGroupNode):
            if child.semantic is None:
                raise CompileError(f"Unresolved brace group: {{{child.content}}}")
            min_reps, max_reps, count_ref = _count_config(child.count)
            elements.append(
                GroupEl(lower(child.semantic), min_reps, max_reps, count_ref)
            )
        elif isinstance(child, t.SeparatorNode):
            sep_class = lower(child.sep_class) if child.sep_class is not None else None
            elements.append(SepEl(child.sep_value, sep_class))
        else:
            raise CompileError(f"Unexpected node in pattern: {type(child).__name__}")
    return elements
