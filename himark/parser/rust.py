"""The native (Rust) parsing backend — a full HMK parser compiled to a
native extension, callable without the Python phase0–3 pipeline.

`RustParser.parse` calls `himark_rs.parse(source)` which runs all four phases
in Rust and returns a JSON string.  `_from_json_roots` deserialises that JSON
back into Python `models.nodes_typed` objects so the rest of the engine sees
exactly the same types it would from `PythonParser`.

`RUST_PARSER_AVAILABLE` is False when the extension has not been built; in that
case constructing `RustParser` raises.  Nothing else in the module is affected.
"""

from __future__ import annotations

import json
from typing import Any

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError

_rs: Any = None
RUST_PARSER_AVAILABLE = False
try:
    import himark_rs as _himark_rs

    _rs = _himark_rs
    RUST_PARSER_AVAILABLE = True
except ImportError:
    pass

__all__ = ["RustParser", "RUST_PARSER_AVAILABLE"]


class RustParser:
    name = "rust"

    def __init__(self) -> None:
        if not RUST_PARSER_AVAILABLE:
            raise RuntimeError(
                "himark_rs is not built; run "
                "`maturin develop --release -m rust/Cargo.toml`"
            )

    def parse(self, source: str) -> list[t.RootNode]:
        try:
            raw = _rs.parse(source)
        except Exception as exc:
            raise CompileError(str(exc)) from exc
        data = json.loads(raw)
        return [_from_json_root(d) for d in data]


# ── JSON → Python AST ─────────────────────────────────────────────────────────


def _from_json_root(d: dict) -> t.RootNode:
    children = [_from_json_child(c) for c in d["children"]]
    return t.RootNode(children=children, fixed_point=d.get("fixed_point", False))


def _from_json_child(d: dict) -> t.Node:
    ty = d["type"]
    if ty == "leaf":
        return t.LeafNode(content=d["content"])
    if ty == "brace_group":
        semantic = _from_json_semantic(d["semantic"])
        count = _from_json_count(d["count"]) if d.get("count") else None
        return t.BraceGroupNode(content=d["content"], semantic=semantic, count=count)
    raise CompileError(f"Unknown child node type from Rust parser: {ty!r}")


def _from_json_semantic(d: dict) -> t.SemanticNode:
    ty = d["type"]
    if ty == "literal":
        return t.LiteralNode(content=d["content"])
    if ty == "char_range":
        return t.CharRangeNode(
            start=d["start"], end=d["end"], exclusions=list(d.get("exclusions", []))
        )
    if ty == "value_range":
        return t.ValueRangeNode(
            alpha=_from_json_semantic(d["alpha"]),
            lower=d.get("lower"),
            upper=d.get("upper"),
            lower_ref=_from_json_semantic(d["lower_ref"]) if d.get("lower_ref") else None,
            upper_ref=_from_json_semantic(d["upper_ref"]) if d.get("upper_ref") else None,
            exclusions=list(d.get("exclusions", [])),
        )
    if ty == "union":
        return t.UnionNode(
            options=[_from_json_semantic(o) for o in d["options"]],
            exclusions=list(d.get("exclusions", [])),
        )
    if ty == "complement":
        return t.ComplementNode(inner=_from_json_semantic(d["inner"]))
    if ty == "heterogeneous":
        return t.HeterogeneousNode(inner=_from_json_semantic(d["inner"]))
    if ty == "group_class":
        return t.GroupClassNode(groups=[list(g) for g in d["groups"]])
    if ty == "sequence":
        return t.SequenceNode(children=[_from_json_child(c) for c in d["children"]])
    if ty == "back_ref":
        return t.BackRefNode(group=d["group"])
    if ty == "count_ref":
        return t.CountRefNode(group=d["group"])
    if ty == "stage_ref":
        return t.StageRefNode(stage=d["stage"], path=tuple(d.get("path", [])))
    if ty == "anchor":
        return t.AnchorNode(at=d["at"])
    raise CompileError(f"Unknown semantic node type from Rust parser: {ty!r}")


def _from_json_count(d: dict) -> t.CountSpec:
    ty = d["type"]
    if ty == "range":
        return t.CountRange(min=d["min"], max=d.get("max"), group=d.get("group"))
    if ty == "set":
        return t.CountSet(values=list(d["values"]), group=d.get("group"))
    if ty == "ref":
        return t.CountRefSpec(group=d["group"])
    raise CompileError(f"Unknown count spec type from Rust parser: {ty!r}")
