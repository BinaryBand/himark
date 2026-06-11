"""Phase 2: Tokenize an HMK pattern string into a typed node tree.

Constructs recognized:
  {expr}[count]   — brace_group with optional count modifier
  <<sep>>[count]  — separator with optional count modifier
  {{ref}}         — template reference (double-brace, passed through)
  leaf text       — verbatim literal fragments
"""

import re

from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError

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


def parse(text: str) -> t.RootNode:
    """Tokenize HMK pattern text into a typed node tree."""
    nodes: list[t.Node] = []
    pos = 0
    leaf_buf: list[str] = []

    def flush_leaf():
        if leaf_buf:
            nodes.append(t.LeafNode(content="".join(leaf_buf)))
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
                nodes.append(t.LeafNode(content=mapping[esc]))
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
                nodes.append(t.DoubleBracesNode(content=m.group(1)))
                pos = m.end()
                continue

        # Brace group {expr}[count?]
        if ch == "{":
            flush_leaf()
            end = _scan_braces(text, pos)
            brace = t.BraceGroupNode(content=text[pos + 1 : end - 1])
            pos = end
            cm = _COUNT_SRC.match(text, pos)
            if cm:
                brace.count_src = cm.group(1)
                pos = cm.end()
            nodes.append(brace)
            continue

        # Separator <<sep>>[count?]
        if text[pos : pos + 2] == "<<":
            flush_leaf()
            end = _scan_chevrons(text, pos + 2)
            sep = t.SeparatorNode(content=text[pos + 2 : end - 2])
            pos = end
            cm = _COUNT_SRC.match(text, pos)
            if cm:
                sep.count_src = cm.group(1)
                pos = cm.end()
            nodes.append(sep)
            continue

        leaf_buf.append(ch)
        pos += 1

    flush_leaf()
    return t.RootNode(content=text, children=nodes or [t.LeafNode(content=text)])
