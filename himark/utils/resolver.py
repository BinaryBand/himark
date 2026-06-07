"""SymbolResolver Protocol and central registry for {{ :emoji: }} / {{ $latex$ }} nodes.

To add a new symbol type:
  1. Implement a class with `node_type`, `metadata_key`, and `resolve(content) -> str`.
  2. Call `register(instance)` — the engine will pick it up automatically.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SymbolResolver(Protocol):
    node_type: str  # matches HMKNode.type, e.g. "emoji", "latex"
    metadata_key: str  # key in node.metadata holding the resolver input

    def resolve(self, content: str) -> str:
        """Resolve *content* to Unicode, or return a fallback string."""
        ...


RESOLVERS: dict[str, SymbolResolver] = {}


def register(resolver: SymbolResolver) -> None:
    """Register *resolver* under its declared node_type."""
    RESOLVERS[resolver.node_type] = resolver
