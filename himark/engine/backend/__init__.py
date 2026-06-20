"""The swappable matching backend — the compile+run pair behind the `Engine` seam.

This subpackage holds everything that turns a resolved AST into matches and is
private to one backend: the `Engine` Protocol (`interface`), the built-in
pure-Python implementation (`python.PythonEngine`), the pattern compiler
(`_compile`), the backtracking matcher (`_run`), the `Alphabet` model
(`alphabet`), and the `Match`/`Capture` seam types (`_types`). It depends only on
`himark.models` — never on the orchestration layer above it (`engine.__init__`,
`engine._render`) — so a native backend (e.g. Rust via PyO3) can replace it
wholesale via `engine.set_backend` without pulling in the Python core.

The swap unit is the whole pair: `compile` returns an opaque handle that only the
*same* backend's `run` consumes, so the compiler and runner are never mixed
across backends.
"""

from himark.engine.backend.alphabet import (
    MAX_SYMBOLS,
    Alphabet,
    RangeAlphabet,
)
from himark.engine.backend.interface import Engine
from himark.engine.backend.python import PythonEngine
from himark.engine.backend.rust import RUST_AVAILABLE, RustEngine
from himark.engine.backend._types import Capture, Match

__all__ = [
    "Engine",
    "PythonEngine",
    "RustEngine",
    "RUST_AVAILABLE",
    "Match",
    "Capture",
    "Alphabet",
    "RangeAlphabet",
    "MAX_SYMBOLS",
]
