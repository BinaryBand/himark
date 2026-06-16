from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

# -----------------------------
# Shared value objects
# -----------------------------


@dataclass(slots=True)
class CountRange:
    min: int
    max: int | None


@dataclass(slots=True)
class CountRefSpec:
    """A count-position reference `[#i]`: repeat exactly as many times as capture
    group `i` did. The bound is unknown until match time, when it resolves to
    group `i`'s repetition count."""

    group: int


CountSpec: TypeAlias = CountRange | CountRefSpec


# -----------------------------
# Structural nodes (phase2/raw)
# -----------------------------


@dataclass(slots=True)
class RootNode:
    type: Literal["root"] = "root"
    children: list[Node] = field(default_factory=list)


@dataclass(slots=True)
class LeafNode:
    type: Literal["leaf"] = "leaf"
    content: str = ""


@dataclass(slots=True)
class BraceGroupNode:
    type: Literal["brace_group"] = "brace_group"
    content: str = ""
    semantic: SemanticNode | None = None
    count: CountSpec | None = None
    count_src: str | None = None


# -----------------------------
# Semantic nodes (phase3)
# -----------------------------


@dataclass(slots=True)
class LiteralNode:
    type: Literal["literal"] = "literal"
    content: str = ""


@dataclass(slots=True)
class CharRangeNode:
    type: Literal["char_range"] = "char_range"
    start: str = ""
    end: str = ""
    exclusions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StringRangeNode:
    type: Literal["string_range"] = "string_range"
    start: str = ""
    end: str = ""


@dataclass(slots=True, kw_only=True)
class ValueRangeNode:
    """A value range over `alpha`. A `None` endpoint is open: no `lower` means a
    floor of zero (width 1); no `upper` means unbounded. The three written forms
    α..τ, τ..α, and τ..α..τ are just which endpoints are given."""

    alpha: SemanticNode
    type: Literal["value_range"] = "value_range"
    lower: str | None = None
    upper: str | None = None
    exclusions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UnionNode:
    type: Literal["union"] = "union"
    options: list[SemanticNode] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)


@dataclass(slots=True, kw_only=True)
class ComplementNode:
    inner: SemanticNode
    type: Literal["complement"] = "complement"


@dataclass(slots=True)
class GroupClassNode:
    """The single congruence primitive: an ordered list of congruence groups,
    each a set of interchangeable spellings of one position.

    A bare comma-list `{a,A}` is one group (`[[a, A]]`) — its members are
    interchangeable, so `[2]` folds case (`aa`, `aA`, `Aa`, `AA`). An ordered
    alphabet of classes `{{a,A},{b,B},…}` is many groups (`[[a,A],[b,B],…]`),
    built by a union of single-group classes. This is `~` in the `(Σ, ≤, ~)`
    model; `..` builds `≤` (ordered ranges) instead."""

    type: Literal["group_class"] = "group_class"
    groups: list[list[str]] = field(default_factory=list)


@dataclass(slots=True, kw_only=True)
class PaddedNode:
    """Width-constrained value match: {N:expr}, {N..M:expr}, or {:expr}.

    max_width None means "up to the width of the inner range's maximum value"
    (the {:expr} form); the engine derives it at match time."""

    inner: SemanticNode
    type: Literal["padded"] = "padded"
    min_width: int = 1
    max_width: int | None = None


@dataclass(slots=True)
class SequenceNode:
    """A grouping brace: a `{...}` whose interior is a concatenation of constructs
    (`{of{black}{quartz}}`) rather than one alphabet expression. It is a single
    capture group whose nested brace children become its sub-captures.
    `children` are the resolved phase-3 nodes of the interior."""

    type: Literal["sequence"] = "sequence"
    children: list[Node] = field(default_factory=list)


@dataclass(slots=True)
class BackRefNode:
    """A self-reference `{$i}`: matches the literal text that capture group `i`
    captured earlier in the same match. Groups are numbered in document order,
    the first `{...}` being group 0. Unlike a `LiteralNode`, the text to match
    is not known at compile time — it is read from the running capture list, so
    the engine lowers this to a dedicated element, not a `Matcher`."""

    type: Literal["back_ref"] = "back_ref"
    group: int = 0


@dataclass(slots=True)
class CountRefNode:
    """A count-reference `{#i}`: matches the decimal *repetition count* of
    capture group `i` (`{…}[2..9]` then `{ repeated {#0} times}`). Like a
    back-reference, the value is read from the running capture list at match
    time — here it is `len(reps)` rendered in base 10."""

    type: Literal["count_ref"] = "count_ref"
    group: int = 0


@dataclass(slots=True)
class StageRefNode:
    """A cross-stage reference `{N$M}`: matches the literal text of pipeline
    stage `N`'s capture `M`. The capture part is a dotted path (`{N$M.K}`) into
    sub-captures, like the moustache `i$j.k`; an empty path (`{N$}`) is the
    stage's whole match. The referent is read from the pipeline stages threaded
    into the matcher, so — like a back-reference — it lowers to a dedicated
    element, not a `Matcher`."""

    type: Literal["stage_ref"] = "stage_ref"
    stage: int = 0
    path: tuple[int, ...] = ()


SemanticNode: TypeAlias = (
    LiteralNode
    | CharRangeNode
    | StringRangeNode
    | ValueRangeNode
    | UnionNode
    | ComplementNode
    | GroupClassNode
    | PaddedNode
    | SequenceNode
    | BackRefNode
    | CountRefNode
    | StageRefNode
)

Node: TypeAlias = RootNode | LeafNode | BraceGroupNode | SemanticNode

SemanticClasses = (
    LiteralNode,
    CharRangeNode,
    StringRangeNode,
    ValueRangeNode,
    UnionNode,
    ComplementNode,
    GroupClassNode,
    PaddedNode,
    SequenceNode,
    BackRefNode,
    CountRefNode,
    StageRefNode,
)
