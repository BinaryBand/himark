"""The match loop — generic over compiled `Element`s.

This file knows nothing about HMK node types. It scans a list of `Element`s
(literals and capturing groups) left to right and emits `Match`es. Matching is
**backtracking** via continuation passing: each element offers its candidate
ends in priority order (greedy: longest first; lazy: shortest first) and asks
the continuation — the rest of the pattern — to match from each, taking the
first that succeeds. Captures are appended to a flat list and rolled back by
truncation when a branch fails.
"""

from __future__ import annotations

from collections.abc import Callable

from marky.engine._compile import (
    AnchorEl,
    BackRefEl,
    CountRefEl,
    Element,
    GroupEl,
    LiteralEl,
    Reps,
    SeqGroupEl,
    StageRefEl,
)
from marky.engine._types import Capture, Match

# A continuation: "match the rest of the pattern from this position", or None.
Cont = Callable[[int], "int | None"]


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
        end = _match_seq(pattern, 0, text, pos, state)
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


# ── Sequence matching (the continuation chain) ────────────────────────────────


def _match_seq(
    elements: list[Element], idx: int, text: str, pos: int, state: _State
) -> int | None:
    """Match `elements[idx:]` from `pos`, backtracking through each element's
    candidate ends. Returns the end of a full match, or None."""
    if idx >= len(elements):
        return pos

    def cont(end: int) -> int | None:
        return _match_seq(elements, idx + 1, text, end, state)

    el = elements[idx]
    if type(el) is LiteralEl:  # by far the most common element — inline it
        s = el.text
        if text[pos : pos + len(s)] == s:
            return cont(pos + len(s))
        return None
    if type(el) is AnchorEl:  # zero-width, non-capturing
        ok = pos == 0 if el.at == "start" else pos == len(text)
        return cont(pos) if ok else None
    return _DISPATCH[type(el)](el, text, pos, state, cont)


def _resolve_reps(reps: Reps, state: _State) -> Reps | None:
    """Resolve a `[#i]` reference to a fixed count; otherwise return `reps` as is.
    An undefined referenced group returns None, failing the element."""
    if reps.count_ref is None:
        return reps
    caps = state.root.captures
    if reps.count_ref >= len(caps):
        return None
    k = len(caps[reps.count_ref].reps)
    return Reps(min=k, max=k)


def _counts(reps: Reps, built: int) -> list[int]:
    """The acceptable rep counts in `0..built`, in priority order: greedy is
    longest-first, lazy shortest-first."""
    ks = [k for k in range(1, built + 1) if reps.accepts(k)]
    ks.sort(reverse=not reps.lazy)
    if reps.accepts(0):  # the zero-rep option is the laziest — tried last by greedy
        ks.append(0) if not reps.lazy else ks.insert(0, 0)
    return ks


# ── Self-references `{$i}` / `{#i}` / `{N$M}`: a value read from earlier state ──


def _referent_run(text: str, pos: int, referent: str, cap: int | None) -> list[int]:
    """Ends after 1, 2, … contiguous copies of `referent` at `pos` (up to `cap`)."""
    ends: list[int] = []
    current = pos
    while (
        (cap is None or len(ends) < cap)
        and referent
        and text.startswith(referent, current)
    ):
        current += len(referent)
        ends.append(current)
    return ends


def _match_referent(
    referent: str | None, reps: Reps, text: str, pos: int, state: _State, cont: Cont
) -> int | None:
    """Match `referent` (a value pulled from running state) per `reps`, then the
    continuation. `referent is None` means the referenced value is undefined."""
    caps = state.captures
    ends = [pos, *_referent_run(text, pos, referent, reps.max)] if referent else [pos]

    def attempt(k: int) -> int | None:
        end = ends[k]
        mark = len(caps)
        caps.append(
            Capture(text[pos:end], (pos, end), [referent] * k if referent else [])
        )
        r = cont(end)
        if r is not None:
            return r
        del caps[mark:]
        return None

    for k in _counts(reps, len(ends) - 1):
        r = attempt(k)
        if r is not None:
            return r
    return None


def _match_back_ref(el: BackRefEl, text: str, pos: int, state: _State, cont: Cont):
    reps = _resolve_reps(el.reps, state)
    if reps is None:
        return None
    caps = state.root.captures
    referent = caps[el.group].text if el.group < len(caps) else None
    return _match_referent(referent, reps, text, pos, state, cont)


def _match_count_ref(el: CountRefEl, text: str, pos: int, state: _State, cont: Cont):
    reps = _resolve_reps(el.reps, state)
    if reps is None:
        return None
    caps = state.root.captures
    referent = str(len(caps[el.group].reps)) if el.group < len(caps) else None
    return _match_referent(referent, reps, text, pos, state, cont)


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


def _match_stage_ref(el: StageRefEl, text: str, pos: int, state: _State, cont: Cont):
    reps = _resolve_reps(el.reps, state)
    if reps is None:
        return None
    referent = _stage_referent(state.root.stages, el.stage, el.path)
    return _match_referent(referent, reps, text, pos, state, cont)


# ── Grouping brace: one capture whose sub-elements are sub-captures ────────────


def _match_seq_group(el: SeqGroupEl, text: str, pos: int, state: _State, cont: Cont):
    reps = _resolve_reps(el.reps, state)
    if reps is None:
        return None
    caps = state.captures

    # A grouping brace is a *shape*: each iteration re-matches that shape, its
    # content free between reps (the cells of a row, the rows of a table). Build
    # the maximal run of shape-matches; each carries its own sub-captures.
    runs: list[tuple[int, list[Capture]]] = []
    current = pos
    while reps.max is None or len(runs) < reps.max:
        sub = _State(root=state.root)
        end = _match_seq(el.elements, 0, text, current, sub)
        if end is None or end == current:
            break
        runs.append((end, sub.captures))
        current = end

    def attempt(k: int) -> int | None:
        end = pos if k == 0 else runs[k - 1][0]
        rep_texts = [
            text[(pos if i == 0 else runs[i - 1][0]) : runs[i][0]] for i in range(k)
        ]
        subs = [c for i in range(k) for c in runs[i][1]]
        mark = len(caps)
        caps.append(Capture(text[pos:end], (pos, end), rep_texts, subs))
        r = cont(end)
        if r is not None:
            return r
        del caps[mark:]
        return None

    for k in _counts(reps, len(runs)):
        r = attempt(k)
        if r is not None:
            return r
    return None


# ── Capturing group with value-equal repetition ───────────────────────────────


def _match_group(el: GroupEl, text: str, pos: int, state: _State, cont: Cont):
    reps = _resolve_reps(el.reps, state)
    if reps is None:
        return None
    caps = state.captures

    def attempt(end: int, rep_list: list[str]) -> int | None:
        mark = len(caps)
        caps.append(Capture(text[pos:end], (pos, end), rep_list))
        r = cont(end)
        if r is not None:
            return r
        del caps[mark:]
        return None

    greedy_end = el.matcher.match(text, pos)
    if greedy_end is None or greedy_end == pos:
        return attempt(pos, []) if reps.accepts(0) else None

    # The first unit need not be greedy-maximal: a shorter first unit may let the
    # remainder split into equal repetitions ("2525" -> 25+25). Try unit lengths
    # longest-first; within each, the run's acceptable counts in priority order.
    # A bare `{U}[n]` repeats **homogeneously** (the same string); a heterogeneous
    # `{{U}}[n]` / complement repeats via the matcher's `equal_unit`.
    het = el.het
    for unit_len in range(greedy_end - pos, 0, -1):
        first = text[pos : pos + unit_len]
        if not el.matcher.accepts(first):
            continue
        rep_list = [first]
        ends = [pos + unit_len]
        current = pos + unit_len
        while reps.max is None or len(rep_list) < reps.max:
            if het:
                nxt = el.matcher.equal_unit(text, current, first)
            elif text.startswith(first, current):
                nxt = current + len(first)
            else:
                nxt = None
            if nxt is None:
                break
            rep_list.append(text[current:nxt])
            ends.append(nxt)
            current = nxt
        for k in _counts(reps, len(rep_list)):
            end = pos if k == 0 else ends[k - 1]
            r = attempt(end, rep_list[:k])
            if r is not None:
                return r
    return attempt(pos, []) if reps.accepts(0) else None


# Continuation-passing dispatch; GroupEl is the generic fall-through.
_DISPATCH: dict[type, Callable[..., int | None]] = {
    SeqGroupEl: _match_seq_group,
    BackRefEl: _match_back_ref,
    CountRefEl: _match_count_ref,
    StageRefEl: _match_stage_ref,
    GroupEl: _match_group,
}
