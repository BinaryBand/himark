"""ANTLR visitor that walks the CST and builds the AST.

Replaces the manual `isinstance` dispatch in `_Resolver` with ANTLR's
double-dispatch. Each labeled alternative in the grammar gets a `visit*` method,
so adding a grammar rule means adding a visitor method Ã¢â‚¬â€ no `elif isinstance(...)`
branch to forget.

The output is the same AST (`himark.models.nodes_typed`) that `_Resolver` produces.
The free helpers (escapes, whitespace, variables) live in `_helpers.py`.
"""

from __future__ import annotations

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError
from himark.models.opcodes import LIT, Instruction, Program
from himark.parser._compiler import _emit_semantic, _reps_tuple
from himark.parser._helpers import _resolve_leaf_escapes, unescape
from himark.parser._generated.GRAMMARParser import GRAMMARParser
from himark.parser._generated.GRAMMARVisitor import GRAMMARVisitor


# Ã¢â€â‚¬Ã¢â€â‚¬ Pure helpers (no environment, same as original __init__.py) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬


def _ambient_alpha() -> t.SemanticNode:
    return t.CharRangeNode.uni()


_EXCLUDABLE = (t.ValueRangeNode, t.UnionNode)


def _attach_exclusions(node: t.SemanticNode, exclusions: list[str]) -> t.SemanticNode:
    if exclusions and isinstance(node, _EXCLUDABLE):
        node.exclusions = exclusions
    return node


def _arm_group(node: t.SemanticNode) -> list[list[str]] | None:
    if isinstance(node, t.LiteralNode):
        return [[node.content]]
    if isinstance(node, t.GroupClassNode):
        if all(len(g) == 1 for g in node.groups):
            return [[m for g in node.groups for m in g]]
        return [list(g) for g in node.groups]
    return None


def _apply_member_exclusions(members: list[str], exclusions: list[str]) -> list[str]:
    if not exclusions:
        return members
    singles = {e for e in exclusions if ".." not in e}
    ranges = [tuple(e.split("..", 1)) for e in exclusions if ".." in e]
    return [
        m
        for m in members
        if m not in singles and not any(lo <= m <= hi for lo, hi in ranges)
    ]


def _atom_is_literal(atom: GRAMMARParser.AtomContext) -> bool:
    return (
        atom.litToken() is not None
        or atom.ESC() is not None
        or atom.HEX_ESC() is not None
    )




def _term_singleton(term: GRAMMARParser.TermContext) -> str | None:
    atoms = term.atom()
    if all(_atom_is_literal(a) for a in atoms):
        return unescape(term.getText())
    if len(atoms) == 1 and atoms[0].braceGroup() is not None and atoms[0].count() is None:
        return _brace_singleton(atoms[0].braceGroup())
    return None


def _brace_singleton(bg: GRAMMARParser.BraceGroupContext) -> str | None:
    band = bg.band()
    if not isinstance(band, GRAMMARParser.BareAlphabetContext):
        return None  # a band or a grouping/sequence brace is never a literal singleton
    arms = band.universe().arm()
    if len(arms) != 1:
        return None
    arm = arms[0]
    if not isinstance(arm, GRAMMARParser.SingleContext):
        return None
    return _term_singleton(arm.term())


def _arm_as_exclusion(arm: GRAMMARParser.ArmContext) -> list[str] | None:
    if not isinstance(arm, GRAMMARParser.SingleContext):
        return None
    term = arm.term()
    atoms = term.atom()
    if len(atoms) != 1 or atoms[0].complement() is None:
        return None
    operand_band = atoms[0].complement().braceGroup().band()
    if not isinstance(operand_band, GRAMMARParser.BareAlphabetContext):
        raise CompileError("an exclusion operand must be a simple alphabet, not a band")
    return [a.getText().strip() for a in operand_band.universe().arm()]


#Ã¢â€â‚¬Ã¢â€â‚¬ Reference / Anchor resolution (unchanged from original) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬


def _resolve_reference_atom(ref: GRAMMARParser.ReferenceContext) -> t.SemanticNode:
    sigil = ref.DOLLAR() or ref.HASH()
    ints = ref.INT()
    leading_int = bool(ints) and ints[0].getSymbol().tokenIndex < sigil.getSymbol().tokenIndex
    if leading_int:
        stage = int(ints[0].getText())
        index = int(ints[1].getText()) if len(ints) == 2 else None
    else:
        stage = None
        index = int(ints[0].getText())
    return t.reference_from_view(
        is_count=ref.HASH() is not None, stage=stage, index=index
    )


def _resolve_anchor_atom(anchor: GRAMMARParser.AnchorContext) -> t.AnchorNode:
    lts = anchor.LT()
    is_start = bool(lts)
    is_document = len(lts or anchor.GT()) == 2
    if is_document:
        return t.AnchorNode(at="doc_start" if is_start else "doc_end")
    return t.AnchorNode(at="line_start" if is_start else "line_end")


def _count_int(term: GRAMMARParser.CountTermContext, count: GRAMMARParser.CountContext) -> int:
    if term.INT() is None:
        raise CompileError(f"Invalid count expression: {count.getText()}")
    return int(term.INT().getText())


def _resolve_count(count: GRAMMARParser.CountContext) -> t.CountSpec:
    arms = count.countBody().countArm()
    if len(arms) > 1:
        values: set[int] = set()
        for arm in arms:
            if not isinstance(arm, GRAMMARParser.ExactCountContext):
                raise CompileError(f"Invalid count expression: {count.getText()}")
            values.add(_count_int(arm.countTerm(), count))
        return t.CountSet(values=sorted(values))
    arm = arms[0]
    if isinstance(arm, GRAMMARParser.ExactCountContext):
        term = arm.countTerm()
        if term.countRef() is not None:
            return t.CountRefSpec(group=int(term.countRef().INT().getText()))
        n = _count_int(term, count)
        return t.CountRange(min=n, max=n)
    if isinstance(arm, GRAMMARParser.FullOpenCountContext):
        return t.CountRange(min=0, max=None)
    if isinstance(arm, GRAMMARParser.OpenLowerCountContext):
        return t.CountRange(min=0, max=_count_int(arm.countTerm(), count))
    if isinstance(arm, GRAMMARParser.OpenUpperCountContext):
        return t.CountRange(min=_count_int(arm.countTerm(), count), max=None)
    return t.CountRange(
        min=_count_int(arm.countTerm(0), count),
        max=_count_int(arm.countTerm(1), count),
    )


# Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â
# VISITOR Ã¢â‚¬â€ one method per labeled grammar alternative
# Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â


class _AstBuilder(GRAMMARVisitor):
    """Walk an ANTLR CST and build the AST (`himark.models.nodes_typed`).

    Replaces the `_Resolver` class in `__init__.py`. The dispatch is ANTLR's
    double-dispatch (visitor pattern) instead of manual `isinstance` chains.
    """

    def __init__(self, env: dict[str, str]) -> None:
        super().__init__()
        self._env = env
        self._resolving: set[str] = set()
        self._parsed_env: dict[str, GRAMMARParser.BandContext] = {}

    # Ã¢â€â‚¬Ã¢â€â‚¬ Environment Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

    def _get_parsed_body(self, name: str) -> GRAMMARParser.BandContext:
        if name not in self._parsed_env:
            from himark.parser.__init__ import _parse_pattern_tree

            tree = _parse_pattern_tree("{" + self._env[name] + "}")
            brace = tree.pattern().factor()[0].braceGroup()
            if brace is None:
                raise CompileError(f"variable @{name} is not a universe: {self._env[name]!r}")
            self._parsed_env[name] = brace.band()
        return self._parsed_env[name]

    def _resolve_variable(self, name: str) -> t.SemanticNode:
        if name not in self._env:
            return t.LiteralNode(content="@" + name)
        if name in self._resolving:
            raise CompileError(f"circular variable definition: @{name} references itself")
        self._resolving.add(name)
        try:
            return self.visit(self._get_parsed_body(name))
        finally:
            self._resolving.discard(name)

    # Ã¢â€â‚¬Ã¢â€â‚¬ Entry: pattern Ã¢â€ â€™ Program (CST Ã¢â€ â€™ opcodes via a transient semantic IR) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

    def compile_pattern(self, pattern: GRAMMARParser.PatternContext) -> Program:
        """Compile a pattern CST into an opcode `Program`. It walks the factors,
        building a transient semantic node (`models.nodes_typed`) per construct via
        the visitor and lowering it to opcodes with `_emit_semantic` — the engine
        only ever receives the resulting `Program`, never a semantic node.
        """
        elements: list[Instruction] = []
        for factor in pattern.factor():
            count_ctx = factor.count()
            reps = _reps_tuple(_resolve_count(count_ctx) if count_ctx else None)
            if factor.braceGroup() is not None:
                _emit_semantic(elements, self.visit(factor.braceGroup().band()), reps)
            elif factor.complement() is not None:
                band = factor.complement().braceGroup().band()
                _emit_semantic(
                    elements, t.ComplementNode(inner=self.visit(band)), reps
                )
            else:  # literalRun
                if count_ctx is not None:
                    raise CompileError(
                        "a repetition count cannot apply to bare literal text; "
                        "put the text in a brace, e.g. {x}[2]"
                    )
                content = _resolve_leaf_escapes(factor.literalRun().getText())
                if content:
                    elements.append((LIT, content))
        return Program(elements=tuple(elements))

    # Ã¢â€â‚¬Ã¢â€â‚¬ Band alternatives Ã¢â€ â€™ SemanticNode Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    # (These replace the isinstance chains in _Resolver.resolve_brace_body)

    def visitValueBand(self, ctx: GRAMMARParser.ValueBandContext) -> t.SemanticNode:
        """Resolve a `{payload::spec}` band Ã¢â‚¬â€ explicit payload alphabet."""
        alpha = self._resolve_universe(ctx.universe(0))
        spec = ctx.universe(1)
        options = [self._resolve_band_arm(alpha, arm) for arm in spec.arm()]
        return options[0] if len(options) == 1 else t.UnionNode(options=options)

    def visitAmbientBand(self, ctx: GRAMMARParser.AmbientBandContext) -> t.SemanticNode:
        """Resolve a `{::spec}` band Ã¢â‚¬â€ implicit @uni payload alphabet."""
        alpha = _ambient_alpha()
        spec = ctx.universe()
        options = [self._resolve_band_arm(alpha, arm) for arm in spec.arm()]
        return options[0] if len(options) == 1 else t.UnionNode(options=options)

    def visitBareAlphabet(self, ctx: GRAMMARParser.BareAlphabetContext) -> t.SemanticNode:
        return self._resolve_universe(ctx.universe())

    def visitSequenceBrace(self, ctx: GRAMMARParser.SequenceBraceContext) -> t.SemanticNode:
        """Build a grouping/sequence brace from its structurally-typed children.

        The grammar's `sequence` rule already separates literal text runs (`seqText`)
        from nested constructs (`seqUnit`), so each interior element is read directly,
        in document order — no terminal re-walking and no literal/construct mask."""
        items: list[t.SeqItem] = []
        for child in ctx.sequence().getChildren():
            if isinstance(child, GRAMMARParser.SeqUnitContext):
                items.append(self._seq_unit(child))
            else:  # SeqTextContext
                self._seq_text(child, items)
        return t.SequenceNode(items=items)

    def _seq_unit(self, ctx: GRAMMARParser.SeqUnitContext) -> t.SeqItem:
        """A nested `braceGroup`/`complement` element of a sequence, with its count."""
        count_ctx = ctx.count()
        reps = _reps_tuple(_resolve_count(count_ctx)) if count_ctx else (1, 1)
        if ctx.braceGroup() is not None:
            node: t.SemanticNode = self.visit(ctx.braceGroup().band())
        else:
            inner = ctx.complement().braceGroup().band()
            node = t.ComplementNode(inner=self.visit(inner))
        return t.SeqItem(node=node, reps=reps)

    def _seq_text(self, ctx: GRAMMARParser.SeqTextContext, items: list[t.SeqItem]) -> None:
        """A run of `seqAtom`s: literal text folds into one `LIT` item, while a macro,
        reference, or anchor breaks the run into its own resolved item."""
        buf: list[str] = []

        def flush() -> None:
            if buf:
                content = _resolve_leaf_escapes("".join(buf))
                items.append(t.SeqItem(node=t.LiteralNode(content=content), literal=True))
                buf.clear()

        for atom in ctx.seqAtom():
            if atom.macro() is not None:
                flush()
                items.append(t.SeqItem(node=self._resolve_variable(atom.macro().NAME().getText())))
            elif atom.reference() is not None:
                flush()
                items.append(t.SeqItem(node=_resolve_reference_atom(atom.reference())))
            elif atom.anchor() is not None:
                flush()
                items.append(t.SeqItem(node=_resolve_anchor_atom(atom.anchor())))
            else:  # seqLit / ESC / HEX_ESC — literal text
                buf.append(atom.getText())
        flush()

    # Ã¢â€â‚¬Ã¢â€â‚¬ Band arm resolution (isinstance here is type-matching for parameter
    #     shapes, not dispatch routing Ã¢â‚¬â€ universe arms and band arms share the
    #     same ArmContext types but need different construction) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

    def _resolve_band_arm(self, alpha: t.SemanticNode, arm: GRAMMARParser.ArmContext) -> t.ValueRangeNode:
        if isinstance(arm, GRAMMARParser.SingleContext):
            value, ref = self._band_endpoint(arm.term())
            return t.ValueRangeNode.band_arm(alpha, value, ref, value, ref)
        lower = upper = None
        lower_ref = upper_ref = None
        if isinstance(arm, GRAMMARParser.ClosedRangeContext):
            lower, lower_ref = self._band_endpoint(arm.term(0))
            upper, upper_ref = self._band_endpoint(arm.term(1))
        elif isinstance(arm, GRAMMARParser.OpenUpperContext):
            lower, lower_ref = self._band_endpoint(arm.term())
        elif isinstance(arm, GRAMMARParser.OpenLowerContext):
            upper, upper_ref = self._band_endpoint(arm.term())
        return t.ValueRangeNode.band_arm(alpha, lower, lower_ref, upper, upper_ref)

    def _band_endpoint(self, term: GRAMMARParser.TermContext) -> tuple[str | None, t.SemanticNode | None]:
        atoms = term.atom()
        if len(atoms) == 1 and atoms[0].reference() is not None:
            return None, _resolve_reference_atom(atoms[0].reference())
        sval = _term_singleton(term)
        if sval is None:
            raise CompileError("a band bound must be a literal value or a reference")
        return sval, None

    # Ã¢â€â‚¬Ã¢â€â‚¬ Arm alternatives Ã¢â€ â€™ SemanticNode Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    # (These replace isinstance in _Resolver.resolve_arm)

    def visitSingle(self, ctx: GRAMMARParser.SingleContext) -> t.SemanticNode:
        return self._resolve_term(ctx.term())

    def visitClosedRange(self, ctx: GRAMMARParser.ClosedRangeContext) -> t.SemanticNode:
        terms = ctx.term()
        av = _term_singleton(terms[0])
        bv = _term_singleton(terms[1])
        if av is None or bv is None:
            raise CompileError("a `..` range endpoint must be a literal value")
        return t.ValueRangeNode(alpha=t.CharRangeNode.uni(), lower=av, upper=bv)

    def visitOpenUpper(self, ctx: GRAMMARParser.OpenUpperContext) -> t.SemanticNode:
        raise CompileError(
            "an open-ended range like {a..} or {..z} is only valid as a band bound "
            "(e.g. {@d::0..}), not as a bare alphabet"
        )

    def visitOpenLower(self, ctx: GRAMMARParser.OpenLowerContext) -> t.SemanticNode:
        raise CompileError(
            "an open-ended range like {a..} or {..z} is only valid as a band bound "
            "(e.g. {@d::0..}), not as a bare alphabet"
        )

    # Ã¢â€â‚¬Ã¢â€â‚¬ Universe Ã¢â€ â€™ SemanticNode Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

    def _resolve_universe(self, universe: GRAMMARParser.UniverseContext) -> t.SemanticNode:
        arms: list[GRAMMARParser.ArmContext] = []
        exclusions: list[str] = []
        for arm in universe.arm():
            exc = _arm_as_exclusion(arm)
            if exc is not None:
                exclusions.extend(exc)
            else:
                arms.append(arm)
        if not arms:
            raise CompileError(f"Empty brace group: {{{universe.getText()}}}")
        return self._classify_arms(arms, exclusions)

    def _classify_arms(self, arms: list[GRAMMARParser.ArmContext], exclusions: list[str]) -> t.SemanticNode:
        if len(arms) == 1:
            return _attach_exclusions(self.visit(arms[0]), exclusions)

        resolved = [self.visit(a) for a in arms]
        per_arm = [_arm_group(n) for n in resolved]
        if all(g is not None for g in per_arm):
            groups: list[list[str]] = []
            for arm_groups in per_arm:
                assert arm_groups is not None
                for grp in arm_groups:
                    kept = _apply_member_exclusions(grp, exclusions)
                    if kept:
                        groups.append(kept)
            return t.GroupClassNode(groups=groups)
        return _attach_exclusions(t.UnionNode(options=resolved), exclusions)

    # Ã¢â€â‚¬Ã¢â€â‚¬ Term Ã¢â€ â€™ SemanticNode Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

    def _resolve_term(self, term: GRAMMARParser.TermContext) -> t.SemanticNode:
        atoms = term.atom()
        if len(atoms) == 1 and atoms[0].reference() is not None:
            return _resolve_reference_atom(atoms[0].reference())
        if len(atoms) == 1 and atoms[0].anchor() is not None:
            return _resolve_anchor_atom(atoms[0].anchor())
        if len(atoms) == 1 and atoms[0].macro() is not None:
            return self._resolve_variable(atoms[0].macro().NAME().getText())

        if len(atoms) == 1 and atoms[0].braceGroup() is not None and atoms[0].count() is None:
            sval = _brace_singleton(atoms[0].braceGroup())
            if sval is not None:
                return t.LiteralNode(content=sval)
            return self.visit(atoms[0].braceGroup().band())

        if all(_atom_is_literal(a) for a in atoms):
            return t.LiteralNode(content=unescape(term.getText()))

        raise CompileError("a grouping brace is not allowed inside a band or range here")


