"""Render a template step (the right-hand side of `=>`) against a match.

The only reference is `{{.}}`, the full matched text. `full_match_override`
carries the deferred `{{.}}` value when rendering mid-chain.
"""

from marky.engine._types import Match
from marky.models import nodes_typed as t


def is_template(tree: t.RootNode) -> bool:
    """True if `tree` is a template step (renders output) rather than a matcher.

    A step is a template when it contains a `{{.}}` node — or nothing but
    literal leaves, which makes it a constant template (`{\\<} =>+ &lt;`).
    Pattern steps are marked by their matchable brace groups.
    """
    return any(t.is_template(n) for n in tree.children) or all(
        isinstance(n, t.LeafNode) for n in tree.children
    )


def render(
    template_tree: t.RootNode,
    match: Match,
    full_match_override: str | None = None,
) -> str:
    """Render a template against a match.

    `full_match_override` supplies the deferred value for `{{.}}` in a chained
    template — the result of applying the remaining chain to the current match.
    When None, `{{.}}` resolves to the raw matched text.
    """
    parts: list[str] = []
    for node in template_tree.children:
        if isinstance(node, t.LeafNode):
            parts.append(node.content)
        elif isinstance(node, t.FullMatchNode):
            parts.append(full_match_override if full_match_override is not None else match.text)
    return "".join(parts)
