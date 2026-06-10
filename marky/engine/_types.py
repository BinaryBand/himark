from dataclasses import dataclass, field


@dataclass
class Match:
    text: str
    start: int
    end: int

    # Capture groups in document order (one entry per brace_group / separator)
    groups: list[str] = field(default_factory=list)

    # (start, end) offsets relative to match.start for each group
    group_spans: list[tuple[int, int]] = field(default_factory=list)

    # sub_groups[i] = per-repetition texts for group i (when count > 1)
    sub_groups: list[list[str]] = field(default_factory=list)

    # count_refs[i] = how many times group i was repeated
    count_refs: dict[int, int] = field(default_factory=dict)
