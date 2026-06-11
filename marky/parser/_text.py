"""Lexical text helpers shared by the parser phases.

These operate on raw HMK source fragments — brace-depth-aware splitting,
escape resolution, and brace scanning — with no knowledge of semantics.
"""

from marky.models.exceptions import CompileError

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r"}


def unescape(s: str) -> str:
    """Resolve backslash escapes in a literal arm (\\!, \\{, \\n, …)."""
    if "\\" not in s:
        return s
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(_ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def brace_end(expr: str) -> int | None:
    """Index just past the '}' matching the '{' at position 0, or None if unbalanced."""
    depth = 0
    for i, ch in enumerate(expr):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def inner_of(part: str) -> str:
    """Return the content inside the outer braces of an α part like '{a..z}'."""
    end = brace_end(part)
    return part[1 : end - 1] if end is not None else part[1:-1]


def split_top(sep: str, text: str) -> list[str]:
    """Split `text` on `sep` only at brace depth 0."""
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    sep_len = len(sep)
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
            cur.append(ch)
            i += 1
        elif ch == "}":
            depth -= 1
            cur.append(ch)
            i += 1
        elif depth == 0 and text[i : i + sep_len] == sep:
            parts.append("".join(cur))
            cur = []
            i += sep_len
        else:
            cur.append(ch)
            i += 1
    parts.append("".join(cur))
    return parts


def strict_split(sep: str, text: str, context: str) -> list[str]:
    """split_top that rejects whitespace-padded parts (whitespace is
    significant; a part that is *purely* whitespace stays a literal)."""
    parts = split_top(sep, text)
    for p in parts:
        stripped = p.strip(" \t")
        if stripped and stripped != p:
            raise CompileError(
                f"Unexpected whitespace in {context!r}: remove spaces around {sep!r}"
            )
    return parts
