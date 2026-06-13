from marky.models.nodes_typed import (
    BraceGroupNode,
    CharRangeNode,
    CountRange,
    FullMatchNode,
    LiteralNode,
    RootNode,
    TokenSetNode,
    UnionNode,
    ValueRangeNode,
    ZipNode,
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


def test_typed_count_and_template():
    group = BraceGroupNode(content="a", semantic=LiteralNode(content="a"))
    group.count = CountRange(min=1, max=3)

    zip_node = ZipNode(tracks=[LiteralNode(content="a"), LiteralNode(content="A")])

    assert group.count is not None
    assert FullMatchNode().type == "full_match"
    assert zip_node.type == "zip"


def test_semantic_payload_fields():
    bounded = ValueRangeNode(
        lower="10", alpha=CharRangeNode(start="0", end="9"), upper="20"
    )
    tokens = TokenSetNode(tokens=["cat", "dog"], exclusions=["dog"])

    assert bounded.type == "value_range"
    assert tokens.tokens == ["cat", "dog"]
    assert tokens.exclusions == ["dog"]
