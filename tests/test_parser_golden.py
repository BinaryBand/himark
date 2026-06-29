"""Compiled-output golden harness for the parser front-end.

Pins the *compiled* output (`Program` / `Template`) over the pattern corpus
and shipped `.hmk` scripts, so a parser change is a diff against this golden.

The parser has a single compile path: ANTLR CST → SemanticNode → opcodes.
These golden files pin that output directly.

Regenerate the pins after an *intended* parser change:
`HIMARK_UPDATE_GOLDEN=1 pytest tests/test_parser_golden.py` — then eyeball the diff.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from himark import parser
from himark.models.exceptions import CompileError
from himark import engine

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "himark" / "scripts"
GOLDEN = Path(__file__).resolve().parent / "golden" / "parser_ast"

_UPDATE = bool(os.environ.get("HIMARK_UPDATE_GOLDEN"))


# ── Compiled-output canonicalisation ─────────────────────────────────────────────────

def _step_to_json(step) -> dict:
    """Canonicalise a compiled `Program` or `Template` step to a JSON dict.
    A `Program` is represented as its opcode elements (tuples converted to lists
    for JSON); a `Template` as its literal + moustache parts."""
    from himark.models.compiled import Template
    from himark.models.opcodes import Program

    if isinstance(step, Program):
        return {
            "_t": "Program",
            "elements": _tuples_to_lists(list(step.elements)),
            "fixed_point": step.fixed_point,
        }
    if isinstance(step, Template):
        return step.to_json()
    raise TypeError(f"unexpected step type: {type(step)}")


def _tuples_to_lists(obj):
    """Recursively convert tuples to lists for JSON serialization."""
    if isinstance(obj, tuple):
        return [_tuples_to_lists(x) for x in obj]
    if isinstance(obj, list):
        return [_tuples_to_lists(x) for x in obj]
    return obj


def _canon_steps(steps: list) -> list[dict]:
    return [_step_to_json(s) for s in steps]


def _canon_pipeline(pipeline: list[list]) -> list[list[dict]]:
    return [_canon_steps(stmt) for stmt in pipeline]


def diff(a: Any, b: Any, path: str = "") -> str | None:
    """The dotted path to the first inequality, or None."""
    if a == b:
        return None
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return f"{path}: keys differ: {sorted(a)} vs {sorted(b)}"
        for k in a:
            if (d := diff(a[k], b[k], f"{path}.{k}")) is not None:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: lengths {len(a)} vs {len(b)}"
        for i in range(len(a)):
            if (d := diff(a[i], b[i], f"{path}[{i}]")) is not None:
                return d
        return None
    return f"{path}: {a!r} vs {b!r}"


# ── Corpus ────────────────────────────────────────────────────────────────────

PATTERNS = [
    ("literal", r"{abc}"),
    ("char_range", r"{a..z}"),
    ("char_range_multi", r"{az..zz}"),
    ("value_range_upper", r"{@d::..255}"),
    ("value_range_lower", r"{@d::0..}"),
    ("value_range_both", r"{@d::0..255}"),
    ("value_range_single", r"{@d::128}"),
    ("value_range_dyn_ref", r"{@d::0..$0}"),
    ("union_strings", r"{a,b,c}"),
    ("group_class_one", r"{{a,A}}"),
    ("complement", r"!{xyz}"),
    ("complement_multichar", r"!{abc,def,ghi}"),
    ("heterogeneous", r"{{a,A},{b,B}}"),
    ("anchor_line_start", r"{@<}"),
    ("anchor_line_end", r"{@>}"),
    ("anchor_doc_start", r"{@<<}"),
    ("anchor_doc_end", r"{@>>}"),
    ("sequence", r"{of{black}{quartz}}"),
    ("back_ref", r"{abc}{$0}[0..]"),
    ("count_ref_node", r"{abc}[2..9]{#0}"),
    ("stage_ref_whole", r"{abc} => {$0}"),
    ("band_ambient", r"{@d::0..255}"),
    ("count_exact", r"{a}[3]"),
    ("count_range", r"{a}[1..6]"),
    ("count_open_upper", r"{a}[2..]"),
    ("count_open_lower", r"{a}[..5]"),
    ("count_set", r"{a}[1,3,5]"),
    ("count_ref_spec", r"{a}[2..]{b}[#0]"),
    ("multi_step_template", r'{#}[1..] => "<h1>{{.}}</h1>"'),
    ("chained_steps", r"{a..z} => {A..Z} => upper"),
    ("var_digit", r"{@d}"),
    ("var_lower", r"{@l}"),
    ("var_upper", r"{@u}"),
    ("var_word", r"{@w}"),
    ("var_complement_ws", r"!{@s}"),
]

SCRIPT_FILES = sorted(p.name for p in SCRIPTS.glob("*.hmk"))


# ── Corpus builders ──────────────────────────────────────────────────────────

def _build_pattern_compiled() -> dict[str, Any]:
    return {pid: _canon_steps(parser.parse(src)) for pid, src in PATTERNS}


def _build_script_compiled() -> dict[str, Any]:
    return {
        name: _canon_pipeline(
            engine.compile_script((SCRIPTS / name).read_text("utf-8"))
        )
        for name in SCRIPT_FILES
    }


def _check_golden(built: dict[str, Any], golden_path: Path, label: str) -> None:
    """Compare a built corpus dict to its golden file, per-id, or update it."""
    if _UPDATE:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(
            json.dumps(built, indent=2, ensure_ascii=False) + "\n", "utf-8"
        )
        return
    assert golden_path.exists(), (
        f"missing golden {golden_path} — run HIMARK_UPDATE_GOLDEN=1 pytest"
    )
    expected = json.loads(golden_path.read_text("utf-8"))
    assert set(built) == set(expected), (
        f"{label} corpus ids changed; if intended, regenerate with "
        f"HIMARK_UPDATE_GOLDEN=1"
    )
    for key in built:
        if (d := diff(expected[key], built[key], key)) is not None:
            pytest.fail(
                f"{label} compiled output for {key!r} drifted from golden at {d}; "
                f"if intended, regenerate with HIMARK_UPDATE_GOLDEN=1"
            )


# ── Tests ────────────────────────────────────────────────────────────────────

def test_pattern_compiled_golden():
    """The parser's compiled output over the pattern corpus matches its pin."""
    _check_golden(
        _build_pattern_compiled(), GOLDEN / "patterns.json", "pattern"
    )


def test_script_compiled_golden():
    """The parser's compiled output over every shipped `.hmk` matches its pin."""
    _check_golden(
        _build_script_compiled(), GOLDEN / "scripts.json", "script"
    )
