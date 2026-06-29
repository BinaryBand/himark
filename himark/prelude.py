"""Loader for `himark/std.hmk` — the centralized declaration prelude.

The prelude is the single source of truth for named alphabets. It runs (loads)
once, before every `.hmk` run, replacing the former `macros.toml`/`macros.py`
pair. Declarations are *Himark source* now declared *in Himark's own file*, not a
foreign config format.

One declaration form (see `std.hmk`):

  * ``@name = <source>`` — a named alphabet. `@name` expands to the source before
    tokenizing (phase 1). The engine holds no alphabet knowledge; it only sees the
    ranges and congruence classes the source expands to.

(Filters are a closed, native set in `engine/_render`; there is no declared filter
form.) This module parses the prelude once and exposes `VARIABLES`. It lives at the
package root (not under `parser`) because the parser expands `VARIABLES` before
tokenizing. The structural `[[rewrites]]` that also lived in `macros.toml` are not
data-declarable (they inspect braces); they now live as code defaults in
`parser/rewrites.py`.
"""

import re
from pathlib import Path

from himark.models.exceptions import CompileError

PRELUDE_PATH = Path(__file__).parent / "std.hmk"

_VARIABLE_RE = re.compile(r"@(\w+)\s*=\s*(.*)")


def _strip_inline_comment(s: str) -> str:
    depth = 0
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        elif depth == 0 and c == "/" and s[i + 1 : i + 2] == "/":
            return s[:i].rstrip()
        i += 1
    return s


def _load() -> dict[str, str]:
    """Parse `std.hmk` into a `name -> source` variable table. A line that is not a
    `@name` alphabet declaration is a `CompileError` — the prelude is declarations
    only, so a stray statement is a typo, not silent input."""
    variables: dict[str, str] = {}
    for raw in PRELUDE_PATH.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if (m := _VARIABLE_RE.fullmatch(line)) is not None:
            variables[m.group(1)] = _strip_inline_comment(m.group(2).strip())
        else:
            raise CompileError(f"{PRELUDE_PATH.name}: not a declaration: {line!r}")
    return variables


# name -> Himark source, expanded into the pattern before tokenizing (phase 1).
VARIABLES = _load()
