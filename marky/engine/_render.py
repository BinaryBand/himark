"""Render a template step (the right-hand side of `=>`) against a match.

Each template node is dispatched by class through a small registry. A chained
template forwards its references through the rest of the chain in
`engine/__init__.py` (the reference conveyor); rendering here is always a plain
node-by-node concatenation against one `Match`.
"""

from collections.abc import Callable

from marky.engine._types import Match
from marky.models import nodes_typed as t


def _full_match(node: t.FullMatchNode, match: Match) -> str:
    return match.text


def _group_ref(node: t.GroupRefNode, match: Match) -> str:
    g_idx = node.index[0]  # 0-based
    if len(node.index) == 1:
        return match.groups[g_idx] if g_idx < len(match.groups) else ""
    s_idx = node.index[1]
    subs = match.sub_groups[g_idx] if g_idx < len(match.sub_groups) else []
    return subs[s_idx] if s_idx < len(subs) else ""


def _span_ref(node: t.SpanRefNode, match: Match) -> str:
    s_idx, e_idx = node.start[0], node.end[0]  # 0-based
    spans = match.group_spans
    if s_idx < len(spans) and e_idx < len(spans):
        return match.text[spans[s_idx][0] : spans[e_idx][1]]
    return ""


def _count_ref(node: t.CountRefNode, match: Match) -> str:
    """Repeat count of the capture at `index` — a path into the capture tree, so
    `{{#N}}` is a top-level group's count and `{{#N.M}}` is sub-group M's count."""
    caps = match.captures
    cap = None
    for i in node.index:
        if i >= len(caps):
            return "0"
        cap = caps[i]
        caps = cap.subs
    return str(len(cap.reps)) if cap is not None else "0"


# Class-keyed dispatch — no node.type strings, no silent isinstance fallbacks.
_RENDERERS: dict[type, Callable[..., str]] = {
    t.FullMatchNode: _full_match,
    t.GroupRefNode: _group_ref,
    t.SpanRefNode: _span_ref,
    t.CountRefNode: _count_ref,
}


def is_template(tree: t.RootNode) -> bool:
    """True if `tree` is a template step (renders output) rather than a matcher.

    A step is a template when it contains any template-expression node
    (`{{.}}`, `{{N}}`, `{{#N}}`, …) — or nothing but literal leaves, which makes
    it a constant template (`{\\<} =>+ &lt;`). Pattern steps are marked by their
    matchable brace groups.
    """
    return any(t.is_template(n) for n in tree.children) or all(
        isinstance(n, t.LeafNode) for n in tree.children
    )


def render(template_tree: t.RootNode, match: Match) -> str:
    """Render a template against a match: literal leaves verbatim, reference
    nodes through their registered renderer, concatenated in order."""
    parts: list[str] = []
    for node in template_tree.children:
        if isinstance(node, t.LeafNode):
            parts.append(node.content)
        else:
            renderer = _RENDERERS.get(type(node))
            if renderer is not None:
                parts.append(renderer(node, match))
    return "".join(parts)
