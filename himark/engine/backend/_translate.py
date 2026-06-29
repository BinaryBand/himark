"""Translate a compiled opcode `Program` into the plain JSON the Rust backend
consumes — or declare it out of scope with `Unsupported`.

The Rust backend ([rust.py](rust.py)) accelerates the **structural** subset of the
language: literals, anchors, capturing groups over the char-class matcher grammar
(`_Literal` / `_CharRange` / `_Union` / `_Complement` / `_Group`),
back-references, and plain repetition. Anything carrying value/alphabet arithmetic
(`{A::x..y}` bounds), a count/stage reference, a `[#i]` rep, or a grouping brace
(`SEQ_GROUP`) raises `Unsupported`, and `RustEngine` falls back to `PythonEngine`
for that whole pattern.

The wire format is JSON (one boundary, robust over PyO3): each element/matcher is a
tagged object `{"k": ...}`; see the `serde` enums in `rust/src/program.rs`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from himark.models.opcodes import (
    ANCHOR,
    BACK_REF,
    CHAR,
    GROUP,
    LIT,
    SEQ_GROUP,
    VALUE_RANGE,
    DYN_RANGE,
    COUNT_REF,
    STAGE_REF,
    Instruction,
    Reps,
    reps_from_tuple,
)


class Unsupported(Exception):
    """The program uses a construct the Rust subset does not support; the caller
    should fall back to the Python backend."""


def to_json(elements: Sequence[Instruction]) -> str:
    """The Rust-program JSON for `elements` (a `Program`'s element sequence), or
    raise `Unsupported`."""
    return json.dumps([_element(el) for el in elements], ensure_ascii=False)


def _reps(reps_tuple) -> dict:
    """Convert a serialised reps tuple to the Rust JSON reps dict."""
    r = reps_from_tuple(reps_tuple)
    if r.count_ref is not None:
        raise Unsupported("count-reference repetition")  # `[#i]` — Python only
    allowed = sorted(r.allowed) if r.allowed is not None else None
    return {"min": r.min, "max": r.max, "allowed": allowed}


def _element(el: Instruction) -> dict:
    """Translate one opcode tuple to the Rust JSON element dict."""
    opcode, *args = el

    if opcode == LIT:
        return {"k": "lit", "s": args[0]}

    if opcode == ANCHOR:
        kind_map = {0: "line_start", 1: "line_end", 2: "doc_start", 3: "doc_end"}
        return {"k": "anchor", "at": kind_map[args[0]]}

    if opcode == CHAR:
        lo, hi, excl_list, reps_tuple = args
        return {
            "k": "group",
            "m": {"k": "range", "lo": lo, "hi": hi, "excl": _excluder(excl_list)},
            "reps": _reps(reps_tuple),
            "het": False,
        }

    if opcode == GROUP:
        groups, het, reps_tuple = args
        return {
            "k": "group",
            "m": _group_matcher(groups, het),
            "reps": _reps(reps_tuple),
            "het": het,
        }

    if opcode == BACK_REF:
        group, reps_tuple = args
        return {"k": "backref", "g": group, "reps": _reps(reps_tuple)}

    # These opcodes carry value arithmetic / dynamic resolution — Rust doesn't
    # implement those, so fall back to Python.
    if opcode in (VALUE_RANGE, DYN_RANGE, COUNT_REF, STAGE_REF, SEQ_GROUP):
        raise Unsupported(f"opcode {opcode}")

    raise Unsupported(f"unknown opcode {opcode}")


def _excluder(excl: list[str]) -> dict | None:
    """Build Rust JSON excluder from a list of exclusion strings."""
    if not excl:
        return None
    singles = sorted(e for e in excl if ".." not in e)
    ranges = sorted(
        [[lo, hi] for lo, hi in (tuple(e.split("..", 1)) for e in excl if ".." in e)]
    )
    return {"singles": singles, "ranges": ranges} if (singles or ranges) else None


def _group_matcher(
    groups: list[list[str]], het: bool
) -> dict:
    """Build the Rust JSON matcher for a group alphabet.

    A homogeneous singleton-alphabet group produces a union of literals; a
    multi-face group (congruence class) produces the Rust ``group`` matcher.
    A complement (currently unsupported) would raise.
    """
    # Flatten single-element groups into a union of literals
    if all(len(grp) == 1 for grp in groups):
        members = sorted([grp[0] for grp in groups if grp[0]])
        if len(members) == 1 and not het:
            return {"k": "lit", "s": members[0]}
        return {
            "k": "union",
            "arms": [{"k": "lit", "s": m} for m in members],
            "excl": None,
        }
    # Multi-face groups — the Rust ``group`` matcher with (member, group_index) pairs
    members = sorted(
        ((m, i) for i, grp in enumerate(groups) for m in grp if m),
        key=lambda x: len(x[0]),
        reverse=True,
    )
    return {"k": "group", "members": [[m, i] for m, i in members]}