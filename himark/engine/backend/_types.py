"""Match results.

A `Capture` is one captured group — its text, its span (relative to the match
start), its per-repetition pieces (`reps`), and its nested sub-captures (`subs`,
the brace groups written inside a grouping brace). A `Match` is the ordered list
of top-level captures plus the matched slice. The parallel-array views are
derived, so consumers keep a stable interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from himark.models.alphabet import Alphabet, RangeAlphabet


@dataclass(slots=True)
class Capture:
    text: str
    span: tuple[int, int]  # (start, end) relative to the match start
    reps: list[str]  # per-repetition pieces (one entry when count == 1)
    subs: list[Capture] = field(default_factory=list)  # nested capture groups
    # A *deferred* repetition count: while a branch is still backtracking, the run
    # matcher leaves `text` empty and `reps` as the whole untrimmed run, recording
    # the chosen count here (>= 0) so `_finalize` can trim once the branch commits.
    # -1 means already materialized (text + reps are final), as from the Rust seam.
    count: int = -1
    # The value alphabet this group matched under, when it was a `{A::x..y}` bound
    # (else None). It lets a downstream value filter (e.g. `b256`) read the
    # capture as a number in `A`, not just its raw text.
    alphabet: Alphabet | RangeAlphabet | None = None


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
    def sub_groups(self) -> list[list[str]]:
        return [[s.text for s in c.subs] for c in self.captures]

    def capture_at(self, path: tuple[int, ...]) -> Capture | None:
        """Walk a dotted capture path: the first index selects a top-level
        capture, each further index descends into that capture's sub-captures
        (the nested grouping braces). None if any index is out of range, or if
        `path` is empty (callers handle the whole-match case themselves)."""
        captures = self.captures
        cap = None
        for idx in path:
            if not 0 <= idx < len(captures):
                return None
            cap = captures[idx]
            captures = cap.subs
        return cap
