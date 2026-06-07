"""Phase 3: Refine leaf node contents based on their parent container type."""

import re
from himark.node import HMKNode

_SPAN_RE  = re.compile(r"^(\d+(?:\.\d+)?)\.\.(\d+(?:\.\d+)?)$")
_GROUP_RE = re.compile(r"^\d+(?:\.\d+)?$")
_EMOJI_RE = re.compile(r"^:([^:]+):$")
_LATEX_RE = re.compile(r"^\$(.+)\$$", re.DOTALL)
_VAR_RE   = re.compile(r"^[a-z]$")


def parse(node: HMKNode) -> HMKNode:
    """Walk the tree and refine leaf nodes based on their parent's type."""
    node.children = [_refine_child(child, parent_type=node.type) for child in node.children]
    if node.metadata.get("options"):
        node.metadata["options"] = [
            _refine_child(child, parent_type="options")
            for child in node.metadata["options"]
        ]
    return node


def _refine_child(node: HMKNode, parent_type: str) -> HMKNode:
    if node.type != "leaf":
        return parse(node)  # recurse into non-leaf nodes

    if parent_type in ("single_brackets", "double_brackets"):
        return _parse_bracket_leaf(node.content)

    if parent_type == "options":
        return _parse_options_leaf(node.content)

    if parent_type == "double_braces":
        return _parse_template_expr(node.content)

    if parent_type == "double_chevrons":
        return HMKNode("literal", node.content)
    return node  # root — deferred


def _parse_bracket_leaf(content: str) -> HMKNode:
    arms = content.split("||")
    if len(arms) > 1:
        children = [_parse_range_or_literal(arm) for arm in arms]
        return HMKNode("alternation", content, children)
    return _parse_range_or_literal(content)


_SHORTCUTS = {
    "..":  "any_char",    # [..]  — any single character
    "0..": "digits",      # [0..] — one or more decimal digits
    "a..": "word_chars",  # [a..] — one or more word characters [a-zA-Z0-9_]
    " ..": "whitespace",  # [ ..] — one or more whitespace characters
}


def _parse_range_or_literal(content: str) -> HMKNode:
    if content in _SHORTCUTS:
        return HMKNode("shortcut", content, metadata={"kind": _SHORTCUTS[content]})
    if ".." in content:
        parts = content.split("..", 1)
        return HMKNode("range", content, metadata={"start": parts[0], "end": parts[1]})
    return HMKNode("literal", content)


def _parse_capture_path(dotted: str) -> list[int]:
    return [int(p) for p in dotted.split(".")]


def _parse_template_expr(content: str) -> HMKNode:
    expr = content.strip()
    if expr == ".":
        return HMKNode("full_match", expr)
    if m := _SPAN_RE.match(expr):
        return HMKNode("span_ref", expr, metadata={
            "start": _parse_capture_path(m.group(1)),
            "end":   _parse_capture_path(m.group(2)),
        })
    if _GROUP_RE.match(expr):
        return HMKNode("group_ref", expr, metadata={"index": _parse_capture_path(expr)})
    if m := _EMOJI_RE.match(expr):
        return HMKNode("emoji", expr, metadata={"code": m.group(1)})
    if m := _LATEX_RE.match(expr):
        return HMKNode("latex", expr, metadata={"expr": m.group(1)})
    if _VAR_RE.match(expr):
        return HMKNode("var_ref", expr)
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
        return HMKNode("repetition_range", content, metadata={"min": parts[0], "max": parts[1]})
    if content.startswith("pad:"):
        return HMKNode("pad", content, metadata={"width": content[4:]})
    return HMKNode("option", content)
