"""The match loop — generic over compiled `Element`s.

This file knows nothing about HMK node types. It scans a list of `Element`s
(literals and capturing groups) left to right, builds `Capture`s, and emits
`Match`es. All construct-specific behaviour lives behind the `Matcher`
interface, decided once at compile time in `_compile.py`.
"""

from __future__ import annotations

from marky.engine._compile import (
    BackRefEl,
    CountRefEl,
    Element,
    GroupEl,
    LiteralEl,
    SeqGroupEl,
    StageRefEl,
)
from marky.engine._types import Capture, Match


class _State:
    """Captures accumulated during one match attempt, with absolute spans.

    `root` is the top-level state shared by every nested sub-match, kept so the
    rebasing in `_finalize` can flatten the whole tree against the match start.
    `stages` are the earlier pipeline matches, held on the root so a cross-stage
    reference (`{N$M}`) can resolve stage N's capture during the match."""

    __slots__ = ("captures", "root", "stages")

    def __init__(
        self, root: "_State | None" = None, stages: tuple[Match, ...] = ()
    ) -> None:
        self.captures: list[Capture] = []
        self.root = root if root is not None else self
        self.stages = stages


def find_matches(
    pattern: list[Element], text: str, stages: tuple[Match, ...] = ()
) -> list[Match]:
    matches: list[Match] = []
    n = len(text)
    pos = 0
    while pos < n:
        state = _State(stages=stages)
        end = _match_elements(pattern, text, pos, state)
        if end is not None and end > pos:
            matches.append(_finalize(text, pos, end, state))
            pos = end
        else:
            pos += 1
    return matches


def _finalize(text: str, start: int, end: int, state: _State) -> Match:
    # Spans are accumulated absolute; shift them to be match-relative. The
    # captures belong to this match alone, so rebase in place rather than
    # allocating a parallel tree.
    def rebase(c: Capture) -> None:
        c.span = (c.span[0] - start, c.span[1] - start)
        for s in c.subs:
            rebase(s)

    for c in state.captures:
        rebase(c)
    return Match(text[start:end], start, end, state.captures)


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


def _reps_bounds(el: Element, state: _State) -> tuple[int, int | None] | None:
    """Effective (min_reps, max_reps) for a repeatable element. A `[#i]` count
    (`count_ref` set) resolves to group i's exact repetition count at match time;
    an undefined referenced group returns None, failing the element."""
    ref = el.count_ref
    if ref is None:
        return el.min_reps, el.max_reps
    caps = state.root.captures
    if ref >= len(caps):
        return None
    k = len(caps[ref].reps)
    return k, k


def _match_element(el: Element, text: str, pos: int, state: _State) -> int | None:
    # LiteralEl is by far the most common element, so keep it inline; everything
    # else dispatches on exact type through _DISPATCH (built at module load).
    if type(el) is LiteralEl:
        s = el.text
        return pos + len(s) if text[pos : pos + len(s)] == s else None
    return _DISPATCH[type(el)](el, text, pos, state)


# ── Self-references `{$i}` / `{#i}`: match a value read from an earlier group ───


def _match_referent(
    referent: str | None,
    min_reps: int,
    max_reps: int | None,
    text: str,
    pos: int,
    state: _State,
) -> int | None:
    """Match `referent` (a value pulled from the running captures), repeated per
    the count. `referent is None` means the referenced group is undefined."""

    def record(end: int, reps: list[str]) -> int:
        state.captures.append(Capture(text[pos:end], (pos, end), reps))
        return end

    if referent is None:
        return record(pos, []) if min_reps == 0 else None

    reps: list[str] = []
    current = pos
    while max_reps is None or len(reps) < max_reps:
        if not (referent and text.startswith(referent, current)):
            break
        reps.append(referent)
        current += len(referent)
    if len(reps) >= max(min_reps, 1):
        return record(current, reps)
    return record(pos, []) if min_reps == 0 else None


def _match_back_ref(el: BackRefEl, text: str, pos: int, state: _State) -> int | None:
    bounds = _reps_bounds(el, state)
    if bounds is None:
        return None
    # The referent is the text group i captured; an unrecorded group is undefined.
    root_caps = state.root.captures
    referent = root_caps[el.group].text if el.group < len(root_caps) else None
    return _match_referent(referent, bounds[0], bounds[1], text, pos, state)


def _match_count_ref(el: CountRefEl, text: str, pos: int, state: _State) -> int | None:
    bounds = _reps_bounds(el, state)
    if bounds is None:
        return None
    # The referent is group i's decimal repetition count (len of its rep pieces).
    root_caps = state.root.captures
    referent = str(len(root_caps[el.group].reps)) if el.group < len(root_caps) else None
    return _match_referent(referent, bounds[0], bounds[1], text, pos, state)


def _stage_referent(stages: tuple[Match, ...], stage: int, path: tuple[int, ...]):
    """The text of pipeline `stage`'s capture along `path` (empty path = whole
    match), or None if any index is out of range / the stage doesn't exist."""
    if not 0 <= stage < len(stages):
        return None
    match = stages[stage]
    if not path:
        return match.text
    cap = match.capture_at(path)
    return cap.text if cap is not None else None


def _match_stage_ref(el: StageRefEl, text: str, pos: int, state: _State) -> int | None:
    bounds = _reps_bounds(el, state)
    if bounds is None:
        return None
    referent = _stage_referent(state.root.stages, el.stage, el.path)
    return _match_referent(referent, bounds[0], bounds[1], text, pos, state)


# ── Grouping brace: one capture whose sub-elements are sub-captures ────────────


def _match_seq_group(el: SeqGroupEl, text: str, pos: int, state: _State) -> int | None:
    bounds = _reps_bounds(el, state)
    if bounds is None:
        return None
    min_reps, max_reps = bounds

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
    bounds = _reps_bounds(el, state)
    if bounds is None:
        return None
    min_reps, max_reps = bounds

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


# Exact-type dispatch for _match_element; GroupEl is the generic fall-through.
_DISPATCH = {
    SeqGroupEl: _match_seq_group,
    BackRefEl: _match_back_ref,
    CountRefEl: _match_count_ref,
    StageRefEl: _match_stage_ref,
    GroupEl: _match_group,
}
