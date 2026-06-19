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

from himark.engine._types import Match
from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError

_MOUSTACHE_RE = re.compile(r"\{\{(.*?)\}\}")
_ACCESSOR_RE = re.compile(r"\s*(\d*)([$#])(\d+(?:\.\d+)*)?\s*")
_FILTER_RE = re.compile(r"\s*(\w+)\s*(?:\(\s*(.*?)\s*\))?\s*")


@dataclass(slots=True)
class _Value:
    """A moustache value flowing through the filter chain. `text` is the surface
    string; `alphabet` (set only for a **group** accessor over a `{x:A:y}` bound)
    lets a value filter read it as a number. A whole-stage accessor, `{{.}}`, and
    any string-filter output carry no alphabet — they are raw strings."""

    text: str
    alphabet: object | None = None


# String filters read the surface text and produce a raw string.
_STRING_FILTERS = {
    "upper": str.upper,
    "lower": str.lower,
    "trim": str.strip,
    "len": lambda s: str(len(s)),
    "hex": lambda s: s.encode().hex(),
}


def _filter_b256(value: _Value, n: int) -> str:
    """The reference's value as `n` big-endian base-256 bytes (latin-1 string)."""
    if value.alphabet is None:
        raise CompileError(
            "b256 needs a value reference (a '{x:A:y}' group), not a raw string"
        )
    iv = value.alphabet.value(value.text)
    try:
        return iv.to_bytes(n, "big").decode("latin-1")
    except OverflowError:
        raise CompileError(f"b256({n}): value {iv} does not fit in {n} bytes") from None


# Value filters read the typed `_Value` (alphabet required) plus literal args.
_VALUE_FILTERS = {
    "b256": _filter_b256,
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


def _eval(inner: str, current: str, stages: list[Match]) -> str:
    """Resolve a moustache body `accessor | filter | …` to its surface string."""
    parts = inner.split("|")
    accessor = parts[0].strip()
    value = _Value(current) if accessor == "." else _resolve(accessor, stages)
    for f in parts[1:]:
        value = _apply_filter(f, value)
    return value.text


def _apply_filter(token: str, value: _Value) -> _Value:
    """Apply one `name` or `name(args)` filter, returning a raw-string `_Value`."""
    m = _FILTER_RE.fullmatch(token)
    if m is None:
        raise CompileError(f"Malformed template filter: '{token.strip()}'")
    name, arg_src = m.group(1), m.group(2)
    if name in _STRING_FILTERS:
        if arg_src:
            raise CompileError(f"Filter '{name}' takes no arguments")
        return _Value(_STRING_FILTERS[name](value.text))
    vfn = _VALUE_FILTERS.get(name)
    if vfn is None:
        raise CompileError(f"Unknown template filter: '{name}'")
    args = [int(a) for a in arg_src.split(",")] if arg_src else []
    return _Value(vfn(value, *args))


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
