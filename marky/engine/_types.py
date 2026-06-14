"""Match results.

A `Capture` is one captured group — its text, its span (relative to the match
start), its per-repetition pieces (`reps`, for `{{#N}}`), and its nested
sub-captures (`subs`, the brace groups written inside it, for `{{N.M}}`). A
`Match` is the ordered list of top-level captures plus the matched slice. The
parallel-array views are derived, so the renderer keeps a stable interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Capture:
    text: str
    span: tuple[int, int]  # (start, end) relative to the match start
    reps: list[str]  # per-repetition pieces (one entry when count == 1)
    subs: list[Capture] = field(default_factory=list)  # nested capture groups


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
        return [[s.text for s in c.subs] for c in self.captures]
