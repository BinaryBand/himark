"""Direct execution engine for parsed HMK expressions.

A `=>` chain is a list of step trees, each either a *pattern* (a matcher) or a
*template* (renders output). The first step is always a pattern.

Two fold behaviors compose a chain:

* **Top level** — `execute` extracts every match and transforms it, returning a
  list of strings. Non-matches are dropped. A run of patterns
  (`P => P => … => T`) narrows successively; the trailing template renders.
* **Deferred `{{.}}`** — when a template's `{{.}}` is reached mid-chain, the
  *remaining* chain is applied to the current match in place via `_transform`,
  preserving the surrounding text. The transformed string is substituted for
  `{{.}}`.
"""

from marky.engine._render import is_template as _is_template
from marky.engine._render import render as _render
from marky.engine._types import Match
from marky.engine.backend import Engine, PythonEngine
from marky.models import nodes_typed as t

__all__ = [
    "execute",
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


def find_matches(tree: t.RootNode, target: str) -> list[Match]:
    """Compile a pattern tree and return all its matches in target."""
    return _backend.run(_backend.compile(tree), target)


def find(steps: list[t.RootNode], target: str) -> list[tuple[int, int]]:
    """Return (start, end) positions of all matches of steps[0] in target."""
    return [(m.start, m.end) for m in find_matches(steps[0], target)]


def execute(steps: list[t.RootNode], target: str) -> list[str] | str:
    """Execute an ordered list of HMK step trees against target.

    steps[0]   — pattern applied to target
    steps[1:]  — alternating patterns / templates (see module docstring)

    Returns the list of rendered matches (`=>`, extract mode), or — when the
    statement used `=>+` — the whole target with each match spliced in place
    as a single string (replace mode).
    """
    if steps and steps[0].replace:
        return _transform(steps, target)
    return _run(steps, target)


def _run(steps: list[t.RootNode], text: str) -> list[str]:
    """Top-level extract: find matches of steps[0], transform each, flatten."""
    matches = find_matches(steps[0], text)
    rest = steps[1:]

    if not rest:
        return [m.text for m in matches]

    head = rest[0]
    if _is_template(head):
        remaining = rest[1:]
        return [
            _render(
                head,
                m,
                _transform(remaining, m.text) if remaining else None,
            )
            for m in matches
        ]

    # head is another pattern — feed each match forward and flatten.
    out: list[str] = []
    for m in matches:
        out.extend(_run(rest, m.text))
    return out


def _transform(steps: list[t.RootNode], text: str) -> str:
    """In-place transform: replace each match of steps[0] with the rendered
    remainder, leaving non-matched text untouched. Used for deferred `{{.}}`."""
    if not steps:
        return text

    matches = find_matches(steps[0], text)
    if not matches:
        return text

    rest = steps[1:]
    out: list[str] = []
    last = 0
    for m in matches:
        out.append(text[last : m.start])
        out.append(_render_match(rest, m))
        last = m.end
    out.append(text[last:])
    return "".join(out)


def _render_match(rest: list[t.RootNode], m: Match) -> str:
    """Render the chain remainder for a single match, in place."""
    if not rest:
        return m.text
    head = rest[0]
    if _is_template(head):
        remaining = rest[1:]
        deferred = _transform(remaining, m.text) if remaining else None
        return _render(head, m, deferred)
    return _transform(rest, m.text)
