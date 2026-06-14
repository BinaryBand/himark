from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias, TypeGuard

# -----------------------------
# Shared value objects
# -----------------------------


@dataclass(slots=True)
class CountRange:
    min: int
    max: int | None


@dataclass(slots=True)
class CountRef:
    index: int


CountSpec: TypeAlias = CountRange | CountRef


# -----------------------------
# Structural nodes (phase2/raw)
# -----------------------------


@dataclass(slots=True)
class RootNode:
    type: Literal["root"] = "root"
    children: list[Node] = field(default_factory=list)
    # Statement-level output mode, set on the first step only: True (`=>+`)
    # splices rendered matches back into the source; False (`=>`) extracts them.
    replace: bool = False
    # Inner-arrow `=>+` (pipe): this template's output is spliced at the
    # preceding pattern's matches and the chain continues on the result.
    piped: bool = False


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
class FullAlphaNode:
    inner: SemanticNode
    type: Literal["full_alpha"] = "full_alpha"
    exclusions: list[str] = field(default_factory=list)


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
class TokenSetNode:
    type: Literal["token_set"] = "token_set"
    tokens: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GroupClassNode:
    type: Literal["group_class"] = "group_class"
    groups: list[list[str]] = field(default_factory=list)


@dataclass(slots=True)
class ZipNode:
    """A congruence (`<->`): an n-ary position-wise zip of its tracks into one
    folded alphabet. Each track is a $\\sigma$; the i-th position accepts the
    i-th spelling of any track. Equal cardinality and distinct spellings are
    checked when the zip is lowered (it needs each track's ordered groups)."""

    type: Literal["zip"] = "zip"
    tracks: list[SemanticNode] = field(default_factory=list)


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
    capture group whose nested brace children become its sub-captures (`{{N.M}}`).
    `children` are the resolved phase-3 nodes of the interior."""

    type: Literal["sequence"] = "sequence"
    children: list[Node] = field(default_factory=list)


# -----------------------------
# Template/reference nodes
# -----------------------------


@dataclass(slots=True)
class FullMatchNode:
    type: Literal["full_match"] = "full_match"


@dataclass(slots=True)
class GroupRefNode:
    type: Literal["group_ref"] = "group_ref"
    index: list[int] = field(default_factory=list)


@dataclass(slots=True)
class SpanRefNode:
    type: Literal["span_ref"] = "span_ref"
    start: list[int] = field(default_factory=list)
    end: list[int] = field(default_factory=list)


@dataclass(slots=True)
class CountRefNode:
    type: Literal["count_ref"] = "count_ref"
    group: int = 0


SemanticNode: TypeAlias = (
    LiteralNode
    | CharRangeNode
    | StringRangeNode
    | FullAlphaNode
    | ValueRangeNode
    | UnionNode
    | ComplementNode
    | TokenSetNode
    | GroupClassNode
    | ZipNode
    | PaddedNode
    | SequenceNode
)

TemplateNode: TypeAlias = FullMatchNode | GroupRefNode | SpanRefNode | CountRefNode

Node: TypeAlias = (
    RootNode | LeafNode | BraceGroupNode | SemanticNode | TemplateNode
)

SemanticClasses = (
    LiteralNode,
    CharRangeNode,
    StringRangeNode,
    FullAlphaNode,
    ValueRangeNode,
    UnionNode,
    ComplementNode,
    TokenSetNode,
    GroupClassNode,
    ZipNode,
    PaddedNode,
    SequenceNode,
)

TemplateClasses = (
    FullMatchNode,
    GroupRefNode,
    SpanRefNode,
    CountRefNode,
)


def is_template(node: Node) -> TypeGuard[TemplateNode]:
    """Runtime check + narrowing for the template-node union."""
    return isinstance(node, TemplateClasses)
