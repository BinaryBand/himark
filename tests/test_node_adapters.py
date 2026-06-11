from marky.models import nodes_typed as t
from marky.models.node import HMKNode
from marky.models.nodes_adapter import from_legacy, to_legacy


def test_roundtrip_structural_nodes():
    typed = t.RootNode(
        content="root",
        children=[
            t.LeafNode(content="x"),
            t.DoubleBracesNode(content="0"),
            t.BraceGroupNode(
                content="a",
                semantic=t.LiteralNode(content="a"),
                count=t.CountRange(min=1, max=2),
                count_src="1..2",
            ),
            t.SeparatorNode(
                content=",",
                count=t.CountRef(index=0),
                count_src="{{#0}}",
                sep_value=",",
                sep_class=t.CharRangeNode(start="a", end="z"),
            ),
        ],
    )

    legacy = to_legacy(typed)
    back = from_legacy(legacy)

    assert isinstance(legacy, HMKNode)
    assert back == typed


def test_roundtrip_semantic_nodes():
    samples: list[t.Node] = [
        t.LiteralNode(content="abc"),
        t.CharRangeNode(start="a", end="z", exclusions=["d..f"]),
        t.NamedAlphaNode(name="hex", exclusions=["a..c"]),
        t.StringRangeNode(start="aa", end="zz"),
        t.FullAlphaNode(inner=t.CharRangeNode(start="a", end="f"), exclusions=["d"]),
        t.UpperBoundNode(alpha=t.CharRangeNode(start="0", end="9"), upper="255"),
        t.LowerBoundNode(lower="10", alpha=t.CharRangeNode(start="0", end="9")),
        t.BoundedRangeNode(
            lower="10", alpha=t.CharRangeNode(start="0", end="9"), upper="99"
        ),
        t.ZipRangeNode(
            left=t.CharRangeNode(start="a", end="z"),
            right=t.CharRangeNode(start="A", end="Z"),
        ),
        t.UnionNode(
            options=[t.LiteralNode(content="cat"), t.LiteralNode(content="dog")],
            exclusions=["dog"],
        ),
        t.ComplementNode(inner=t.CharRangeNode(start="a", end="z")),
        t.TokenSetNode(tokens=["cat", "dog"], exclusions=["dog"]),
        t.GroupClassNode(groups=[["a", "A"], ["b", "B"]], exclusions=["A"]),
        t.PaddedNode(inner=t.CharRangeNode(start="0", end="9"), width=3),
        t.FullMatchNode(),
        t.GroupRefNode(index=[0, 1]),
        t.SpanRefNode(start=[0], end=[1]),
        t.CountRefNode(group=2),
        t.EmojiNode(code="rocket"),
        t.LatexNode(expr="x^2"),
    ]

    for sample in samples:
        back = from_legacy(to_legacy(sample))
        assert back == sample


def test_from_legacy_manual_hmknode_tree():
    legacy = HMKNode(
        "brace_group",
        "a..z",
        [HMKNode("char_range", "a..z", metadata={"start": "a", "end": "z"})],
        metadata={"count": {"min": 1, "max": 3}},
    )

    typed = from_legacy(legacy)

    assert isinstance(typed, t.BraceGroupNode)
    assert isinstance(typed.semantic, t.CharRangeNode)
    assert typed.semantic.start == "a"
    assert isinstance(typed.count, t.CountRange)
    assert typed.count.max == 3
