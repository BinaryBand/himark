"""The compiled product — what the parser emits and the engine VM consumes.

A `.hmk` statement is a chain of **steps**, and each step is one of two compiled
forms:

  * a **query** is a `Program` (the flat opcode IR in `opcodes.py`) — the VM scans
    it against text to produce matches;
  * a **template** is a `Template` — a pre-split sequence of literal text and
    `Moustache` expressions the renderer fills in.

`Step` is the union. The parser owns *both* parse and compile (ANTLR is the
parser and the compiler), so it hands the engine these compiled steps directly —
the engine never sees the intermediate AST (`nodes_typed`). Both forms are plain
dataclasses over primitives, so a pipeline of them serialises (JSON via the
`to_json` pair, or pickle) without any engine or AST objects riding along.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from himark.models.opcodes import Program


@dataclass(slots=True)
class Moustache:
    """One `{{ … }}` reference in a template — its expression body (the text
    between the braces, already trimmed). The renderer evaluates it against the
    pipeline stages at run time; compiling only locates and isolates it."""

    body: str


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
        literal part stays a string; a moustache becomes `{"m": <body>}`."""
        return {
            "version": 1,
            "fixed_point": self.fixed_point,
            "template": [
                p if isinstance(p, str) else {"m": p.body} for p in self.parts
            ],
        }

    @classmethod
    def from_json(cls, data: dict) -> "Template":
        parts: list[str | Moustache] = [
            p if isinstance(p, str) else Moustache(body=p["m"])
            for p in data["template"]
        ]
        return cls(parts=parts, fixed_point=data["fixed_point"])


# A compiled pipeline step: a matcher program or a render template.
Step: TypeAlias = Program | Template
