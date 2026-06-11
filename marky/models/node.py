from __future__ import annotations

from typing import Literal, TypeAlias, TypedDict, TypeGuard

CapturePath: TypeAlias = list[int]


class CountRangeMetadata(TypedDict):
    min: int
    max: int | None


class CountRefMetadata(TypedDict):
    count_ref: int


CountSpec: TypeAlias = CountRangeMetadata | CountRefMetadata


class ExclusionsMetadata(TypedDict, total=False):
    exclusions: list[str]


class CountCarrierMetadata(TypedDict, total=False):
    count_src: str
    count: CountSpec


class SeparatorMetadata(CountCarrierMetadata, total=False):
    sep_value: str
    sep_class: "HMKNode"


class CharRangeMetadata(ExclusionsMetadata):
    start: str
    end: str


class NamedAlphaMetadata(ExclusionsMetadata):
    name: str


class StringRangeMetadata(TypedDict):
    start: str
    end: str


class FullAlphaMetadata(ExclusionsMetadata, total=False):
    pass


class UpperBoundMetadata(ExclusionsMetadata, total=False):
    alpha: "HMKNode"
    upper: str


class LowerBoundMetadata(ExclusionsMetadata, total=False):
    lower: str
    alpha: "HMKNode"


class BoundedRangeMetadata(ExclusionsMetadata, total=False):
    lower: str
    alpha: "HMKNode"
    upper: str


class ZipRangeMetadata(TypedDict):
    left: "HMKNode"
    right: "HMKNode"


class TokenSetMetadata(ExclusionsMetadata):
    tokens: list[str]


class GroupClassMetadata(ExclusionsMetadata):
    groups: list[list[str]]


class PaddedMetadata(TypedDict, total=False):
    width: int | None


class GroupRefMetadata(TypedDict):
    index: CapturePath


class SpanRefMetadata(TypedDict):
    start: CapturePath
    end: CapturePath


class CountTemplateRefMetadata(TypedDict):
    group: int


class EmojiMetadata(TypedDict):
    code: str


class LatexMetadata(TypedDict):
    expr: str


NodeType: TypeAlias = Literal[
    "root",
    "leaf",
    "double_braces",
    "brace_group",
    "separator",
    "literal",
    "char_range",
    "named_alpha",
    "string_range",
    "full_alpha",
    "upper_bound",
    "lower_bound",
    "bounded_range",
    "zip_range",
    "union",
    "complement",
    "token_set",
    "group_class",
    "padded",
    "full_match",
    "group_ref",
    "span_ref",
    "count_ref",
    "emoji",
    "latex",
]

NodeMetadataSchema: TypeAlias = (
    dict[str, object]
    | CountCarrierMetadata
    | SeparatorMetadata
    | CharRangeMetadata
    | NamedAlphaMetadata
    | StringRangeMetadata
    | FullAlphaMetadata
    | UpperBoundMetadata
    | LowerBoundMetadata
    | BoundedRangeMetadata
    | ZipRangeMetadata
    | TokenSetMetadata
    | GroupClassMetadata
    | PaddedMetadata
    | GroupRefMetadata
    | SpanRefMetadata
    | CountTemplateRefMetadata
    | EmojiMetadata
    | LatexMetadata
)

NodeMetadata: TypeAlias = dict[str, object]


class HMKNode:
    type: NodeType
    content: str
    children: list[HMKNode]
    metadata: NodeMetadata

    def __init__(
        self,
        node_type: NodeType,
        content: str,
        children: list[HMKNode] | None = None,
        metadata: NodeMetadata | None = None,
    ):
        self.type = node_type
        self.content = content
        self.children = children or []
        self.metadata = metadata or {}

    def __repr__(self):
        if self.children:
            children_str = ", ".join(repr(c) for c in self.children)
            return f"HMK({self.type!r}, {self.content!r}, [{children_str}])"
        if self.metadata:
            return f"HMK({self.type!r}, {self.content!r}, meta={self.metadata})"
        return f"HMK({self.type!r}, {self.content!r})"


class CharRangeNode(HMKNode):
    type: Literal["char_range"]
    metadata: CharRangeMetadata


class NamedAlphaNode(HMKNode):
    type: Literal["named_alpha"]
    metadata: NamedAlphaMetadata


class StringRangeNode(HMKNode):
    type: Literal["string_range"]
    metadata: StringRangeMetadata


class UpperBoundNode(HMKNode):
    type: Literal["upper_bound"]
    metadata: UpperBoundMetadata


class LowerBoundNode(HMKNode):
    type: Literal["lower_bound"]
    metadata: LowerBoundMetadata


class BoundedRangeNode(HMKNode):
    type: Literal["bounded_range"]
    metadata: BoundedRangeMetadata


class ZipRangeNode(HMKNode):
    type: Literal["zip_range"]
    metadata: ZipRangeMetadata


class TokenSetNode(HMKNode):
    type: Literal["token_set"]
    metadata: TokenSetMetadata


class GroupClassNode(HMKNode):
    type: Literal["group_class"]
    metadata: GroupClassMetadata


class GroupRefNode(HMKNode):
    type: Literal["group_ref"]
    metadata: GroupRefMetadata


class SpanRefNode(HMKNode):
    type: Literal["span_ref"]
    metadata: SpanRefMetadata


class CountRefNode(HMKNode):
    type: Literal["count_ref"]
    metadata: CountTemplateRefMetadata


class EmojiNode(HMKNode):
    type: Literal["emoji"]
    metadata: EmojiMetadata


class LatexNode(HMKNode):
    type: Literal["latex"]
    metadata: LatexMetadata


def is_char_range_node(node: HMKNode) -> TypeGuard[CharRangeNode]:
    return node.type == "char_range"


def is_named_alpha_node(node: HMKNode) -> TypeGuard[NamedAlphaNode]:
    return node.type == "named_alpha"


def is_string_range_node(node: HMKNode) -> TypeGuard[StringRangeNode]:
    return node.type == "string_range"


def is_upper_bound_node(node: HMKNode) -> TypeGuard[UpperBoundNode]:
    return node.type == "upper_bound"


def is_lower_bound_node(node: HMKNode) -> TypeGuard[LowerBoundNode]:
    return node.type == "lower_bound"


def is_bounded_range_node(node: HMKNode) -> TypeGuard[BoundedRangeNode]:
    return node.type == "bounded_range"


def is_zip_range_node(node: HMKNode) -> TypeGuard[ZipRangeNode]:
    return node.type == "zip_range"


def is_token_set_node(node: HMKNode) -> TypeGuard[TokenSetNode]:
    return node.type == "token_set"


def is_group_class_node(node: HMKNode) -> TypeGuard[GroupClassNode]:
    return node.type == "group_class"


def is_group_ref_node(node: HMKNode) -> TypeGuard[GroupRefNode]:
    return node.type == "group_ref"


def is_span_ref_node(node: HMKNode) -> TypeGuard[SpanRefNode]:
    return node.type == "span_ref"


def is_count_ref_node(node: HMKNode) -> TypeGuard[CountRefNode]:
    return node.type == "count_ref"


def is_emoji_node(node: HMKNode) -> TypeGuard[EmojiNode]:
    return node.type == "emoji"


def is_latex_node(node: HMKNode) -> TypeGuard[LatexNode]:
    return node.type == "latex"


def print_tree(node: HMKNode, indent: int = 0) -> None:
    prefix = "  " * indent
    t = node.type
    m = node.metadata

    if t == "leaf":
        print(f"{prefix}LEAF: {node.content!r}")
    elif t == "root":
        print(f"{prefix}root")
        for child in node.children:
            print_tree(child, indent + 1)
    elif t == "brace_group":
        count = m.get("count")
        count_str = f"[{count}]" if count else ""
        print(f"{prefix}brace_group{count_str}: {node.content!r}")
        for child in node.children:
            print_tree(child, indent + 1)
    elif t == "separator":
        count = m.get("count")
        count_str = f"[{count}]" if count else ""
        print(f"{prefix}separator{count_str}: {node.content!r}")
    elif t == "literal":
        print(f"{prefix}literal: {node.content!r}")
    elif is_char_range_node(node):
        print(
            f"{prefix}char_range: {node.metadata['start']!r}..{node.metadata['end']!r}"
        )
    elif is_named_alpha_node(node):
        print(f"{prefix}named_alpha: {node.metadata['name']}")
    elif t == "full_alpha":
        print(f"{prefix}full_alpha")
        for child in node.children:
            print_tree(child, indent + 1)
    elif is_string_range_node(node):
        print(
            f"{prefix}string_range: {node.metadata['start']!r}..{node.metadata['end']!r}"
        )
    elif is_upper_bound_node(node):
        print(f"{prefix}upper_bound: ..{node.metadata['upper']!r}")
        print_tree(node.metadata["alpha"], indent + 1)
    elif is_lower_bound_node(node):
        print(f"{prefix}lower_bound: {node.metadata['lower']!r}..")
        print_tree(node.metadata["alpha"], indent + 1)
    elif is_bounded_range_node(node):
        print(
            f"{prefix}bounded_range: {node.metadata['lower']!r}..{node.metadata['upper']!r}"
        )
        print_tree(node.metadata["alpha"], indent + 1)
    elif is_zip_range_node(node):
        print(f"{prefix}zip_range")
        print_tree(node.metadata["left"], indent + 1)
        print_tree(node.metadata["right"], indent + 1)
    elif t == "union":
        excl = m.get("exclusions", [])
        print(f"{prefix}union (exclusions: {excl})")
        for child in node.children:
            print_tree(child, indent + 1)
    elif t == "complement":
        print(f"{prefix}complement")
        for child in node.children:
            print_tree(child, indent + 1)
    elif is_token_set_node(node):
        print(f"{prefix}token_set: {node.metadata['tokens']}")
    elif is_group_class_node(node):
        print(f"{prefix}group_class: {node.metadata['groups']}")
    elif t == "padded":
        width = m.get("width")
        print(f"{prefix}padded: width={width}")
        for child in node.children:
            print_tree(child, indent + 1)
    elif t == "full_match":
        print(f"{prefix}full_match")
    elif is_group_ref_node(node):
        idx = ".".join(str(i) for i in node.metadata["index"])
        print(f"{prefix}group_ref: {idx}")
    elif is_span_ref_node(node):
        start = ".".join(str(i) for i in node.metadata["start"])
        end = ".".join(str(i) for i in node.metadata["end"])
        print(f"{prefix}span_ref: {start}..{end}")
    elif is_count_ref_node(node):
        print(f"{prefix}count_ref: #{node.metadata['group']}")
    elif is_emoji_node(node):
        print(f"{prefix}emoji: :{node.metadata['code']}:")
    elif is_latex_node(node):
        print(f"{prefix}latex: {node.metadata['expr']!r}")
    else:
        print(f"{prefix}{t}: {node.content!r}")
        for child in node.children:
            print_tree(child, indent + 1)
