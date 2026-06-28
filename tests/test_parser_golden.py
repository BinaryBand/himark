"""Differential-parity harness for the parser front-end.

This guards the migration sketched in docs/GRAMMAR.g4: replacing the hand-rolled
`phase2`/`phase3` scanning with an ANTLR-generated lexer+parser plus a tree-walking
visitor, *without changing the typed AST that comes out the other end*. The output
contract is the `nodes_typed` tree from `himark.parser.parse` (and, for whole files,
`precompiled.compile_script`). If two parser implementations produce structurally
equal ASTs over the corpus, they are interchangeable for everything downstream
(engine, renderer, transpiler), because the AST is the only thing those layers see.

It has two jobs, and is useful in both phases of the work:

  1. **Golden pin (always on).** Snapshot the *current* parser's AST over a corpus
     to `golden/parser_ast/{patterns,scripts}.json`. Any refactor of the existing
     parser — including incrementally moving `phase3` logic into an ANTLR visitor —
     is then a byte-for-byte diff against this pin. This catches regressions today,
     before any ANTLR code exists.

  2. **Live differential (on when a candidate is present).** If a second parser is
     importable (the ANTLR-backed one), parse the same corpus with both and assert
     the canonical ASTs are equal, reporting the *path* to the first divergence.

The candidate-parser contract (so the ANTLR side can plug in with zero edits here):
set `HIMARK_ANTLR_PARSER` to a module path (default `himark.parser_antlr`) exposing

    parse(text: str, variables: dict[str, str] | None = None) -> list[RootNode]

and *optionally* `compile_script(source: str) -> list[list[RootNode]]`. When only
`parse` is exposed, the script tier reuses this module's parser-agnostic
`compile_script_with` (the real `precompiled` splitter/variable logic, candidate parser
injected), so a candidate only ever has to implement `parse`.

Regenerate the pins after an *intended* parser change (same switch as test_golden):
`HIMARK_UPDATE_GOLDEN=1 pytest tests/test_parser_parity.py` — then eyeball the diff.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any, Callable

import pytest

from himark import parser
from himark.models.exceptions import CompileError
from himark.prelude import VARIABLES
from himark.tools import precompiled

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "himark" / "scripts"
GOLDEN = Path(__file__).resolve().parent / "golden" / "parser_ast"

_UPDATE = bool(os.environ.get("HIMARK_UPDATE_GOLDEN"))

# A parser is any callable with `parse`'s signature. The reference is the live
# `himark.parser.parse`; a candidate injects its own under the same shape.
ParseFn = Callable[..., list]


# ── Canonical form ────────────────────────────────────────────────────────────
# A `nodes_typed` tree is a graph of slotted dataclasses. `canon` projects it to a
# JSON-stable nested dict/list/scalar so it can be (a) stored as a golden and (b)
# diffed with a readable path. It mirrors dataclass *equality*: fields marked
# `compare=False` (e.g. `RootNode.fixed_point`, a runner directive set after
# parsing) are omitted, so two ASTs are canon-equal exactly when they are `==`.


# `BraceGroupNode.content` is the raw inside-brace *source* echo, not behavior: the
# engine lowers the `semantic` node and only ever reads `content` in an error message
# (himark/engine/backend/_compile.py "Unresolved brace group"). It legitimately
# differs between the text-macro reference (`{@d}` → content `0..9`) and the variable
# candidate (content `@d`), so comparing it would flag a non-divergence. Excluded so
# the harness tests *behavioral* AST equivalence. (`LeafNode`/`LiteralNode.content`
# ARE semantic and stay compared.)
_INCIDENTAL = {("BraceGroupNode", "content")}


def canon(obj: Any) -> Any:
    """Project a node / list / scalar into a JSON-stable comparable structure."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        cls = type(obj).__name__
        out: dict[str, Any] = {"_t": cls}
        for f in dataclasses.fields(obj):
            # `type` is the Literal discriminator — `_t` already carries it.
            if f.compare is False or f.name == "type":
                continue
            if (cls, f.name) in _INCIDENTAL:
                continue
            out[f.name] = canon(getattr(obj, f.name))
        return out
    if isinstance(obj, (list, tuple)):
        return [canon(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    raise TypeError(f"non-canonicalizable value in AST: {obj!r} ({type(obj)})")


def diff(a: Any, b: Any, path: str = "") -> str | None:
    """First structural difference between two canonical trees, or None if equal.

    Returns a human-readable `path: left != right` so a parity failure names the
    exact node and field that diverged, not just "trees differ"."""
    if isinstance(a, dict) and isinstance(b, dict):
        if a.get("_t") != b.get("_t"):
            return f"{path or '<root>'}._t: {a.get('_t')!r} != {b.get('_t')!r}"
        keys = list(dict.fromkeys([*a, *b]))
        for k in keys:
            if k == "_t":
                continue
            if k not in a:
                return f"{path}.{k}: <missing> != {b[k]!r}"
            if k not in b:
                return f"{path}.{k}: {a[k]!r} != <missing>"
            if (d := diff(a[k], b[k], f"{path}.{k}")) is not None:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}[]: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            if (d := diff(x, y, f"{path}[{i}]")) is not None:
                return d
        return None
    if a != b:
        return f"{path or '<root>'}: {a!r} != {b!r}"
    return None


# ── Parser-agnostic whole-file compile ────────────────────────────────────────
# Mirrors `precompiled.compile_script` but with the parser injected, reusing the
# real splitter / definition / fixed-point helpers so the two cannot drift. The
# reference tier calls `precompiled.compile_script` directly (the true code path);
# only a candidate that lacks its own `compile_script` routes through here.


def compile_script_with(source: str, parse_fn: ParseFn) -> list[list]:
    local: dict[str, str] = {}
    pipeline: list[list] = []
    for item in precompiled.split_statements(source):
        if (defn := precompiled._split_definition(item)) is not None:
            name, body = defn
            if name in VARIABLES:
                raise CompileError(f"definition @{name} shadows a prelude variable")
            if name in local:
                raise CompileError(f"@{name} is already defined")
            local[name] = body
            continue
        converted, loop = precompiled._split_fixed_point(item)
        steps = parse_fn(converted, variables=local)
        if loop and steps:
            steps[0].fixed_point = True
        pipeline.append(steps)
    return pipeline


# ── Corpus ────────────────────────────────────────────────────────────────────
# Pattern tier: one row per surface feature, so a divergence names the construct
# that broke. Covers every phase3 node type and every count form. Kept valid (each
# must parse) and macro-using rows (`@d`) exercise prelude expansion inside `parse`.
PATTERNS: list[tuple[str, str]] = [
    ("literal", r"{hello}"),
    ("char_range", r"{a..z}"),
    ("char_range_multi", r"{aa..zz}"),
    ("value_range_upper", r"{@d::..255}"),
    ("value_range_lower", r"{@d::128..}"),
    ("value_range_both", r"{@d::0..255}"),
    ("value_range_single", r"{@d::5}"),
    ("value_range_union", r"{@d::1..5,9..12}"),
    ("value_range_dyn_ref", r"{{@d}}[1..]\,{@d::0..$0}"),
    ("union_strings", r"{cat,dog}"),
    ("group_class_one", r"{a,A}"),
    ("group_class_alphabet", r"{{a,A},{b,B}}"),
    ("complement", r"{!{x,y}}"),
    ("complement_multichar", r"{!{-->}}"),
    ("heterogeneous", r"{{@d}}"),
    ("anchor_line_start", r"{@<}"),
    ("anchor_line_end", r"{@>}"),
    ("anchor_doc_start", r"{@<<}"),
    ("anchor_doc_end", r"{@>>}"),
    ("sequence", r"{of {black} {quartz}}"),
    ("back_ref", r"{abc}{$0}"),
    ("count_ref_node", r"{a}[2..]{ }{#0}"),
    ("stage_ref_whole", r"{1$}"),
    ("stage_ref_indexed", r"{1$0}"),
    ("exclusion_range", r"{a..z,!{m..p}}"),
    ("band_ambient", r"{@d::0..255}"),
    ("count_exact", r"{a}[3]"),
    ("count_range", r"{a}[1..6]"),
    ("count_open_upper", r"{a}[2..]"),
    ("count_open_lower", r"{a}[..5]"),
    ("count_set", r"{a}[1,3,5]"),
    ("count_ref_spec", r"{a}[2..]{b}[#0]"),
    ("multi_step_template", r'{#}[1..] => "<h1>{{.}}</h1>"'),
    ("chained_steps", r"{a..z} => {A..Z} => upper"),
    # Variable references (`@name`): the reference expands them as text macros, the
    # candidate resolves them structurally — both must reach the same semantic node.
    ("var_digit", r"{@d}"),
    ("var_lower", r"{@l}"),
    ("var_upper", r"{@u}"),
    ("var_word", r"{@w}"),
    ("var_complement_ws", r"{!@s}"),
]

# Script tier: every shipped `.hmk` pipeline, parsed end-to-end (macro expansion,
# multi-statement, fixed-point flags). This is the real-world coverage the inline
# rows can't reach.
SCRIPT_FILES = sorted(p.name for p in SCRIPTS.glob("*.hmk"))


# ── Reference corpus builders ─────────────────────────────────────────────────


def _build_pattern_asts(parse_fn: ParseFn) -> dict[str, Any]:
    return {pid: canon(parse_fn(src)) for pid, src in PATTERNS}


def _build_script_asts(compile_fn: Callable[[str], list]) -> dict[str, Any]:
    return {
        name: canon(compile_fn((SCRIPTS / name).read_text("utf-8")))
        for name in SCRIPT_FILES
    }


def _check_golden(built: dict[str, Any], path: Path, label: str) -> None:
    """Compare a built corpus dict to its golden file, per-id, or update it."""
    if _UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(built, indent=2, ensure_ascii=False) + "\n", "utf-8")
        return
    assert path.exists(), f"missing golden {path} — run HIMARK_UPDATE_GOLDEN=1 pytest"
    expected = json.loads(path.read_text("utf-8"))
    assert set(built) == set(expected), (
        f"{label} corpus ids changed; if intended, regenerate with "
        f"HIMARK_UPDATE_GOLDEN=1"
    )
    for key in built:
        if (d := diff(expected[key], built[key], key)) is not None:
            pytest.fail(
                f"{label} AST for {key!r} drifted from golden at {d}; "
                f"if intended, regenerate with HIMARK_UPDATE_GOLDEN=1"
            )


# ── Tests: golden pins (always on) ────────────────────────────────────────────


def test_pattern_ast_golden():
    """The reference parser's AST over the pattern corpus matches its pin."""
    _check_golden(
        _build_pattern_asts(parser.parse), GOLDEN / "patterns.json", "pattern"
    )


def test_script_ast_golden():
    """The reference parser's AST over every shipped `.hmk` matches its pin."""
    _check_golden(
        _build_script_asts(precompiled.compile_script),
        GOLDEN / "scripts.json",
        "script",
    )
