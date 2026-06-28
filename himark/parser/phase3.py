"""Phase 3: Semantic resolution — convert phase2 nodes into typed HMK AST nodes.

Transforms:
  brace_group  → literal | char_range | value_range |
                 union | complement | group_class |
                 sequence (a grouping brace — a concatenation of constructs)

A `{…}` brace is one σ (built from `..` and `,`) unless its interior is a
*concatenation* of constructs — then it is a grouping brace (a capture group
whose nested braces are sub-captures, `{of{black}{quartz}}`).

The σ-grammar has two axes: `..` builds an ordered range (≤), and `,` builds a
congruence class (~) whose members are interchangeable spellings of one
position. `{a,A}` is one folded position; `{{a,A},{b,B},…}` is an ordered
alphabet of folded positions. A *band* is `{payload::band}`: a payload alphabet
restricted by a band over its values — a `..` range (`{@d::0..255}`), a single
value (`{@d::5}`), or a `,`-union of either (`{@d::1..5,9..12}`). Written endpoint
widths set the field-width window. A brace is a band iff its body holds a
top-level `::`, which splits payload from band; a single `:` is always literal
(`{12:30}`, `{https://x.com}`), and a literal `::` is escaped `\\::`.
"""

import re

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError
from himark.parser import phase2
from himark.parser._count import parse_count
from himark.parser._shape import is_sequence_brace
from himark.parser._text import (
    brace_end,
    inner_of,
    split_top,
    strict_split,
    strip_unescaped,
    unescape,
)

_BACKREF_RE = re.compile(r"\$(\d+)")
_COUNTREF_RE = re.compile(r"#(\d+)")
_STAGEREF_RE = re.compile(r"(\d+)\$(\d+(?:\.\d+)*)?")


_EXCLUDABLE = (
    t.CharRangeNode,
    t.ValueRangeNode,
    t.UnionNode,
)


def _attach_exclusions(node: t.SemanticNode, exclusions: list[str]) -> t.SemanticNode:
    """Set `exclusions` on a node that supports them; ignore for those that don't."""
    if exclusions and isinstance(node, _EXCLUDABLE):
        node.exclusions = exclusions
    return node


def _resolved_brace(child: t.BraceGroupNode) -> t.BraceGroupNode:
    """Resolve a brace group into a **fresh** node, leaving `child` untouched: a
    `{…}` is an alphabet expression unless its interior concatenates constructs, in
    which case it is a grouping brace (`SequenceNode`). Any `[count]` suffix is
    parsed too."""
    # A band with a braced-universe head (`{{a..z}::b}`) reads as a nested brace
    # plus adjacent text, so test for a band before the grouping-brace check.
    split = _split_band(child.content)
    if split is not None:
        semantic: t.SemanticNode = _resolve_band(*split)
    elif is_sequence_brace(child.content):
        semantic = resolve_grouping_brace(child.content)
    else:
        semantic = _resolve_brace(child.content)
    count, count_src = child.count, child.count_src
    if count_src is not None:
        count, count_src = parse_count(count_src), None
    return t.BraceGroupNode(
        content=child.content, semantic=semantic, count=count, count_src=count_src
    )


def parse(node: t.RootNode) -> t.RootNode:
    """Resolve every brace group, returning a **new** tree — the phase-2 input is
    left unmodified, so resolution is a pure function of the structural tree.
    (Leaf nodes are immutable and carried through as-is.)"""
    children = [
        _resolved_brace(c) if isinstance(c, t.BraceGroupNode) else c
        for c in node.children
    ]
    return t.RootNode(children=children, fixed_point=node.fixed_point)


# ── Grouping brace (concatenation vs. alphabet) ───────────────────────────────


def resolve_grouping_brace(content: str) -> t.SequenceNode:
    """Resolve a grouping brace into one capture group (``SequenceNode``).
    Two forms:
    - Single nested brace `{{X}}`: resolve the inner as an alphabet expression,
      wrap as single-child scope — re-entry per rep frees members afresh.
    - Concatenation `{of{x}{y}}`: re-tokenize interior as a sub-pattern, whose
      nested brace children become sub-captures.
    (The concatenation-vs-alphabet test lives in `parser/_shape.py`.)"""
    stripped = strip_unescaped(content)
    if stripped.startswith("{") and brace_end(stripped) == len(stripped):
        # {{X}} — single-child grouping; re-entry per rep frees members
        inner = _resolve_brace(inner_of(stripped))
        return t.SequenceNode(children=[inner])
    # Concatenation — re-parse interior as sub-pattern
    sub = parse(phase2.parse(content))
    return t.SequenceNode(children=sub.children)

# ── Brace resolution ─────────────────────────────────────────────────────────


def _ambient_alpha() -> t.SemanticNode:
    """The ambient Unicode universe (`@uni`): every code point. It is the default
    alphabet for a band with an empty payload (`{::0..255}`) and for an unnamed
    multi-char `..` range (`{aa..zz}` == `{@uni::aa..zz}`)."""
    return t.CharRangeNode(start="\x00", end="\U0010ffff")


def _resolve_universe(expr: str) -> t.SemanticNode:
    """Resolve a universe expression — a band's payload, or a `{…}` alphabet arm.
    Strips one layer of surrounding braces (`{a..z}` → `a..z`) so a bare
    expression and a braced one resolve the same way."""
    expr = strip_unescaped(expr)
    if expr.startswith("{") and brace_end(expr) == len(expr):
        expr = inner_of(expr)
    return _resolve_brace(expr)


def _split_band(content: str) -> tuple[str, str] | None:
    """Split a brace body into `(payload, band)` at the **first** top-level `::`, or
    None when there is no top-level `::`. The band keeps every later `::` and every
    single `:` (they read literally), so `{a::b::c}` → `('a', 'b::c')`.

    The presence of a top-level `::` is the *only* signal of a band (ANTLR branch):
    no inspection of the head or the right side. A single `:` is always literal and
    never splits, and a literal `::` is escaped `\\::`."""
    parts = split_top("::", content)
    if len(parts) < 2:
        return None
    return parts[0], "::".join(parts[1:])


def _resolve_band(payload: str, band: str) -> t.SemanticNode:
    """Resolve a `{payload::band}` band. The payload is any universe (ambient @uni
    when empty); the band is a `,`-union of arms, each a `lo..hi` range or a single
    value over the payload alphabet. One arm is a `ValueRangeNode`; several fold
    into a `UnionNode` of ranges (`{@d::1..5,9..12}`)."""
    payload = strip_unescaped(payload)
    alpha: t.SemanticNode = (
        _ambient_alpha() if payload == "" else _resolve_universe(payload)
    )
    options = [_resolve_band_arm(alpha, arm) for arm in split_top(",", band)]
    return options[0] if len(options) == 1 else t.UnionNode(options=options)


def _resolve_band_arm(alpha: t.SemanticNode, arm: str) -> t.ValueRangeNode:
    """One band arm: a `lo..hi` range (either end omittable) or a single value
    (`{@d::5}` is `5..5`). An endpoint may be a reference (`{@d::0..$0}`), resolved
    to a captured value at match time; else its written width sets the field
    window."""
    parts = split_top("..", arm)
    if len(parts) == 1:
        value, ref = _bound_endpoint(strip_unescaped(parts[0]))
        if value is None and ref is None:
            raise CompileError(f"An empty band arm has no value: got {arm!r}")
        return t.ValueRangeNode(
            alpha=alpha, lower=value, upper=value, lower_ref=ref, upper_ref=ref
        )
    if len(parts) == 2:
        lower, lower_ref = _bound_endpoint(strip_unescaped(parts[0]))
        upper, upper_ref = _bound_endpoint(strip_unescaped(parts[1]))
        if lower is None and upper is None and lower_ref is None and upper_ref is None:
            raise CompileError("A band needs a floor or a ceiling: got '{U:..}'")
        return t.ValueRangeNode(
            alpha=alpha,
            lower=lower,
            upper=upper,
            lower_ref=lower_ref,
            upper_ref=upper_ref,
        )
    raise CompileError(
        f"Too many '..' in a band arm (a range is 'lo..hi'): got {arm!r}"
    )


def _bound_endpoint(s: str) -> tuple[str | None, t.SemanticNode | None]:
    """Resolve one bound endpoint into `(literal, reference)`. A `$i` / `N$M` /
    `#i` endpoint is a reference node (dynamic); anything else is literal text."""
    if not s:
        return None, None
    ref = _resolve_reference(s)
    return (None, ref) if ref is not None else (_member_value(s), None)


def _resolve_reference(content: str) -> t.SemanticNode | None:
    """A whole-brace reference node, or None if the brace is an alphabet expression.

    Three forms, each consuming the entire brace:
      `{$i}`    back-ref — the literal text captured by group i (`\\$` is a literal).
      `{#i}`    count-ref — group i's decimal repetition count.
      `{N$M.K}` cross-stage ref — stage N's capture M (dotted into sub-captures),
                or its whole match for `{N$}`.
    """
    stripped = strip_unescaped(content)
    m = _BACKREF_RE.fullmatch(stripped)
    if m:
        return t.BackRefNode(group=int(m.group(1)))
    m = _COUNTREF_RE.fullmatch(stripped)
    if m:
        return t.CountRefNode(group=int(m.group(1)))
    m = _STAGEREF_RE.fullmatch(stripped)
    if m:
        path = tuple(int(i) for i in m.group(2).split(".")) if m.group(2) else ()
        return t.StageRefNode(stage=int(m.group(1)), path=path)
    return None


def _resolve_brace(content: str) -> t.SemanticNode:
    """Resolve the inner text of a {…} brace group into a typed semantic node."""
    sa = strip_unescaped(content)
    if sa == "@<":
        return t.AnchorNode(at="line_start")
    if sa == "@>":
        return t.AnchorNode(at="line_end")
    if sa == "@<<":
        return t.AnchorNode(at="doc_start")
    if sa == "@>>":
        return t.AnchorNode(at="doc_end")

    ref = _resolve_reference(content)
    if ref is not None:
        return ref

    # `::`-bands: {payload::band}. A top-level `::` separates a payload alphabet
    # from a value band; its presence alone marks a band, with no head inspection
    # (ANTLR branch). A single `:` is always literal (`{12:30}`, `{https://x.com}`),
    # and a literal `::` is escaped `\::`.
    split = _split_band(content)
    if split is not None:
        return _resolve_band(*split)


    # Object nesting `{{X}}` → grouping brace (scope).
    # A brace whose whole content is one nested brace is a single-child
    # grouping — resolved via resolve_grouping_brace so all callers
    # (including _resolve_universe) produce the uniform representation.
    stripped = strip_unescaped(content)
    if stripped.startswith("{") and brace_end(stripped) == len(stripped):
        return resolve_grouping_brace(stripped)




    # Complement prefix: {!expr}
    is_complement = content.startswith("!")
    if is_complement:
        content = content[1:]

    # Split on top-level commas. Whitespace is significant — reject leading/trailing
    # spaces on arms unless the arm is purely whitespace (e.g. { } = literal space)
    # or is a single nested-brace arm needing disambiguation space (e.g. { {a..z} }).
    raw_arms = split_top(",", content)
    arms = []
    for a in raw_arms:
        stripped = strip_unescaped(a)
        if stripped and stripped != a:
            if len(raw_arms) == 1:
                # A single arm has no comma to pad. A leading-brace value keeps its
                # disambiguation spacing stripped ({ {a..z} } → {a..z}); otherwise
                # the surrounding whitespace may be a `..` operand ({a.. }), so keep
                # it raw and let _resolve_arm apply whitespace significance.
                arms.append(stripped if stripped.startswith("{") else a)
            else:
                raise CompileError(
                    f"Unexpected whitespace in '{{{content}}}': "
                    f"remove spaces around ','"
                )
        else:
            arms.append(a)

    # Separate exclusion arms (!value, !v1..v2, or !{set}). A braced operand is
    # a set: each member subtracts independently, so `!{0,l,I,O}` drops all four.
    exclusions: list[str] = []
    for a in arms:
        if not a.startswith("!"):
            continue
        operand = a[1:].strip()
        if operand.startswith("{") and brace_end(operand) == len(operand):
            exclusions.extend(m.strip() for m in split_top(",", inner_of(operand)))
        else:
            exclusions.append(operand)
    include_arms = [a for a in arms if not a.startswith("!")]
    if not include_arms:
        raise CompileError(f"Empty brace group: {{{content}}}")

    node = _classify_arms(include_arms, exclusions)

    if is_complement:
        node = t.ComplementNode(inner=node)
    return node


def _member_value(arm: str) -> str:
    """The concrete spelling of a bare congruence-class member (`a`, `cat`, a
    literal space). Escapes are resolved (`\\ ` → space, `\\n` → newline)."""
    sval = _singleton_value(arm)
    return sval if sval is not None else unescape(arm)


def _apply_member_exclusions(members: list[str], exclusions: list[str]) -> list[str]:
    """Drop class members named by an exclusion (a single value or a `lo..hi`)."""
    if not exclusions:
        return members
    singles = {e for e in exclusions if ".." not in e}
    ranges = [tuple(e.split("..", 1)) for e in exclusions if ".." in e]
    return [
        m
        for m in members
        if m not in singles and not any(lo <= m <= hi for lo, hi in ranges)
    ]


def _arm_group(node: t.SemanticNode) -> list[list[str]] | None:
    """The congruence groups one comma-arm contributes, or None when the arm is a
    range/value/complement that cannot be materialised. A bare token is one singleton
    group. The fold here **is** the nesting step: an arm that is itself a flat class
    of primitives — the inner `{a,A}` of `{{a,A},…}`, or the whole inner of `{{a,A}}`
    — collapses to one congruence group (`[[a, A]]`, one opaque position); an arm
    already an ordered alphabet of objects (`{{a,A},{b,B}}`) keeps its groups in order
    (two folded positions, so `@w` is 26 ordered case-folds). A non-nested `{a,A}`
    never reaches this fold — it is two singleton groups."""
    if isinstance(node, t.LiteralNode):
        return [[node.content]]
    if isinstance(node, t.GroupClassNode):
        if all(len(g) == 1 for g in node.groups):
            return [[m for g in node.groups for m in g]]  # flat primitives → fold
        return [list(g) for g in node.groups]  # ordered alphabet of objects → keep
    return None


def _classify_arms(arms: list[str], exclusions: list[str]) -> t.SemanticNode:
    """Build the node for a comma-list: an **ordered alphabet of points**. Each
    arm contributes its group(s): a bare arm is a primitive (a singleton group);
    a nested brace arm is an object that folds into one group, unless it is
    already an alphabet of objects (whose groups carry through in order). When
    every arm is materialisable this is a `GroupClassNode` (so `{a,b}` is `{a..b}`
    and `{{a,A},{c,C}}` is two folded positions); a range/value arm (`{a..z}`,
    `{@d}`) keeps the alphabet lazy as an ordered `UnionNode`."""
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

    # A range/value arm → ordered union, kept lazy (`{a..z,A..Z}`, `{@d},{@u}`).
    return _attach_exclusions(t.UnionNode(options=resolved), exclusions)


def _singleton_value(expr: str) -> str | None:
    """Return the single concrete value of `expr` if it has cardinality 1, else None.

    A singleton is τ: a bare literal, or a `{...}` (with an optional exact `[N]`
    count) whose inner expression is itself a singleton. `{a}` is implicitly
    `{a}[1]`, so `{a}[3]` → 'aaa'. Named alphabets, unions, and value ranges all
    have cardinality > 1 and yield None. The value is returned with escapes
    resolved (`\\ ` is a literal space, `\\n` a newline, …).
    """
    expr = strip_unescaped(expr)
    if not expr:
        return None
    if expr.startswith("!") and len(expr) > 1:
        return None  # complement — a class, never a singleton
    if expr.startswith("{"):
        end = brace_end(expr)
        if end is None:
            return None
        inner_val = _singleton_value(expr[1 : end - 1])
        if inner_val is None:
            return None
        rest = expr[end:]
        if not rest:
            return inner_val
        m = re.fullmatch(r"\[(\d+)\]", rest)
        return inner_val * int(m.group(1)) if m else None
    if len(split_top(",", expr)) > 1 or len(split_top("..", expr)) > 1:
        return None
    return unescape(expr)


def _resolve_arm(arm: str) -> t.SemanticNode:
    """Resolve one arm (no top-level commas) into a typed node.

    `..` is a plain range between two concrete endpoints. A *band* (an alphabet
    plus a value range) is written with `::` (`{alphabet::lo..hi}`), not `..`, so an
    alphabet endpoint here is an error pointing at the `::` form.
    """
    parts = strict_split("..", arm, arm)
    svals = [_singleton_value(p) for p in parts]

    if len(parts) == 1:
        part, sval = parts[0], svals[0]
        if part.startswith("{"):
            if sval is not None:
                # Singleton {…} → literal match of its single value
                return t.LiteralNode(content=sval)
            # A brace around a single class is transparent — it occupies the
            # same single position as the class it wraps (`{ {a..z} }` = `{a..z}`).
            return _resolve_universe(part)
        return t.LiteralNode(content=unescape(part))

    if len(parts) == 2:
        av, bv = svals
        if av is not None and bv is not None:
            # τ..τ — a range between two concrete endpoints. Single chars occupy
            # one position (`{a..z}`); a multi-char range is a value bound over
            # ambient Unicode (HMK.md §Universes): `{aa..zz}` == `{@uni::aa..zz}`,
            # the whole value band between the two words, the written widths
            # setting the field-width window.
            if len(av) == 1 and len(bv) == 1:
                return t.CharRangeNode(start=av, end=bv)
            return t.ValueRangeNode(alpha=_ambient_alpha(), lower=av, upper=bv)
        # An alphabet endpoint means this is a band, now spelled with `:`.
        raise CompileError(
            f"A '..' range needs concrete endpoints; a band over an alphabet is "
            f"'{{alphabet::lo..hi}}' with '::': got {arm!r}"
        )

    raise CompileError(
        f"Too many '..' separators in a range (a band is '{{alphabet::lo..hi}}' "
        f"with '::'): got {arm!r}"
    )
