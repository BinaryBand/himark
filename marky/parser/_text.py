"""Lexical text helpers shared by the parser phases.

These operate on raw HMK source fragments — brace-depth-aware splitting,
escape resolution, and brace scanning — with no knowledge of semantics.
"""

from marky.models.exceptions import CompileError

# The single escape table for HMK source. Named control characters plus the
# metacharacters that need escaping to appear literally; any other escaped
# character resolves to itself (so `\!` -> `!`).
ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "\\": "\\",
    "{": "{",
    "}": "}",
    "<": "<",
    ">": ">",
    '"': '"',
}


def unescape(s: str) -> str:
    """Resolve backslash escapes in a literal fragment (\\!, \\{, \\n, …).

    An unknown escape resolves to the escaped character itself.
    """
    if "\\" not in s:
        return s
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _is_escaped(s: str, i: int) -> bool:
    """True if s[i] is escaped — preceded by an odd run of backslashes."""
    n = 0
    j = i - 1
    while j >= 0 and s[j] == "\\":
        n += 1
        j -= 1
    return n % 2 == 1


def strip_unescaped(s: str) -> str:
    """Strip whitespace from both ends, keeping backslash-escaped whitespace.

    Arithmetic treats padding around operators as noise; `\\ ` makes a space a
    literal part of the value (e.g. the `-\\ ` member of `{-\\ <->-}`).
    """
    start = 0
    while start < len(s) and s[start] in " \t":
        start += 1
    end = len(s)
    while end > start and s[end - 1] in " \t" and not _is_escaped(s, end - 1):
        end -= 1
    return s[start:end]


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
    """Split `text` on `sep` only at top level — outside every `{…}` brace and
    `[…]` count. Tracking count brackets keeps a range count like `[1..3]` from
    being mistaken for a top-level `..` range operator."""
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    sep_len = len(sep)
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "{[":
            depth += 1
            cur.append(ch)
            i += 1
        elif ch in "}]":
            if depth > 0:
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
    significant; a part that is *purely* whitespace stays a literal, and
    escaped whitespace is part of the value)."""
    parts = split_top(sep, text)
    for p in parts:
        stripped = strip_unescaped(p)
        if stripped and stripped != p:
            raise CompileError(
                f"Unexpected whitespace in {context!r}: remove spaces around "
                f"{sep!r} (or escape a literal space as '\\ ')"
            )
    return parts
