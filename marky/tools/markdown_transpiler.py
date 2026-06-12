#!/usr/bin/env python3
"""Transpile docs/HMK.md to docs/HMK.html by running a list of Himark commands.

A bare experiment: read the document, run each `=>+` (replace-mode) Himark
statement over it in turn, write the result. No escaping, no block parsing, no
styling — just to see how far a plain sequence of Himark commands gets. Output
is rough where Himark can't yet reach (e.g. markup inside code fences is still
transformed); that's the point of the test.

Run:  python -m marky.tools.markdown_transpiler
"""

from pathlib import Path

from marky import parser
from marky.engine import execute

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "HMK.md"
DST = ROOT / "docs" / "HMK.html"

# Himark commands, applied in sequence to the whole document.
COMMANDS = [
    "{\<!--<<>>-->} =>+ ",  # strip comments (before escaping eats the delimiters)
    "{\&} =>+ &amp;",  # escape & first, or it re-escapes the entities below
    "{\<} =>+ &lt;",  # escape <
    "{\>} =>+ &gt;",  # escape >
    # "{\n|}<<|>>{|\n} =>+ <tr>{{1}}</tr>",  # tables (rough)
    "{```<<>>```} =>+ <pre><code>{{0}}</code></pre>",  # code blocks
    "{`<<>>`} =>+ <code>{{0}}</code>",  # inline code
    "{#}[1..6]{ }{!\n} =>+ <h{{#0}}>{{2}}</h{{#0}}>",  # headings
    "{**<<>>**} =>+ <strong>{{0}}</strong>",  # bold
    "{*<<>>*} =>+ <em>{{0}}</em>",  # italic
    "{\n---\n} =>+ \n<hr>\n",  # horizontal rule (own line, not table rules)
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
