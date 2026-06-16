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

from marky.engine._render import has_refs as _has_refs
from marky.engine._render import is_template as _is_template
from marky.engine._render import render as _render
from marky.engine._render import render_parts as _render_parts
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


def find_matches(
    tree: t.RootNode, target: str, stages: tuple[Match, ...] = ()
) -> list[Match]:
    """Compile a pattern tree and return all its matches in target. `stages` are
    the earlier pipeline matches a cross-stage reference (`{N$M}`) can resolve."""
    return _backend.run(_backend.compile(tree), target, stages)


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


def _splice(
    pattern: t.RootNode,
    template: t.RootNode,
    text: str,
    ancestors: tuple[Match, ...] = (),
) -> str:
    """Replace each match of `pattern` in `text` with the rendered template."""
    out: list[str] = []
    last = 0
    for m in find_matches(pattern, text, ancestors):
        out.append(text[last : m.start])
        out.append(_render(template, m, [*ancestors, m]))
        last = m.end
    out.append(text[last:])
    return "".join(out)


def _run(
    steps: list[t.RootNode], text: str, ancestors: tuple[Match, ...] = ()
) -> list[str]:
    """Top-level extract: find matches of steps[0], transform each, flatten.

    `ancestors` are the matches of earlier pipeline stages, kept so a template's
    `{{ i$j }}` moustache can address any stage by index."""
    if _piped_pair(steps):
        spliced = _splice(steps[0], steps[1], text, ancestors)
        return _run(steps[2:], spliced, ancestors) if len(steps) > 2 else [spliced]

    matches = find_matches(steps[0], text, ancestors)
    rest = steps[1:]

    if not rest:
        return [m.text for m in matches]

    head = rest[0]
    if _is_template(head):
        remaining = rest[1:]
        return [_render_chained(head, m, remaining, ancestors) for m in matches]

    # head is another pattern — feed each match forward and flatten.
    out: list[str] = []
    for m in matches:
        out.extend(_run(rest, m.text, (*ancestors, m)))
    return out


def _render_chained(
    head: t.RootNode,
    m: Match,
    remaining: list[t.RootNode],
    ancestors: tuple[Match, ...] = (),
) -> str:
    """Render a template against the pipeline. The template's moustache
    references (`{{ i$j }}`) interpolate stage values; its literal text is
    constant. `ancestors` plus the feeding match `m` form the addressable stages.

    A trailing chain (`remaining`) re-matches the forwarded text. A mid-pipe
    template with moustache references feeds only its interpolated payload to the
    next link; its literal chrome wraps the result (line-39 conveyor). A constant
    mid-pipe template has no payload to split, so its whole text is forwarded.

    A mid-pipe template is itself an addressable stage: it appends its result to
    the ancestry (as a text-only stage with no captures) so a later template can
    reference it by index. The feeding match `m` is appended first, then this
    template — preserving one stage per `=>` step in document order."""
    pipeline = [*ancestors, m]
    if not remaining:
        return _render(head, m, pipeline)

    def _stage(text: str) -> Match:
        return Match(text, 0, len(text), [])

    if not _has_refs(head):
        flowed = _render(head, m, pipeline)
        return _transform(remaining, flowed, (*ancestors, m, _stage(flowed)))
    prefix, payload, suffix = _render_parts(head, m, pipeline)
    onward = _transform(remaining, payload, (*ancestors, m, _stage(payload)))
    return prefix + onward + suffix


def _transform(
    steps: list[t.RootNode], text: str, ancestors: tuple[Match, ...] = ()
) -> str:
    """In-place transform: replace each match of steps[0] with the rendered
    remainder, leaving non-matched text untouched (used by `=>+` replace mode)."""
    if not steps:
        return text

    if _piped_pair(steps):
        spliced = _splice(steps[0], steps[1], text, ancestors)
        return (
            _transform(steps[2:], spliced, ancestors) if len(steps) > 2 else spliced
        )

    matches = find_matches(steps[0], text, ancestors)
    if not matches:
        return text

    rest = steps[1:]
    out: list[str] = []
    last = 0
    for m in matches:
        out.append(text[last : m.start])
        out.append(_render_match(rest, m, ancestors))
        last = m.end
    out.append(text[last:])
    return "".join(out)


def _render_match(
    rest: list[t.RootNode], m: Match, ancestors: tuple[Match, ...] = ()
) -> str:
    """Render the chain remainder for a single match, in place."""
    if not rest:
        return m.text
    head = rest[0]
    if _is_template(head):
        return _render_chained(head, m, rest[1:], ancestors)
    return _transform(rest, m.text, (*ancestors, m))
