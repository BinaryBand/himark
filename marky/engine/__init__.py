"""Direct execution engine for parsed HMK expressions."""

from himark.engine._match import find_matches as _find_matches
from himark.engine._render import render as _render
from himark.engine._types import Match, MatchCtx
from himark.models.node import HMKNode

__all__ = ["execute", "find", "Match", "MatchCtx"]


def find(steps: list[HMKNode], target: str) -> list[tuple[int, int]]:
    """Return (start, end) positions of all matches of steps[0] in target."""
    return [(m.start, m.end) for m in _find_matches(steps[0], target)]


def execute(steps: list[HMKNode], target: str) -> list[str]:
    """Execute an ordered list of HMK step trees against target.

    steps[0]      — pattern applied to target
    steps[1:-1]   — intermediate patterns, each applied to the previous step's matches
    steps[-1]     — template (when len > 1) rendered against the final matches
    """
    current = _find_matches(steps[0], target)

    if len(steps) == 1:
        return [m.text for m in current]

    for step_tree in steps[1:-1]:
        next_ = []
        for m in current:
            next_.extend(_find_matches(step_tree, m.text))
        current = next_

    return [_render(steps[-1], m) for m in current]
