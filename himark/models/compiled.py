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
# string/int literals, parenthesised `,`-concatenation, `|` filter pipes, and value
# operators (arithmetic `+ - * / %`, bitwise `& ^ ~ << >>` and backtick-or). The
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
    """A filter pipe `src | name` — `src`'s value transformed by the declared filter
    `name`. Filters are declared in L2 (`himark/std.hmk`, or a script-local `@name =`
    definition) as ordinary himark pipelines; the compiler resolves `name` and
    attaches its **compiled body** here so the renderer never needs a registry:

      * `body` is an `Expr` for a **value-shaped** filter — one whose pipeline is a
        single bare `{{ … }}` moustache (`@double = "{{ $ * 2 }}"`). Applied by
        evaluating that `Expr` with `$` bound to the subject universe, so the
        subject's alphabet + band survive (docs/ALGEBRA.md).
      * `body` is a compiled pipeline (`list[list[Step]]`) for a **document-shaped**
        filter (`@trim = {@s}… => "…"`). Applied by running that pipeline over the
        subject's rendered text, yielding a plain `@uni` string.

    `body` is a compile-time attachment: it does not serialise (the wire form names
    the filter; an executor resolves it from its own std.hmk — see PAYLOAD.md)."""

    src: Expr
    name: str
    body: "Expr | list[list[Step]] | None" = None


@dataclass(slots=True)
class ExBinOp:
    """A binary value operator `lhs OP rhs` — arithmetic (`+ - * / %`) or bitwise
    (`& ^ << >>` and backtick-or). Evaluated on the operands' universe values;
    the result takes the LHS alphabet + band, then normalize + encode (LHS wins).
    See docs/ALGEBRA.md. `op` is the operator spelling (`<<`/`>>` for the shifts,
    a backtick for or)."""

    op: str
    lhs: Expr
    rhs: Expr


@dataclass(slots=True)
class ExUnOp:
    """A unary value operator — only bitwise not `~` today. `~a` complements the
    operand's value, then normalize + encode under its own alphabet + band."""

    op: str
    operand: Expr


Expr: TypeAlias = ExLit | ExCurrent | ExRef | ExConcat | ExFilter | ExBinOp | ExUnOp


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
    if isinstance(e, ExBinOp):
        return {"binop": [e.op, _expr_to_json(e.lhs), _expr_to_json(e.rhs)]}
    if isinstance(e, ExUnOp):
        return {"unop": [e.op, _expr_to_json(e.operand)]}
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
