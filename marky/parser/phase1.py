"""Phase 1: source preprocessing — macro expansion and implicit root wrapping.

Runs before tokenization (phase 2) on each `=>` step. Two transforms:

  Macros        a text macro (`@w`, `@s`, `@hex` — see [macros] in macros.toml)
                expands to its HMK source. Macros may reference other macros;
                expansion repeats until the text is stable.

  Implicit wrap a step with no top-level `{…}` construct is wrapped in `{…}`, so
                a bare expression like `a..z` reads as arithmetic rather than
                the literal text "a..z".
"""

import re

from marky.macros import MACROS
from marky.models.exceptions import CompileError
from marky.parser import rewrites

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


def _needs_wrap(step: str) -> bool:
    """A non-empty step holding no `{…}` construct is a bare expression."""
    return bool(step) and "{" not in step


def preprocess(step: str, *, first: bool = True) -> str:
    """Expand text macros, apply advanced rewrites, then wrap a bare expression.

    The rewrites (`marky/parser/rewrites.py`, configured in `macros.toml`) are
    structural sugar that run before tokenizing, so the engine sees only plain
    Himark source. The wrap applies only to the first step (the pattern
    position): a bare step after `=>` is a constant template, rendered as-is.
    """
    expanded = rewrites.apply(_expand_macros(step))
    if first and _needs_wrap(expanded):
        return "{" + expanded + "}"
    return expanded
