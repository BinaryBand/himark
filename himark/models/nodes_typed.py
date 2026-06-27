from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

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
# Structural nodes (phase2/raw)
# -----------------------------


# `weakref_slot` lets the engine's `Runtime` hold this node as a weak cache key:
# the lowered-program cache lives off the AST now (see himark/engine/runtime.py),
# so a node is purely data — no engine state rides on it.
@dataclass(slots=True, weakref_slot=True)
class RootNode:
    type: Literal["root"] = "root"
    children: list[Node] = field(default_factory=list)
    # Set by the pipeline compiler on a statement's first step when the statement
    # uses the `<=` fixed-point arrow: the runner re-splices it until the document
    # settles. A plain `=>` statement leaves it False. Excluded from equality (it
    # is a runner directive, not part of the matched shape).
    fixed_point: bool = field(default=False, compare=False)


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


@dataclass(slots=True, kw_only=True)
class ValueRangeNode:
    """A value range over `alpha` (a band `{alpha::lower..upper}`). A `None`
    endpoint is open: no `lower` means a floor of zero (width 1); no `upper` means
    unbounded. The written forms `{A::..τ}`, `{A::τ..}`, and `{A::τ..τ}` are just
    which endpoints are given; a single value `{A:τ}` is `lower == upper`."""

    alpha: SemanticNode
    type: Literal["value_range"] = "value_range"
    lower: str | None = None
    upper: str | None = None
    # A reference endpoint (`{@d::0..$0}`) resolves to a captured value at match
    # time; when set, the matching `lower`/`upper` string is None (dynamic).
    lower_ref: "SemanticNode | None" = None
    upper_ref: "SemanticNode | None" = None
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


@dataclass(slots=True, kw_only=True)
class AnchorNode:
    """A zero-width anchor: `@<`/`@>` match a **line** start/end; `@<<`/`@>>` the
    whole **document** start/end. Matches a position without consuming or
    capturing."""

    at: Literal[
        "line_start",
        "line_end",
        "doc_start",
        "doc_end",
    ]
    type: Literal["anchor"] = "anchor"


@dataclass(slots=True, kw_only=True)
class HeterogeneousNode:
    """A nested universe `{{U}}` whose inner is a **lazy** alphabet (a range/value,
    not an enumerable member list) — one opaque position that repeats
    **heterogeneously**: a fresh match of `inner` per rep (`{{a..z}}[2]` is any two
    letters — `ab`, `zq`, …), unlike a bare `{U}[n]` which repeats the same matched
    string. The position, and its opacity, come from the **nesting**; a nesting with
    an enumerable inner (`{{a,A}}`) folds to a `GroupClassNode` instead. Both are one
    position built by `{{…}}`, differing only in whether the faces are listed or lazy."""

    inner: SemanticNode
    type: Literal["heterogeneous"] = "heterogeneous"


@dataclass(slots=True)
class GroupClassNode:
    """The single congruence primitive: an ordered list of congruence groups,
    each a set of interchangeable spellings of one position.

    The **outer** list is positions (distinguishable points); the **inner** list is
    the congruent faces at one position. A face count > 1 comes **only from nesting**
    — never from a bare `,`. A bare comma-list `{a,A}` is two primitives an operator
    picks between, so it is two singleton groups (`[[a], [A]]`, the same as `{a..b}`);
    nesting `{{a,A}}` folds them into one position with two faces (`[[a, A]]`), so
    `[2]` frees the faces (`aa`/`aA`/`Aa`/`AA`). An ordered alphabet of folded
    positions `{{a,A},{b,B},…}` is many two-face groups (`[[a,A],[b,B],…]`). This is
    `~` in the `(Σ, ≤, ~)` model; `..` builds `≤` (ordered ranges) instead."""

    type: Literal["group_class"] = "group_class"
    groups: list[list[str]] = field(default_factory=list)


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
    | ValueRangeNode
    | UnionNode
    | ComplementNode
    | HeterogeneousNode
    | AnchorNode
    | GroupClassNode
    | SequenceNode
    | BackRefNode
    | CountRefNode
    | StageRefNode
)

Node: TypeAlias = RootNode | LeafNode | BraceGroupNode | SemanticNode
