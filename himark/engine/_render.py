"""Render a template step (the right-hand side of `=>`) against the pipeline.

A template step is literal text that may contain **moustache** references:

  * `{{ $ }}` — the pipe's current subject: the whole text flowing into this step.
    After a query it is the matched text; after a template it is that template's
    render — so `{{$}}` composes through templates (each wraps the previous one's
    output). (`.` is a deprecated spelling of the same thing.)
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

Evaluation flows **universes**, not raw strings (see `Universe`): each moustache
node yields a `<alphabet, band, value>` object and is only collapsed to text at
the `render` boundary. Today every universe renders to its own text (identity), so
output is byte-for-byte what the string evaluator produced; the value channel is
scaffolding for the template operators in docs/ALGEBRA.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from himark.engine._types import Match
from himark.models.alphabet import Alphabet, RangeAlphabet
from himark.models.compiled import (
    ExBinOp,
    ExConcat,
    ExCurrent,
    ExFilter,
    ExLit,
    ExRef,
    ExUnOp,
    Expr,
    Moustache,
    Template,
)
from himark.models.exceptions import CompileError


# ── Universe: the one render-time value ────────────────────────────────────────


@dataclass(slots=True)
class Universe:
    """A render-time value: text plus, when known, the `alphabet` codec the text was
    captured under. This is the `<alphabet, band, value>` object of docs/ALGEBRA.md
    in its Step-1 form -- band and operator arithmetic arrive with the template
    operators; for now a universe carries its text and (optionally) its codec, and
    `render` is identity, so threading it changes no output.

    A universe with no alphabet is a plain `@uni` string (a match spanning several
    alphabets, a literal, a concatenation) -- text with no positional value.

    `band` is the closed value band `(lo, hi)` the text was captured under, when
    known -- the cardinality `n = hi - lo + 1` an operator normalizes onto; None
    for an open/absent band (no wrap)."""

    text: str
    alphabet: Alphabet | RangeAlphabet | None = None
    band: tuple[int, int] | None = None

    def render(self) -> str:
        return self.text

    @property
    def value(self) -> int | None:
        """The positional ordinal of `text` under its alphabet, or None for a plain
        string universe. Unused until operators consume it (docs/ALGEBRA.md)."""
        return self.alphabet.value(self.text) if self.alphabet is not None else None


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
    flows as one branch -- signalled by `spans` being None. `current` is `{{$}}`.

    The literal/moustache split and the moustache expressions were both compiled
    up front (`compile_template_text`); this only *evaluates* each `Expr`
    against the pipeline stages — no lexing, no parsing."""
    out: list[str] = []
    length = 0
    spans: list[tuple[int, int]] = []
    for part in template.parts:
        if isinstance(part, Moustache):
            value = _eval(part.expr, current, stages).render()
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


def _eval(expr: Expr, current: str, stages: list[Match]) -> Universe:
    """Evaluate a compiled moustache `Expr` to a `Universe` against the stages."""
    if isinstance(expr, ExLit):
        return Universe(expr.text)
    if isinstance(expr, ExCurrent):
        return Universe(current)  # `{{$}}` — the flowing subject (a @uni string)
    if isinstance(expr, ExRef):
        return _eval_ref(expr, stages)
    if isinstance(expr, ExConcat):
        # A concatenation is always a plain @uni string (docs/ALGEBRA.md).
        return Universe("".join(_eval(p, current, stages).render() for p in expr.parts))
    if isinstance(expr, ExFilter):
        text = _apply_filter(expr.name, _eval(expr.src, current, stages).render())
        return Universe(text)
    if isinstance(expr, ExBinOp):
        lhs = _eval(expr.lhs, current, stages)
        rhs = _eval(expr.rhs, current, stages)
        raw = _BINOPS[expr.op](_operand_value(lhs), _operand_value(rhs))
        return _encode(raw, lhs)  # LHS alphabet + band win
    if isinstance(expr, ExUnOp):
        operand = _eval(expr.operand, current, stages)
        return _encode(~_operand_value(operand), operand)  # only `~` today
    raise CompileError(f"Unknown moustache expression: {type(expr).__name__}")


# ── Value operators (docs/ALGEBRA.md) ──────────────────────────────────────────

# Every operator is total: it computes on the operands' integer values and never
# traps. `/` and `%` are defined at zero (`x/0 = x%0 = 0`); "or" is the backtick
# (`|` is the filter pipe). Meaningfulness (e.g. bitwise over a non-2^k band) is a
# separate L2/lint concern -- the engine just computes.
_BINOPS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a // b if b != 0 else 0,
    "%": lambda a, b: a % b if b != 0 else 0,
    "&": lambda a, b: a & b,
    "^": lambda a, b: a ^ b,
    "`": lambda a, b: a | b,  # backtick-or
    "<<": lambda a, b: a << b,
    ">>": lambda a, b: a >> b,
}


def _operand_value(u: Universe) -> int:
    """The integer an operand contributes. A universe with an alphabet reads its
    positional value; a bare decimal literal reads in base 10; anything else (a
    general `@uni` string) contributes 0 -- total but non-meaningful (an L2 lint
    concern, not an engine trap)."""
    if u.alphabet is not None:
        v = u.value
        return v if v is not None else 0
    try:
        return int(u.text)  # a bare (possibly signed) decimal literal or result
    except ValueError:
        return 0


def _normalize(v: int, lo: int, hi: int) -> int:
    """Collapse a raw integer onto band `[lo, hi]`: `lo + (v - lo) mod n` with
    `n = hi - lo + 1`, using floored mod so negatives wrap correctly (ALGEBRA)."""
    n = hi - lo + 1
    return lo + (v - lo) % n


def _encode(raw: int, lhs: Universe) -> Universe:
    """Render an operator's raw integer back to a `Universe`, LHS-wins: normalize
    onto the LHS band (if any), then encode through the LHS alphabet at the LHS
    operand's width (grown if the result needs more symbols). With no LHS alphabet
    the value has no positional codec, so it renders as its decimal spelling."""
    alph, band = lhs.alphabet, lhs.band
    res = _normalize(raw, band[0], band[1]) if band is not None else raw
    if alph is None:
        return Universe(str(res))
    if res < 0:
        # Unbanded underflow: no `n` to wrap onto, so no positional spelling --
        # fall back to a signed decimal (banded arithmetic wraps and never lands
        # here). A documented edge of the total algebra.
        return Universe(str(res), alph, band)
    width = max(len(lhs.text), alph.canonical_len(res))
    return Universe(alph.encode(res, width), alph, band)


def _eval_ref(ref: ExRef, stages: list[Match]) -> Universe:
    """Resolve a capture accessor against the stages — the one part that genuinely
    needs run-time data (the stages), so it stays here, not in the parser. A group
    matched under a `{A::x..y}` bound carries its alphabet `A` forward; the whole
    match and a count are plain strings (no single positional alphabet)."""
    pipe_idx = ref.stage if ref.stage is not None else len(stages) - 1
    if not 0 <= pipe_idx < len(stages):
        raise CompileError(f"Moustache stage {pipe_idx} is out of range")
    stage = stages[pipe_idx]
    if ref.path is None:
        return Universe(stage.text)  # `$` / `N$` — the stage's whole text
    capture = stage.capture_at(ref.path)
    if capture is None:
        raise CompileError(f"Moustache capture {ref.path} is out of range")
    if ref.is_count:
        return Universe(str(len(capture.reps)))
    return Universe(capture.text, capture.alphabet, capture.band)


def _apply_filter(name: str, text: str) -> str:
    """Apply one named filter. The set is closed and native (`trim`, `indent`); an
    unknown name is an error (the parser already rejected arguments)."""
    fn = _FILTERS.get(name)
    if fn is None:
        raise CompileError(f"Unknown template filter: '{name}'")
    return fn(text)
