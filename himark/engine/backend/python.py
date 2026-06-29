"""The built-in pure-Python matching backend.

The parser already compiled the query to a `Program`; `prepare` lowers it to VM-ready
instructions, and `find_matches` runs them against text directly.
"""

from __future__ import annotations

from himark.engine.backend._types import Match
from himark.engine.backend._vm import find_matches as _run_find_matches
from himark.engine.backend._vm import prepare as _prepare
from himark.models.opcodes import Program


def prepare(program: Program) -> object:
    """Lower `program` into VM-ready instructions."""
    return _prepare(program)


def find_matches(
    compiled: object,
    text: str,
    stages: tuple[Match, ...] = (),
    start: int = 0,
    stop: int | None = None,
) -> list[Match]:
    """Run the VM over `text` and return all matches."""
    return _run_find_matches(compiled, text, stages, start, stop)  # type: ignore[arg-type]
