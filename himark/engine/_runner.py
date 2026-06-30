"""Subprocess runner — delegates run_pipeline to an external engine process.

The external engine is selected by the HMK_ENGINE env var: "rust" (default),
"java", or "python".

Protocol (stdin → stdout, newline-delimited JSON):
  in:  {"pipeline": [[[step], ...], ...], "target": "..."}
  out: {"result": "..."} | {"error": "..."}

Each step is serialised with its own to_json() method; Program adds a
"kind": "program" discriminator, Template uses its existing to_json() shape
plus "kind": "template".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from himark.models.compiled import Step, Template

_SANDBOX = Path(__file__).parents[2] / "sandbox"

_JAVA_BUILD_DIR = _SANDBOX / "build" / "java"
_GO_BUILD_DIR = _SANDBOX / "build" / "go"


def _go_command() -> list[str]:
    binary = _GO_BUILD_DIR / "himark-engine"
    if binary.exists():
        return [str(binary)]
    return ["go", "run", str(_SANDBOX / "engine.go")]


def _java_command() -> list[str]:
    if (_JAVA_BUILD_DIR / "engine.class").exists():
        return ["java", "-cp", str(_JAVA_BUILD_DIR), "engine"]
    return ["java", str(_SANDBOX / "engine.java")]


def _engine_command() -> list[str]:
    name = os.environ.get("HMK_ENGINE", "rust")
    if name == "rust":
        return [str(_SANDBOX / "rust" / "target" / "release" / "himark-engine")]
    if name == "java":
        return _java_command()
    if name == "python":
        return [sys.executable, str(_SANDBOX / "engine.py")]
    if name == "go":
        return _go_command()
    raise RuntimeError(
        f"Unknown HMK_ENGINE {name!r}; expected rust, java, python, or go"
    )


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
        _engine_command(),
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
