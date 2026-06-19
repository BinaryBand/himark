"""The backend seam — the `Engine` Protocol, with no engine internals.

This is the minimal contract a matching backend implements: `compile` a resolved
AST into an opaque handle, then `run` that handle against text. It depends only
on the shared AST (`models`) and the `Match` result type — never on `_compile` /
`_run` — so a native backend (e.g. Rust via PyO3) can satisfy it without pulling
in the pure-Python core. Because it is a `@runtime_checkable Protocol`, a backend
is matched structurally and need not even import this module.

The built-in implementation lives in `backend.py` (`PythonEngine`).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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
