#!/usr/bin/env python3
"""Engine bridge for the Himark Tester GUI.

The Vite dev server pipes a JSON request to this script's stdin and forwards the
JSON we write to stdout. Because the GUI now lives *inside* the himark repo, we
import the engine directly instead of shelling out to the CLI per expression — a
request is one in-process pipeline run, not a fan-out of subprocesses. The native
backend is selected when it is built (else the default Python one).

Request (stdin):

    {
      "mode": "find" | "execute",
      "expressions": ["<hmk stmt>", ...],   # the project's enabled expressions
      "target": "<document text>"
    }

Response (stdout):

    # find    — every enabled expression's matches, for source highlighting
    {"matches": [{"start", "end"}, ...], "count": N}

    # execute — the expressions run as a pipeline (each spliced over the whole
    #           document in order, exactly as a .hmk script runs)
    {"output": "<transformed text>", "count": N}

    # either, on a parse/compile error
    {"error": "<message>"}

`count` is the OUTPUT badge: matches found (find) or splices applied (execute).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# gui/ sits next to the himark package; put the repo root on the path so the
# engine imports resolve whichever interpreter the dev server launched us with.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from himark import parser  # noqa: E402
from himark.engine import (  # noqa: E402
    RUST_AVAILABLE,
    RustEngine,
    deltas,
    find,
    set_backend,
    splice,
    splice_to_fixed_point,
)
from himark.models.exceptions import CompileError  # noqa: E402
from himark.tools import precompiled  # noqa: E402

# Prefer the native matcher when it is built, so the GUI inherits the same
# speedups the test suite gets from forcing RustEngine. Absent the extension,
# RUST_AVAILABLE is False and the default PythonEngine stays.
if RUST_AVAILABLE:
    set_backend(RustEngine())


def _find(expressions: list[str], target: str) -> dict:
    """Union of every expression's first-step matches in `target` — the spans the
    GUI paints over the test string."""
    spans: list[dict] = []
    for expr in expressions:
        steps = parser.parse(expr)
        if steps:
            spans.extend({"start": s, "end": e} for s, e in find(steps, target))
    spans.sort(key=lambda s: (s["start"], s["end"]))
    return {"matches": spans, "count": len(spans)}


def _highlight(patterns: list[str], targets: list[str]) -> dict:
    """Tokenize each target by running the syntax-highlight `patterns` (from
    `gui/highlight.hmk`) over it. Each pattern's index is its *class*; the GUI
    maps that to a colour. Returns one span list per target — `{start, end, cls}`
    — so the sidebar can paint a colour backdrop behind every expression.

    A pattern that fails to parse is skipped, not fatal: the highlighter must
    never break the editor (and an empty/whitespace target just yields no spans).
    """
    compiled: list[tuple[int, list]] = []
    for cls, pat in enumerate(patterns):
        try:
            steps = parser.parse(pat)
        except CompileError:
            continue
        if steps:
            compiled.append((cls, steps))
    highlights: list[list[dict]] = []
    for tgt in targets:
        spans: list[dict] = []
        for cls, steps in compiled:
            spans.extend(
                {"start": s, "end": e, "cls": cls} for s, e in find(steps, tgt) if e > s
            )
        highlights.append(spans)
    return {"highlights": highlights}


def _execute(expressions: list[str], target: str) -> dict:
    """Run the expressions as a pipeline over `target` — the same path a `.hmk`
    script takes (`compile_pipeline` parses them and flags each `<=>` stage as a
    fixed point) — counting the splices each stage applies (the badge total)."""
    text = target
    count = 0
    for steps in precompiled.compile_pipeline(expressions):
        if not steps:
            continue
        if steps[0].fixed_point:
            before, text = text, splice_to_fixed_point(steps, text)
            count += 1 if text != before else 0
        else:
            count += len(deltas(steps, text))
            text = splice(steps, text)
    return {"output": text, "count": count}


def _handle_request() -> None:
    """Read one JSON request from stdin and write the JSON response to stdout —
    the path the Vite middleware drives, one process per request."""
    raw = sys.stdin.read().lstrip("﻿").strip()
    req = json.loads(raw or "{}")
    mode = req.get("mode", "find")
    target = req.get("target", "")
    expressions = [e for e in req.get("expressions", []) if e and e.strip()]
    try:
        if mode == "highlight":
            # The highlight patterns are a fixed script, not the user's enabled
            # expressions, so they are passed unfiltered; `targets` are the texts
            # to tokenize (every sidebar expression).
            payload = _highlight(req.get("expressions", []), req.get("targets", []))
        elif mode == "execute":
            payload = _execute(expressions, target)
        else:
            payload = _find(expressions, target)
    except (CompileError, ValueError, IndexError) as exc:
        payload = {"error": str(exc) or exc.__class__.__name__}
    sys.stdout.write(json.dumps(payload))


def _serve() -> int:
    """Start the GUI dev server (`npm run dev`), installing deps on first run.

    This is what you get by running the script straight from a terminal — Vite
    then handles the page and pipes each `/api/run` back to this same script (via
    `_handle_request`), so one command brings the whole tester up."""
    import shutil
    import subprocess

    gui = Path(__file__).resolve().parent
    npm = shutil.which("npm")
    if npm is None:
        sys.stderr.write("npm not found on PATH — install Node.js to run the GUI.\n")
        return 1
    if not (gui / "node_modules").exists():
        sys.stderr.write("Installing GUI dependencies (npm install)…\n")
        if subprocess.run([npm, "install"], cwd=gui).returncode != 0:
            return 1
    return subprocess.run([npm, "run", "dev"], cwd=gui).returncode


def main() -> None:
    # A piped stdin (the Vite middleware) means "handle this request"; a terminal
    # means "bring the server up".
    if sys.stdin.isatty():
        raise SystemExit(_serve())
    _handle_request()


if __name__ == "__main__":
    main()
