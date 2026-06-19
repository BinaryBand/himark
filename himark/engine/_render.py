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

from himark.engine._types import Match
from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError

_MOUSTACHE_RE = re.compile(r"\{\{(.*?)\}\}")
_ACCESSOR_RE = re.compile(r"\s*(\d*)([$#])(\d+(?:\.\d+)*)?\s*")

# Standard-library template filters: pure, deterministic transforms applied with
# `{{ accessor | f | g }}`. Hashing / base-conversion helpers are deferred.
_FILTERS = {
    "upper": str.upper,
    "lower": str.lower,
    "trim": str.strip,
    "len": lambda s: str(len(s)),
    "hex": lambda s: s.encode().hex(),
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
    """Resolve a moustache body `accessor | filter | …`."""
    parts = inner.split("|")
    accessor = parts[0].strip()
    value = current if accessor == "." else _resolve(accessor, stages)
    for f in parts[1:]:
        name = f.strip()
        fn = _FILTERS.get(name)
        if fn is None:
            raise CompileError(f"Unknown template filter: '{name}'")
        value = fn(value)
    return value


def _resolve(expr: str, stages: list[Match]) -> str:
    m = _ACCESSOR_RE.fullmatch(expr)
    if m is None:
        raise CompileError(f"Unsupported moustache reference: {{{{{expr}}}}}")
    pipe_src, sigil, path_src = m.groups()

    pipe_idx = int(pipe_src) if pipe_src else len(stages) - 1
    if not 0 <= pipe_idx < len(stages):
        raise CompileError(f"Moustache stage {pipe_idx} is out of range")
    stage = stages[pipe_idx]

    if sigil == "$" and not path_src:
        return stage.text  # whole match
    if not path_src:
        raise CompileError("A '#' moustache reference needs a capture index")

    path = tuple(int(i) for i in path_src.split("."))
    capture = stage.capture_at(path)
    if capture is None:
        raise CompileError(f"Moustache index out of range in {{{{{expr}}}}}")
    return capture.text if sigil == "$" else str(len(capture.reps))
