"""The native (Rust) matching backend — an opt-in accelerator behind the `Engine`
seam.

`RustEngine` runs the **structural** subset of the language in Rust (literals,
anchors, capturing groups over the char-class grammar, back-references, plain
repetition) and **falls back to `PythonEngine`** for any pattern it does not yet
implement (value bounds, count/stage references, grouping braces). So swapping it
in via `set_backend(RustEngine())` is always correct — it only changes *how* a
pattern matches, never *whether*.

It is opt-in: the native module `himark_rs` is built separately
(`maturin develop --release -m rust/Cargo.toml`). If it is not built,
`RUST_AVAILABLE` is False and constructing `RustEngine` raises — nothing else in
the engine is affected, and `PythonEngine` stays the default.
"""

from __future__ import annotations

import json
from typing import Any, cast

from himark.engine.backend._translate import Unsupported, to_json
from himark.engine.backend._types import Capture, Match
from himark.engine.backend.python import PythonEngine
from himark.models.opcodes import Program

# The native module is built separately and has no type stubs, so it is held as
# `Any`. Absent (not built) → `RUST_AVAILABLE` is False and `RustEngine` raises.
_rs: Any = None
RUST_AVAILABLE = False
try:
    import himark_rs as _himark_rs

    _rs = _himark_rs
    RUST_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the build
    pass

__all__ = ["RustEngine", "RUST_AVAILABLE"]


class RustEngine:
    """The native backend: Rust for the supported subset, Python by fallback.

    `compile` returns a tagged handle — `("rs", program)` for the Rust matcher, or
    `("py", compiled)` when translation hit an unsupported construct — that this
    backend's own `run` dispatches on (the seam's opaque-handle contract)."""

    name = "rust"

    def __init__(self) -> None:
        if not RUST_AVAILABLE:
            raise RuntimeError(
                "himark_rs is not built; run "
                "`maturin develop --release -m rust/Cargo.toml`"
            )
        self._fallback = PythonEngine()

    def compile(self, program: Program) -> object:
        try:
            program_json = to_json(program.elements)
        except Unsupported:
            return ("py", self._fallback.compile(program))
        return ("rs", _rs.compile(program_json))

    def run(
        self,
        compiled: object,
        text: str,
        stages: tuple[Match, ...] = (),
        start: int = 0,
        stop: int | None = None,
    ) -> list[Match]:
        tag, handle = cast("tuple[str, Any]", compiled)
        if tag == "py":
            return self._fallback.run(handle, text, stages, start, stop)
        # `stages` only feed the (unsupported) reference elements, so the Rust
        # subset ignores them. `stop` bounds where a match may begin (the
        # incremental-fixed-point scan window); `None` means scan to the end —
        # the native loop takes the char length for that. (`start` is unused: the
        # orchestration only ever prunes the tail, never the prefix.) JSON in the
        # seam's currency: rebuild Match/Capture.
        out: list[Match] = []
        for m in json.loads(handle.run(text, len(text) if stop is None else stop)):
            mtext = text[m["s"] : m["e"]]
            captures = [
                Capture(mtext[c["s"] : c["e"]], (c["s"], c["e"]), c["reps"])
                for c in m["caps"]
            ]
            out.append(Match(mtext, m["s"], m["e"], captures))
        return out