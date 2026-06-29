"""The built-in pure-Python matching backend.

`PythonEngine` is the default implementation of the `Engine` seam (defined in
`interface.py`): the parser already compiled the query to a `Program`, so this
backend's `compile` is the identity and `run` is just the opcode VM in `_vm`.
The seam is deliberately coarse — a backend receives the whole `Program` and text
and returns `Match` objects, so the scan never crosses an FFI boundary per
character — which is what lets a native backend (e.g. Rust via PyO3) drop in
via `set_backend` without touching orchestration (chaining, rendering,
splicing).
"""

from __future__ import annotations

from himark.engine.backend._types import Match
from himark.engine.backend._vm import find_matches as _run_find_matches
from himark.engine.backend.interface import Engine
from himark.models.opcodes import Program

__all__ = ["Engine", "PythonEngine"]


class PythonEngine:
    """The built-in pure-Python backend: the `Program` runs directly on the VM."""

    name = "python"

    def compile(self, program: Program) -> object:
        return program

    def run(
        self,
        compiled: object,
        text: str,
        stages: tuple[Match, ...] = (),
        start: int = 0,
        stop: int | None = None,
    ) -> list[Match]:
        return _run_find_matches(compiled, text, stages, start, stop)  # type: ignore[arg-type]