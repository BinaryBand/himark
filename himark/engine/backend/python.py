"""The built-in pure-Python matching backend.

`PythonEngine` is the default implementation of the `Engine` seam (defined in
`interface.py`): it wraps `compile_pattern` plus the opcode VM in `_vm`.  The
seam is deliberately coarse — a backend receives the whole AST and text and
returns `Match` objects, so the scan never crosses an FFI boundary per
character — which is what lets a native backend (e.g. Rust via PyO3) drop in
via `set_backend` without touching orchestration (chaining, rendering,
splicing).
"""

from __future__ import annotations

from himark.engine.backend._types import Match
from himark.engine.backend._vm import find_matches as _run_find_matches
from himark.engine.backend.interface import Engine
from himark.models import nodes_typed as t
from himark.models.opcodes import Program
from himark.engine.backend._compiler import compile_pattern

__all__ = ["Engine", "PythonEngine"]


class PythonEngine:
    """The built-in pure-Python backend: `compile_pattern` + the opcode VM."""

    name = "python"

    def compile(self, tree: t.RootNode) -> object:
        return compile_pattern(tree)

    def run(
        self,
        compiled: object,
        text: str,
        stages: tuple[Match, ...] = (),
        start: int = 0,
        stop: int | None = None,
    ) -> list[Match]:
        return _run_find_matches(compiled, text, stages, start, stop)  # type: ignore[arg-type]