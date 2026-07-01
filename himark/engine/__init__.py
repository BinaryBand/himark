"""Direct execution engine for parsed HMK expressions.

A `=>` chain is `step => step => ...`, where each step is a **query** (a matcher)
or a **template** (plain text with no matchable `{...}`).

Execution is a **branch model**. The first step bootstraps the branches: a **query**
starts one per match, while a leading **template** starts a single branch over the
whole document (`{{$}}` is the entire input). The rest of the chain transforms each
branch's text independently:

* a **query** matches within the branch's text and splices each match's transform
  back in place (keeping the text between matches); a query that matches nothing
  drops the branch — that is how filtering works;
* a **template** renders, and the chain continues on its render — so templates are
  *not* terminal: a later query matches the rendered text, and a later template
  wraps it (`{{$}}` is the flowing text, so templates compose).

Stages are numbered by `=>` position; each step (query or template) appends one,
so `{{ i$j }}` / `{N$M}` address any earlier step by position.

The branches render two ways, neither privileged:

* `execute` — the **list** of branch results (one per surviving branch).
* `splice`  — the source with each branch's span replaced by its result, the text
  between branches kept verbatim (in-place transform).
"""

import os

from himark.engine._render import render as _render
from himark.engine._runner import run_pipeline as _subprocess_run_pipeline
from himark.engine._types import Match
from himark.engine._vm import find_matches as _vm_find_matches, prepare
from himark.models.compiled import Program, Step, Template
from himark.models.exceptions import CompileError

# A step is a template (rendered) when it is a `Template`, else a query `Program`
# (matched). `isinstance(step, Template)` is used inline at the dispatch sites so
# the type checker narrows `Step` to the right arm in each branch.

__all__ = [
    "execute",
    "splice",
    "splice_to_fixed_point",
    "run_pipeline",
    "deltas",
    "find",
    "find_matches",
    "Match",
]


def find_matches(
    program: Program,
    target: str,
    stages: tuple[Match, ...] = (),
) -> list[Match]:
    """Return all matches of a compiled query `program` in target. `stages` are
    the earlier pipeline matches a cross-stage reference (`{N$M}`) can resolve.

    Preparation runs per call (no cache) — the simplicity-over-speed trade this
    branch wants."""
    return _vm_find_matches(prepare(program), target, stages)


def find(steps: list[Step], target: str) -> list[tuple[int, int]]:
    """Return (start, end) positions of all matches of steps[0] in target. A leading
    template is the whole-document branch, so its span is the whole input."""
    head = steps[0]
    if isinstance(head, Template):
        return [(0, len(target))]
    return [(m.start, m.end) for m in find_matches(head, target)]


# ── Branch building ───────────────────────────────────────────────────────────


def _transform(
    steps: list[Step],
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

    if isinstance(head, Template):
        full, spans = _render(head, text, list(ancestors))
        if spans is None:  # no moustaches — the whole render flows on as one branch
            stage = Match(full, 0, len(full), [])
            return _transform(rest, full, (*ancestors, stage), committed=True)
        if not rest:
            return full
        # Each moustache is a branch: its value flows downstream and its result is
        # spliced back over its own span, keeping the decoration between (the same
        # splice the query branch below runs, with moustaches playing the matches).
        pieces: list[str] = []
        last = 0
        for start, end in spans:
            payload = full[start:end]
            stage = Match(payload, 0, len(payload), [])
            sub = _transform(rest, payload, (*ancestors, stage), committed=True)
            if sub is None:
                return None
            pieces.append(full[last:start])
            pieces.append(sub)
            last = end
        pieces.append(full[last:])
        return "".join(pieces)

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


def deltas(
    steps: list[Step],
    target: str,
) -> list[tuple[int, int, str]]:
    """The branches as (start, end, text): each surviving first-query match's
    source span and its transformed result. `execute` lists the texts; `splice`
    lays them back over the source."""
    if not steps:
        return []
    head = steps[0]
    if isinstance(head, Template):
        # A leading template has no query to locate matches: the whole document is
        # one branch, with `{{$}}` the entire input. Render the chain over it.
        text = _transform(steps, target, ())
        return [] if text is None else [(0, len(target), text)]
    rest = steps[1:]
    result: list[tuple[int, int, str]] = []
    for m in find_matches(head, target):
        text = _transform(rest, m.text, (m,))
        if text is not None:
            result.append((m.start, m.end, text))
    return result


# ── Renderings ────────────────────────────────────────────────────────────────


def execute(steps: list[Step], target: str) -> list[str]:
    """The list of rendered matches — one entry per surviving leaf branch."""
    return [text for _, _, text in deltas(steps, target)]


def splice(steps: list[Step], target: str) -> str:
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


# ── Pipelines ─────────────────────────────────────────────────────────────────


def splice_to_fixed_point(steps: list[Step], target: str) -> str:
    """Re-splice `steps` over `target` until a pass changes nothing (the fixed
    point) — the in-place form of a `while` loop, for a `<=` statement. A
    contracting rule settles in a few passes per unit of input, so the guards only
    trip on a rule that does not converge (a `CompileError`): a pass count (catches
    oscillators) and a size bound (catches a grower like `{a} <= "aa"`).

    Each pass scans the whole document — the simplest correct loop with no
    tail-pruning. The simplicity-over-speed trade this branch wants."""
    text = target
    cap = 8 * len(target) + 1024
    size_limit = 64 * len(target) + 65536
    for _ in range(cap):
        result = splice(steps, text)
        if result == text:  # nothing changed — the fixed point
            return text
        text = result
        if len(text) > size_limit:
            break
    raise CompileError(
        "a `<=` statement did not settle: the rule is not contracting toward a "
        "fixed point (it grows or oscillates). Use `=>` for a single pass."
    )


def run_pipeline(pipeline: list[list[Step]], target: str) -> str:
    """Run each statement of `pipeline` as a splice pass over `target`, feeding one
    statement's output into the next -- the `.hmk` pipeline. A statement whose head
    step is a fixed point (`<=>`) re-splices to convergence; otherwise it is a single
    pass.

    Runs **in-process** by default: while the grammar is settling the Python engine
    in this package is the single implementation, so the demo/golden suite exercises
    the same code the CLI does. The archived subprocess ports under `sandbox/` are
    still reachable for a re-port check by naming one explicitly, e.g.
    `HMK_ENGINE=rust` (that engine must be built first -- the conftest no longer does
    it). An unset `HMK_ENGINE` (or `inprocess`/`python-inprocess`) stays in-process."""
    name = os.environ.get("HMK_ENGINE")
    if name and name not in ("inprocess", "python-inprocess"):
        return _subprocess_run_pipeline(pipeline, target)
    text = target
    for statement in pipeline:
        head = statement[0]
        if head.fixed_point:
            text = splice_to_fixed_point(statement, text)
        else:
            text = splice(statement, text)
    return text
