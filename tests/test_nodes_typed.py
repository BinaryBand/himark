from marky.models.nodes_typed import (
    BraceGroupNode,
    CharRangeNode,
    CountRange,
    GroupClassNode,
    LiteralNode,
    RootNode,
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


def test_typed_count_and_group_class():
    group = BraceGroupNode(content="a", semantic=LiteralNode(content="a"))
    group.count = CountRange(min=1, max=3)

    gc = GroupClassNode(groups=[["a", "A"]])

    assert group.count is not None
    assert gc.type == "group_class"
    assert gc.groups == [["a", "A"]]


def test_semantic_payload_fields():
    bounded = ValueRangeNode(
        lower="10", alpha=CharRangeNode(start="0", end="9"), upper="20"
    )
    klass = GroupClassNode(groups=[["cat", "dog"]])

    assert bounded.type == "value_range"
    assert klass.groups == [["cat", "dog"]]
