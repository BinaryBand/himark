"""Phase 2: Tokenize an HMK pattern string into an HMKNode tree.

Constructs recognized:
  {expr}[count]   — brace_group with optional count modifier
  <<sep>>[count]  — separator with optional count modifier
  {{ref}}         — template reference (double-brace, passed through)
  leaf text       — verbatim literal fragments
"""

import re

from marky.models.exceptions import CompileError
from marky.models.node import HMKNode

# Template refs: {{.}}, {{0}}, {{0.1}}, {{0..2}}, {{#0}} — double-brace, no braces
# inside (so {{a..z}..{A..Z}} stays a brace group, not a template ref).
_TEMPLATE_REF = re.compile(r"\{\{([^{}]*)\}\}")

# Count suffix: [N], [N..], [..N], [N..M], [..]  (also allows {{#N}})
_COUNT_SRC = re.compile(r"\[([^\]]*)\]")


def _scan_braces(text: str, pos: int) -> int:
    """Return the end index (exclusive) of the brace group starting at pos."""
    depth = 0
    for i in range(pos, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        if depth == 0:
            return i + 1
    raise CompileError(f"Unclosed '{{' at position {pos}")


def _scan_chevrons(text: str, pos: int) -> int:
    """Return end index (exclusive) of <<...>> starting at pos (past the opening <<)."""
    end = text.find(">>", pos)
    if end == -1:
        raise CompileError(f"Unclosed '<<' at position {pos - 2}")
    return end + 2


def parse(text: str) -> HMKNode:
    """Tokenize HMK pattern text into an HMKNode tree."""
    nodes: list[HMKNode] = []
    pos = 0
    leaf_buf: list[str] = []

    def flush_leaf():
        if leaf_buf:
            nodes.append(HMKNode("leaf", "".join(leaf_buf)))
            leaf_buf.clear()

    while pos < len(text):
        ch = text[pos]

        # Escape sequences
        if ch == "\\" and pos + 1 < len(text):
            esc = text[pos + 1]
            mapping = {
                "n": "\n",
                "t": "\t",
                "r": "\r",
                "\\": "\\",
                "{": "{",
                "}": "}",
                "<": "<",
                ">": ">",
            }
            if esc in mapping:
                flush_leaf()
                nodes.append(HMKNode("leaf", mapping[esc]))
                pos += 2
                continue
            # unrecognized escape — treat \ as literal
            leaf_buf.append(ch)
            pos += 1
            continue

        # Template refs {{...}} — must check before single {
        if text[pos : pos + 2] == "{{":
            m = _TEMPLATE_REF.match(text, pos)
            if m:
                flush_leaf()
                nodes.append(HMKNode("double_braces", m.group(1)))
                pos = m.end()
                continue

        # Brace group {expr}[count?]
        if ch == "{":
            flush_leaf()
            end = _scan_braces(text, pos)
            inner = text[pos + 1 : end - 1]
            node = HMKNode("brace_group", inner)
            pos = end
            cm = _COUNT_SRC.match(text, pos)
            if cm:
                node.metadata["count_src"] = cm.group(1)
                pos = cm.end()
            nodes.append(node)
            continue

        # Separator <<sep>>[count?]
        if text[pos : pos + 2] == "<<":
            flush_leaf()
            end = _scan_chevrons(text, pos + 2)
            sep = text[pos + 2 : end - 2]
            node = HMKNode("separator", sep)
            pos = end
            cm = _COUNT_SRC.match(text, pos)
            if cm:
                node.metadata["count_src"] = cm.group(1)
                pos = cm.end()
            nodes.append(node)
            continue

        leaf_buf.append(ch)
        pos += 1

    flush_leaf()
    return HMKNode("root", text, nodes or [HMKNode("leaf", text)])
