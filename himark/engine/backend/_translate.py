"""Translate a compiled `Element` program into the plain JSON the Rust backend
consumes — or declare it out of scope with `Unsupported`.

The Rust backend ([rust.py](rust.py)) accelerates the **structural** subset of the
language: literals, anchors, capturing groups over the char-class matcher grammar
(`_Literal` / `_CharRange` / `_Union` / `_Complement` / `_Group` / `_Het`),
back-references, and plain repetition. Anything carrying value/alphabet arithmetic
(`{x:A:y}` bounds), a count/stage reference, a `[#i]` rep, or a grouping brace
(`SeqGroupEl`) raises `Unsupported`, and `RustEngine` falls back to `PythonEngine`
for that whole pattern. The translation is a pure read of the compiled objects —
the same `Element`s the Python loop runs — so the two backends stay in lock-step.

The wire format is JSON (one boundary, robust over PyO3): each element/matcher is a
tagged object `{"k": ...}`; see the `serde` enums in `rust/src/program.rs`.
"""

from __future__ import annotations

import json

from himark.engine.backend import _compile as c


class Unsupported(Exception):
    """The program uses a construct the Rust subset does not implement; the caller
    should fall back to the Python backend."""


def to_json(elements: list) -> str:
    """The Rust-program JSON for `elements`, or raise `Unsupported`."""
    return json.dumps([_element(el) for el in elements], ensure_ascii=False)


def _reps(reps: c.Reps) -> dict:
    if reps.count_ref is not None:  # `[#i]` resolves from running state — Python only
        raise Unsupported("count-reference repetition")
    allowed = sorted(reps.allowed) if reps.allowed is not None else None
    return {"min": reps.min, "max": reps.max, "allowed": allowed}


def _element(el) -> dict:
    if type(el) is c.LiteralEl:
        return {"k": "lit", "s": el.text}
    if type(el) is c.AnchorEl:
        return {"k": "anchor", "at": el.at}
    if type(el) is c.GroupEl:
        return {
            "k": "group",
            "m": _matcher(el.matcher),
            "reps": _reps(el.reps),
            "het": el.het,
        }
    if type(el) is c.BackRefEl:
        return {"k": "backref", "g": el.group, "reps": _reps(el.reps)}
    # SeqGroupEl, DynValueRangeEl, CountRefEl, StageRefEl — Python only (for now).
    raise Unsupported(f"element {type(el).__name__}")


def _excluder(excl) -> dict | None:
    if excl is None:
        return None
    return {
        "singles": sorted(excl.singles),
        "ranges": [[lo, hi] for lo, hi in excl.ranges],
    }


def _matcher(m) -> dict:
    # A value-carrying matcher (a `{x:A:y}` bound) is out of the structural subset.
    if getattr(m, "value_alphabet", None) is not None:
        raise Unsupported("value-bound matcher")
    if type(m) is c._Literal:
        return {"k": "lit", "s": m.content}
    if type(m) is c._CharRange:
        return {"k": "range", "lo": m.start, "hi": m.end, "excl": _excluder(m._excl)}
    if type(m) is c._Union:
        return {
            "k": "union",
            "arms": [_matcher(a) for a in m.options],
            "excl": _excluder(m._excl),
        }
    if type(m) is c._Complement:
        return {"k": "compl", "inner": _matcher(m.inner)}
    if type(m) is c._Group:
        return {"k": "group", "members": [[mem, gi] for mem, gi in m.members]}
    if type(m) is c._Het:
        return {"k": "het", "inner": _matcher(m.inner)}
    # _ValueRange and anything new — fall back.
    raise Unsupported(f"matcher {type(m).__name__}")
