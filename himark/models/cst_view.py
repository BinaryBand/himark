"""Parser-agnostic *views* onto a concrete-syntax atom.

The bridge that lets a typed AST node build itself from **any** front-end's parse
tree without `himark/models` depending on a specific parser. A front-end (ANTLR
today) supplies a thin adapter exposing these read-only attributes; the node's
`from_view` classmethod (or a small factory) does the mechanical CST→AST mapping.

This keeps the AST the tech-neutral contract every backend already relies on: the
mapping logic lives on the model, but the model never imports the parser — it only
speaks `…View`. A different front-end (a hand parser, a Lark grammar) implements the
same Protocols and reuses the identical `from_view` code.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AnchorView(Protocol):
    """An anchor atom (`@< @> @<< @>>`): a direction and a scope.

    `is_start` is `<` (a start) vs `>` (an end); `is_document` is the doubled
    bracket (`@<<`/`@>>`, whole-document) vs a single one (a line)."""

    is_start: bool
    is_document: bool


@runtime_checkable
class ReferenceView(Protocol):
    """A reference atom (`$i  #i  N$  N$i  N#  N#i`).

    `is_count` is the `#` sigil (a count-reference) vs `$` (a text/back-reference).
    `stage` is the leading pipeline-stage number `N`, or None for the no-stage forms
    (`$i`/`#i`). `index` is the trailing group number, or None (`{N$}` whole match)."""

    is_count: bool
    stage: int | None
    index: int | None


@runtime_checkable
class RangeView(Protocol):
    """A written `τ..τ` range with two concrete endpoints (`{a..z}`, `{aa..zz}`).

    Both ends are given as literal strings; an open-ended or alphabet endpoint is a
    band (`::`), not this view."""

    lower: str
    upper: str
