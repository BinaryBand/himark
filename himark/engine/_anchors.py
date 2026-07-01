"""Out-of-band anchor marks -- the parallel position structure (docs/TODO.md Step 4).

A **named anchor** is a zero-width, non-rendering mark carried *beside* the document
text (never a byte in it, so input cannot spoof it). An ``AnchorMap`` maps a name to
the sorted, unique positions (``0..len``) where that mark sits. The engine threads an
``AnchorMap`` alongside the text through every splice, remapping positions as text is
inserted or removed; a mark strictly inside a replaced span is destroyed. Nothing
here is serialised -- it is pure runtime state (an executor rebuilds it from the
`emit`/`clear` template directives, see docs/PAYLOAD.md).

This module holds only plain position bookkeeping (no engine or parser imports), so
threading it keeps the engine free of any `himark.parser` dependency.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

# name -> the sorted, unique positions (0..len(text)) that mark currently sits at.
AnchorMap = dict[str, tuple[int, ...]]


@dataclass(slots=True)
class Woven:
    """The result of transforming one branch: its ``text``, the marks ``anchors``
    emitted within that text (positions in the text's own ``0..len`` frame), and the
    ``cleared`` names to drop from the enclosing splice's output map."""

    text: str
    anchors: AnchorMap = field(default_factory=dict)
    cleared: frozenset[str] = frozenset()


def _extend(dst: AnchorMap, name: str, more: Iterable[int]) -> None:
    dst[name] = tuple(sorted(set(dst.get(name, ())).union(more)))


def carry(dst: AnchorMap, src: AnchorMap, lo: int, hi: int, shift: int) -> None:
    """Carry ``src`` marks with ``lo <= p < hi`` into ``dst``, shifted by ``shift``.
    Used for the text between matches (a gap): marks there survive, remapped into
    output coordinates. A mark at a match's left edge (``p == start``) falls outside
    the gap and is destroyed with the replaced span; one at the right edge is carried
    by the next gap (whose ``lo`` is that match's ``end``)."""
    for name, positions in src.items():
        kept = [p + shift for p in positions if lo <= p < hi]
        if kept:
            _extend(dst, name, kept)


def place(dst: AnchorMap, src: AnchorMap, base: int) -> None:
    """Add ``src`` marks (in their own ``0..len`` frame) into ``dst`` at output
    offset ``base`` -- a branch's emitted marks landing in the assembled output."""
    for name, positions in src.items():
        if positions:
            _extend(dst, name, [base + p for p in positions])


def slice_local(src: AnchorMap, lo: int, hi: int) -> AnchorMap:
    """The marks with ``lo <= p <= hi``, rebased to a local ``0..(hi - lo)`` frame --
    the interior marks of a matched span handed to its sub-transform so nested
    queries can match them."""
    out: AnchorMap = {}
    for name, positions in src.items():
        kept = tuple(p - lo for p in positions if lo <= p <= hi)
        if kept:
            out[name] = kept
    return out


def drop(dst: AnchorMap, names: Iterable[str]) -> None:
    """Remove named marks from ``dst`` entirely (a `clear` directive's effect)."""
    for name in names:
        dst.pop(name, None)
