"""Direct execution engine for parsed HMK expressions.

A `=>` chain is a list of step trees, each either a *pattern* (a matcher) or a
*template* (renders output). The first step is always a pattern.

Two fold behaviors compose a chain:

* **Top level** — `execute` extracts every match and transforms it, returning a
  list of strings. Non-matches are dropped. A run of patterns
  (`P => P => … => T`) narrows successively; the trailing template renders.
* **Reference conveyor** — a chained template's *references* form its forward
  payload: the remaining chain transforms their rendered text in place via
  `_transform`, while the template's *literal* text is chrome that wraps the
  result. A `{{.}}`-only template reduces to plain deferral of the whole match.
* **Pipe (inner `=>+`)** — a `pattern =>+ template` pair splices the template's
  output at the pattern's matches within the current scope, and the chain
  continues on the spliced text. Spans survive at scope granularity: the
  outermost matches are the splice targets; piped stages are pure text
  computation.
"""

from marky.engine._render import is_template as _is_template
from marky.engine._render import render as _render
from marky.engine._types import Match
from marky.engine.backend import Engine, PythonEngine
from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError

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
    _validate_pipes(steps)
    if steps and steps[0].replace:
        return _transform(steps, target)
    return _run(steps, target)


def _validate_pipes(steps: list[t.RootNode]) -> None:
    for i, step in enumerate(steps):
        if step.piped and (not _is_template(step) or _is_template(steps[i - 1])):
            raise CompileError(
                "An inner '=>+' pipes a pattern into a template "
                "(pattern =>+ template); the chain continues on the spliced text"
            )


def _piped_pair(steps: list[t.RootNode]) -> bool:
    """True when steps open with a `pattern =>+ template` pipe pair."""
    return len(steps) >= 2 and steps[1].piped


def _splice(pattern: t.RootNode, template: t.RootNode, text: str) -> str:
    """Replace each match of `pattern` in `text` with the rendered template."""
    out: list[str] = []
    last = 0
    for m in find_matches(pattern, text):
        out.append(text[last : m.start])
        out.append(_render(template, m))
        last = m.end
    out.append(text[last:])
    return "".join(out)


def _run(steps: list[t.RootNode], text: str) -> list[str]:
    """Top-level extract: find matches of steps[0], transform each, flatten."""
    if _piped_pair(steps):
        spliced = _splice(steps[0], steps[1], text)
        return _run(steps[2:], spliced) if len(steps) > 2 else [spliced]

    matches = find_matches(steps[0], text)
    rest = steps[1:]

    if not rest:
        return [m.text for m in matches]

    head = rest[0]
    if _is_template(head):
        remaining = rest[1:]
        return [_render_chained(head, m, remaining) for m in matches]

    # head is another pattern — feed each match forward and flatten.
    out: list[str] = []
    for m in matches:
        out.extend(_run(rest, m.text))
    return out


def _render_chained(head: t.RootNode, m: Match, remaining: list[t.RootNode]) -> str:
    """Render a chained template. Its **references** (`{{.}}`, `{{N}}`, `{{#N}}`,
    …) form the forward payload: the remaining chain transforms their rendered
    text in order, and the template's **literal** text is chrome that wraps the
    result. The payload is the contiguous span from the first reference to the
    last (interior literals included); leading/trailing literals are the chrome.

    With no remaining chain, or a reference-free (constant) template, this is a
    plain render. A `{{.}}`-only template reduces to the classic deferral, so
    existing chains are unchanged."""
    children = head.children
    refs = [i for i, n in enumerate(children) if not isinstance(n, t.LeafNode)]
    if not remaining or not refs:
        return _render(head, m)
    lo, hi = refs[0], refs[-1]
    prefix = t.RootNode(children=children[:lo])
    region = t.RootNode(children=children[lo : hi + 1])
    suffix = t.RootNode(children=children[hi + 1 :])
    payload = _transform(remaining, _render(region, m))
    return _render(prefix, m) + payload + _render(suffix, m)


def _transform(steps: list[t.RootNode], text: str) -> str:
    """In-place transform: replace each match of steps[0] with the rendered
    remainder, leaving non-matched text untouched. Used for deferred `{{.}}`."""
    if not steps:
        return text

    if _piped_pair(steps):
        spliced = _splice(steps[0], steps[1], text)
        return _transform(steps[2:], spliced) if len(steps) > 2 else spliced

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
        return _render_chained(head, m, rest[1:])
    return _transform(rest, m.text)
