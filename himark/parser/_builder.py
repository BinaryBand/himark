"""ANTLR visitor that walks the CST and builds the AST.

Replaces the manual `isinstance` dispatch in `_Resolver` with ANTLR's
double-dispatch. Each labeled alternative in the grammar gets a `visit*` method,
so adding a grammar rule means adding a visitor method — no `elif isinstance(...)`
branch to forget.

The output is the same AST (`himark.models.nodes_typed`) that `_Resolver` produces.
The free helpers (escapes, whitespace, variables) live in `_helpers.py`.
"""

from __future__ import annotations

from antlr4.tree.Tree import TerminalNode

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError
from himark.models.opcodes import LIT, Instruction, Program
from himark.parser._compiler import _emit_semantic, _reps_tuple
from himark.parser._helpers import ESCAPES, _resolve_leaf_escapes, unescape
from himark.parser._generated.GRAMMARParser import GRAMMARParser
from himark.parser._generated.GRAMMARVisitor import GRAMMARVisitor


# ── Pure helpers (no environment, same as original __init__.py) ──────────────


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


# ── CST views (unchanged from original) ──────────────────────────────────────


class _AnchorView:
    __slots__ = ("is_start", "is_document")
    def __init__(self, is_start: bool, is_document: bool):
        self.is_start = is_start
        self.is_document = is_document


class _ReferenceView:
    __slots__ = ("is_count", "stage", "index")
    def __init__(self, is_count: bool, stage: int | None, index: int | None):
        self.is_count = is_count
        self.stage = stage
        self.index = index


class _RangeView:
    __slots__ = ("lower", "upper")
    def __init__(self, lower: str, upper: str):
        self.lower = lower
        self.upper = upper


class _BandArmView:
    __slots__ = ("alpha", "lower", "upper", "lower_ref", "upper_ref")
    def __init__(self, alpha, lower, upper, lower_ref, upper_ref):
        self.alpha = alpha
        self.lower = lower
        self.upper = upper
        self.lower_ref = lower_ref
        self.upper_ref = upper_ref


# ── Singleton helpers on CST nodes ───────────────────────────────────────────


def _term_singleton(term: GRAMMARParser.TermContext) -> str | None:
    atoms = term.atom()
    if all(_atom_is_literal(a) for a in atoms):
        return unescape(term.getText())
    if len(atoms) == 1 and atoms[0].braceGroup() is not None and atoms[0].count() is None:
        return _brace_singleton(atoms[0].braceGroup())
    return None


def _brace_singleton(bg: GRAMMARParser.BraceGroupContext) -> str | None:
    band = bg.band()
    if isinstance(band, (GRAMMARParser.ValueBandContext, GRAMMARParser.AmbientBandContext)):
        return None
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
    if isinstance(operand_band, (GRAMMARParser.ValueBandContext, GRAMMARParser.AmbientBandContext)):
        raise NotImplementedError("complex exclusion operand not in band slice")
    return [a.getText().strip() for a in operand_band.universe().arm()]


def _is_whole_nested_brace(universe: GRAMMARParser.UniverseContext) -> bool:
    arms = universe.arm()
    if len(arms) != 1 or not isinstance(arms[0], GRAMMARParser.SingleContext):
        return False
    term = arms[0].term()
    atoms = term.atom()
    return len(atoms) == 1 and atoms[0].braceGroup() is not None and atoms[0].count() is None


def _term_is_sequence(term: GRAMMARParser.TermContext) -> bool:
    atoms = term.atom()
    constructs = [
        a for a in atoms
        if a.braceGroup() is not None or a.complement() is not None or a.macro() is not None
    ]
    if not constructs:
        return False
    return len(atoms) > 1


def _cst_is_sequence_brace(universe: GRAMMARParser.UniverseContext) -> bool:
    if _is_whole_nested_brace(universe):
        return True
    for arm in universe.arm():
        if isinstance(arm, GRAMMARParser.SingleContext):
            if _term_is_sequence(arm.term()):
                return True
        elif isinstance(arm, GRAMMARParser.ClosedRangeContext):
            if _term_is_sequence(arm.term(0)) or _term_is_sequence(arm.term(1)):
                return True
        elif isinstance(arm, GRAMMARParser.OpenUpperContext):
            if _term_is_sequence(arm.term()):
                return True
        elif isinstance(arm, GRAMMARParser.OpenLowerContext):
            if _term_is_sequence(arm.term()):
                return True
    return False


# ── Reference / Anchor resolution (unchanged from original) ──────────────────


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
        _ReferenceView(is_count=ref.HASH() is not None, stage=stage, index=index)
    )


def _resolve_anchor_atom(anchor: GRAMMARParser.AnchorContext) -> t.AnchorNode:
    lts = anchor.LT()
    return t.AnchorNode.from_view(
        _AnchorView(is_start=bool(lts), is_document=len(lts or anchor.GT()) == 2)
    )


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


# ═══════════════════════════════════════════════════════════════════════════════
# VISITOR — one method per labeled grammar alternative
# ═══════════════════════════════════════════════════════════════════════════════


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

    # ── Environment ──────────────────────────────────────────────────────────

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

    # ── Entry: pattern → Program (CST → opcodes, no structural AST) ───────────

    def compile_pattern(self, pattern: GRAMMARParser.PatternContext) -> Program:
        """Compile a pattern CST **straight to an opcode `Program`** -- the
        single compile path. It walks the factors and emits opcodes
        from the visitor.
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
                    raise NotImplementedError("counted bare literal run not in slice")
                content = _resolve_leaf_escapes(factor.literalRun().getText())
                if content:
                    elements.append((LIT, content))
        return Program(elements=tuple(elements))

    # ── Band alternatives → SemanticNode ─────────────────────────────────────
    # (These replace the isinstance chains in _Resolver.resolve_brace_body)

    def visitValueBand(self, ctx: GRAMMARParser.ValueBandContext) -> t.SemanticNode:
        """Resolve a `{payload::spec}` band — explicit payload alphabet."""
        alpha = self._resolve_universe(ctx.universe(0))
        spec = ctx.universe(1)
        options = [self._resolve_band_arm(alpha, arm) for arm in spec.arm()]
        return options[0] if len(options) == 1 else t.UnionNode(options=options)

    def visitAmbientBand(self, ctx: GRAMMARParser.AmbientBandContext) -> t.SemanticNode:
        """Resolve a `{::spec}` band — implicit @uni payload alphabet."""
        alpha = _ambient_alpha()
        spec = ctx.universe()
        options = [self._resolve_band_arm(alpha, arm) for arm in spec.arm()]
        return options[0] if len(options) == 1 else t.UnionNode(options=options)

    def visitBareAlphabet(self, ctx: GRAMMARParser.BareAlphabetContext) -> t.SemanticNode:
        universe = ctx.universe()
        if _is_whole_nested_brace(universe):
            inner = universe.arm()[0].term().atom()[0].braceGroup()
            return t.SequenceNode(children=[self.visit(inner.band())], _literal_mask=(False,))
        if _cst_is_sequence_brace(universe):
            children, mask, child_counts = self._universe_to_sequence_children(universe)
            return t.SequenceNode(children=children, _literal_mask=tuple(mask), _child_counts=tuple(child_counts))
        return self._resolve_universe(universe)

    # ── Band arm resolution (isinstance here is type-matching for parameter
    #     shapes, not dispatch routing — universe arms and band arms share the
    #     same ArmContext types but need different construction) ────────────────

    def _resolve_band_arm(self, alpha: t.SemanticNode, arm: GRAMMARParser.ArmContext) -> t.ValueRangeNode:
        if isinstance(arm, GRAMMARParser.SingleContext):
            value, ref = self._band_endpoint(arm.term())
            return t.ValueRangeNode.from_band_view(
                _BandArmView(alpha, value, value, ref, ref)
            )
        lower = upper = None
        lower_ref = upper_ref = None
        if isinstance(arm, GRAMMARParser.ClosedRangeContext):
            lower, lower_ref = self._band_endpoint(arm.term(0))
            upper, upper_ref = self._band_endpoint(arm.term(1))
        elif isinstance(arm, GRAMMARParser.OpenUpperContext):
            lower, lower_ref = self._band_endpoint(arm.term())
        elif isinstance(arm, GRAMMARParser.OpenLowerContext):
            upper, upper_ref = self._band_endpoint(arm.term())
        return t.ValueRangeNode.from_band_view(
            _BandArmView(alpha, lower, upper, lower_ref, upper_ref)
        )

    def _band_endpoint(self, term: GRAMMARParser.TermContext) -> tuple[str | None, t.SemanticNode | None]:
        atoms = term.atom()
        if len(atoms) == 1 and atoms[0].reference() is not None:
            return None, _resolve_reference_atom(atoms[0].reference())
        sval = _term_singleton(term)
        if sval is None:
            raise NotImplementedError("non-literal band endpoint not in slice")
        return sval, None

    # ── Arm alternatives → SemanticNode ──────────────────────────────────────
    # (These replace isinstance in _Resolver.resolve_arm)

    def visitSingle(self, ctx: GRAMMARParser.SingleContext) -> t.SemanticNode:
        return self._resolve_term(ctx.term())

    def visitClosedRange(self, ctx: GRAMMARParser.ClosedRangeContext) -> t.SemanticNode:
        terms = ctx.term()
        av = _term_singleton(terms[0])
        bv = _term_singleton(terms[1])
        if av is None or bv is None:
            raise CompileError("non-literal `..` endpoint not in band slice")
        return t.ValueRangeNode.from_range_view(_RangeView(lower=av, upper=bv))

    def visitOpenUpper(self, ctx: GRAMMARParser.OpenUpperContext) -> t.SemanticNode:
        raise NotImplementedError("open-ended `..` range not in band slice")

    def visitOpenLower(self, ctx: GRAMMARParser.OpenLowerContext) -> t.SemanticNode:
        raise NotImplementedError("open-ended `..` range not in band slice")

    # ── Universe → SemanticNode ──────────────────────────────────────────────

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

    # ── Term → SemanticNode ──────────────────────────────────────────────────

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

        raise NotImplementedError("grouping/sequence brace not in band slice")

    # -- Sequence flattening ----------------------------------------------------

    def _universe_to_sequence_children(
        self, universe: GRAMMARParser.UniverseContext
    ) -> tuple[list[t.SemanticNode], list[bool], list[tuple]]:
        """Walk the CST of a grouping brace interior.

        Returns (children, literal_mask, counts) where:
        - children: resolved SemanticNode per element
        - literal_mask[i]: True = plain CST text (emit LIT), False = brace group
        - counts[i]: serialised reps tuple for this element (None = default (1,1))
        """
        children: list[t.SemanticNode] = []
        literal_mask: list[bool] = []
        counts: list[tuple] = []
        leaf_buf: list[str] = []

        def flush_leaf():
            if leaf_buf:
                children.append(t.LiteralNode(content="".join(leaf_buf)))
                literal_mask.append(True)
                counts.append(None)
                leaf_buf.clear()

        def walk(ctx):
            if isinstance(ctx, TerminalNode):
                leaf_buf.append(ctx.getText())
            elif isinstance(ctx, GRAMMARParser.AtomContext):
                if ctx.braceGroup() is not None or ctx.complement() is not None:
                    flush_leaf()
                    count_ctx = ctx.count()
                    count = _resolve_count(count_ctx) if count_ctx else None
                    from himark.parser._compiler import _reps_tuple
                    child_reps = _reps_tuple(count) if count else (1, 1)
                    if ctx.braceGroup() is not None:
                        children.append(self.visit(ctx.braceGroup().band()))
                    else:
                        bband = ctx.complement().braceGroup().band()
                        children.append(
                            t.ComplementNode(inner=self.visit(bband))
                        )
                    literal_mask.append(False)
                    counts.append(child_reps)
                else:
                    if ctx.ESC() is not None:
                        raw = ctx.getText()
                        esc = raw[1]
                        if esc in ESCAPES:
                            leaf_buf.append(ESCAPES[esc])
                        else:
                            leaf_buf.append(raw)
                    elif ctx.macro() is not None:
                        flush_leaf()
                        children.append(
                            self._resolve_variable(ctx.macro().NAME().getText())
                        )
                        literal_mask.append(False)
                        counts.append((1, 1))
                    elif ctx.reference() is not None:
                        flush_leaf()
                        children.append(
                            _resolve_reference_atom(ctx.reference())
                        )
                        literal_mask.append(False)
                        counts.append((1, 1))
                    elif ctx.anchor() is not None:
                        flush_leaf()
                        children.append(_resolve_anchor_atom(ctx.anchor()))
                        literal_mask.append(False)
                        counts.append((1, 1))
                    else:
                        leaf_buf.append(ctx.getText())
            else:
                for i in range(ctx.getChildCount()):
                    walk(ctx.getChild(i))

        walk(universe)
        flush_leaf()
        return children, literal_mask, counts

