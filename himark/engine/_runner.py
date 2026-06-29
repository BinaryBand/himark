"""Subprocess runner — delegates run_pipeline to an external engine process.

The external engine is pointed to by _ENGINE. Right now that is _stub.py (a
seam test that returns the target unchanged). Swap _ENGINE for a compiled
binary path (Rust, Go, …) once the protocol is proven.

Protocol (stdin → stdout, newline-delimited JSON):
  in:  {"pipeline": [[[step], ...], ...], "target": "..."}
  out: {"result": "..."} | {"error": "..."}

Each step is serialised with its own to_json() method; Program adds a
"kind": "program" discriminator, Template uses its existing to_json() shape
plus "kind": "template".
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from himark.models.compiled import Step, Template

_ENGINE: list[str] = [
    str(
        Path(__file__).parents[2]
        / "sandbox"
        / "rust"
        / "target"
        / "release"
        / "himark-engine"
    ),
]


def _step_to_json(step: Step) -> dict:
    if isinstance(step, Template):
        d = step.to_json()
        d["kind"] = "template"
        return d
    d = step.to_json()
    return d


def run_pipeline(pipeline: list[list[Step]], target: str) -> str:
    payload = json.dumps(
        {
            "pipeline": [[_step_to_json(s) for s in stmt] for stmt in pipeline],
            "target": target,
        },
        default=list,  # converts any remaining tuples to JSON arrays
    )
    proc = subprocess.run(
        _ENGINE,
        input=payload,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"engine process failed:\n{proc.stderr}")
    out = json.loads(proc.stdout)
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]
