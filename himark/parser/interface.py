"""The parser seam — the `Parser` Protocol, with no parser internals.

This is the minimal contract a parsing backend implements: `parse` a raw HMK
statement string into a list of resolved `RootNode` trees (one per `=>` step).
It depends only on the shared AST (`models`) — never on the phases — so a native
backend (e.g. Rust via PyO3) can satisfy it without pulling in the pure-Python
core. Because it is a `@runtime_checkable Protocol`, a backend is matched
structurally and need not even import this module.

The built-in implementation lives in `python.py` (`PythonParser`).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from himark.models import nodes_typed as t


@runtime_checkable
class Parser(Protocol):
    """A parsing backend. `parse` accepts a raw HMK statement and returns one
    resolved `RootNode` per `=>` step."""

    name: str

    def parse(self, source: str) -> list[t.RootNode]: ...
