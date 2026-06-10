from collections.abc import Callable

from marky.engine._types import Match
from marky.models.node import HMKNode
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


def _render_full_match(expr: HMKNode, match: Match) -> str:
    return match.text


def _render_group_ref(expr: HMKNode, match: Match) -> str:
    path = expr.metadata["index"]
    g_idx = path[0]  # 0-based
    if len(path) == 1:
        return match.groups[g_idx] if g_idx < len(match.groups) else ""
    s_idx = path[1]
    subs = match.sub_groups[g_idx] if g_idx < len(match.sub_groups) else []
    return subs[s_idx] if s_idx < len(subs) else ""


def _render_span_ref(expr: HMKNode, match: Match) -> str:
    s_idx = expr.metadata["start"][0]  # 0-based
    e_idx = expr.metadata["end"][0]
    if s_idx < len(match.group_spans) and e_idx < len(match.group_spans):
        s = match.group_spans[s_idx][0]
        e = match.group_spans[e_idx][1]
        return match.text[s:e]
    return ""


def _render_count_ref(expr: HMKNode, match: Match) -> str:
    return str(match.count_refs.get(expr.metadata["group"], 0))


def _render_emoji(expr: HMKNode, _match: Match) -> str:
    r = _RESOLVERS.get("emoji")
    return (
        r.resolve(expr.metadata[r.metadata_key]) if r else f":{expr.metadata['code']}:"
    )


def _render_latex(expr: HMKNode, _match: Match) -> str:
    r = _RESOLVERS.get("latex")
    return r.resolve(expr.metadata[r.metadata_key]) if r else expr.metadata["expr"]


_EXPR_RENDERERS: dict[str, Callable[[HMKNode, Match], str]] = {
    "full_match": _render_full_match,
    "group_ref": _render_group_ref,
    "span_ref": _render_span_ref,
    "count_ref": _render_count_ref,
    "emoji": _render_emoji,
    "latex": _render_latex,
}


def render(template_tree: HMKNode, match: Match) -> str:
    parts = []
    for node in template_tree.children:
        if node.type == "leaf":
            parts.append(node.content)
        elif node.type in _TEMPLATE_NODE_TYPES:
            renderer = _EXPR_RENDERERS.get(node.type)
            if renderer is not None:
                parts.append(renderer(node, match))
    return "".join(parts)
