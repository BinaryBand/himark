"""Direct execution engine for parsed HMK expressions.

A `=>` chain is `step => step => ...`, where each step is a **query** (a matcher)
or a **template** (plain text with no matchable `{...}`). The first step is a query.

Execution is a **branch model**. Each match of the first query starts a branch;
the rest of the chain transforms that branch's text independently:

* a **query** matches within the branch's text and splices each match's transform
  back in place (keeping the text between matches); a query that matches nothing
  drops the branch — that is how filtering works;
* a **template** renders, and the chain continues on its render — so templates are
  *not* terminal: a later query matches the rendered text, and a later template
  wraps it (`{{.}}` is the flowing text, so templates compose).

Stages are numbered by `=>` position; each step (query or template) appends one,
so `{{ i$j }}` / `{N$M}` address any earlier step by position.

The branches render two ways, neither privileged:

* `execute` — the **list** of branch results (one per first-query match that survives).
* `splice`  — the source with each branch's span replaced by its result, the text
  between branches kept verbatim (in-place transform).
"""

from collections.abc import Iterator
from contextlib import contextmanager

from himark.engine._render import is_template as _is_template
from himark.engine._render import render as _render
from himark.engine.backend import (
    RUST_AVAILABLE,
    Engine,
    Match,
    PythonEngine,
    RustEngine,
)
from himark.engine.runtime import Runtime
from himark.models import nodes_typed as t

__all__ = [
    "execute",
    "splice",
    "deltas",
    "find",
    "find_matches",
    "Match",
    "Engine",
    "PythonEngine",
    "RustEngine",
    "RUST_AVAILABLE",
    "Runtime",
    "set_backend",
    "get_backend",
    "using_backend",
]

# The default runtime owns the active matching backend and the per-tree compile
# cache. Swap the backend via set_backend / using_backend; orchestration below is
# backend-agnostic. (Construct a fresh `Runtime` for an isolated backend + cache.)
_runtime = Runtime()


def set_backend(engine: Engine) -> None:
    """Install `engine` as the matching backend for all subsequent calls."""
    _runtime.backend = engine


def get_backend() -> Engine:
    """The currently installed matching backend."""
    return _runtime.backend


@contextmanager
def using_backend(engine: Engine) -> Iterator[Engine]:
    """Install `engine` for the duration of the `with` block, restoring the
    previously installed backend on exit (even on error)."""
    prev = _runtime.backend
    _runtime.backend = engine
    try:
        yield engine
    finally:
        _runtime.backend = prev


def find_matches(
    tree: t.RootNode, target: str, stages: tuple[Match, ...] = ()
) -> list[Match]:
    """Compile a pattern tree and return all its matches in target. `stages` are
    the earlier pipeline matches a cross-stage reference (`{N$M}`) can resolve."""
    return _runtime.find_matches(tree, target, stages)


def find(steps: list[t.RootNode], target: str) -> list[tuple[int, int]]:
    """Return (start, end) positions of all matches of steps[0] in target."""
    return [(m.start, m.end) for m in find_matches(steps[0], target)]


# ── Branch building ───────────────────────────────────────────────────────────


def _transform(
    steps: list[t.RootNode],
    text: str,
    ancestors: tuple[Match, ...],
    committed: bool = False,
) -> str | None:
    """Transform `text` through the rest of the chain, returning the branch's
    result — its **committed** output. `ancestors` is the chain of stage matches
    so far; `committed` is True once a template upstream has rendered.

    Eager-commit: a template renders and **commits** that render (the chain
    continues on it, never rolled back). A query splices each match's transform
    in place; a query that matches nothing keeps the committed text if a template
    has rendered, else drops the branch — that is how a guard filters."""
    if not steps:
        return text
    head, rest = steps[0], steps[1:]

    if _is_template(head):
        full, payload, span = _render(head, text, list(ancestors))
        stage = Match(payload, 0, len(payload), [])
        if span is None:  # no `{{> }}` — the whole render flows on
            return _transform(rest, full, (*ancestors, stage), committed=True)
        # `{{> }}`: `full` lands in the document; only `payload` flows downstream.
        if not rest:
            return full
        downstream = _transform(rest, payload, (*ancestors, stage), committed=True)
        if downstream is None:
            return None
        return full[: span[0]] + downstream + full[span[1] :]

    pieces: list[str] = []
    last = 0
    matched = False
    for m in find_matches(head, text, ancestors):
        matched = True
        sub = _transform(rest, m.text, (*ancestors, m), committed)
        if sub is None:
            return None
        pieces.append(text[last : m.start])
        pieces.append(sub)
        last = m.end
    if not matched:
        return text if committed else None
    pieces.append(text[last:])
    return "".join(pieces)


def deltas(steps: list[t.RootNode], target: str) -> list[tuple[int, int, str]]:
    """The branches as (start, end, text): each surviving first-query match's
    source span and its transformed result. `execute` lists the texts; `splice`
    lays them back over the source."""
    if not steps:
        return []
    head, rest = steps[0], steps[1:]
    result: list[tuple[int, int, str]] = []
    for m in find_matches(head, target):
        text = _transform(rest, m.text, (m,))
        if text is not None:
            result.append((m.start, m.end, text))
    return result


# ── Renderings ────────────────────────────────────────────────────────────────


def execute(steps: list[t.RootNode], target: str) -> list[str]:
    """The list of rendered matches — one entry per surviving leaf branch."""
    return [text for _, _, text in deltas(steps, target)]


def splice(steps: list[t.RootNode], target: str) -> str:
    """The source with each leaf branch's span replaced by its render, the text
    between branches kept verbatim (in-place transform)."""
    out: list[str] = []
    last = 0
    for start, end, text in deltas(steps, target):
        out.append(target[last:start])
        out.append(text)
        last = end
    out.append(target[last:])
    return "".join(out)
