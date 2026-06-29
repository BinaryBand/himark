"""Pure helpers extracted from himark/parser/__init__.py — no ANTLR dependency.

These are value-semantic functions: escape resolution, whitespace stripping,
and leaf-text resolution. They don't depend on the parse tree structure.
"""

from __future__ import annotations

import re

# ── Escape resolution (leaf value, not structure) ────────────────────────────
# The grammar recognises an escape (`ESC`/`HEX_ESC` tokens); mapping it to a code
# point is leaf *value* semantics a grammar can't express, so it lives here as the
# single escape table. Named control characters plus the metacharacters that need
# escaping to appear literally; any other escaped character resolves to itself (so
# `\!` -> `!`). `\r` matches a carriage return, so CRLF target text is handled.
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
# form — so the trailing hex never looks like a brace to a depth scanner.
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


def _resolve_leaf_escapes(raw: str) -> str:
    """Resolve escapes in a top-level literal run. Unlike `unescape`, an unknown
    escape *keeps* its backslash (the character rides along next iteration)."""
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == "\\" and i + 1 < len(raw):
            esc = raw[i + 1]
            if esc in ESCAPES:
                out.append(ESCAPES[esc])
                i += 2
                continue
            out.append(raw[i])  # keep the backslash; the char rides along next
            i += 1
            continue
        out.append(raw[i])
        i += 1
    return "".join(out)


# ── Depth-aware whitespace stripping ─────────────────────────────────────────
def strip_insignificant_ws(text: str) -> str:
    """Drop spaces/tabs the grammar treats as insignificant — the depth-aware
    whitespace pre-pass HMK.md mandates. Spaces and tabs are literal only inside a
    `{…}` brace body or a `"…"` template; everywhere else (around steps and arrows,
    between top-level constructs, inside a `[count]`) they are dropped, so
    `{a} {b}` == `{a}{b}` and `[1 .. 6]` == `[1..6]`. Newlines are kept — the
    grammar's `sp` consumes them as the `.hmk` continuation form — and a
    backslash-escaped space (`\\ `) is preserved verbatim."""
    out: list[str] = []
    depth = 0
    inq = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:  # an escape — both chars are literal
            out.append(text[i : i + 2])
            i += 2
            continue
        if c == '"':
            inq = not inq
            out.append(c)
        elif inq:  # inside a template — every char (incl. braces, spaces) is literal
            out.append(c)
        elif c == "{":
            depth += 1
            out.append(c)
        elif c == "}":
            depth = max(0, depth - 1)
            out.append(c)
        elif depth == 0 and c in (" ", "\t"):
            pass  # insignificant whitespace at top level / in a count — drop it
        else:
            out.append(c)
        i += 1
    return "".join(out)


# ── Depth-aware comment stripping ────────────────────────────────────────────
def strip_comments(source: str) -> str:
    """Drop `//` line comments — but only at brace/quote **depth 0** (HMK.md). A
    `//` inside a `{…}` brace or a `"…"` template is literal, so `{//}` and a
    `http://…` in a template survive; a top-level `// note` runs to end of line.
    Depth and quote state carry across physical lines, since a brace or template
    may span them. ANTLR's lexer is context-free and cannot express this depth-0
    rule, so comment stripping is a pre-pass before the grammar sees the source."""
    out: list[str] = []
    depth = 0
    inq = False
    i = 0
    n = len(source)
    while i < n:
        c = source[i]
        if c == "\\" and i + 1 < n:  # an escape — both chars ride along literal
            out.append(source[i : i + 2])
            i += 2
            continue
        if c == '"':
            inq = not inq
            out.append(c)
            i += 1
        elif not inq and depth == 0 and c == "/" and source[i + 1 : i + 2] == "/":
            j = source.find("\n", i)
            i = n if j == -1 else j  # skip to (but keep) the newline
        else:
            if not inq:
                depth += (c == "{") - (c == "}")
            out.append(c)
            i += 1
    return "".join(out)


# ── Script-local variable text expansion ─────────────────────────────────────
def text_expand_variables(text: str, variables: dict[str, str]) -> str:
    """Inline script-local @name references by fixed-point substitution.

    Top-level @name uses are tokenised as literalRun (AT NAME) by ANTLR, so the
    structural resolver never sees them.  Before ANTLR tokenises a non-template
    step, substitute each @name that appears in `variables` with its body text.
    Prelude variables are left alone — they only appear inside braces and are
    handled structurally by the resolver.
    """
    names = sorted(variables, key=len, reverse=True)
    pat = re.compile(r"@(" + "|".join(re.escape(n) for n in names) + r")(?!\w)")
    out = text
    for _ in range(100):
        new = pat.sub(lambda m: variables[m.group(1)], out)
        if new == out:
            break
        out = new
    return out