"""Regenerate the ANTLR Python parser for the braceBody slice from docs/GRAMMAR.g4.

The generated lexer/parser/visitor under `_generated/` are a *build product* of the
grammar and are git-ignored; this script reproduces them. Run after editing
docs/GRAMMAR.g4 (or on a fresh checkout):

    python -m himark.parser.regenerate

Requirements:
  • Java (any JRE/JDK 11+ on PATH).
  • The ANTLR 4.13.2 *complete* tool jar. Point `ANTLR_JAR` at it, or drop it at
    the default path below. Get it from https://www.antlr.org/download/antlr-4.13.2-complete.jar
  • The matching runtime: `antlr4-python3-runtime==4.13.2` (a project test dependency).

The tool jar version must match the runtime version, or ANTLR refuses to load the
generated parser.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ANTLR_VERSION = "4.13.2"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GRAMMAR = ROOT / "docs" / "GRAMMAR.g4"
OUT = HERE / "_generated"

_DEFAULT_JAR = Path.home() / ".antlr" / f"antlr-{ANTLR_VERSION}-complete.jar"


def _find_jar() -> Path:
    jar = Path(os.environ.get("ANTLR_JAR", _DEFAULT_JAR))
    if not jar.is_file():
        sys.exit(
            f"ANTLR tool jar not found at {jar}.\n"
            f"Set ANTLR_JAR, or download antlr-{ANTLR_VERSION}-complete.jar from\n"
            f"  https://www.antlr.org/download/antlr-{ANTLR_VERSION}-complete.jar\n"
            f"and place it at {_DEFAULT_JAR} (or point ANTLR_JAR at it)."
        )
    return jar


def main() -> None:
    jar = _find_jar()
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [
        "java",
        "-jar",
        str(jar),
        "-Dlanguage=Python3",
        "-visitor",
        "-no-listener",
        "-o",
        str(OUT),
        "-Xexact-output-dir",
        str(GRAMMAR),
    ]
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)
    # ANTLR does not emit a package marker; the slice imports `_generated` as one.
    (OUT / "__init__.py").touch()
    print(f"regenerated {OUT}")


if __name__ == "__main__":
    main()
