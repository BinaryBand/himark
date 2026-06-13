#!/usr/bin/env python3
"""Transpile docs/HMK.md to docs/HMK.html by running a list of Himark commands.

A bare experiment: read the document and run each replace-mode (`=>+`) Himark
statement over it in turn. The experimental core has no separators or numbered
captures, so this is deliberately minimal — the HTML-escape pass, which only
needs constant templates. Richer block/inline rules await the spec's North Star
section (currently a TODO in docs/HMK.md).

Run:  python -m marky.tools.markdown_transpiler
"""

from pathlib import Path

from marky import parser
from marky.engine import execute

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "HMK.md"
DST = ROOT / "docs" / "HMK.html"

COMMANDS = [
    r"{\&} =>+ &amp;",  # escape & first, or it re-escapes the entities below
    r"{\<} =>+ &lt;",  # escape <
    r"{\>} =>+ &gt;",  # escape >
]


def transpile(text: str) -> str:
    for command in COMMANDS:
        result = execute(parser.parse(command), text)
        text = result if isinstance(result, str) else "\n".join(result)
    return text


def main() -> None:
    DST.write_text(transpile(SRC.read_text("utf-8")), "utf-8")
    print(f"wrote {DST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
