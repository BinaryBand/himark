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

from himark.engine._anchors import AnchorMap, Woven, carry, drop, place, slice_local
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
    anchors: AnchorMap | None = None,
) -> list[Match]:
    """Return all matches of a compiled query `program` in target. `stages` are
    the earlier pipeline matches a cross-stage reference (`{N$M}`) can resolve;
    `anchors` are the out-of-band named-anchor positions a `{@name}` match consults.

    Preparation runs per call (no cache) — the simplicity-over-speed trade this
    branch wants."""
    return _vm_find_matches(prepare(program), target, stages, anchors)


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
    anchors_in: AnchorMap | None = None,
) -> Woven | None:
    """Transform `text` through the rest of the chain, returning the branch's
    **committed** output as a `Woven` (its text plus the out-of-band marks it carries
    and clears). `ancestors` is the chain of stage matches so far; `committed` is True
    once a template upstream has rendered; `anchors_in` are the named-anchor marks
    within `text` (its own `0..len` frame), which nested queries can match and which
    survive/relocate per the splice remap rules (himark/engine/_anchors.py).

    Eager-commit: a template renders and **commits** that render (the chain
    continues on it, never rolled back). A query splices each match's transform
    in place; a query that matches nothing keeps the committed text if a template
    has rendered, else drops the branch — that is how a guard filters.

    With no marks anywhere (`anchors_in` empty, no emit/clear directive) every mark
    op is a no-op and the assembled text is byte-identical to the plain engine."""
    anchors_in = anchors_in or {}
    if not steps:
        return Woven(text, dict(anchors_in))
    head, rest = steps[0], steps[1:]

    if isinstance(head, Template):
        full, spans, emitted, cleared = _render(head, text, list(ancestors))
        if spans is None:  # no moustaches — the whole render flows on as one branch
            stage = Match(full, 0, len(full), [])
            sub = _transform(rest, full, (*ancestors, stage), True, emitted)
            if sub is None:
                return None
            return Woven(sub.text, sub.anchors, cleared | sub.cleared)
        if not rest:
            return Woven(full, emitted, cleared)
        # Each moustache is a branch: its value flows downstream and its result is
        # spliced back over its own span, keeping the decoration between (the same
        # splice the query branch below runs, with moustaches playing the matches).
        pieces: list[str] = []
        out_anchors: AnchorMap = {}
        all_cleared: set[str] = set(cleared)
        last = 0
        cursor = 0
        for start, end in spans:
            gap = full[last:start]
            pieces.append(gap)
            carry(out_anchors, emitted, last, start, cursor - last)
            cursor += len(gap)
            payload = full[start:end]
            stage = Match(payload, 0, len(payload), [])
            sub = _transform(
                rest,
                payload,
                (*ancestors, stage),
                True,
                slice_local(emitted, start, end),
            )
            if sub is None:
                return None
            place(out_anchors, sub.anchors, cursor)
            all_cleared |= sub.cleared
            pieces.append(sub.text)
            cursor += len(sub.text)
            last = end
        pieces.append(full[last:])
        carry(out_anchors, emitted, last, len(full) + 1, cursor - last)
        return Woven("".join(pieces), out_anchors, frozenset(all_cleared))

    pieces = []
    out_anchors = {}
    all_cleared = set()
    last = 0
    cursor = 0
    matched = False
    for m in find_matches(head, text, ancestors, anchors_in):
        matched = True
        gap = text[last : m.start]
        pieces.append(gap)
        carry(out_anchors, anchors_in, last, m.start, cursor - last)
        cursor += len(gap)
        sub = _transform(
            rest,
            m.text,
            (*ancestors, m),
            committed,
            slice_local(anchors_in, m.start, m.end),
        )
        if sub is None:
            return None
        place(out_anchors, sub.anchors, cursor)
        all_cleared |= sub.cleared
        pieces.append(sub.text)
        cursor += len(sub.text)
        last = m.end
    if not matched:
        return Woven(text, dict(anchors_in)) if committed else None
    pieces.append(text[last:])
    carry(out_anchors, anchors_in, last, len(text) + 1, cursor - last)
    return Woven("".join(pieces), out_anchors, frozenset(all_cleared))


def _deltas(
    steps: list[Step],
    target: str,
    anchors_in: AnchorMap,
) -> list[tuple[int, int, Woven]]:
    """The branches as `(start, end, Woven)`: each surviving first-query match's
    source span and its transformed result (text + carried/cleared marks)."""
    if not steps:
        return []
    head = steps[0]
    if isinstance(head, Template):
        # A leading template has no query to locate matches: the whole document is
        # one branch, with `{{$}}` the entire input. Render the chain over it.
        w = _transform(steps, target, (), anchors_in=anchors_in)
        return [] if w is None else [(0, len(target), w)]
    rest = steps[1:]
    result: list[tuple[int, int, Woven]] = []
    for m in find_matches(head, target, (), anchors_in):
        w = _transform(
            rest, m.text, (m,), anchors_in=slice_local(anchors_in, m.start, m.end)
        )
        if w is not None:
            result.append((m.start, m.end, w))
    return result


def _splice(
    steps: list[Step], target: str, anchors_in: AnchorMap
) -> tuple[str, AnchorMap]:
    """`splice` with the out-of-band `AnchorMap` threaded: carry each gap's marks into
    output coordinates, place each branch's emitted marks, then drop cleared names."""
    out: list[str] = []
    out_anchors: AnchorMap = {}
    cleared: set[str] = set()
    last = 0
    cursor = 0
    for start, end, w in _deltas(steps, target, anchors_in):
        gap = target[last:start]
        out.append(gap)
        carry(out_anchors, anchors_in, last, start, cursor - last)
        cursor += len(gap)
        place(out_anchors, w.anchors, cursor)
        cleared |= w.cleared
        out.append(w.text)
        cursor += len(w.text)
        last = end
    out.append(target[last:])
    carry(out_anchors, anchors_in, last, len(target) + 1, cursor - last)
    drop(out_anchors, cleared)
    return "".join(out), out_anchors


def _splice_fixed(
    steps: list[Step], target: str, anchors_in: AnchorMap
) -> tuple[str, AnchorMap]:
    """`splice_to_fixed_point` with the `AnchorMap` carried across rounds. Convergence
    still compares text (marks are runtime state); the guards are unchanged."""
    text = target
    anchors = anchors_in
    cap = 8 * len(target) + 1024
    size_limit = 64 * len(target) + 65536
    for _ in range(cap):
        result, next_anchors = _splice(steps, text, anchors)
        if result == text:  # nothing changed — the fixed point
            return text, next_anchors
        text = result
        anchors = next_anchors
        if len(text) > size_limit:
            break
    raise CompileError(
        "a `<=` statement did not settle: the rule is not contracting toward a "
        "fixed point (it grows or oscillates). Use `=>` for a single pass."
    )


# ── Renderings ────────────────────────────────────────────────────────────────


def deltas(steps: list[Step], target: str) -> list[tuple[int, int, str]]:
    """The branches as (start, end, text): each surviving first-query match's
    source span and its transformed result. `execute` lists the texts; `splice`
    lays them back over the source."""
    return [(s, e, w.text) for s, e, w in _deltas(steps, target, {})]


def execute(steps: list[Step], target: str) -> list[str]:
    """The list of rendered matches — one entry per surviving leaf branch."""
    return [w.text for _, _, w in _deltas(steps, target, {})]


def splice(steps: list[Step], target: str) -> str:
    """The source with each leaf branch's span replaced by its render, the text
    between branches kept verbatim (in-place transform)."""
    return _splice(steps, target, {})[0]


# ── Pipelines ─────────────────────────────────────────────────────────────────


def splice_to_fixed_point(steps: list[Step], target: str) -> str:
    """Re-splice `steps` over `target` until a pass changes nothing (the fixed
    point) — the in-place form of a `while` loop, for a `<=` statement. A
    contracting rule settles in a few passes per unit of input, so the guards only
    trip on a rule that does not converge (a `CompileError`): a pass count (catches
    oscillators) and a size bound (catches a grower like `{a} <= "aa"`).

    Each pass scans the whole document — the simplest correct loop with no
    tail-pruning. The simplicity-over-speed trade this branch wants."""
    return _splice_fixed(steps, target, {})[0]


def run_pipeline(pipeline: list[list[Step]], target: str) -> str:
    """Run each statement of `pipeline` as a splice pass over `target`, feeding one
    statement's output into the next -- the `.hmk` pipeline. A statement whose head
    step is a fixed point (`<=>`) re-splices to convergence; otherwise it is a single
    pass. The out-of-band `AnchorMap` is threaded statement-to-statement, so a mark a
    template emits survives (offset-remapped) into a later statement that matches or
    clears it; it is discarded at the end (marks never render).

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
    anchors: AnchorMap = {}
    for statement in pipeline:
        head = statement[0]
        if head.fixed_point:
            text, anchors = _splice_fixed(statement, text, anchors)
        else:
            text, anchors = _splice(statement, text, anchors)
    return text
