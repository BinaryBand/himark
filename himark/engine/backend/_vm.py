"""Flat opcode VM — the run loop for compiled Himark patterns.

This file is the *engine*: it scans a flat list of opcodes left-to-right,
backtracking through candidate ends, and emits ``Match``\ es.  It knows nothing
about the grammar, AST nodes, or ``Element`` types — just opcodes and strings.

Matching is **backtracking** via continuation passing: each instruction offers
its candidate ends greedily (longest first) and asks the continuation — the
rest of the program — to match from each, taking the first that succeeds.
Captures are appended to a flat list and rolled back by truncation when a
branch fails.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from himark.models.opcodes import (
    ANCHOR,
    BACK_REF,
    CHAR,
    COUNT_REF,
    DYN_RANGE,
    GROUP,
    LIT,
    SEQ_GROUP,
    STAGE_REF,
    VALUE_RANGE,
    Instruction,
    Program,
    Reps,
    reps_from_tuple,
)
from himark.engine.backend._types import Capture, Match
from himark.models.alphabet import Alphabet, RangeAlphabet

# A continuation: "match the rest of the program from this position", or None.
Cont = Callable[[int], "int | None"]


class _State:
    """Captures accumulated during one match attempt, with absolute spans.

    ``root`` is the top-level state shared by every nested sub-match, kept so
    the rebasing in ``_finalize`` can flatten the whole tree against the match
    start.  ``stages`` are the earlier pipeline matches, held on the root so a
    cross-stage reference (``{N$M}``) can resolve stage N's capture during the
    match.
    """

    __slots__ = ("captures", "root", "stages")

    def __init__(
        self, root: "_State | None" = None, stages: tuple[Match, ...] = ()
    ) -> None:
        self.captures: list[Capture] = []
        self.root = root if root is not None else self
        self.stages = stages


# ── Public API ─────────────────────────────────────────────────────────────────


def find_matches(
    program: Program,
    text: str,
    stages: tuple[Match, ...] = (),
    start: int = 0,
    stop: int | None = None,
) -> list[Match]:
    """All matches of ``program`` in ``text``.  A match may *begin* only in
    ``[start, stop)`` (``stop is None`` = to the end); it still reads forward
    freely past ``stop``, so a match starting inside the window but extending
    beyond it is found in full.
    """
    matches: list[Match] = []
    elements = list(program.elements)  # mutable for reversed iteration when needed
    n = len(text)
    limit = n if stop is None else min(stop, n)
    pos = start
    while pos < limit:
        state = _State(stages=stages)
        end = _run_program(elements, 0, text, pos, state)
        if end is not None and end > pos:
            matches.append(_finalize(text, pos, end, state))
            pos = end
        else:
            pos += 1
    return matches


# ── Program execution (the continuation chain) ────────────────────────────────


def _run_program(
    elements: list[Instruction], idx: int, text: str, pos: int, state: _State
) -> int | None:
    """Execute ``elements[idx:]`` from ``pos``, backtracking through each
    element's candidate ends.  Returns the end of a full match, or None.
    """
    if idx >= len(elements):
        return pos

    def cont(end: int) -> int | None:
        return _run_program(elements, idx + 1, text, end, state)

    opcode, *args = elements[idx]

    if opcode == LIT:
        s: str = args[0]
        if text[pos : pos + len(s)] == s:
            return cont(pos + len(s))
        return None

    if opcode == ANCHOR:
        kind: int = args[0]
        ok = _check_anchor(kind, text, pos)
        return cont(pos) if ok else None

    if opcode == CHAR:
        lo, hi, excl_list, reps_tuple = args
        reps = _resolve_reps(reps_from_tuple(reps_tuple), state)
        if reps is None:
            return None
        return _match_char_range(
            text, pos, lo, hi, excl_list, reps, state, cont
        )

    if opcode == GROUP:
        groups, het, reps_tuple = args
        reps = _resolve_reps(reps_from_tuple(reps_tuple), state)
        if reps is None:
            return None
        return _match_group(text, pos, groups, het, reps, state, cont)

    if opcode == BACK_REF:
        group, reps_tuple = args
        reps = _resolve_reps(reps_from_tuple(reps_tuple), state)
        if reps is None:
            return None
        caps = state.root.captures
        referent = _cap_text(caps[group], text) if group < len(caps) else None
        return _match_referent(referent, reps, text, pos, state, cont)

    if opcode == COUNT_REF:
        group, reps_tuple = args
        reps = _resolve_reps(reps_from_tuple(reps_tuple), state)
        if reps is None:
            return None
        caps = state.root.captures
        referent = (
            str(_rep_count(caps[group])) if group < len(caps) else None
        )
        return _match_referent(referent, reps, text, pos, state, cont)

    if opcode == STAGE_REF:
        stage, path, reps_tuple = args
        reps = _resolve_reps(reps_from_tuple(reps_tuple), state)
        if reps is None:
            return None
        referent = _stage_referent(state.root.stages, stage, tuple(path))
        return _match_referent(referent, reps, text, pos, state, cont)

    if opcode == VALUE_RANGE:
        alphabet_desc, lo_val, hi_val, wmin, wmax, excl_list, reps_tuple = args
        reps = _resolve_reps(reps_from_tuple(reps_tuple), state)
        if reps is None:
            return None
        alph = _make_alphabet(alphabet_desc)
        desc = ("value", alph, lo_val, hi_val, wmin, wmax, excl_list)
        return _run_matcher(desc, reps, state, text, pos, cont, alphabet=alph)

    if opcode == DYN_RANGE:
        (
            alphabet_desc,
            lo_static,
            hi_static,
            lo_ref,
            hi_ref,
            excl_list,
            reps_tuple,
        ) = args
        reps = _resolve_reps(reps_from_tuple(reps_tuple), state)
        if reps is None:
            return None
        # Resolve dynamic endpoints from capture state
        lower = lo_static if lo_ref is None else _endpoint_text(lo_ref, state, text)
        upper = hi_static if hi_ref is None else _endpoint_text(hi_ref, state, text)
        if (lo_ref is not None and lower is None) or (
            hi_ref is not None and upper is None
        ):
            return None  # a referenced endpoint is undefined
        matcher_desc = _build_dyn_matcher_desc(alphabet_desc, lower, upper, excl_list)
        if matcher_desc is None:
            return None
        return _run_matcher(matcher_desc, reps, state, text, pos, cont)

    if opcode == SEQ_GROUP:
        children, reps_tuple = args
        reps = _resolve_reps(reps_from_tuple(reps_tuple), state)
        if reps is None:
            return None
        return _match_seq_group(children, reps, text, pos, state, cont)

    raise ValueError(f"Unknown opcode: {opcode}")


# ── Anchor ─────────────────────────────────────────────────────────────────────


def _check_anchor(kind: int, text: str, pos: int) -> bool:
    """Check zero-width anchor at ``pos``.  Kind: line_start=0, line_end=1,
    doc_start=2, doc_end=3.
    """
    if kind == 0:  # line_start
        return pos == 0 or text[pos - 1] == "\n"
    if kind == 1:  # line_end
        return pos == len(text) or text[pos] == "\n"
    if kind == 2:  # doc_start
        return pos == 0
    # kind == 3: doc_end
    return pos == len(text)


# ── Char range matcher (inlined, not a Matcher object) ────────────────────────


def _char_match(text: str, pos: int, lo: int, hi: int, excl: list[str]) -> int | None:
    """Match one char in ``[lo, hi]`` excluding ``excl`` strings.  Returns the
    end position, or None.
    """
    if pos >= len(text):
        return None
    ch = text[pos]
    if not (lo <= ord(ch) <= hi):
        return None
    if any(ch in e or e == ch for e in excl if len(e) == 1):
        return None
    # Multi-char exclusions are rare and checked separately
    for e in excl:
        if len(e) > 1 and text.startswith(e, pos):
            return None
    return pos + 1


def _match_char_range(
    text: str,
    pos: int,
    lo: int,
    hi: int,
    excl: list[str],
    reps: Reps,
    state: _State,
    cont: Cont,
) -> int | None:
    """Match a code-point range per ``reps``, capture as a RangeAlphabet group."""
    alphabet = RangeAlphabet(lo, hi)
    return _run_matcher(
        ("char_range", lo, hi, excl), reps, state, text, pos, cont, alphabet=alphabet
    )


# ── Group matcher ──────────────────────────────────────────────────────────────


def _group_unit(
    text: str, pos: int, groups: list[list[str]]
) -> tuple[int, int] | None:
    """Match one position from the group alphabet.  Returns ``(end, group_index)``
    or None.  Multi-char members tried first (longest-match)."""
    # Build sorted (member, group_index) list once — but for simplicity inline
    members = [
        (m, i) for i, grp in enumerate(groups) for m in grp if m
    ]
    members.sort(key=lambda x: len(x[0]), reverse=True)
    for m, idx in members:
        if text.startswith(m, pos):
            return pos + len(m), idx
    return None


def _group_accepts(s: str, groups: list[list[str]]) -> bool:
    """True if ``s`` is exactly one member of the groups."""
    members = {m for grp in groups for m in grp}
    return s in members


def _group_equal_unit(
    text: str, pos: int, first: str, groups: list[list[str]]
) -> int | None:
    """Match the next repetition where each face stays in the same congruence
    group as ``first``."""
    # Parse `first` into a sequence of group indices
    members = [
        (m, i) for i, grp in enumerate(groups) for m in grp if m
    ]
    members.sort(key=lambda x: len(x[0]), reverse=True)
    # Decompose first into group indices
    seq: list[int] = []
    i = 0
    while i < len(first):
        for m, idx in members:
            if first.startswith(m, i):
                seq.append(idx)
                i += len(m)
                break
        else:
            return None
    # Match same group indices at pos
    cur = pos
    for gidx in seq:
        for m, idx in members:
            if idx == gidx and text.startswith(m, cur):
                cur += len(m)
                break
        else:
            return None
    return cur


def _match_group(
    text: str,
    pos: int,
    groups: list[list[str]],
    het: bool,
    reps: Reps,
    state: _State,
    cont: Cont,
) -> int | None:
    """Match a group alphabet per ``reps``, capture with ``Alphabet(groups)``."""
    alphabet = Alphabet(groups)
    desc = ("group", groups, het)
    return _run_matcher(desc, reps, state, text, pos, cont, alphabet=alphabet)


# ── Value-range matcher (inlined) ─────────────────────────────────────────────


def _match_value(
    text: str, pos: int, alphabet, lo_val, hi_val, wmin, wmax, excl: list[str]
) -> int | None:
    """Width-window value match for a static value band.  Returns the greedy
    end position, or None.
    """
    if isinstance(alphabet, RangeAlphabet):
        n = len(text)
        end = pos
        while end < n and ord(text[end]) in range(alphabet.lo, alphabet.hi + 1):
            end += 1
    elif isinstance(alphabet, Alphabet):
        n = len(text)
        end = pos
        while end < n and text[end] in alphabet:
            end += 1
    else:
        return None

    avail = end - pos
    top = avail if wmax is None else min(wmax, avail)
    for width in range(top, wmin - 1, -1):
        val = alphabet.value(text[pos : pos + width])
        if (lo_val is not None and val < lo_val) or (hi_val is not None and val > hi_val):
            continue
        # Check exclusions
        if excl and any(text[pos : pos + width] == e for e in excl if len(e) > 1):
            continue
        return pos + width
    return None


def _build_dyn_matcher_desc(
    alphabet_desc, lower: str | None, upper: str | None, excl: list[str]
) -> tuple | None:
    """Build a matcher description for a dynamic value range.  ``alphabet_desc``
    is either ``("range", lo, hi)`` or ``("groups", groups)``."""
    if alphabet_desc[0] == "range":
        alph = RangeAlphabet(alphabet_desc[1], alphabet_desc[2])
    else:
        alph = Alphabet(alphabet_desc[1])

    try:
        lo_val = alph.value(lower) if lower is not None else None
        hi_val = alph.value(upper) if upper is not None else None
    except (KeyError, CompileError):
        return None

    wf, wc = (len(lower) if lower is not None else None), (
        len(upper) if upper is not None else None
    )
    if wf is not None and wc is not None:
        wmin, wmax = min(wf, wc), max(wf, wc)
    elif wf is not None:
        wmin, wmax = wf, None
    else:
        wmin, wmax = 1, wc
    return ("value", alph, lo_val, hi_val, wmin, wmax, excl)


# ── Shared matcher runner (backtracking + capture) ────────────────────────────


def _run_matcher(
    desc: tuple,
    reps: Reps,
    state: _State,
    text: str,
    pos: int,
    cont: Cont,
    alphabet=None,
) -> int | None:
    """Run a concrete matcher (encoded in ``desc``) per ``reps``, longest-first
    unit splitting, capture with ``alphabet``, then the continuation."""
    caps = state.captures

    def attempt(end: int, rep_list: list[str], k: int) -> int | None:
        mark = len(caps)
        caps.append(
            Capture("", (pos, end), rep_list, count=k,
                     alphabet=alphabet)
        )
        r = cont(end)
        if r is not None:
            return r
        del caps[mark:]
        return None

    # Match one unit
    first_end = _matcher_match(desc, text, pos)
    if first_end is None or first_end == pos:
        return attempt(pos, [], 0) if reps.accepts(0) else None

    # Try unit lengths longest-first
    for unit_len in range(first_end - pos, 0, -1):
        first = text[pos : pos + unit_len]
        if not _matcher_accepts(desc, first):
            continue
        rep_list = [first]
        ends = [pos + unit_len]
        current = pos + unit_len
        while reps.max is None or len(rep_list) < reps.max:
            nxt = _matcher_equal_unit(desc, text, current, first)
            if nxt is None:
                break
            rep_list.append(text[current:nxt])
            ends.append(nxt)
            current = nxt
        for k in _counts(reps, len(rep_list)):
            end = pos if k == 0 else ends[k - 1]
            r = attempt(end, rep_list, k)
            if r is not None:
                return r
    return attempt(pos, [], 0) if reps.accepts(0) else None


def _matcher_match(desc: tuple, text: str, pos: int) -> int | None:
    """Dispatch one unit match based on the description tuple."""
    kind = desc[0]
    if kind == "char_range":
        _, lo, hi, excl = desc
        return _char_match(text, pos, lo, hi, excl)
    if kind == "group":
        _, groups, _het = desc
        result = _group_unit(text, pos, groups)
        return result[0] if result else None
    if kind == "value":
        _, alph, lo_val, hi_val, wmin, wmax, excl = desc
        return _match_value(text, pos, alph, lo_val, hi_val, wmin, wmax, excl)
    return None


def _matcher_accepts(desc: tuple, s: str) -> bool:
    """True if ``s`` is exactly one unit of the matcher."""
    kind = desc[0]
    if kind == "char_range":
        _, lo, hi, excl = desc
        return (
            len(s) == 1
            and lo <= ord(s) <= hi
            and not any(e == s for e in excl if len(e) == 1)
        )
    if kind == "group":
        _, groups, _het = desc
        return _group_accepts(s, groups)
    if kind == "value":
        return _matcher_match(desc, s, 0) == len(s)
    return False


def _matcher_equal_unit(
    desc: tuple, text: str, pos: int, first: str
) -> int | None:
    """Match the next repetition equal-unit (homogeneous) or next group-member
    (heterogeneous)."""
    kind = desc[0]
    if kind == "char_range":
        # Homogeneous: same char
        if text.startswith(first, pos):
            return pos + len(first)
        return None
    if kind == "group":
        _, groups, het = desc
        if het:
            # Heterogeneous: any member, not necessarily same face
            return _matcher_match(desc, text, pos)
        # Homogeneous: same member string
        if text.startswith(first, pos):
            return pos + len(first)
        return None
    if kind == "value":
        # Value ranges are homogeneous: same value
        if text.startswith(first, pos):
            return pos + len(first)
        return None
    return None


# ── Self-references ────────────────────────────────────────────────────────────


def _cap_text(cap: Capture, text: str) -> str:
    """A capture's text, sliced on demand from its span."""
    return text[cap.span[0] : cap.span[1]]


def _rep_count(cap: Capture) -> int:
    """A capture's repetition count."""
    return cap.count if cap.count >= 0 else len(cap.reps)


def _referent_run(
    text: str, pos: int, referent: str, cap: int | None
) -> list[int]:
    """Ends after 1, 2, … contiguous copies of ``referent`` at ``pos``
    (up to ``cap``, or unbounded if None)."""
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
    referent: str | None,
    reps: Reps,
    text: str,
    pos: int,
    state: _State,
    cont: Cont,
) -> int | None:
    """Match ``referent`` per ``reps``, then the continuation."""
    caps = state.captures
    if referent == "":
        # An empty captured referent matches zero-width.
        mark = len(caps)
        caps.append(Capture("", (pos, pos), [""] * reps.min))
        r = cont(pos)
        if r is None:
            del caps[mark:]
        return r
    ends = (
        [pos, *_referent_run(text, pos, referent, reps.max)]
        if referent
        else [pos]
    )

    def attempt(k: int) -> int | None:
        end = ends[k]
        mark = len(caps)
        caps.append(
            Capture(
                text[pos:end],
                (pos, end),
                [referent] * k if referent else [],
            )
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


def _stage_referent(
    stages: tuple[Match, ...], stage: int, path: tuple[int, ...]
) -> str | None:
    """The text of pipeline ``stage``'s capture along ``path``, or None."""
    if not 0 <= stage < len(stages):
        return None
    match = stages[stage]
    if not path:
        return match.text
    cap = match.capture_at(path)
    return cap.text if cap is not None else None


def _endpoint_text(desc: tuple, state: _State, text: str) -> str | None:
    """Resolve a reference-endpoint descriptor to its captured text."""
    caps = state.root.captures
    kind = desc[0]
    if kind == "back":
        return _cap_text(caps[desc[1]], text) if desc[1] < len(caps) else None
    if kind == "count":
        return (
            str(_rep_count(caps[desc[1]])) if desc[1] < len(caps) else None
        )
    return _stage_referent(state.root.stages, desc[1], tuple(desc[2]))


# ── Sequence group (grouping brace) ────────────────────────────────────────────


def _match_seq_group(
    children: list[Instruction],
    reps: Reps,
    text: str,
    pos: int,
    state: _State,
    cont: Cont,
) -> int | None:
    """Match a grouping brace: repeat the sub-program per ``reps``."""
    caps = state.captures

    # Build the maximal run of shape-matches
    runs: list[tuple[int, list[Capture]]] = []
    current = pos
    while reps.max is None or len(runs) < reps.max:
        sub = _State(root=state.root)
        end = _run_program(children, 0, text, current, sub)
        if end is None or end == current:
            break
        runs.append((end, sub.captures))
        current = end

    def attempt(k: int) -> int | None:
        end = pos if k == 0 else runs[k - 1][0]
        rep_texts = [
            text[(pos if i == 0 else runs[i - 1][0]) : runs[i][0]]
            for i in range(k)
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


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_alphabet(alphabet_desc: tuple) -> Alphabet | RangeAlphabet:
    """Build an alphabet object from its serialised descriptor."""
    if alphabet_desc[0] == "range":
        return RangeAlphabet(alphabet_desc[1], alphabet_desc[2])
    return Alphabet(alphabet_desc[1])


def _resolve_reps(reps: Reps, state: _State) -> Reps | None:
    """Resolve a ``[#i]`` reference to a fixed count."""
    if reps.count_ref is None:
        return reps
    caps = state.root.captures
    if reps.count_ref >= len(caps):
        return None
    k = _rep_count(caps[reps.count_ref])
    return Reps(min=k, max=k)


def _counts(reps: Reps, built: int) -> list[int]:
    """Acceptable rep counts in ``0..built``, greedy (longest-first) priority."""
    ks = [k for k in range(built, 0, -1) if reps.accepts(k)]
    if reps.accepts(0):
        ks.append(0)
    return ks


def _finalize(text: str, start: int, end: int, state: _State) -> Match:
    """Settle each capture: trim deferred runs, shift spans to match-relative."""

    def settle(c: Capture) -> None:
        if c.count >= 0:
            c.reps = c.reps[: c.count]
        c.text = text[c.span[0] : c.span[1]]
        c.span = (c.span[0] - start, c.span[1] - start)
        for s in c.subs:
            settle(s)

    for c in state.captures:
        settle(c)
    return Match(text[start:end], start, end, state.captures)


class CompileError(Exception):
    """Raised when a value cannot be expressed in an alphabet."""
    pass