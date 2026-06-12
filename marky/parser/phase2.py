"""Phase 2: Tokenize an HMK pattern string into a typed node tree.

Constructs recognized:
  {expr}[count]   — brace_group with optional count modifier
  <<sep>>[count]  — separator (count modifier is a compile error)
  {{ref}}         — template reference, parsed immediately into a typed node
  leaf text       — verbatim literal fragments
"""

import re

from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError
from marky.parser._text import ESCAPES
from marky.parser.templates import parse_template_expr

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

        # Escape sequences. A recognized escape becomes its literal character
        # (so an escaped metacharacter is not tokenized); an unrecognized one
        # keeps the backslash for a later phase to resolve.
        if ch == "\\" and pos + 1 < len(text):
            esc = text[pos + 1]
            if esc in ESCAPES:
                flush_leaf()
                nodes.append(t.LeafNode(content=ESCAPES[esc]))
                pos += 2
                continue
            leaf_buf.append(ch)
            pos += 1
            continue

        # Template refs {{...}} — parsed immediately; must check before single {
        if text[pos : pos + 2] == "{{":
            m = _TEMPLATE_REF.match(text, pos)
            if m:
                flush_leaf()
                nodes.append(parse_template_expr(m.group(1)))
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

        # Separator <<sep>> — count modifier is not allowed
        if text[pos : pos + 2] == "<<":
            flush_leaf()
            end = _scan_chevrons(text, pos + 2)
            sep = t.SeparatorNode(content=text[pos + 2 : end - 2])
            pos = end
            cm = _COUNT_SRC.match(text, pos)
            if cm:
                raise CompileError(
                    f"A count on <<...>> is not allowed: "
                    f"<<{sep.content}>>[{cm.group(1)}]"
                )
            nodes.append(sep)
            continue

        leaf_buf.append(ch)
        pos += 1

    flush_leaf()
    return t.RootNode(children=nodes or [t.LeafNode(content=text)])
