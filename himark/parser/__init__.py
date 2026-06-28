"""ANTLR-backed front-end for the Himark parser.

Pipeline:
  • ANTLR lexes/parses the input into a validated CST.
  • `_AstBuilder` (a `GRAMMARVisitor` subclass in `_builder.py`) walks the CST
    and builds the AST (`himark.models.nodes_typed`). Each labeled grammar
    alternative has a `visit*` method — no manual `isinstance` dispatch.
  • Free helpers (escapes, whitespace, variables) live in `_helpers.py`.

Entry point: `parse(text, variables=None) -> list[RootNode]`
"""

from __future__ import annotations

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError
from himark.parser._builder import _AstBuilder
from himark.parser._helpers import (
    strip_insignificant_ws,
    text_expand_variables,
    unescape,
)


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


def parse(text: str, variables: dict[str, str] | None = None) -> list[t.RootNode]:
    """ANTLR-backed `parse`, signature-compatible with `himark.parser.parse`."""
    from himark.prelude import VARIABLES

    builder = _AstBuilder({**VARIABLES, **(variables or {})})
    roots: list[t.RootNode] = []
    text = strip_insignificant_ws(text)
    for step in _parse_snippet_tree(text).statement().step():
        template = step.template()
        if template is not None:
            quoted = template.getText()
            roots.append(
                t.RootNode(children=[t.LeafNode(content=unescape(quoted[1:-1]))])
            )
            continue
        pattern = step.pattern()
        if variables:
            src = text[step.start.start : step.stop.stop + 1]
            pattern = _parse_pattern_tree(
                text_expand_variables(src, variables)
            ).pattern()
        roots.append(builder.resolve_pattern(pattern))
    return roots