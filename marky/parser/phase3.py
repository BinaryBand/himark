"""Phase 3: Semantic resolution — convert phase2 nodes into typed HMK AST nodes.

Transforms:
  brace_group  → literal | char_range | string_range | full_alpha |
                 value_range | union | complement | group_class | padded |
                 sequence (a grouping brace — a concatenation of constructs)

A `{…}` brace is one σ (built from `..` and `,`) unless its interior is a
*concatenation* of constructs — then it is a grouping brace (a capture group
whose nested braces are sub-captures, `{of{black}{quartz}}`).

The σ-grammar has two axes: `..` builds an ordered range (≤), and `,` builds a
congruence class (~) whose members are interchangeable spellings of one
position. `{a,A}` is one folded position; `{{a,A},{b,B},…}` is an ordered
alphabet of folded positions.
"""

import re

from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError
from marky.parser import phase2
from marky.parser._text import (
    brace_end,
    inner_of,
    split_top,
    strict_split,
    strip_unescaped,
    unescape,
)

_PADDING_RE = re.compile(r"^(\d+\.\.\d+|\d*)\s*:\s*(.+)$", re.DOTALL)
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
    if _is_sequence_brace(child.content):
        child.semantic = _resolve_sequence_brace(child.content)
    else:
        child.semantic = _resolve_brace(child.content)
    if child.count_src is not None:
        child.count = _parse_count(child.count_src)
        child.count_src = None


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
    _, body = _parse_padding(content)
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


def _parse_padding(content: str) -> tuple[tuple[int, int | None] | None, str]:
    """Strip a padding prefix ({N: }, {N..M: }, {: }) → ((min, max), rest)."""
    pm = _PADDING_RE.match(content)
    if not pm:
        return None, content
    spec, rest = pm.group(1), pm.group(2)
    if not spec:
        return (1, None), rest  # {:expr} — engine derives max from the range
    if ".." in spec:
        lo, hi = spec.split("..", 1)
        return (int(lo), int(hi)), rest
    return (int(spec), int(spec)), rest


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
    ref = _resolve_reference(content)
    if ref is not None:
        return ref

    pad, content = _parse_padding(content)

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
    if pad is not None:
        node = t.PaddedNode(inner=node, min_width=pad[0], max_width=pad[1])
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


def _classify_arms(arms: list[str], exclusions: list[str]) -> t.SemanticNode:
    """Build the appropriate node type for a list of union arms."""
    if len(arms) == 1:
        return _attach_exclusions(_resolve_arm(arms[0]), exclusions)

    # A brace or range arm → ordered union: each arm contributes its own
    # position(s), concatenated. `{{a,A},{b,B}}` is an ordered alphabet of
    # congruence classes; `{a..z,A..Z}` is two ranges placed in sequence.
    if any(a.startswith("{") or ".." in a for a in arms):
        options = [_resolve_arm(a) for a in arms]
        return _attach_exclusions(t.UnionNode(options=options), exclusions)

    # All bare single symbols/tokens → one congruence class: the members are
    # interchangeable spellings of a single position (`,` builds `~`), so `[N]`
    # repetition folds them (`{a,A}[2]` accepts aa, aA, Aa, AA).
    members = _apply_member_exclusions([_member_value(a) for a in arms], exclusions)
    return t.GroupClassNode(groups=[members])


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


def _alpha(part: str) -> t.SemanticNode:
    """Resolve an α part like '{a..z}' into its class node."""
    return _resolve_brace(inner_of(part))


def _resolve_arm(arm: str) -> t.SemanticNode:
    """Resolve one arm (no top-level commas) into a typed node.

    Each `..`-part is classified by cardinality: a singleton (τ) evaluates to its
    one concrete value; anything else is an abstract group (α).
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
            return _alpha(part)
        return t.LiteralNode(content=unescape(part))

    if len(parts) == 2:
        a, b = parts
        av, bv = svals
        if av is not None and bv is not None:
            # τ..τ — a single-char range occupies one position: `{a..z}` matches
            # exactly one symbol a–z. A run is the explicit open range
            # `{a..{a..z}}`. Multi-char endpoints are a lexicographic string
            # range (bounded between the two words).
            if len(av) == 1 and len(bv) == 1:
                return t.CharRangeNode(start=av, end=bv)
            return t.StringRangeNode(start=av, end=bv)
        if av is None and bv is not None:
            return t.ValueRangeNode(alpha=_alpha(a), upper=bv)  # α..τ
        if av is not None and bv is None:
            return t.ValueRangeNode(alpha=_alpha(b), lower=av)  # τ..α
        # α..α — a class-to-class range has no ordering. To fold two classes
        # position-wise, enumerate the pairs as a class of classes
        # (e.g. {{a,A},{b,B},…}).
        raise CompileError(
            f"A class-to-class range is not supported; enumerate the folded "
            f"positions as a class of classes (e.g. {{{{a,A}},{{b,B}}}}): got {arm!r}"
        )

    if len(parts) == 3:
        (av, bv, cv) = svals
        # A bounded range needs single-value endpoints around a class middle,
        # e.g. aa..{a..z}..zz.
        if av is None or cv is None or bv is not None:
            raise CompileError(
                f"Bounded range must be value..class..value "
                f"(e.g. aa..{{a..z}}..zz), got: {arm!r}"
            )
        return t.ValueRangeNode(alpha=_alpha(parts[1]), lower=av, upper=cv)

    raise CompileError(f"Too many '..' separators in: {arm!r}")


# ── Count parsing ─────────────────────────────────────────────────────────────


def _parse_count(src: str) -> t.CountSpec:
    """Parse a count modifier string into a count descriptor."""
    src = src.strip()
    # `[#i]` — repeat exactly group i's repetition count (resolved at match time).
    m = _COUNTREF_RE.fullmatch(src)
    if m:
        return t.CountRefSpec(group=int(m.group(1)))
    m = re.fullmatch(r"(\d*)(\.\.)?(\d*)", src)
    if m and (m.group(1) or m.group(2)):
        lo, dots, hi = m.groups()
        if dots:
            return t.CountRange(min=int(lo) if lo else 0, max=int(hi) if hi else None)
        return t.CountRange(min=int(lo), max=int(lo))
    raise CompileError(f"Invalid count expression: [{src}]")
