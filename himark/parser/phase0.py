"""Phase 0: Split a raw HMK statement into its ordered list of steps.

A statement is a `=>` chain: `pattern => pattern => ... => template`. There is a
single arrow — `=>`. The chain produces one **branch** per match of the first
pattern; each branch is transformed independently and rendered either as a list
(the rendered matches) or spliced back into the source (in-place transform). The
two renderings come from the same branches, so there is no separate replace arrow.
"""


def split_statement(text: str) -> list[str]:
    """Split `'P1 => P2 => ... => T'` into its ordered list of step strings.

    Scans for `=>` outside of any construct delimiters to avoid false splits.
    """
    steps: list[str] = []
    remaining = text
    while True:
        idx = _find_arrow(remaining)
        if idx is None:
            steps.append(remaining.strip())
            break
        steps.append(remaining[:idx].strip())
        remaining = remaining[idx + 2 :]
    return steps


def _find_arrow(text: str) -> int | None:
    """Index of the first top-level `=>`, or None.

    An arrow is recognised only at top level — outside every `{…}`, `[…]`, and
    `"…"` (ANTLR friendly): inside a quoted template `=>` is literal text and never
    splits, so a template may contain `=>` freely with no escape. A single `<` or
    `>` is plain text (a template's `<strong>` never reads as an arrow), and a
    backslash-escaped character is never a delimiter.
    """
    depth = 0
    inq = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            inq = not inq
        elif inq:
            pass  # inside a quoted template — braces and `=>` are literal
        elif ch == "=" and text[i + 1 : i + 2] == ">" and depth == 0:
            return i
        elif ch in ("[", "{"):
            depth += 1
        elif ch in ("]", "}"):
            depth = max(0, depth - 1)
        i += 1
    return None
