"""Render a template step (the right-hand side of `=>`) against a match.

Each template node is dispatched by class through a small registry (the node
set is tiny, so a compile step would be overkill). `full_match_override`
carries the deferred `{{.}}` value when rendering mid-chain.
"""

from collections.abc import Callable

from marky.engine._types import Match
from marky.models import nodes_typed as t
from marky.utils.resolver import RESOLVERS as _RESOLVERS


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
    return str(match.count_refs.get(node.group, 0))


def _emoji(node: t.EmojiNode, _match: Match) -> str:
    r = _RESOLVERS.get("emoji")
    return r(node.code) if r else f":{node.code}:"


def _latex(node: t.LatexNode, _match: Match) -> str:
    r = _RESOLVERS.get("latex")
    return r(node.expr) if r else node.expr


# Class-keyed dispatch — no node.type strings, no silent isinstance fallbacks.
_RENDERERS: dict[type, Callable[..., str]] = {
    t.FullMatchNode: _full_match,
    t.GroupRefNode: _group_ref,
    t.SpanRefNode: _span_ref,
    t.CountRefNode: _count_ref,
    t.EmojiNode: _emoji,
    t.LatexNode: _latex,
}


def is_template(tree: t.RootNode) -> bool:
    """True if `tree` is a template step (renders output) rather than a matcher.

    A step is a template when it contains any template-expression node
    (`{{.}}`, `{{N}}`, `{{#N}}`, …). Pattern steps contain only matchable
    constructs (brace groups, separators) and literal leaves.
    """
    return any(t.is_template(n) for n in tree.children)


def render(
    template_tree: t.RootNode,
    match: Match,
    full_match_override: str | None = None,
) -> str:
    """Render a template against a match.

    `full_match_override` supplies the deferred value for `{{.}}` in a chained
    template — the result of applying the remaining chain to the current match.
    When None, `{{.}}` resolves to the raw matched text.
    """
    parts: list[str] = []
    for node in template_tree.children:
        if isinstance(node, t.LeafNode):
            parts.append(node.content)
        elif isinstance(node, t.FullMatchNode) and full_match_override is not None:
            parts.append(full_match_override)
        else:
            renderer = _RENDERERS.get(type(node))
            if renderer is not None:
                parts.append(renderer(node, match))
    return "".join(parts)
