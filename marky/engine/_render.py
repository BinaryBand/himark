"""Render a template step (the right-hand side of `=>`) against the pipeline.

A template step is literal text that may contain **moustache** references —
`{{ i$j }}` interpolates a value from an earlier pipeline stage:

  * `i$j` — capture group `j` of pipeline stage `i`
  * `i$`  — the whole match of stage `i`
  * `i#j` — the repetition count of group `j` of stage `i`

The capture part is a dotted **path**: `i$j.k.l` selects stage `i`'s capture
`j`, then descends into its sub-captures (`.k`, `.l`, …) — the nested groups of
a grouping brace `{…{a}{b}…}`. So `1$2.3` is stage 1, capture 2, sub-capture 3.

The pipeline index `i` may be omitted to mean the current (feeding) stage, and
the capture path may be omitted with `$` to mean the whole match. Stage 0 is the
first pattern in the chain; the feeding stage is the one immediately before this
template. Literal text (everything outside `{{ }}`) is constant.
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


def render(
    template_tree: t.RootNode, match: Match, pipeline: list[Match] | None = None
) -> str:
    """Render a template against the pipeline: literal leaves concatenated in
    order, with each `{{ … }}` reference resolved. `pipeline` is the ordered list
    of stage matches (stage 0 first, the feeding match last); it defaults to the
    single `match` when this template has no upstream stages to address."""
    stages = pipeline if pipeline is not None else [match]
    return "".join(
        _expand(n.content, stages)
        for n in template_tree.children
        if isinstance(n, t.LeafNode)
    )


def _expand(text: str, stages: list[Match]) -> str:
    return _MOUSTACHE_RE.sub(lambda mo: _resolve(mo.group(1), stages), text)


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
