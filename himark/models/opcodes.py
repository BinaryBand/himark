"""Flat opcode IR — the portable instruction set for Himark compiled patterns.

Each instruction is ``(opcode: int, *operands)``.  The VM dispatches on the
integer opcode; operands are plain Python values (strings, ints, lists, tuples)
that serialise to JSON / MessagePack / CBOR without custom types.

Adding a construct:
  1. Add an opcode constant here.
  2. Teach the compiler visitor (``himark/parser/_compiler.py``) to emit it.
  3. Teach the VM (``himark/engine/backend/_vm.py``) to execute it.
"""

from __future__ import annotations

from typing import Any, TypeAlias

# ── Opcode constants ───────────────────────────────────────────────────────────

# Literal text that must appear verbatim.
LIT = 0

# Zero-width anchor: line_start(0), line_end(1), doc_start(2), doc_end(3).
ANCHOR = 1

# A code-point range with exclusions — the compiled form of `{a..z}`, `{\d}`,
# and value-range bands over ``@uni`` with single-char endpoints.
# Operands: (lo: int, hi: int, excl: list[str], reps: Reps)
CHAR = 2

# A group alphabet — one position from an explicit symbol set, repeated.
# Operands: (groups: list[list[str]], het: bool, reps: Reps)
GROUP = 3

# Match the literal text captured by group ``group``, repeated.
# Operands: (group: int, reps: Reps)
BACK_REF = 4

# Match the decimal representation of group ``group``'s repetition count.
# Operands: (group: int, reps: Reps)
COUNT_REF = 5

# Match text of pipeline stage ``stage``'s capture at ``path``.
# Operands: (stage: int, path: tuple[int, ...], reps: Reps)
STAGE_REF = 6

# A static value-range band ``{@d::0..99}`` — width-window positional-value
# match over an explicit alphabet with pre-computed bounds.
# Operands: (alphabet_desc, lo_val: int|None, hi_val: int|None,
#             wmin: int, wmax: int|None, excl: list[str], reps: Reps)
# alphabet_desc is ("range", lo, hi) for code-point alphabets, or
# ("groups", [[str]]) for materialized alphabets.
VALUE_RANGE = 7

# A value range with a dynamic (reference) endpoint that resolves at match time.
# Operands: (alphabet_desc, lo_static, hi_static, lo_ref, hi_ref, excl, reps)
# lo_ref/hi_ref are None for static, or ("back"|"count"|"stage", ...) descriptors.
DYN_RANGE = 8

# A complement ``{^abc}`` — match one position whose value is NOT in the inner
# alphabet.  Operands: (inner_groups: list[list[str]], reps: Reps)
COMPLEMENT = 10

# A grouping brace ``{of{black}{quartz}}`` — a sub-program that is one capture
# group whose inner elements become sub-captures.
# Operands: (children: list[Instruction], reps: Reps)
SEQ_GROUP = 11

# ── Repetition spec ────────────────────────────────────────────────────────────

# In the serialised form a reps value is one of:
#   [min, max]          — count range; max is int, or -1 for unbounded
#   ["#", group]        — count reference [#i]; resolves at match time
#   ["=", [v1, v2, …]]  — count set [a,b,c]; one of these exact values

# A ``Reps`` tiny struct the VM uses internally (resolved from the tuple form).
from dataclasses import dataclass


@dataclass(slots=True)
class Reps:
    min: int = 1
    max: int | None = 1
    allowed: frozenset[int] | None = None
    count_ref: int | None = None

    def accepts(self, k: int) -> bool:
        if self.allowed is not None:
            return k in self.allowed
        return k >= self.min and (self.max is None or k <= self.max)


def reps_from_tuple(r: Any) -> Reps:
    """Parse a serialised reps tuple into a ``Reps``."""
    if r is None:
        return Reps(1, 1)
    # Tagged form: ("#", group) for count-reference, ("=", [values]) for count set
    if isinstance(r, (list, tuple)) and r and r[0] == "#":
        return Reps(count_ref=r[1])
    if isinstance(r, (list, tuple)) and r and r[0] == "=":
        vals = frozenset(r[1])
        return Reps(min=min(vals), max=max(vals), allowed=vals)
    lo, hi = r
    return Reps(min=lo, max=None if hi == -1 else hi)


# ── Instruction type (for typing convenience) ──────────────────────────────────

# An instruction is ``(int, *operands)`` where operands are primitives.
Instruction: TypeAlias = tuple


# ── Compiled program ───────────────────────────────────────────────────────────


# `weakref_slot` lets the engine's `Runtime` cache the per-backend handle off the
# Program (keyed by identity, evicted when the Program dies). It is not frozen
# because the pipeline runner sets `fixed_point` on a statement's first step after
# the parser has compiled it (the `<=>` flag is a runner directive, not shape).
@dataclass(slots=True, weakref_slot=True)
class Program:
    """The lowered, executable form of a pattern — a flat list of opcode
    tuples.  This is the single named boundary between compilation and
    execution; it is trivially serialisable to JSON."""

    elements: tuple[Instruction, ...]
    groups: int = 0  # total capture group count (for allocation)
    fixed_point: bool = False  # <=> arrow
