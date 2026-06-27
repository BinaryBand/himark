"""ANTLR-backed front-end — a *slice* of the parser migration (see docs/GRAMMAR.g4).

This is the candidate parser the differential harness (tests/test_parser_parity.py)
diffs against the reference `himark.parser`. It demonstrates the target architecture
for one rule — `braceBody` — end to end:

  • The pre-pass stays **shared and unchanged**: `phase0.split_statement` (top-level
    `=>` split) and `phase1.preprocess` (macro expansion + rewrites) run exactly as
    in the reference. They are documented as outside the grammar, so both parsers use
    the same code here — parity below the seam is automatic.

  • ANTLR replaces phase2: the generated lexer+parser (`_generated/GRAMMAR*`) turns a
    preprocessed pattern string into a validated parse tree.

  • A tree-walk replaces phase3 *for the slice*: `_resolve_brace_body` and friends
    build the typed `nodes_typed` AST by walking `band → universe → arm → term → atom`,
    making the same σ-grammar decisions phase3 makes on substrings — but driven by the
    tree. Only leaf-lexical helpers (`_text.unescape`, `_count.parse_count`) are reused;
    the congruence/range/complement *decisions* are reimplemented here.

Scope (the `braceBody` σ-core): literal, char-range, multi-char value-range, the
congruence forms (`{a,A}`, `{cat,dog}`, `{{a,A},{b,B}}`), complement (`{!{x,y}}`),
and member exclusions (`{a..z,!{m..p}}`). Counts on braces are parsed (reusing
`_count`). Everything else — `::` bands, `$`/`#`/`N$` references, anchors, grouping
`SequenceNode`s, heterogeneous `{{…}}`, top-level templates with moustaches — raises
`NotImplementedError`. The harness treats that as "not in this slice yet" (skips),
so an *unhandled* divergence still fails loudly; only a declared gap is skipped.

Entry point: `parse(text, macros=None) -> list[RootNode]`, matching the reference
`himark.parser.parse` signature so the candidate plugs into the harness unchanged.
"""

from __future__ import annotations

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError
from himark.parser import phase0, phase1
from himark.parser._count import parse_count
from himark.parser._text import split_top, unescape

# The generated lexer/parser (`_generated/GRAMMAR*`) are a git-ignored build product
# of docs/GRAMMAR.g4 — see regenerate.py. They are imported lazily (inside
# `_parse_pattern_tree`) so this package still imports when they are absent (e.g. on
# a fresh checkout before regeneration); only an actual `parse` call needs them. The
# `GRAMMARParser.*Context` names in annotations below are strings (future
# annotations), so they never force the import.
try:  # pragma: no cover - typing-only convenience when generated code is present
    from himark.parser_antlr._generated.GRAMMARParser import GRAMMARParser
except ModuleNotFoundError:  # pragma: no cover - parser not generated yet
    GRAMMARParser = None  # type: ignore[assignment]


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


# ── Shared leaf/decision helpers (mirrors of phase3's pure logic) ─────────────
# These operate on already-resolved nodes / strings, not on source — they are the
# "same decision" logic the migration keeps, ported verbatim so the slice matches.


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


# ── Tree-walk: braceBody → semantic node (the phase3 replacement) ─────────────


def _term_singleton(term: GRAMMARParser.TermContext) -> str | None:
    """The single concrete value of a `term`, or None if it is not a singleton.

    A term is `atom+`. It is a singleton when every atom is a literal token (its
    text, unescaped), or it is exactly one nested singleton brace. Mirrors the
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


def _atom_is_literal(atom: GRAMMARParser.AtomContext) -> bool:
    return (
        atom.litToken() is not None
        or atom.ESC() is not None
        or atom.HEX_ESC() is not None
    )


def _guard_in_slice_atom(atom: GRAMMARParser.AtomContext) -> None:
    """Raise for atoms outside the braceBody σ-slice (references / anchors / macros)."""
    if atom.reference() is not None:
        raise NotImplementedError("reference ($/#/N$) not in braceBody slice")
    if atom.anchor() is not None:
        raise NotImplementedError("anchor (@</@>) not in braceBody slice")
    if atom.macro() is not None:
        # An unexpanded @name should not survive phase1; treat as out of slice.
        raise NotImplementedError("unexpanded macro not in braceBody slice")


def _resolve_term(term: GRAMMARParser.TermContext) -> t.SemanticNode:
    """Resolve a single (non-ranged) arm term into a node. Mirrors the single-part
    path of phase3._resolve_arm."""
    atoms = term.atom()
    for a in atoms:
        _guard_in_slice_atom(a)

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
        return _resolve_brace_body(atoms[0].braceGroup().braceBody())

    if all(_atom_is_literal(a) for a in atoms):
        return t.LiteralNode(content=unescape(term.getText()))

    # A brace glued to text, or several constructs — a grouping/sequence brace.
    raise NotImplementedError("grouping/sequence brace not in braceBody slice")


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


def _resolve_range_arm(arm: GRAMMARParser.ArmContext) -> t.SemanticNode:
    """Resolve a `term .. term` arm. Slice supports concrete singleton endpoints
    only (`{a..z}`, `{aa..zz}`); open-ended or alphabet endpoints are out of slice."""
    terms = arm.term()
    if len(terms) != 2:
        raise NotImplementedError("open-ended `..` range not in braceBody slice")
    av = _term_singleton(terms[0])
    bv = _term_singleton(terms[1])
    if av is None or bv is None:
        raise NotImplementedError("non-literal `..` endpoint not in braceBody slice")
    if len(av) == 1 and len(bv) == 1:
        return t.CharRangeNode(start=av, end=bv)
    return t.ValueRangeNode(alpha=_ambient_alpha(), lower=av, upper=bv)


def _resolve_arm(arm: GRAMMARParser.ArmContext) -> t.SemanticNode:
    if arm.RANGE() is not None:
        return _resolve_range_arm(arm)
    terms = arm.term()
    if len(terms) != 1:  # a leading `RANGE term` (`..τ`) — open range, out of slice
        raise NotImplementedError("open-ended `..` range not in braceBody slice")
    return _resolve_term(terms[0])


def _classify_arms(
    arms: list[GRAMMARParser.ArmContext], exclusions: list[str]
) -> t.SemanticNode:
    """Build the node for a comma-list (an ordered alphabet of points). Ported from
    phase3._classify_arms, driven by arm contexts instead of substrings."""
    if len(arms) == 1:
        return _attach_exclusions(_resolve_arm(arms[0]), exclusions)

    resolved = [_resolve_arm(a) for a in arms]
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


def _is_whole_nested_brace(universe: GRAMMARParser.UniverseContext) -> bool:
    """True if a universe is exactly one un-counted nested brace (`{{X}}`) — the
    object/heterogeneous nesting phase3 resolves specially."""
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


def _resolve_brace_body(body: GRAMMARParser.BraceBodyContext) -> t.SemanticNode:
    """Resolve a `braceBody` (`BANG? band`) into a semantic node — the slice's core
    tree-walk, the phase3 replacement for one rule."""
    band = body.band()
    if band.BAND() is not None:
        raise NotImplementedError("band `::` not in braceBody slice")
    universe = band.universe()[0]

    # Whole-content single nested brace `{{X}}` (no outer `!`): phase3 treats this
    # as object/heterogeneous nesting (a fold or a lazy het run), not a plain arm.
    # Out of the braceBody σ-slice. (A complement `{!{…}}` keeps its BANG, so the
    # `body.BANG()` guard lets it through to the complement path below.)
    if body.BANG() is None and _is_whole_nested_brace(universe):
        raise NotImplementedError("object/heterogeneous `{{…}}` not in braceBody slice")

    arms: list[GRAMMARParser.ArmContext] = []
    exclusions: list[str] = []
    for arm in universe.arm():
        exc = _arm_as_exclusion(arm)
        if exc is not None:
            exclusions.extend(exc)
        else:
            arms.append(arm)
    if not arms:
        raise CompileError(f"Empty brace group: {{{body.getText()}}}")

    node = _classify_arms(arms, exclusions)
    if body.BANG() is not None:
        node = t.ComplementNode(inner=node)
    return node


# ── Tree-walk: pattern → RootNode (structural assembly, phase2 replacement) ───


def _resolve_leaf(literal_run: GRAMMARParser.LiteralRunContext) -> str:
    """A bare top-level literal run. Recognised escapes resolve; an unknown escape
    keeps its backslash (mirrors phase2's leaf scanner, not `unescape`)."""
    raw = literal_run.getText()
    out: list[str] = []
    i = 0
    from himark.parser._text import ESCAPES

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


def _resolve_pattern(ctx: GRAMMARParser.PatternOnlyContext) -> t.RootNode:
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
                    semantic=_resolve_brace_body(body),
                    count=count,
                )
            )
        elif factor.complement() is not None:
            # A top-level subtractive `!{…}`: phase2 folds the `!` into content and
            # phase3 resolves it as a complement.
            body = factor.complement().braceGroup().braceBody()
            children.append(
                t.BraceGroupNode(
                    content="!" + body.getText(),
                    semantic=t.ComplementNode(inner=_resolve_brace_body(body)),
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

    Shared pre-pass (`phase0` split + `phase1` macro/rewrite), then ANTLR + the
    slice tree-walk per step. A whole-step `"…"` template is handled like phase2
    (one verbatim leaf); its interior moustaches are a separate layer, unparsed
    here. Out-of-slice constructs raise `NotImplementedError`."""
    roots: list[t.RootNode] = []
    for step in phase0.split_statement(text):
        pre = phase1.preprocess(step, macros=macros)
        stripped = pre.strip()
        if len(stripped) >= 2 and stripped.startswith('"') and stripped.endswith('"'):
            roots.append(
                t.RootNode(children=[t.LeafNode(content=unescape(stripped[1:-1]))])
            )
            continue
        roots.append(_resolve_pattern(_parse_pattern_tree(pre)))
    return roots
