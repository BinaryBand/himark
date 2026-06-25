"""Lexical text helpers shared by the parser phases.

These operate on raw HMK source fragments — brace-depth-aware splitting,
escape resolution, and brace scanning — with no knowledge of semantics.
"""

from himark.models.exceptions import CompileError

# The single escape table for HMK source. Named control characters plus the
# metacharacters that need escaping to appear literally; any other escaped
# character resolves to itself (so `\!` -> `!`). `\r` matches a carriage return,
# so `@s` whitespace and the `phase2` tokenizer handle CRLF target text.
ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "\\": "\\",
    "{": "{",
    "}": "}",
    '"': '"',
}

# Fixed-width hex code-point escapes, Python/C spellings: `\xHH` (a byte),
# `\uHHHH` (BMP), `\UHHHHHHHH` (full plane). Fixed width — not a `\u{…}` brace
# form — so the trailing hex never looks like a brace to a depth scanner, and the
# named alphabets (`@b256`/`@ascii`/`@uni`) can be spelled as text in the prelude.
_HEX_ESCAPE_WIDTH = {"x": 2, "u": 4, "U": 8}
_HEX_DIGITS = set("0123456789abcdefABCDEF")


def unescape(s: str) -> str:
    """Resolve backslash escapes in a literal fragment (\\!, \\{, \\n, \\x41, …).

    `\\xHH`/`\\uHHHH`/`\\UHHHHHHHH` resolve to the code point; any other escape
    resolves to the escaped character itself (so `\\!` -> `!`, and a `\\x` without
    two hex digits stays a literal `x`).
    """
    if "\\" not in s:
        return s
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            width = _HEX_ESCAPE_WIDTH.get(s[i + 1])
            hexits = s[i + 2 : i + 2 + width] if width else ""
            if width and len(hexits) == width and set(hexits) <= _HEX_DIGITS:
                out.append(chr(int(hexits, 16)))
                i += 2 + width
            else:
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
    literal part of the value (e.g. the `-\\ ` member of `{-\\ ,-}`).
    """
    start = 0
    while start < len(s) and s[start] in " \t":
        start += 1
    end = len(s)
    while end > start and s[end - 1] in " \t" and not _is_escaped(s, end - 1):
        end -= 1
    return s[start:end]


def brace_end(expr: str) -> int | None:
    """Index just past the '}' matching the '{' at position 0, or None if
    unbalanced. A backslash-escaped brace (`\\{`, `\\}`) is a literal and does not
    affect depth."""
    depth = 0
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch == "\\":
            i += 2  # skip the escaped char — it is literal, never a delimiter
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def inner_of(part: str) -> str:
    """Return the content inside the outer braces of an α part like '{a..z}'."""
    end = brace_end(part)
    return part[1 : end - 1] if end is not None else part[1:-1]


def split_top(sep: str, text: str) -> list[str]:
    """Split `text` on `sep` only at top level — outside every `{…}` brace and
    `[…]` count. Tracking count brackets keeps a range count like `[1..3]` from
    being mistaken for a top-level `..` range operator. A backslash-escaped
    bracket (`\\{`, `\\}`, …) is a literal and does not affect depth."""
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    sep_len = len(sep)
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            cur.append(
                text[i : i + 2]
            )  # keep the escape pair intact, never a delimiter
            i += 2
        elif ch in "{[":
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
