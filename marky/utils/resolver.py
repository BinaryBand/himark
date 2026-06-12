"""Central registry for the symbol-rendering hooks (`{{:emoji:}}`, `{{$latex$}}`).

A resolver is just a function `str -> str`: it receives the inner content of a
symbol node and returns its rendered form (or a fallback string when it cannot
resolve). Register one under the template node-type it serves.

To add a new symbol type:
  1. Write a `resolve(content: str) -> str` function.
  2. Call `register("<node_type>", resolve)` — the renderer picks it up by name.
"""

from __future__ import annotations

from collections.abc import Callable

Resolver = Callable[[str], str]

RESOLVERS: dict[str, Resolver] = {}


def register(node_type: str, resolver: Resolver) -> None:
    """Register *resolver* under the template *node_type* it renders."""
    RESOLVERS[node_type] = resolver
