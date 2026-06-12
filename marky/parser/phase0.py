"""Phase 0: Split a raw HMK statement into its ordered list of steps.

The transform arrow has two forms. `=>` *extracts* — the statement returns the
list of rendered matches. `=>+` *replaces* — it splices each rendered match back
into the source text and returns the whole string. The mode is taken from the
first arrow (inner arrows are plain `=>`); its `+`, wherever it appears, is
consumed so it never leaks into a step's text.
"""


def split_statement(text: str) -> tuple[list[str], bool]:
    """Split 'P1 => P2 => ... => T' into its steps and the replace-mode flag.

    Scans for => outside of any bracket/chevron/brace delimiters to avoid
    false splits on => appearing inside a token.
    """
    steps = []
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
            first_arrow = False
        remaining = remaining[after:]
    return steps, replace


def _find_arrow(text: str) -> int | None:
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "=" and text[i + 1 : i + 2] == ">" and depth == 0:
            return i
        if ch in ("[", "<", "{"):
            depth += 1
        elif ch in ("]", ">", "}"):
            depth = max(0, depth - 1)
        i += 1
    return None
