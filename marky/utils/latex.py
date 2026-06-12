"""LaTeX expression -> Unicode via the `unicodeit` library.

Supports single-token commands like \\pi, \\alpha, \\infty, etc.
Falls back to the original $expr$ string when the expression is not recognised.
"""

import unicodeit as _unicodeit

from marky.utils.resolver import register


def resolve(expr: str) -> str:
    """Return Unicode for a LaTeX expression, or '$expr$' if unsupported."""
    stripped = expr.strip()
    result = _unicodeit.replace(stripped)
    if result == stripped:
        return f"${expr}$"
    return result


register("latex", resolve)
