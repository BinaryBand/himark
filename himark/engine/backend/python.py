"""The built-in pure-Python matching backend.

`PythonEngine` is the default implementation of the `Engine` seam (defined in
`interface.py`): it wraps `compile_pattern` plus the generic backtracking loop in
`_run`. The seam is deliberately coarse — a backend receives the whole AST and
text and returns `Match` objects, so the scan never crosses an FFI boundary
per character — which is what lets a native backend (e.g. Rust via PyO3) drop in
via `set_backend` without touching orchestration (chaining, rendering, splicing).
"""

from __future__ import annotations

from typing import cast

from himark.engine.backend._compile import Element, compile_pattern
from himark.engine.backend._run import find_matches as _run_find_matches
from himark.engine.backend._types import Match
from himark.engine.backend.interface import Engine
from himark.models import nodes_typed as t

__all__ = ["Engine", "PythonEngine"]


class PythonEngine:
    """The built-in pure-Python backend: `compile_pattern` + the generic loop."""

    name = "python"

    def compile(self, tree: t.RootNode) -> object:
        return compile_pattern(tree)

    def run(
        self, compiled: object, text: str, stages: tuple[Match, ...] = ()
    ) -> list[Match]:
        return _run_find_matches(cast("list[Element]", compiled), text, stages)
