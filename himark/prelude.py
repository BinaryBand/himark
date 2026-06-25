"""Loader for `himark/std.hmk` — the centralized declaration prelude.

The prelude is the single source of truth for named alphabets and derived
filters. It runs (loads) once, before every `.hmk` run, replacing the former
`macros.toml`/`macros.py` pair. Declarations are *Himark source* now declared
*in Himark's own file*, not a foreign config format.

Two declaration forms (see `std.hmk`):

  * ``@name = <source>`` — a named alphabet. `@name` expands to the source before
    tokenizing (phase 1). The engine holds no alphabet knowledge; it only sees the
    ranges and congruence classes the source expands to.
  * ``filter name = <expr>`` — a derived filter: a named moustache expression over
    the primitive filters, consumed in template position (see `engine/_render`).

This module parses the prelude once and exposes `MACROS` and `FILTERS`. It lives
at the package root (not under `parser` or `engine`) because both layers consume
it — the parser expands `MACROS`, the engine resolves `FILTERS` — and those two
siblings are forbidden from importing each other. The structural `[[rewrites]]`
that also lived in `macros.toml` are not data-declarable (they inspect braces);
they now live as code defaults in `parser/rewrites.py`.
"""

import re
from pathlib import Path

from himark.models.exceptions import CompileError

PRELUDE_PATH = Path(__file__).parent / "std.hmk"

_MACRO_RE = re.compile(r"@(\w+)\s*=\s*(.*)")
_FILTER_RE = re.compile(r"filter\s+(\w+)\s*=\s*(.*)")


def _strip_comment(line: str) -> str:
    """Drop a `//` line comment, ignoring `//` inside braces or quotes (so a `//`
    that is part of a declared alphabet survives). Mirrors the script loader."""
    depth = 0
    inq = False
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            i += 2
            continue
        if c == '"':
            inq = not inq
        elif not inq:
            if c == "/" and depth == 0 and line[i + 1 : i + 2] == "/":
                return line[:i]
            depth += (c == "{") - (c == "}")
        i += 1
    return line


def _load() -> tuple[dict[str, str], dict[str, str]]:
    """Parse `std.hmk` into `(macros, filters)`. A line that is neither a `@name`
    alphabet nor a `filter name` declaration is a `CompileError` — the prelude is
    declarations only, so a stray statement is a typo, not silent input."""
    macros: dict[str, str] = {}
    filters: dict[str, str] = {}
    for raw in PRELUDE_PATH.read_text("utf-8").splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if (m := _FILTER_RE.fullmatch(line)) is not None:
            filters[m.group(1)] = m.group(2).strip()
        elif (m := _MACRO_RE.fullmatch(line)) is not None:
            macros[m.group(1)] = m.group(2).strip()
        else:
            raise CompileError(f"{PRELUDE_PATH.name}: not a declaration: {line!r}")
    return macros, filters


# name -> Himark source, expanded into the pattern before tokenizing (phase 1).
# name -> derived-filter body, a moustache expression evaluated in template position.
MACROS, FILTERS = _load()
