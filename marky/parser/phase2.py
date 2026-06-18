"""Phase 2: Tokenize an HMK pattern string into a typed node tree.

Constructs recognized:
  {expr}[count]   — brace_group with optional count modifier
  "..."           — quoted literal text (verbatim, with escapes)
  leaf text       — verbatim literal fragments
"""

import re

from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError
from marky.parser._text import ESCAPES, unescape

# Count suffix: [N], [N..], [..N], [N..M], [..]
_COUNT_SRC = re.compile(r"\[([^\]]*)\]")
# Fuzzy suffix `~k`, with an optional (currently informational) insertion
# alphabet `:@l` / `:{a..z}` — `{cat}~2`, `{cat}~2:@l`.
_FUZZ_SRC = re.compile(r"~(\d+)(?::(?:[^\[\s{]+|\{[^}]*\}))?")


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

        # Brace group {expr}[count?]
        if ch == "{":
            flush_leaf()
            end = _scan_braces(text, pos)
            brace = t.BraceGroupNode(content=text[pos + 1 : end - 1])
            pos = end
            fm = _FUZZ_SRC.match(text, pos)
            if fm:
                brace.fuzz = int(fm.group(1))
                pos = fm.end()
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
