"""LaTeX expression → Unicode via the `unicodeit` library.

Supports single-token commands like \\pi, \\alpha, \\infty, etc.
Falls back to the original $expr$ string when the expression is not recognised.
"""

import unicodeit as _unicodeit


def resolve(expr: str) -> str:
    """Return Unicode for a LaTeX expression, or '$expr$' if unsupported."""
    result = _unicodeit.replace(expr.strip())
    # unicodeit returns the input unchanged when it cannot convert
    if result == expr.strip():
        return f"${expr}$"
    return result
