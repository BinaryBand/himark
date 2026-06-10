"""North Star: Markdown headings — docs/HMK.md"""

from marky import parser
from marky.engine import execute

# Three-step chain: split on newlines → match heading structure → render HTML.
# Spec writes "{#}[1..6] { } {!\n}" with surrounding spaces for readability, but
# those spaces are literal leaf text in HMK — the compact form below is correct.
PATTERN = "<<\n>> => {#}[1..6]{ }{!\n} => <h{{#0}}>{{2}}</h{{#0}}>"


def render(text):
    return execute(parser.parse(PATTERN), text)


def test_h1():
    assert render("# Hello") == ["<h1>Hello</h1>"]


def test_h2():
    assert render("## World") == ["<h2>World</h2>"]


def test_h6():
    assert render("###### Deep") == ["<h6>Deep</h6>"]


def test_multiple_headings():
    result = render("# One\n## Two\n### Three")
    assert result == ["<h1>One</h1>", "<h2>Two</h2>", "<h3>Three</h3>"]


def test_non_heading_lines_dropped():
    result = render("# Title\nnot a heading\n## Section")
    assert result == ["<h1>Title</h1>", "<h2>Section</h2>"]


def test_seven_hashes_produces_h6():
    # HMK has no anchors: ####### contains ###### at offset 1, so the engine
    # returns a h6 result. There is no h7 match.
    result = render("####### Too deep")
    assert result == ["<h6>Too deep</h6>"]
    assert not any("<h7>" in r for r in result)
