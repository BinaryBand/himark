"""Compile a moustache body (`{{ … }}`) into an `Expr` tree — the *compiler* for
the template side, the mirror of `_compiler` for the query side.

A moustache body is a tiny expression: accessors (`.` the current text, `$i`/`#i`
captures, `2$0.1` a cross-stage sub-capture), string/integer literals,
parenthesised `,`-concatenation, and `|` filter pipes. Two operators, tightest
to loosest: `|` (filter) then `,` (concat, parens only); both left-associative.

This used to live in the renderer and run on *every* render. Now the parser does
it once, so the engine only evaluates the `Expr` (see `himark.engine._render`).
Filter *names* are kept as-is — the renderer owns the (small, fixed) filter set —
but a filter with arguments is rejected here, since filters take none.
"""

from __future__ import annotations

import re

from himark.models.compiled import (
    ExConcat,
    ExCurrent,
    ExFilter,
    ExLit,
    ExRef,
    Expr,
)
from himark.models.exceptions import CompileError

# One expression token. Order matters: a string and an accessor (`0$0`, `$`, `.`)
# are tried before a bare integer or filter name so they are not mis-split.
_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<string>"[^"]*")
    | (?P<accessor>\d*[$#]\d+(?:\.\d+)*|\d*[$#]|\.)
    | (?P<filter>[A-Za-z_]\w*\s*\([^)]*\)|[A-Za-z_]\w*)
    | (?P<int>\d+)
    | (?P<lparen>\()
    | (?P<rparen>\))
    | (?P<pipe>\|)
    | (?P<comma>,)
    """,
    re.X,
)

_ACCESSOR_RE = re.compile(r"\s*(\d*)([$#])(\d+(?:\.\d+)*)?\s*")
_FILTER_RE = re.compile(r"\s*(\w+)\s*(?:\(\s*(.*?)\s*\))?\s*")


def parse_expr(body: str) -> Expr:
    """Compile a moustache body into an `Expr`. Raises `CompileError` on a malformed
    expression — caught now, at compile time, instead of on first render."""
    return _ExprParser(_tokenize(body)).parse()


def _tokenize(s: str) -> list[tuple[str, str]]:
    """Lex a moustache expression into `(kind, text)` tokens, dropping whitespace."""
    toks: list[tuple[str, str]] = []
    pos = 0
    while pos < len(s):
        m = _TOKEN_RE.match(s, pos)
        if m is None:
            raise CompileError(
                f"Unexpected character {s[pos]!r} in moustache expression {{{{{s}}}}}"
            )
        pos = m.end()
        if m.lastgroup != "ws":
            toks.append((m.lastgroup, m.group()))
    return toks


def _filter_name(token: str) -> str:
    """The clean filter name from a filter token, rejecting any arguments (filters
    take none). Existence of the name is the renderer's call, at apply time."""
    m = _FILTER_RE.fullmatch(token)
    if m is None:
        raise CompileError(f"Malformed template filter: '{token.strip()}'")
    name, arg_src = m.group(1), m.group(2)
    if arg_src:
        raise CompileError(f"Filter '{name}' takes no arguments")
    return name


def _parse_ref(text: str) -> ExRef:
    """Compile a non-`.` accessor (`$i`, `#i`, `2$0.1`, `$`) into an `ExRef`."""
    m = _ACCESSOR_RE.fullmatch(text)
    if m is None:
        raise CompileError(f"Unsupported moustache reference: {{{{{text}}}}}")
    stage_src, sigil, path_src = m.groups()
    is_count = sigil == "#"
    if not path_src:
        if is_count:
            raise CompileError("A '#' moustache reference needs a capture index")
        path = None  # `$` / `N$` — the stage's whole text
    else:
        path = tuple(int(i) for i in path_src.split("."))
    stage = int(stage_src) if stage_src else None
    return ExRef(stage=stage, is_count=is_count, path=path)


class _ExprParser:
    """Recursive descent over the token stream: an operand (accessor, literal, or a
    parenthesised group) followed by zero or more `| filter` pipes; inside parens,
    `,` concatenates. Each rule returns an `Expr` node."""

    def __init__(self, toks: list[tuple[str, str]]) -> None:
        self.toks = toks
        self.i = 0

    def _peek(self) -> str:
        return self.toks[self.i][0] if self.i < len(self.toks) else ""

    def parse(self) -> Expr:
        value = self._pipe()
        if self.i != len(self.toks):
            raise CompileError(
                f"Unexpected '{self.toks[self.i][1]}' in moustache expression"
            )
        return value

    def _pipe(self) -> Expr:
        value = self._atom()
        while self._peek() == "pipe":
            self.i += 1
            if self._peek() != "filter":
                raise CompileError("'|' must be followed by a filter")
            value = ExFilter(value, _filter_name(self.toks[self.i][1]))
            self.i += 1
        return value

    def _atom(self) -> Expr:
        kind, text = self.toks[self.i] if self.i < len(self.toks) else ("", "")
        if kind == "lparen":
            return self._parens()
        self.i += 1
        if kind == "string":
            return ExLit(text[1:-1])  # strip the quotes
        if kind == "int":
            return ExLit(text)
        if kind == "accessor":
            return ExCurrent() if text == "." else _parse_ref(text)
        raise CompileError(f"Expected a value in moustache expression, got {text!r}")

    def _parens(self) -> Expr:
        self.i += 1  # consume '('
        members = [self._pipe()]
        while self._peek() == "comma":
            self.i += 1
            members.append(self._pipe())
        if self._peek() != "rparen":
            raise CompileError("Unclosed '(' in moustache expression")
        self.i += 1  # consume ')'
        return members[0] if len(members) == 1 else ExConcat(members)
