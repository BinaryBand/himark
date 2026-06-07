"""Phase 2: Tokenize an HMK pattern string into an HMKNode tree."""

import re
from himark.node import HMKNode

_parenthesis = r"\(([^)]+)\)"
_single_brackets = r"\[((?:[^\]\\]|\\.)+)\]"
_double_brackets = r"\[\[((?:[^\]\\]|\\.)+)\]\]"
_brackets = f"{_double_brackets}|{_single_brackets}"
_brackets_with_opts = f"{_brackets}(?:{_parenthesis})?"
_double_chevrons = r"<<((?:[^>]|>[^>])*)>>"
_double_braces = r"{{((?:[^}]|}[^}])*)}}"

_PATTERN = re.compile(
    f"{_brackets_with_opts}|{_double_chevrons}|{_double_braces}"
)

# Maps regex group index → node type (group 3 is options, handled separately)
_GROUP_TYPES = ["double_brackets", "single_brackets", "options", "double_chevrons", "double_braces"]


def parse(text: str) -> HMKNode:
    """Recursively tokenize HMK text into an AST."""
    nodes = []
    pos = 0
    leaf_start = None

    while pos < len(text):
        match = _PATTERN.match(text, pos)
        if not match:
            if leaf_start is None:
                leaf_start = pos
            pos += 1
            continue

        if leaf_start is not None:
            nodes.append(HMKNode("leaf", text[leaf_start:pos]))
            leaf_start = None

        if match.start() > pos:
            nodes.append(HMKNode("leaf", text[pos:match.start()]))

        groups = match.groups()
        matched_idx = next(i for i, g in enumerate(groups) if g is not None)
        node_type = _GROUP_TYPES[matched_idx]
        content = groups[matched_idx]

        node = HMKNode(node_type, content, parse(content).children)

        if matched_idx == 1 and groups[2]:  # single_brackets with options
            node.metadata["options"] = parse(groups[2]).children

        nodes.append(node)
        pos = match.end()

    if leaf_start is not None:
        nodes.append(HMKNode("leaf", text[leaf_start:]))

    return HMKNode("root", text, nodes or [HMKNode("leaf", text)])
