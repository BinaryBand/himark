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
alphabet of folded positions. A value *bound* is `{floor:alphabet:ceiling}`:
the alphabet restricted to values floor–ceiling, the two written widths setting
the field-width window (`{0:@d:255}`, `{aa:@l:zz}`, `{x::y}` = ambient @uni).
"""

import re

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError
from himark.parser import phase2
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


def _resolve_brace_node(child: t.BraceGroupNode) -> None:
    """Resolve a brace group in place: a `{…}` is an alphabet expression unless
    its interior concatenates constructs, in which case it is a grouping brace
    (`SequenceNode`). Any `[count]` suffix is parsed too."""
    if child.fuzz is not None:
        child.semantic = _resolve_fuzzy(child.content, child.fuzz)
    elif _is_sequence_brace(child.content):
        child.semantic = _resolve_sequence_brace(child.content)
    else:
        child.semantic = _resolve_brace(child.content)
    if child.count_src is not None:
        child.count = _parse_count(child.count_src)
        child.count_src = None


def _resolve_fuzzy(content: str, k: int) -> t.FuzzyNode:
    """A `{token}~k` fuzzy operand: a token, a token union, or a single
    alphabet-annotated token `{token:A:token}` whose middle `A` is the bridge
    alphabet the edits draw from (default: ambient Unicode). Each plain arm must
    be a token; an annotated operand reuses the bounds grammar but must collapse
    to one token (floor == ceiling)."""
    arms = split_top(",", content)
    tokens: list[str] = []
    alpha: t.SemanticNode | None = None
    for arm in arms:
        colon = split_top(":", arm)
        if len(colon) == 3:  # {token:A:token} — alphabet-annotated
            if len(arms) > 1:
                raise CompileError(
                    "An alphabet-annotated fuzzy token cannot be part of a union; "
                    f"write a single {{token:A:token}}~k, got: {content!r}"
                )
            bound = _resolve_bounds(colon)
            if bound.lower is None or bound.lower != bound.upper:
                raise CompileError(
                    "A fuzzy alphabet annotation is {token:A:token} with floor "
                    f"== ceiling (one token), got: {arm!r}"
                )
            tokens.append(bound.lower)
            alpha = bound.alpha
        elif len(colon) == 1:
            val = _singleton_value(arm)
            if val is None:
                raise CompileError(
                    f"A fuzzy operand must be a token or token union, got: {arm!r}"
                )
            tokens.append(val)
        else:
            raise CompileError(
                f"A fuzzy alphabet annotation is token:alphabet:token, got: {arm!r}"
            )
    if not tokens:
        raise CompileError(f"Empty fuzzy operand: {{{content}}}~{k}")
    return t.FuzzyNode(tokens=tokens, k=k, alpha=alpha)


def parse(node: t.RootNode) -> t.RootNode:
    """Walk the phase2 tree and resolve each brace group in place."""
    for child in node.children:
        if isinstance(child, t.BraceGroupNode):
            _resolve_brace_node(child)
    return node


# ── Grouping brace (concatenation vs. alphabet) ───────────────────────────────


def _resolve_sequence_brace(content: str) -> t.SequenceNode:
    """Re-tokenize and resolve a grouping brace's interior into one capture group;
    its nested brace children become the group's sub-captures."""
    sub = parse(phase2.parse(content))
    return t.SequenceNode(children=sub.children)


def _is_sequence_brace(content: str) -> bool:
    """True if a brace's interior is a *concatenation* of constructs rather than a
    single alphabet expression.

    The σ-grammar has no concatenation operator: every `,`/`..`-separated part is
    bare text or exactly one `{…}` atom. A part that glues a construct onto
    adjacent text — or holds more than one construct — is a sub-pattern.
    """
    if len(split_top(":", content)) == 3:
        return False  # a `{floor:alphabet:ceiling}` bound is one value universe
    body = content
    if body.startswith("!"):
        body = body[1:]
    for arm in split_top(",", body):
        for part in split_top("..", arm):
            if not _is_sigma_atom(part):
                return True
    return False


def _is_sigma_atom(part: str) -> bool:
    """True if `part` is a valid σ atom: bare text, or a single `{…}` (optionally
    with an exact `[N]` count) surrounded only by whitespace. A construct glued
    to text, several constructs, or a ranged count is a sub-pattern fragment."""
    part = strip_unescaped(part)
    if part.startswith("!"):
        part = part[1:].strip()  # a `!` complement/exclusion arm, e.g. !{0,l,I,O}
    if not part:
        return True
    children = phase2.parse(part).children
    constructs = [c for c in children if isinstance(c, t.BraceGroupNode)]
    if not constructs:
        return True  # bare token (a..z, cat, etc.)
    if len(constructs) > 1:
        return False
    only = constructs[0]
    if any(isinstance(c, t.LeafNode) and c.content.strip() for c in children):
        return False  # a brace glued to adjacent literal text → concatenation
    if only.count_src is not None and not re.fullmatch(r"\d+", only.count_src.strip()):
        return False  # a ranged/star count is repetition, not a σ singleton
    return True


# ── Brace resolution ─────────────────────────────────────────────────────────


def _ambient_alpha() -> t.SemanticNode:
    """The ambient Unicode universe (`@uni`): every code point. It is the default
    alphabet for a bound with an empty middle (`{x::y}`) and for an unnamed
    multi-char `..` range (`{aa..zz}` == `{aa:@uni:zz}`)."""
    return t.CharRangeNode(start="\x00", end="\U0010ffff")


def _resolve_universe(expr: str) -> t.SemanticNode:
    """Resolve a universe expression — the middle of a bound, or a `{…}` alphabet
    arm. Strips one layer of surrounding braces (`{a..z}` → `a..z`) so a bare
    expression and a braced one resolve the same way."""
    expr = strip_unescaped(expr)
    if expr.startswith("{") and brace_end(expr) == len(expr):
        expr = inner_of(expr)
    return _resolve_brace(expr)


def _resolve_bounds(parts: list[str]) -> t.ValueRangeNode:
    """Resolve a `{floor:alphabet:ceiling}` bound. An empty alphabet normalises to
    @uni (full Unicode); an omitted floor/ceiling is an open end. Endpoint strings
    are kept verbatim — their written widths set the engine's field-width window."""
    floor_s, alpha_s, ceil_s = (strip_unescaped(p) for p in parts)
    if alpha_s == "":
        alpha: t.SemanticNode = _ambient_alpha()
    else:
        alpha = _resolve_universe(alpha_s)
    # Endpoints may be singleton constructors (`{1}[3]` → '111'), else literal text.
    lower = _member_value(floor_s) if floor_s else None
    upper = _member_value(ceil_s) if ceil_s else None
    if lower is None and upper is None:
        raise CompileError("A bound needs a floor or a ceiling: got '{:U:}'")
    return t.ValueRangeNode(alpha=alpha, lower=lower, upper=upper)


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
    if sa == "@^":
        return t.AnchorNode(at="line_start")
    if sa == "@$":
        return t.AnchorNode(at="line_end")
    if sa == "@^^":
        return t.AnchorNode(at="scope_start")
    if sa == "@$$":
        return t.AnchorNode(at="scope_end")

    ref = _resolve_reference(content)
    if ref is not None:
        return ref

    # `:`-bounds: {floor:alphabet:ceiling} (two top-level colons). A literal colon
    # in a class is escaped (`\:`).
    colon_parts = split_top(":", content)
    if len(colon_parts) == 3:
        return _resolve_bounds(colon_parts)

    # Object nesting `{{X}}`: a brace whose whole content is one nested brace is
    # a single object. A materialisable inner (`{{a,A}}`) folds its members into
    # one congruence group, repeated with faces free; a range/value inner
    # (`{{a..z}}`) stays a lazy heterogeneous run (a fresh match per rep).
    stripped = strip_unescaped(content)
    if stripped.startswith("{") and brace_end(stripped) == len(stripped):
        inner = _resolve_brace(inner_of(stripped))
        grps = _arm_group(inner)
        if grps is not None:
            return t.GroupClassNode(groups=grps)
        return t.HeterogeneousNode(inner=inner)

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
    range/value/complement that cannot be materialised. A bare token is one
    singleton group; a flat class of primitives folds into a single object
    (`{a,A}` → `[[a, A]]`); a class that is already an ordered alphabet of objects
    keeps its groups in order (`{{a,A},{b,B}}` stays two folded positions, so `@w`
    is 26 ordered case-folds)."""
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

    `..` is a plain range between two concrete endpoints. A value *bound* (an
    alphabet plus floor/ceiling) is written with `:` ({floor:alphabet:ceiling}),
    not `..`, so an alphabet endpoint here is an error pointing at the `:` form.
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
            # ambient Unicode (HMK.md §Universes): `{aa..zz}` == `{aa:@uni:zz}`,
            # the whole value band between the two words, the written widths
            # setting the field-width window.
            if len(av) == 1 and len(bv) == 1:
                return t.CharRangeNode(start=av, end=bv)
            return t.ValueRangeNode(alpha=_ambient_alpha(), lower=av, upper=bv)
        # An alphabet endpoint means this is a value bound, now spelled with `:`.
        raise CompileError(
            f"A value bound is written '{{floor:alphabet:ceiling}}' with ':', "
            f"not '..': got {arm!r}"
        )

    if len(parts) == 3:
        av, bv, cv = svals
        # τ..τ..s — a strided single-char range: `{a..z..2}` is a, c, e, … as one
        # ordered alphabet of stepped positions.
        if (
            av is not None
            and bv is not None
            and cv is not None
            and len(av) == 1
            and len(bv) == 1
            and cv.isdigit()
        ):
            step = int(cv)
            if step < 1:
                raise CompileError(f"A stride must be positive: got {arm!r}")
            chars = [chr(c) for c in range(ord(av), ord(bv) + 1, step)]
            return t.GroupClassNode(groups=[[ch] for ch in chars])
        raise CompileError(
            f"A 3-part '..' is a stride 'lo..hi..step' ('{{a..z..2}}'); a value "
            f"bound uses ':' ('{{floor:alphabet:ceiling}}'): got {arm!r}"
        )

    raise CompileError(f"Too many '..' separators in: {arm!r}")


# ── Count parsing ─────────────────────────────────────────────────────────────


def _parse_count(src: str) -> t.CountSpec:
    """Parse a count modifier string into a count descriptor.

    Forms: `[n]`, `[x..]`, `[..y]`, `[x..y]`, `[x..y..s]` (stride), `[..<y]`
    (lazy), `[a,b,c]` (union), `[#i]` (count-reference)."""
    src = src.strip()
    # `[#i]` — repeat exactly group i's repetition count (resolved at match time).
    m = _COUNTREF_RE.fullmatch(src)
    if m:
        return t.CountRefSpec(group=int(m.group(1)))
    # `[a,b,c]` — an explicit union of exact counts.
    if "," in src:
        try:
            values = sorted({int(p.strip()) for p in src.split(",")})
        except ValueError:
            raise CompileError(f"Invalid count expression: [{src}]") from None
        return t.CountSet(values=values)
    # `[n]` / `[x..y]` with optional lazy `<` and optional stride `..s`.
    m = re.fullmatch(r"(\d*)(?:\.\.(<?)(\d*)(?:\.\.(\d+))?)?", src)
    if not m or not (m.group(1) or ".." in src):
        raise CompileError(f"Invalid count expression: [{src}]")
    lo, lazy, hi, step = m.groups()
    if ".." not in src:  # exact [n]
        return t.CountRange(min=int(lo), max=int(lo))
    step_n = int(step) if step else 1
    max_n = int(hi) if hi else None
    if step_n != 1 and max_n is None:
        raise CompileError(f"A strided count needs an upper bound: [{src}]")
    return t.CountRange(
        min=int(lo) if lo else 0, max=max_n, step=step_n, lazy=bool(lazy)
    )
