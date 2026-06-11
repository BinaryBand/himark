from collections.abc import Callable

from marky.engine._types import Match
from marky.models import nodes_typed as t
from marky.utils.resolver import RESOLVERS as _RESOLVERS

_TEMPLATE_NODE_TYPES = frozenset(
    {
        "full_match",
        "group_ref",
        "span_ref",
        "count_ref",
        "emoji",
        "latex",
    }
)


def _render_full_match(expr: t.Node, match: Match) -> str:
    return match.text


def _render_group_ref(expr: t.Node, match: Match) -> str:
    if not isinstance(expr, t.GroupRefNode):
        return ""
    path = expr.index
    g_idx = path[0]  # 0-based
    if len(path) == 1:
        return match.groups[g_idx] if g_idx < len(match.groups) else ""
    s_idx = path[1]
    subs = match.sub_groups[g_idx] if g_idx < len(match.sub_groups) else []
    return subs[s_idx] if s_idx < len(subs) else ""


def _render_span_ref(expr: t.Node, match: Match) -> str:
    if not isinstance(expr, t.SpanRefNode):
        return ""
    s_idx = expr.start[0]  # 0-based
    e_idx = expr.end[0]
    if s_idx < len(match.group_spans) and e_idx < len(match.group_spans):
        s = match.group_spans[s_idx][0]
        e = match.group_spans[e_idx][1]
        return match.text[s:e]
    return ""


def _render_count_ref(expr: t.Node, match: Match) -> str:
    if not isinstance(expr, t.CountRefNode):
        return ""
    return str(match.count_refs.get(expr.group, 0))


def _render_emoji(expr: t.Node, _match: Match) -> str:
    if not isinstance(expr, t.EmojiNode):
        return ""
    code = expr.code
    r = _RESOLVERS.get("emoji")
    return r.resolve(code) if r else f":{code}:"


def _render_latex(expr: t.Node, _match: Match) -> str:
    if not isinstance(expr, t.LatexNode):
        return ""
    expr_str = expr.expr
    r = _RESOLVERS.get("latex")
    return r.resolve(expr_str) if r else expr_str


_EXPR_RENDERERS: dict[str, Callable[[t.Node, Match], str]] = {
    "full_match": _render_full_match,
    "group_ref": _render_group_ref,
    "span_ref": _render_span_ref,
    "count_ref": _render_count_ref,
    "emoji": _render_emoji,
    "latex": _render_latex,
}


def is_template(tree: t.RootNode) -> bool:
    """True if `tree` is a template step (renders output) rather than a matcher.

    A step is a template when it contains any template-expression node
    (`{{.}}`, `{{N}}`, `{{#N}}`, …). Pattern steps contain only matchable
    constructs (brace groups, separators) and literal leaves.
    """
    return any(n.type in _TEMPLATE_NODE_TYPES for n in tree.children)


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
    parts = []
    for node in template_tree.children:
        if isinstance(node, t.LeafNode):
            parts.append(node.content)
        elif isinstance(node, t.FullMatchNode) and full_match_override is not None:
            parts.append(full_match_override)
        elif node.type in _TEMPLATE_NODE_TYPES:
            renderer = _EXPR_RENDERERS.get(node.type)
            if renderer is not None:
                parts.append(renderer(node, match))
    return "".join(parts)
