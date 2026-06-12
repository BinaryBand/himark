"""Phase 1: source preprocessing — macro expansion and implicit root wrapping.

Runs before tokenization (phase 2) on each `=>` step. Two transforms:

  Macros        a text macro (`@i`, `@s`, `@hexi` — see [macros] in macros.toml)
                expands to its HMK source. Alphabet references (`@d`, `@b58`,
                …) are left intact for phase 3 to resolve into alphabet nodes.

  Implicit wrap a step with no top-level construct (`{…}` or `<<…>>`) is wrapped
                in `{…}`, so a bare expression like `a..z` reads as arithmetic
                rather than the literal text "a..z".
"""

import re

from marky.macros import MACROS
from marky.models.exceptions import CompileError

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
    """A non-empty step holding no top-level construct is a bare expression."""
    return bool(step) and "{" not in step and "<<" not in step


def preprocess(step: str) -> str:
    """Expand text macros, then wrap a bare expression step in `{…}`."""
    expanded = _expand_macros(step)
    if _needs_wrap(expanded):
        return "{" + expanded + "}"
    return expanded
