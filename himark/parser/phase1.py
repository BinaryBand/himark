"""Phase 1: Split a raw HMK statement into its pattern and template sides."""

from dataclasses import dataclass


@dataclass
class Statement:
    pattern_text: str
    template_text: str | None = None


def split_statement(text: str) -> Statement:
    """Split 'pattern => template' into a Statement.

    Scans for => outside of any bracket/chevron/brace delimiters to avoid
    false splits on => appearing inside a token.
    """
    idx = _find_arrow(text)
    if idx is None:
        return Statement(pattern_text=text.strip())
    return Statement(
        pattern_text=text[:idx].rstrip(),
        template_text=text[idx + 2:].lstrip(),
    )


def _find_arrow(text: str) -> int | None:
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "=" and text[i + 1:i + 2] == ">" and depth == 0:
            return i
        if ch in ("[", "<", "{"):
            depth += 1
        elif ch in ("]", ">", "}"):
            depth = max(0, depth - 1)
        i += 1
    return None
