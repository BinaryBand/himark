"""Direct execution engine for parsed HMK expressions.

A `=>` chain is `step => step => ...`, where each step is a **query** (a matcher)
or a **template** (plain text with no matchable `{...}`).

Execution is a **branch model**. The first step bootstraps the branches: a **query**
starts one per match, while a leading **template** starts a single branch over the
whole document (`{{.}}` is the entire input). The rest of the chain transforms each
branch's text independently:

* a **query** matches within the branch's text and splices each match's transform
  back in place (keeping the text between matches); a query that matches nothing
  drops the branch — that is how filtering works;
* a **template** renders, and the chain continues on its render — so templates are
  *not* terminal: a later query matches the rendered text, and a later template
  wraps it (`{{.}}` is the flowing text, so templates compose).

Stages are numbered by `=>` position; each step (query or template) appends one,
so `{{ i$j }}` / `{N$M}` address any earlier step by position.

The branches render two ways, neither privileged:

* `execute` — the **list** of branch results (one per surviving branch).
* `splice`  — the source with each branch's span replaced by its result, the text
  between branches kept verbatim (in-place transform).
"""

from collections.abc import Iterator
from contextlib import contextmanager

from himark.engine._render import render as _render
from himark.engine.backend import (
    RUST_AVAILABLE,
    Engine,
    Match,
    PythonEngine,
    RustEngine,
)
from himark.engine.runtime import Runtime
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
    "Engine",
    "PythonEngine",
    "RustEngine",
    "RUST_AVAILABLE",
    "Runtime",
    "set_backend",
    "get_backend",
    "using_backend",
]

# The default runtime owns the active matching backend and the per-program handle
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
    program: Program,
    target: str,
    stages: tuple[Match, ...] = (),
    start: int = 0,
    stop: int | None = None,
) -> list[Match]:
    """Return all matches of a compiled query `program` in target. `stages` are
    the earlier pipeline matches a cross-stage reference (`{N$M}`) can resolve;
    `start`/`stop` bound the positions a match may begin at."""
    return _runtime.find_matches(program, target, stages, start, stop)


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
    steps: list[Step], target: str, stop: int | None = None
) -> list[tuple[int, int, str]]:
    """The branches as (start, end, text): each surviving first-query match's
    source span and its transformed result. `execute` lists the texts; `splice`
    lays them back over the source. `stop` caps where a branch may begin (used by
    `splice_to_fixed_point` to skip the already-settled tail)."""
    if not steps:
        return []
    head = steps[0]
    if isinstance(head, Template):
        # A leading template has no query to locate matches: the whole document is
        # one branch, with `{{.}}` the entire input. Render the chain over it.
        text = _transform(steps, target, ())
        return [] if text is None else [(0, len(target), text)]
    rest = steps[1:]
    result: list[tuple[int, int, str]] = []
    for m in find_matches(head, target, stop=stop):
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

    Incremental (safe but not a left-skip): each pass remembers where its last
    change ended and the next pass only *begins* matches before that point.
    Matching reads forward, so a match that differs this pass must read a byte the
    last pass rewrote — and one can begin no later than the last such byte.
    Everything beyond it is byte-identical to a tail the previous pass already
    scanned and found settled, so re-scanning it for new starts is waste. The dual
    (skipping the *prefix* before the first change) is **unsafe**: a forward-reading
    rule can begin a match before the change and read into it (bubble_sort mis-sorts
    `2,3,1` that way), so only the tail is pruned. The win grows with input size —
    near 1× on a small input, but ~1.4-1.6× on the full dedup file as the tail the
    fixed point has settled grows over its many passes. It is backend-agnostic (the
    native backend honours the same `stop` bound)."""
    text = target
    cap = 8 * len(target) + 1024
    size_limit = 64 * len(target) + 65536
    stop = None  # the first pass scans the whole document
    for _ in range(cap):
        out: list[str] = []
        last = 0
        length = 0  # running length of `out` == offset into the new document
        dirty: int | None = None  # end (new coords) of the right-most real change
        for s, e, repl in deltas(steps, text, stop=stop):
            out.append(text[last:s])
            out.append(repl)
            length += (s - last) + len(repl)
            if repl != text[s:e]:  # an identity rewrite changes nothing, so skip it
                dirty = length
            last = e
        if dirty is None:
            return text  # nothing changed — the fixed point
        out.append(text[last:])
        text = "".join(out)
        stop = dirty  # next pass: no new match can begin past the last change
        if len(text) > size_limit:
            break
    raise CompileError(
        "a `<=` statement did not settle: the rule is not contracting toward a "
        "fixed point (it grows or oscillates). Use `=>` for a single pass."
    )


def run_pipeline(pipeline: list[list[Step]], target: str) -> str:
    """Run a pipeline of statements over `target`, each spliced in turn, returning
    the transformed document. A `<=` (fixed-point) statement — flagged on its first
    step — is re-spliced until the text stops changing (`splice_to_fixed_point`)."""
    text = target
    for steps in pipeline:
        if steps and steps[0].fixed_point:
            text = splice_to_fixed_point(steps, text)
        else:
            text = splice(steps, text)
    return text
