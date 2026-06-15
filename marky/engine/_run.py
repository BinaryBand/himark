"""The match loop — generic over compiled `Element`s.

This file knows nothing about HMK node types. It scans a list of `Element`s
(literals and capturing groups) left to right, builds `Capture`s, and emits
`Match`es. All construct-specific behaviour lives behind the `Matcher`
interface, decided once at compile time in `_compile.py`.
"""

from __future__ import annotations

from marky.engine._compile import Element, GroupEl, LiteralEl, SeqGroupEl
from marky.engine._types import Capture, Match


class _State:
    """Captures accumulated during one match attempt, with absolute spans.

    `root` is the top-level state shared by every nested sub-match, kept so the
    rebasing in `_finalize` can flatten the whole tree against the match start."""

    __slots__ = ("captures", "root")

    def __init__(self, root: "_State | None" = None) -> None:
        self.captures: list[Capture] = []
        self.root = root if root is not None else self


def find_matches(pattern: list[Element], text: str) -> list[Match]:
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
    def rebase(c: Capture) -> Capture:
        return Capture(
            c.text,
            (c.span[0] - start, c.span[1] - start),
            c.reps,
            [rebase(s) for s in c.subs],
        )

    return Match(text[start:end], start, end, [rebase(c) for c in state.captures])


# ── Sequence matching ─────────────────────────────────────────────────────────


def _match_elements(
    elements: list[Element], text: str, pos: int, state: _State
) -> int | None:
    current = pos
    for el in elements:
        end = _match_element(el, text, current, state)
        if end is None:
            return None
        current = end
    return current


def _match_element(el: Element, text: str, pos: int, state: _State) -> int | None:
    if isinstance(el, LiteralEl):
        s = el.text
        return pos + len(s) if text[pos : pos + len(s)] == s else None
    if isinstance(el, SeqGroupEl):
        return _match_seq_group(el, text, pos, state)
    return _match_group(el, text, pos, state)


# ── Grouping brace: one capture whose sub-elements are sub-captures ────────────


def _match_seq_group(el: SeqGroupEl, text: str, pos: int, state: _State) -> int | None:
    min_reps, max_reps = el.min_reps, el.max_reps

    def once(p: int) -> tuple[int, list[Capture]] | None:
        sub = _State(root=state.root)
        end = _match_elements(el.elements, text, p, sub)
        return None if end is None else (end, sub.captures)

    def record(end: int, reps: list[str], subs: list[Capture]) -> int:
        state.captures.append(Capture(text[pos:end], (pos, end), reps, subs))
        return end

    first = once(pos)
    if first is None or first[0] == pos:
        return record(pos, [], []) if min_reps == 0 else None

    end, subs = first
    if max_reps == 1:
        return record(end, [text[pos:end]], subs)

    # Structural repetition: a grouping brace is a *shape*, so each iteration
    # only has to re-match that shape — its content may differ between reps (the
    # cells of a row, the rows of a table). Every iteration's sub-captures are
    # kept, in document order. (Atomic classes still repeat by *value*; that
    # stays in _match_group.)
    reps = [text[pos:end]]
    all_subs = list(subs)
    current = end
    while max_reps is None or len(reps) < max_reps:
        nxt = once(current)
        if nxt is None or nxt[0] == current:  # no further match / zero-width
            break
        reps.append(text[current : nxt[0]])
        all_subs.extend(nxt[1])
        current = nxt[0]
    if len(reps) >= min_reps:
        return record(current, reps, all_subs)
    return record(pos, [], []) if min_reps == 0 else None


# ── Capturing group with value-equal repetition ───────────────────────────────


def _match_group(el: GroupEl, text: str, pos: int, state: _State) -> int | None:
    min_reps, max_reps = el.min_reps, el.max_reps

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
