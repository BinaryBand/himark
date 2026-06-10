"""Phase 2: Tokenize an HMK pattern string into an HMKNode tree."""

import re

from himark.models.node import HMKNode

_parenthesis = r"\(([^)]+)\)"
_single_brackets = r"\[((?:[^\]\\]|\\.)+)\]"
_double_brackets = r"\[\[((?:[^\]\\]|\\.)+)\]\]"
_brackets = f"{_double_brackets}|{_single_brackets}"
_double_chevrons = r"<<((?:[^>]|>[^>])*)>>"
_double_braces = r"{{(?!\{)((?:[^}]|}[^}])*)}}"

_PATTERN = re.compile(f"{_brackets}|{_double_chevrons}|{_double_braces}")
_OPTION_GROUP = re.compile(_parenthesis)

# Maps regex group index → node type
_GROUP_TYPES = [
    "double_brackets",
    "single_brackets",
    "double_chevrons",
    "double_braces",
]


def parse(text: str) -> HMKNode:
    """Recursively tokenize HMK text into an AST."""
    nodes = []
    pos = 0
    leaf_start = None

    while pos < len(text):
        # Handle top-level escapes for recognized sequences only.
        # Unrecognized \x sequences fall through so \ is treated as a literal char.
        if text[pos] == "\\" and pos + 1 < len(text):
            esc = text[pos + 1]
            if esc == "n":
                repl: str | None = "\n"
            elif esc == "t":
                repl = "\t"
            elif esc == "r":
                repl = "\r"
            elif esc in r"\[]{}<>^$":
                repl = esc
            else:
                repl = None  # unrecognized — treat \ as a literal char
            if repl is not None:
                if leaf_start is not None:
                    nodes.append(HMKNode("leaf", text[leaf_start:pos]))
                    leaf_start = None
                nodes.append(HMKNode("leaf", repl))
                pos += 2
                continue

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
            nodes.append(HMKNode("leaf", text[pos : match.start()]))

        groups = match.groups()
        matched_idx = next(i for i, g in enumerate(groups) if g is not None)
        node_type = _GROUP_TYPES[matched_idx]
        content = groups[matched_idx]

        node = HMKNode(node_type, content, parse(content).children)

        if node_type in ("single_brackets", "double_brackets"):
            # Consume one or more trailing option groups, e.g. [a](hex)(1..)
            # Whitespace between the bracket and an option group is insignificant.
            option_pos = match.end()
            option_nodes = []
            while True:
                # Peek past insignificant whitespace before the next option group
                peek_pos = option_pos
                while peek_pos < len(text) and text[peek_pos] in " \t":
                    peek_pos += 1
                opt_match = _OPTION_GROUP.match(text, peek_pos)
                if not opt_match:
                    break
                option_nodes.extend(parse(opt_match.group(1)).children)
                option_pos = opt_match.end()
            if option_nodes:
                node.metadata["options"] = option_nodes
            pos = option_pos
        else:
            pos = match.end()

        nodes.append(node)

    if leaf_start is not None:
        nodes.append(HMKNode("leaf", text[leaf_start:]))

    return HMKNode("root", text, nodes or [HMKNode("leaf", text)])
