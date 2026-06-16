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

from marky.engine._render import is_template as _is_template
from marky.engine._render import render as _render
from marky.engine._types import Match
from marky.engine.backend import Engine, PythonEngine
from marky.models import nodes_typed as t

__all__ = [
    "execute",
    "splice",
    "deltas",
    "find",
    "find_matches",
    "Match",
    "Engine",
    "set_backend",
    "get_backend",
]

# The active matching backend. Swap it (e.g. for a native engine) via
# set_backend; orchestration below is backend-agnostic.
_backend: Engine = PythonEngine()


def set_backend(engine: Engine) -> None:
    """Install `engine` as the matching backend for all subsequent calls."""
    global _backend
    _backend = engine


def get_backend() -> Engine:
    """The currently installed matching backend."""
    return _backend


def find_matches(
    tree: t.RootNode, target: str, stages: tuple[Match, ...] = ()
) -> list[Match]:
    """Compile a pattern tree and return all its matches in target. `stages` are
    the earlier pipeline matches a cross-stage reference (`{N$M}`) can resolve."""
    return _backend.run(_backend.compile(tree), target, stages)


def find(steps: list[t.RootNode], target: str) -> list[tuple[int, int]]:
    """Return (start, end) positions of all matches of steps[0] in target."""
    return [(m.start, m.end) for m in find_matches(steps[0], target)]


# ── Branch building ───────────────────────────────────────────────────────────


def _transform(
    steps: list[t.RootNode], text: str, ancestors: tuple[Match, ...]
) -> str | None:
    """Transform `text` through the rest of the chain, returning the branch's
    result — or None when a query in the chain matches nothing (the branch is
    dropped). `ancestors` is the chain of stage matches so far, one per step.

    A template renders (`{{.}}` is `text`) and the chain continues on its render.
    A query splices each match's transform in place; an unmatched query, or a
    sub-transform that drops, drops this branch too."""
    if not steps:
        return text
    head, rest = steps[0], steps[1:]

    if _is_template(head):
        rendered = _render(head, text, list(ancestors))
        stage = Match(rendered, 0, len(rendered), [])
        return _transform(rest, rendered, (*ancestors, stage))

    pieces: list[str] = []
    last = 0
    matched = False
    for m in find_matches(head, text, ancestors):
        matched = True
        sub = _transform(rest, m.text, (*ancestors, m))
        if sub is None:
            return None
        pieces.append(text[last : m.start])
        pieces.append(sub)
        last = m.end
    if not matched:
        return None
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
