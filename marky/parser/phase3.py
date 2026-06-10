"""Phase 3: Semantic resolution — convert phase2 nodes into typed HMK AST nodes.

Transforms:
  brace_group  → literal | char_range | named_alpha | full_alpha |
                 upper_bound | lower_bound | bounded_range | zip_range |
                 union | complement | token_set | group_class | padded
  double_braces → full_match | group_ref | span_ref | count_ref | emoji | latex
  separator    → separator (with parsed count metadata)
"""

import re

from marky.models.exceptions import CompileError
from marky.models.node import HMKNode
from marky.utils.alphabet import is_named_alpha

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
            semantic = _resolve_brace(child.content)
            wrapper = HMKNode("brace_group", child.content, [semantic])
            if "count_src" in child.metadata:
                wrapper.metadata["count"] = _parse_count(child.metadata["count_src"])
            new_children.append(wrapper)
        elif child.type == "double_braces":
            new_children.append(_parse_template_expr(child.content))
        elif child.type == "separator":
            if "count_src" in child.metadata:
                child.metadata["count"] = _parse_count(child.metadata.pop("count_src"))
            new_children.append(child)
        else:
            new_children.append(child)
    node.children = new_children
    return node


# ── Brace resolution ─────────────────────────────────────────────────────────


def _resolve_brace(content: str) -> HMKNode:
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

    # Split on top-level commas; preserve purely-whitespace arms (e.g. { } = literal space)
    arms = [a.strip(" \t") or a for a in _split_top(",", content)]

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
        node = HMKNode("complement", content, [node])

    if has_pad:
        node = HMKNode("padded", content, [node], {"width": pad_width})

    return node


def _classify_arms(arms: list[str], exclusions: list[str]) -> HMKNode:
    """Build the appropriate node type for a list of union arms."""
    if len(arms) == 1:
        node = _resolve_arm(arms[0])
        if exclusions:
            node.metadata["exclusions"] = exclusions
        return node

    # All arms are brace sub-expressions → group_class
    if all(a.startswith("{") for a in arms):
        groups = [_parse_inner_brace_items(a) for a in arms]
        node = HMKNode("group_class", ",".join(arms), metadata={"groups": groups})
        if exclusions:
            node.metadata["exclusions"] = exclusions
        return node

    bare_arms = [a for a in arms if not a.startswith("{")]
    brace_arms = [a for a in arms if a.startswith("{")]

    # Mixed brace + bare → union
    if brace_arms:
        children = [_resolve_arm(a) for a in arms]
        node = HMKNode("union", ",".join(arms), children)
        if exclusions:
            node.metadata["exclusions"] = exclusions
        return node

    # All bare — any multi-char token (not a single-char range like a..z)?
    has_multi = any(
        len(a) > 1
        and not (len(a) == 4 and a[1:3] == "..")  # not a..b form
        and ".." not in a
        for a in bare_arms
    )
    if has_multi:
        node = HMKNode("token_set", ",".join(arms), metadata={"tokens": bare_arms})
        if exclusions:
            node.metadata["exclusions"] = exclusions
        return node

    # Single-char or single-char ranges → union
    children = [_resolve_arm(a) for a in arms]
    node = HMKNode("union", ",".join(arms), children)
    if exclusions:
        node.metadata["exclusions"] = exclusions
    return node


def _parse_inner_brace_items(brace_text: str) -> list[str]:
    """Return the top-level comma-separated items inside a {…} expression."""
    if not (brace_text.startswith("{") and brace_text.endswith("}")):
        raise CompileError(f"Expected brace expression, got: {brace_text!r}")
    return [s.strip(" \t") for s in _split_top(",", brace_text[1:-1])]


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
    if is_named_alpha(expr):
        return None
    if len(_split_top(",", expr)) > 1 or len(_split_top("..", expr)) > 1:
        return None
    return expr


def _resolve_arm(arm: str) -> HMKNode:
    """Resolve one arm (no top-level commas) into a typed node.

    Each `..`-part is classified by cardinality: a singleton (τ) evaluates to its
    one concrete value; anything else is an abstract group (α).
    """
    parts = [p.strip(" \t") or p for p in _split_top("..", arm)]
    svals = [_singleton_value(p) for p in parts]

    if len(parts) == 1:
        part, sval = parts[0], svals[0]
        if part.startswith("{"):
            if sval is not None:
                # Singleton {…} → literal match of its single value
                return HMKNode("literal", sval)
            # α — full range (any length, any value in the alphabet)
            return HMKNode("full_alpha", arm, [_resolve_brace(_inner_of(part))])
        if is_named_alpha(part):
            return HMKNode("named_alpha", part, metadata={"name": part})
        return HMKNode("literal", part)

    if len(parts) == 2:
        a, b = parts
        av, bv = svals

        if av is not None and bv is not None:
            # τ..τ — character range (single-char) or string range (multi-char)
            if len(av) == 1 and len(bv) == 1:
                return HMKNode("char_range", arm, metadata={"start": av, "end": bv})
            return HMKNode("string_range", arm, metadata={"start": av, "end": bv})

        if av is None and bv is not None:
            # α..τ — upper bound
            alpha_node = _resolve_brace(_inner_of(a))
            return HMKNode(
                "upper_bound", arm, metadata={"alpha": alpha_node, "upper": bv}
            )

        if av is not None and bv is None:
            # τ..α — lower bound
            alpha_node = _resolve_brace(_inner_of(b))
            return HMKNode(
                "lower_bound", arm, metadata={"lower": av, "alpha": alpha_node}
            )

        # α..α — zip range
        left = _resolve_brace(_inner_of(a))
        right = _resolve_brace(_inner_of(b))
        return HMKNode("zip_range", arm, metadata={"left": left, "right": right})

    if len(parts) == 3:
        a, b, c = parts
        av, bv, cv = svals
        # Bounded range must be τ..α..τ — singleton endpoints, abstract middle.
        if av is None or cv is None or bv is not None:
            raise CompileError(
                f"Bounded range must be τ..α..τ (e.g. aa..{{dec}}..zz), got: {arm!r}"
            )
        alpha_node = _resolve_brace(_inner_of(b))
        return HMKNode(
            "bounded_range",
            arm,
            metadata={"lower": av, "alpha": alpha_node, "upper": cv},
        )

    raise CompileError(f"Too many '..' separators in: {arm!r}")


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


def _parse_template_expr(content: str) -> HMKNode:
    expr = content.strip()

    if expr == ".":
        return HMKNode("full_match", expr)

    m = _COUNT_REF_EXPR_RE.match(expr)
    if m:
        return HMKNode("count_ref", expr, metadata={"group": int(m.group(1))})

    m = _SPAN_RE.match(expr)
    if m:
        return HMKNode(
            "span_ref",
            expr,
            metadata={
                "start": _parse_capture_path(m.group(1)),
                "end": _parse_capture_path(m.group(2)),
            },
        )

    m = _GROUP_RE.match(expr)
    if m:
        return HMKNode("group_ref", expr, metadata={"index": _parse_capture_path(expr)})

    m = _EMOJI_RE.match(expr)
    if m:
        return HMKNode("emoji", expr, metadata={"code": m.group(1)})

    m = _LATEX_RE.match(expr)
    if m:
        return HMKNode("latex", expr, metadata={"expr": m.group(1)})

    raise CompileError(f"Unknown template expression: {{{{{content}}}}}")


# ── Utility ───────────────────────────────────────────────────────────────────


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
