from himark.models.nodes_typed import (
    CharRangeNode,
    CountRange,
    GroupClassNode,
    LiteralNode,
    SeqItem,
    SequenceNode,
    UnionNode,
    ValueRangeNode,
)


def test_typed_nodes_smoke():
    lit = LiteralNode(content="abc")
    rng = CharRangeNode(start="a", end="z", exclusions=["d..f"])
    union = UnionNode(options=[lit, rng], exclusions=["x"])

    assert lit.type == "literal"
    assert rng.type == "char_range"
    assert union.type == "union"


def test_typed_count_and_group_class():
    count = CountRange(min=1, max=3)
    gc = GroupClassNode(groups=[["a", "A"]])

    assert count.min == 1
    assert count.max == 3
    assert gc.type == "group_class"
    assert gc.groups == [["a", "A"]]


def test_sequence_node():
    seq = SequenceNode(
        items=[
            SeqItem(node=LiteralNode(content="a"), literal=True),
            SeqItem(node=LiteralNode(content="b"), literal=True),
        ]
    )
    assert len(seq.items) == 2
    assert seq.items[0].node.content == "a"


def test_semantic_payload_fields():
    bounded = ValueRangeNode(
        lower="10", alpha=CharRangeNode(start="0", end="9"), upper="20"
    )
    klass = GroupClassNode(groups=[["cat", "dog"]])

    assert bounded.type == "value_range"
    assert klass.groups == [["cat", "dog"]]
