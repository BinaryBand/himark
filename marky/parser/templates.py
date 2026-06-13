"""Template-expression parsing — the `{{...}}` reference sub-language.

The only reference is `{{.}}`, the full matched text. (Numbered, sub, span, and
count captures were dropped; a template renders the whole match or nothing.)
"""

from marky.models import nodes_typed as t
from marky.models.exceptions import CompileError


def parse_template_expr(content: str) -> t.TemplateNode:
    if content.strip() == ".":
        return t.FullMatchNode()
    raise CompileError(
        f"Unknown template expression: {{{{{content}}}}} "
        f"(only {{{{.}}}}, the full match, is supported)"
    )
