"""Phase 2: Tokenize an HMK pattern string into a typed node tree.

Constructs recognized:
  {expr}[count]   — brace_group with optional count modifier
  !{expr}[count]  — subtractive universe (a top-level complement, `!` folded in)
  "..."           — quoted literal text (verbatim, with escapes)
  leaf text       — verbatim literal fragments
"""

import re

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError
from himark.parser._text import ESCAPES, brace_end, unescape

# Count suffix: [N], [N..], [..N], [N..M], [..]
_COUNT_SRC = re.compile(r"\[([^\]]*)\]")


def _scan_braces(text: str, pos: int) -> int:
    """Return the end index (exclusive) of the brace group starting at pos."""
    span = brace_end(text[pos:])
    if span is None:
        raise CompileError(f"Unclosed '{{' at position {pos}")
    return pos + span


def _scan_string(text: str, pos: int) -> int:
    """Return the end index (exclusive) of the `"..."` literal starting at pos."""
    i = pos + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i + 1
        i += 1
    raise CompileError(f"Unclosed '\"' at position {pos}")


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

        # Quoted literal text: verbatim output (or match), with \" / \\ / \n
        # escapes. A lone ' is an ordinary character — only " delimits.
        if ch == '"':
            flush_leaf()
            end = _scan_string(text, pos)
            nodes.append(t.LeafNode(content=unescape(text[pos + 1 : end - 1])))
            pos = end
            continue

        # Brace group {expr}[count?], or a subtractive universe !{expr}[count?].
        # A top-level `!` right before a brace negates it (HMK.md §Subtraction);
        # the `!` is folded into the brace content so phase3's complement path
        # (content starting with `!`) resolves `!{X}` and the inner `{!X}`
        # spelling identically. An inner `!{…}` arm lives inside a brace's
        # content string and is left for phase3, never reaching this top scan.
        if ch == "{" or (ch == "!" and text[pos + 1 : pos + 2] == "{"):
            flush_leaf()
            complement = ch == "!"
            start = pos + 1 if complement else pos
            end = _scan_braces(text, start)
            inner = text[start + 1 : end - 1]
            brace = t.BraceGroupNode(content="!" + inner if complement else inner)
            pos = end
            cm = _COUNT_SRC.match(text, pos)
            if cm:
                brace.count_src = cm.group(1)
                pos = cm.end()
            nodes.append(brace)
            continue

        leaf_buf.append(ch)
        pos += 1

    flush_leaf()
    return t.RootNode(children=nodes or [t.LeafNode(content=text)])
