"""The match loop — generic over compiled `Element`s.

This file knows nothing about HMK node types. It scans a list of `Element`s
(literals and capturing groups) left to right and emits `Match`es. All
construct-specific behaviour lives behind the `Matcher` interface, decided once
at compile time in `_compile.py`.
"""

from __future__ import annotations

from marky.engine._compile import Element, GroupEl, LiteralEl
from marky.engine._types import Match


def find_matches(pattern: list[Element], text: str) -> list[Match]:
    matches: list[Match] = []
    n = len(text)
    pos = 0
    while pos < n:
        end = _match_elements(pattern, text, pos)
        if end is not None and end > pos:
            matches.append(Match(text[pos:end], pos, end))
            pos = end
        else:
            pos += 1
    return matches


# ── Sequence matching ─────────────────────────────────────────────────────────


def _match_elements(elements: list[Element], text: str, pos: int) -> int | None:
    current = pos
    for el in elements:
        end = _match_element(el, text, current)
        if end is None:
            return None
        current = end
    return current


def _match_element(el: Element, text: str, pos: int) -> int | None:
    if isinstance(el, LiteralEl):
        s = el.text
        return pos + len(s) if text[pos : pos + len(s)] == s else None
    return _match_group(el, text, pos)


# ── Group with value-equal repetition ─────────────────────────────────────────


def _match_group(el: GroupEl, text: str, pos: int) -> int | None:
    min_reps, max_reps = el.min_reps, el.max_reps

    greedy_end = el.matcher.match(text, pos)
    if greedy_end is None or greedy_end == pos:
        return pos if min_reps == 0 else None

    # Common case ({expr}, i.e. exactly one rep): the greedy match *is* the one
    # unit, so skip the length-backoff and equality machinery entirely.
    if max_reps == 1:
        return greedy_end

    # The first unit need not be greedy-maximal: a shorter first unit may let
    # the remainder split into equal repetitions ("2525" -> 25+25). Try lengths
    # longest-first and take the first that satisfies the count.
    for unit_len in range(greedy_end - pos, 0, -1):
        first = text[pos : pos + unit_len]
        if not el.matcher.accepts(first):
            continue
        reps = 1
        current = pos + unit_len
        while max_reps is None or reps < max_reps:
            nxt = el.matcher.equal_unit(text, current, first)
            if nxt is None:
                break
            reps += 1
            current = nxt
        if reps >= min_reps:
            return current

    return pos if min_reps == 0 else None
