"""Loader for `himark/std.hmk` — the centralized declaration prelude.

The prelude is the single source of truth for named alphabets **and declared
filters**. It runs (loads) once, before every `.hmk` run, replacing the former
`macros.toml`/`macros.py` pair. Declarations are *Himark source* now declared *in
Himark's own file*, not a foreign config format.

One declaration form, `@name = <body>`, disambiguated by the **body shape**:

  * a **bare pattern** body (`@d = 0..9`) is a **named alphabet** — `@name` expands
    to the source before tokenizing (phase 1). The engine holds no alphabet
    knowledge; it only sees the ranges and congruence classes the source expands to.
  * a body containing a top-level arrow (`@trim = {@s}… => "…"`) or a leading
    template (`@double = "{{ $ * 2 }}"`) is a **declared filter** — an ordinary
    himark pipeline compiled once and stored in `FILTERS`, invoked at a use site as
    `| name`. A filter that is a single bare `{{ … }}` moustache is stored as its
    inner `Expr` (a value-shaped filter, band-preserving); anything else as a
    compiled `list[list[Step]]` pipeline (document-shaped). See docs/HMK.md.

This module parses the prelude once and exposes `VARIABLES` and `FILTERS`. It lives
at the package root (not under `parser`) because the parser expands `VARIABLES`
before tokenizing. The structural `[[rewrites]]` that also lived in `macros.toml`
are not data-declarable (they inspect braces); they now live as code defaults in
`parser/rewrites.py`.
"""

import re
from pathlib import Path

from himark.models.exceptions import CompileError

PRELUDE_PATH = Path(__file__).parent / "std.hmk"

_VARIABLE_RE = re.compile(r"@(\w+)\s*=\s*(.*)")


def _strip_inline_comment(s: str) -> str:
    depth = 0
    inq = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            i += 2
            continue
        if c == '"':
            inq = not inq
        elif inq:
            pass
        elif c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        elif depth == 0 and c == "/" and s[i + 1 : i + 2] == "/":
            return s[:i].rstrip()
        i += 1
    return s


def _is_filter_body(rhs: str) -> bool:
    """Classify a `@name =` body: a filter (True) or a textual alphabet (False).

    A filter body either starts with a `"…"` template or carries a top-level arrow
    (`=>` / `<=>`) — an arrow inside a `"…"` template or a `{…}`/`[…]` group is
    literal, so the scan tracks string and brace/bracket depth and only counts an
    arrow at depth 0 outside a string."""
    s = rhs.strip()
    if s.startswith('"'):
        return True
    depth = 0
    inq = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            i += 2
            continue
        if c == '"':
            inq = not inq
        elif inq:
            pass
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth = max(0, depth - 1)
        elif depth == 0 and c == "=" and s[i + 1 : i + 2] == ">":
            return True  # `=>` (also the tail of `<=>`) — a pipeline body
        i += 1
    return False


def _load() -> tuple[dict[str, str], dict[str, str]]:
    """Parse `std.hmk` into a `(variables, filter_srcs)` pair — the alphabet table
    and an ordered `name -> body-source` map of filter declarations. A line that is
    not a `@name` declaration is a `CompileError` — the prelude is declarations only,
    so a stray statement is a typo, not silent input."""
    variables: dict[str, str] = {}
    filter_srcs: dict[str, str] = {}
    for raw in PRELUDE_PATH.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if (m := _VARIABLE_RE.fullmatch(line)) is None:
            raise CompileError(f"{PRELUDE_PATH.name}: not a declaration: {line!r}")
        name = m.group(1)
        body = _strip_inline_comment(m.group(2).strip())
        if _is_filter_body(body):
            filter_srcs[name] = body
        else:
            variables[name] = body
    return variables, filter_srcs


def compile_filter_body(
    body: str,
    variables: dict[str, str] | None,
    filters: dict[str, object],
) -> object:
    """Compile one filter declaration `body` into the form `ExFilter.body` carries.

    A body that compiles to a single template step of one bare `{{ … }}` moustache
    is **value-shaped** — return its inner `Expr` (applied by evaluating it with `$`
    bound to the subject universe, so alphabet + band survive). Anything else is
    **document-shaped** — return the compiled one-statement pipeline `list[list[Step]]`
    (applied by running it over the subject's text). `filters` supplies any earlier
    filters this body pipes through (`@trim = "{{ $ | lstrip | rstrip }}"`)."""
    from himark.models.compiled import Moustache, Template
    from himark.parser import parse

    steps = parse(body, variables=variables or None, filters=filters)
    if len(steps) == 1 and isinstance(steps[0], Template):
        parts = steps[0].parts
        if len(parts) == 1 and isinstance(parts[0], Moustache):
            return parts[0].expr
    return [steps]


def _compile_filters(
    filter_srcs: dict[str, str], variables: dict[str, str]
) -> dict[str, object]:
    """Compile the prelude filter declarations in source order, so a later filter can
    pipe through an earlier one (the registry is built incrementally)."""
    filters: dict[str, object] = {}
    for name, body in filter_srcs.items():
        filters[name] = compile_filter_body(body, variables, filters)
    return filters


# name -> Himark source, expanded into the pattern before tokenizing (phase 1).
VARIABLES, _FILTER_SRCS = _load()
# name -> compiled filter body (an `Expr` or a `list[list[Step]]` pipeline),
# resolved by the moustache compiler when it lowers a `| name` pipe.
FILTERS = _compile_filters(_FILTER_SRCS, VARIABLES)
