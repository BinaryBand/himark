"""North Star: Markdown translations — docs/HMK.md"""

import html

import pytest

from marky import parser
from marky.engine import execute

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

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


# ── Tables ────────────────────────────────────────────────────────────────────
# How far does table → HTML conversion go in pure HMK?
#
#   1. A fixed-shape table (known columns × known rows) converts completely —
#      <table> wrapper, <th> header, <td> body — in ONE statement, because leaf
#      literals may contain newlines, so the whole table is a single match.
#   2. Arbitrary row count needs host composition: per-row HMK programs applied
#      line by line. HMK has no cross-match state, so "first row is the header"
#      and the <table> wrapper live in the caller.
#   3. Variable column count is out of reach for full rendering: [N] repetition
#      is equality-based (same unit repeated), so unequal cells can't repeat,
#      and templates can't iterate. A separator-split still exposes the cells
#      positionally ({{0.M}}) and their count ({{#0}}).
#
# Cell padding: a cell is {!|} (complement of pipe), which keeps the spaces
# around the content — there is no inter-element backtracking, so a greedy
# complement can't give back a trailing space to a ` |` literal. The trimmed
# form {!|, } works only for cells without inner spaces (used for headers).

# 2-col × 2-row table as one statement. Groups in document order: header cells
# 0–1, alignment cells 2–3, body cells 4–5 and 6–7.
TABLE_2X2 = (
    "| {!|, } | {!|, } |\n"
    "| { {-,:} } | { {-,:} } |\n"
    "|{!|}|{!|}|\n"
    "|{!|}|{!|}|"
    " => <table><tr><th>{{0}}</th><th>{{1}}</th></tr>"
    "<tr><td>{{4}}</td><td>{{5}}</td></tr>"
    "<tr><td>{{6}}</td><td>{{7}}</td></tr></table>"
)

# Per-row programs for host composition.
HEADER_ROW = "| {!|, } | {!|, } | => <tr><th>{{0}}</th><th>{{1}}</th></tr>"
ALIGN_ROW = "| { {-,:} } | { {-,:} } |"  # classifier: matches iff alignment row
BODY_ROW = "|{!|}|{!|}| => <tr><td>{{0}}</td><td>{{1}}</td></tr>"

TABLE = "| Name | Age |\n| --- | --- |\n| Alice | 30 |\n| Bob | 25 |"
TABLE_HTML = (
    "<table><tr><th>Name</th><th>Age</th></tr>"
    "<tr><td> Alice </td><td> 30 </td></tr>"
    "<tr><td> Bob </td><td> 25 </td></tr></table>"
)


def test_fixed_shape_table_single_statement():
    assert execute(parser.parse(TABLE_2X2), TABLE) == [TABLE_HTML]


def test_fixed_shape_requires_exact_shape():
    # One body row short — the single-statement form is rigid by design.
    three_lines = "| Name | Age |\n| --- | --- |\n| Alice | 30 |"
    assert execute(parser.parse(TABLE_2X2), three_lines) == []


def test_alignment_classifier_accepts_dashes():
    assert execute(parser.parse(ALIGN_ROW), "| --- | --- |") != []


def test_alignment_classifier_accepts_colons():
    assert execute(parser.parse(ALIGN_ROW), "| :-- | --: |") != []


def test_alignment_classifier_rejects_data_row():
    assert execute(parser.parse(ALIGN_ROW), "| Alice | 30 |") == []


def test_alignment_classifier_rejects_hyphenated_words():
    # The {-,:} run must start immediately after '| ', so a-b is not mistaken
    # for an alignment cell.
    assert execute(parser.parse(ALIGN_ROW), "| a-b | c |") == []


def test_body_row_keeps_cell_padding():
    result = execute(parser.parse(BODY_ROW), "| Alice | 30 |")
    assert result == ["<tr><td> Alice </td><td> 30 </td></tr>"]


def test_body_row_multiword_cells():
    result = execute(parser.parse(BODY_ROW), "| Alice Smith | 30 |")
    assert result == ["<tr><td> Alice Smith </td><td> 30 </td></tr>"]


def test_body_row_also_matches_alignment_row():
    # The known leak: per-row programs are stateless, so the alignment row
    # looks like data. Host composition must classify it first (ALIGN_ROW).
    result = execute(parser.parse(BODY_ROW), "| --- | --- |")
    assert result == ["<tr><td> --- </td><td> --- </td></tr>"]


def test_variable_columns_positional_refs():
    # A lone value-separator splits its span: cells land in sub-groups,
    # addressable as {{0.M}}, with the piece count in {{#0}}. Templates cannot
    # iterate, so rendering still requires a fixed arity.
    pat = "|<<|>> => <tr cols={{#0}}><td>{{0.0}}</td><td>{{0.1}}</td></tr>"
    result = execute(parser.parse(pat), "| Alice | 30 |")
    assert result == ["<tr cols=3><td> Alice </td><td> 30 </td></tr>"]


def test_host_composition_arbitrary_row_count():
    # The general pipeline: HMK programs per row, host code for sequencing.
    def md_table_to_html(md: str) -> str:
        lines = md.split("\n")
        head = execute(parser.parse(HEADER_ROW), lines[0])
        assert execute(parser.parse(ALIGN_ROW), lines[1])
        body = [r for ln in lines[2:] for r in execute(parser.parse(BODY_ROW), ln)]
        return "<table>" + "".join([*head, *body]) + "</table>"

    assert md_table_to_html(TABLE) == TABLE_HTML

    bigger = TABLE + "\n| Carol | 41 |"
    assert md_table_to_html(bigger) == TABLE_HTML.replace(
        "</table>", "<tr><td> Carol </td><td> 41 </td></tr></table>"
    )


# ── Property tests: the whole range of table shapes ───────────────────────────
# A host that knows the column count can generate a column-count-sized HMK
# program, so arbitrary `cols × rows` shapes are reachable with thin glue. The
# two properties below separate what works from what doesn't:
#
#   structural — HMK extracts the exact between-pipe substring of every cell, for
#                any shape. This is the achievable result today and stays green.
#   real-markdown — the same conversion measured against *real* CommonMark output
#                (cells trimmed, `&<>` escaped). HMK does neither, so this is an
#                xfail: a living TODO for the trim + escape gaps, which will flip
#                to xpass once the engine learns to trim.


def _row_pat(n: int) -> str:
    return "|" + "{!|}|" * n  # n untrimmed cells; padding is captured verbatim


def _align_pat(n: int) -> str:
    return "|" + " { {-,:} } |" * n  # n alignment cells (run of '-'/':')


def _refs(tag: str, n: int) -> str:
    return "".join("<" + tag + ">{{" + str(i) + "}}</" + tag + ">" for i in range(n))


def _build_source(headers, aligns, rows) -> str:
    """Render a markdown table, every cell padded as ' <text> ' between pipes."""

    def line(cells):
        return "|" + "".join(" " + c + " |" for c in cells)

    return "\n".join([line(headers), line(aligns), *(line(r) for r in rows)])


def _hmk_convert(source: str, n: int) -> str:
    """Convert a markdown table to HTML with per-row HMK programs sized to n."""
    lines = source.split("\n")
    head = execute(
        parser.parse(_row_pat(n) + " => <tr>" + _refs("th", n) + "</tr>"), lines[0]
    )
    assert execute(parser.parse(_align_pat(n)), lines[1]), (
        "alignment row not recognized"
    )
    body_prog = _row_pat(n) + " => <tr>" + _refs("td", n) + "</tr>"
    body = [r for ln in lines[2:] for r in execute(parser.parse(body_prog), ln)]
    return "<table>" + "".join([*head, *body]) + "</table>"


if HAS_HYPOTHESIS:
    # Printable ASCII cell text, minus the pipe (the column delimiter). Newlines
    # and tabs are already excluded by the codepoint floor of 32.
    _CELL = st.text(
        alphabet=st.characters(
            min_codepoint=32, max_codepoint=126, exclude_characters="|"
        ),
        max_size=8,
    )
    # A valid alignment marker: 1+ dashes with optional leading/trailing colon.
    _ALIGN = st.builds(
        lambda left, dashes, right: left + "-" * dashes + right,
        st.sampled_from(["", ":"]),
        st.integers(min_value=1, max_value=3),
        st.sampled_from(["", ":"]),
    )

    @st.composite
    def _tables(draw):
        n = draw(st.integers(min_value=1, max_value=4))
        headers = draw(st.lists(_CELL, min_size=n, max_size=n))
        aligns = draw(st.lists(_ALIGN, min_size=n, max_size=n))
        rows = draw(st.lists(st.lists(_CELL, min_size=n, max_size=n), max_size=4))
        return headers, aligns, rows

    @settings(max_examples=300)
    @given(_tables())
    def test_table_shapes_structural(table):
        """Any rectangular shape converts with exact, verbatim cell fidelity."""
        headers, aligns, rows = table
        n = len(headers)
        source = _build_source(headers, aligns, rows)

        def cells(tag, values):
            return "<tr>" + "".join(f"<{tag}> {v} </{tag}>" for v in values) + "</tr>"

        expected = (
            "<table>"
            + cells("th", headers)
            + "".join(cells("td", r) for r in rows)
            + "</table>"
        )
        assert _hmk_convert(source, n) == expected

    @pytest.mark.xfail(
        reason="HMK keeps cell padding and does not HTML-escape; trim/escape are TODO",
        strict=False,
    )
    @settings(max_examples=200)
    @given(_tables())
    def test_table_real_markdown(table):
        """The same conversion measured against real CommonMark rendering."""
        headers, aligns, rows = table
        n = len(headers)
        source = _build_source(headers, aligns, rows)

        def esc(s):
            return html.escape(s.strip(), quote=False)

        def cells(tag, values):
            return (
                "<tr>" + "".join(f"<{tag}>{esc(v)}</{tag}>" for v in values) + "</tr>"
            )

        expected = (
            "<table>"
            + cells("th", headers)
            + "".join(cells("td", r) for r in rows)
            + "</table>"
        )
        assert _hmk_convert(source, n) == expected
