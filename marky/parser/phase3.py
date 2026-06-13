"""Phase 3: Semantic resolution — convert phase2 nodes into typed HMK AST nodes.

Transforms:
  brace_group  → literal | char_range | string_range | full_alpha |
                 value_range | union | complement | token_set |
                 group_class | padded
  double_braces → template node (see parser/templates.py)
  separator    → separator (resolved to sep_value or sep_class)

A brace group whose content holds a top-level `<<...>>` is not arithmetic — it
encloses a pattern sub-sequence (e.g. `{**<<>>**}`). Such a brace is transparent:
its interior is re-tokenized and spliced into the parent sequence, so inner
constructs capture and number as if the brace were not there.
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
_COUNT_SRC_REF_RE = re.compile(r"^\{\{#(\d+)\}\}$")


_EXCLUDABLE = (
    t.CharRangeNode,
    t.FullAlphaNode,
    t.ValueRangeNode,
    t.UnionNode,
    t.TokenSetNode,
)


def _attach_exclusions(node: t.SemanticNode, exclusions: list[str]) -> t.SemanticNode:
    """Set `exclusions` on a node that supports them; ignore for those that don't."""
    if exclusions and isinstance(node, _EXCLUDABLE):
        node.exclusions = exclusions
    return node


def parse(node: t.RootNode) -> t.RootNode:
    """Walk the phase2 tree and resolve all construct nodes in place."""
    new_children: list[t.Node] = []
    for child in node.children:
        if isinstance(child, t.BraceGroupNode):
            if _is_sequence_brace(child.content):
                _resolve_sequence_brace(child, new_children)
                continue
            child.semantic = _resolve_brace(child.content)
            if child.count_src is not None:
                child.count = _parse_count(child.count_src)
                child.count_src = None
            new_children.append(child)
        elif isinstance(child, t.SeparatorNode):
            _resolve_separator(child)
            new_children.append(child)
        else:
            new_children.append(child)
    node.children = new_children
    return node


# ── Separator resolution ──────────────────────────────────────────────────────


def _resolve_separator(node: t.SeparatorNode) -> None:
    """Resolve separator content by cardinality.

    τ (a bare constant or singleton constructor) keeps split semantics — the
    span is split on every occurrence of the constant (`sep_value`). α is an
    arithmetic class — the span must be a member of it (`sep_class`). Empty
    content (`<<>>`) stays an unconstrained span.
    """
    content = node.content
    if not content:
        return

    dot_parts = split_top("..", content)
    comma_parts = split_top(",", content)
    has_ops = (
        len(dot_parts) > 1
        or len(comma_parts) > 1
        or content.startswith("{")
        or (content.startswith("!") and len(content) > 1)  # complement class
    )

    # τ: bare constant with no arithmetic operators (<<\n>>, << >>, <<abc>>)
    if not has_ops:
        node.sep_value = content
        return

    # τ: singleton constructor ({a}[3] → 'aaa')
    sval = _singleton_value(content)
    if sval is not None:
        node.sep_value = sval
        return

    # Operator chars with empty operands are punctuation constants (<<,>>,
    # <<..>>), not arithmetic.
    if (len(dot_parts) > 1 and any(not p.strip(" \t") for p in dot_parts)) or (
        len(comma_parts) > 1 and any(not p.strip(" \t") for p in comma_parts)
    ):
        node.sep_value = content
        return

    # α: the span is constrained to the class.
    node.sep_class = _resolve_brace(content)


# ── Brace resolution ─────────────────────────────────────────────────────────


def _has_top_level_separator(content: str) -> bool:
    """True if `content` holds a `<<` at brace depth 0 — i.e. the brace group
    encloses a pattern sub-sequence rather than an arithmetic expression."""
    depth = 0
    i = 0
    while i < len(content):
        ch = content[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0 and content[i : i + 2] == "<<":
            return True
        i += 1
    return False


# ── Brace grouping (sequence vs. alphabet) ────────────────────────────────────


def _is_sequence_brace(content: str) -> bool:
    """True if a brace's interior is a *sequence* (a concatenation of constructs)
    rather than a single alphabet expression.

    The σ-grammar has no concatenation operator: every `..`/`,`-separated part is
    either bare text or exactly one `{…}`/`<->` atom. So a part that glues a
    construct onto adjacent text — or holds more than one construct, or a
    separator — can only be a sub-pattern. Such a brace becomes a transparent
    group (spliced when uncounted, a repeatable unit when counted), making
    `{X}` match-equivalent to `X`.
    """
    if _has_top_level_separator(content):
        return True
    _, body = _parse_padding(content)
    if body.startswith("!"):
        body = body[1:]
    # σ joins atoms with `,`, `..`, and `<->`; none is concatenation. Split on
    # all three and check each atom — a leftover concatenation is a sub-pattern.
    for arm in split_top(",", body):
        for part in split_top("..", arm):
            for atom in split_top("<->", part):
                if not _is_sigma_atom(atom):
                    return True
    return False


def _is_sigma_atom(part: str) -> bool:
    """True if `part` is a valid σ atom: bare text, or a single `{…}` (with an
    optional exact `[N]` count) surrounded only by whitespace. Anything else —
    a construct glued to text, several constructs, a separator, or a ranged
    count — is a sub-pattern fragment, not arithmetic."""
    part = strip_unescaped(part)
    if part.startswith("!"):
        part = part[1:].strip()  # a `!` complement/exclusion arm, e.g. !{0,l,I,O}
    if not part:
        return True
    children = phase2.parse(part).children
    constructs = [
        c for c in children if isinstance(c, (t.BraceGroupNode, t.SeparatorNode))
    ]
    if not constructs:
        return True  # bare token (a..z, cat, etc.)
    if len(constructs) > 1 or isinstance(constructs[0], t.SeparatorNode):
        return False
    only = constructs[0]
    if any(isinstance(c, t.LeafNode) and c.content.strip() for c in children):
        return False  # a brace glued to adjacent literal text → concatenation
    if only.count_src is not None and not re.fullmatch(r"\d+", only.count_src.strip()):
        return False  # a ranged/star count is repetition, not a σ singleton
    return True


def _is_unit_count(count_src: str | None) -> bool:
    """True if the count is absent or exactly `[1]` — i.e. one repetition, which
    the spec defines as identical to no count."""
    if count_src is None:
        return True
    count = _parse_count(count_src)
    return isinstance(count, t.CountRange) and count.min == 1 and count.max == 1


def _resolve_sequence_brace(child: t.BraceGroupNode, out: list[t.Node]) -> None:
    """Resolve a sequence brace into the parent child list.

    Uncounted (or `[1]`): the re-tokenized interior is spliced transparently, so
    inner constructs number left-to-right as if the brace were not there. With a
    real count: the interior becomes one `SequenceNode` matched as a single
    repeatable unit."""
    sub = parse(phase2.parse(child.content))
    if _is_unit_count(child.count_src):
        out.extend(sub.children)
        return
    if any(isinstance(c, t.SeparatorNode) for c in sub.children):
        raise CompileError(
            f"A repeated group cannot contain a separator: "
            f"{{{child.content}}}[{child.count_src}]"
        )
    child.semantic = t.SequenceNode(children=sub.children)
    child.count = _parse_count(child.count_src)
    child.count_src = None
    out.append(child)


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


def _resolve_brace(content: str) -> t.SemanticNode:
    """Resolve the inner text of a {…} brace group into a typed semantic node."""
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
            if len(raw_arms) == 1 and stripped.startswith("{"):
                arms.append(stripped)  # single nested-brace: disambiguation space
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


def _classify_arms(arms: list[str], exclusions: list[str]) -> t.SemanticNode:
    """Build the appropriate node type for a list of union arms."""
    if len(arms) == 1:
        return _attach_exclusions(_resolve_arm(arms[0]), exclusions)

    # Any brace arm → plain union of classes. A braced `<->` arm resolves to a
    # ZipNode here, so the enumerated form `{{a<->A},{b<->B}}` is just a union
    # of single-position zips — the same alphabet as `{a..b}<->{A..B}`.
    if any(a.startswith("{") for a in arms):
        options = [_resolve_arm(a) for a in arms]
        return _attach_exclusions(t.UnionNode(options=options), exclusions)

    # All bare. Any multi-char token (not a range, not a lone escaped char)
    # makes this a string-token alphabet.
    has_multi = any(
        len(a) > 1
        and ".." not in a
        and not (len(a) == 2 and a.startswith("\\"))  # not an escaped char
        for a in arms
    )
    if has_multi:
        return _attach_exclusions(t.TokenSetNode(tokens=arms), exclusions)

    # Single-char or single-char ranges → union
    options = [_resolve_arm(a) for a in arms]
    return _attach_exclusions(t.UnionNode(options=options), exclusions)


def _singleton_value(expr: str) -> str | None:
    """Return the single concrete value of `expr` if it has cardinality 1, else None.

    A singleton is τ: a bare literal, or a `{...}` (with an optional exact `[N]`
    count) whose inner expression is itself a singleton. `{a}` is implicitly
    `{a}[1]`, so `{a}[3]` → 'aaa'. Named alphabets, unions, value ranges, and
    range-counts all have cardinality > 1 and yield None. The value is returned
    with escapes resolved (`\\ ` is a literal space, `\\n` a newline, …).
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
    if (
        len(split_top(",", expr)) > 1
        or len(split_top("..", expr)) > 1
        or len(split_top("<->", expr)) > 1
    ):
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
    # `<->` (congruence) is looser than `..` and tighter than `,`: a top-level
    # `<->` zips its operands position-wise into one folded alphabet. Each
    # operand has no top-level `<->`, so the recursion resolves it as a range.
    zip_parts = split_top("<->", arm)
    if len(zip_parts) > 1:
        return t.ZipNode(tracks=[_resolve_arm(p) for p in zip_parts])

    parts = strict_split("..", arm, arm)
    svals = [_singleton_value(p) for p in parts]

    if len(parts) == 1:
        part, sval = parts[0], svals[0]
        if part.startswith("{"):
            if sval is not None:
                # Singleton {…} → literal match of its single value
                return t.LiteralNode(content=sval)
            inner = _alpha(part)
            if isinstance(inner, (t.GroupClassNode, t.ZipNode)):
                # A folded alphabet is already a full class of positions;
                # wrapping it would only restate its greedy-run semantics.
                return inner
            # α — full range (any length, any value in the alphabet)
            return t.FullAlphaNode(inner=inner)
        return t.LiteralNode(content=unescape(part))

    if len(parts) == 2:
        a, b = parts
        av, bv = svals
        if av is not None and bv is not None:
            # τ..τ — character range (single-char) or string range (multi-char)
            if len(av) == 1 and len(bv) == 1:
                return t.CharRangeNode(start=av, end=bv)
            return t.StringRangeNode(start=av, end=bv)
        if av is None and bv is not None:
            return t.ValueRangeNode(alpha=_alpha(a), upper=bv)  # α..τ
        if av is not None and bv is None:
            return t.ValueRangeNode(alpha=_alpha(b), lower=av)  # τ..α
        # α..α — a class-to-class range has no ordering. To fold two classes
        # position-wise, zip them with `<->` (e.g. {a..z}<->{A..Z}).
        raise CompileError(
            f"A class-to-class range is not supported; zip the classes with "
            f"'<->' instead (e.g. {{a..z}}<->{{A..Z}}): got {arm!r}"
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
    m = _COUNT_SRC_REF_RE.match(src)
    if m:
        return t.CountRef(index=int(m.group(1)))
    m = re.fullmatch(r"(\d*)(\.\.)?(\d*)", src)
    if m and (m.group(1) or m.group(2)):
        lo, dots, hi = m.groups()
        if dots:
            return t.CountRange(min=int(lo) if lo else 0, max=int(hi) if hi else None)
        return t.CountRange(min=int(lo), max=int(lo))
    raise CompileError(f"Invalid count expression: [{src}]")
