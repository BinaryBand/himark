"""The pure-Python parsing backend — the default implementation of the `Parser` seam.

Wraps the four-phase pipeline (phase0 → phase1 → phase2 → phase3) behind the
single `parse` method the seam requires. A caller that wants to swap in the Rust
backend uses `set_parser(RustParser())` and this implementation is bypassed.
"""

from __future__ import annotations

from himark.models import nodes_typed as t
from himark.parser import phase0, phase1, phase2, phase3


class PythonParser:
    name = "python"

    def parse(self, source: str) -> list[t.RootNode]:
        steps = phase0.split_statement(source)
        return [
            phase3.parse(phase2.parse(phase1.preprocess(step, first=i == 0)))
            for i, step in enumerate(steps)
        ]
