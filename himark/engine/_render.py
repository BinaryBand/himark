"""Render a template step (the right-hand side of `=>`) against the pipeline.

A template step is literal text that may contain **moustache** references:

  * `{{ . }}` — the whole text flowing into this step. After a query it is the
    matched text; after a template it is that template's render — so `{{.}}`
    composes through templates (each wraps the previous one's output).
  * `{{ i$j }}` — capture group `j` of pipeline stage `i`
  * `{{ i$ }}`  — the whole match of stage `i`
  * `{{ i#j }}` — the repetition count of group `j` of stage `i`

The capture part is a dotted **path**: `i$j.k.l` selects stage `i`'s capture
`j`, then descends into its sub-captures (`.k`, `.l`, …) — the nested groups of
a grouping brace `{…{a}{b}…}`. So `1$2.3` is stage 1, capture 2, sub-capture 3.

Stages are numbered by `=>` position from 0; a template stage carries its render
but no captures. The pipeline index `i` may be omitted to mean the current stage,
and the capture path may be omitted with `$` to mean the whole match. Literal text
(everything outside `{{ }}`) is constant.
"""

from himark.engine.backend import Match
from himark.models.compiled import (
    ExConcat,
    ExCurrent,
    ExFilter,
    ExLit,
    ExRef,
    Expr,
    Moustache,
    Template,
)
from himark.models.exceptions import CompileError


def _indent(s: str) -> str:
    """Prefix every line of `s` with one tab. A line filter (not a scalar one): it
    reshapes multi-line text rather than the whole string at once, which is what
    lets indentation **accumulate** under an inside-out wrap — text re-indented by
    each enclosing pass ends up as deep as its nesting (see scripts/html_format.hmk)."""
    return "" if s == "" else "\t" + s.replace("\n", "\n\t")


# The native filter set — closed and string-only: `trim` strips surrounding
# whitespace; `indent` tabs every line. Filters take no arguments (the parser
# enforces that); the template layer only ever moves text.
_FILTERS = {
    "trim": str.strip,
    "indent": _indent,
}


def render(
    template: Template, current: str, stages: list[Match]
) -> tuple[str, list[tuple[int, int]] | None]:
    """Render a `Template` into `(full, spans)`. `full` is the whole render -- what
    **lands** in the document. `spans` are the `(start, end)` of each moustache's
    value within `full`: each is a **branch** that flows downstream independently,
    spliced back over its own span, with the literal text between (decoration) kept
    -- the same splice a query runs, with each moustache playing the part of a match.
    A template with **no** moustaches has nothing to single out, so its whole render
    flows as one branch -- signalled by `spans` being None. `current` is `{{.}}`.

    The literal/moustache split and the moustache expressions were both compiled
    up front (`compile_template`/`parse_expr`); this only *evaluates* each `Expr`
    against the pipeline stages — no lexing, no parsing."""
    out: list[str] = []
    length = 0
    spans: list[tuple[int, int]] = []
    for part in template.parts:
        if isinstance(part, Moustache):
            value = _eval(part.expr, current, stages)
            start = length
            out.append(value)
            length += len(value)
            spans.append((start, length))
        else:
            out.append(part)
            length += len(part)
    full = "".join(out)
    return full, (spans or None)


# ── Expression evaluation (the parser already built the `Expr`) ────────────────


def _eval(expr: Expr, current: str, stages: list[Match]) -> str:
    """Evaluate a compiled moustache `Expr` to text against the pipeline stages."""
    if isinstance(expr, ExLit):
        return expr.text
    if isinstance(expr, ExCurrent):
        return current  # `{{.}}` — the whole flowing text
    if isinstance(expr, ExRef):
        return _eval_ref(expr, stages)
    if isinstance(expr, ExConcat):
        return "".join(_eval(p, current, stages) for p in expr.parts)
    if isinstance(expr, ExFilter):
        return _apply_filter(expr.name, _eval(expr.src, current, stages))
    raise CompileError(f"Unknown moustache expression: {type(expr).__name__}")


def _eval_ref(ref: ExRef, stages: list[Match]) -> str:
    """Resolve a capture accessor against the stages — the one part that genuinely
    needs run-time data (the stages), so it stays here, not in the parser."""
    pipe_idx = ref.stage if ref.stage is not None else len(stages) - 1
    if not 0 <= pipe_idx < len(stages):
        raise CompileError(f"Moustache stage {pipe_idx} is out of range")
    stage = stages[pipe_idx]
    if ref.path is None:
        return stage.text  # `$` / `N$` — the stage's whole text
    capture = stage.capture_at(ref.path)
    if capture is None:
        raise CompileError(f"Moustache capture {ref.path} is out of range")
    return str(len(capture.reps)) if ref.is_count else capture.text


def _apply_filter(name: str, text: str) -> str:
    """Apply one named filter. The set is closed and native (`trim`, `indent`); an
    unknown name is an error (the parser already rejected arguments)."""
    fn = _FILTERS.get(name)
    if fn is None:
        raise CompileError(f"Unknown template filter: '{name}'")
    return fn(text)
