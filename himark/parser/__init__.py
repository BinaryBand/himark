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
  • `parse_ast(text, variables=None) -> list[RootNode]` — the intermediate typed
    AST, exposed for introspection and the parser golden harness.
"""

from __future__ import annotations

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from himark.models import nodes_typed as t
from himark.models.compiled import Step
from himark.models.exceptions import CompileError
from himark.parser._builder import _AstBuilder
from himark.parser._compiler import compile_pattern, compile_template
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


def parse_ast(
    text: str, variables: dict[str, str] | None = None
) -> list[t.RootNode]:
    """Parse `text` into its ordered step ASTs (`RootNode`s). A template step is a
    single-leaf root carrying the unescaped template text; a query step is the
    resolved pattern tree. This is the intermediate representation — `parse`
    compiles it — kept public for introspection and the parser golden harness."""
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


def _is_template_root(root: t.RootNode) -> bool:
    """A step is a template when its AST is nothing but literal leaves — the same
    proxy the engine used to apply at run time, decided once here at compile time."""
    return all(isinstance(n, t.LeafNode) for n in root.children)


def parse(text: str, variables: dict[str, str] | None = None) -> list[Step]:
    """Parse and **compile** `text` into the product the engine VM consumes: a
    `Program` per query step, a `Template` per template step."""
    return [
        compile_template(root) if _is_template_root(root) else compile_pattern(root)
        for root in parse_ast(text, variables)
    ]