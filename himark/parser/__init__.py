"""The swappable parsing frontend — the `Parser` seam.

Callers use `parse()` for the active backend. Swap the backend via
`set_parser` / `using_parser`; all orchestration above is backend-agnostic.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from himark.models import nodes_typed as t
from himark.parser.interface import Parser
from himark.parser.python import PythonParser
from himark.parser.rust import RUST_PARSER_AVAILABLE, RustParser

__all__ = [
    "parse",
    "set_parser",
    "get_parser",
    "using_parser",
    "Parser",
    "PythonParser",
    "RustParser",
    "RUST_PARSER_AVAILABLE",
]

_parser: Parser = PythonParser()


def parse(source: str) -> list[t.RootNode]:
    """Run the active parser backend and return one tree per `=>` step."""
    return _parser.parse(source)


def set_parser(parser: Parser) -> None:
    """Install `parser` as the active backend for all subsequent calls."""
    global _parser
    _parser = parser


def get_parser() -> Parser:
    """The currently installed parsing backend."""
    return _parser


@contextmanager
def using_parser(parser: Parser) -> Iterator[Parser]:
    """Install `parser` for the duration of the `with` block, restoring the
    previous backend on exit (even on error)."""
    global _parser
    prev = _parser
    _parser = parser
    try:
        yield parser
    finally:
        _parser = prev
