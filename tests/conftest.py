"""Pytest configuration.

Before any tests are collected, ``ruff format``, ``ruff check --fix``, and
``ty check --fix`` are run proactively so trivial format/lint/type issues are
fixed before the suite exercises them.  Failures are reported as warnings but
do **not** block the test run — the CI-gate tests in ``test_lint.py`` still
serve as the final arbiter.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    from hypothesis import settings

    settings.register_profile("no_deadline", deadline=None)
    settings.load_profile("no_deadline")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_BIN = Path(sys.executable).parent


# ---------------------------------------------------------------------------
# Proactive lint / format / type-check helpers
# ---------------------------------------------------------------------------


def _run_tool(cmd: list[str], label: str) -> None:
    """Run *cmd* from *ROOT*; print a warning to stderr on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        print(
            f"\n[{label}] exited {result.returncode}:\n"
            f"{result.stdout}\n{result.stderr}",
            file=sys.stderr,
        )


def pytest_sessionstart(session: object) -> None:
    """Proactively fix trivial format/lint/type issues before the suite runs.

    The suite runs the **in-process** Python engine (`himark.engine.run_pipeline`),
    the single implementation while the grammar settles, so no engine build hooks run
    here. The `sandbox/` ports are archived; to validate a re-port, build the port by
    hand and select it with `HMK_ENGINE` (e.g. `HMK_ENGINE=rust`)."""
    _run_tool([str(_BIN / "ruff"), "format", str(ROOT)], "ruff format")
    _run_tool([str(_BIN / "ruff"), "check", "--fix", str(ROOT)], "ruff check --fix")
    _run_tool([str(_BIN / "ty"), "check", "--fix"], "ty check --fix")
