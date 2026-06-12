"""Match results.

A `Capture` is one captured group — its text, its span (relative to the match
start), and its per-repetition pieces. A `Match` is an ordered list of them
plus the matched slice. The legacy parallel-array views (`groups`,
`group_spans`, `sub_groups`, `count_refs`) are derived, so the renderer and
tests keep a stable interface while the engine carries a single source of truth.
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class Capture:
    text: str
    span: tuple[int, int]  # (start, end) relative to the match start
    reps: list[str]  # per-repetition pieces (one entry when count == 1)


@dataclass
class Match:
    text: str
    start: int
    end: int
    captures: list[Capture] = field(default_factory=list)

    @property
    def groups(self) -> list[str]:
        return [c.text for c in self.captures]

    @property
    def group_spans(self) -> list[tuple[int, int]]:
        return [c.span for c in self.captures]

    @property
    def sub_groups(self) -> list[list[str]]:
        return [c.reps for c in self.captures]

    @property
    def count_refs(self) -> dict[int, int]:
        return {i: len(c.reps) for i, c in enumerate(self.captures)}
