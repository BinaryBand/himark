"""The compiled product — what the parser emits and the engine VM consumes.

A `.hmk` statement is a chain of **steps**, and each step is one of two compiled
forms:

  * a **query** is a `Program` (the flat opcode IR in `opcodes.py`) — the VM scans
    it against text to produce matches;
  * a **template** is a `Template` — a pre-split sequence of literal text and
    `Moustache` references, each holding a parsed expression (`Expr`) the renderer
    only has to *evaluate*.

`Step` is the union. The parser owns *both* parse and compile (ANTLR is the
parser and the compiler), so it hands the engine these compiled steps directly —
the engine never sees the intermediate AST (`nodes_typed`), and never parses a
moustache expression at render time. Both forms are plain dataclasses over
primitives, so a pipeline of them serialises (JSON via the `to_json` pair, or
pickle) without any engine or AST objects riding along.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from himark.models.opcodes import Program


# ── Moustache expression AST ──────────────────────────────────────────────────
# A `{{ … }}` body is a tiny expression: accessors (`$`, `$i`, `#i`, `2$0.1`),
# string/int literals, parenthesised `,`-concatenation, and `|` filter pipes. The
# parser compiles the body into this `Expr` tree once; the renderer evaluates it.


@dataclass(slots=True)
class ExLit:
    """A string or integer literal — renders to its own text."""

    text: str


@dataclass(slots=True)
class ExCurrent:
    """The bare `$` accessor — the pipe's current subject, the whole text flowing
    into this step (`{{$}}`). `.` is a deprecated spelling of the same node."""


@dataclass(slots=True)
class ExRef:
    """A capture accessor `[stage]$|#[path]`. `stage` is the pipeline stage index, or
    None for the current stage; `is_count` is the `#` sigil (a repetition count) vs
    `$` (text); `path` is the dotted capture path, or None for the stage's whole
    text (`N$`). A `#` always carries a path (enforced at compile). Bare `$` (no
    stage, no path) is not an `ExRef` -- it compiles to `ExCurrent`."""

    stage: int | None
    is_count: bool
    path: tuple[int, ...] | None


@dataclass(slots=True)
class ExConcat:
    """A parenthesised comma-concatenation `( a, b, … )` — its parts joined."""

    parts: list[Expr]


@dataclass(slots=True)
class ExFilter:
    """A filter pipe `src | name` — `src`'s value transformed by the named filter
    (`trim`, `indent`). The filter set lives in the renderer; this only names one."""

    src: Expr
    name: str


Expr: TypeAlias = ExLit | ExCurrent | ExRef | ExConcat | ExFilter


def _expr_to_json(e: Expr) -> dict:
    if isinstance(e, ExLit):
        return {"lit": e.text}
    if isinstance(e, ExCurrent):
        return {"cur": True}
    if isinstance(e, ExRef):
        path = list(e.path) if e.path is not None else None
        return {"ref": [e.stage, e.is_count, path]}
    if isinstance(e, ExConcat):
        return {"cat": [_expr_to_json(p) for p in e.parts]}
    return {"filter": e.name, "src": _expr_to_json(e.src)}


# ── Compiled steps ────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Moustache:
    """One `{{ … }}` reference in a template, holding its compiled `Expr`. The
    renderer evaluates it against the pipeline stages at run time; the parser did
    the parsing, so rendering never re-lexes the body."""

    expr: Expr


@dataclass(slots=True)
class Template:
    """A compiled template step: the literal text and `Moustache` references of a
    `"…"` template, pre-split into ordered `parts` (each a literal `str` or a
    `Moustache`). The renderer walks `parts`, emitting literals verbatim and the
    evaluated value of each moustache, recording where each moustache value lands
    so it can flow downstream as its own branch.

    `fixed_point` mirrors `Program.fixed_point`: the pipeline runner sets it on a
    statement's first step when the statement uses the `<=>` arrow."""

    parts: list[str | Moustache] = field(default_factory=list)
    fixed_point: bool = False

    def to_json(self) -> dict:
        """Serialise to a JSON-stable dict — parity with `Program.to_json`. A
        literal part stays a string; a moustache becomes `{"m": <expr-json>}`."""
        return {
            "version": 1,
            "fixed_point": self.fixed_point,
            "template": [
                p if isinstance(p, str) else {"m": _expr_to_json(p.expr)}
                for p in self.parts
            ],
        }


# A compiled pipeline step: a matcher program or a render template.
Step: TypeAlias = Program | Template
