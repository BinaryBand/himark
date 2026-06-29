"""The matching runtime — a light cache of VM-ready instructions keyed by Program identity.

`prepare` lowers a `Program` into VM instructions once; the result is cached and
reused for repeated matches against the same pattern (e.g. a nested transform that
re-runs the same query across many branches).
"""

from __future__ import annotations

import weakref

from himark.engine.backend import Match, prepare
from himark.models.opcodes import Program


class Runtime:
    """A per-program instruction cache keyed by Program identity."""

    def __init__(self) -> None:
        self._cache: dict[int, object] = {}

    def compiled(self, program: Program) -> object:
        """The VM-ready handle for `program`, cached by identity."""
        key = id(program)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        handle = prepare(program)
        cache = self._cache
        weakref.finalize(program, cache.pop, key, None)
        self._cache[key] = handle
        return handle

    def find_matches(
        self,
        program: Program,
        target: str,
        stages: tuple[Match, ...] = (),
        start: int = 0,
        stop: int | None = None,
    ) -> list[Match]:
        """All matches of `program` in `target`."""
        from himark.engine.backend import find_matches as _find

        return _find(self.compiled(program), target, stages, start, stop)
