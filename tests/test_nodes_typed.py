from marky.models.nodes_typed import (
    BraceGroupNode,
    CharRangeNode,
    CountRange,
    GroupRefNode,
    LiteralNode,
    RootNode,
    SpanRefNode,
    TokenSetNode,
    UnionNode,
    ValueRangeNode,
)


def test_typed_nodes_smoke():
    lit = LiteralNode(content="abc")
    rng = CharRangeNode(start="a", end="z", exclusions=["d..f"])
    union = UnionNode(options=[lit, rng], exclusions=["x"])
    root = RootNode(children=[union])

    assert lit.type == "literal"
    assert rng.type == "char_range"
    assert union.type == "union"
    assert root.children[0].type == "union"


def test_typed_count_and_refs():
    group = BraceGroupNode(content="a", semantic=LiteralNode(content="a"))
    group.count = CountRange(min=1, max=3)

    ref = GroupRefNode(index=[0, 1])
    span = SpanRefNode(start=[0], end=[1])

    assert group.count is not None
    assert ref.index == [0, 1]
    assert span.end == [1]


def test_semantic_payload_fields():
    bounded = ValueRangeNode(
        lower="10", alpha=CharRangeNode(start="0", end="9"), upper="20"
    )
    tokens = TokenSetNode(tokens=["cat", "dog"], exclusions=["dog"])

    assert bounded.type == "value_range"
    assert tokens.tokens == ["cat", "dog"]
    assert tokens.exclusions == ["dog"]
