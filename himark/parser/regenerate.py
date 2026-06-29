"""Regenerate the ANTLR Python parser for the braceBody slice from docs/GRAMMAR.g4.

The generated lexer/parser/visitor under `_generated/` are a *build product* of the
grammar and are git-ignored; this script reproduces them. Run after editing
docs/GRAMMAR.g4 (or on a fresh checkout):

    python -m himark.parser.regenerate

Requirements:
  • Java (any JRE/JDK 11+ on PATH).
  • The matching runtime: `antlr4-python3-runtime==4.13.2` (a project dev dependency).

The tool jar is downloaded automatically on first run to ~/.antlr/. The jar version
must match the runtime version, or ANTLR refuses to load the generated parser.
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ANTLR_VERSION = "4.13.2"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GRAMMAR = ROOT / "docs" / "GRAMMAR.g4"
OUT = HERE / "_generated"

_JAR_URL = f"https://www.antlr.org/download/antlr-{ANTLR_VERSION}-complete.jar"
_DEFAULT_JAR = Path.home() / ".antlr" / f"antlr-{ANTLR_VERSION}-complete.jar"


def _ensure_jar() -> Path:
    jar = Path(os.environ.get("ANTLR_JAR", _DEFAULT_JAR))
    if not jar.is_file():
        print(f"Downloading ANTLR {ANTLR_VERSION} tool jar to {jar} ...")
        jar.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(_JAR_URL, jar)
        print("Download complete.")
    return jar


def main() -> None:
    jar = _ensure_jar()
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
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        sys.exit("java not found on PATH. Install a JRE/JDK 11+.")
    (OUT / "__init__.py").touch()
    print(f"regenerated {OUT}")


if __name__ == "__main__":
    main()
