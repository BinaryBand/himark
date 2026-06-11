"""Phase 3: Semantic resolution — convert phase2 nodes into typed HMK AST nodes.

Transforms:
  brace_group  → literal | char_range | named_alpha | full_alpha |
                 upper_bound | lower_bound | bounded_range | zip_range |
                 union | complement | token_set | group_class | padded
  double_braces → full_match | group_ref | span_ref | count_ref | emoji | latex
  separator    → separator (with parsed count metadata)

A brace group whose content holds a top-level `<<...>>` is not arithmetic — it
encloses a pattern sub-sequence (e.g. `{**<<>>**}`). Such a brace is transparent:
its interior is re-tokenized and spliced into the parent sequence, so inner
constructs capture and number as if the brace were not there.
"""

import re

from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError
from marky.models.node import HMKNode
from marky.models.nodes_adapter import to_legacy
from marky.parser import phase2

# Semantic node kinds that carry an `exclusions` field.
_EXCLUDABLE = (
    t.CharRangeNode,
    t.NamedAlphaNode,
    t.FullAlphaNode,
    t.UpperBoundNode,
    t.LowerBoundNode,
    t.BoundedRangeNode,
    t.UnionNode,
    t.TokenSetNode,
    t.GroupClassNode,
)


def _attach_exclusions(node: t.SemanticNode, exclusions: list[str]) -> t.SemanticNode:
    """Set `exclusions` on a node that supports them; ignore for those that don't."""
    if exclusions and isinstance(node, _EXCLUDABLE):
        node.exclusions = exclusions
    return node


_PADDING_RE = re.compile(r"^(\d*)\s*:\s*(.+)$", re.DOTALL)
_SPAN_RE = re.compile(r"^(\d+(?:\.\d+)?)\.\.(\d+(?:\.\d+)?)$")
_GROUP_RE = re.compile(r"^\d+(?:\.\d+)?$")
_EMOJI_RE = re.compile(r"^:([^:]+):$")
_LATEX_RE = re.compile(r"^\$(.+)\$$", re.DOTALL)
_COUNT_REF_EXPR_RE = re.compile(r"^#(\d+)$")
_COUNT_SRC_REF_RE = re.compile(r"^\{\{#(\d+)\}\}$")


def parse(node: HMKNode) -> HMKNode:
    """Walk the phase2 tree and resolve all construct nodes in place."""
    new_children = []
    for child in node.children:
        if child.type == "brace_group":
            if _has_top_level_separator(child.content):
                # Transparent sub-sequence: splice the re-tokenized interior
                # into the parent so inner constructs number left-to-right
                # as if unwrapped.
                if "count_src" in child.metadata:
                    raise CompileError(
                        f"Count modifier is not supported on a sequence brace: "
                        f"{{{child.content}}}[{child.metadata['count_src']}]"
                    )
                sub = parse(phase2.parse(child.content))
                new_children.extend(sub.children)
                continue
            semantic = to_legacy(_resolve_brace(child.content))
            wrapper = HMKNode("brace_group", child.content, [semantic])
            src = child.metadata.get("count_src")
            if isinstance(src, str):
                wrapper.metadata["count"] = _parse_count(src)
            new_children.append(wrapper)
        elif child.type == "double_braces":
            new_children.append(to_legacy(_parse_template_expr(child.content)))
        elif child.type == "separator":
            src = child.metadata.pop("count_src", None)
            if isinstance(src, str):
                child.metadata["count"] = _parse_count(src)
            _resolve_separator(child)
            new_children.append(child)
        else:
            new_children.append(child)
    node.children = new_children
    return node


# ── Separator resolution ──────────────────────────────────────────────────────


def _resolve_separator(node: HMKNode) -> None:
    """Resolve separator content by cardinality.

    τ (a bare constant or singleton constructor) keeps split semantics — the
    span is split on every occurrence of the constant (`sep_value`). α is an
    arithmetic class — the span must be a member of it (`sep_class`). Empty
    content (`<<>>`) stays an unconstrained span.
    """
    content = node.content
    if not content:
        return

    dot_parts = _split_top("..", content)
    comma_parts = _split_top(",", content)
    has_ops = len(dot_parts) > 1 or len(comma_parts) > 1 or content.startswith("{")

    # τ: bare constant with no arithmetic operators (<<\n>>, << >>, <<abc>>)
    if not has_ops:
        node.metadata["sep_value"] = content
        return

    # τ: singleton constructor ({a}[3] → 'aaa')
    sval = _singleton_value(content)
    if sval is not None:
        node.metadata["sep_value"] = sval
        return

    # Operator chars with empty operands are punctuation constants (<<,>>,
    # <<..>>), not arithmetic.
    if (len(dot_parts) > 1 and any(not p.strip(" \t") for p in dot_parts)) or (
        len(comma_parts) > 1 and any(not p.strip(" \t") for p in comma_parts)
    ):
        node.metadata["sep_value"] = content
        return

    # α: the span is constrained to the class.
    node.metadata["sep_class"] = to_legacy(_resolve_brace(content))


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


def _resolve_brace(content: str) -> t.SemanticNode:
    """Resolve the inner text of a {…} brace group into a typed semantic node."""
    # Padding prefix: {N: expr} or {: expr}
    has_pad = False
    pad_width: int | None = None
    pm = _PADDING_RE.match(content)
    if pm:
        has_pad = True
        pad_str = pm.group(1)
        pad_width = int(pad_str) if pad_str else None
        content = pm.group(2)

    # Complement prefix: {!expr}
    is_complement = content.startswith("!")
    if is_complement:
        content = content[1:]

    # Split on top-level commas. Whitespace is significant — reject leading/trailing
    # spaces on arms unless the arm is purely whitespace (e.g. { } = literal space)
    # or is a single nested-brace arm needing disambiguation space (e.g. { {a..z} }).
    raw_arms = _split_top(",", content)
    arms = []
    for a in raw_arms:
        stripped = a.strip(" \t")
        if stripped == "":
            arms.append(a)  # pure-whitespace: literal space arm
        elif stripped != a:
            if len(raw_arms) == 1 and stripped.startswith("{"):
                arms.append(stripped)  # single nested-brace: disambiguation space
            else:
                raise CompileError(
                    f"Unexpected whitespace in '{{{content}}}': "
                    f"remove spaces around ','"
                )
        else:
            arms.append(a)

    # Separate exclusion arms (!value or !v1..v2)
    include_arms = []
    exclusions: list[str] = []
    for arm in arms:
        if arm.startswith("!"):
            exclusions.append(arm[1:].strip())
        else:
            include_arms.append(arm)

    if not include_arms:
        raise CompileError(f"Empty brace group: {{{content}}}")

    node = _classify_arms(include_arms, exclusions)

    if is_complement:
        node = t.ComplementNode(inner=node)

    if has_pad:
        node = t.PaddedNode(inner=node, width=pad_width)

    return node


def _classify_arms(arms: list[str], exclusions: list[str]) -> t.SemanticNode:
    """Build the appropriate node type for a list of union arms."""
    if len(arms) == 1:
        return _attach_exclusions(_resolve_arm(arms[0]), exclusions)

    # All arms are brace sub-expressions → group_class
    if all(a.startswith("{") for a in arms):
        groups = [_parse_inner_brace_items(a) for a in arms]
        return _attach_exclusions(t.GroupClassNode(groups=groups), exclusions)

    bare_arms = [a for a in arms if not a.startswith("{")]
    brace_arms = [a for a in arms if a.startswith("{")]

    # Mixed brace + bare → union
    if brace_arms:
        options = [_resolve_arm(a) for a in arms]
        return _attach_exclusions(t.UnionNode(options=options), exclusions)

    # All bare — any multi-char token (not a single-char range like a..z, and
    # not a single escaped char like \! )?
    has_multi = any(
        len(a) > 1
        and not (len(a) == 4 and a[1:3] == "..")  # not a..b form
        and not (len(a) == 2 and a.startswith("\\"))  # not an escaped char
        and ".." not in a
        for a in bare_arms
    )
    if has_multi:
        return _attach_exclusions(t.TokenSetNode(tokens=bare_arms), exclusions)

    # Single-char or single-char ranges → union
    options = [_resolve_arm(a) for a in arms]
    return _attach_exclusions(t.UnionNode(options=options), exclusions)


def _parse_inner_brace_items(brace_text: str) -> list[str]:
    """Return the top-level comma-separated items inside a {…} expression."""
    if not (brace_text.startswith("{") and brace_text.endswith("}")):
        raise CompileError(f"Expected brace expression, got: {brace_text!r}")
    items = _split_top("<->", brace_text[1:-1])
    for item in items:
        stripped = item.strip(" \t")
        if stripped and stripped != item:
            raise CompileError(
                f"Unexpected whitespace in {brace_text!r}: remove spaces around '<->'"
            )
    return [s.strip(" \t") or s for s in items]


def _brace_end(expr: str) -> int | None:
    """Index just past the '}' matching the '{' at position 0, or None if unbalanced."""
    depth = 0
    for i, ch in enumerate(expr):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def _inner_of(part: str) -> str:
    """Return the content inside the outer braces of an α part like '{a..z}'."""
    end = _brace_end(part)
    return part[1 : end - 1] if end is not None else part[1:-1]


def _singleton_value(expr: str) -> str | None:
    """Return the single concrete value of `expr` if it has cardinality 1, else None.

    A singleton is τ: a bare literal, or a `{...}` (with an optional exact `[N]`
    count) whose inner expression is itself a singleton. `{a}` is implicitly
    `{a}[1]`, so `{a}[3]` → 'aaa'. Named alphabets, unions, value ranges, and
    range-counts all have cardinality > 1 and yield None.
    """
    expr = expr.strip(" \t")
    if not expr:
        return None
    if expr.startswith("{"):
        end = _brace_end(expr)
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
    if len(_split_top(",", expr)) > 1 or len(_split_top("..", expr)) > 1:
        return None
    return expr


def _resolve_arm(arm: str) -> t.SemanticNode:
    """Resolve one arm (no top-level commas) into a typed node.

    Each `..`-part is classified by cardinality: a singleton (τ) evaluates to its
    one concrete value; anything else is an abstract group (α).
    """
    parts = _split_top("..", arm)
    for p in parts:
        stripped = p.strip(" \t")
        if stripped and stripped != p:
            raise CompileError(
                f"Unexpected whitespace in '{arm}': remove spaces around '..'"
            )
    parts = [p.strip(" \t") or p for p in parts]

    # `<->` (congruence) binds tighter than `..`. If any `..`-part holds a
    # top-level `<->`, the arm is a congruence group or a range of them.
    cong = [_split_top("<->", p) for p in parts]
    if any(len(c) > 1 for c in cong):
        return _resolve_congruence(parts, cong)

    svals = [_singleton_value(p) for p in parts]

    if len(parts) == 1:
        part, sval = parts[0], svals[0]
        if part.startswith("{"):
            if sval is not None:
                # Singleton {…} → literal match of its single value
                return t.LiteralNode(content=sval)
            # α — full range (any length, any value in the alphabet)
            return t.FullAlphaNode(inner=_resolve_brace(_inner_of(part)))
        return t.LiteralNode(content=_unescape(part))

    if len(parts) == 2:
        a, b = parts
        av, bv = svals

        if av is not None and bv is not None:
            # τ..τ — character range (single-char) or string range (multi-char)
            if len(av) == 1 and len(bv) == 1:
                return t.CharRangeNode(start=av, end=bv)
            return t.StringRangeNode(start=av, end=bv)

        if av is None and bv is not None:
            # α..τ — upper bound
            return t.UpperBoundNode(alpha=_resolve_brace(_inner_of(a)), upper=bv)

        if av is not None and bv is None:
            # τ..α — lower bound
            return t.LowerBoundNode(lower=av, alpha=_resolve_brace(_inner_of(b)))

        # α..α — zip range
        return t.ZipRangeNode(
            left=_resolve_brace(_inner_of(a)), right=_resolve_brace(_inner_of(b))
        )

    if len(parts) == 3:
        a, b, c = parts
        av, bv, cv = svals
        # Bounded range must be τ..α..τ — singleton endpoints, abstract middle.
        if av is None or cv is None or bv is not None:
            raise CompileError(
                f"Bounded range must be τ..α..τ (e.g. aa..{{dec}}..zz), got: {arm!r}"
            )
        return t.BoundedRangeNode(
            lower=av, alpha=_resolve_brace(_inner_of(b)), upper=cv
        )

    raise CompileError(f"Too many '..' separators in: {arm!r}")


# ── Congruence (`<->`) resolution ─────────────────────────────────────────────


def _congruence_members(members: list[str]) -> list[str]:
    """Resolve each `<->` member to its singleton value."""
    vals = []
    for m in members:
        sv = _singleton_value(m)
        if sv is None:
            raise CompileError(f"Congruence member must be a singleton or class: {m!r}")
        vals.append(sv)
    return vals


def _congruence_union(members: list[str]) -> t.SemanticNode:
    """Build a union node (or lone literal) from singleton `<->` members."""
    children: list[t.SemanticNode] = [
        t.LiteralNode(content=v) for v in _congruence_members(members)
    ]
    if len(children) == 1:
        return children[0]
    return t.UnionNode(options=children)


def _resolve_congruence(parts: list[str], cong: list[list[str]]) -> t.SemanticNode:
    """Resolve a `<->` congruence arm.

    One part:  `a<->A`            → a single congruence group
               `{a..z}<->{A..Z}`  → a zip of two classes
    Two parts: `a<->A..z<->Z`     → a range of congruence pairs (zip)
    """
    if len(parts) == 1:
        members = cong[0]
        # α<->α — congruence of two classes (zip).
        if len(members) == 2 and all(m.startswith("{") for m in members):
            return t.ZipRangeNode(
                left=_resolve_brace(_inner_of(members[0])),
                right=_resolve_brace(_inner_of(members[1])),
            )
        # Singleton members — one enumerated congruence group.
        return t.GroupClassNode(groups=[_congruence_members(members)])

    if len(parts) == 2:
        # Range of congruence pairs steps both columns in parallel (zip).
        return t.ZipRangeNode(
            left=_congruence_union(cong[0]), right=_congruence_union(cong[1])
        )

    raise CompileError(
        f"Congruence range supports at most two endpoints, got: {parts!r}"
    )


# ── Count parsing ─────────────────────────────────────────────────────────────


def _parse_count(src: str) -> dict:
    """Parse a count modifier string into a count descriptor dict."""
    src = src.strip()
    m = _COUNT_SRC_REF_RE.match(src)
    if m:
        return {"count_ref": int(m.group(1))}
    m = re.match(r"^(\d*)\.\.(\d*)$", src)
    if m:
        lo, hi = m.group(1), m.group(2)
        return {"min": int(lo) if lo else 0, "max": int(hi) if hi else None}
    if re.match(r"^\d+$", src):
        n = int(src)
        return {"min": n, "max": n}
    raise CompileError(f"Invalid count expression: [{src}]")


# ── Template expression parsing ───────────────────────────────────────────────


def _parse_capture_path(dotted: str) -> list[int]:
    return [int(p) for p in dotted.split(".")]


def _parse_template_expr(content: str) -> t.TemplateNode:
    expr = content.strip()

    if expr == ".":
        return t.FullMatchNode()

    m = _COUNT_REF_EXPR_RE.match(expr)
    if m:
        return t.CountRefNode(group=int(m.group(1)))

    m = _SPAN_RE.match(expr)
    if m:
        return t.SpanRefNode(
            start=_parse_capture_path(m.group(1)),
            end=_parse_capture_path(m.group(2)),
        )

    m = _GROUP_RE.match(expr)
    if m:
        return t.GroupRefNode(index=_parse_capture_path(expr))

    m = _EMOJI_RE.match(expr)
    if m:
        return t.EmojiNode(code=m.group(1))

    m = _LATEX_RE.match(expr)
    if m:
        return t.LatexNode(expr=m.group(1))

    raise CompileError(f"Unknown template expression: {{{{{content}}}}}")


# ── Utility ───────────────────────────────────────────────────────────────────


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r"}


def _unescape(s: str) -> str:
    """Resolve backslash escapes in a literal arm (\\!, \\{, \\n, …)."""
    if "\\" not in s:
        return s
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(_ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _split_top(sep: str, text: str) -> list[str]:
    """Split `text` on `sep` only at brace depth 0."""
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    sep_len = len(sep)
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
            cur.append(ch)
            i += 1
        elif ch == "}":
            depth -= 1
            cur.append(ch)
            i += 1
        elif depth == 0 and text[i : i + sep_len] == sep:
            parts.append("".join(cur))
            cur = []
            i += sep_len
        else:
            cur.append(ch)
            i += 1
    parts.append("".join(cur))
    return parts
