"""Render a template step (the right-hand side of `=>`) against the pipeline.

A template step is literal text that may contain **moustache** references —
`{{ i$j }}` interpolates a value from an earlier pipeline stage:

  * `i$j` — capture group `j` of pipeline stage `i`
  * `i$`  — the whole match of stage `i`
  * `i#j` — the repetition count of group `j` of stage `i`

The pipeline index `i` may be omitted to mean the current (feeding) stage, and
the capture index `j` may be omitted with `$` to mean the whole match. Stage 0
is the first pattern in the chain; the feeding stage is the one immediately
before this template. Literal text (everything outside `{{ }}`) is constant.
"""

import re

from marky.engine._types import Match
from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError

_MOUSTACHE_RE = re.compile(r"\{\{(.*?)\}\}")
_ACCESSOR_RE = re.compile(r"\s*(\d*)([$#])(\d*)\s*")


def is_template(tree: t.RootNode) -> bool:
    """True if `tree` is a template step (literal text, possibly with moustache
    references) rather than a matcher — i.e. nothing but literal leaves."""
    return all(isinstance(n, t.LeafNode) for n in tree.children)


def has_refs(tree: t.RootNode) -> bool:
    """True if any leaf carries a `{{ … }}` moustache reference."""
    return any(
        isinstance(n, t.LeafNode) and _MOUSTACHE_RE.search(n.content)
        for n in tree.children
    )


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
    pipe_src, sigil, cap_src = m.groups()

    pipe_idx = int(pipe_src) if pipe_src else len(stages) - 1
    if not 0 <= pipe_idx < len(stages):
        raise CompileError(f"Moustache stage {pipe_idx} is out of range")
    stage = stages[pipe_idx]

    if sigil == "$" and cap_src == "":
        return stage.text  # whole match
    if cap_src == "":
        raise CompileError("A '#' moustache reference needs a capture index")
    cap_idx = int(cap_src)
    if not 0 <= cap_idx < len(stage.captures):
        raise CompileError(
            f"Moustache capture {cap_idx} is out of range for stage {pipe_idx}"
        )
    capture = stage.captures[cap_idx]
    return capture.text if sigil == "$" else str(len(capture.reps))
