"""Advanced pattern rewrites — a configurable preprocessing seam.

Rewrites run in phase 1, *after* macro expansion and *before* tokenizing, so they
are pure notation: the engine never sees them, only the Himark source they expand
to. Unlike a text macro (`@name` → text), a rewrite is **structural** — it
inspects braces and renumbers groups.

Two layers keep the specifics in data, not code:

  * **Tools** — a small set of generic, parameterized interpreters (below). Each
    knows *how* to perform a class of structural rewrite.
  * **Rewrites** — the `[[rewrites]]` rules in `macros.toml`: each names a tool
    and supplies its parameters. Adding a shortcut that fits an existing tool is
    pure TOML; only a genuinely new *shape* needs a new tool here.
"""

import re
import tomllib
from pathlib import Path

from marky.parser._text import brace_end

_COUNT = re.compile(r"\[[^\]]*\]")


# ── Tools (generic interpreters) ──────────────────────────────────────────────


def unroll_on_marker(src: str, *, marker: str, free: str, bound: str) -> str:
    """'Bind on first repeat' unroll. Where `marker` (a count token such as `[#]`)
    sits inside a repeated grouping brace `{BODY}[N]`, emit a free first copy
    (`marker` → `free`) then the repeats (`marker` → `bound`, with `@` the bound
    group index): `{BODY[#]…}[N]` → `BODY[..]… {BODY[#G]…}[N]`."""
    while True:
        h = src.find(marker)
        if h == -1:
            return src
        open_idx = _enclosing_brace(src, h)
        if open_idx is None:
            return src  # malformed; let the engine report it
        span = brace_end(src[open_idx:])
        if span is None:
            return src
        end = open_idx + span
        count = _COUNT.match(src, end)
        if count is None:
            return src
        body = src[open_idx + 1 : end - 1]
        g = _count_top_groups(src[:open_idx])
        first = body.replace(marker, free, 1)
        rest = "{" + body.replace(marker, bound.replace("@", str(g)), 1) + "}"
        src = src[:open_idx] + first + rest + count.group(0) + src[count.end() :]


_TOOLS = {"unroll_on_marker": unroll_on_marker}


# ── Brace helpers ─────────────────────────────────────────────────────────────


def _enclosing_brace(src: str, pos: int) -> int | None:
    """Index of the `{` directly enclosing `pos` (the brace `pos` sits in), or None."""
    depth = 0
    for i in range(pos - 1, -1, -1):
        c = src[i]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                return i
            depth -= 1
    return None


def _count_top_groups(text: str) -> int:
    """Number of top-level `{…}` groups in `text` (each opens one capture)."""
    depth = n = 0
    for c in text:
        if c == "{":
            if depth == 0:
                n += 1
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
    return n


# ── Rules (data, from shortcuts.toml) ─────────────────────────────────────────


def _load_rules() -> list[tuple]:
    """The `[[rewrites]]` rules: each pairs a tool with its keyword parameters."""
    path = Path(__file__).parent.parent / "macros.toml"
    if not path.exists():
        return []
    out: list[tuple] = []
    for rule in tomllib.loads(path.read_text("utf-8")).get("rewrites", []):
        tool = _TOOLS.get(rule.get("tool", ""))
        if tool is not None:
            out.append((tool, {k: v for k, v in rule.items() if k != "tool"}))
    return out


_RULES = _load_rules()


def apply(src: str) -> str:
    """Run every configured rewrite over `src`, in declaration order."""
    for tool, params in _RULES:
        src = tool(src, **params)
    return src
