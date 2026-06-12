"""Phase 0: Split a raw HMK statement into its ordered list of steps."""


def split_statement(text: str) -> list[str]:
    """Split 'P1 => P2 => ... => T' into an ordered list of step strings.

    Scans for => outside of any bracket/chevron/brace delimiters to avoid
    false splits on => appearing inside a token.
    """
    steps = []
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
