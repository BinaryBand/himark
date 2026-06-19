"""Architecture guard — runs the import-linter contracts as a test.

The layering (`main > tools > {parser, engine} > models`) is declared in
`pyproject.toml` under `[tool.importlinter]`. This test fails the suite if any
import crosses a layer the wrong way — most importantly if `parser` and `engine`
(independent siblings) ever import each other instead of communicating only
through the `models` AST.
"""

from pathlib import Path

import pytest

pytest.importorskip(
    "importlinter", reason="import-linter not installed (dev dependency)"
)

from importlinter.api import use_cases  # noqa: E402  (guarded by importorskip)

_CONFIG = str(Path(__file__).resolve().parent.parent / "pyproject.toml")


def test_import_contracts_hold():
    ok = use_cases.lint_imports(config_filename=_CONFIG, cache_dir=None)
    assert ok is True, "import-linter contract(s) broken — see report above"
