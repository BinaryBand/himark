"""ANTLR-backed front-end — a *slice* of the parser migration (see docs/GRAMMAR.g4).

This is the candidate parser the differential harness (tests/test_parser_parity.py)
diffs against the reference `himark.parser`. It demonstrates the target architecture
for one rule — `braceBody` — end to end, and (unlike the reference) resolves `@name`
as a **scoped variable** rather than a text macro:

  • The pre-pass is `phase0.split_statement` (top-level `=>` split) + `rewrites.apply`
    (structural sugar). It does **not** text-expand macros — that is the brittle step
    this branch removes (see below).

  • ANTLR replaces phase2: the generated lexer+parser (`_generated/GRAMMAR*`) turns a
    pattern string into a validated parse tree, with `@name` left intact as a `macro`
    atom (`AT NAME`) inside braces.

  • A tree-walking `_Resolver` replaces phase3 *for the slice*: it builds the typed
    `nodes_typed` AST by walking `band → universe → arm → term → atom`, and resolves a
    `macro` atom by looking `@name` up in a **variable environment** (the prelude
    `MACROS` overlaid with script-local defs), parsing that definition's body once and
    splicing the resulting *node*. Cycles are detected; an unknown `@name` falls back
    to literal `@name` text, matching the reference's no-op expansion.

Why variables, not text macros: textual `@name` substitution is context-blind — it
expands inside `"…"` templates, depends on a fixed-point cap, and renumbers captures
by splice position. Structural resolution is referentially transparent: `@name`
denotes a fixed node wherever it appears, and a template is an opaque STRING the
`macro` rule never sees, so the template leak is gone. The reference parser keeps text
macros (it is the parity oracle); the harness proves the two agree on every capture-
free alphabet, which is the whole prelude.

Scope (the `braceBody` σ-core): literal, char-range, multi-char value-range, the
congruence forms (`{a,A}`, `{cat,dog}`, `{{a,A},{b,B}}`), complement (`{!{x,y}}`),
member exclusions (`{a..z,!{m..p}}`), `::` value bands over a literal spec
(`{@d::0..255}`, `{@d::5}`, `{@d::1..5,9..12}`, the open-ended `{@d::..255}` /
`{@d::128..}`, and the ambient `{::lo..hi}`), the references `{$i}` (back-ref),
`{#i}` (count-ref) and `{N$}`/`{N$i}` (stage-ref) — including as a band endpoint
(`{@d::0..$0}`) — the anchors `{@<}`/`{@>}`/`{@<<}`/`{@>>}`, and `@name` variable
references that resolve to any of those (`{@d}`, `{@w}`, `{!@s}`). Counts on braces
are parsed. Everything else — the `N#` stage count-ref (no phase3 oracle), grouping
`SequenceNode`s, heterogeneous `{{…}}`, top-level (un-braced) `@name`, templates with
moustaches — raises `NotImplementedError`, which the harness records as "not in this
slice yet" (skipped); an *unhandled* divergence still fails loudly.

Entry point: `parse(text, macros=None) -> list[RootNode]`, matching the reference
`himark.parser.parse` signature so the candidate plugs into the harness unchanged.
"""

from __future__ import annotations

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError
from himark.parser import phase0, rewrites
from himark.parser._count import parse_count
from himark.parser._text import ESCAPES, split_top, unescape
from himark.prelude import MACROS

# The generated lexer/parser (`_generated/GRAMMAR*`) are a git-ignored build product
# of docs/GRAMMAR.g4 — see regenerate.py. They are imported lazily (inside
# `_parse_pattern_tree`) so this package still imports when they are absent (e.g. on
# a fresh checkout before regeneration); only an actual `parse` call needs them. The
# `GRAMMARParser.*Context` names in annotations below are strings (future
# annotations), so they never force the import.
try:  # pragma: no cover - typing-only convenience when generated code is present
    from himark.parser_antlr._generated.GRAMMARParser import GRAMMARParser
except ModuleNotFoundError:  # pragma: no cover - parser not generated yet
    GRAMMARParser = None  # ty:ignore[invalid-assignment]


# ── ANTLR plumbing ────────────────────────────────────────────────────────────


class _RaiseOnError(ErrorListener):
    """Turn ANTLR's default recover-and-print into a hard `CompileError`, so a
    malformed pattern fails the same way the reference parser does."""

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        raise CompileError(f"ANTLR syntax error at {line}:{column}: {msg}")


def _parse_pattern_tree(src: str) -> "GRAMMARParser.PatternOnlyContext":
    from himark.parser_antlr._generated.GRAMMARLexer import GRAMMARLexer
    from himark.parser_antlr._generated.GRAMMARParser import GRAMMARParser

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
    """The ambient Unicode universe `@uni` — the alphabet for an unnamed multi-char
    `..` range (`{aa..zz}` == `{@uni::aa..zz}`)."""
    return t.CharRangeNode(start="\x00", end="\U0010ffff")


_EXCLUDABLE = (t.CharRangeNode, t.ValueRangeNode, t.UnionNode)


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


def _guard_in_slice_atom(atom: GRAMMARParser.AtomContext) -> None:
    """Raise for atoms outside the braceBody σ-slice (anchors, and a `reference`
    glued into a multi-atom term — a sequence). A standalone `reference` atom is
    resolved by `_resolve_reference_atom`, and a `macro` atom by `_Resolver`, before
    this guard runs, so neither is rejected here."""
    if atom.reference() is not None:
        raise NotImplementedError(
            "glued reference ($/#/N$) is a sequence, not in slice"
        )
    if atom.anchor() is not None:
        raise NotImplementedError("anchor (@</@>) not in braceBody slice")


def _resolve_reference_atom(
    ref: GRAMMARParser.ReferenceContext,
) -> t.SemanticNode:
    """Resolve a `reference` atom to its typed node, mirroring phase3._resolve_reference.

    The grammar's `reference` covers `$i  #i  N$  N$i  N#  N#i`, but the parity oracle
    (phase3) only recognises four: `{$i}` → BackRef, `{#i}` → CountRef, `{N$}`/`{N$i}`
    → StageRef (flat path). `N#`/`N#i` have no phase3 regex (it would treat them as a
    literal), so they stay out of slice rather than diverge. The leading-INT alternative
    is distinguished from the no-stage one by token order (sigil before vs. after INT)."""
    sigil = ref.DOLLAR() or ref.HASH()
    is_dollar = ref.DOLLAR() is not None
    ints = ref.INT()
    leading_int = (
        bool(ints) and ints[0].getSymbol().tokenIndex < sigil.getSymbol().tokenIndex
    )
    if not leading_int:  # `$i` / `#i` — the no-stage form (index required by grammar)
        group = int(ints[0].getText())
        return t.BackRefNode(group=group) if is_dollar else t.CountRefNode(group=group)
    if not is_dollar:  # `N#` / `N#i` — no phase3 oracle, keep out of slice
        raise NotImplementedError("stage count-ref `N#` not in references slice")
    stage = int(ints[0].getText())
    path = (int(ints[1].getText()),) if len(ints) == 2 else ()  # `{N$}` whole match
    return t.StageRefNode(stage=stage, path=path)


def _resolve_anchor_atom(anchor: GRAMMARParser.AnchorContext) -> t.AnchorNode:
    """Resolve an `anchor` atom (`AT (LT LT? | GT GT?)`) to its zero-width position,
    mirroring phase3's `@<`/`@>`/`@<<`/`@>>` map. One bracket is a line anchor, two a
    document anchor; `<` is a start, `>` an end."""
    lts = anchor.LT()
    if lts:
        return t.AnchorNode(at="doc_start" if len(lts) == 2 else "line_start")
    return t.AnchorNode(at="doc_end" if len(anchor.GT()) == 2 else "line_end")


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
    body = bg.braceBody()
    if body.BANG() is not None:
        return None  # complement is a class, never a singleton
    band = body.band()
    if band.BAND() is not None:
        return None  # a band is a value universe, not a singleton
    arms = band.universe()[0].arm()
    if len(arms) != 1:
        return None
    arm = arms[0]
    if arm.RANGE() is not None:
        return None
    terms = arm.term()
    if len(terms) != 1:
        return None
    return _term_singleton(terms[0])


def _arm_as_exclusion(arm: GRAMMARParser.ArmContext) -> list[str] | None:
    """If `arm` is a subtractive `!{set}` exclusion, the excluded value strings;
    else None. Mirrors phase3's exclusion-arm handling."""
    if arm.RANGE() is not None:
        return None
    terms = arm.term()
    if len(terms) != 1:
        return None
    atoms = terms[0].atom()
    if len(atoms) != 1 or atoms[0].complement() is None:
        return None
    operand_body = atoms[0].complement().braceGroup().braceBody()
    if operand_body.BANG() is not None or operand_body.band().BAND() is not None:
        raise NotImplementedError("complex exclusion operand not in braceBody slice")
    inner = operand_body.getText()
    return [m.strip() for m in split_top(",", inner)]


def _is_whole_nested_brace(universe: GRAMMARParser.UniverseContext) -> bool:
    """True if a universe is exactly one un-counted nested brace (`{{X}}`) — the
    nesting that **constructs** a single opaque congruence position (a listed fold
    for an enumerable inner, a lazy heterogeneous run for a range/value inner).
    phase3 resolves it specially; here it is the marker for the (out-of-slice) fold."""
    arms = universe.arm()
    if len(arms) != 1 or arms[0].RANGE() is not None:
        return False
    terms = arms[0].term()
    if len(terms) != 1:
        return False
    atoms = terms[0].atom()
    return (
        len(atoms) == 1
        and atoms[0].braceGroup() is not None
        and atoms[0].count() is None
    )


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
        self._env = env  # @name -> definition body (prelude MACROS + script locals)
        self._resolving: set[str] = set()  # names being resolved now (cycle guard)

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
            # The body is a σ-universe; wrap it so it parses as one brace group, then
            # resolve that group's interior (the same node `{@name}` should yield).
            tree = _parse_pattern_tree("{" + self._env[name] + "}")
            brace = tree.pattern().factor()[0].braceGroup()
            if brace is None:
                raise CompileError(
                    f"variable @{name} is not a universe: {self._env[name]!r}"
                )
            return self.resolve_brace_body(brace.braceBody())
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
        for a in atoms:
            _guard_in_slice_atom(a)

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

    def resolve_range_arm(self, arm: GRAMMARParser.ArmContext) -> t.SemanticNode:
        """Resolve a `term .. term` arm. Slice supports concrete singleton endpoints
        only (`{a..z}`, `{aa..zz}`); open-ended/alphabet endpoints are out of slice."""
        terms = arm.term()
        if len(terms) != 2:
            raise NotImplementedError("open-ended `..` range not in braceBody slice")
        av = _term_singleton(terms[0])
        bv = _term_singleton(terms[1])
        if av is None or bv is None:
            raise NotImplementedError(
                "non-literal `..` endpoint not in braceBody slice"
            )
        if len(av) == 1 and len(bv) == 1:
            return t.CharRangeNode(start=av, end=bv)
        return t.ValueRangeNode(alpha=_ambient_alpha(), lower=av, upper=bv)

    def resolve_arm(self, arm: GRAMMARParser.ArmContext) -> t.SemanticNode:
        if arm.RANGE() is not None:
            return self.resolve_range_arm(arm)
        terms = arm.term()
        if len(terms) != 1:  # a leading `RANGE term` (`..τ`) — open range, out of slice
            raise NotImplementedError("open-ended `..` range not in braceBody slice")
        return self.resolve_term(terms[0])

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
        universes = band.universe()
        if len(universes) == 2:  # `payload :: spec`
            alpha = self.resolve_universe(universes[0])
            spec = universes[1]
        else:  # `:: spec` — empty payload, ambient Unicode alphabet
            alpha = _ambient_alpha()
            spec = universes[0]
        options = [self.resolve_band_arm(alpha, arm) for arm in spec.arm()]
        return options[0] if len(options) == 1 else t.UnionNode(options=options)

    def resolve_band_arm(
        self, alpha: t.SemanticNode, arm: GRAMMARParser.ArmContext
    ) -> t.ValueRangeNode:
        """One band-spec arm: a `lo..hi` range (either end omittable) or a single
        value (`{@d::5}` is `5..5`). Mirrors phase3._resolve_band_arm; reference
        endpoints (`$0`) are out of slice."""
        terms = arm.term()
        if arm.RANGE() is None:  # single value: lower == upper (one endpoint, reused)
            value, ref = self._band_endpoint(terms[0])
            return t.ValueRangeNode(
                alpha=alpha, lower=value, upper=value, lower_ref=ref, upper_ref=ref
            )
        lower = upper = None
        lower_ref = upper_ref = None
        if len(terms) == 2:  # `lo..hi`
            lower, lower_ref = self._band_endpoint(terms[0])
            upper, upper_ref = self._band_endpoint(terms[1])
        elif len(terms) == 1:  # `..hi` (RANGE before term) or `lo..` (RANGE after)
            if arm.RANGE().getSymbol().tokenIndex < terms[0].start.tokenIndex:
                upper, upper_ref = self._band_endpoint(terms[0])
            else:
                lower, lower_ref = self._band_endpoint(terms[0])
        if lower is None and upper is None and lower_ref is None and upper_ref is None:
            raise CompileError("A band needs a floor or a ceiling: got '{U:..}'")
        return t.ValueRangeNode(
            alpha=alpha,
            lower=lower,
            upper=upper,
            lower_ref=lower_ref,
            upper_ref=upper_ref,
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
        for a in atoms:
            _guard_in_slice_atom(a)
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

    def resolve_brace_body(
        self, body: GRAMMARParser.BraceBodyContext
    ) -> t.SemanticNode:
        """Resolve a `braceBody` (`BANG? band`) into a semantic node — the slice's
        core tree-walk, the phase3 replacement for one rule."""
        band = body.band()
        if band.BAND() is not None:
            node = self.resolve_band(band)
        else:
            universe = band.universe()[0]
            # Whole-content single nested brace `{{X}}` (no outer `!`): the nesting
            # *constructs* one opaque congruence position — a listed fold for an
            # enumerable inner (`{{a,A}}`), a lazy het run for a range/value inner
            # (`{{a..z}}`). Distinct from a bare `{a,A}` (two primitives), so it is not
            # a plain arm. Out of the braceBody σ-slice. (A complement `{!{…}}` keeps
            # its BANG, so the `body.BANG()` guard lets it through to the complement.)
            if body.BANG() is None and _is_whole_nested_brace(universe):
                raise NotImplementedError(
                    "object/heterogeneous `{{…}}` not in braceBody slice"
                )
            node = self.resolve_universe(universe)

        if body.BANG() is not None:
            node = t.ComplementNode(inner=node)
        return node

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


def parse(text: str, macros: dict[str, str] | None = None) -> list[t.RootNode]:
    """ANTLR-backed `parse`, signature-compatible with `himark.parser.parse`.

    Shared pre-pass (`phase0` split + `rewrites` sugar — **no** macro text
    expansion), then ANTLR + the slice tree-walk per step, with `@name` resolved as a
    scoped variable from `MACROS` overlaid with `macros`. A whole-step `"…"` template
    is one verbatim leaf (no macro expansion → no template leak); its moustaches are a
    separate layer. Out-of-slice constructs raise `NotImplementedError`."""
    resolver = _Resolver({**MACROS, **(macros or {})})
    roots: list[t.RootNode] = []
    for step in phase0.split_statement(text):
        pre = rewrites.apply(step)
        stripped = pre.strip()
        if len(stripped) >= 2 and stripped.startswith('"') and stripped.endswith('"'):
            roots.append(
                t.RootNode(children=[t.LeafNode(content=unescape(stripped[1:-1]))])
            )
            continue
        roots.append(resolver.resolve_pattern(_parse_pattern_tree(pre)))
    return roots
