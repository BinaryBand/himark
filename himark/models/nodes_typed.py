from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from himark.models.exceptions import CompileError

# -----------------------------
# Shared value objects
# -----------------------------


@dataclass(slots=True)
class CountRange:
    """A repetition count `[x..y]` (`max` None is open-ended)."""

    min: int
    max: int | None
    group: int | None = None


@dataclass(slots=True)
class CountSet:
    """An explicit union of counts `[a,b,c]` — repeat exactly `a`, `b`, or `c`
    times. `values` is sorted and de-duplicated."""

    values: list[int]
    group: int | None = None


@dataclass(slots=True)
class CountRefSpec:
    """A count-position reference `[#i]`: repeat exactly as many times as capture
    group `i` did. The bound is unknown until match time, when it resolves to
    group `i`'s repetition count."""

    group: int


CountSpec: TypeAlias = CountRange | CountSet | CountRefSpec

# -----------------------------
# Semantic nodes — the live IR produced by the ANTLR visitor and lowered
# directly to opcodes by _emit_semantic.
# -----------------------------


@dataclass(slots=True)
class LiteralNode:
    type: Literal["literal"] = "literal"
    content: str = ""


@dataclass(slots=True)
class CharRangeNode:
    """A contiguous run of code points `start..end` — the **ambient `@uni`
    alphabet primitive**. Since the range merge, a written `{a..z}` is a
    `ValueRangeNode` over this `@uni` primitive (a band whose ordinal is the code
    point), not a `CharRangeNode` directly; this node now appears only as that
    `alpha`. The engine fast-paths a single-code-point `@uni` band back to a direct
    code-point matcher, so `{a..z}` stays a one-char match."""

    type: Literal["char_range"] = "char_range"
    start: str = ""
    end: str = ""
    exclusions: list[str] = field(default_factory=list)

    @classmethod
    def uni(cls) -> CharRangeNode:
        """The ambient `@uni` alphabet primitive — every code point. The default
        alphabet for an unnamed `..` range and an empty-payload band (`{::lo..hi}`)."""
        return cls(start="\x00", end="\U0010ffff")


@dataclass(slots=True, kw_only=True)
class ValueRangeNode:
    """A value range over `alpha` (a band `{alpha::lower..upper}`). Each endpoint is
    **self-describing** — one of: a concrete value string, a `FloorNode` (open floor:
    zero, width 1), an `InfNode` (unbounded ceiling), or a dynamic reference node
    (`{@d::0..$0}`, resolved from captures at match time). There is no positional `None`:
    you read what an endpoint *is* from the node, not from which slot it sits in. The
    forms `{A::..τ}`/`{A::τ..}`/`{A::τ..τ}` are which bounds are written; a single value
    `{A::τ}` is `lower == upper`."""

    alpha: SemanticNode
    lower: "str | SemanticNode"
    upper: "str | SemanticNode"
    type: Literal["value_range"] = "value_range"
    exclusions: list[str] = field(default_factory=list)

    @classmethod
    def band_arm(
        cls,
        alpha: SemanticNode,
        lower: str | None,
        lower_ref: SemanticNode | None,
        upper: str | None,
        upper_ref: SemanticNode | None,
    ) -> ValueRangeNode:
        """Canonicalise one band arm into two self-describing endpoints. Each side is
        the concrete value if written, else its dynamic reference, else the open marker
        (`FloorNode` for an omitted floor, `InfNode` for an omitted ceiling). At least
        one bound is required — both omitted (`{U::..}`) is an error. The single-value
        form `{alpha::t}` arrives as `lower == upper`. Shared by every front-end, so the
        AST is identical no matter which parser built it."""
        if lower is None and lower_ref is None and upper is None and upper_ref is None:
            raise CompileError("A band needs a floor or a ceiling: got '{U:..}'")
        lo: str | SemanticNode = (
            lower
            if lower is not None
            else lower_ref
            if lower_ref is not None
            else FloorNode()
        )
        hi: str | SemanticNode = (
            upper
            if upper is not None
            else upper_ref
            if upper_ref is not None
            else InfNode()
        )
        return cls(alpha=alpha, lower=lo, upper=hi)


@dataclass(slots=True)
class UnionNode:
    type: Literal["union"] = "union"
    options: list[SemanticNode] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)


@dataclass(slots=True, kw_only=True)
class ComplementNode:
    inner: SemanticNode
    type: Literal["complement"] = "complement"


@dataclass(slots=True, kw_only=True)
class LookaroundNode:
    """A zero-width **negative lookaround** (grammar `lookaround`): `!<{X}` asserts the
    char *behind* the cursor is not in `inner`; `!>{X}` the char *ahead*. Matches a
    position without consuming or capturing. This is the sole boundary primitive --
    the four line/doc anchors are declared in `himark/std.hmk` as lookarounds over it
    (`@doc_start = !<{@uni}`, `@line_start = !<!{\\n}`, ...), and `@<`/`@>`/`@<<`/`@>>`
    are glyph sugar resolving to those names. Lowers to the `LOOKAROUND` opcode."""

    direction: Literal["behind", "ahead"]
    inner: "SemanticNode"
    negate: bool = True
    type: Literal["lookaround"] = "lookaround"


@dataclass(slots=True, kw_only=True)
class NamedAnchorNode:
    """A zero-width **out-of-band named anchor** match: `{@name}` asserts a `name`
    mark sits at the current position; `!{@name}` asserts it does not (`negate`). The
    marks are carried beside the text in an `AnchorMap` (never a byte in it), emitted
    by a `{{@name}}` template directive. Declared via `@name = anchor`. Lowers to the
    `NAMED_ANCHOR` opcode; see docs/HMK.md."""

    name: str
    negate: bool = False
    type: Literal["named_anchor"] = "named_anchor"


@dataclass(slots=True)
class GroupClassNode:
    """A congruence alphabet: an ordered list of congruence groups,
    each a set of interchangeable spellings of one position.

    The **outer** list is positions (distinguishable points); the **inner** list is
    the congruent faces at one position. A face count > 1 comes **only from nesting**
    — never from a bare `,`. A bare comma-list `{a,A}` is two primitives an operator
    picks between, so it is two singleton groups (`[[a], [A]]`, the same as `{a..b}`);
    nesting `{{a,A}}` folds them into one position with two faces (`[[a, A]]`), so
    `[2]` frees the faces (`aa`/`aA`/`Aa`/`AA`). An ordered alphabet of folded
    positions `{{a,A},{b,B},…}` is many two-face groups (`[[a,A],[b,B],…]`). This is
    `~` in the `(Σ, ≤, ~)` model; `..` builds `≤` (ordered ranges) instead.

    The folded form `{{a,A}}` is now stored as a grouping brace
    (``SequenceNode``) wrapping this bare alphabet; congruence at
    value-read time is derived from the grouping's single child,
    not stored on this node."""

    type: Literal["group_class"] = "group_class"
    groups: list[list[str]] = field(default_factory=list)


@dataclass(slots=True)
class SeqItem:
    """One element of a grouping/sequence brace: a resolved child plus its reps.
    `literal` marks a raw text run (emitted as a `LIT`) as opposed to an alphabet or
    nested construct (emitted via `_emit_semantic`). Replaces the parallel
    `_literal_mask`/`_child_counts` arrays the `SequenceNode` used to carry — the
    grammar's `sequence` production now separates text runs from constructs, so each
    item is self-describing."""

    node: SemanticNode
    reps: tuple = (1, 1)
    literal: bool = False


@dataclass(slots=True)
class SequenceNode:
    """A grouping brace: a `{...}` whose interior is a concatenation of constructs
    (`{of{black}{quartz}}`, `{{a,A}}`) rather than one alphabet expression. It is a
    single capture group whose nested brace children become its sub-captures. `items`
    are the resolved interior elements in document order."""

    type: Literal["sequence"] = "sequence"
    items: list[SeqItem] = field(default_factory=list)


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


def reference_from_view(
    is_count: bool,
    stage: int | None,
    index: int | None,
) -> BackRefNode | CountRefNode | StageRefNode:
    """Build the right reference node from a front-end's parsed fields.

    The three reference node types are one structural choice over the fields: a
    no-stage form (`$i`/`#i`) is a back- or count-reference by sigil; a stage form
    (`N$`/`N$i`) is a cross-stage reference. The stage count-ref (`N#`/`N#i`) has no
    node type — it is not a representable reference — so it is rejected here, the one
    place that decision lives."""
    if stage is None:  # `$i` / `#i` — index is the group, sigil picks the kind
        group = index or 0
        return CountRefNode(group=group) if is_count else BackRefNode(group=group)
    if is_count:  # `N#` / `N#i` — no node type for a stage count-ref
        raise CompileError("a stage count-reference like {2#} is not supported")
    path = (index,) if index is not None else ()
    return StageRefNode(stage=stage, path=path)


@dataclass(slots=True)
class FloorNode:
    """The alphabet's **floor** (its ordinal-0 symbol, width 1) as an explicit band
    endpoint — the self-describing form of an omitted lower bound (`{@d::..255}`).
    Sits in a `ValueRangeNode.lower` slot; the engine reads it as a zero floor."""

    type: Literal["floor"] = "floor"


@dataclass(slots=True)
class InfNode:
    """An **unbounded ceiling** as an explicit band endpoint — the self-describing form
    of an omitted upper bound (`{@d::128..}`). Sits in a `ValueRangeNode.upper`
    slot; the engine reads it as no upper limit."""

    type: Literal["inf"] = "inf"


SemanticNode: TypeAlias = (
    LiteralNode
    | CharRangeNode
    | ValueRangeNode
    | UnionNode
    | ComplementNode
    | LookaroundNode
    | NamedAnchorNode
    | GroupClassNode
    | SequenceNode
    | BackRefNode
    | CountRefNode
    | StageRefNode
    | FloorNode
    | InfNode
)

# Node is now just SemanticNode — the structural wrapper layer was removed.
Node: TypeAlias = SemanticNode
