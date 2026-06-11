from __future__ import annotations


from marky.models.node import HMKNode
from marky.models import nodes_typed as t


SemanticClasses = (
    t.LiteralNode,
    t.CharRangeNode,
    t.NamedAlphaNode,
    t.StringRangeNode,
    t.FullAlphaNode,
    t.UpperBoundNode,
    t.LowerBoundNode,
    t.BoundedRangeNode,
    t.ZipRangeNode,
    t.UnionNode,
    t.ComplementNode,
    t.TokenSetNode,
    t.GroupClassNode,
    t.PaddedNode,
)


def _as_str_list(obj: object) -> list[str]:
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, str)]
    return []


def _as_int_list(obj: object) -> list[int]:
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, int)]
    return []


def _as_groups(obj: object) -> list[list[str]]:
    out: list[list[str]] = []
    if isinstance(obj, list):
        for grp in obj:
            if isinstance(grp, list):
                out.append([x for x in grp if isinstance(x, str)])
    return out


def _as_str(obj: object) -> str | None:
    return obj if isinstance(obj, str) else None


def _str_or_empty(obj: object) -> str:
    return obj if isinstance(obj, str) else ""


def _as_obj_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return {k: v for k, v in value.items() if isinstance(k, str)}
    return None


def _count_to_legacy(count: t.CountSpec | None) -> dict[str, object] | None:
    if count is None:
        return None
    if isinstance(count, t.CountRange):
        return {"min": count.min, "max": count.max}
    return {"count_ref": count.index}


def _count_from_legacy(value: object) -> t.CountSpec | None:
    d = _as_obj_dict(value)
    if d is None:
        return None
    ref_v = d.get("count_ref")
    if isinstance(ref_v, int):
        return t.CountRef(index=ref_v)
    min_v = d.get("min")
    max_v = d.get("max")
    if isinstance(min_v, int) and (isinstance(max_v, int) or max_v is None):
        return t.CountRange(min=min_v, max=max_v)
    return None


def _as_semantic(node: t.Node | None) -> t.SemanticNode | None:
    if node is not None and isinstance(node, SemanticClasses):
        return node
    return None


def to_legacy(node: t.Node) -> HMKNode:
    if isinstance(node, t.RootNode):
        return HMKNode("root", node.content, [to_legacy(ch) for ch in node.children])
    if isinstance(node, t.LeafNode):
        return HMKNode("leaf", node.content)
    if isinstance(node, t.DoubleBracesNode):
        return HMKNode("double_braces", node.content)
    if isinstance(node, t.BraceGroupNode):
        children = [to_legacy(node.semantic)] if node.semantic is not None else []
        meta: dict[str, object] = {}
        c = _count_to_legacy(node.count)
        if c is not None:
            meta["count"] = c
        if node.count_src is not None:
            meta["count_src"] = node.count_src
        return HMKNode("brace_group", node.content, children, meta)
    if isinstance(node, t.SeparatorNode):
        meta: dict[str, object] = {}
        c = _count_to_legacy(node.count)
        if c is not None:
            meta["count"] = c
        if node.count_src is not None:
            meta["count_src"] = node.count_src
        if node.sep_value is not None:
            meta["sep_value"] = node.sep_value
        if node.sep_class is not None:
            meta["sep_class"] = to_legacy(node.sep_class)
        return HMKNode("separator", node.content, metadata=meta)

    if isinstance(node, t.LiteralNode):
        return HMKNode("literal", node.content)
    if isinstance(node, t.CharRangeNode):
        meta: dict[str, object] = {"start": node.start, "end": node.end}
        if node.exclusions:
            meta["exclusions"] = list(node.exclusions)
        return HMKNode("char_range", f"{node.start}..{node.end}", metadata=meta)
    if isinstance(node, t.NamedAlphaNode):
        meta: dict[str, object] = {"name": node.name}
        if node.exclusions:
            meta["exclusions"] = list(node.exclusions)
        return HMKNode("named_alpha", node.name, metadata=meta)
    if isinstance(node, t.StringRangeNode):
        return HMKNode(
            "string_range",
            f"{node.start}..{node.end}",
            metadata={"start": node.start, "end": node.end},
        )
    if isinstance(node, t.FullAlphaNode):
        children = [to_legacy(node.inner)] if node.inner is not None else []
        meta: dict[str, object] = {}
        if node.exclusions:
            meta["exclusions"] = list(node.exclusions)
        return HMKNode("full_alpha", "", children=children, metadata=meta)
    if isinstance(node, t.UpperBoundNode):
        meta: dict[str, object] = {"upper": node.upper}
        if node.alpha is not None:
            meta["alpha"] = to_legacy(node.alpha)
        if node.exclusions:
            meta["exclusions"] = list(node.exclusions)
        return HMKNode("upper_bound", "", metadata=meta)
    if isinstance(node, t.LowerBoundNode):
        meta: dict[str, object] = {"lower": node.lower}
        if node.alpha is not None:
            meta["alpha"] = to_legacy(node.alpha)
        if node.exclusions:
            meta["exclusions"] = list(node.exclusions)
        return HMKNode("lower_bound", "", metadata=meta)
    if isinstance(node, t.BoundedRangeNode):
        meta: dict[str, object] = {"lower": node.lower, "upper": node.upper}
        if node.alpha is not None:
            meta["alpha"] = to_legacy(node.alpha)
        if node.exclusions:
            meta["exclusions"] = list(node.exclusions)
        return HMKNode("bounded_range", "", metadata=meta)
    if isinstance(node, t.ZipRangeNode):
        meta: dict[str, object] = {}
        if node.left is not None:
            meta["left"] = to_legacy(node.left)
        if node.right is not None:
            meta["right"] = to_legacy(node.right)
        return HMKNode("zip_range", "", metadata=meta)
    if isinstance(node, t.UnionNode):
        meta: dict[str, object] = {}
        if node.exclusions:
            meta["exclusions"] = list(node.exclusions)
        return HMKNode(
            "union",
            "",
            children=[to_legacy(ch) for ch in node.options],
            metadata=meta,
        )
    if isinstance(node, t.ComplementNode):
        children = [to_legacy(node.inner)] if node.inner is not None else []
        return HMKNode("complement", "", children=children)
    if isinstance(node, t.TokenSetNode):
        meta: dict[str, object] = {"tokens": list(node.tokens)}
        if node.exclusions:
            meta["exclusions"] = list(node.exclusions)
        return HMKNode("token_set", "", metadata=meta)
    if isinstance(node, t.GroupClassNode):
        meta: dict[str, object] = {"groups": [list(g) for g in node.groups]}
        if node.exclusions:
            meta["exclusions"] = list(node.exclusions)
        return HMKNode("group_class", "", metadata=meta)
    if isinstance(node, t.PaddedNode):
        children = [to_legacy(node.inner)] if node.inner is not None else []
        return HMKNode("padded", "", children=children, metadata={"width": node.width})

    if isinstance(node, t.FullMatchNode):
        return HMKNode("full_match", ".")
    if isinstance(node, t.GroupRefNode):
        return HMKNode("group_ref", "", metadata={"index": list(node.index)})
    if isinstance(node, t.SpanRefNode):
        return HMKNode(
            "span_ref",
            "",
            metadata={"start": list(node.start), "end": list(node.end)},
        )
    if isinstance(node, t.CountRefNode):
        return HMKNode("count_ref", "", metadata={"group": node.group})
    if isinstance(node, t.EmojiNode):
        return HMKNode("emoji", "", metadata={"code": node.code})
    if isinstance(node, t.LatexNode):
        return HMKNode("latex", "", metadata={"expr": node.expr})

    raise ValueError(f"Unsupported typed node: {type(node)!r}")


def from_legacy(node: HMKNode) -> t.Node:
    tpe = node.type

    if tpe == "root":
        return t.RootNode(
            content=node.content, children=[from_legacy(ch) for ch in node.children]
        )
    if tpe == "leaf":
        return t.LeafNode(content=node.content)
    if tpe == "double_braces":
        return t.DoubleBracesNode(content=node.content)
    if tpe == "brace_group":
        semantic = (
            _as_semantic(from_legacy(node.children[0])) if node.children else None
        )
        return t.BraceGroupNode(
            content=node.content,
            semantic=semantic,
            count=_count_from_legacy(node.metadata.get("count")),
            count_src=_as_str(node.metadata.get("count_src")),
        )
    if tpe == "separator":
        sep_class_obj = node.metadata.get("sep_class")
        sep_class = (
            _as_semantic(from_legacy(sep_class_obj))
            if isinstance(sep_class_obj, HMKNode)
            else None
        )
        return t.SeparatorNode(
            content=node.content,
            count=_count_from_legacy(node.metadata.get("count")),
            count_src=_as_str(node.metadata.get("count_src")),
            sep_value=_as_str(node.metadata.get("sep_value")),
            sep_class=sep_class,
        )

    if tpe == "literal":
        return t.LiteralNode(content=node.content)
    if tpe == "char_range":
        return t.CharRangeNode(
            start=_str_or_empty(node.metadata.get("start")),
            end=_str_or_empty(node.metadata.get("end")),
            exclusions=_as_str_list(node.metadata.get("exclusions")),
        )
    if tpe == "named_alpha":
        return t.NamedAlphaNode(
            name=_str_or_empty(node.metadata.get("name")),
            exclusions=_as_str_list(node.metadata.get("exclusions")),
        )
    if tpe == "string_range":
        return t.StringRangeNode(
            start=_str_or_empty(node.metadata.get("start")),
            end=_str_or_empty(node.metadata.get("end")),
        )
    if tpe == "full_alpha":
        inner = _as_semantic(from_legacy(node.children[0])) if node.children else None
        return t.FullAlphaNode(
            inner=inner, exclusions=_as_str_list(node.metadata.get("exclusions"))
        )
    if tpe == "upper_bound":
        alpha_obj = node.metadata.get("alpha")
        alpha = (
            _as_semantic(from_legacy(alpha_obj))
            if isinstance(alpha_obj, HMKNode)
            else None
        )
        return t.UpperBoundNode(
            alpha=alpha,
            upper=_str_or_empty(node.metadata.get("upper")),
            exclusions=_as_str_list(node.metadata.get("exclusions")),
        )
    if tpe == "lower_bound":
        alpha_obj = node.metadata.get("alpha")
        alpha = (
            _as_semantic(from_legacy(alpha_obj))
            if isinstance(alpha_obj, HMKNode)
            else None
        )
        return t.LowerBoundNode(
            lower=_str_or_empty(node.metadata.get("lower")),
            alpha=alpha,
            exclusions=_as_str_list(node.metadata.get("exclusions")),
        )
    if tpe == "bounded_range":
        alpha_obj = node.metadata.get("alpha")
        alpha = (
            _as_semantic(from_legacy(alpha_obj))
            if isinstance(alpha_obj, HMKNode)
            else None
        )
        return t.BoundedRangeNode(
            lower=_str_or_empty(node.metadata.get("lower")),
            alpha=alpha,
            upper=_str_or_empty(node.metadata.get("upper")),
            exclusions=_as_str_list(node.metadata.get("exclusions")),
        )
    if tpe == "zip_range":
        left_obj = node.metadata.get("left")
        right_obj = node.metadata.get("right")
        left = (
            _as_semantic(from_legacy(left_obj))
            if isinstance(left_obj, HMKNode)
            else None
        )
        right = (
            _as_semantic(from_legacy(right_obj))
            if isinstance(right_obj, HMKNode)
            else None
        )
        return t.ZipRangeNode(left=left, right=right)
    if tpe == "union":
        opts = [_as_semantic(from_legacy(ch)) for ch in node.children]
        options = [o for o in opts if o is not None]
        return t.UnionNode(
            options=options, exclusions=_as_str_list(node.metadata.get("exclusions"))
        )
    if tpe == "complement":
        inner = _as_semantic(from_legacy(node.children[0])) if node.children else None
        return t.ComplementNode(inner=inner)
    if tpe == "token_set":
        return t.TokenSetNode(
            tokens=_as_str_list(node.metadata.get("tokens")),
            exclusions=_as_str_list(node.metadata.get("exclusions")),
        )
    if tpe == "group_class":
        groups = _as_groups(node.metadata.get("groups"))
        return t.GroupClassNode(
            groups=groups, exclusions=_as_str_list(node.metadata.get("exclusions"))
        )
    if tpe == "padded":
        inner = _as_semantic(from_legacy(node.children[0])) if node.children else None
        width_obj = node.metadata.get("width")
        width = width_obj if isinstance(width_obj, int) or width_obj is None else None
        return t.PaddedNode(inner=inner, width=width)

    if tpe == "full_match":
        return t.FullMatchNode()
    if tpe == "group_ref":
        return t.GroupRefNode(index=_as_int_list(node.metadata.get("index")))
    if tpe == "span_ref":
        start_v = _as_int_list(node.metadata.get("start"))
        end_v = _as_int_list(node.metadata.get("end"))
        return t.SpanRefNode(start=start_v, end=end_v)
    if tpe == "count_ref":
        grp = node.metadata.get("group")
        return t.CountRefNode(group=grp if isinstance(grp, int) else 0)
    if tpe == "emoji":
        code = node.metadata.get("code")
        return t.EmojiNode(code=code if isinstance(code, str) else "")
    if tpe == "latex":
        expr = node.metadata.get("expr")
        return t.LatexNode(expr=expr if isinstance(expr, str) else "")

    raise ValueError(f"Unsupported legacy node type: {tpe!r}")
