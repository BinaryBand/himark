"""The match loop — generic over compiled `Element`s.

This file knows nothing about HMK node types. It scans a list of `Element`s
(literals, capturing groups, separators) left to right, builds `Capture`s, and
emits `Match`es. All construct-specific behaviour lives behind the `Matcher`
interface, decided once at compile time in `_compile.py`.
"""

from __future__ import annotations

from marky.engine._compile import Element, GroupEl, LiteralEl, SepEl
from marky.engine._types import Capture, Match


class _State:
    """Captures accumulated during one match attempt, with absolute spans.
    A snapshot is just the current count; restore truncates back to it."""

    __slots__ = ("captures",)

    def __init__(self) -> None:
        self.captures: list[Capture] = []

    def snapshot(self) -> int:
        return len(self.captures)

    def restore(self, mark: int) -> None:
        del self.captures[mark:]

    def count_of(self, index: int) -> int:
        return len(self.captures[index].reps) if index < len(self.captures) else 0


# ── Public API ────────────────────────────────────────────────────────────────


def find_matches(pattern: list[Element], text: str) -> list[Match]:
    # A lone separator splits the whole input rather than scanning for a match.
    if len(pattern) == 1 and isinstance(pattern[0], SepEl):
        return _split_by_separator(pattern[0], text)

    matches: list[Match] = []
    n = len(text)
    pos = 0
    while pos < n:
        state = _State()
        end = _match_elements(pattern, text, pos, state)
        if end is not None and end > pos:
            matches.append(_finalize(text, pos, end, state))
            pos = end
        else:
            pos += 1
    return matches


def _finalize(text: str, start: int, end: int, state: _State) -> Match:
    captures = [
        Capture(c.text, (c.span[0] - start, c.span[1] - start), c.reps)
        for c in state.captures
    ]
    return Match(text[start:end], start, end, captures)


def _split_by_separator(el: SepEl, text: str) -> list[Match]:
    if el.sep_class is not None:
        # Constrained span: the whole input must be one member of the class.
        return [Match(text, 0, len(text))] if el.sep_class.accepts(text) else []
    sep = el.sep_value or ""
    if not sep:
        return [Match(text, 0, len(text))] if text else []
    result, pos = [], 0
    for part in text.split(sep):
        result.append(Match(part, pos, pos + len(part)))
        pos += len(part) + len(sep)
    return result


# ── Sequence matching ─────────────────────────────────────────────────────────


def _match_elements(
    elements: list[Element], text: str, pos: int, state: _State
) -> int | None:
    current = pos
    i = 0
    while i < len(elements):
        el = elements[i]
        if isinstance(el, SepEl):
            return _match_separator(el, elements[i + 1 :], text, current, state)
        end = _match_element(el, text, current, state)
        if end is None:
            return None
        current = end
        i += 1
    return current


def _match_element(el: Element, text: str, pos: int, state: _State) -> int | None:
    if isinstance(el, LiteralEl):
        s = el.text
        return pos + len(s) if text[pos : pos + len(s)] == s else None
    if isinstance(el, GroupEl):
        return _match_group(el, text, pos, state)
    return None  # SepEl handled by the caller


# ── Capturing group with value-equal repetition ───────────────────────────────


def _match_group(el: GroupEl, text: str, pos: int, state: _State) -> int | None:
    min_reps, max_reps = el.min_reps, el.max_reps
    if el.count_ref is not None:
        min_reps = max_reps = state.count_of(el.count_ref)

    def record(end: int, reps: list[str]) -> int:
        state.captures.append(Capture(text[pos:end], (pos, end), reps))
        return end

    greedy_end = el.matcher.match(text, pos)
    if greedy_end is None or greedy_end == pos:
        return record(pos, []) if min_reps == 0 else None

    # Common case ({expr}, i.e. exactly one rep): the greedy match *is* the one
    # unit, so skip the length-backoff and equality machinery entirely.
    if max_reps == 1:
        return record(greedy_end, [text[pos:greedy_end]])

    # The first unit need not be greedy-maximal: a shorter first unit may let
    # the remainder split into equal repetitions ("2525" -> 25+25). Try lengths
    # longest-first and take the first that satisfies the count.
    for unit_len in range(greedy_end - pos, 0, -1):
        first = text[pos : pos + unit_len]
        if not el.matcher.accepts(first):
            continue
        reps = [first]
        current = pos + unit_len
        while max_reps is None or len(reps) < max_reps:
            nxt = el.matcher.equal_unit(text, current, first)
            if nxt is None:
                break
            reps.append(text[current:nxt])
            current = nxt
        if len(reps) >= min_reps:
            return record(current, reps)

    return record(pos, []) if min_reps == 0 else None


# ── Separator: lazy span between bounding context ──────────────────────────────


def _match_separator(
    el: SepEl, remaining: list[Element], text: str, pos: int, state: _State
) -> int | None:
    cls, sep_val = el.sep_class, el.sep_value

    if not remaining:
        span = text[pos:]
        if cls is not None and not cls.accepts(span):
            return None
        _insert_sep(state, state.snapshot(), span, pos, len(text), sep_val)
        return len(text)

    snap = state.snapshot()
    for n in range(len(text) - pos + 1):
        span = text[pos : pos + n]
        if cls is not None and not cls.accepts(span):
            continue
        state.restore(snap)
        end = _match_elements(remaining, text, pos + n, state)
        if end is not None:
            _insert_sep(state, snap, span, pos, pos + n, sep_val)
            return end
    state.restore(snap)
    return None


def _insert_sep(
    state: _State, mark: int, span: str, start: int, end: int, sep_val: str | None
) -> None:
    reps = span.split(sep_val) if sep_val else [span]
    state.captures.insert(mark, Capture(span, (start, end), reps))
