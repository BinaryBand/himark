"""ANTLR-backed front-end for the parser (see docs/GRAMMAR.g4).

The candidate the differential harness (tests/test_parser_parity.py) diffs against the
reference `himark.parser`: both emit the same typed `nodes_typed` AST over the corpus,
so they are interchangeable for everything downstream (engine, renderer, transpiler).
Unlike the reference, it resolves `@name` as a **scoped variable**, not a text macro.

Pipeline:
  • Pre-pass: `phase0.split_statement` (top-level `=>` split) + `rewrites.apply`
    (structural sugar) + script-local variable text expansion (see below).
  • ANTLR replaces phase2: the generated lexer+parser (`_generated/GRAMMAR*`) turns a
    pattern string into a validated parse tree, `@name` left intact as a `macro` atom.
  • A tree-walking `_Resolver` replaces phase3: it walks `band → universe → arm → term
    → atom`, resolving `@name` against a variable environment (prelude `VARIABLES`) —
    parsing the definition's body once and splicing the node.

The CST→AST *decisions* live on the model, not here: each leaf/value node builds itself
from a parser-agnostic view (`himark.models.cst_view`) — `AnchorNode.from_view`,
`reference_from_view`, `ValueRangeNode.from_range_view`. This module only reads the parse
tree and hands across a tech-neutral view, so the same `from_view` code serves any
front-end. Composite nodes (union, complement, sequence, brace) are plain composition of
already-resolved children.

Why variables, not text macros: textual `@name` substitution is context-blind — it
expands inside `"…"` templates, depends on a fixed-point cap, and renumbers captures by
splice position. Structural resolution is referentially transparent: `@name` denotes a
fixed node wherever it appears, and a template is an opaque string the `macro` rule never
sees. The reference keeps text macros (it is the parity oracle); the harness proves they
agree.

A few non-corpus edge forms still raise `NotImplementedError` (e.g. the `N#` stage
count-ref, which has no reference node; open-ended bare `..` ranges).

Entry point: `parse(text, variables=None) -> list[RootNode]`, matching
`himark.parser.parse` so the candidate plugs into the harness unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError
from himark.parser import phase0, rewrites
from himark.parser._count import parse_count
from himark.parser._text import ESCAPES, split_top, unescape
from himark.prelude import VARIABLES

# The generated lexer/parser (`_generated/GRAMMAR*`) are a git-ignored build product
# of docs/GRAMMAR.g4 — see regenerate.py. They are imported lazily (inside
# `_parse_pattern_tree`) so this package still imports when they are absent (e.g. on
# a fresh checkout before regeneration); only an actual `parse` call needs them. The
# `GRAMMARParser.*Context` names in annotations below are strings (future
# annotations), so they never force the import.
try:  # pragma: no cover - typing-only convenience when generated code is present
    from himark.parser._generated.GRAMMARParser import GRAMMARParser
except ModuleNotFoundError:  # pragma: no cover - parser not generated yet
    GRAMMARParser = None  # ty:ignore[invalid-assignment]


# ── Script-local variable text expansion ─────────────────────────────────────


def _text_expand_variables(text: str, variables: dict[str, str]) -> str:
    """Inline script-local @name references by fixed-point substitution.

    Top-level @name uses are tokenised as literalRun (AT NAME) by ANTLR, so the
    structural resolver never sees them.  Before ANTLR tokenises a non-template
    step, substitute each @name that appears in `variables` with its body text.
    Prelude variables are left alone — they only appear inside braces and are
    handled structurally by the resolver.
    """
    names = sorted(variables, key=len, reverse=True)
    pat = re.compile(r"@(" + "|".join(re.escape(n) for n in names) + r")(?!\w)")
    out = text
    for _ in range(100):
        new = pat.sub(lambda m: variables[m.group(1)], out)
        if new == out:
            break
        out = new
    return out


# ── ANTLR plumbing ────────────────────────────────────────────────────────────


class _RaiseOnError(ErrorListener):
    """Turn ANTLR's default recover-and-print into a hard `CompileError`, so a
    malformed pattern fails the same way the reference parser does."""

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        raise CompileError(f"ANTLR syntax error at {line}:{column}: {msg}")


def _parse_pattern_tree(src: str) -> "GRAMMARParser.PatternOnlyContext":
    from himark.parser._generated.GRAMMARLexer import GRAMMARLexer
    from himark.parser._generated.GRAMMARParser import GRAMMARParser

    lexer = GRAMMARLexer(InputStream(src))
    lexer.removeErrorListeners()
    lexer.addErrorListener(_RaiseOnError())
    parser = GRAMMARParser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(_RaiseOnError())
    return parser.patternOnly()


# ── Pure helpers (no environment) ─────────────────────────────────────────────
# Leaf-lexical mirrors of phase3's pure logic, operating on resolved nodes / tree
# shape — the "same decision" logic the migration keeps, ported so the slice matches.


def _ambient_alpha() -> t.SemanticNode:
    """The ambient Unicode universe `@uni`, owned by the model (single source of
    truth, shared with any front-end and the engine)."""
    return t.CharRangeNode.uni()


# A written `{a..z,!…}` range now resolves to a `ValueRangeNode` (over @uni), so
# `CharRangeNode` — the bare @uni alpha primitive — never reaches exclusion attach.
# Mirrors phase3._EXCLUDABLE.
_EXCLUDABLE = (t.ValueRangeNode, t.UnionNode)


def _attach_exclusions(node: t.SemanticNode, exclusions: list[str]) -> t.SemanticNode:
    if exclusions and isinstance(node, _EXCLUDABLE):
        node.exclusions = exclusions
    return node


def _arm_group(node: t.SemanticNode) -> list[list[str]] | None:
    """The congruence groups one comma-arm contributes, or None when it cannot be
    materialised (a range/value/complement). Ported from phase3._arm_group."""
    if isinstance(node, t.LiteralNode):
        return [[node.content]]
    if isinstance(node, t.GroupClassNode):
        if all(len(g) == 1 for g in node.groups):
            return [[m for g in node.groups for m in g]]  # flat primitives → fold
        return [list(g) for g in node.groups]  # ordered alphabet of objects → keep
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


# ── CST views: parser-specific adapters to the models' `…View` Protocols ──────
# These thin ANTLR-shaped carriers satisfy himark.models.cst_view; the CST→AST
# *mapping* lives on the model (`AnchorNode.from_view`, `reference_from_view`), so
# this module only reads the parse tree and hands across a tech-neutral view. A
# different front-end implements the same Protocols and reuses that mapping verbatim.


@dataclass(frozen=True, slots=True)
class _AnchorView:
    is_start: bool
    is_document: bool


@dataclass(frozen=True, slots=True)
class _ReferenceView:
    is_count: bool
    stage: int | None
    index: int | None


@dataclass(frozen=True, slots=True)
class _RangeView:
    lower: str
    upper: str


@dataclass(frozen=True, slots=True)
class _BandArmView:
    alpha: t.SemanticNode
    lower: str | None
    upper: str | None
    lower_ref: t.SemanticNode | None
    upper_ref: t.SemanticNode | None


def _resolve_reference_atom(
    ref: GRAMMARParser.ReferenceContext,
) -> t.SemanticNode:
    """Adapt a `reference` atom (`$i  #i  N$  N$i  N#  N#i`) to a `ReferenceView`; the
    node choice (BackRef / CountRef / StageRef, and the out-of-slice `N#`) lives on
    `reference_from_view`. The leading-INT stage form is told from the no-stage form by
    token order — sigil before vs. after the INT."""
    sigil = ref.DOLLAR() or ref.HASH()
    ints = ref.INT()
    leading_int = (
        bool(ints) and ints[0].getSymbol().tokenIndex < sigil.getSymbol().tokenIndex
    )
    if leading_int:  # `N$` / `N$i` — first INT is the stage, optional second the index
        stage: int | None = int(ints[0].getText())
        index = int(ints[1].getText()) if len(ints) == 2 else None
    else:  # `$i` / `#i` — no stage; the (grammar-required) INT is the group index
        stage = None
        index = int(ints[0].getText())
    return t.reference_from_view(
        _ReferenceView(is_count=ref.HASH() is not None, stage=stage, index=index)
    )


def _resolve_anchor_atom(anchor: GRAMMARParser.AnchorContext) -> t.AnchorNode:
    """Adapt an `anchor` atom (`AT (LT LT? | GT GT?)`) to an `AnchorView` and let the
    model build itself via `AnchorNode.from_view`. `<`/`>` is the side, one/two brackets
    the line/document scope; this half only reads the brackets off the ANTLR tree."""
    lts = anchor.LT()
    return t.AnchorNode.from_view(
        _AnchorView(is_start=bool(lts), is_document=len(lts or anchor.GT()) == 2)
    )


def _term_singleton(term: GRAMMARParser.TermContext) -> str | None:
    """The single concrete value of a `term`, or None if it is not a singleton.

    A term is `atom+`. It is a singleton when every atom is a literal token (its
    text, unescaped), or it is exactly one nested singleton brace. A `macro` atom is
    never a singleton here (a named alphabet has cardinality > 1). Mirrors the
    cardinality check phase3._singleton_value performs on substrings."""
    atoms = term.atom()
    if all(_atom_is_literal(a) for a in atoms):
        return unescape(term.getText())
    if (
        len(atoms) == 1
        and atoms[0].braceGroup() is not None
        and atoms[0].count() is None
    ):
        return _brace_singleton(atoms[0].braceGroup())
    return None


def _brace_singleton(bg: GRAMMARParser.BraceGroupContext) -> str | None:
    """The single value of a `{…}` if it has cardinality 1, else None (no count
    handling beyond a bare singleton — counted singletons are out of slice)."""
    band = bg.braceBody().band()
    if isinstance(
        band, (GRAMMARParser.ValueBandContext, GRAMMARParser.AmbientBandContext)
    ):
        return None  # a band is a value universe, not a singleton
    arms = band.universe().arm()
    if len(arms) != 1:
        return None
    arm = arms[0]
    if not isinstance(arm, GRAMMARParser.SingleContext):
        return None
    return _term_singleton(arm.term())


def _arm_as_exclusion(arm: GRAMMARParser.ArmContext) -> list[str] | None:
    """If `arm` is a subtractive `!{set}` exclusion, the excluded value strings;
    else None. Mirrors phase3's exclusion-arm handling."""
    if not isinstance(arm, GRAMMARParser.SingleContext):
        return None
    term = arm.term()
    atoms = term.atom()
    if len(atoms) != 1 or atoms[0].complement() is None:
        return None
    operand_body = atoms[0].complement().braceGroup().braceBody()
    if isinstance(
        operand_body.band(),
        (GRAMMARParser.ValueBandContext, GRAMMARParser.AmbientBandContext),
    ):
        raise NotImplementedError("complex exclusion operand not in braceBody slice")
    inner = operand_body.getText()
    return [m.strip() for m in split_top(",", inner)]


def _is_whole_nested_brace(universe: GRAMMARParser.UniverseContext) -> bool:
    """True if a universe is exactly one un-counted nested brace (`{{X}}`) — the
    nesting that **constructs** a single opaque congruence position (a listed fold
    for an enumerable inner, a lazy heterogeneous run for a range/value inner).
    phase3 resolves it specially; here it is the marker for the (out-of-slice) fold."""
    arms = universe.arm()
    if len(arms) != 1 or not isinstance(arms[0], GRAMMARParser.SingleContext):
        return False
    term = arms[0].term()
    atoms = term.atom()
    return (
        len(atoms) == 1
        and atoms[0].braceGroup() is not None
        and atoms[0].count() is None
    )


def _term_is_sequence(term: GRAMMARParser.TermContext) -> bool:
    atoms = term.atom()
    constructs = [
        a
        for a in atoms
        if a.braceGroup() is not None
        or a.complement() is not None
        or a.macro() is not None
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


def _resolve_leaf(literal_run: GRAMMARParser.LiteralRunContext) -> str:
    """A bare top-level literal run. Recognised escapes resolve; an unknown escape
    keeps its backslash (mirrors phase2's leaf scanner, not `unescape`). A top-level
    `@name` rides through as literal text — the grammar models `macro` only inside a
    brace, so structural resolution of un-braced references is out of slice."""
    raw = literal_run.getText()
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == "\\" and i + 1 < len(raw):
            esc = raw[i + 1]
            if esc in ESCAPES:
                out.append(ESCAPES[esc])
                i += 2
                continue
            out.append(raw[i])  # keep the backslash; the char rides along next
            i += 1
            continue
        out.append(raw[i])
        i += 1
    return "".join(out)


# ── Resolver: braceBody → semantic node, with a variable environment ──────────
# Carries the `@name` environment so a `macro` atom resolves structurally. The
# σ-decisions (congruence folding, ranges, complement, exclusions) are reimplemented
# here as a tree-walk — this is the phase3 replacement; only leaf-lexical helpers
# above are shared.


class _Resolver:
    def __init__(self, env: dict[str, str]) -> None:
        self._env = env  # @name -> definition body (prelude VARIABLES + script locals)
        self._resolving: set[str] = set()  # names being resolved now (cycle guard)
        self._parsed_env: dict[str, GRAMMARParser.BraceBodyContext] = {}

    def _get_parsed_body(self, name: str) -> GRAMMARParser.BraceBodyContext:
        if name not in self._parsed_env:
            tree = _parse_pattern_tree("{" + self._env[name] + "}")
            brace = tree.pattern().factor()[0].braceGroup()
            if brace is None:
                raise CompileError(
                    f"variable @{name} is not a universe: {self._env[name]!r}"
                )
            self._parsed_env[name] = brace.braceBody()
        return self._parsed_env[name]

    # — variable references —

    def variable(self, name: str) -> t.SemanticNode:
        """Resolve `@name` to the node its definition denotes. Unknown → literal
        `@name` (the reference's no-op expansion); a self-reference → CompileError."""
        if name not in self._env:
            return t.LiteralNode(content="@" + name)
        if name in self._resolving:
            raise CompileError(
                f"circular variable definition: @{name} references itself"
            )
        self._resolving.add(name)
        try:
            return self.resolve_brace_body(self._get_parsed_body(name))
        finally:
            self._resolving.discard(name)

    # — terms / arms —

    def resolve_term(self, term: GRAMMARParser.TermContext) -> t.SemanticNode:
        """Resolve a single (non-ranged) arm term. Mirrors the single-part path of
        phase3._resolve_arm, plus `@name` variable resolution."""
        atoms = term.atom()
        if len(atoms) == 1 and atoms[0].reference() is not None:
            return _resolve_reference_atom(atoms[0].reference())
        if len(atoms) == 1 and atoms[0].anchor() is not None:
            return _resolve_anchor_atom(atoms[0].anchor())
        if len(atoms) == 1 and atoms[0].macro() is not None:
            return self.variable(atoms[0].macro().NAME().getText())

        # A single nested brace: transparent (`{ {a..z} }` == `{a..z}`) unless it is a
        # singleton, in which case it is a literal match of that value.
        if (
            len(atoms) == 1
            and atoms[0].braceGroup() is not None
            and atoms[0].count() is None
        ):
            sval = _brace_singleton(atoms[0].braceGroup())
            if sval is not None:
                return t.LiteralNode(content=sval)
            return self.resolve_brace_body(atoms[0].braceGroup().braceBody())

        if all(_atom_is_literal(a) for a in atoms):
            return t.LiteralNode(content=unescape(term.getText()))

        # A brace glued to text, several constructs, or a glued macro — a sequence.
        raise NotImplementedError("grouping/sequence brace not in braceBody slice")

    def resolve_range_arm(
        self, arm: GRAMMARParser.ClosedRangeContext
    ) -> t.SemanticNode:
        """Adapt a `term .. term` arm to a `RangeView`; `ValueRangeNode.from_range_view`
        owns the τ..τ→band-over-@uni decision. Slice supports concrete singleton
        endpoints only (`{a..z}`, `{aa..zz}`); open-ended/alphabet endpoints are bands."""
        terms = arm.term()
        av = _term_singleton(terms[0])
        bv = _term_singleton(terms[1])
        if av is None or bv is None:
            raise CompileError("non-literal `..` endpoint not in braceBody slice")
        return t.ValueRangeNode.from_range_view(_RangeView(lower=av, upper=bv))

    def resolve_arm(self, arm: GRAMMARParser.ArmContext) -> t.SemanticNode:
        if isinstance(arm, GRAMMARParser.ClosedRangeContext):
            return self.resolve_range_arm(arm)
        if isinstance(
            arm, (GRAMMARParser.OpenUpperContext, GRAMMARParser.OpenLowerContext)
        ):
            raise NotImplementedError("open-ended `..` range not in braceBody slice")
        return self.resolve_term(arm.term())

    def classify_arms(
        self, arms: list[GRAMMARParser.ArmContext], exclusions: list[str]
    ) -> t.SemanticNode:
        """Build the node for a comma-list (an ordered alphabet of points). Ported
        from phase3._classify_arms, driven by arm contexts instead of substrings."""
        if len(arms) == 1:
            return _attach_exclusions(self.resolve_arm(arms[0]), exclusions)

        resolved = [self.resolve_arm(a) for a in arms]
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

    # — bands (`{payload::lo..hi}`) —

    def resolve_band(self, band: GRAMMARParser.BandContext) -> t.SemanticNode:
        """Resolve a `payload :: spec` band into a value range over the payload
        alphabet. Mirrors phase3._resolve_band: the payload is any universe (ambient
        `@uni` when empty, the `{::lo..hi}` form), the band-spec is a `,`-union of
        arms; one arm is a `ValueRangeNode`, several fold into a `UnionNode`."""
        if isinstance(band, GRAMMARParser.ValueBandContext):
            alpha = self.resolve_universe(band.universe(0))
            spec = band.universe(1)
        elif isinstance(band, GRAMMARParser.AmbientBandContext):
            alpha = _ambient_alpha()
            spec = band.universe()
        else:
            raise CompileError("resolve_band called on bareAlphabet")
        options = [self.resolve_band_arm(alpha, arm) for arm in spec.arm()]
        return options[0] if len(options) == 1 else t.UnionNode(options=options)

    def resolve_band_arm(
        self, alpha: t.SemanticNode, arm: GRAMMARParser.ArmContext
    ) -> t.ValueRangeNode:
        """Fill a `_BandArmView` for one band-spec arm; `ValueRangeNode.from_band_view`
        owns the construction and the floor-or-ceiling invariant. A `lo..hi` range
        (either end omittable) or a single value (`{@d::5}` is `5..5`); reference
        endpoints (`$0`) resolve to a node, glued runs are out of slice."""
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

    def _band_endpoint(
        self, term: GRAMMARParser.TermContext
    ) -> tuple[str | None, t.SemanticNode | None]:
        """A band endpoint as `(literal, reference)` — mirrors phase3._bound_endpoint.
        A `$i`/`#i`/`N$i` endpoint is a dynamic reference node (the literal is None);
        anything else is a literal value. Anchors and glued runs are out of slice."""
        atoms = term.atom()
        if len(atoms) == 1 and atoms[0].reference() is not None:
            return None, _resolve_reference_atom(atoms[0].reference())
        sval = _term_singleton(term)
        if sval is None:
            raise NotImplementedError("non-literal band endpoint not in slice")
        return sval, None

    # — brace body / pattern —

    def resolve_universe(
        self, universe: GRAMMARParser.UniverseContext
    ) -> t.SemanticNode:
        """Resolve a bare `universe` (a `,`-list of arms) into a semantic node:
        split off subtractive `!{…}` exclusion arms, then classify the rest. Shared
        by a `braceBody`'s payload and a band's payload alphabet."""
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
        return self.classify_arms(arms, exclusions)

    def _universe_to_sequence_children(
        self, universe: GRAMMARParser.UniverseContext
    ) -> list[t.Node]:
        children: list[t.Node] = []
        leaf_buf: list[str] = []

        def flush_leaf():
            if leaf_buf:
                children.append(t.LeafNode(content="".join(leaf_buf)))
                leaf_buf.clear()

        def walk(ctx):
            from antlr4.tree.Tree import TerminalNode

            if isinstance(ctx, TerminalNode):
                leaf_buf.append(ctx.getText())
            elif isinstance(ctx, GRAMMARParser.AtomContext):
                if ctx.braceGroup() is not None or ctx.complement() is not None:
                    flush_leaf()
                    count_ctx = ctx.count()
                    count = (
                        parse_count(count_ctx.countBody().getText())
                        if count_ctx
                        else None
                    )
                    if ctx.braceGroup() is not None:
                        bbody = ctx.braceGroup().braceBody()
                        children.append(
                            t.BraceGroupNode(
                                content=bbody.getText(),
                                semantic=self.resolve_brace_body(bbody),
                                count=count,
                            )
                        )
                    else:
                        bbody = ctx.complement().braceGroup().braceBody()
                        children.append(
                            t.BraceGroupNode(
                                content="!" + bbody.getText(),
                                semantic=t.ComplementNode(
                                    inner=self.resolve_brace_body(bbody)
                                ),
                                count=count,
                            )
                        )
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
                        children.append(self.variable(ctx.macro().NAME().getText()))
                    elif ctx.reference() is not None:
                        flush_leaf()
                        children.append(_resolve_reference_atom(ctx.reference()))
                    elif ctx.anchor() is not None:
                        flush_leaf()
                        children.append(_resolve_anchor_atom(ctx.anchor()))
                    else:
                        leaf_buf.append(ctx.getText())
            else:
                for i in range(ctx.getChildCount()):
                    walk(ctx.getChild(i))

        walk(universe)
        flush_leaf()
        return children

    def resolve_brace_body(
        self, body: GRAMMARParser.BraceBodyContext
    ) -> t.SemanticNode:
        """Resolve a `braceBody` (`band`) into a semantic node — the slice's core
        tree-walk, the phase3 replacement for one rule. Subtraction is never here:
        it is the leading-sigil `!{…}` `complement` atom/factor, resolved separately."""
        band = body.band()
        if isinstance(
            band, (GRAMMARParser.ValueBandContext, GRAMMARParser.AmbientBandContext)
        ):
            return self.resolve_band(band)
        universe = band.universe()
        # Whole-content single nested brace `{{X}}`: the nesting *constructs* one
        # capture-group scope (`SequenceNode`) around the inner alphabet — a listed
        # fold for an enumerable inner (`{{a,A}}`), a lazy het run for a range/value
        # inner (`{{a..z}}`) — where re-entry per rep frees its members afresh.
        # Distinct from a bare `{a,A}` (two primitives).
        if _is_whole_nested_brace(universe):
            inner = universe.arm()[0].term().atom()[0].braceGroup()
            return t.SequenceNode(children=[self.resolve_brace_body(inner.braceBody())])
        if _cst_is_sequence_brace(universe):
            # Concatenation grouping (`{of {black} {quartz}}`, several glued
            # constructs): one capture-group scope over a sub-pattern.
            return t.SequenceNode(children=self._universe_to_sequence_children(universe))
        return self.resolve_universe(universe)

    def resolve_pattern(self, ctx: GRAMMARParser.PatternOnlyContext) -> t.RootNode:
        pattern = ctx.pattern()
        children: list[t.Node] = []
        for factor in pattern.factor():
            count_ctx = factor.count()
            count = parse_count(count_ctx.countBody().getText()) if count_ctx else None

            if factor.braceGroup() is not None:
                body = factor.braceGroup().braceBody()
                children.append(
                    t.BraceGroupNode(
                        content=body.getText(),
                        semantic=self.resolve_brace_body(body),
                        count=count,
                    )
                )
            elif factor.complement() is not None:
                # A top-level subtractive `!{…}`: phase2 folds the `!` into content
                # and phase3 resolves it as a complement.
                body = factor.complement().braceGroup().braceBody()
                children.append(
                    t.BraceGroupNode(
                        content="!" + body.getText(),
                        semantic=t.ComplementNode(inner=self.resolve_brace_body(body)),
                        count=count,
                    )
                )
            else:  # literalRun
                if count is not None:
                    raise NotImplementedError("counted bare literal run not in slice")
                children.append(t.LeafNode(content=_resolve_leaf(factor.literalRun())))

        return t.RootNode(children=children or [t.LeafNode(content="")])


# ── Public entry point ────────────────────────────────────────────────────────


def parse(text: str, variables: dict[str, str] | None = None) -> list[t.RootNode]:
    """ANTLR-backed `parse`, signature-compatible with `himark.parser.parse`.

    Shared pre-pass (`phase0` split + `rewrites` sugar), then ANTLR + the slice
    tree-walk per step, with `@name` resolved as a scoped variable from `VARIABLES`
    overlaid with `variables`. A whole-step `"…"` template is one verbatim leaf (no
    variable expansion → no template leak); its moustaches are a separate layer.
    Out-of-slice constructs raise `NotImplementedError`.

    Script-local `variables` are text-expanded into each non-template pattern step
    before ANTLR tokenises it.  ANTLR tokenises top-level `@name` as a `literalRun`
    (not a `macro` atom), so structural resolution alone would miss these references.
    Prelude variables stay structural — they only appear inside braces."""
    resolver = _Resolver({**VARIABLES, **(variables or {})})
    roots: list[t.RootNode] = []
    for step in phase0.split_statement(text):
        pre = rewrites.apply(step)
        stripped = pre.strip()
        if len(stripped) >= 2 and stripped.startswith('"') and stripped.endswith('"'):
            roots.append(
                t.RootNode(children=[t.LeafNode(content=unescape(stripped[1:-1]))])
            )
            continue
        if variables:
            pre = _text_expand_variables(pre, variables)
        roots.append(resolver.resolve_pattern(_parse_pattern_tree(pre)))
    return roots
