"""North Star: in-place document transpilation via replace-mode (`=>+`).

`=>` *extracts* — the statement returns the list of rendered matches. `=>+`
*replaces* — it splices each rendered match back into the source and returns the
whole string, keeping the text between matches verbatim. That turns a single HMK
statement into a document transform, and a short pipeline of them into a small
Markdown transpiler.
"""

from marky import parser
from marky.engine import execute


def transform(pattern, text):
    return execute(parser.parse(pattern), text)


# ── Extract vs replace ────────────────────────────────────────────────────────


def test_extract_returns_list_of_matches():
    assert transform("{a..z} => <p>{{.}}</p>", "a1b2c") == [
        "<p>a</p>",
        "<p>b</p>",
        "<p>c</p>",
    ]


def test_replace_returns_whole_text_spliced():
    assert transform("{a..z} =>+ <p>{{.}}</p>", "a1b2c") == "<p>a</p>1<p>b</p>2<p>c</p>"


def test_replace_keeps_non_matching_text_verbatim():
    out = transform("{**<<>>**} =>+ <strong>{{0}}</strong>", "say **hi** now")
    assert out == "say <strong>hi</strong> now"


def test_replace_no_match_is_identity():
    assert transform("{a..z} =>+ <p>{{.}}</p>", "123") == "123"


# ── Whitespace formatting ─────────────────────────────────────────────────────
# A captured single unit ({{0}}) is the replacement, so a run collapses to one.


def collapse_spaces(text):
    return transform("{ }{ }[1..] =>+ {{0}}", text)


def test_collapse_runs_of_spaces():
    assert collapse_spaces("a   b    c d") == "a b c d"


def test_single_spaces_preserved():
    assert collapse_spaces("a b c") == "a b c"


def test_collapse_blank_lines():
    # Two or more newlines collapse to one; single newlines are untouched.
    assert transform("{\n}{\n}[1..] =>+ {{0}}", "a\n\n\nb\nc") == "a\nb\nc"


# ── A small Markdown transpiler ───────────────────────────────────────────────
# Each rule is one replace-mode statement; the host applies them in order. Bold
# runs before italic so '**' is consumed before the single-'*' rule sees it.

RULES = [
    "{#}[1..6]{ }{!\n} =>+ <h{{#0}}>{{2}}</h{{#0}}>",  # ATX headings
    "{**<<>>**} =>+ <strong>{{0}}</strong>",  # bold
    "{*<<>>*} =>+ <em>{{0}}</em>",  # italic
    "{`<<>>`} =>+ <code>{{0}}</code>",  # inline code
]


def transpile(md):
    for rule in RULES:
        md = transform(rule, md)
    return md


def test_transpile_inline_only():
    src = "This is **bold**, *italic*, and `code`."
    assert transpile(src) == (
        "This is <strong>bold</strong>, <em>italic</em>, and <code>code</code>."
    )


def test_transpile_heading_levels():
    assert transpile("# Title") == "<h1>Title</h1>"
    assert transpile("###### Deep") == "<h6>Deep</h6>"


def test_transpile_inline_inside_heading():
    # Headings render first; the inline rules then wrap markup inside the text.
    assert transpile("## **Bold** heading") == "<h2><strong>Bold</strong> heading</h2>"


def test_transpile_multiple_bold_on_one_line():
    src = "**one** and **two** and **three**"
    assert transpile(src) == (
        "<strong>one</strong> and <strong>two</strong> and <strong>three</strong>"
    )


def test_transpile_full_document():
    src = (
        "# Welcome\n"
        "This is **bold** text and *italic* too.\n"
        "Run `npm install` first.\n"
        "## Notes\n"
        "Mix **bold** and `code`."
    )
    expected = (
        "<h1>Welcome</h1>\n"
        "This is <strong>bold</strong> text and <em>italic</em> too.\n"
        "Run <code>npm install</code> first.\n"
        "<h2>Notes</h2>\n"
        "Mix <strong>bold</strong> and <code>code</code>."
    )
    assert transpile(src) == expected
