"""Phase 3: Refine leaf node contents based on their parent container type."""

from himark.node import HMKNode


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

    return node  # double_braces, double_chevrons, root — deferred


def _parse_bracket_leaf(content: str) -> HMKNode:
    arms = content.split("||")
    if len(arms) > 1:
        children = [_parse_range_or_literal(arm) for arm in arms]
        return HMKNode("alternation", content, children)
    return _parse_range_or_literal(content)


def _parse_range_or_literal(content: str) -> HMKNode:
    if ".." in content:
        parts = content.split("..", 1)
        return HMKNode("range", content, metadata={"start": parts[0], "end": parts[1]})
    return HMKNode("literal", content)


def _parse_options_leaf(content: str) -> HMKNode:
    parts = [p.strip() for p in content.split(",")]
    if len(parts) > 1:
        children = [_parse_single_option(p) for p in parts]
        return HMKNode("option_list", content, children)
    return _parse_single_option(content)


def _parse_single_option(content: str) -> HMKNode:
    if ".." in content:
        parts = content.split("..", 1)
        return HMKNode("repetition_range", content, metadata={"min": parts[0], "max": parts[1]})
    if content.startswith("pad:"):
        return HMKNode("pad", content, metadata={"width": content[4:]})
    return HMKNode("option", content)
