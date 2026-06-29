"""Standalone Python engine for the himark opcode IR.

Executes a compiled HMK pipeline against a target string, using the same
opcode VM and template renderer as the reference Python engine — zero himark
package imports. Swap this file for a compiled binary (Rust, Go, …) by
updating _ENGINE in himark/engine/_runner.py.

stdin:  {"pipeline": [[step, ...], ...], "target": "..."}
stdout: {"result": "..."} | {"error": "..."}

Step JSON shapes
  Program  → {"kind": "program", "elements": [[opcode, ...], ...],
              "groups": N, "fixed_point": bool}
  Template → {"kind": "template",
              "template": ["literal" | {"m": expr_json}, ...],
              "fixed_point": bool, "version": 1}
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


# ── Opcode constants (mirrors himark/models/opcodes.py) ───────────────────────

LIT = 0
ANCHOR = 1
CHAR = 2
GROUP = 3
BACK_REF = 4
COUNT_REF = 5
STAGE_REF = 6
VALUE_RANGE = 7
DYN_RANGE = 8
COMPLEMENT = 10
SEQ_GROUP = 11

_REPS_OPCODES = frozenset(
    {
        CHAR,
        GROUP,
        COMPLEMENT,
        BACK_REF,
        COUNT_REF,
        STAGE_REF,
        VALUE_RANGE,
        DYN_RANGE,
        SEQ_GROUP,
    }
)


# ── Repetition spec ───────────────────────────────────────────────────────────


@dataclass(slots=True)
class Reps:
    min: int = 1
    max: int | None = 1
    allowed: frozenset[int] | None = None
    count_ref: int | None = None

    def accepts(self, k: int) -> bool:
        if self.allowed is not None:
            return k in self.allowed
        return k >= self.min and (self.max is None or k <= self.max)


def reps_from_list(r: Any) -> Reps:
    if r is None:
        return Reps(1, 1)
    if isinstance(r, list) and r and r[0] == "#":
        return Reps(count_ref=r[1])
    if isinstance(r, list) and r and r[0] == "=":
        vals = frozenset(r[1])
        return Reps(min=min(vals), max=max(vals), allowed=vals)
    lo, hi = r
    return Reps(min=lo, max=None if hi == -1 else hi)


# ── Match / Capture ───────────────────────────────────────────────────────────


@dataclass(slots=True)
class Capture:
    text: str
    span: tuple[int, int]
    reps: list[str]
    subs: list[Capture] = field(default_factory=list)
    count: int = -1
    alphabet: Alphabet | RangeAlphabet | None = None


@dataclass
class Match:
    text: str
    start: int
    end: int
    captures: list[Capture] = field(default_factory=list)

    @property
    def groups(self) -> list[str]:
        return [c.text for c in self.captures]

    def capture_at(self, path: tuple[int, ...]) -> Capture | None:
        captures = self.captures
        cap = None
        for idx in path:
            if not 0 <= idx < len(captures):
                return None
            cap = captures[idx]
            captures = cap.subs
        return cap


# ── Alphabet (mirrors himark/models/alphabet.py) ──────────────────────────────


class Alphabet:
    __slots__ = ("groups", "base", "_index")

    def __init__(self, groups: list[list[str]]) -> None:
        self.groups = groups
        self.base = len(groups)
        self._index = {m: i for i, grp in enumerate(groups) for m in grp}

    def __contains__(self, ch: str) -> bool:
        return ch in self._index

    def is_zero(self, ch: str) -> bool:
        return self._index[ch] == 0

    def value(self, s: str) -> int:
        v = 0
        for c in s:
            v = v * self.base + self._index[c]
        return v


class RangeAlphabet:
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


def _make_alphabet(desc: list) -> Alphabet | RangeAlphabet:
    if desc[0] == "range":
        return RangeAlphabet(desc[1], desc[2])
    return Alphabet(desc[1])


# ── VM state ──────────────────────────────────────────────────────────────────

Cont = Callable[[int], "int | None"]


class _State:
    __slots__ = ("captures", "root", "stages")

    def __init__(
        self, root: _State | None = None, stages: tuple[Match, ...] = ()
    ) -> None:
        self.captures: list[Capture] = []
        self.root = root if root is not None else self
        self.stages = stages


# ── Prepare: lower serialised opcodes to VM-ready form ────────────────────────
# Mirrors himark/engine/_vm.py::prepare() + _prepare_elements().
# JSON deserialises tuples as lists, so operand indexing uses lists throughout;
# the VM dispatch is identical to the reference engine.


class _GroupMatcher:
    __slots__ = ("members", "accept_set")

    def __init__(self, groups: list[list[str]]) -> None:
        members = [(m, i) for i, grp in enumerate(groups) for m in grp if m]
        members.sort(key=lambda x: len(x[0]), reverse=True)
        self.members = members
        self.accept_set = frozenset(m for m, _ in members)

    def match(self, text: str, pos: int) -> int | None:
        r = _group_unit(text, pos, self)
        return r[0] if r else None

    def accepts(self, s: str) -> bool:
        return s in self.accept_set

    def equal_unit(self, text: str, pos: int, first: str) -> int | None:
        return _group_equal_unit(text, pos, first, self)


class _CharMatcher:
    __slots__ = ("lo", "hi", "excl")

    def __init__(self, lo: int, hi: int, excl: Any) -> None:
        self.lo = lo
        self.hi = hi
        self.excl = excl

    def match(self, text: str, pos: int) -> int | None:
        return _char_match(text, pos, self.lo, self.hi, self.excl)

    def accepts(self, s: str) -> bool:
        if len(s) != 1 or not (self.lo <= ord(s) <= self.hi):
            return False
        if self.excl:
            singles, _ranges, _literals = self.excl
            return s not in singles
        return True

    def equal_unit(self, text: str, pos: int, first: str) -> int | None:
        return pos + len(first) if text.startswith(first, pos) else None


class _ComplementMatcher:
    __slots__ = ("inner_groups",)

    def __init__(self, inner_groups: list[list[str]]) -> None:
        self.inner_groups = inner_groups

    def match(self, text: str, pos: int) -> int | None:
        return _complement_match(text, pos, self.inner_groups)

    def accepts(self, s: str) -> bool:
        return _complement_match(s, 0, self.inner_groups) == len(s)

    def equal_unit(self, text: str, pos: int, first: str) -> int | None:
        return _complement_match(text, pos, self.inner_groups)


class _ValueMatcher:
    __slots__ = ("alph", "lo_val", "hi_val", "wmin", "wmax", "excl")

    def __init__(
        self,
        alph: Alphabet | RangeAlphabet,
        lo_val: int | None,
        hi_val: int | None,
        wmin: int,
        wmax: int | None,
        excl: Any,
    ) -> None:
        self.alph = alph
        self.lo_val = lo_val
        self.hi_val = hi_val
        self.wmin = wmin
        self.wmax = wmax
        self.excl = excl

    def match(self, text: str, pos: int) -> int | None:
        return _match_value(
            text,
            pos,
            self.alph,
            self.lo_val,
            self.hi_val,
            self.wmin,
            self.wmax,
            self.excl,
        )

    def accepts(self, s: str) -> bool:
        return self.match(s, 0) == len(s)

    def equal_unit(self, text: str, pos: int, first: str) -> int | None:
        return pos + len(first) if text.startswith(first, pos) else None


def _prepare_elements(elements: list) -> list:
    """Lower serialised opcode lists to VM-ready instructions (bake Reps + alphabets)."""
    out: list = []
    for el in elements:
        opcode = el[0]
        if opcode not in _REPS_OPCODES:
            out.append(el)
            continue
        args = list(el[1:])
        args[-1] = reps_from_list(args[-1])
        if opcode in (VALUE_RANGE, DYN_RANGE):
            args[0] = _make_alphabet(args[0])
        elif opcode == GROUP:
            args[0] = _GroupMatcher(args[0])
        elif opcode == SEQ_GROUP:
            args[0] = _prepare_elements(args[0])
        out.append((opcode, *args))
    return out


# ── VM execution (mirrors himark/engine/_vm.py) ───────────────────────────────


def _find_matches(
    prepared: list, text: str, stages: tuple[Match, ...] = ()
) -> list[Match]:
    matches: list[Match] = []
    n = len(text)
    pos = 0
    while pos < n:
        state = _State(stages=stages)
        end = _run_program(prepared, 0, text, pos, state)
        if end is not None and end > pos:
            matches.append(_finalize(text, pos, end, state))
            pos = end
        else:
            pos += 1
    return matches


def _run_program(
    elements: list, idx: int, text: str, pos: int, state: _State
) -> int | None:
    if idx >= len(elements):
        return pos

    def cont(end: int) -> int | None:
        return _run_program(elements, idx + 1, text, end, state)

    opcode, *args = elements[idx]

    if opcode == LIT:
        s: str = args[0]
        return cont(pos + len(s)) if text[pos : pos + len(s)] == s else None

    if opcode == ANCHOR:
        return cont(pos) if _check_anchor(args[0], text, pos) else None

    if opcode == CHAR:
        lo, hi, excl_list, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        return _run_matcher(
            _CharMatcher(lo, hi, excl_list), reps, state, text, pos, cont
        )

    if opcode == GROUP:
        gm, _het, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        return _run_matcher(gm, reps, state, text, pos, cont, alphabet=None)

    if opcode == COMPLEMENT:
        inner_groups, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        return _run_matcher(
            _ComplementMatcher(inner_groups), reps, state, text, pos, cont
        )

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
        matcher = _ValueMatcher(alph, lo_val, hi_val, wmin, wmax, excl_list)
        return _run_matcher(matcher, reps, state, text, pos, cont, alphabet=alph)

    if opcode == DYN_RANGE:
        alph, lo_static, hi_static, lo_ref, hi_ref, excl_list, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        if reps is None:
            return None
        lower = lo_static if lo_ref is None else _endpoint_text(lo_ref, state, text)
        upper = hi_static if hi_ref is None else _endpoint_text(hi_ref, state, text)
        if (lo_ref is not None and lower is None) or (
            hi_ref is not None and upper is None
        ):
            return None
        matcher = _build_dyn_matcher(alph, lower, upper, excl_list)
        return _run_matcher(matcher, reps, state, text, pos, cont) if matcher else None

    if opcode == SEQ_GROUP:
        children, reps_spec = args
        reps = _resolve_reps(reps_spec, state)
        return (
            _match_seq_group(children, reps, text, pos, state, cont) if reps else None
        )

    raise ValueError(f"Unknown opcode: {opcode}")


def _check_anchor(kind: int, text: str, pos: int) -> bool:
    if kind == 0:
        return pos == 0 or text[pos - 1] == "\n"
    if kind == 1:
        return pos == len(text) or text[pos] == "\n"
    if kind == 2:
        return pos == 0
    return pos == len(text)


def _char_match(text: str, pos: int, lo: int, hi: int, excl: Any) -> int | None:
    if pos >= len(text):
        return None
    ch = text[pos]
    if not (lo <= ord(ch) <= hi):
        return None
    if excl:
        singles, ranges, literals = excl
        if ch in singles:
            return None
        for lo2, hi2 in ranges:
            if lo2 <= ch <= hi2:
                return None
        for lit in literals:
            if text.startswith(lit, pos):
                return None
    return pos + 1


def _complement_match(text: str, pos: int, inner_groups: list[list[str]]) -> int | None:
    if pos >= len(text):
        return None
    for grp in inner_groups:
        for m in grp:
            if m and text.startswith(m, pos):
                return None
    return pos + 1


def _group_unit(text: str, pos: int, gm: _GroupMatcher) -> tuple[int, int] | None:
    for m, idx in gm.members:
        if text.startswith(m, pos):
            return pos + len(m), idx
    return None


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


def _match_value(
    text: str,
    pos: int,
    alphabet: Alphabet | RangeAlphabet,
    lo_val: int | None,
    hi_val: int | None,
    wmin: int,
    wmax: int | None,
    excl: Any,
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
        candidate = text[pos : pos + width]
        if excl:
            singles, ranges, literals = excl
            if candidate in singles:
                continue
            if width == 1 and any(lo2 <= candidate <= hi2 for lo2, hi2 in ranges):
                continue
            if any(
                candidate.startswith(lit) and len(candidate) == len(lit)
                for lit in literals
            ):
                continue
        val = alphabet.value(candidate)
        if (lo_val is not None and val < lo_val) or (
            hi_val is not None and val > hi_val
        ):
            continue
        return pos + width
    return None


def _build_dyn_matcher(
    alph: Alphabet | RangeAlphabet,
    lower: str | None,
    upper: str | None,
    excl: Any,
) -> _ValueMatcher | None:
    try:
        lo_val = alph.value(lower) if lower is not None else None
        hi_val = alph.value(upper) if upper is not None else None
    except Exception:
        return None
    wf = len(lower) if lower is not None else None
    wc = len(upper) if upper is not None else None
    if wf is not None and wc is not None:
        wmin, wmax = min(wf, wc), max(wf, wc)
    elif wf is not None:
        wmin, wmax = wf, None
    else:
        wmin, wmax = 1, wc
    return _ValueMatcher(alph, lo_val, hi_val, wmin, wmax, excl)


def _run_matcher(
    matcher: Any,
    reps: Reps,
    state: _State,
    text: str,
    pos: int,
    cont: Cont,
    alphabet: Alphabet | RangeAlphabet | None = None,
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

    first_end = matcher.match(text, pos)
    if first_end is None or first_end == pos:
        return attempt(pos, [], 0) if reps.accepts(0) else None

    for unit_len in range(first_end - pos, 0, -1):
        first = text[pos : pos + unit_len]
        if not matcher.accepts(first):
            continue
        rep_list = [first]
        ends = [pos + unit_len]
        current = pos + unit_len
        while reps.max is None or len(rep_list) < reps.max:
            nxt = matcher.equal_unit(text, current, first)
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


def _cap_text(cap: Capture, text: str) -> str:
    return text[cap.span[0] : cap.span[1]]


def _rep_count(cap: Capture) -> int:
    return cap.count if cap.count >= 0 else len(cap.reps)


def _referent_run(text: str, pos: int, referent: str, cap: int | None) -> list[int]:
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
    if not 0 <= stage < len(stages):
        return None
    match = stages[stage]
    if not path:
        return match.text
    cap = match.capture_at(path)
    return cap.text if cap is not None else None


def _endpoint_text(desc: list | tuple, state: _State, text: str) -> str | None:
    caps = state.root.captures
    kind = desc[0]
    if kind == "back":
        return _cap_text(caps[desc[1]], text) if desc[1] < len(caps) else None
    if kind == "count":
        return str(_rep_count(caps[desc[1]])) if desc[1] < len(caps) else None
    return _stage_referent(state.root.stages, desc[1], tuple(desc[2]))


def _match_seq_group(
    children: list,
    reps: Reps,
    text: str,
    pos: int,
    state: _State,
    cont: Cont,
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


# ── Expr types (mirrors himark/models/compiled.py) ────────────────────────────


@dataclass(slots=True)
class ExLit:
    text: str


@dataclass(slots=True)
class ExCurrent:
    pass


@dataclass(slots=True)
class ExRef:
    stage: int | None
    is_count: bool
    path: tuple[int, ...] | None


@dataclass(slots=True)
class ExConcat:
    parts: list[Any]  # list[Expr]


@dataclass(slots=True)
class ExFilter:
    src: Any  # Expr
    name: str


def _json_to_expr(d: dict) -> Any:
    if "lit" in d:
        return ExLit(d["lit"])
    if "cur" in d:
        return ExCurrent()
    if "ref" in d:
        stage, is_count, path = d["ref"]
        return ExRef(stage, is_count, tuple(path) if path is not None else None)
    if "cat" in d:
        return ExConcat([_json_to_expr(p) for p in d["cat"]])
    return ExFilter(_json_to_expr(d["src"]), d["filter"])


# ── Template rendering (mirrors himark/engine/_render.py) ─────────────────────


def _indent(s: str) -> str:
    return "" if s == "" else "\t" + s.replace("\n", "\n\t")


_FILTERS = {"trim": str.strip, "indent": _indent}


@dataclass
class _Moustache:
    expr: Any  # Expr


@dataclass
class _Template:
    parts: list[str | _Moustache]
    fixed_point: bool = False


def _eval_expr(expr: Any, current: str, stages: list[Match]) -> str:
    if isinstance(expr, ExLit):
        return expr.text
    if isinstance(expr, ExCurrent):
        return current
    if isinstance(expr, ExRef):
        pipe_idx = expr.stage if expr.stage is not None else len(stages) - 1
        if not 0 <= pipe_idx < len(stages):
            raise RuntimeError(f"Moustache stage {pipe_idx} out of range")
        stage_match = stages[pipe_idx]
        if expr.path is None:
            return stage_match.text
        cap = stage_match.capture_at(expr.path)
        if cap is None:
            raise RuntimeError(f"Moustache capture {expr.path} out of range")
        return str(len(cap.reps)) if expr.is_count else cap.text
    if isinstance(expr, ExConcat):
        return "".join(_eval_expr(p, current, stages) for p in expr.parts)
    if isinstance(expr, ExFilter):
        fn = _FILTERS.get(expr.name)
        if fn is None:
            raise RuntimeError(f"Unknown template filter: '{expr.name}'")
        return fn(_eval_expr(expr.src, current, stages))
    raise RuntimeError(f"Unknown expr type: {type(expr).__name__}")


def _render_template(
    template: _Template, current: str, stages: list[Match]
) -> tuple[str, list[tuple[int, int]] | None]:
    out: list[str] = []
    length = 0
    spans: list[tuple[int, int]] = []
    for part in template.parts:
        if isinstance(part, _Moustache):
            value = _eval_expr(part.expr, current, stages)
            start = length
            out.append(value)
            length += len(value)
            spans.append((start, length))
        else:
            out.append(part)
            length += len(part)
    full = "".join(out)
    return full, (spans or None)


# ── JSON step deserialization ─────────────────────────────────────────────────


@dataclass
class _Program:
    elements: list  # VM-ready (prepared) instructions
    groups: int
    fixed_point: bool


def _json_to_step(d: dict) -> _Program | _Template:
    kind = d.get("kind")
    if kind == "program":
        return _Program(
            _prepare_elements(d["elements"]),
            d.get("groups", 0),
            bool(d.get("fixed_point", False)),
        )
    if kind == "template":
        parts: list[str | _Moustache] = []
        for p in d["template"]:
            if isinstance(p, str):
                parts.append(p)
            else:
                parts.append(_Moustache(_json_to_expr(p["m"])))
        return _Template(parts, bool(d.get("fixed_point", False)))
    raise ValueError(f"Unknown step kind: {kind!r}")


# ── Pipeline execution (mirrors himark/engine/__init__.py) ────────────────────


def _step_find_matches(
    program: _Program, text: str, stages: tuple[Match, ...] = ()
) -> list[Match]:
    return _find_matches(program.elements, text, stages)


def _transform(
    steps: list[_Program | _Template],
    text: str,
    ancestors: tuple[Match, ...],
    committed: bool = False,
) -> str | None:
    if not steps:
        return text
    head, rest = steps[0], steps[1:]

    if isinstance(head, _Template):
        full, spans = _render_template(head, text, list(ancestors))
        if spans is None:
            stage = Match(full, 0, len(full))
            return _transform(rest, full, (*ancestors, stage), committed=True)
        if not rest:
            return full
        pieces: list[str] = []
        last = 0
        for start, end in spans:
            payload = full[start:end]
            stage = Match(payload, 0, len(payload))
            sub = _transform(rest, payload, (*ancestors, stage), committed=True)
            if sub is None:
                return None
            pieces.append(full[last:start])
            pieces.append(sub)
            last = end
        pieces.append(full[last:])
        return "".join(pieces)

    # Query branch: splice each match's transform in place
    pieces = []
    last = 0
    matched = False
    for m in _step_find_matches(head, text, ancestors):
        matched = True
        sub = _transform(rest, m.text, (*ancestors, m), committed)
        if sub is None:
            return None
        pieces.append(text[last : m.start])
        pieces.append(sub)
        last = m.end
    if not matched:
        return text if committed else None
    pieces.append(text[last:])
    return "".join(pieces)


def _deltas(
    steps: list[_Program | _Template], target: str
) -> list[tuple[int, int, str]]:
    if not steps:
        return []
    head = steps[0]
    if isinstance(head, _Template):
        result = _transform(steps, target, ())
        return [] if result is None else [(0, len(target), result)]
    rest = steps[1:]
    out: list[tuple[int, int, str]] = []
    for m in _step_find_matches(head, target):
        result = _transform(rest, m.text, (m,))
        if result is not None:
            out.append((m.start, m.end, result))
    return out


def _splice(steps: list[_Program | _Template], target: str) -> str:
    out: list[str] = []
    last = 0
    for start, end, text in _deltas(steps, target):
        out.append(target[last:start])
        out.append(text)
        last = end
    out.append(target[last:])
    return "".join(out)


def _splice_to_fixed_point(steps: list[_Program | _Template], target: str) -> str:
    text = target
    cap = 8 * len(target) + 1024
    size_limit = 64 * len(target) + 65536
    for _ in range(cap):
        result = _splice(steps, text)
        if result == text:
            return text
        text = result
        if len(text) > size_limit:
            break
    raise RuntimeError(
        "A `<=` statement did not settle — the rule is not contracting toward a "
        "fixed point (it grows or oscillates). Use `=>` for a single pass."
    )


def run_pipeline(pipeline: list[list[dict]], target: str) -> str:
    """Execute each statement in `pipeline` as a splice pass over `target`,
    chaining the result of each statement into the next."""
    result = target
    for stmt_json in pipeline:
        steps = [_json_to_step(s) for s in stmt_json]
        if not steps:
            continue
        if steps[0].fixed_point:
            result = _splice_to_fixed_point(steps, result)
        else:
            result = _splice(steps, result)
    return result


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
        result = run_pipeline(payload["pipeline"], payload["target"])
        print(json.dumps({"result": result}))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
