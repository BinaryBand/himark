"""Phase 0: Split a raw HMK statement into its ordered list of steps.

The transform arrow has two forms. `=>` *extracts* — the statement returns the
list of rendered matches. `=>+` *splices* — the template's output replaces the
preceding pattern's matches in place. On the first arrow that makes the whole
statement replace-mode; on an inner arrow it is a *pipe*: the chain continues
on the spliced text. Every `+` is consumed so it never leaks into a step.
"""


def split_statement(text: str) -> tuple[list[str], bool, list[bool]]:
    """Split 'P1 => P2 => ... => T' into (steps, replace, piped).

    `replace` is the first arrow's `+` (statement-level replace mode). `piped`
    has one flag per step: True when the arrow *before* that step carried a
    `+` (inner arrows only — the first arrow's `+` is the replace flag).
    Scans for => outside of any construct delimiters to avoid false splits.
    """
    steps = []
    piped = [False]
    remaining = text
    replace = False
    first_arrow = True
    while True:
        idx = _find_arrow(remaining)
        if idx is None:
            steps.append(remaining.strip())
            break
        steps.append(remaining[:idx].strip())
        after = idx + 2
        plus = remaining[after : after + 1] == "+"
        if plus:
            after += 1
        if first_arrow:
            replace = plus
            piped.append(False)
            first_arrow = False
        else:
            piped.append(plus)
        remaining = remaining[after:]
    return steps, replace, piped


def _find_arrow(text: str) -> int | None:
    """Index of the first top-level `=>`, or None.

    Only HMK's real delimiters track depth: `{…}`, `[…]`, and the two-char
    chevrons `<<`/`>>`. A single `<` or `>` is plain text, and a
    backslash-escaped character is never a delimiter.
    """
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "=" and text[i + 1 : i + 2] == ">" and depth == 0:
            return i
        if text[i : i + 2] in ("<<", ">>"):
            depth += 1 if ch == "<" else -1
            depth = max(0, depth)
            i += 2
            continue
        if ch in ("[", "{"):
            depth += 1
        elif ch in ("]", "}"):
            depth = max(0, depth - 1)
        i += 1
    return None
