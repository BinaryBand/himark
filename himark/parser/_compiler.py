"""AST → opcode compiler.

Converts ``RootNode`` ASTs (produced by ``_builder.py``) into flat opcode
``Program``\s consumable by ``himark.engine.backend._vm``.

This replaces the lowering half of ``himark.engine.backend._compile``
(``_compile_elements`` + all ``Element`` types + ``Matcher`` protocol) with
a single pass that emits ``(opcode, *operands)`` tuples.
"""

from __future__ import annotations

from himark.models.opcodes import (
    ANCHOR,
    BACK_REF,
    CHAR,
    COUNT_REF,
    DYN_RANGE,
    GROUP,
    LIT,
    SEQ_GROUP,
    STAGE_REF,
    VALUE_RANGE,
    Instruction,
    Program,
)
from himark.models.alphabet import MAX_SYMBOLS, Alphabet, RangeAlphabet
from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError


# ── Reps serialisation ────────────────────────────────────────────────────────


def _reps_tuple(count: t.CountSpec | None) -> tuple:
    """Convert a parsed ``CountSpec`` to the serialised reps tuple."""
    if count is None:
        return (1, 1)
    if isinstance(count, t.CountRefSpec):
        return ("#", count.group)
    if isinstance(count, t.CountSet):
        return ("=", list(count.values))
    return (count.min, -1 if count.max is None else count.max)


# ── Alphabet descriptor ───────────────────────────────────────────────────────


def _alphabet_desc(node: t.SemanticNode) -> tuple:
    """Build an alphabet descriptor ``("range", lo, hi)`` or ``("groups", [[str]])``."""
    if isinstance(node, t.CharRangeNode):
        return ("range", ord(node.start), ord(node.end))
    # ValueRangeNode over @uni with single-char endpoints
    if (
        isinstance(node, t.ValueRangeNode)
        and isinstance(node.alpha, t.CharRangeNode)
    ):
        lo = _static_str(node.lower)
        hi = _static_str(node.upper)
        if lo is not None and len(lo) == 1 and hi is not None and len(hi) == 1:
            return ("range", ord(lo), ord(hi))
    # Materialized alphabet
    groups = _groups(node)
    return ("groups", groups)


def _static_str(end: "str | t.SemanticNode") -> str | None:
    """A band endpoint's concrete value string, or None for Floor/Inf/ref."""
    return end if isinstance(end, str) else None


def _drop_excluded(
    groups: list[list[str]], exclusions: list[str]
) -> list[list[str]]:
    """Remove excluded symbols from groups."""
    if not exclusions:
        return groups
    kept = [[m for m in grp if m not in exclusions] for grp in groups]
    return [grp for grp in kept if grp]


def _codepoint_span(node: t.SemanticNode) -> tuple[int, int] | None:
    """The ``(lo, hi)`` code-point span, or None."""
    if isinstance(node, t.CharRangeNode):
        return ord(node.start), ord(node.end)
    if (
        isinstance(node, t.ValueRangeNode)
        and isinstance(node.alpha, t.CharRangeNode)
        and not node.exclusions
    ):
        low, high = _static_str(node.lower), _static_str(node.upper)
        if (low is None or len(low) == 1) and (high is None or len(high) == 1):
            lo = ord(low) if low is not None else ord(node.alpha.start)
            hi = ord(high) if high is not None else ord(node.alpha.end)
            return lo, hi
    return None


def _value_alphabet(node: t.SemanticNode) -> Alphabet | RangeAlphabet:
    """The alphabet a bound's values are read in."""
    cp = _codepoint_span(node)
    if cp is not None:
        lo, hi = cp
        if hi - lo + 1 > MAX_SYMBOLS:
            return RangeAlphabet(lo, hi)
    return Alphabet(_groups(node), distinct=True)


def _groups(node: t.SemanticNode) -> list[list[str]]:
    """The ordered symbol groups for a value alphabet."""
    if isinstance(node, t.CharRangeNode):
        lo, hi = ord(node.start), ord(node.end)
        if hi - lo + 1 > 0x10000:
            raise CompileError(
                f"Range {node.start!r}..{node.end!r} is too large "
                f"to use as a value bound"
            )
        return _drop_excluded(
            [[chr(c)] for c in range(lo, hi + 1)], node.exclusions
        )
    if isinstance(node, t.UnionNode):
        groups = [g for o in node.options for g in _groups(o)]
        return _drop_excluded(groups, node.exclusions)
    if isinstance(node, t.LiteralNode):
        return [[node.content]]
    if isinstance(node, t.SequenceNode):
        if len(node.children) != 1:
            raise CompileError(
                "A grouping brace with multiple children cannot be used as a value alphabet"
            )
        return _groups(node.children[0])
    if isinstance(node, t.GroupClassNode):
        return [list(grp) for grp in node.groups]
    if isinstance(node, t.ValueRangeNode):
        return _sliced_groups(node)
    raise CompileError(f"Cannot use {type(node).__name__} as a value alphabet")


def _sliced_groups(node: t.ValueRangeNode) -> list[list[str]]:
    """The sub-alphabet between endpoint positions."""
    if node.exclusions:
        raise CompileError("A range with exclusions cannot be a sub-alphabet")
    low, high = _static_str(node.lower), _static_str(node.upper)
    for end in (low, high):
        if end is not None and len(end) != 1:
            raise CompileError(
                f"Sub-alphabet endpoint must be a single symbol, got {end!r}"
            )
    if isinstance(node.alpha, t.CharRangeNode):
        lo = ord(low) if low is not None else ord(node.alpha.start)
        hi = ord(high) if high is not None else ord(node.alpha.end)
        if hi - lo + 1 > 0x10000:
            raise CompileError(
                f"Range {chr(lo)!r}..{chr(hi)!r} is too large to use as a value bound"
            )
        return [[chr(c)] for c in range(lo, hi + 1)]
    groups = _groups(node.alpha)
    alph = Alphabet(groups)
    lo = alph.value(low) if low is not None else 0
    hi = alph.value(high) if high is not None else len(groups) - 1
    return groups[lo : hi + 1]


# ── Value-view computation ────────────────────────────────────────────────────


def _endpoint_value(
    alph: Alphabet | RangeAlphabet, s: str, which: str
) -> int:
    """The positional value of bound endpoint ``s``."""
    bad = next((c for c in s if c not in alph), None)
    if bad is not None:
        raise CompileError(
            f"Bound {which} {s!r} has a symbol not in its alphabet: {bad!r}"
        )
    return alph.value(s)


def _value_view(node: t.ValueRangeNode) -> tuple:
    """Compute ``(alphabet_desc, lo_val, hi_val, wmin, wmax, exclusions)`` for
    a static value-range band.  Returns the operands for a ``VALUE_RANGE`` opcode."""
    alph = _value_alphabet(node.alpha)
    lo_static = _static_str(node.lower)
    hi_static = _static_str(node.upper)

    lo = _endpoint_value(alph, lo_static, "floor") if lo_static is not None else None
    hi = _endpoint_value(alph, hi_static, "ceiling") if hi_static is not None else None

    wf = len(lo_static) if lo_static is not None else None
    wc = len(hi_static) if hi_static is not None else None
    if wf is not None and wc is not None:
        wmin, wmax = min(wf, wc), max(wf, wc)
    elif wf is not None:
        wmin, wmax = wf, None
    else:
        wmin, wmax = 1, wc

    alphabet_desc = ("range", alph.lo, alph.hi) if isinstance(alph, RangeAlphabet) else ("groups", alph.groups)
    return alphabet_desc, lo, hi, wmin, wmax, node.exclusions


# ── Dynamic reference endpoint descriptor ─────────────────────────────────────


def _dynamic_ref(end: "str | t.SemanticNode | None") -> t.SemanticNode | None:
    """A band endpoint's *dynamic* reference, or None."""
    if isinstance(end, (t.BackRefNode, t.CountRefNode, t.StageRefNode)):
        return end
    return None


def _ref_descriptor(ref: t.SemanticNode) -> tuple:
    """A loop-resolvable descriptor for a dynamic reference-endpoint node."""
    if isinstance(ref, t.BackRefNode):
        return ("back", ref.group)
    if isinstance(ref, t.CountRefNode):
        return ("count", ref.group)
    if isinstance(ref, t.StageRefNode):
        return ("stage", ref.stage, ref.path)
    raise CompileError(f"Unsupported bound reference: {type(ref).__name__}")


# ── Group lowering (LiteralNode / UnionNode / GroupClassNode → groups) ────────


def _lower_to_groups(node: t.SemanticNode) -> tuple[list[list[str]], bool]:
    """Lower a semantic node to group-list + het flag, or raise if not a group form."""
    if isinstance(node, t.LiteralNode):
        return [[node.content]], False
    if isinstance(node, t.CharRangeNode):
        lo, hi = ord(node.start), ord(node.end)
        excl = _drop_excluded([[chr(c)] for c in range(lo, hi + 1)], node.exclusions)
        return excl, False
    if isinstance(node, t.UnionNode):
        # Try to merge into one class; if not possible, flatten to groups
        try:
            groups = _groups(node)
        except CompileError:
            raise CompileError(f"Cannot lower union node as a group alphabet")
        return groups, False
    if isinstance(node, t.GroupClassNode):
        return [list(g) for g in node.groups], True
    if isinstance(node, t.ComplementNode):
        # Complement: everything BUT inner. We compile it as a virtual group.
        # But the opcode model doesn't have a complement opcode — it uses
        # the GROUP opcode with het=True and a different matcher. For now,
        # we raise — complement needs a special matcher that we'll handle below.
        raise CompileError("Complement not expressible as group list")
    raise CompileError(
        f"Cannot lower {type(node).__name__} as a group alphabet"
    )


# ── Main compilation entry ────────────────────────────────────────────────────


def _is_complement(node: t.SemanticNode) -> bool:
    """Check if this node (possibly wrapped in BraceGroupNode) is a complement."""
    return isinstance(node, t.ComplementNode)


def compile_pattern(root: t.RootNode) -> Program:
    """Compile a resolved pattern tree into an opcode ``Program``."""
    elements: list[Instruction] = []
    for child in root.children:
        if isinstance(child, t.LeafNode):
            if child.content:  # skip empty leaf nodes
                elements.append((LIT, child.content))
        elif isinstance(child, t.BraceGroupNode):
            if child.semantic is None:
                raise CompileError(
                    f"Unresolved brace group: {{{child.content}}}"
                )
            reps = _reps_tuple(child.count)

            sem = child.semantic

            # Anchor
            if isinstance(sem, t.AnchorNode):
                kind_map = {
                    "line_start": 0,
                    "line_end": 1,
                    "doc_start": 2,
                    "doc_end": 3,
                }
                elements.append((ANCHOR, kind_map[sem.at]))
                continue

            # Back-reference
            if isinstance(sem, t.BackRefNode):
                elements.append((BACK_REF, sem.group, reps))
                continue

            # Count-reference
            if isinstance(sem, t.CountRefNode):
                elements.append((COUNT_REF, sem.group, reps))
                continue

            # Stage-reference
            if isinstance(sem, t.StageRefNode):
                elements.append((STAGE_REF, sem.stage, list(sem.path), reps))
                continue

            # Sequence (grouping brace)
            if isinstance(sem, t.SequenceNode):
                sub = compile_pattern(
                    t.RootNode(children=sem.children)
                )
                elements.append((SEQ_GROUP, list(sub.elements), reps))
                continue

            # Value range
            if isinstance(sem, t.ValueRangeNode):
                # Check for dynamic endpoints
                lo_ref = _dynamic_ref(sem.lower)
                hi_ref = _dynamic_ref(sem.upper)
                if lo_ref or hi_ref:
                    alph = _value_alphabet(sem.alpha)
                    alphabet_desc = (
                        ("range", alph.lo, alph.hi)
                        if isinstance(alph, RangeAlphabet)
                        else ("groups", alph.groups)
                    )
                    lo_static = _static_str(sem.lower)
                    hi_static = _static_str(sem.upper)
                    lo_desc = _ref_descriptor(lo_ref) if lo_ref else None
                    hi_desc = _ref_descriptor(hi_ref) if hi_ref else None
                    elements.append(
                        (
                            DYN_RANGE,
                            alphabet_desc,
                            lo_static,
                            hi_static,
                            lo_desc,
                            hi_desc,
                            sem.exclusions,
                            reps,
                        )
                    )
                    continue

                # Fast path: single-code-point @uni band → CHAR
                if (
                    isinstance(sem.alpha, t.CharRangeNode)
                    and (low_s := _static_str(sem.lower)) is not None
                    and len(low_s) == 1
                    and (high_s := _static_str(sem.upper)) is not None
                    and len(high_s) == 1
                ):
                    elements.append(
                        (CHAR, ord(low_s), ord(high_s), sem.exclusions, reps)
                    )
                    continue

                # General static value band → VALUE_RANGE
                alphabet_desc, lo_val, hi_val, wmin, wmax, excl = _value_view(sem)
                elements.append(
                    (VALUE_RANGE, alphabet_desc, lo_val, hi_val, wmin, wmax, excl, reps)
                )
                continue

            # Complement — compile inner as a group with het=True
            # (The complement behavior is handled by the VM's het flag)
            if isinstance(sem, t.ComplementNode):
                # For complement, we compile the inner as a group and mark het=True
                inner_groups, _ = _lower_to_groups(sem.inner)
                # We need a special marker that this is a complement.
                # The VM matches "anything NOT in inner" with het flag.
                # We'll use a negative groups convention: empty groups + het=True
                # means "complement of the inner groups".
                # Actually, let's use the inner groups + a special flag.
                # The simplest approach: use the inner groups and let the VM know
                # this is a complement via a convention. For now, we pass the inner
                # as groups with het=True and also store the complement info.
                # BUT the current GROUP opcode doesn't handle complement.
                # Let me add a COMPLEMENT opcode or extend GROUP...
                # For now, let's raise and handle complement as a special case.
                raise CompileError(
                    "Complement not yet supported in opcode VM — "
                    "needs COMPLEMENT opcode or GROUP extension"
                )

            # Group (LiteralNode, CharRangeNode, UnionNode, GroupClassNode)
            groups, het = _lower_to_groups(sem)
            elements.append((GROUP, groups, het, reps))

        elif isinstance(child, t.SequenceNode):
            # Bare sequence node inside a grouping brace (single-child scope)
            sub = compile_pattern(t.RootNode(children=child.children))
            elements.append((SEQ_GROUP, list(sub.elements), (1, 1)))

        elif isinstance(child, t.BackRefNode):
            elements.append((BACK_REF, child.group, (1, 1)))

        elif isinstance(child, t.CountRefNode):
            elements.append((COUNT_REF, child.group, (1, 1)))

        elif isinstance(child, t.StageRefNode):
            elements.append(
                (STAGE_REF, child.stage, list(child.path), (1, 1))
            )

        else:
            # Remaining bare semantic nodes → GROUP
            groups, het = _lower_to_groups(child)
            elements.append((GROUP, groups, het, (1, 1)))

    return Program(elements=tuple(elements), fixed_point=root.fixed_point)