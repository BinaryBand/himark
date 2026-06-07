"""Phase 3: Refine leaf node contents based on their parent container type."""

import re
from collections.abc import Callable
from himark.node import HMKNode
from himark.models import CompileError

_SPAN_RE = re.compile(r"^(\d+(?:\.\d+)?)\.\.(\d+(?:\.\d+)?)$")
_GROUP_RE = re.compile(r"^\d+(?:\.\d+)?$")
_EMOJI_RE = re.compile(r"^:([^:]+):$")
_LATEX_RE = re.compile(r"^\$(.+)\$$", re.DOTALL)
_VAR_RE = re.compile(r"^[a-z]$")


def parse(node: HMKNode) -> HMKNode:
    """Walk the tree and refine leaf nodes based on their parent's type.

    Note: options must be refined before children so bracket leaf parsing
    can consult alphabet/modifier options when validating ranges.
    """
    if node.type == "double_brackets":
        if node.metadata.get("options"):
            raise CompileError(
                "Count modifiers are not supported on negation patterns [[...]]"
            )
        # Nested [[: the regex for [[...]] stops at the first ]], so [[[[a]]]]
        # produces content "[[a". Detecting this via content prefix is reliable.
        if node.content.startswith("[["):
            raise CompileError("Negation of negation [[[[...]]]] is not supported")
        for child in node.children:
            if child.type == "double_brackets":
                raise CompileError("Negation of negation [[[[...]]]] is not supported")
    if node.metadata.get("options"):
        node.metadata["options"] = [
            _refine_child(child, parent_type="options")
            for child in node.metadata["options"]
        ]
    node.children = [
        _refine_child(child, parent_type=node.type, parent=node)
        for child in node.children
    ]
    return node


def _refine_child(
    node: HMKNode, parent_type: str, parent: HMKNode | None = None
) -> HMKNode:
    if node.type != "leaf":
        return parse(node)  # recurse into non-leaf nodes

    if parent_type in ("single_brackets", "double_brackets"):
        options = parent.metadata.get("options", []) if parent is not None else []
        return _parse_bracket_leaf(node.content, options=options)

    if parent_type == "options":
        return _parse_options_leaf(node.content)

    if parent_type == "double_braces":
        return _parse_template_expr(node.content)

    if parent_type == "double_chevrons":
        return HMKNode("literal", node.content)
    return node  # root — deferred


def _parse_bracket_leaf(content: str, options: list[HMKNode] | None = None) -> HMKNode:
    arms = content.split("||")
    if len(arms) > 1:
        children = [_parse_range_or_literal(arm) for arm in arms]
        return HMKNode("alternation", content, children)
    return _parse_range_or_literal(content, options=options or [])


_SHORTCUTS = {
    "..": "any_char",  # [..]  — any single character
    "0..": "digits",  # [0..] — one or more decimal digits
    "a..": "word_chars",  # [a..] — one or more word characters [a-zA-Z0-9_]
    " ..": "whitespace",  # [ ..] — one or more whitespace characters
}


def _flatten(opts: list[HMKNode]) -> list[HMKNode]:
    out: list[HMKNode] = []
    for o in opts:
        if o.type == "option_list":
            out.extend(_flatten(o.children))
        else:
            out.append(o)
    return out


def _parse_range_or_literal(
    content: str, options: list[HMKNode] | None = None
) -> HMKNode:
    if content in _SHORTCUTS:
        return HMKNode("shortcut", content, metadata={"kind": _SHORTCUTS[content]})
    if ".." in content:
        parts = content.split("..", 1)
        start, end = parts[0], parts[1]

        flat_options = _flatten(options or [])

        # Open-ended range with no matching shortcut is a compile error
        if not start or not end:
            raise CompileError(
                f"Undefined range shortcut: [{content}]. "
                f"Known open-ended shortcuts: [..], [0..], [a..], [ ..]"
            )

        # Determine if an explicit alphabet option is present; this permits
        # non-digit endpoints when an alphabet like 'hex' is specified.
        explicit_alph = False
        alph_names = {"b10", "dec", "hex", "b16", "b32", "b58", "b64"}
        for opt in flat_options:
            if opt.type == "option" and opt.content in alph_names:
                explicit_alph = True
                break

        # Mixed-type endpoints (one decimal digit endpoint, the other not) are a compile error
        if (start.isdigit() and not end.isdigit()) or (
            end.isdigit() and not start.isdigit()
        ):
            if not explicit_alph:
                raise CompileError(f"Mixed-type range endpoints: {content}")

        # Descending ranges are compile errors unless they trigger cross-case shorthand
        # or an explicit alphabet is given (which has its own ordering, not ASCII order).
        # Cross-case shorthand allowance: left is lowercase ASCII and right is uppercase ASCII
        if start and end and not explicit_alph:
            try:
                if start > end:
                    if not (
                        len(start) == 1
                        and len(end) == 1
                        and start.islower()
                        and end.isupper()
                    ):
                        raise CompileError(f"Descending range endpoints: {content}")
            except TypeError:
                raise CompileError(f"Invalid range endpoints: {content}")

        return HMKNode("range", content, metadata={"start": start, "end": end})
    return HMKNode("literal", content)


def _parse_capture_path(dotted: str) -> list[int]:
    return [int(p) for p in dotted.split(".")]


# Registry of template expression rules evaluated in order.
# Each entry: (node_type, pattern_or_None, metadata_fn(match, expr_str) -> dict)
# pattern=None signals an exact-string sentinel check ("." for full_match).
_TemplateRule = tuple[str, re.Pattern | None, Callable[[re.Match, str], dict]]


def _meta_noop(_m: re.Match, _e: str) -> dict:
    return {}


def _meta_span(m: re.Match, _e: str) -> dict:
    return {
        "start": _parse_capture_path(m.group(1)),
        "end": _parse_capture_path(m.group(2)),
    }


def _meta_group(_m: re.Match, e: str) -> dict:
    return {"index": _parse_capture_path(e)}


def _meta_emoji(m: re.Match, _e: str) -> dict:
    return {"code": m.group(1)}


def _meta_latex(m: re.Match, _e: str) -> dict:
    return {"expr": m.group(1)}


_TEMPLATE_EXPR_RULES: list[_TemplateRule] = [
    ("full_match", None, _meta_noop),
    ("span_ref", _SPAN_RE, _meta_span),
    ("group_ref", _GROUP_RE, _meta_group),
    ("emoji", _EMOJI_RE, _meta_emoji),
    ("latex", _LATEX_RE, _meta_latex),
    ("var_ref", _VAR_RE, _meta_noop),
]


def _parse_template_expr(content: str) -> HMKNode:
    expr = content.strip()
    for node_type, pattern, meta_fn in _TEMPLATE_EXPR_RULES:
        if pattern is None:
            if expr != ".":
                continue
            return HMKNode(node_type, expr)
        m = pattern.match(expr)
        if m:
            return HMKNode(node_type, expr, metadata=meta_fn(m, expr))
    return HMKNode("leaf", content)


def _parse_options_leaf(content: str) -> HMKNode:
    parts = [p.strip() for p in content.split(",")]
    if len(parts) > 1:
        children = [_parse_single_option(p) for p in parts]
        return HMKNode("option_list", content, children)
    return _parse_single_option(content)


def _parse_single_option(content: str) -> HMKNode:
    if content == "?":
        return HMKNode("lazy", content)
    if ".." in content:
        parts = content.split("..", 1)
        return HMKNode(
            "repetition_range", content, metadata={"min": parts[0], "max": parts[1]}
        )
    if content.startswith("pad:"):
        return HMKNode("pad", content, metadata={"width": content[4:]})
    return HMKNode("option", content)
