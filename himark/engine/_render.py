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
from himark.engine.backend.alphabet import Alphabet, RangeAlphabet
from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError

_MOUSTACHE_RE = re.compile(r"\{\{(.*?)\}\}")
_ACCESSOR_RE = re.compile(r"\s*(\d*)([$#])(\d+(?:\.\d+)*)?\s*")
_FILTER_RE = re.compile(r"\s*(\w+)\s*(?:\(\s*(.*?)\s*\))?\s*")


@dataclass(slots=True)
class _Value:
    """A moustache value flowing through an expression and its filter chain. `text`
    is the surface string; `alphabet` (set only for a **group** accessor over a
    `{A:x..y}` bound) lets a value filter read it as a number. `num` is set for a
    **computed** integer (`$0 + 1`, `2 * #0`) — a `Z` result with no alphabet that
    render-casts to decimal. A whole-stage accessor, `{{.}}`, a string literal, and
    any string-filter output carry neither — they are raw strings."""

    text: str
    alphabet: Alphabet | RangeAlphabet | None = None
    num: int | None = None


def _to_int(v: _Value) -> int:
    """The integer value of `v` for arithmetic: a computed `num`, else a typed
    group read through its alphabet. A raw string has no value — a compile error."""
    if v.num is not None:
        return v.num
    if v.alphabet is not None:
        return v.alphabet.value(v.text)
    raise CompileError(
        f"arithmetic needs a value (a typed-alphabet group or an integer), "
        f"not the raw string {v.text!r}"
    )


def _to_text(v: _Value) -> str:
    """The surface text of `v` — a computed integer render-casts to decimal (`@d`)."""
    return str(v.num) if v.num is not None else v.text


def _as_bytes(s: str, filt: str) -> bytes:
    """The byte string of `s` — one byte per code point, matching b256's latin-1
    output so a byte string round-trips (`… | b256(n) | uint`)."""
    try:
        return s.encode("latin-1")
    except UnicodeEncodeError:
        raise CompileError(
            f"{filt} operates on a byte string (code points 0-255); "
            "pipe through b256 first"
        ) from None


def _indent(s: str) -> str:
    """Prefix every line of `s` with one tab. A line filter (not a scalar one): it
    reshapes multi-line text rather than the whole string at once, which is what
    lets indentation **accumulate** under an inside-out wrap — text re-indented by
    each enclosing pass ends up as deep as its nesting (see scripts/html_format.hmk)."""
    return "" if s == "" else "\t" + s.replace("\n", "\n\t")


def _arg(nums: list[int], name: str) -> int:
    """The single integer argument a width/count filter needs, or a clear error."""
    if len(nums) != 1:
        raise CompileError(f"Filter '{name}' needs exactly one integer argument")
    return nums[0]


def _filter_b256(value: _Value, nums: list[int], little: bool) -> str:
    """The reference's value as base-256 bytes (latin-1 string), big-endian unless
    `le`. The only **value** filter — it needs the alphabet the reference matched
    under. Width is the `b256(n)` argument."""
    n = _arg(nums, "b256")
    if value.num is not None:
        iv = value.num
    elif value.alphabet is not None:
        iv = value.alphabet.value(value.text)
    else:
        raise CompileError(
            "b256 needs a value (a '{A:x..y}' group or an arithmetic result), "
            "not a raw string"
        )
    try:
        return iv.to_bytes(n, "little" if little else "big").decode("latin-1")
    except OverflowError:
        raise CompileError(f"b256({n}): value {iv} does not fit in {n} bytes") from None


def _filter_uint(value: _Value, nums: list[int], little: bool) -> str:
    """A byte string back to an unsigned integer (decimal text), big-endian unless
    `le` — the inverse of `b256`, so `v | b256(n) | uint` round-trips."""
    raw = _as_bytes(value.text, "uint")
    return str(int.from_bytes(raw, "little" if little else "big"))


# Every filter maps `(value, nums, little)` to a raw string: `nums` are the integer
# arguments, `little` is set by an `le` flag (cleared by `be`). The spec's core set
# is `pad`/`b256`/`uint` — the value model's two byte projections plus output
# padding; hashes and other derived transforms are deferred to a layer above these
# primitives. `upper`/`lower`/`trim`/`indent`/`len` are convenience string filters.
_FILTERS = {
    "upper": lambda v, nums, little: v.text.upper(),
    "lower": lambda v, nums, little: v.text.lower(),
    "trim": lambda v, nums, little: v.text.strip(),
    "indent": lambda v, nums, little: _indent(v.text),
    "len": lambda v, nums, little: str(len(v.text)),
    "pad": lambda v, nums, little: v.text.rjust(_arg(nums, "pad"), "0"),
    "b256": _filter_b256,
    "uint": _filter_uint,
}


def is_template(tree: t.RootNode) -> bool:
    """True if `tree` is a template step (literal text, possibly with moustache
    references) rather than a matcher — i.e. nothing but literal leaves."""
    return all(isinstance(n, t.LeafNode) for n in tree.children)


def render(
    template_tree: t.RootNode, current: str, stages: list[Match]
) -> tuple[str, str, tuple[int, int] | None]:
    """Render a template into `(full, payload, span)`. `full` is the whole render
    (what lands in the document); `payload` is the text that flows downstream and
    `span` its `(start, end)` within `full`. With no `{{> }}` marker the payload
    is the whole render and `span` is None. `current` is `{{.}}`."""
    out: list[str] = []
    length = 0
    payload: tuple[str, int] | None = None
    for n in template_tree.children:
        if not isinstance(n, t.LeafNode):
            continue
        text = n.content
        last = 0
        for mo in _MOUSTACHE_RE.finditer(text):
            literal = text[last : mo.start()]
            out.append(literal)
            length += len(literal)
            inner = mo.group(1).strip()
            is_payload = inner.startswith(">")
            if is_payload:
                inner = inner[1:].strip()
            value = _eval(inner, current, stages)
            if is_payload:
                if payload is not None:
                    raise CompileError("At most one '{{> }}' marker per template")
                payload = (value, length)
            out.append(value)
            length += len(value)
            last = mo.end()
        tail = text[last:]
        out.append(tail)
        length += len(tail)
    full = "".join(out)
    if payload is None:
        return full, full, None
    ptext, pstart = payload
    return full, ptext, (pstart, pstart + len(ptext))


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
    | (?P<star>\*)
    | (?P<plus>\+)
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
    """Recursive descent over a moustache expression. Precedence tightest to
    loosest: `*`, `+`, `|` (filter), `,` (concat, parentheses only). Each rule
    returns a `_Value`; arithmetic reads `Z` values and yields a computed integer,
    `,` concatenates surface text, `|` applies a filter."""

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
        value = self._add()
        while self._peek() == "pipe":
            self.i += 1
            if self._peek() != "filter":
                raise CompileError("'|' must be followed by a filter")
            value = _apply_filter(self.toks[self.i][1], value)
            self.i += 1
        return value

    def _add(self) -> _Value:
        value = self._mul()
        while self._peek() == "plus":
            self.i += 1
            n = _to_int(value) + _to_int(self._mul())
            value = _Value(str(n), num=n)
        return value

    def _mul(self) -> _Value:
        value = self._atom()
        while self._peek() == "star":
            self.i += 1
            n = _to_int(value) * _to_int(self._atom())
            value = _Value(str(n), num=n)
        return value

    def _atom(self) -> _Value:
        kind, text = self.toks[self.i] if self.i < len(self.toks) else ("", "")
        if kind == "lparen":
            return self._parens()
        self.i += 1
        if kind == "string":
            return _Value(text[1:-1])  # a raw string
        if kind == "int":
            return _Value(text, num=int(text))
        if kind == "accessor":
            return _Value(self.current) if text == "." else _resolve(text, self.stages)
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
        return _Value("".join(_to_text(m) for m in members))  # concatenation


def _eval(inner: str, current: str, stages: list[Match]) -> str:
    """Evaluate a moustache body — an expression over accessors, integer/string
    literals, `*`/`+` arithmetic, `,` concatenation, and `|` filters — to text."""
    return _to_text(_ExprParser(_tokenize(inner), current, stages).parse())


def _apply_filter(token: str, value: _Value) -> _Value:
    """Apply one `name` or `name(args)` filter, returning a raw-string `_Value`.
    Arguments are integers (width/count) plus an optional `le`/`be` endianness
    flag (default big-endian)."""
    m = _FILTER_RE.fullmatch(token)
    if m is None:
        raise CompileError(f"Malformed template filter: '{token.strip()}'")
    name, arg_src = m.group(1), m.group(2)
    fn = _FILTERS.get(name)
    if fn is None:
        raise CompileError(f"Unknown template filter: '{name}'")
    nums: list[int] = []
    little = False
    for a in (p.strip() for p in arg_src.split(",")) if arg_src else ():
        if a in ("le", "be"):
            little = a == "le"
            continue
        try:
            nums.append(int(a))
        except ValueError:
            raise CompileError(
                f"Filter '{name}' argument must be an integer or 'le'/'be': '{a}'"
            ) from None
    return _Value(fn(value, nums, little))


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
        return _Value(str(len(capture.reps)))  # repetition count — a number
    # A group accessor carries the alphabet it matched under (its value type).
    return _Value(capture.text, capture.alphabet)
