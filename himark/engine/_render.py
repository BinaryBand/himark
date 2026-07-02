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
from typing import cast

from himark.engine._anchors import AnchorMap, place
from himark.engine._types import Match
from himark.models.alphabet import Alphabet, RangeAlphabet
from himark.models.compiled import (
    AnchorOp,
    ExAlpha,
    ExBinOp,
    ExConcat,
    ExCurrent,
    ExFilter,
    ExLit,
    ExRef,
    ExUnOp,
    Expr,
    Moustache,
    Step,
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


def render(
    template: Template,
    current: str,
    stages: list[Match],
    anchors_in: AnchorMap | None = None,
) -> tuple[str, list[tuple[int, int]] | None, AnchorMap, frozenset[str]]:
    """Render a `Template` into `(full, spans, emitted, cleared)`. `full` is the whole
    render -- what **lands** in the document. `spans` are the `(start, end)` of each
    moustache's value within `full`: each is a **branch** that flows downstream
    independently, spliced back over its own span, with the literal text between
    (decoration) kept -- the same splice a query runs, with each moustache playing the
    part of a match. A template with **no** moustaches has nothing to single out, so
    its whole render flows as one branch -- signalled by `spans` being None.
    `current` is `{{$}}`. `emitted` are the out-of-band marks a `{{@name}}` directive
    drops **plus** the marks a passthrough moustache carries (below); `cleared` the
    names a `{{/name}}` directive removes.

    `anchors_in` are the out-of-band marks within `current` (its own `0..len` frame,
    which is also the current stage's match-start frame). A moustache that is a bare
    text **passthrough** -- `{{$}}` (the whole subject) or `{{$N}}` / `{{$N.M}}` (a
    current-stage capture) -- re-emits source text verbatim, so its interior marks
    ride along: they are placed into `emitted` at the moustache's output offset. That
    is what lets a mark survive a capture-and-re-emit (a `{{$4}}` copy), so an
    out-of-band anchor can delimit text that a splice moves around (see dedup.hmk). An
    operator/filter/concat moustache transforms the text, so its marks do not apply.

    The literal/moustache split and the moustache expressions were both compiled
    up front (`compile_template_text`); this only *evaluates* each `Expr`
    against the pipeline stages — no lexing, no parsing."""
    anchors_in = anchors_in or {}
    out: list[str] = []
    length = 0
    spans: list[tuple[int, int]] = []
    emitted: AnchorMap = {}
    cleared: set[str] = set()
    for part in template.parts:
        if isinstance(part, AnchorOp):  # zero-width mark op -- no text, no branch
            if part.clear:
                cleared.add(part.name)
            else:
                place(emitted, {part.name: (0,)}, length)
        elif isinstance(part, Moustache):
            value = _eval(part.expr, current, stages).render()
            start = length
            out.append(value)
            length += len(value)
            spans.append((start, length))
            carried = _passthrough_marks(part.expr, stages, anchors_in)
            if carried:
                place(emitted, carried, start)
        else:
            out.append(part)
            length += len(part)
    full = "".join(out)
    return full, (spans or None), emitted, frozenset(cleared)


def _passthrough_marks(
    expr: Expr, stages: list[Match], anchors_in: AnchorMap
) -> AnchorMap | None:
    """The out-of-band marks a **passthrough** moustache re-emits, in the value's own
    `0..len` frame, or None if the moustache is not a verbatim text passthrough.

    A passthrough copies source text unchanged, so its interior marks travel with it:
    `{{$}}` (or `{{N$}}` for the current stage) carries the whole subject's marks;
    `{{$N.M}}` a capture's interior marks (`[cs, ce)` of its span, rebased). A cross-
    stage reference to an *earlier* stage is not a passthrough here -- that stage's
    marks are not in `anchors_in` -- and anything computed (operator, filter, concat,
    literal, count) is not verbatim, so both return None."""
    if isinstance(expr, ExCurrent):
        return dict(anchors_in)  # `{{$}}` — the whole current subject, marks and all
    if not isinstance(expr, ExRef) or expr.is_count:
        return None
    if expr.stage is not None and expr.stage != len(stages) - 1:
        return None  # an earlier stage's marks are not carried in this frame
    if expr.path is None:
        return dict(anchors_in)  # `{{$}}` / `{{N$}}` — the current stage's whole text
    cap = stages[-1].capture_at(expr.path) if stages else None
    if cap is None:
        return None
    cs, ce = cap.span
    out: AnchorMap = {}
    for name, positions in anchors_in.items():
        local = tuple(p - cs for p in positions if cs <= p < ce)
        if local:
            out[name] = local
    return out


# ── Expression evaluation (the parser already built the `Expr`) ────────────────


def _eval(
    expr: Expr,
    current: str,
    stages: list[Match],
    subject: Universe | None = None,
) -> Universe:
    """Evaluate a compiled moustache `Expr` to a `Universe` against the stages.

    `subject` is the universe bound to `$` inside a **value-shaped filter body** —
    the pipe's actual subject, carrying its alphabet + band so `$ * 2` keeps the
    subject's width. It is None at the top level, where `$` is the flowing text."""
    if isinstance(expr, ExLit):
        return Universe(expr.text)
    if isinstance(expr, ExCurrent):
        # `{{$}}` — the pipe's subject: the filter subject inside a value-filter
        # body, else the flowing text (a plain @uni string).
        return subject if subject is not None else Universe(current)
    if isinstance(expr, ExRef):
        return _eval_ref(expr, stages)
    if isinstance(expr, ExConcat):
        # A concatenation is always a plain @uni string (docs/ALGEBRA.md).
        return Universe(
            "".join(_eval(p, current, stages, subject).render() for p in expr.parts)
        )
    if isinstance(expr, ExAlpha):
        # A named alphabet reference -- ``| name`` desugared to a codec carrier
        # (docs/ALGEBRA.md: a named alphabet is a universe whose value is 0). The
        # text is the alphabet's encoding of zero at width 1 so it carries a sane
        # width for `_encode`; the value of 0 makes it an identity operand in binary
        # ops -- ``a + hex`` is ``value(a) + 0`` rendered under ``hex``. Its band is
        # **None**: a cast is a lossless recode, so the codec never imposes a wrap --
        # the value's domain stays the LHS band (``_encode`` prefers it).
        return Universe(expr.alphabet.encode(0, 1), expr.alphabet, None)
    if isinstance(expr, ExFilter):
        return _apply_filter(expr, current, stages, subject)
    if isinstance(expr, ExBinOp):
        lhs = _eval(expr.lhs, current, stages, subject)
        rhs = _eval(expr.rhs, current, stages, subject)
        raw = _BINOPS[expr.op](_operand_value(lhs), _operand_value(rhs))
        return _encode(raw, lhs, rhs)  # RHS alphabet wins, band from RHS or LHS
    if isinstance(expr, ExUnOp):
        operand = _eval(expr.operand, current, stages, subject)
        return _encode(~_operand_value(operand), operand, operand)  # only `~` today
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


def _encode(raw: int, lhs: Universe, rhs: Universe) -> Universe:
    """Render an operator's raw integer back into a `Universe`, splitting the two
    channels of the result universe by operand:

      * **alphabet (codec) -- RHS wins** when the RHS carries one, else LHS. This is
        the `| name` cast mechanic: `$0 | hex` desugars to `$0 + hex`, and the hex
        codec (the RHS) spells the result.
      * **band (value domain) -- LHS wins** when the LHS carries one, else RHS. A
        cast is a lossless recode, so the target codec never shrinks the domain: the
        value keeps the LHS band (or none), so `$0 | hex` re-spells the whole value
        rather than wrapping onto the alphabet's own tiny range.

    Width comes from the operand that supplied the alphabet (grown to fit the value).
    With no alphabet at all, the value has no positional codec and renders decimal."""
    if rhs.alphabet is not None:
        alph, text_len = rhs.alphabet, len(rhs.text)
    elif lhs.alphabet is not None:
        alph, text_len = lhs.alphabet, len(lhs.text)
    else:
        return Universe(str(raw))  # no positional codec -> decimal
    band = lhs.band if lhs.band is not None else rhs.band

    res = _normalize(raw, band[0], band[1]) if band is not None else raw
    if res < 0:
        # Unbanded underflow: no `n` to wrap onto, so no positional spelling --
        # fall back to a signed decimal (banded arithmetic wraps and never lands
        # here). A documented edge of the total algebra.
        return Universe(str(res), alph, band)
    width = max(text_len, alph.canonical_len(res))
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


def _apply_filter(
    expr: ExFilter, current: str, stages: list[Match], subject: Universe | None
) -> Universe:
    """Apply a declared filter pipe `src | name`. The compiler baked the filter's
    compiled body onto `expr.body` (docs/HMK.md), so there is no registry here:

      * a value-shaped filter (`body` is an `Expr`, from a single `{{ … }}`
        moustache) is evaluated with `$` bound to the subject universe, so the
        subject's alphabet + band flow through the arithmetic;
      * a document-shaped filter (`body` is a `list[list[Step]]` pipeline) runs over
        the subject's rendered text, yielding a plain `@uni` string.

    The pipeline runner is reached by a **deferred** import: `engine/__init__`
    imports this module, so the cycle can only close at call time (and it keeps the
    engine free of any parser import)."""
    src = _eval(expr.src, current, stages, subject)
    body = expr.body
    if body is None:
        raise CompileError(f"Unknown template filter: '{expr.name}'")
    if isinstance(body, list):  # document-shaped: splice the pipeline over the text
        from himark.engine import run_pipeline

        return Universe(run_pipeline(cast("list[list[Step]]", body), src.render()))
    return _eval(body, current, stages, subject=src)  # value-shaped: `$` is the subject
