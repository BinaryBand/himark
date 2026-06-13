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

# COMMANDS = [
#     r"<!--<<>>--> =>+",  # remove comments
#     r"{\&} =>+ &amp;",  # escape & first, or it re-escapes the entities below
#     r"{\<} =>+ &lt;",  # escape <
#     r"{\>} =>+ &gt;",  # escape >
#     r"{```<<>>```} =>+ <pre><code>{{0}}</code></pre>",  # code blocks
#     r"{`<<>>`} =>+ <code>{{0}}</code>",  # inline code
#     r"{#}[1..6]{ }{!\n} =>+ <h{{#0}}>{{2}}</h{{#0}}>",  # headings
#     # blockquote: anchored at line start ({\n}); {!\n} grabs the rest of the
#     # line.  Mirrors the heading idiom.  The marker is the escaped '&gt;' since
#     # the escape pass above already ran.  {{3}} is the line body (group 3).
#     r"{\n}{&gt;}{ }{!\n} =>+ \n<blockquote>{{3}}</blockquote>",
#     r"{**<<>>**} =>+ <strong>{{0}}</strong>",  # bold
#     r"{*<<>>*} =>+ <em>{{0}}</em>",  # italic
#     # hr: 3+ of the same rule char, spaces interleaved or not — each unit is a
#     # congruence of two spellings, "char + escaped space" and "char".
#     r"{\n}{{-\ <->-},{*\ <->*},{_\ <->_}}[3..]{ }[0..]{\n} =>+ \n<hr>\n",
# ]

title = "| Construct | Role                      |"
div = "| --------- | ------------------------- |"

COMMANDS = [
    "{| Construct{ }[..]| Role{ }[..]|} =>+ header",
    # "| Construct{ }[..]| Role{ }[..]| =>+ header",
    # f"{div} =>+ divider",
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
