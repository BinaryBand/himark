"""AST → compiled-step lowering — the *compiler* half of the parser.

The parser front-end (``__init__.py`` + ``_builder.py``) turns source into the
typed AST (``nodes_typed``); this module lowers that AST into the **compiled
product** the engine VM consumes:

  * a **query** AST → a flat opcode ``Program`` (``compile_pattern``);
  * a **template** AST → a ``Template`` of literal + moustache parts
    (``compile_template``).

Keeping both passes in the parser package is what makes "ANTLR is the parser and
the compiler" literally true: the engine is handed ``Program``/``Template`` and
never sees an AST node.
"""

from __future__ import annotations

import re

from typing import cast

from himark.models.compiled import (
    AnchorOp,
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
from himark.parser._generated.GRAMMARParser import GRAMMARParser
from himark.parser._generated.GRAMMARVisitor import GRAMMARVisitor
from himark.models.opcodes import (
    BACK_REF,
    CHAR,
    COMPLEMENT,
    COUNT_REF,
    DYN_RANGE,
    GROUP,
    LIT,
    LOOK_AHEAD,
    LOOK_BEHIND,
    LOOKAROUND,
    NAMED_ANCHOR,
    SEQ_GROUP,
    STAGE_REF,
    VALUE_RANGE,
    Instruction,
)
from himark.models.alphabet import MAX_SYMBOLS, Alphabet, RangeAlphabet
from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError


# ── Reps serialisation ────────────────────────────────────────────────────────


def _reps_tuple(count: t.CountSpec | None) -> tuple:
    """Convert a parsed ``CountSpec`` to the serialised reps tuple."""
    if count is None:
        return (1, 1)
    if isinstance(count, t.CountRefSpec):
        return ("#", count.group)
    if isinstance(count, t.CountSet):
        return ("=", list(count.values))
    return (count.min, -1 if count.max is None else count.max)


# ── Alphabet descriptor ───────────────────────────────────────────────────────


def _alphabet_desc(node: t.SemanticNode) -> tuple:
    """Build an alphabet descriptor ``("range", lo, hi)`` or ``("groups", [[str]])``."""
    if isinstance(node, t.CharRangeNode):
        return ("range", ord(node.start), ord(node.end))
    # ValueRangeNode over @uni with single-char endpoints
    if isinstance(node, t.ValueRangeNode) and isinstance(node.alpha, t.CharRangeNode):
        lo = _static_str(node.lower)
        hi = _static_str(node.upper)
        if lo is not None and len(lo) == 1 and hi is not None and len(hi) == 1:
            return ("range", ord(lo), ord(hi))
    # Materialized alphabet
    groups = _groups(node)
    return ("groups", groups)


def _static_str(end: "str | t.SemanticNode") -> str | None:
    """A band endpoint's concrete value string, or None for Floor/Inf/ref."""
    return end if isinstance(end, str) else None


def _drop_excluded(groups: list[list[str]], exclusions: list[str]) -> list[list[str]]:
    """Remove excluded symbols from groups."""
    if not exclusions:
        return groups
    kept = [[m for m in grp if m not in exclusions] for grp in groups]
    return [grp for grp in kept if grp]


def _normalize_exclusions(
    exclusions: list[str],
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Lower a raw exclusion list into a canonical structure the VM can test against
    without re-parsing: singles for membership tests, ranges for interval tests,
    and multi-char literals for startswith checks.  All JSON-serialisable."""
    singles: list[str] = []
    ranges: list[tuple[str, str]] = []
    literals: list[str] = []
    for e in exclusions:
        if len(e) == 1:
            singles.append(e)
        elif ".." in e:
            lo, sep, hi = e.partition("..")
            ranges.append((lo, hi))
        else:
            literals.append(e)
    return (tuple(singles), tuple(ranges), tuple(literals))


def _codepoint_span(node: t.SemanticNode) -> tuple[int, int] | None:
    """The ``(lo, hi)`` code-point span, or None."""
    if isinstance(node, t.CharRangeNode):
        return ord(node.start), ord(node.end)
    if (
        isinstance(node, t.ValueRangeNode)
        and isinstance(node.alpha, t.CharRangeNode)
        and not node.exclusions
    ):
        low, high = _static_str(node.lower), _static_str(node.upper)
        if (low is None or len(low) == 1) and (high is None or len(high) == 1):
            lo = ord(low) if low is not None else ord(node.alpha.start)
            hi = ord(high) if high is not None else ord(node.alpha.end)
            return lo, hi
    return None


def _value_alphabet(node: t.SemanticNode) -> Alphabet | RangeAlphabet:
    """The alphabet a bound's values are read in."""
    cp = _codepoint_span(node)
    if cp is not None:
        lo, hi = cp
        if hi - lo + 1 > MAX_SYMBOLS:
            return RangeAlphabet(lo, hi)
    return Alphabet(_groups(node), distinct=True)


def _groups(node: t.SemanticNode) -> list[list[str]]:
    """The ordered symbol groups for a value alphabet."""
    if isinstance(node, t.CharRangeNode):
        lo, hi = ord(node.start), ord(node.end)
        if hi - lo + 1 > 0x10000:
            raise CompileError(
                f"Range {node.start!r}..{node.end!r} is too large "
                f"to use as a value bound"
            )
        return _drop_excluded([[chr(c)] for c in range(lo, hi + 1)], node.exclusions)
    if isinstance(node, t.UnionNode):
        groups = [g for o in node.options for g in _groups(o)]
        return _drop_excluded(groups, node.exclusions)
    if isinstance(node, t.LiteralNode):
        return [[node.content]]
    if isinstance(node, t.SequenceNode):
        if len(node.items) != 1:
            raise CompileError(
                "A grouping brace with multiple children cannot be used as a value alphabet"
            )
        return _groups(node.items[0].node)
    if isinstance(node, t.GroupClassNode):
        return [list(grp) for grp in node.groups]
    if isinstance(node, t.ValueRangeNode):
        return _sliced_groups(node)
    raise CompileError(f"Cannot use {type(node).__name__} as a value alphabet")


def _sliced_groups(node: t.ValueRangeNode) -> list[list[str]]:
    """The sub-alphabet between endpoint positions."""
    if node.exclusions:
        raise CompileError("A range with exclusions cannot be a sub-alphabet")
    low, high = _static_str(node.lower), _static_str(node.upper)
    for end in (low, high):
        if end is not None and len(end) != 1:
            raise CompileError(
                f"Sub-alphabet endpoint must be a single symbol, got {end!r}"
            )
    if isinstance(node.alpha, t.CharRangeNode):
        lo = ord(low) if low is not None else ord(node.alpha.start)
        hi = ord(high) if high is not None else ord(node.alpha.end)
        if hi - lo + 1 > 0x10000:
            raise CompileError(
                f"Range {chr(lo)!r}..{chr(hi)!r} is too large to use as a value bound"
            )
        return [[chr(c)] for c in range(lo, hi + 1)]
    groups = _groups(node.alpha)
    alph = Alphabet(groups)
    lo = alph.value(low) if low is not None else 0
    hi = alph.value(high) if high is not None else len(groups) - 1
    return groups[lo : hi + 1]


# ── Value-view computation ────────────────────────────────────────────────────


def _endpoint_value(alph: Alphabet | RangeAlphabet, s: str, which: str) -> int:
    """The positional value of bound endpoint ``s``."""
    bad = next((c for c in s if c not in alph), None)
    if bad is not None:
        raise CompileError(
            f"Bound {which} {s!r} has a symbol not in its alphabet: {bad!r}"
        )
    return alph.value(s)


def _value_view(node: t.ValueRangeNode) -> tuple:
    """Compute ``(alphabet_desc, lo_val, hi_val, wmin, wmax, exclusions)`` for
    a static value-range band.  Returns the operands for a ``VALUE_RANGE`` opcode."""
    alph = _value_alphabet(node.alpha)
    lo_static = _static_str(node.lower)
    hi_static = _static_str(node.upper)

    lo = _endpoint_value(alph, lo_static, "floor") if lo_static is not None else None
    hi = _endpoint_value(alph, hi_static, "ceiling") if hi_static is not None else None

    wf = len(lo_static) if lo_static is not None else None
    wc = len(hi_static) if hi_static is not None else None
    if wf is not None and wc is not None:
        wmin, wmax = min(wf, wc), max(wf, wc)
    elif wf is not None:
        wmin, wmax = wf, None
    else:
        wmin, wmax = 1, wc

    alphabet_desc = (
        ("range", alph.lo, alph.hi)
        if isinstance(alph, RangeAlphabet)
        else ("groups", alph.groups)
    )
    return alphabet_desc, lo, hi, wmin, wmax, _normalize_exclusions(node.exclusions)


# ── Dynamic reference endpoint descriptor ─────────────────────────────────────


def _dynamic_ref(end: "str | t.SemanticNode | None") -> t.SemanticNode | None:
    """A band endpoint's *dynamic* reference, or None."""
    if isinstance(end, (t.BackRefNode, t.CountRefNode, t.StageRefNode)):
        return end
    return None


def _ref_descriptor(ref: t.SemanticNode) -> tuple:
    """A loop-resolvable descriptor for a dynamic reference-endpoint node."""
    if isinstance(ref, t.BackRefNode):
        return ("back", ref.group)
    if isinstance(ref, t.CountRefNode):
        return ("count", ref.group)
    if isinstance(ref, t.StageRefNode):
        return ("stage", ref.stage, ref.path)
    raise CompileError(f"Unsupported bound reference: {type(ref).__name__}")


# ── Value formatting ───────────────────────────────────────────────────────────


def _format_value(alph: Alphabet | RangeAlphabet, value: int, width: int) -> str:
    """Format `value` as a canonical string of `width` in `alph` (most-significant
    first, zero-padded with the alphabet's zero symbol). Both alphabet kinds own
    the codec; this thin wrapper keeps the existing call sites."""
    return alph.encode(value, width)


# ── Group lowering (LiteralNode / UnionNode / GroupClassNode → groups) ────────


def _lower_to_groups(node: t.SemanticNode) -> tuple[list[list[str]], bool]:
    """Lower a semantic node to group-list + het flag, or raise if not a group form."""
    if isinstance(node, t.LiteralNode):
        return [[node.content]], False
    if isinstance(node, t.CharRangeNode):
        lo, hi = ord(node.start), ord(node.end)
        excl = _drop_excluded([[chr(c)] for c in range(lo, hi + 1)], node.exclusions)
        return excl, False
    if isinstance(node, t.UnionNode):
        # Try to merge into one flat group class. If a sub-node is a value-range
        # with multi-char endpoints (e.g. {0..9::9..12} → "12"), _groups raises.
        # Fall back to flattening each option individually into value-strings.
        try:
            groups = _groups(node)
        except CompileError:
            groups = []
            for opt in node.options:
                if isinstance(opt, t.ValueRangeNode):
                    alph = _value_alphabet(opt.alpha)
                    lo_static = _static_str(opt.lower)
                    hi_static = _static_str(opt.upper)
                    if lo_static is None or hi_static is None:
                        raise CompileError(
                            "Cannot lower open-ended value range to groups"
                        )
                    lo_val = _endpoint_value(alph, lo_static, "floor")
                    hi_val = _endpoint_value(alph, hi_static, "ceiling")
                    for val in range(lo_val, hi_val + 1):
                        width = alph.canonical_len(val)
                        # Build the canonical representation of `val` in `alph`
                        s = _format_value(alph, val, width)
                        groups.append([s])
                elif isinstance(opt, t.LiteralNode):
                    groups.append([opt.content])
                elif isinstance(opt, t.CharRangeNode):
                    lo, hi = ord(opt.start), ord(opt.end)
                    for c in range(lo, hi + 1):
                        groups.append([chr(c)])
                else:
                    raise CompileError(f"Cannot lower {type(opt).__name__} to groups")
        return groups, False
    if isinstance(node, t.GroupClassNode):
        return [list(g) for g in node.groups], True
    if isinstance(node, t.ValueRangeNode):
        # Lower the value-range band into its resolved sub-alphabet groups
        try:
            groups = _sliced_groups(node)
        except CompileError:
            # If we can't slice (e.g. has exclusions), fall through to error
            raise CompileError("Cannot lower ValueRangeNode as a group alphabet")
        return groups, False
    if isinstance(node, t.ComplementNode):
        raise CompileError("Complement not expressible as group list")
    raise CompileError(f"Cannot lower {type(node).__name__} as a group alphabet")


# ── Per-construct lowering ────────────────────────────────────────────────────────────
# The single map from a resolved SemanticNode to opcodes. Called by the CST
# compiler (`_AstBuilder.compile_pattern`) — one call per factor.


def _lookaround_operands(inner: t.SemanticNode) -> tuple[int, int, tuple | None]:
    """Reduce a lookaround's inner class to the `(lo, hi, excl)` a `LOOKAROUND`
    matcher tests. A `!{X}` complement is "any char except X's members" (full range
    minus them); a `{@uni}`-style code range is itself. `None` excl is the any-char
    fast path in `_char_match`."""
    if isinstance(inner, t.ComplementNode):
        groups, _ = _lower_to_groups(inner.inner)
        chars = [m for grp in groups for m in grp]
        return 0, 0x10FFFF, _normalize_exclusions(chars)
    cp = _codepoint_span(inner)  # CharRangeNode or a `{@uni}` ValueRangeNode
    if cp is not None:
        lo, hi = cp
        excl_list = getattr(inner, "exclusions", None)
        return lo, hi, _normalize_exclusions(excl_list) if excl_list else None
    raise CompileError(
        "a lookaround operand must be a code-point range (e.g. {@uni}) or a "
        "complement (e.g. !{\\n})"
    )


def _emit_semantic(
    elements: list[Instruction], sem: t.SemanticNode, reps: tuple
) -> None:
    """Emit the opcode(s) for one resolved universe `sem`, repeated `reps`."""
    if isinstance(sem, t.LookaroundNode):  # the one zero-width boundary primitive
        direction = LOOK_BEHIND if sem.direction == "behind" else LOOK_AHEAD
        lo, hi, excl = _lookaround_operands(sem.inner)
        elements.append((LOOKAROUND, direction, sem.negate, lo, hi, excl))
        return
    if isinstance(sem, t.NamedAnchorNode):  # `{@name}` -> zero-width mark assertion
        elements.append((NAMED_ANCHOR, sem.name, sem.negate))
        return
    if isinstance(sem, t.ComplementNode) and isinstance(sem.inner, t.NamedAnchorNode):
        # `!{@name}` is a negative zero-width assertion (no mark here), NOT a
        # character complement -- an out-of-band mark occupies no character.
        elements.append((NAMED_ANCHOR, sem.inner.name, True))
        return
    if isinstance(sem, t.BackRefNode):
        elements.append((BACK_REF, sem.group, reps))
        return
    if isinstance(sem, t.CountRefNode):
        elements.append((COUNT_REF, sem.group, reps))
        return
    if isinstance(sem, t.StageRefNode):
        elements.append((STAGE_REF, sem.stage, list(sem.path), reps))
        return
    if isinstance(sem, t.SequenceNode):  # grouping brace -> one capture, sub-elements
        sub: list[Instruction] = []
        for item in sem.items:
            if (
                item.literal
                and isinstance(item.node, t.LiteralNode)
                and item.node.content
            ):
                sub.append((LIT, item.node.content))
            else:
                _emit_semantic(sub, item.node, item.reps)
        elements.append((SEQ_GROUP, sub, reps))
        return
    if isinstance(sem, t.ValueRangeNode):
        _emit_value_range(elements, sem, reps)
        return
    if isinstance(sem, t.ComplementNode):  # match one char NOT in the inner alphabet
        inner_groups, _ = _lower_to_groups(sem.inner)
        elements.append((COMPLEMENT, inner_groups, reps))
        return
    # Group (LiteralNode, CharRangeNode, UnionNode, GroupClassNode)
    groups, het = _lower_to_groups(sem)
    elements.append((GROUP, groups, het, reps))


def _emit_value_range(
    elements: list[Instruction], sem: t.ValueRangeNode, reps: tuple
) -> None:
    """Emit a value-range band: `DYN_RANGE` (a reference endpoint), the single-code-
    point `@uni` `CHAR` fast path, or a static `VALUE_RANGE`."""
    lo_ref = _dynamic_ref(sem.lower)
    hi_ref = _dynamic_ref(sem.upper)
    if lo_ref or hi_ref:
        alph = _value_alphabet(sem.alpha)
        alphabet_desc = (
            ("range", alph.lo, alph.hi)
            if isinstance(alph, RangeAlphabet)
            else ("groups", alph.groups)
        )
        elements.append(
            (
                DYN_RANGE,
                alphabet_desc,
                _static_str(sem.lower),
                _static_str(sem.upper),
                _ref_descriptor(lo_ref) if lo_ref else None,
                _ref_descriptor(hi_ref) if hi_ref else None,
                _normalize_exclusions(sem.exclusions),
                reps,
            )
        )
        return
    # Fast path: single-code-point @uni band → CHAR
    if (
        isinstance(sem.alpha, t.CharRangeNode)
        and (low_s := _static_str(sem.lower)) is not None
        and len(low_s) == 1
        and (high_s := _static_str(sem.upper)) is not None
        and len(high_s) == 1
    ):
        elements.append(
            (CHAR, ord(low_s), ord(high_s), _normalize_exclusions(sem.exclusions), reps)
        )
        return
    # General static value band → VALUE_RANGE
    alphabet_desc, lo_val, hi_val, wmin, wmax, excl = _value_view(sem)
    elements.append(
        (VALUE_RANGE, alphabet_desc, lo_val, hi_val, wmin, wmax, excl, reps)
    )


# ── Template compilation ──────────────────────────────────────────────────────

# A `{{ … }}` moustache. Recognised only inside a template; a query never reads
# it (and a literal `\{{` in a template is unescaped before this runs, so it does
# not match here — same split the renderer used to do at run time).
_MOUSTACHE_RE = re.compile(r"\{\{(.*?)\}\}")


class _ExprVisitor(GRAMMARVisitor):
    """Lower a `moustacheExpression` CST into an `Expr` tree — the moustache compiler,
    a thin walk over the grammar's own parse rather than a hand-rolled tokenizer and
    recursive descent. The leaf-value semantics the grammar can't state (a `#` needs
    a capture index; a dotted path is a tuple of ints) live in `visitAccessor`.

    `filters` is the declared-filter registry in scope (prelude globals plus any
    script-local `@name =` filters): a `| name` pipe resolves `name` here and bakes
    its compiled body onto the `ExFilter`, so the renderer needs no registry and an
    unknown filter is caught at compile time."""

    def __init__(self, filters: dict[str, object] | None = None) -> None:
        self.filters = filters or {}

    def visitMoustacheExpression(
        self, ctx: GRAMMARParser.MoustacheExpressionContext
    ) -> Expr:
        return self.visit(ctx.pipeExpr())

    def visitPipeExpr(self, ctx: GRAMMARParser.PipeExprContext) -> Expr:
        value = self.visit(ctx.orExpr())
        for f in ctx.filter_():  # `| name` pipes, left-associative
            name = f.NAME().getText()
            if name not in self.filters:
                raise CompileError(f"Unknown template filter: '{name}'")
            body = cast("Expr | list[list[Step]]", self.filters[name])
            value = ExFilter(value, name, body)
        return value

    def _binop_chain(self, ctx) -> Expr:
        """Fold a `operand (OP operand)*` cascade rule left-associatively into
        nested `ExBinOp`s. The operator is a single token between operands; a
        lone operand (no operators) returns its own value untouched."""
        children = list(ctx.getChildren())
        value = self.visit(children[0])
        i = 1
        while i < len(children):
            op = children[i].getText()
            value = ExBinOp(op, value, self.visit(children[i + 1]))
            i += 2
        return value

    # or / xor / and / add / mul all share the single-token fold above.
    visitOrExpr = _binop_chain
    visitXorExpr = _binop_chain
    visitAndExpr = _binop_chain
    visitAddExpr = _binop_chain
    visitMulExpr = _binop_chain

    def visitShiftExpr(self, ctx: GRAMMARParser.ShiftExprContext) -> Expr:
        """`<<`/`>>` are two tokens (`LT LT` / `GT GT`) to keep the `@<<` anchor
        intact, so the operator spans two children -- fold with a stride of three."""
        children = list(ctx.getChildren())
        value = self.visit(children[0])
        i = 1
        while i < len(children):
            op = children[i].getText() + children[i + 1].getText()  # '<<' or '>>'
            value = ExBinOp(op, value, self.visit(children[i + 2]))
            i += 3
        return value

    def visitUnary(self, ctx: GRAMMARParser.UnaryContext) -> Expr:
        if ctx.TILDE() is not None:
            return ExUnOp("~", self.visit(ctx.unary()))
        return self.visit(ctx.primary())

    def visitPrimary(self, ctx: GRAMMARParser.PrimaryContext) -> Expr:
        if ctx.LPAREN() is not None:
            parts = [self.visit(e) for e in ctx.pipeExpr()]
            return parts[0] if len(parts) == 1 else ExConcat(parts)
        if ctx.accessor() is not None:
            return self.visit(ctx.accessor())
        if ctx.INT() is not None:
            return ExLit(ctx.INT().getText())
        return ExLit(ctx.STRING().getText()[1:-1])  # strip the quotes

    def visitAccessor(self, ctx: GRAMMARParser.AccessorContext) -> Expr:
        sigil = ctx.DOLLAR() or ctx.HASH()
        if sigil is None:
            return ExCurrent()  # `.` — a deprecated spelling of bare `$`
        # `INT? (DOLLAR|HASH) (INT (DOT INT)*)?`: an INT before the sigil is the
        # cross-stage index; INTs after it are the dotted capture path.
        sigil_pos = sigil.getSymbol().tokenIndex
        ints = ctx.INT()
        stage = next(
            (int(i.getText()) for i in ints if i.getSymbol().tokenIndex < sigil_pos),
            None,
        )
        path = tuple(
            int(i.getText()) for i in ints if i.getSymbol().tokenIndex > sigil_pos
        )
        is_count = ctx.HASH() is not None
        if not path:
            if is_count:
                raise CompileError("A '#' moustache reference needs a capture index")
            # Bare `$` (no stage, no path) is the pipe's current subject -- the text
            # flowing into this step -- so it is `ExCurrent`, the same value `.` gave.
            # `N$` keeps its cross-stage meaning: stage N's whole match.
            if stage is None:
                return ExCurrent()
            return ExRef(stage=stage, is_count=False, path=None)
        return ExRef(stage=stage, is_count=is_count, path=path)


def _compile_moustache(body: str, filters: dict[str, object] | None = None) -> Expr:
    """Parse one `{{ … }}` body into an `Expr`. The moustache is whitespace-
    insensitive but the shared lexer treats a space as a token, so insignificant
    whitespace is stripped first (the mirror of `strip_insignificant_ws`); then the
    grammar's `moustacheExpression` rule parses it and `_ExprVisitor` lowers it,
    resolving any `| name` filter pipe against `filters`."""
    from himark.parser import _make_parser  # deferred: __init__ imports this module

    tree = _make_parser(_strip_moustache_ws(body)).moustacheExpression()
    return _ExprVisitor(filters).visit(tree)


def _strip_moustache_ws(body: str) -> str:
    """Drop whitespace insignificant to a moustache expression — every space, tab,
    or newline except inside a `"…"` string literal, where it is literal content.
    A `"` always toggles the literal (no escaped-quote form), matching the grammar's
    STRING and the old hand-rolled tokenizer."""
    out: list[str] = []
    inq = False
    for ch in body:
        if ch == '"':
            inq = not inq
            out.append(ch)
        elif inq or not ch.isspace():
            out.append(ch)
    return "".join(out)


def compile_template_text(
    text: str, filters: dict[str, object] | None = None
) -> Template:
    """Lower a template body (the already-unescaped literal text of a `"…"` template,
    or of a brace-free pattern step) into a ``Template``.

    Splits the text into an ordered list of literal strings, ``Moustache``
    references, and ``AnchorOp`` directives — the structure the renderer used to
    recompute by regex on every render. Works straight off text, so it needs no AST
    node. `filters` is the declared-filter registry a `| name` moustache pipe
    resolves against."""
    parts: list[str | Moustache | AnchorOp] = []
    last = 0
    for mo in _MOUSTACHE_RE.finditer(text):
        if mo.start() > last:
            parts.append(text[last : mo.start()])
        parts.append(_compile_moustache_part(mo.group(1), filters))
        last = mo.end()
    if last < len(text):
        parts.append(text[last:])
    return Template(parts=parts)


# A `{{ ... }}` body that is a bare `@name` is an out-of-band anchor **emit** and
# `/name` a **clear** — both currently moustache parse-errors (no `@`/leading-`/` in
# the expression grammar), so repurposing them needs no grammar change.
_EMIT_RE = re.compile(r"@(\w+)")
_CLEAR_RE = re.compile(r"/(\w+)")


def _compile_moustache_part(
    body: str, filters: dict[str, object] | None
) -> "Moustache | AnchorOp":
    """One `{{ … }}` body -> an anchor emit/clear directive (`{{@g}}` / `{{/g}}`) or,
    otherwise, a value `Moustache`."""
    stripped = _strip_moustache_ws(body)
    if (m := _EMIT_RE.fullmatch(stripped)) is not None:
        return AnchorOp(name=m.group(1), clear=False)
    if (m := _CLEAR_RE.fullmatch(stripped)) is not None:
        return AnchorOp(name=m.group(1), clear=True)
    return Moustache(expr=_compile_moustache(body, filters))
