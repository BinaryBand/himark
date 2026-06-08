"""Varied-repetition support: variable extraction, domain merging, binding enumeration.

A pattern like [a](n)[b](n) contains the variable `n` whose value must be the
same for both brackets.  This module handles everything *outside* the actual
character matching:

  1. collect_var_specs(tree)  — walk a parsed tree, find every variable
     letter used in count positions, and merge their literal bounds into a
     compact VarSpec per variable.

  2. iter_bindings(specs, max_count) — enumerate every valid {var: int}
     assignment in *greedy-first* order (largest values tried first so the
     engine's first successful binding is the greediest match).

The engine is responsible for substituting bindings into _parse_repetition
and for propagating them through the matching stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product as _product
from typing import Iterator

from himark.models.exceptions import CompileError
from himark.models.node import HMKNode

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class VarSpec:
    name: str
    lo: int = 1  # inclusive lower bound on the variable's value
    hi: int | None = None  # inclusive upper bound (None = capped by text length)

    def domain(self, max_count: int) -> range:
        """Integer values this variable may take, given a text-length cap."""
        hi = self.hi if self.hi is not None else max_count
        return range(self.lo, hi + 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_var_specs(tree: HMKNode) -> dict[str, VarSpec]:
    """Walk *tree* and return a merged VarSpec for every variable letter found."""
    specs: dict[str, VarSpec] = {}
    _walk(tree, specs)
    return specs


def iter_bindings(
    specs: dict[str, VarSpec], max_count: int
) -> Iterator[dict[str, int]]:
    """Yield every valid {var: value} dict, largest values first (greedy).

    Variables are enumerated in sorted name order so the iteration order is
    deterministic.  For patterns with no variables an empty dict is yielded
    once so callers can always iterate without special-casing.
    """
    if not specs:
        yield {}
        return

    names = sorted(specs)
    # Build domains largest-first so that product() tries the greediest
    # combination first.
    domains = [list(reversed(specs[n].domain(max_count))) for n in names]
    for combo in _product(*domains):
        yield dict(zip(names, combo))


def has_variables(tree: HMKNode) -> bool:
    """Return True if *tree* contains any variable-count bracket."""
    specs: dict[str, VarSpec] = {}
    _walk(tree, specs)
    return bool(specs)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _walk(node: HMKNode, specs: dict[str, VarSpec]) -> None:
    if node.type == "single_brackets":
        options = _flatten(node.metadata.get("options", []))
        for opt in options:
            if opt.type == "option" and _is_var(opt.content):
                # bare (n): exactly n; variable is unconstrained from this site
                _merge(specs, opt.content, lo=1, hi=None)
            elif opt.type == "repetition_range":
                mn, mx = opt.metadata["min"], opt.metadata["max"]
                if _is_var(mn):
                    # (n..k): var is the lower bound; literal k caps it from above
                    hi = int(mx) if mx and mx.isdigit() else None
                    _merge(specs, mn, lo=1, hi=hi)
                if _is_var(mx):
                    # (k..n): var is the upper bound; literal k floors it from below
                    lo = int(mn) if mn and mn.isdigit() else 1
                    _merge(specs, mx, lo=lo, hi=None)

    for child in node.children:
        _walk(child, specs)
    for opt in node.metadata.get("options", []):
        _walk(opt, specs)


def _is_var(s: str) -> bool:
    return len(s) == 1 and s.isalpha()


def _merge(specs: dict[str, VarSpec], name: str, lo: int, hi: int | None) -> None:
    """Tighten the domain for *name* with a new lo/hi constraint."""
    if name not in specs:
        specs[name] = VarSpec(name, lo, hi)
    else:
        existing = specs[name]
        existing.lo = max(existing.lo, lo)
        if hi is not None:
            existing.hi = min(existing.hi, hi) if existing.hi is not None else hi
    spec = specs[name]
    if spec.hi is not None and spec.lo > spec.hi:
        raise CompileError(
            f"Conflicting bounds for variable '{name}': {spec.lo}..{spec.hi}"
        )


def _flatten(opts: list[HMKNode]) -> list[HMKNode]:
    result: list[HMKNode] = []
    for o in opts:
        if o.type == "option_list":
            result.extend(_flatten(o.children))
        else:
            result.append(o)
    return result
