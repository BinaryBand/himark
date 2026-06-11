"""Phase 0: source preprocessing — macro expansion and implicit root wrapping.

Runs before tokenization (phase 2) on each `=>` step. Two transforms:

  Macros        `@name` expands to its definition text. Simple alphabets expand
                to their range form (`@dec` → `0..9`). Alphabets whose value is
                an exclusion set or a codepoint range (`b58`, `b85`, `ascii`,
                `uni`) expand to their bare alphabet token instead — textual
                range expansion would corrupt value-range materialization, since
                `_alpha_str` ignores exclusions and cannot size a codepoint set.

  Implicit wrap a step with no top-level construct (`{…}` or `<<…>>`) is wrapped
                in `{…}`, so a bare expression like `a..z` reads as arithmetic
                rather than the literal text "a..z".
"""

import re

MACROS: dict[str, str] = {
    "dec": "0..9",
    "hex": "0..9,a..f",
    "HEX": "0..9,A..F",
    "hexi": "0..9,a<->A..f<->F",
    "b32": "0..9,a..v",
    "b64": "A..Z,a..z,0..9,+,/",
    "i": "0..9,a<->A..z<->Z",
    "s": "\n,\r, ,\t",
    # Value-range materialization is unsafe for these, so defer to the engine's
    # named alphabet (the `@` is simply dropped).
    "b58": "b58",
    "b85": "b85",
    "ascii": "ascii",
    "uni": "uni",
}

# Longest names first so e.g. @hexi wins over @hex; \b keeps @dec from firing
# inside @decimal-like text.
_MACRO_RE = re.compile(r"@(" + "|".join(sorted(MACROS, key=len, reverse=True)) + r")\b")


def _expand_macros(text: str) -> str:
    return _MACRO_RE.sub(lambda m: MACROS[m.group(1)], text)


def _needs_wrap(step: str) -> bool:
    """A non-empty step holding no top-level construct is a bare expression."""
    return bool(step) and "{" not in step and "<<" not in step


def preprocess(step: str) -> str:
    """Expand macros, then wrap a bare expression step in `{…}`."""
    expanded = _expand_macros(step)
    if _needs_wrap(expanded):
        return "{" + expanded + "}"
    return expanded
