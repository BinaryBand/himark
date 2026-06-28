"""Advanced pattern rewrites — a configurable preprocessing seam.

Rewrites run in phase 1, *after* variable expansion and *before* tokenizing, so they
are pure notation: the engine never sees them, only the Himark source they expand
to. Unlike a text variable (`@name` → text), a rewrite is **structural** — it
inspects braces and renumbers groups.

Two layers keep the specifics in data, not code:

  * **Tools** — a small set of generic, parameterized interpreters (below). Each
    knows *how* to perform a class of structural rewrite.
  * **Rules** — the `_RULES` table below: each pairs a tool with its parameters.
    Rewrites are structural (they inspect braces), so — unlike the named alphabets
    of the `.hmk` prelude — they are not data-declarable and stay here as code.
"""

import re

from himark.parser._text import brace_end, _is_escaped

_COUNT = re.compile(r"\[[^\]]*\]")
# A self-binding count token: a `[…]` count holding a lone `#` (not `#N`, which is
# a count-reference) — `[#]`, `[x..#]`, `[#..y]`, `[x..#..y]`.
_HASH_COUNT = re.compile(r"\[[^\]#]*#(?![0-9])[^\]#]*\]")
_HASH_BOUNDS = re.compile(r"(\.\.)?#(\.\.)?")


# ── Tools (generic interpreters) ──────────────────────────────────────────────


def substitute(src: str, *, find: str, into: str) -> str:
    """Replace every literal occurrence of `find` with `into` — the simplest
    rewrite, for fixed sugar like `{|..}` → `{|}[..]`."""
    return src.replace(find, into)


def bind_count(src: str) -> str:
    """The self-binding count `[…#…]`, with optional bounds. The `#` count binds on
    the first repeat and is enforced on the rest; bounds around it constrain that
    count, collapsing into the free copy's range:
    `[#]`→`[..]`, `[x..#]`→`[x..]`, `[#..y]`→`[..y]`, `[x..#..y]`→`[x..y]`. So
    `{ROW[x..#..y]}[N]` → `ROW[x..y]… {ROW[#G]…}[N]`."""
    while True:
        m = _HASH_COUNT.search(src)
        if m is None:
            return src
        marker = m.group(0)
        free = "[" + _HASH_BOUNDS.sub("..", marker[1:-1]) + "]"
        out = _unroll(src, m.start(), marker, free, "[#@]")
        if out is None:
            return src
        src = out


def _unroll(src: str, marker_at: int, marker: str, free: str, bound: str) -> str | None:
    """Unroll the repeated grouping brace enclosing `marker` (at `marker_at`):
    a free first copy (marker→`free`) then the repeats (marker→`bound`, with `@`
    the establishing copy's group index). None if there's no such brace+count."""
    open_idx = _enclosing_brace(src, marker_at)
    if open_idx is None:
        return None
    span = brace_end(src[open_idx:])
    if span is None:
        return None
    end = open_idx + span
    count = _COUNT.match(src, end)
    if count is None:
        return None
    body = src[open_idx + 1 : end - 1]
    g = _count_top_groups(src[:open_idx])
    first = body.replace(marker, free, 1)
    rest = "{" + body.replace(marker, bound.replace("@", str(g)), 1) + "}"
    return src[:open_idx] + first + rest + count.group(0) + src[count.end() :]


_TOOLS = {
    "substitute": substitute,
    "bind_count": bind_count,
}


# ── Brace helpers ─────────────────────────────────────────────────────────────


def _enclosing_brace(src: str, pos: int) -> int | None:
    """Index of the `{` directly enclosing `pos` (the brace `pos` sits in), or None.

    A backslash-escaped brace (`\\{`, `\\}`) is a literal and does not affect depth,
    matching `brace_end`/`split_top` in `_text`."""
    depth = 0
    for i in range(pos - 1, -1, -1):
        c = src[i]
        if c not in "{}" or _is_escaped(src, i):
            continue
        if c == "}":
            depth += 1
        elif depth == 0:
            return i
        else:
            depth -= 1
    return None


def _count_top_groups(text: str) -> int:
    """Number of top-level `{…}` groups in `text` (each opens one capture).

    A backslash-escaped brace (`\\{`, `\\}`) is a literal and is not a group, so it
    never changes depth or the count — consistent with the rest of the parser."""
    depth = n = 0
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2  # skip the escaped char — a literal, never a delimiter
            continue
        if c == "{":
            if depth == 0:
                n += 1
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        i += 1
    return n


# ── Rules ─────────────────────────────────────────────────────────────────────
# The active rewrites, in order. Structural sugar inspects braces and renumbers
# groups, so — unlike a named alphabet — it is not declarable in the `.hmk`
# prelude; it lives here as code. `bind_count` handles the self-binding count
# `[#]`; `substitute` expands `{|..}` (a pipe repeated any number of times).
_RULES: list[tuple] = [
    (bind_count, {}),
    (substitute, {"find": "{|..}", "into": "{|}[..]"}),
]


def apply(src: str) -> str:
    """Run every configured rewrite over `src`, in declaration order."""
    for tool, params in _RULES:
        src = tool(src, **params)
    return src
