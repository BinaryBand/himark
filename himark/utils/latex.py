"""LaTeX expression → Unicode via the `unicodeit` library.

Supports single-token commands like \\pi, \\alpha, \\infty, etc.
Falls back to the original $expr$ string when the expression is not recognised.
"""

import unicodeit as _unicodeit

from himark.utils.resolver import register


class _LaTeXResolver:
    node_type = "latex"
    metadata_key = "expr"

    def resolve(self, expr: str) -> str:
        """Return Unicode for a LaTeX expression, or '$expr$' if unsupported."""
        result = _unicodeit.replace(expr.strip())
        if result == expr.strip():
            return f"${expr}$"
        return result


register(_LaTeXResolver())
