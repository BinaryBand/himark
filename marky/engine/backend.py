"""Swappable execution backend for the matching core.

The engine exposes a coarse two-call seam — `compile` a resolved AST into an
opaque handle, then `run` that handle against text. Only this hot path (compile
+ scan) sits behind the seam; orchestration (chaining, rendering, `=>+`
splicing) stays in pure Python and calls `find_matches`.

The seam is deliberately coarse: a native backend (e.g. Rust via PyO3) receives
the whole AST and text and returns `Match` objects, so the scan loop never
crosses the FFI boundary per character. The handle is opaque, paired to the
backend that produced it. The built-in `PythonEngine` wraps `compile_pattern`
plus the generic run loop.
"""

from __future__ import annotations

from typing import Protocol, cast, runtime_checkable

from marky.engine._compile import Element, compile_pattern
from marky.engine._run import find_matches as _run_find_matches
from marky.engine._types import Match
from marky.models import nodes_typed as t


@runtime_checkable
class Engine(Protocol):
    """An execution backend. `compile` returns an opaque handle that the same
    backend's `run` consumes."""

    name: str

    def compile(self, tree: t.RootNode) -> object: ...

    def run(
        self, compiled: object, text: str, stages: tuple[Match, ...] = ()
    ) -> list[Match]: ...


class PythonEngine:
    """The built-in pure-Python backend: `compile_pattern` + the generic loop."""

    name = "python"

    def compile(self, tree: t.RootNode) -> object:
        return compile_pattern(tree)

    def run(
        self, compiled: object, text: str, stages: tuple[Match, ...] = ()
    ) -> list[Match]:
        return _run_find_matches(cast("list[Element]", compiled), text, stages)
