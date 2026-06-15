"""Render a template step (the right-hand side of `=>`) against a match.

With references removed from the language, a template step is plain literal
text: its rendered output is the same constant for every match (the matched
text itself is produced by the default, reference-free `=>` path in
`engine/__init__.py`).
"""

from marky.engine._types import Match
from marky.models import nodes_typed as t


def is_template(tree: t.RootNode) -> bool:
    """True if `tree` is a template step (constant output) rather than a matcher.

    A step is a template when it has no matchable brace groups — i.e. nothing
    but literal leaves (`{\\<} =>+ &lt;`)."""
    return all(isinstance(n, t.LeafNode) for n in tree.children)


def render(template_tree: t.RootNode, match: Match) -> str:
    """Render a template against a match: literal leaves concatenated in order."""
    return "".join(
        n.content for n in template_tree.children if isinstance(n, t.LeafNode)
    )
