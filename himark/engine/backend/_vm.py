"""Flat opcode VM — the run loop for compiled Himark patterns.

This file is the *engine*: it scans a flat list of opcodes left-to-right,
backtracking through candidate ends, and emits ``Match`` objects.  It knows
nothing about the grammar, AST nodes, or ``Element`` types — just opcodes and
strings.

Matching is **backtracking** via continuation passing: each instruction offers
its candidate ends greedily (longest first) and asks the continuation — the
rest of the program — to match from each, taking the first that succeeds.
Captures are appended to a flat list and rolled back by truncation when a
branch fails.
"""

from __future__ import annotations

from collections.abc import Callable

from himark.models.opcodes import (
    ANCHOR,
    BACK_REF,
    CHAR,
    COMPLEMENT,
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
from himark.models.exceptions import CompileError

# A continuation: "match the rest of the program from this position", or None.
Cont = Callable[[int], "int | None"]


class _State:
    __slots__ = ("captures", "root", "stages")

    def __init__(
        self, root: "_State | None" = None, stages: tuple[Match, ...] = ()
    ) -> None:
        self.captures: list[Capture] = []
        self.root = root if root is not None else self
        self.stages = stages


# ── Public API ─────────────────────────────────────────────────────────────────


def find_matches(
    prepared: list[Instruction],
    text: str,
    stages: tuple[Match, ...] = (),
    start: int = 0,
    stop: int | None = None,
) -> list[Match]:
    """All matches in ``text`` of a program already lowered by ``prepare``."""
    matches: list[Match] = []
    n = len(text)
    limit = n if stop is None else min(stop, n)
    pos = start
    while pos < limit:
        state = _State(stages=stages)
        end = _run_program(prepared, 0, text, pos, state)
        if end is not None and end > pos:
            matches.append(_finalize(text, pos, end, state))
            pos = end
        else:
            pos += 1
    return matches


# ── One-time lowering: serialised opcodes → VM-ready instructions ──────────────
# The match loop runs an instruction many times (once per position, and again per
# backtrack), so anything it can re-derive from the operands is wasted work to do
# there. `prepare` does that derivation once, up front: it bakes the reps tuple into
# a `Reps`, builds an alphabet descriptor into an `Alphabet`, and pre-sorts a group's
# members. The Python backend calls it in `compile` (cached per program by the
# Runtime), so the hot loop only ever *interprets* baked operands. The serialised
# `Program` is untouched — it stays portable (JSON / pickle / the Rust seam).

# Opcodes whose last operand is a reps spec (so it is baked). LIT and ANCHOR carry no
# reps. The order of the other operands is unchanged — only their *values* are baked.
_REPS_OPCODES = frozenset(
    {CHAR, GROUP, COMPLEMENT, BACK_REF, COUNT_REF, STAGE_REF, VALUE_RANGE, DYN_RANGE, SEQ_GROUP}
)


def prepare(program: Program) -> list[Instruction]:
    """Lower a serialised ``Program`` into VM-ready instructions (see above)."""
    return _prepare_elements(program.elements)


def _prepare_elements(elements: tuple[Instruction, ...]) -> list[Instruction]:
    out: list[Instruction] = []
    for el in elements:
        opcode = el[0]
        if opcode not in _REPS_OPCODES:
            out.append(el)  # LIT / ANCHOR — nothing to bake
            continue
        args = list(el[1:])
        args[-1] = reps_from_tuple(args[-1])  # reps is always the last operand
        if opcode in (VALUE_RANGE, DYN_RANGE):
            args[0] = _make_alphabet(args[0])  # alphabet descriptor → Alphabet
        elif opcode == GROUP:
            args[0] = _GroupMatcher(args[0])  # groups → pre-sorted members + set
        elif opcode == SEQ_GROUP:
            args[0] = _prepare_elements(args[0])  # recurse into the sub-program
        out.append((opcode, *args))
    return out


# ── Program execution ─────────────────────────────────────────────────────────


def _run_program(
    elements: list[Instruction], idx: int, text: str, pos: int, state: _State
) -> int | None:
    if idx >= len(elements):
        return pos

    def cont(end: int) -> int | None:
        return _run_program(elements, idx + 1, text, end, state)

    # Operands are already baked by `prepare`: a `reps_spec` is a `Reps`, an alphabet
    # is an `Alphabet`, a GROUP carries a `_GroupMatcher`. The loop only interprets.
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
        lo, hi, excl_list, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        return _match_char_range(text, pos, lo, hi, excl_list, reps, state, cont)

    if opcode == GROUP:
        gm, het, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        return _match_group(text, pos, gm, het, reps, state, cont)

    if opcode == COMPLEMENT:
        inner_groups, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        return _match_complement(text, pos, inner_groups, reps, state, cont)

    if opcode == BACK_REF:
        group, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        caps = state.root.captures
        referent = _cap_text(caps[group], text) if group < len(caps) else None
        return _match_referent(referent, reps, text, pos, state, cont)

    if opcode == COUNT_REF:
        group, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        caps = state.root.captures
        referent = str(_rep_count(caps[group])) if group < len(caps) else None
        return _match_referent(referent, reps, text, pos, state, cont)

    if opcode == STAGE_REF:
        stage, path, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        referent = _stage_referent(state.root.stages, stage, tuple(path))
        return _match_referent(referent, reps, text, pos, state, cont)

    if opcode == VALUE_RANGE:
        alph, lo_val, hi_val, wmin, wmax, excl_list, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        desc = ("value", alph, lo_val, hi_val, wmin, wmax, excl_list)
        return _run_matcher(desc, reps, state, text, pos, cont, alphabet=alph)

    if opcode == DYN_RANGE:
        (
            alph, lo_static, hi_static,
            lo_ref, hi_ref, excl_list, reps_spec,
        ) = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        lower = lo_static if lo_ref is None else _endpoint_text(lo_ref, state, text)
        upper = hi_static if hi_ref is None else _endpoint_text(hi_ref, state, text)
        if (lo_ref is not None and lower is None) or (hi_ref is not None and upper is None):
            return None
        matcher_desc = _build_dyn_matcher_desc(alph, lower, upper, excl_list)
        if matcher_desc is None:
            return None
        return _run_matcher(matcher_desc, reps, state, text, pos, cont)

    if opcode == SEQ_GROUP:
        children, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        return _match_seq_group(children, reps, text, pos, state, cont)

    raise ValueError(f"Unknown opcode: {opcode}")


# ── Anchor ─────────────────────────────────────────────────────────────────────


def _check_anchor(kind: int, text: str, pos: int) -> bool:
    if kind == 0:
        return pos == 0 or text[pos - 1] == "\n"
    if kind == 1:
        return pos == len(text) or text[pos] == "\n"
    if kind == 2:
        return pos == 0
    return pos == len(text)


# ── Char range ─────────────────────────────────────────────────────────────────


def _char_match(text: str, pos: int, lo: int, hi: int, excl: list[str]) -> int | None:
    if pos >= len(text):
        return None
    ch = text[pos]
    if not (lo <= ord(ch) <= hi):
        return None
    for e in excl:
        if len(e) == 1:
            if e == ch:
                return None
        elif ".." in e:
            lo2, hi2 = e.split("..", 1)
            if lo2 <= ch <= hi2:
                return None
        elif text.startswith(e, pos):
            return None
    return pos + 1


def _match_char_range(
    text: str, pos: int, lo: int, hi: int, excl: list[str],
    reps: Reps, state: _State, cont: Cont,
) -> int | None:
    return _run_matcher(
        ("char_range", lo, hi, excl), reps, state, text, pos, cont, alphabet=None
    )


# ── Group matcher ──────────────────────────────────────────────────────────────


class _GroupMatcher:
    """A GROUP alphabet, lowered for the VM by `prepare`: members `(spelling, group
    index)` pre-sorted longest-first (so the longest match wins without re-sorting on
    every attempt), plus the set of spellings for the O(1) accept test."""

    __slots__ = ("members", "accept_set")

    def __init__(self, groups: list[list[str]]) -> None:
        members = [(m, i) for i, grp in enumerate(groups) for m in grp if m]
        members.sort(key=lambda x: len(x[0]), reverse=True)
        self.members = members
        self.accept_set = frozenset(m for m, _ in members)


def _group_unit(text: str, pos: int, gm: _GroupMatcher) -> tuple[int, int] | None:
    for m, idx in gm.members:
        if text.startswith(m, pos):
            return pos + len(m), idx
    return None


def _group_accepts(s: str, gm: _GroupMatcher) -> bool:
    return s in gm.accept_set


def _group_equal_unit(text: str, pos: int, first: str, gm: _GroupMatcher) -> int | None:
    members = gm.members
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
    text: str, pos: int, gm: "_GroupMatcher", het: bool,
    reps: Reps, state: _State, cont: Cont,
) -> int | None:
    # GROUP captures never carry a value alphabet — only VALUE_RANGE ops do.
    desc = ("group", gm, het)
    return _run_matcher(desc, reps, state, text, pos, cont, alphabet=None)


# ── Complement matcher ─────────────────────────────────────────────────────────


def _complement_match(text: str, pos: int, inner_groups: list[list[str]]) -> int | None:
    if pos >= len(text):
        return None
    # Reject a single character that is in the inner set, AND reject any position
    # where a multi-char inner member starts (a "break" — §Subtraction).
    for grp in inner_groups:
        for m in grp:
            if not m:
                continue
            if text.startswith(m, pos):
                return None
    return pos + 1


def _match_complement(
    text: str, pos: int, inner_groups: list[list[str]],
    reps: Reps, state: _State, cont: Cont,
) -> int | None:
    desc = ("complement", inner_groups)
    return _run_matcher(desc, reps, state, text, pos, cont, alphabet=None)


# ── Value-range matcher ────────────────────────────────────────────────────────


def _match_value(
    text: str, pos: int, alphabet, lo_val, hi_val, wmin, wmax, excl: list[str],
) -> int | None:
    if isinstance(alphabet, RangeAlphabet):
        end = pos
        n = len(text)
        while end < n and alphabet.lo <= ord(text[end]) <= alphabet.hi:
            end += 1
    elif isinstance(alphabet, Alphabet):
        end = pos
        n = len(text)
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
        if excl:
            # Simple exclusion check — multi-char excluded values ignored for now
            pass
        return pos + width
    return None


def _build_dyn_matcher_desc(
    alph: "Alphabet | RangeAlphabet", lower: str | None, upper: str | None,
    excl: list[str],
) -> tuple | None:
    # `alph` is baked by `prepare`; only the endpoint *values* vary per match (the
    # references resolve at match time), so just the bounds are recomputed here.
    try:
        lo_val = alph.value(lower) if lower is not None else None
        hi_val = alph.value(upper) if upper is not None else None
    except (KeyError, CompileError):
        return None
    wf = len(lower) if lower is not None else None
    wc = len(upper) if upper is not None else None
    if wf is not None and wc is not None:
        wmin, wmax = min(wf, wc), max(wf, wc)
    elif wf is not None:
        wmin, wmax = wf, None
    else:
        wmin, wmax = 1, wc
    return ("value", alph, lo_val, hi_val, wmin, wmax, excl)


# ── Shared matcher runner ──────────────────────────────────────────────────────


def _run_matcher(
    desc: tuple, reps: Reps, state: _State, text: str, pos: int,
    cont: Cont, alphabet=None,
) -> int | None:
    caps = state.captures

    def attempt(end: int, rep_list: list[str], k: int) -> int | None:
        mark = len(caps)
        caps.append(Capture("", (pos, end), rep_list, count=k, alphabet=alphabet))
        r = cont(end)
        if r is not None:
            return r
        del caps[mark:]
        return None

    first_end = _matcher_match(desc, text, pos)
    if first_end is None or first_end == pos:
        return attempt(pos, [], 0) if reps.accepts(0) else None

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
    kind = desc[0]
    if kind == "char_range":
        _, lo, hi, excl = desc
        return _char_match(text, pos, lo, hi, excl)
    if kind == "group":
        _, gm, _het = desc
        r = _group_unit(text, pos, gm)
        return r[0] if r else None
    if kind == "complement":
        _, inner = desc
        return _complement_match(text, pos, inner)
    if kind == "value":
        _, alph, lo_val, hi_val, wmin, wmax, excl = desc
        return _match_value(text, pos, alph, lo_val, hi_val, wmin, wmax, excl)
    return None


def _matcher_accepts(desc: tuple, s: str) -> bool:
    kind = desc[0]
    if kind == "char_range":
        _, lo, hi, excl = desc
        return (len(s) == 1 and lo <= ord(s) <= hi
                and not any(e == s for e in excl if len(e) == 1))
    if kind == "group":
        _, gm, _het = desc
        return _group_accepts(s, gm)
    if kind == "complement":
        _, inner = desc
        return _complement_match(s, 0, inner) == len(s)
    if kind == "value":
        return _matcher_match(desc, s, 0) == len(s)
    return False


def _matcher_equal_unit(desc: tuple, text: str, pos: int, first: str) -> int | None:
    kind = desc[0]
    if kind == "char_range":
        if text.startswith(first, pos):
            return pos + len(first)
        return None
    if kind == "group":
        _, gm, het = desc
        if het:
            # Heterogeneous: stay within the SAME group-index sequence as first.
            # A congruence class `{{a,A}}` picks group 0 but may switch faces.
            # A complement picks any non-inner char.
            return _group_equal_unit(text, pos, first, gm)
        # Homogeneous: re-match the exact same string
        if text.startswith(first, pos):
            return pos + len(first)
        return None
    if kind == "complement":
        # Heterogeneous — any non-inner char
        return _complement_match(text, pos, desc[1])
    if kind == "value":
        if text.startswith(first, pos):
            return pos + len(first)
        return None
    return None


# ── Self-references ────────────────────────────────────────────────────────────


def _cap_text(cap: Capture, text: str) -> str:
    return text[cap.span[0] : cap.span[1]]


def _rep_count(cap: Capture) -> int:
    return cap.count if cap.count >= 0 else len(cap.reps)


def _referent_run(text: str, pos: int, referent: str, cap: int | None) -> list[int]:
    ends: list[int] = []
    current = pos
    while (cap is None or len(ends) < cap) and referent and text.startswith(referent, current):
        current += len(referent)
        ends.append(current)
    return ends


def _match_referent(
    referent: str | None, reps: Reps, text: str, pos: int,
    state: _State, cont: Cont,
) -> int | None:
    caps = state.captures
    if referent == "":
        mark = len(caps)
        caps.append(Capture("", (pos, pos), [""] * reps.min))
        r = cont(pos)
        if r is None:
            del caps[mark:]
        return r
    ends = [pos, *_referent_run(text, pos, referent, reps.max)] if referent else [pos]

    def attempt(k: int) -> int | None:
        end = ends[k]
        mark = len(caps)
        caps.append(Capture(
            text[pos:end], (pos, end),
            [referent] * k if referent else [],
        ))
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


def _stage_referent(stages: tuple[Match, ...], stage: int, path: tuple[int, ...]) -> str | None:
    if not 0 <= stage < len(stages):
        return None
    match = stages[stage]
    if not path:
        return match.text
    cap = match.capture_at(path)
    return cap.text if cap is not None else None


def _endpoint_text(desc: tuple, state: _State, text: str) -> str | None:
    caps = state.root.captures
    kind = desc[0]
    if kind == "back":
        return _cap_text(caps[desc[1]], text) if desc[1] < len(caps) else None
    if kind == "count":
        return str(_rep_count(caps[desc[1]])) if desc[1] < len(caps) else None
    return _stage_referent(state.root.stages, desc[1], tuple(desc[2]))


# ── Sequence group ─────────────────────────────────────────────────────────────


def _match_seq_group(
    children: list[Instruction], reps: Reps, text: str,
    pos: int, state: _State, cont: Cont,
) -> int | None:
    caps = state.captures
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
    if alphabet_desc[0] == "range":
        return RangeAlphabet(alphabet_desc[1], alphabet_desc[2])
    return Alphabet(alphabet_desc[1])


def _resolve_reps(reps: Reps, state: _State) -> Reps | None:
    if reps.count_ref is None:
        return reps
    caps = state.root.captures
    if reps.count_ref >= len(caps):
        return None
    k = _rep_count(caps[reps.count_ref])
    return Reps(min=k, max=k)


def _counts(reps: Reps, built: int) -> list[int]:
    ks = [k for k in range(built, 0, -1) if reps.accepts(k)]
    if reps.accepts(0):
        ks.append(0)
    return ks


def _finalize(text: str, start: int, end: int, state: _State) -> Match:
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