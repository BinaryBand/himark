"""Phase 1: source preprocessing — macro expansion and structural rewrites.

Runs before tokenization (phase 2) on each `=>` step. Two transforms:

  Macros        a text macro (`@w`, `@s`, `@hex` — declared in `himark/std.hmk`,
                loaded by `himark/prelude.py`) expands to its HMK source. Macros
                may reference other macros; expansion repeats until stable.

  Rewrites      structural sugar (`himark/parser/rewrites.py`) that runs before
                tokenizing, so the engine only ever sees plain Himark source.

There is **no implicit first-step wrap** a first step must be an
explicit universe — write `{a..z}`, not `a..z`. Auto-wrapping bare text, if
wanted, belongs in a layer-2 preprocess pass.
"""

import re

from himark.models.exceptions import CompileError
from himark.parser import rewrites
from himark.prelude import MACROS

# Only text macros are expanded here; @alphabet references pass through. Longest
# names first so e.g. @hexi wins over @hex, and \b prevents partial-name hits.
_MACRO_RE = (
    re.compile(r"@(" + "|".join(sorted(MACROS, key=len, reverse=True)) + r")\b")
    if MACROS
    else None
)


def _expand_macros(text: str) -> str:
    if _MACRO_RE is None:
        return text
    out = text
    for _ in range(10):
        new = _MACRO_RE.sub(lambda m: MACROS[m.group(1)], out)
        if new == out:
            break
        out = new
    if _MACRO_RE.search(out):
        unresolved = re.findall(r"@\w+", out)
        raise CompileError(f"Unresolved macros (circular or undefined): {unresolved}")
    return out


def preprocess(step: str, *, first: bool = True) -> str:
    """Expand text macros and apply structural rewrites.

    The rewrites (`himark/parser/rewrites.py`) are structural sugar (code rules,
    not prelude declarations) that run before tokenizing, so the engine sees plain
    Himark source. There is no implicit wrap: a first step must be an explicit
    universe (`{a..z}`, not `a..z`). The `first` flag is kept for callers but no
    longer changes the result.
    """
    return rewrites.apply(_expand_macros(step))
