"""Direct execution engine for parsed HMK expressions.

A `=>` chain is `pattern => pattern => ... => template`: a run of patterns and an
optional trailing **template** (plain text with no matchable `{...}`). A template
may only be the final step.

Execution is a **branch model**. The first pattern's matches each start a branch;
each later pattern *narrows* a branch (its matches within the branch's text become
sub-branches, dropping branches that don't match); the trailing template renders
each surviving leaf. A leaf carries its absolute span in the source and the chain
of stage matches that produced it (so `{{ i$j }}` can address any stage).

The same branches render two ways — neither privileged:

* `execute` — the **list** of rendered leaves.
* `splice`  — the source with each leaf's span replaced by its render, the text
  between leaves kept verbatim (in-place transform).

Matches (and narrowed sub-matches) are non-overlapping, so leaves own disjoint
spans and the splice is unambiguous.
"""

from marky.engine._render import is_template as _is_template
from marky.engine._render import render as _render
from marky.engine._types import Match
from marky.engine.backend import Engine, PythonEngine
from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError

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


def _split_chain(
    steps: list[t.RootNode],
) -> tuple[list[t.RootNode], t.RootNode | None]:
    """Split a chain into (patterns, trailing_template_or_None). A plain-text
    template is only valid as the final step; one earlier is a compile error."""
    template: t.RootNode | None = None
    patterns = steps
    if len(steps) >= 2 and _is_template(steps[-1]):
        template, patterns = steps[-1], steps[:-1]
    for step in patterns[1:]:
        if _is_template(step):
            raise CompileError(
                "A plain-text template may only be the final step of a '=>' chain"
            )
    return patterns, template


def _leaves(
    patterns: list[t.RootNode],
    text: str,
    offset: int,
    ancestors: tuple[Match, ...],
) -> list[tuple[int, int, tuple[Match, ...]]]:
    """Narrow `patterns` over `text`, returning each leaf as (abs_start, abs_end,
    ancestry). `offset` rebases sub-match spans to the original source; `ancestors`
    is the chain of stage matches so far (for `{N$M}` and `{{ i$j }}`)."""
    head, rest = patterns[0], patterns[1:]
    out: list[tuple[int, int, tuple[Match, ...]]] = []
    for m in find_matches(head, text, ancestors):
        anc = (*ancestors, m)
        if rest:
            out.extend(_leaves(rest, m.text, offset + m.start, anc))
        else:
            out.append((offset + m.start, offset + m.end, anc))
    return out


def deltas(steps: list[t.RootNode], target: str) -> list[tuple[int, int, str]]:
    """The branches as (start, end, text): each leaf's source span and its render.
    `execute` lists the texts; `splice` lays them back over the source."""
    patterns, template = _split_chain(steps)
    result: list[tuple[int, int, str]] = []
    for start, end, anc in _leaves(patterns, target, 0, ()):
        text = (
            _render(template, anc[-1], list(anc))
            if template is not None
            else target[start:end]
        )
        result.append((start, end, text))
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
