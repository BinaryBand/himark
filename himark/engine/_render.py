"""Render a template step (the right-hand side of `=>`) against the pipeline.

A template step is literal text that may contain **moustache** references:

  * `{{ . }}` — the whole text flowing into this step. After a query it is the
    matched text; after a template it is that template's render — so `{{.}}`
    composes through templates (each wraps the previous one's output).
  * `{{ i$j }}` — capture group `j` of pipeline stage `i`
  * `{{ i$ }}`  — the whole match of stage `i`
  * `{{ i#j }}` — the repetition count of group `j` of stage `i`

The capture part is a dotted **path**: `i$j.k.l` selects stage `i`'s capture
`j`, then descends into its sub-captures (`.k`, `.l`, …) — the nested groups of
a grouping brace `{…{a}{b}…}`. So `1$2.3` is stage 1, capture 2, sub-capture 3.

Stages are numbered by `=>` position from 0; a template stage carries its render
but no captures. The pipeline index `i` may be omitted to mean the current stage,
and the capture path may be omitted with `$` to mean the whole match. Literal text
(everything outside `{{ }}`) is constant.
"""

import re
from dataclasses import dataclass

from himark.engine.backend import Match
from himark.models.compiled import Moustache, Template
from himark.models.exceptions import CompileError

_ACCESSOR_RE = re.compile(r"\s*(\d*)([$#])(\d+(?:\.\d+)*)?\s*")
_FILTER_RE = re.compile(r"\s*(\w+)\s*(?:\(\s*(.*?)\s*\))?\s*")


@dataclass(slots=True)
class _Value:
    """A moustache value flowing through an expression and its filter chain -- a
    surface string. (The matcher carries the value model; the template layer only
    ever moves text now that byte filters and arithmetic are gone.)"""

    text: str


def _indent(s: str) -> str:
    """Prefix every line of `s` with one tab. A line filter (not a scalar one): it
    reshapes multi-line text rather than the whole string at once, which is what
    lets indentation **accumulate** under an inside-out wrap — text re-indented by
    each enclosing pass ends up as deep as its nesting (see scripts/html_format.hmk)."""
    return "" if s == "" else "\t" + s.replace("\n", "\n\t")


# The native filter set — closed and string-only: each maps a `_Value` to a raw
# string. `trim` strips surrounding whitespace; `indent` tabs every line. Byte
# projections and arithmetic were removed (no live consumer), so a filter takes no
# arguments and the template layer only ever moves text.
_FILTERS = {
    "trim": lambda v: v.text.strip(),
    "indent": lambda v: _indent(v.text),
}


def render(
    template: Template, current: str, stages: list[Match]
) -> tuple[str, list[tuple[int, int]] | None]:
    """Render a `Template` into `(full, spans)`. `full` is the whole render -- what
    **lands** in the document. `spans` are the `(start, end)` of each moustache's
    value within `full`: each is a **branch** that flows downstream independently,
    spliced back over its own span, with the literal text between (decoration) kept
    -- the same splice a query runs, with each moustache playing the part of a match.
    A template with **no** moustaches has nothing to single out, so its whole render
    flows as one branch -- signalled by `spans` being None. `current` is `{{.}}`.

    The literal/moustache split was done at compile time (`compile_template`); this
    only fills each moustache's value in against the pipeline stages."""
    out: list[str] = []
    length = 0
    spans: list[tuple[int, int]] = []
    for part in template.parts:
        if isinstance(part, Moustache):
            value = _eval(part.body, current, stages)
            start = length
            out.append(value)
            length += len(value)
            spans.append((start, length))
        else:
            out.append(part)
            length += len(part)
    full = "".join(out)
    return full, (spans or None)


# One expression token. Order matters: a string and an accessor (`0$0`, `$`, `.`)
# are tried before a bare integer or filter name so they are not mis-split.
_EXPR_TOKEN_RE = re.compile(
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


def _tokenize(s: str) -> list[tuple[str, str]]:
    """Lex a moustache expression into `(kind, text)` tokens, dropping whitespace."""
    toks: list[tuple[str, str]] = []
    pos = 0
    while pos < len(s):
        m = _EXPR_TOKEN_RE.match(s, pos)
        if m is None:
            raise CompileError(
                f"Unexpected character {s[pos]!r} in moustache expression {{{{{s}}}}}"
            )
        pos = m.end()
        if m.lastgroup != "ws":
            toks.append((m.lastgroup, m.group()))
    return toks


class _ExprParser:
    """Recursive descent over a moustache expression: an operand (accessor, int or
    string literal, or a parenthesized group) followed by zero or more `| filter`
    pipes; inside parens, `,` concatenates surface text. Each rule returns a
    `_Value` (raw text)."""

    def __init__(self, toks: list[tuple[str, str]], current: str, stages):
        self.toks = toks
        self.i = 0
        self.current = current
        self.stages = stages

    def _peek(self) -> str:
        return self.toks[self.i][0] if self.i < len(self.toks) else ""

    def parse(self) -> _Value:
        value = self._pipe()
        if self.i != len(self.toks):
            raise CompileError(
                f"Unexpected '{self.toks[self.i][1]}' in moustache expression"
            )
        return value

    def _pipe(self) -> _Value:
        value = self._atom()
        while self._peek() == "pipe":
            self.i += 1
            if self._peek() != "filter":
                raise CompileError("'|' must be followed by a filter")
            value = _apply_filter(self.toks[self.i][1], value)
            self.i += 1
        return value

    def _atom(self) -> _Value:
        kind, text = self.toks[self.i] if self.i < len(self.toks) else ("", "")
        if kind == "lparen":
            return self._parens()
        self.i += 1
        if kind == "string":
            return _Value(text[1:-1])  # a raw string
        if kind == "int":
            return _Value(text)
        if kind == "accessor":
            if text == ".":
                return _Value(self.current)
            return _resolve(text, self.stages)
        raise CompileError(f"Expected a value in moustache expression, got {text!r}")

    def _parens(self) -> _Value:
        self.i += 1  # consume '('
        members = [self._pipe()]
        while self._peek() == "comma":
            self.i += 1
            members.append(self._pipe())
        if self._peek() != "rparen":
            raise CompileError("Unclosed '(' in moustache expression")
        self.i += 1  # consume ')'
        if len(members) == 1:
            return members[0]  # plain grouping
        return _Value("".join(m.text for m in members))  # concatenation


def _eval(inner: str, current: str, stages: list[Match]) -> str:
    """Evaluate a moustache body — accessors, integer/string literals, `,`
    concatenation, and `|` filters — to text."""
    return _ExprParser(_tokenize(inner), current, stages).parse().text


def _apply_filter(token: str, value: _Value) -> _Value:
    """Apply one named filter, returning a raw-string `_Value`. The filter set is
    closed and native (`trim`, `indent`); an unknown name or any argument is a
    compile error."""
    m = _FILTER_RE.fullmatch(token)
    if m is None:
        raise CompileError(f"Malformed template filter: '{token.strip()}'")
    name, arg_src = m.group(1), m.group(2)
    fn = _FILTERS.get(name)
    if fn is None:
        raise CompileError(f"Unknown template filter: '{name}'")
    if arg_src:
        raise CompileError(f"Filter '{name}' takes no arguments")
    return _Value(fn(value))


def _resolve(expr: str, stages: list[Match]) -> _Value:
    m = _ACCESSOR_RE.fullmatch(expr)
    if m is None:
        raise CompileError(f"Unsupported moustache reference: {{{{{expr}}}}}")
    pipe_src, sigil, path_src = m.groups()

    pipe_idx = int(pipe_src) if pipe_src else len(stages) - 1
    if not 0 <= pipe_idx < len(stages):
        raise CompileError(f"Moustache stage {pipe_idx} is out of range")
    stage = stages[pipe_idx]

    if sigil == "$" and not path_src:
        return _Value(stage.text)  # whole match — a raw string, no alphabet
    if not path_src:
        raise CompileError("A '#' moustache reference needs a capture index")

    path = tuple(int(i) for i in path_src.split("."))
    capture = stage.capture_at(path)
    if capture is None:
        raise CompileError(f"Moustache index out of range in {{{{{expr}}}}}")
    if sigil == "#":
        return _Value(str(len(capture.reps)))  # repetition count
    return _Value(capture.text)
