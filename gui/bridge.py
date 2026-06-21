#!/usr/bin/env python3
"""Dev-server bridge from himark-101 to marky's CLI.

The React tester POSTs {mode, pattern, target}; the Vite middleware pipes that
JSON to this script's stdin. We shell out to marky's `find --json` / `execute
--json` commands — marky does all the work in-engine — and forward the result
under the key the client expects:

    {"matches": [{"start", "end"}, ...]}         # find  mode
    {"deltas":  [{"start", "end", "text"}, ...]} # execute mode
    {"error": "<message>"}                       # a parse / compile error

`--json` makes marky emit structured output (a JSON array on stdout, or a JSON
{"error": ...} on stderr with exit 1), so there is no text to parse or align —
the engine produces the exact spans and per-match renderings.

Run with marky's venv python so that `python -m marky` resolves; the Vite
middleware does exactly that. All the glue lives here, on the himark-101 side.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# marky sits next to himark-101 under .../Dev; override with the MARKY_DIR env.
MARKY_DIR = Path(
    os.environ.get("MARKY_DIR") or Path(__file__).resolve().parent.parent / "marky"
)


def _marky_json(command: str, pattern: str, target: str) -> dict:
    """Run `marky <command> --json` and return either the parsed result wrapped
    under its key, or {"error": ...}."""
    res = subprocess.run(
        [sys.executable, "-m", "marky", command, pattern, target, "--json"],
        cwd=MARKY_DIR,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        try:
            return json.loads(res.stderr)  # {"error": "<message>"}
        except json.JSONDecodeError:
            tail = next(
                (ln for ln in reversed(res.stderr.splitlines()) if ln.strip()),
                "marky CLI error",
            )
            return {"error": tail}
    array = json.loads(res.stdout)
    key = "deltas" if command == "execute" else "matches"
    return {key: array}


def main() -> None:
    raw = sys.stdin.read().lstrip("﻿").strip()
    req = json.loads(raw or "{}")
    command = "execute" if req.get("mode") == "execute" else "find"
    payload = _marky_json(command, req.get("pattern", ""), req.get("target", ""))
    sys.stdout.write(json.dumps(payload))


if __name__ == "__main__":
    main()
