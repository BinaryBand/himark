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

from himark.engine.alphabet import MAX_SYMBOLS, Alphabet, RangeAlphabet
from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError

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
    """Default `accepts` (via match). `equal_unit` is the **heterogeneous**
    continuation — a fresh match of the next rep — used by the `{{U}}[n]` form
    (homogeneous `{U}[n]` checks string equality in the loop instead). Concrete
    matchers override `match`; `_Group` overrides `equal_unit` to stay within the
    same congruence group."""

    # The value alphabet a capture of this matcher carries (None unless the
    # matcher is a `{x:A:y}` bound); read by the run loop to type the capture.
    value_alphabet: "Alphabet | RangeAlphabet | None" = None

    def match(self, text: str, pos: int) -> int | None:  # pragma: no cover
        raise NotImplementedError

    def accepts(self, s: str) -> bool:
        return bool(s) and self.match(s, 0) == len(s)

    def equal_unit(self, text: str, pos: int, first: str) -> int | None:
        return self.match(text, pos)


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


def _excluder(excl: list[str]) -> _Excluder | None:
    """An excluder, or None when there is nothing to exclude (the common case) —
    so hot matchers skip the call with a cheap `is not None` test per character."""
    e = _Excluder(excl)
    return e if (e.singles or e.ranges) else None


class _ValueExcluder:
    __slots__ = ("singles", "ranges")

    def __init__(self, excl: list[str], alph: Alphabet | RangeAlphabet):
        base = _Excluder(excl)
        self.singles = {alph.value(x) for x in base.singles}
        self.ranges = [(alph.value(lo), alph.value(hi)) for lo, hi in base.ranges]

    def __call__(self, v: int) -> bool:
        return v in self.singles or any(lo <= v <= hi for lo, hi in self.ranges)


# ── Alphabet construction from a sub-node ─────────────────────────────────────


def _drop_excluded(groups: list[list[str]], exclusions: list[str]) -> list[list[str]]:
    """Remove excluded symbols from an alphabet's groups, dropping any group left
    empty. An excluded symbol is simply not part of the value alphabet, so a run
    stops at it — this is what keeps `@b58`'s forbidden `0`/`O`/`I`/`l` out of a
    `{floor:@b58:ceiling}` bound, and keeps the positional values canonical."""
    excl = _excluder(exclusions)
    if excl is None:
        return groups
    kept = [[m for m in grp if not excl(m)] for grp in groups]
    return [grp for grp in kept if grp]


def _groups(node: t.SemanticNode) -> list[list[str]]:
    """The ordered symbol groups a node contributes to a value alphabet.
    Most symbols are singleton groups; a congruence group's members share one
    position. A value-range sub-node contributes the bounded slice of its own
    alphabet, so `{{@i}..f}` is the first six case-fold letter groups. A node's
    own exclusions are removed from the symbols it contributes."""
    if isinstance(node, t.CharRangeNode):
        lo, hi = ord(node.start), ord(node.end)
        if hi - lo + 1 > 0x10000:
            raise CompileError(
                f"Range {node.start!r}..{node.end!r} is too large "
                f"to use as a value bound"
            )
        return _drop_excluded([[chr(c)] for c in range(lo, hi + 1)], node.exclusions)
    if isinstance(node, t.UnionNode):
        groups = [g for o in node.options for g in _groups(o)]
        return _drop_excluded(groups, node.exclusions)
    if isinstance(node, t.LiteralNode):
        # One position whose single spelling is the whole literal — so a
        # multi-char token (`bc` in `{a,bc}`) folds as one unit, not per char.
        return [[node.content]]
    if isinstance(node, t.GroupClassNode):
        return [list(grp) for grp in node.groups]
    if isinstance(node, t.ValueRangeNode):
        return _sliced_groups(node)
    raise CompileError(f"Cannot use {type(node).__name__} as a value alphabet")


def _sliced_groups(node: t.ValueRangeNode) -> list[list[str]]:
    """The sub-alphabet a bounded range stands for: its alphabet's groups
    between the endpoint positions. Endpoints must be single positions."""
    if node.exclusions:
        raise CompileError("A range with exclusions cannot be a sub-alphabet")
    groups = _groups(node.alpha)
    alph = Alphabet(groups)
    for end in (node.lower, node.upper):
        if end is not None and len(end) != 1:
            raise CompileError(
                f"Sub-alphabet endpoint must be a single symbol, got {end!r}"
            )
    lo = alph.value(node.lower) if node.lower is not None else 0
    hi = alph.value(node.upper) if node.upper is not None else len(groups) - 1
    return groups[lo : hi + 1]


def _alphabet_of(node: t.SemanticNode, *, distinct: bool) -> Alphabet:
    return Alphabet(_groups(node), distinct=distinct)


def _value_alphabet(node: t.SemanticNode) -> Alphabet | RangeAlphabet:
    """The alphabet a bound's values are read in. A code-point range too large to
    materialize (`@uni`, the normalised `{x::y}` middle) becomes a virtual
    `RangeAlphabet`; everything else is the ordinary materialized `Alphabet`."""
    if isinstance(node, t.CharRangeNode):
        lo, hi = ord(node.start), ord(node.end)
        if hi - lo + 1 > MAX_SYMBOLS:
            return RangeAlphabet(lo, hi)
    return _alphabet_of(node, distinct=True)


# ── Value-bound view ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class _ValueView:
    alphabet: Alphabet | RangeAlphabet
    lo: int | None
    hi: int | None
    excluded: _ValueExcluder
    wmin: int
    wmax: int | None


def _value_view(node: t.ValueRangeNode) -> _ValueView:
    """The value-arithmetic view of a `{floor:alphabet:ceiling}` bound.

    The two written endpoint widths set the field-width window: with both present
    it is `[min, max]` of the widths; an omitted ceiling opens the top (wmax None),
    an omitted floor lets the value start at width 1. Leading zero-padding inside
    the window is allowed, so `{000:@d:9}` matches `9`, `09`, and `009`.
    """
    alph = _value_alphabet(node.alpha)
    lo = alph.value(node.lower) if node.lower is not None else None
    hi = alph.value(node.upper) if node.upper is not None else None
    wf = len(node.lower) if node.lower is not None else None
    wc = len(node.upper) if node.upper is not None else None
    if wf is not None and wc is not None:
        wmin, wmax = min(wf, wc), max(wf, wc)
    elif wf is not None:  # open ceiling — any width at or above the floor's
        wmin, wmax = wf, None
    else:  # open floor — value starts at 0, up to the ceiling's width
        wmin, wmax = 1, wc
    return _ValueView(alph, lo, hi, _ValueExcluder(node.exclusions, alph), wmin, wmax)


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
        self._excl = _excluder(node.exclusions)

    def match(self, text: str, pos: int) -> int | None:
        if pos >= len(text):
            return None
        ch = text[pos]
        if not (self.start <= ch <= self.end):
            return None
        if self._excl is not None and self._excl(ch):
            return None
        return pos + 1


class _ValueRange(_Base):
    """Width-window value match for a `{floor:alphabet:ceiling}` bound: the value
    lies in [floor, ceiling] and the written width lies in the bound's width
    window. Leading zero-padding inside the window is allowed, and the longest
    valid width wins."""

    __slots__ = ("view",)

    def __init__(self, view: _ValueView):
        self.view = view

    @property
    def value_alphabet(self) -> Alphabet | RangeAlphabet:
        return self.view.alphabet

    def match(self, text: str, pos: int) -> int | None:
        v = self.view
        n = len(text)
        end = pos
        while end < n and text[end] in v.alphabet:
            end += 1
        avail = end - pos
        top = avail if v.wmax is None else min(v.wmax, avail)
        for width in range(top, v.wmin - 1, -1):
            value = v.alphabet.value(text[pos : pos + width])
            if (v.lo is not None and value < v.lo) or (
                v.hi is not None and value > v.hi
            ):
                continue
            if v.excluded(value):
                continue
            return pos + width
        return None


class _Union(_Base):
    __slots__ = ("options", "_excl")

    def __init__(self, node: t.UnionNode):
        self.options = [lower(o) for o in node.options]
        self._excl = _excluder(node.exclusions)

    def match(self, text: str, pos: int) -> int | None:
        excl = self._excl
        for arm in self.options:
            end = arm.match(text, pos)
            if end is not None and (excl is None or not excl(text[pos:end])):
                return end
        return None


def _lower_union(node: t.UnionNode) -> Matcher:
    """A union of pure alphabets is itself one alphabet: merge the arms' ordered
    groups into a single folded class so a mixed run (`{a..z,A..Z}` over "aBc")
    matches as one unit and value/repetition see one axis. Token or complement
    arms have no group form, so those fall back to arm-by-arm `_Union`."""
    try:
        groups = _groups(node)
    except CompileError:
        return _Union(node)
    excl = _Excluder(node.exclusions)
    if excl.singles or excl.ranges:
        groups = [[m for m in g if not excl(m)] for g in groups]
        groups = [g for g in groups if g]
    return _Group(groups)


class _Complement(_Base):
    """A single character the inner node does NOT match (one position). A run is
    `[count]`, and it repeats heterogeneously -- each rep is any such character --
    so `{!a}[1..]` is a run of non-`a` characters."""

    __slots__ = ("inner",)

    def __init__(self, node: t.ComplementNode):
        self.inner = lower(node.inner)

    def match(self, text: str, pos: int) -> int | None:
        if pos >= len(text) or self.inner.match(text, pos) is not None:
            return None
        return pos + 1

    def accepts(self, s: str) -> bool:
        return len(s) == 1 and self.inner.match(s, 0) is None

    def equal_unit(self, text: str, pos: int, first: str) -> int | None:
        return self.match(text, pos)  # any non-inner character, not just `first`


class _Group(_Base):
    """An ordered alphabet of congruence groups — each group a set of
    interchangeable faces of one point. A run stays in the matched member's
    group, with faces free: `{a,A}` is two singleton groups (so `{a,A}[2]` is
    aa/AA), while `{{a,A}}` is one two-face group (so `{{a,A}}[2]` is all four)
    and `{{a,A},{c,C}}[2]` is `&²`/`%²` — never crossing to another group."""

    __slots__ = ("members", "_singles")

    def __init__(self, groups: list[list[str]]):
        # (member, group_index) longest-first so multi-char members win.
        self.members = sorted(
            ((m, i) for i, grp in enumerate(groups) for m in grp if m),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )
        self._singles = (
            frozenset(m for m, _ in self.members)
            if all(len(m) == 1 for m, _ in self.members)
            else None
        )

    def match(self, text: str, pos: int) -> int | None:
        if pos >= len(text):
            return None
        singles = self._singles
        if singles is not None:  # all members single-char
            return pos + 1 if text[pos] in singles else None
        for m, _ in self.members:
            if text.startswith(m, pos):
                return pos + len(m)
        return None

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


class _Het(_Base):
    """The `{{U}}` object: one universe repeated with **every member free each
    position** (HMK.md §Repetition — `{{a..z}}[3]` is any three letters, each
    free). It wraps the lowered universe so a run's `equal_unit` is a fresh match
    of any member — unlike a bare alphabet of objects (`{{a,A},{c,C}}`), whose run
    stays within one congruence group. `_CharRange`/`_Union` already free their
    members this way; the wrapper also frees a `_Group` (a folded range union like
    `{{0..9,a..f}}`), whose own `equal_unit` would otherwise pin each rep to the
    first member's group."""

    __slots__ = ("inner",)

    def __init__(self, inner: Matcher):
        self.inner = inner

    @property
    def value_alphabet(self) -> "Alphabet | RangeAlphabet | None":
        return self.inner.value_alphabet

    def match(self, text: str, pos: int) -> int | None:
        return self.inner.match(text, pos)

    def accepts(self, s: str) -> bool:
        return self.inner.accepts(s)

    # equal_unit inherited from _Base = a fresh match → any member, each position.


def _lower_value_range(node: t.ValueRangeNode) -> Matcher:
    return _ValueRange(_value_view(node))


# ── Lowering registry ─────────────────────────────────────────────────────────

_LOWERINGS: dict[type, Callable[..., Matcher]] = {
    t.LiteralNode: lambda n: _Literal(n.content),
    t.CharRangeNode: _CharRange,
    t.ValueRangeNode: _lower_value_range,
    t.GroupClassNode: lambda n: _Group(n.groups),
    t.UnionNode: _lower_union,
    t.ComplementNode: _Complement,
    # Nested fallback (e.g. a `{{U}}` arm); the het flag is set at the element
    # level in `compile_pattern`, so here it lowers to the inner matcher.
    t.HeterogeneousNode: lambda n: lower(n.inner),
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
class AnchorEl:
    """A zero-width anchor — succeeds at a line/scope boundary without consuming
    or capturing. `at` is line_start / line_end / scope_start / scope_end."""

    at: str


@dataclass(slots=True)
class Reps:
    """A resolved repetition spec on an element. `allowed` (a `[a,b,c]` set)
    overrides the `min..max` step-range; `count_ref` (a `[#i]`) resolves to a
    group's rep count at match time."""

    min: int = 1
    max: int | None = 1
    step: int = 1
    allowed: frozenset[int] | None = None
    count_ref: int | None = None

    def accepts(self, k: int) -> bool:
        if self.allowed is not None:
            return k in self.allowed
        if k < self.min or (self.max is not None and k > self.max):
            return False
        return (k - self.min) % self.step == 0


@dataclass(slots=True)
class GroupEl:
    matcher: Matcher
    reps: Reps
    het: bool = False  # heterogeneous repetition ({{U}} or a complement)


@dataclass(slots=True)
class SeqGroupEl:
    """A grouping brace `{of{black}{quartz}}`: one capture group whose sub-element
    brace groups become its sub-captures. Matched by the loop, not a Matcher."""

    elements: "list[Element]"
    reps: Reps


@dataclass(slots=True)
class BackRefEl:
    """A self-reference `{$i}`: matches the literal text captured by group `i`.
    The referent is read from the running capture list at match time, so this is
    handled by the loop (which holds that state), not by a compile-time Matcher."""

    group: int
    reps: Reps


@dataclass(slots=True)
class CountRefEl:
    """A count-reference `{#i}`: matches the decimal repetition count of group
    `i`, read from the running capture list at match time (like `BackRefEl`)."""

    group: int
    reps: Reps


@dataclass(slots=True)
class StageRefEl:
    """A cross-stage reference `{N$M.K…}`: matches the text of pipeline stage `N`'s
    capture along `path` (empty path = whole match). The referent is read from the
    stages threaded into the matcher, so the loop — not a Matcher — handles it."""

    stage: int
    path: tuple[int, ...]
    reps: Reps


Element = (
    LiteralEl | AnchorEl | GroupEl | SeqGroupEl | BackRefEl | CountRefEl | StageRefEl
)


def _reps(count: t.CountSpec | None) -> Reps:
    """Resolve a parsed count into the engine's `Reps`."""
    if count is None:
        return Reps(1, 1)
    if isinstance(count, t.CountRefSpec):
        return Reps(count_ref=count.group)
    if isinstance(count, t.CountSet):
        vals = frozenset(count.values)
        return Reps(min=min(vals), max=max(vals), allowed=vals)
    return Reps(min=count.min, max=count.max, step=count.step)


def compile_pattern(root: t.RootNode) -> list[Element]:
    """Compile a resolved pattern tree into a flat list of executable elements."""
    elements: list[Element] = []
    for child in root.children:
        if isinstance(child, t.LeafNode):
            elements.append(LiteralEl(child.content))
        elif isinstance(child, t.BraceGroupNode):
            if child.semantic is None:
                raise CompileError(f"Unresolved brace group: {{{child.content}}}")
            reps = _reps(child.count)
            if isinstance(child.semantic, t.AnchorNode):
                elements.append(AnchorEl(child.semantic.at))
                continue
            if isinstance(child.semantic, t.SequenceNode):
                sub = compile_pattern(t.RootNode(children=child.semantic.children))
                elements.append(SeqGroupEl(sub, reps))
            elif isinstance(child.semantic, t.BackRefNode):
                elements.append(BackRefEl(child.semantic.group, reps))
            elif isinstance(child.semantic, t.CountRefNode):
                elements.append(CountRefEl(child.semantic.group, reps))
            elif isinstance(child.semantic, t.StageRefNode):
                elements.append(
                    StageRefEl(child.semantic.stage, child.semantic.path, reps)
                )
            elif isinstance(child.semantic, t.HeterogeneousNode):
                # `{{U}}`: one object, repeated with every member free per position
                # (`_Het` makes each rep a fresh match, even over a folded union).
                inner = _Het(lower(child.semantic.inner))
                elements.append(GroupEl(inner, reps, het=True))
            else:
                # A run repeats one **point**, faces free within it: a congruence
                # class (`GroupClassNode`) stays in the matched member's group
                # (`{{a,A},{c,C}}[2]` is `&²`/`%²`), and a complement draws any
                # non-inner char each rep. Both are the group-based continuation.
                het = isinstance(child.semantic, (t.ComplementNode, t.GroupClassNode))
                elements.append(GroupEl(lower(child.semantic), reps, het=het))
        else:
            raise CompileError(f"Unexpected node in pattern: {type(child).__name__}")
    return elements
