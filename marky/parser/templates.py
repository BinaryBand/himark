"""Template-expression parsing — the `{{...}}` reference sub-language.

Resolves the content of a double-brace node into a typed template node:
`{{.}}` full match, `{{N}}`/`{{N.M}}` group refs, `{{N..M}}` span refs,
`{{#N}}` count refs, `{{:emoji:}}`, and `{{$latex$}}`.
"""

import re

from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError

_SPAN_RE = re.compile(r"^(\d+(?:\.\d+)?)\.\.(\d+(?:\.\d+)?)$")
_GROUP_RE = re.compile(r"^\d+(?:\.\d+)?$")
_EMOJI_RE = re.compile(r"^:([^:]+):$")
_LATEX_RE = re.compile(r"^\$(.+)\$$", re.DOTALL)
_COUNT_REF_RE = re.compile(r"^#(\d+)$")


def _capture_path(dotted: str) -> list[int]:
    return [int(p) for p in dotted.split(".")]


def parse_template_expr(content: str) -> t.TemplateNode:
    expr = content.strip()

    if expr == ".":
        return t.FullMatchNode()

    m = _COUNT_REF_RE.match(expr)
    if m:
        return t.CountRefNode(group=int(m.group(1)))

    m = _SPAN_RE.match(expr)
    if m:
        return t.SpanRefNode(
            start=_capture_path(m.group(1)),
            end=_capture_path(m.group(2)),
        )

    if _GROUP_RE.match(expr):
        return t.GroupRefNode(index=_capture_path(expr))

    m = _EMOJI_RE.match(expr)
    if m:
        return t.EmojiNode(code=m.group(1))

    m = _LATEX_RE.match(expr)
    if m:
        return t.LatexNode(expr=m.group(1))

    raise CompileError(f"Unknown template expression: {{{{{content}}}}}")
