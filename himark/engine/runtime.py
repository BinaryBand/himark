"""The matching runtime: the active backend plus its per-backend handle cache.

A `Runtime` owns the two pieces of engine state that were previously ambient — the
selected `Engine` backend (a module global) and the compiled-handle cache. Holding
them here makes the state explicit and keeps the `models` layer free of engine
concerns: a `Program` is purely data.

The parser already lowered the query to a `Program`, so for the Python backend
`compile` is the identity. The cache still earns its keep for a native backend
(e.g. Rust translates the `Program` to JSON once): it is keyed by `Program`
**identity** and evicted when the `Program` is garbage collected (a
`weakref.finalize` hook), so a long-lived runtime never retains the one-off
programs that callers parse and discard. Each entry records the backend that
produced it, so swapping `backend` transparently re-translates on next use.
"""

from __future__ import annotations

import weakref

from himark.engine.backend import Engine, Match, PythonEngine
from himark.models.opcodes import Program


class Runtime:
    """Owns the active matching backend and a per-runtime handle cache."""

    def __init__(self, backend: Engine | None = None) -> None:
        self.backend: Engine = backend if backend is not None else PythonEngine()
        # id(program) -> (backend handle, the backend that produced it)
        self._cache: dict[int, tuple[object, Engine]] = {}

    def compiled(self, program: Program) -> object:
        """The program's backend handle, produced once and cached — `_transform`
        re-runs the same nested query across every branch, so re-translating each
        time (on a native backend) is pure waste."""
        key = id(program)
        hit = self._cache.get(key)
        if hit is not None and hit[1] is self.backend:
            return hit[0]
        handle = self.backend.compile(program)
        if hit is None:
            # First time we cache this program: evict the entry when it dies, so
            # its `id` can't later be recycled onto a stale handle. Bind the hook
            # to the cache dict (not `self`) so it never keeps the runtime alive.
            cache = self._cache
            weakref.finalize(program, cache.pop, key, None)
        self._cache[key] = (handle, self.backend)
        return handle

    def find_matches(
        self,
        program: Program,
        target: str,
        stages: tuple[Match, ...] = (),
        start: int = 0,
        stop: int | None = None,
    ) -> list[Match]:
        """All matches of `program` in `target`. `stages` are the earlier pipeline
        matches a cross-stage reference (`{N$M}`) can resolve; `start`/`stop` bound
        the positions a match may begin at (the incremental-splice scan window)."""
        return self.backend.run(self.compiled(program), target, stages, start, stop)
