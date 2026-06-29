"""CI/CD gate: fail the test suite when any linter or type checker reports issues.

Add this file to your test suite to enforce strict lint + type hygiene.
Run it standalone:

    pytest tests/test_lint.py

Or run individual checks:

    pytest tests/test_lint.py -k "ruff_check"
    pytest tests/test_lint.py -k "ruff_format"
    pytest tests/test_lint.py -k "ty_check"
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_ruff_check() -> None:
    """``ruff check`` must produce zero diagnostics."""
    result = _run(["ruff", "check", str(ROOT)])
    assert result.returncode == 0, (
        f"ruff check failed (exit {result.returncode}):\n\n{result.stdout}\n{result.stderr}"
    )


def test_ruff_format() -> None:
    """``ruff format --check`` must report no reformats needed."""
    result = _run(["ruff", "format", "--check", str(ROOT)])
    assert result.returncode == 0, (
        f"ruff format --check found unformatted files (exit {result.returncode}):\n\n{result.stdout}"
    )


def test_ty_check() -> None:
    """``ty check`` must produce zero diagnostics."""
    result = _run(["ty", "check", str(ROOT)])
    assert result.returncode == 0, (
        f"ty check failed (exit {result.returncode}):\n\n{result.stdout}\n{result.stderr}"
    )


def test_vulture() -> None:
    """No dead code above 80 % confidence."""
    result = _run(
        [
            "vulture",
            str(ROOT / "himark"),
            "--min-confidence",
            "80",
            "--exclude",
            "_generated/,.venv/,tests/,regenerate.py",
        ]
    )
    assert result.returncode == 0, (
        f"vulture found dead code (exit {result.returncode}):\n\n{result.stdout}"
    )


def test_import_linter() -> None:
    """Import-linter contracts must all pass."""
    result = _run(["lint-imports", "--config", str(ROOT / "pyproject.toml")])
    assert result.returncode == 0, (
        f"import-linter failed (exit {result.returncode}):\n\n{result.stdout}\n{result.stderr}"
    )
