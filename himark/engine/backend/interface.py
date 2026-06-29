"""The backend seam — the `Engine` Protocol, with no engine internals.

This is the minimal contract a matching backend implements: `compile` a compiled
query `Program` into an opaque handle, then `run` that handle against text. It
depends only on the shared `Program` IR (`models`) and the `Match` result type —
never on the VM internals — so a native backend (e.g. Rust via PyO3) can satisfy
it without pulling in the pure-Python core. Because it is a `@runtime_checkable
Protocol`, a backend is matched structurally and need not even import this module.

The built-in implementation lives in `python.py` (`PythonEngine`), whose `compile`
is the identity (the `Program` *is* the executable for the VM).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from himark.engine.backend._types import Match
from himark.models.opcodes import Program


@runtime_checkable
class Engine(Protocol):
    """An execution backend. `compile` returns an opaque handle that the same
    backend's `run` consumes."""

    name: str

    def compile(self, program: Program) -> object: ...

    def run(
        self,
        compiled: object,
        text: str,
        stages: tuple[Match, ...] = (),
        start: int = 0,
        stop: int | None = None,
    ) -> list[Match]: ...
