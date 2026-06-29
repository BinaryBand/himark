"""Whole-`.hmk`-file compilation — the script/pipeline layer of the compiler.

A `.hmk` file is a pipeline: an ordered list of statements (each a `=>`/`<=>`
chain), optionally preceded by `@name = <body>` definitions scoped to the file.
ANTLR's `script` rule owns the file's structure — statement boundaries, blank
lines, continuation lines (a leading-arrow line continues the previous statement),
`=>` vs `<=>`, and definitions — so this module only walks the parse tree. The one
pre-pass ANTLR cannot do context-free is stripping `//` comments at brace/quote
depth 0 (see `strip_comments`).

The product is a `list[list[Step]]` — one inner list of compiled steps per
statement — ready for `engine.run_pipeline`.
"""

from __future__ import annotations

from pathlib import Path

from himark.models.compiled import Step
from himark.models.exceptions import CompileError
from himark.parser._helpers import strip_comments, strip_insignificant_ws
from himark.prelude import VARIABLES


def compile_script(source: str) -> list[list[Step]]:
    """Compile a `.hmk` script — statements plus optional local `@name = <body>`
    definitions — into a runnable pipeline. A definition resolves to its body
    wherever `@name` is used (the same textual mechanism as a prelude alphabet),
    leaving no trace in the compiled pipeline. Shadowing a prelude variable or
    redefining a local is a `CompileError`."""
    from himark.parser import _parse_script_tree, parse

    source = strip_insignificant_ws(strip_comments(source))
    local: dict[str, str] = {}
    pipeline: list[list[Step]] = []
    for item in _parse_script_tree(source).scriptItem():
        defn = item.definition()
        if defn is not None:
            name = defn.NAME().getText()
            if name in VARIABLES:
                raise CompileError(f"definition @{name} shadows a prelude variable")
            if name in local:
                raise CompileError(f"@{name} is already defined")
            body = defn.pattern()
            local[name] = source[body.start.start : body.stop.stop + 1]
            continue
        stmt = item.statement()
        stmt_src = source[stmt.start.start : stmt.stop.stop + 1]
        pipeline.append(parse(stmt_src, variables=local or None))
    return pipeline


def load_script(path: str) -> list[list[Step]]:
    """Read and compile a `.hmk` script file into a runnable pipeline."""
    return compile_script(Path(path).read_text("utf-8"))


def compile_pipeline(statements: list[str]) -> list[list[Step]]:
    """Compile raw HMK statement strings into a runnable pipeline (no definitions).
    Each statement's `<=>` arrow is flagged on its first step by `parse`."""
    from himark.parser import parse

    return [parse(s) for s in statements]
