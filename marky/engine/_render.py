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

from marky.engine._types import Match
from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError

_MOUSTACHE_RE = re.compile(r"\{\{(.*?)\}\}")
_ACCESSOR_RE = re.compile(r"\s*(\d*)([$#])(\d+(?:\.\d+)*)?\s*")


def is_template(tree: t.RootNode) -> bool:
    """True if `tree` is a template step (literal text, possibly with moustache
    references) rather than a matcher — i.e. nothing but literal leaves."""
    return all(isinstance(n, t.LeafNode) for n in tree.children)


def render(template_tree: t.RootNode, current: str, stages: list[Match]) -> str:
    """Render a template: literal leaves concatenated in order, with each
    `{{ … }}` resolved. `current` is the text flowing into this step (`{{.}}`);
    `stages` is the ordered list of stage matches (`{{ i$j }}`)."""
    return "".join(
        _expand(n.content, current, stages)
        for n in template_tree.children
        if isinstance(n, t.LeafNode)
    )


def _expand(text: str, current: str, stages: list[Match]) -> str:
    def sub(mo: re.Match[str]) -> str:
        if mo.group(1).strip() == ".":
            return current
        return _resolve(mo.group(1), stages)

    return _MOUSTACHE_RE.sub(sub, text)


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

    # Walk the dotted path: the first index selects a top-level capture, each
    # further index descends into that capture's sub-captures (grouping braces).
    captures = stage.captures
    capture = None
    for depth, idx in enumerate(int(i) for i in path_src.split(".")):
        if not 0 <= idx < len(captures):
            where = f"stage {pipe_idx}" if depth == 0 else f"depth {depth} of {path_src!r}"
            raise CompileError(f"Moustache index {idx} is out of range for {where}")
        capture = captures[idx]
        captures = capture.subs
    return capture.text if sigil == "$" else str(len(capture.reps))
