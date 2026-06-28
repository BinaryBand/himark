"""Phase 1: source preprocessing — variable resolution and structural rewrites.

Runs before tokenization (phase 2) on each `=>` step. Two transforms:

  Variables     a `@name` variable (`@w`, `@s`, `@hex` — declared in
                `himark/std.hmk`, loaded by `himark/prelude.py`) resolves to its
                named Himark fragment, as if inlined; resolution repeats until
                stable (a variable may reference another). A `@name` inside a
                `"…"` template is literal text — a template is opaque (HMK.md
                §Macros, "Templates are opaque"), so resolution skips a template.

  Rewrites      structural sugar (`himark/parser/rewrites.py`) that runs before
                tokenizing, so the engine only ever sees plain Himark source.

There is **no implicit first-step wrap** a first step must be an
explicit universe — write `{a..z}`, not `a..z`. Auto-wrapping bare text, if
wanted, belongs in a layer-2 preprocess pass.
"""

import functools
import re

from himark.models.exceptions import CompileError
from himark.parser import rewrites
from himark.prelude import MACROS


@functools.lru_cache(maxsize=None)
def _macro_re(names: frozenset[str]) -> "re.Pattern[str] | None":
    """The expansion regex for a macro name set, cached per set. Longest names
    first so e.g. @hexi wins over @hex, and `\\b` prevents partial-name hits."""
    if not names:
        return None
    return re.compile(r"@(" + "|".join(sorted(names, key=len, reverse=True)) + r")\b")


def _expand_macros(text: str, extra: dict[str, str] | None = None) -> str:
    """Expand `@name` text macros to a fixed point. `extra` overlays the prelude
    `MACROS` with script-local definitions (see `tools/precompiled.compile_script`),
    which may reference each other or the prelude — the loop resolves transitively."""
    table = MACROS if not extra else {**MACROS, **extra}
    regex = _macro_re(frozenset(table))
    if regex is None:
        return text
    out = text
    for _ in range(10):
        new = regex.sub(lambda m: table[m.group(1)], out)
        if new == out:
            break
        out = new
    if regex.search(out):
        unresolved = re.findall(r"@\w+", out)
        raise CompileError(f"Unresolved macros (circular or undefined): {unresolved}")
    return out


def preprocess(step: str, *, macros: dict[str, str] | None = None) -> str:
    """Resolve `@name` variables and apply structural rewrites.

    `macros` overlays the prelude `MACROS` with script-local `@name` definitions.
    A `@name` resolves to its named fragment as if inlined; a `@name` inside a
    `"…"` template is **literal text**, never resolved — a template is opaque
    (HMK.md §Macros). The rewrites (`himark/parser/rewrites.py`) are structural
    sugar (code rules, not prelude declarations) that run before tokenizing, so the
    engine sees plain Himark source. There is no implicit wrap: a first step must be
    an explicit universe (`{a..z}`, not `a..z`).
    """
    stripped = step.strip()
    if len(stripped) >= 2 and stripped.startswith('"') and stripped.endswith('"'):
        # A `"…"` template is opaque — `@name` inside it is literal text, never
        # resolved. Only the structural rewrites apply (they do not touch a
        # template's interior); variable resolution is skipped for the whole step.
        return rewrites.apply(step)
    return rewrites.apply(_expand_macros(step, macros))
