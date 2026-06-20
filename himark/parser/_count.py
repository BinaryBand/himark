"""Count-modifier parsing: a `[count]` string → a typed `CountSpec`.

Standalone from the σ-grammar resolution in phase3 — it operates purely on the
count string between the brackets (`"1..6"`, `"a,b,c"`, `"#i"`), with no
knowledge of the universe the count applies to.
"""

import re

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError

_COUNTREF = re.compile(r"#(\d+)")


def parse_count(src: str) -> t.CountSpec:
    """Parse a count modifier string into a count descriptor.

    Forms: `[n]`, `[x..]`, `[..y]`, `[x..y]`, `[x..y..s]` (stride),
    `[a,b,c]` (union), `[#i]` (count-reference)."""
    src = src.strip()
    # `[#i]` — repeat exactly group i's repetition count (resolved at match time).
    m = _COUNTREF.fullmatch(src)
    if m:
        return t.CountRefSpec(group=int(m.group(1)))
    # `[a,b,c]` — an explicit union of exact counts.
    if "," in src:
        try:
            values = sorted({int(p.strip()) for p in src.split(",")})
        except ValueError:
            raise CompileError(f"Invalid count expression: [{src}]") from None
        return t.CountSet(values=values)
    # `[n]` / `[x..y]` with optional stride `..s`.
    m = re.fullmatch(r"(\d*)(?:\.\.(\d*)(?:\.\.(\d+))?)?", src)
    if not m or not (m.group(1) or ".." in src):
        raise CompileError(f"Invalid count expression: [{src}]")
    lo, hi, step = m.groups()
    if ".." not in src:  # exact [n]
        return t.CountRange(min=int(lo), max=int(lo))
    step_n = int(step) if step else 1
    max_n = int(hi) if hi else None
    if step_n != 1 and max_n is None:
        raise CompileError(f"A strided count needs an upper bound: [{src}]")
    return t.CountRange(min=int(lo) if lo else 0, max=max_n, step=step_n)
