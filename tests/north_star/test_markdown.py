"""North Star: Markdown translations — docs/HMK.md"""

from marky import parser
from marky.engine import execute

# ── Headers ───────────────────────────────────────────────────────────────────
# Three-step chain: split on newlines → match heading structure → render HTML.
# Step 2 uses a literal space leaf to consume the mandatory ATX space, then
# <<>> lazily captures the heading content (group 1).
PATTERN = "<<\n>> => {#}[1..6] <<>> => <h{{#0}}>{{1}}</h{{#0}}>"


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


def test_seven_hashes_not_h7():
    # HMK has no anchors: ####### contains ###### at offset 1.
    # The match starting at position 0 fails because text[6]='#' ≠ ' '.
    # The match starting at position 1 succeeds as h6.
    result = render("####### Too deep")
    assert result == ["<h6>Too deep</h6>"]
    assert not any("<h7>" in r for r in result)


def test_heading_with_punctuation():
    assert render("## Hello, World!") == ["<h2>Hello, World!</h2>"]


def test_heading_content_preserved_verbatim():
    # Spacing inside the heading text is part of the content.
    assert render("#   spaced") == ["<h1>  spaced</h1>"]


def test_all_levels():
    lines = "\n".join(f"{'#' * n} H{n}" for n in range(1, 7))
    result = render(lines)
    assert result == [f"<h{n}>H{n}</h{n}>" for n in range(1, 7)]


# ── Decorators ────────────────────────────────────────────────────────────────
# Spec form: the brace encloses a sub-sequence and is transparent to capture
# numbering — `**` are literal text, the inner <<>> is group 0.

BOLD = "{**<<>>**} => <strong>{{0}}</strong>"
ITALIC = "{*<<>>*} => <em>{{0}}</em>"
CODE = "{`<<>>`} => <code>{{0}}</code>"


def bold(text):
    return execute(parser.parse(BOLD), text)


def italic(text):
    return execute(parser.parse(ITALIC), text)


def code(text):
    return execute(parser.parse(CODE), text)


def test_bold_basic():
    assert bold("say **hello** world") == ["<strong>hello</strong>"]


def test_bold_multiple():
    result = bold("**one** and **two**")
    assert result == ["<strong>one</strong>", "<strong>two</strong>"]


def test_bold_not_found():
    assert bold("plain text") == []


def test_italic_basic():
    assert italic("say *hello* world") == ["<em>hello</em>"]


def test_italic_multiple():
    result = italic("*one* and *two*")
    assert result == ["<em>one</em>", "<em>two</em>"]


def test_italic_not_found():
    assert italic("plain text") == []


def test_code_basic():
    assert code("use `var x = 1` here") == ["<code>var x = 1</code>"]


def test_code_with_spaces():
    assert code("`hello world`") == ["<code>hello world</code>"]


def test_code_multiple():
    result = code("both `foo` and `bar`")
    assert result == ["<code>foo</code>", "<code>bar</code>"]


def test_code_not_found():
    assert code("plain text") == []


def test_bold_and_italic_independent():
    # Bold and italic transforms are applied independently; each only sees its
    # own delimiter. Use unambiguous text so ** and * don't interfere.
    assert bold("say **strong** here") == ["<strong>strong</strong>"]
    assert italic("say *emphasized* here") == ["<em>emphasized</em>"]


def test_sequence_brace_equivalent_to_unwrapped():
    # {**<<>>**} matches exactly what the unwrapped form {**}<<>>{**} matches;
    # only the capture numbering differs (transparent vs three groups).
    wrapped = execute(parser.parse("{**<<>>**} => <strong>{{0}}</strong>"), "**hi**")
    unwrapped = execute(
        parser.parse("{**}<<>>{**} => <strong>{{1}}</strong>"), "**hi**"
    )
    assert wrapped == unwrapped == ["<strong>hi</strong>"]
