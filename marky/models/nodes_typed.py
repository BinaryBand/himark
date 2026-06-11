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
    content: str = ""
    children: list[Node] = field(default_factory=list)


@dataclass(slots=True)
class LeafNode:
    type: Literal["leaf"] = "leaf"
    content: str = ""


@dataclass(slots=True)
class DoubleBracesNode:
    type: Literal["double_braces"] = "double_braces"
    content: str = ""


@dataclass(slots=True)
class BraceGroupNode:
    type: Literal["brace_group"] = "brace_group"
    content: str = ""
    semantic: SemanticNode | None = None
    count: CountSpec | None = None
    count_src: str | None = None


@dataclass(slots=True)
class SeparatorNode:
    type: Literal["separator"] = "separator"
    content: str = ""
    count: CountSpec | None = None
    count_src: str | None = None
    sep_value: str | None = None
    sep_class: SemanticNode | None = None


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
class UpperBoundNode:
    alpha: SemanticNode
    type: Literal["upper_bound"] = "upper_bound"
    upper: str = ""
    exclusions: list[str] = field(default_factory=list)


@dataclass(slots=True, kw_only=True)
class LowerBoundNode:
    alpha: SemanticNode
    type: Literal["lower_bound"] = "lower_bound"
    lower: str = ""
    exclusions: list[str] = field(default_factory=list)


@dataclass(slots=True, kw_only=True)
class BoundedRangeNode:
    alpha: SemanticNode
    type: Literal["bounded_range"] = "bounded_range"
    lower: str = ""
    upper: str = ""
    exclusions: list[str] = field(default_factory=list)


@dataclass(slots=True, kw_only=True)
class ZipRangeNode:
    left: SemanticNode
    right: SemanticNode
    type: Literal["zip_range"] = "zip_range"


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
    exclusions: list[str] = field(default_factory=list)


@dataclass(slots=True, kw_only=True)
class PaddedNode:
    inner: SemanticNode
    type: Literal["padded"] = "padded"
    width: int | None = None


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


@dataclass(slots=True)
class EmojiNode:
    type: Literal["emoji"] = "emoji"
    code: str = ""


@dataclass(slots=True)
class LatexNode:
    type: Literal["latex"] = "latex"
    expr: str = ""


SemanticNode: TypeAlias = (
    LiteralNode
    | CharRangeNode
    | StringRangeNode
    | FullAlphaNode
    | UpperBoundNode
    | LowerBoundNode
    | BoundedRangeNode
    | ZipRangeNode
    | UnionNode
    | ComplementNode
    | TokenSetNode
    | GroupClassNode
    | PaddedNode
)

TemplateNode: TypeAlias = (
    FullMatchNode | GroupRefNode | SpanRefNode | CountRefNode | EmojiNode | LatexNode
)

Node: TypeAlias = (
    RootNode
    | LeafNode
    | DoubleBracesNode
    | BraceGroupNode
    | SeparatorNode
    | SemanticNode
    | TemplateNode
)

SemanticClasses = (
    LiteralNode,
    CharRangeNode,
    StringRangeNode,
    FullAlphaNode,
    UpperBoundNode,
    LowerBoundNode,
    BoundedRangeNode,
    ZipRangeNode,
    UnionNode,
    ComplementNode,
    TokenSetNode,
    GroupClassNode,
    PaddedNode,
)


def is_semantic(node: Node) -> TypeGuard[SemanticNode]:
    """Runtime check + narrowing for the semantic-node union."""
    return isinstance(node, SemanticClasses)
