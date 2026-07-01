"""ANTLR-backed front-end for the Himark parser — and its compiler.

Pipeline:
  • ANTLR lexes/parses the input into a validated CST.
  • `_AstBuilder` (a `GRAMMARVisitor` subclass in `_builder.py`) walks the CST
    and builds the AST (`himark.models.nodes_typed`). Each labeled grammar
    alternative has a `visit*` method — no manual `isinstance` dispatch.
  • `_compiler` lowers each AST step into a compiled **step**: a query becomes a
    flat opcode `Program`, a template becomes a `Template`.
  • Free helpers (escapes, whitespace, variables) live in `_helpers.py`.

Entry points:
  • `parse(text, variables=None) -> list[Step]` — the compiled product the engine
    VM consumes (a `Program` per query, a `Template` per template).
"""

from __future__ import annotations

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from typing import TYPE_CHECKING

from himark.models.compiled import Step
from himark.models.exceptions import CompileError
from himark.parser._builder import _AstBuilder
from himark.parser._compiler import compile_template_text
from himark.parser._helpers import (
    _resolve_leaf_escapes,
    strip_insignificant_ws,
    text_expand_variables,
    unescape,
)

if TYPE_CHECKING:
    from himark.parser._generated.GRAMMARParser import GRAMMARParser


class _RaiseOnError(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        raise CompileError(f"ANTLR syntax error at {line}:{column}: {msg}")


def _make_parser(src: str):
    from himark.parser._generated.GRAMMARLexer import GRAMMARLexer
    from himark.parser._generated.GRAMMARParser import GRAMMARParser

    lexer = GRAMMARLexer(InputStream(src))
    lexer.removeErrorListeners()
    lexer.addErrorListener(_RaiseOnError())
    parser = GRAMMARParser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(_RaiseOnError())
    return parser


def _parse_pattern_tree(src: str):
    return _make_parser(src).patternOnly()


def _parse_snippet_tree(src: str):
    return _make_parser(src).snippet()


def _parse_script_tree(src: str):
    return _make_parser(src).script()


def _all_literal(pattern: GRAMMARParser.PatternContext) -> bool:
    """A brace-free pattern step (every factor a bare `literalRun`) — the same proxy
    the old all-leaf AST check applied: such a step is a template (it emits its
    literal text), not a query. A counted literal run is out of slice (see below)."""
    return all(f.literalRun() is not None for f in pattern.factor())


def parse(
    text: str,
    variables: dict[str, str] | None = None,
    filters: dict[str, object] | None = None,
    anchors: set[str] | None = None,
) -> list[Step]:
    """Parse and **compile** one statement into the product the engine VM consumes:
    a `Program` per query step, a `Template` per template step. The compiler builds a
    transient semantic IR (`models.nodes_typed`) per construct and lowers it to
    opcodes; the engine never sees an AST node. A `<=>` (fixed-point) statement is
    flagged on its first step from the `FIXARROW` token, so no caller rewrites arrows.

    `filters` is the declared-filter registry (prelude globals plus any script-local
    filters) a `| name` moustache pipe resolves against; `anchors` is the set of
    declared named anchors a `{@name}` mark match resolves against. Both default to
    the prelude registries so a bare `parse(...)` still sees the standard set."""
    from himark.prelude import VARIABLES

    if filters is None:
        from himark.prelude import FILTERS  # deferred: prelude compiles its own

        filters = FILTERS
    if anchors is None:
        from himark.prelude import ANCHORS

        anchors = ANCHORS
    builder = _AstBuilder({**VARIABLES, **(variables or {})}, anchors=anchors)
    steps: list[Step] = []
    text = strip_insignificant_ws(text)
    statement = _parse_snippet_tree(text).statement()
    fixed_point = any(a.FIXARROW() is not None for a in statement.arrow())
    for step in statement.step():
        template = step.template()
        if template is not None:
            steps.append(
                compile_template_text(unescape(template.getText()[1:-1]), filters)
            )
            continue
        pattern = step.pattern()
        if variables:
            src = text[step.start.start : step.stop.stop + 1]
            pattern = _parse_pattern_tree(
                text_expand_variables(src, variables)
            ).pattern()
        if _all_literal(pattern):
            if any(f.count() is not None for f in pattern.factor()):
                raise CompileError(
                    "a repetition count cannot apply to bare literal text; "
                    "put the text in a brace, e.g. {x}[2]"
                )
            literal = "".join(
                _resolve_leaf_escapes(f.literalRun().getText())
                for f in pattern.factor()
            )
            steps.append(compile_template_text(literal, filters))
        else:
            steps.append(builder.compile_pattern(pattern))
    if fixed_point and steps:
        steps[0].fixed_point = True
    return steps


# Whole-file compilation (statements + definitions). Imported at the bottom so
# `parse` and `_parse_script_tree` above are already defined when `_script` (which
# imports them) loads.
from himark.parser._script import (  # noqa: E402
    compile_pipeline,
    compile_script,
    load_script,
)

__all__ = ["parse", "compile_script", "load_script", "compile_pipeline"]
