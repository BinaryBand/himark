"""The matching runtime: the active backend plus its compile cache.

A `Runtime` owns the two pieces of engine state that were previously ambient — the
selected `Engine` backend (a module global) and the lowered-program cache (mutable
fields on every `RootNode`). Holding them here makes the state explicit and keeps
the `models` layer free of engine concerns: an AST node is now purely data.

The cache is keyed by tree **identity** and evicted when the tree is garbage
collected (a `weakref.finalize` hook), so a long-lived runtime never retains the
one-off pattern trees that callers parse and discard. Each entry records the
backend that produced it, so swapping `backend` transparently recompiles on next
use — the same invalidation the old per-node `_compiled_by` check did.
"""

from __future__ import annotations

import weakref

from himark.engine.backend import Engine, Match, PythonEngine
from himark.models import nodes_typed as t


class Runtime:
    """Owns the active matching backend and a per-runtime compile cache."""

    def __init__(self, backend: Engine | None = None) -> None:
        self.backend: Engine = backend if backend is not None else PythonEngine()
        # id(tree) -> (lowered program, the backend that produced it)
        self._cache: dict[int, tuple[object, Engine]] = {}

    def compiled(self, tree: t.RootNode) -> object:
        """The tree's lowered program for the active backend, compiled once and
        cached — `_transform` re-runs the same nested query across every branch, so
        recompiling each time is pure waste."""
        key = id(tree)
        hit = self._cache.get(key)
        if hit is not None and hit[1] is self.backend:
            return hit[0]
        program = self.backend.compile(tree)
        if hit is None:
            # First time we cache this tree: evict the entry when the tree dies, so
            # its `id` can't later be recycled onto a stale program. Bind the hook
            # to the cache dict (not `self`) so it never keeps the runtime alive.
            cache = self._cache
            weakref.finalize(tree, cache.pop, key, None)
        self._cache[key] = (program, self.backend)
        return program

    def find_matches(
        self, tree: t.RootNode, target: str, stages: tuple[Match, ...] = ()
    ) -> list[Match]:
        """All matches of `tree` in `target`. `stages` are the earlier pipeline
        matches a cross-stage reference (`{N$M}`) can resolve."""
        return self.backend.run(self.compiled(tree), target, stages)
