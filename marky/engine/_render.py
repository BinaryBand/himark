from collections.abc import Callable

from marky.engine._types import Match
from marky.models.node import HMKNode
from marky.utils.resolver import RESOLVERS as _RESOLVERS


def _render_full_match(expr: HMKNode, match: Match) -> str:
    return match.text


def _render_group_ref(expr: HMKNode, match: Match) -> str:
    path = expr.metadata["index"]
    g_idx = path[0] - 1
    if len(path) == 1:
        return match.groups[g_idx] if g_idx < len(match.groups) else ""
    s_idx = path[1] - 1
    subs = match.sub_groups[g_idx] if g_idx < len(match.sub_groups) else []
    return subs[s_idx] if s_idx < len(subs) else ""


def _render_span_ref(expr: HMKNode, match: Match) -> str:
    s_idx = expr.metadata["start"][0] - 1
    e_idx = expr.metadata["end"][0] - 1
    if s_idx < len(match.group_spans) and e_idx < len(match.group_spans):
        s = match.group_spans[s_idx][0]
        e = match.group_spans[e_idx][1]
        return match.text[s:e]
    return ""


def _render_var_ref(expr: HMKNode, match: Match) -> str:
    val = match.bindings.get(expr.content)
    return str(val) if val is not None else ""


_EXPR_RENDERERS: dict[str, Callable[[HMKNode, Match], str]] = {
    "full_match": _render_full_match,
    "group_ref": _render_group_ref,
    "span_ref": _render_span_ref,
    "var_ref": _render_var_ref,
}


def render(template_tree: HMKNode, match: Match) -> str:
    parts = []
    for node in template_tree.children:
        if node.type == "leaf":
            parts.append(node.content)
        elif node.type == "double_braces" and node.children:
            expr = node.children[0]
            renderer = _EXPR_RENDERERS.get(expr.type)
            if renderer is not None:
                parts.append(renderer(expr, match))
            elif expr.type in _RESOLVERS:
                r = _RESOLVERS[expr.type]
                parts.append(r.resolve(expr.metadata[r.metadata_key]))
    return "".join(parts)
