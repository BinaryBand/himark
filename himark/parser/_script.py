"""Whole-`.hmk`-file compilation — the script/pipeline layer of the compiler.

A `.hmk` file is a pipeline: an ordered list of statements (each a `=>`/`<=>`
chain), optionally preceded by `@name = <body>` definitions scoped to the file.
ANTLR's `script` rule owns the file's structure — statement boundaries, blank
lines, continuation lines (a leading-arrow line continues the previous statement),
`=>` vs `<=>`, and definitions — so this module only walks the parse tree. Comments are stripped by `strip_insignificant_ws` before ANTLR sees the source.

The product is a `list[list[Step]]` — one inner list of compiled steps per
statement — ready for `engine.run_pipeline`.
"""

from __future__ import annotations

from pathlib import Path

from himark.models.compiled import Step
from himark.models.exceptions import CompileError
from himark.parser._helpers import strip_insignificant_ws


def compile_script(source: str) -> list[list[Step]]:
    """Compile a `.hmk` script — statements plus optional local `@name = <body>`
    definitions — into a runnable pipeline. A local definition is either a textual
    **alphabet** (a bare-pattern body, resolved wherever `@name` is used, the same
    mechanism as a prelude alphabet) or a declared **filter** (a pipeline/template
    body, compiled and invoked at a `| name` use site) — told apart by the body
    shape, exactly as in the prelude. Both leave no trace in the compiled pipeline.
    Shadowing a prelude variable or redefining a local is a `CompileError`."""
    from himark.parser import _parse_script_tree, parse
    from himark.parser._compiler import compile_alphabet
    from himark.prelude import (
        ANCHORS,
        FILTERS,
        VARIABLES,
        compile_filter_body,
        _is_anchor_body,
        _is_filter_body,
    )

    source = strip_insignificant_ws(source)
    local: dict[str, str] = {}
    filters: dict[str, object] = dict(FILTERS)
    anchors: set[str] = set(ANCHORS)
    local_alphabets: dict[str, tuple] = {}
    pipeline: list[list[Step]] = []
    for item in _parse_script_tree(source).scriptItem():
        defn = item.definition()
        if defn is not None:
            name = defn.NAME().getText()
            if name in VARIABLES or name in FILTERS or name in ANCHORS:
                raise CompileError(f"definition @{name} shadows a prelude declaration")
            if name in local or name in filters or name in anchors:
                raise CompileError(f"@{name} is already defined")
            body = defn.definitionBody()
            body_src = source[body.start.start : body.stop.stop + 1]
            if _is_anchor_body(body_src):
                anchors.add(name)
            elif _is_filter_body(body_src):
                filters[name] = compile_filter_body(body_src, local, filters)
            else:
                local[name] = body_src
                try:
                    local_alphabets[name] = compile_alphabet(body_src, local)
                except CompileError:
                    pass  # not a value alphabet; a `| name` cast diagnoses at use
            continue
        stmt = item.statement()
        stmt_src = source[stmt.start.start : stmt.stop.stop + 1]
        pipeline.append(
            parse(
                stmt_src,
                variables=local or None,
                filters=filters,
                anchors=anchors,
                alphabets=local_alphabets or None,
            )
        )
    return pipeline


def load_script(path: str) -> list[list[Step]]:
    """Read and compile a `.hmk` script file into a runnable pipeline."""
    return compile_script(Path(path).read_text("utf-8"))


def compile_pipeline(statements: list[str]) -> list[list[Step]]:
    """Compile raw HMK statement strings into a runnable pipeline (no definitions).
    Each statement's `<=>` arrow is flagged on its first step by `parse`."""
    from himark.parser import parse

    return [parse(s) for s in statements]
