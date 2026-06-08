from dataclasses import dataclass, field
from typing import NamedTuple


class MatchCtx(NamedTuple):
    """Immutable per-bracket matching context threaded through content matchers."""

    ci: bool = False
    alphabet: str | None = None
    pad: int | None = None


@dataclass
class Match:
    text: str
    start: int
    end: int
    groups: list[str] = field(default_factory=list)
    group_spans: list[tuple[int, int]] = field(
        default_factory=list
    )  # (start, end) relative to match.start
    sub_groups: list[list[str]] = field(
        default_factory=list
    )  # sub_groups[i] = per-repetition texts for group i
    bindings: dict[str, int] = field(default_factory=dict)
