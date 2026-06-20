"""Strict, end-to-end tests for the Markdown -> HTML transpiler script
(`himark/scripts/md_html.hmk`).

Each test asserts the *exact* HTML the pipeline emits for a small Markdown input,
so the script's behaviour -- including its deliberate edge-case handling and its
documented limitations -- is pinned. The pipeline is loaded once from the real
script file, so these tests track the shipped transpiler, not a copy.
"""

from pathlib import Path

import pytest

from himark.tools import precompiled

SCRIPT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "md_html.hmk"
RESOURCES = Path(__file__).resolve().parent / "resources"
_PIPELINE = precompiled.compile_pipeline(precompiled.load_script(SCRIPT))


def md(source: str) -> str:
    """Transpile `source` Markdown to HTML with the shipped pipeline."""
    return precompiled.apply(_PIPELINE, source)


# ── Headings ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "source,expected",
    [
        ("# One", "<h1>One</h1>"),
        ("## Two", "<h2>Two</h2>"),
        ("### Three", "<h3>Three</h3>"),
        ("###### Six", "<h6>Six</h6>"),
        ("#   spaced", "<h1>spaced</h1>"),  # extra spaces collapse into the gap
    ],
)
def test_heading_levels(source, expected):
    assert md(source) == expected


def test_heading_requires_space():
    # No space after the #s -> not a heading.
    assert md("#nospace") == "#nospace"


def test_heading_must_be_line_start():
    # A mid-line '#' is never a heading (anchored at line start).
    assert md("text # not a head") == "text # not a head"


def test_heading_seven_hashes_is_not_a_heading():
    # Markdown caps ATX headings at level 6; 7 '#'s is left literal.
    assert md("####### too deep") == "####### too deep"


def test_heading_keeps_inline_formatting():
    assert md("## A **bold** word") == "<h2>A <strong>bold</strong> word</h2>"


def test_heading_with_link():
    assert md("## [home](/) page") == '<h2><a href="/">home</a> page</h2>'


# ── Horizontal rules ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("source", ["---", "***", "___", "----------"])
def test_horizontal_rule(source):
    assert md(source) == "<hr/>"


def test_hr_needs_three():
    assert md("--") == "--"


def test_hr_must_be_homogeneous():
    # A line mixing rule characters is not a rule.
    assert md("-*-") == "-*-"


# ── Blockquotes ───────────────────────────────────────────────────────────────


def test_blockquote_single_line():
    assert md("> quoted") == "<blockquote>quoted </blockquote>"


def test_blockquote_joins_lines():
    assert md("> one\n> two") == "<blockquote>one \ntwo </blockquote>"


# ── Lists ─────────────────────────────────────────────────────────────────────


def test_unordered_list_dash():
    assert md("- a\n- b\n- c") == "<ul><li>a</li>\n<li>b</li>\n<li>c</li></ul>"


@pytest.mark.parametrize("bullet", ["-", "*", "+"])
def test_unordered_list_bullets(bullet):
    assert md(f"{bullet} only") == "<ul><li>only</li></ul>"


def test_ordered_list_multidigit():
    assert (
        md("1. first\n2. second\n10. tenth")
        == "<ol><li>first</li>\n<li>second</li>\n<li>tenth</li></ol>"
    )


def test_list_items_keep_inline_formatting():
    assert md("- **bold** x\n- *i*") == (
        "<ul><li><strong>bold</strong> x</li>\n<li><em>i</em></li></ul>"
    )


def test_star_bullet_beats_italic():
    # A line-leading '* ' is a list bullet, consumed before italic can see it.
    assert md("* one\n* two") == "<ul><li>one</li>\n<li>two</li></ul>"


# ── Code ──────────────────────────────────────────────────────────────────────


def test_fenced_code_with_language():
    assert md("```python\nx = 1\n```") == (
        '<pre><code class="language-python">x = 1</code></pre>'
    )


def test_fenced_code_plain():
    assert md("```\nplain\n```") == "<pre><code>plain</code></pre>"


def test_fenced_code_multiline():
    assert md("```js\na;\nb;\n```") == (
        '<pre><code class="language-js">a;\nb;</code></pre>'
    )


def test_fenced_code_escapes_content():
    assert md("```\na < b & c\n```") == "<pre><code>a &lt; b &amp; c</code></pre>"


def test_adjacent_code_blocks_stay_separate():
    out = md("```\nA\n```\n```\nB\n```")
    assert out == "<pre><code>A</code></pre>\n<pre><code>B</code></pre>"


def test_inline_code():
    assert md("call `f(x)` now") == "call <code>f(x)</code> now"


def test_inline_code_escapes_content():
    assert md("`a < b`") == "<code>a &lt; b</code>"


# ── Links and images ──────────────────────────────────────────────────────────


def test_link():
    assert md("[docs](http://x.com/a)") == '<a href="http://x.com/a">docs</a>'


def test_image():
    assert md("![alt text](pic.png)") == '<img alt="alt text" src="pic.png"/>'


def test_image_before_link():
    # The image rule wins over the link rule for the shared `[..](..)` shape.
    assert md("![a](p.png)").startswith("<img")


def test_link_ampersand_in_url_is_escaped():
    assert md("[q](http://x?a=1&b=2)") == '<a href="http://x?a=1&amp;b=2">q</a>'


# ── Emphasis ──────────────────────────────────────────────────────────────────


def test_bold_stars():
    assert md("**bold**") == "<strong>bold</strong>"


def test_bold_underscores():
    assert md("__bold__") == "<strong>bold</strong>"


def test_italic_star():
    assert md("*it*") == "<em>it</em>"


def test_italic_underscore():
    assert md("_it_") == "<em>it</em>"


def test_bold_italic():
    assert md("***both***") == "<strong><em>both</em></strong>"


def test_strikethrough():
    assert md("~~gone~~") == "<del>gone</del>"


def test_emphasis_precedence_mixed():
    assert md("**b** and *i* and ***bi***") == (
        "<strong>b</strong> and <em>i</em> and <strong><em>bi</em></strong>"
    )


# ── Escaping ──────────────────────────────────────────────────────────────────


def test_escapes_lt_and_amp():
    assert md("a < b && c") == "a &lt; b &amp;&amp; c"


def test_gt_is_not_escaped():
    # '>' needs no escaping in text content, and leaving it lets blockquotes work.
    assert md("a > b") == "a > b"


# ── Tables ────────────────────────────────────────────────────────────────────


def test_table_basic():
    src = "| H1 | H2 |\n| --- | --- |\n| a | b |"
    assert md(src) == (
        "<table><tr><td>H1</td><td>H2</td></tr>\n<tr><td>a</td><td>b</td></tr></table>"
    )


def test_table_three_columns():
    src = "| a | b | c |\n| - | - | - |\n| 1 | 2 | 3 |"
    assert md(src) == (
        "<table><tr><td>a</td><td>b</td><td>c</td></tr>\n"
        "<tr><td>1</td><td>2</td><td>3</td></tr></table>"
    )


def test_table_cells_are_trimmed():
    src = "|x|y|\n|-|-|\n|  1  |  2  |"
    assert md(src) == (
        "<table><tr><td>x</td><td>y</td></tr>\n<tr><td>1</td><td>2</td></tr></table>"
    )


def test_table_cells_keep_inline_formatting():
    src = "| **a** | `c` |\n| - | - |\n| 1 | 2 |"
    assert md(src) == (
        "<table><tr><td><strong>a</strong></td><td><code>c</code></td></tr>\n"
        "<tr><td>1</td><td>2</td></tr></table>"
    )


def test_prose_with_pipes_is_not_a_table():
    # Rows must start with '|' to count as a table; plain prose is left alone.
    src = "this | that\nfoo | bar"
    assert md(src) == src


# ── Document-level composition ────────────────────────────────────────────────


def test_mixed_document():
    src = "# Title\n\n- a\n- b\n\n> note"
    assert md(src) == (
        "<h1>Title</h1>\n\n"
        "<ul><li>a</li>\n<li>b</li>\n</ul>\n"
        "<blockquote>note </blockquote>"
    )


# ── Documented limitations (pinned so the behaviour is defined) ───────────────


def test_limitation_inline_markdown_inside_code_is_transformed():
    # The engine cannot mask code content, so emphasis inside a fence is still
    # transformed. This is a known, accepted limitation.
    assert md("```\n**x**\n```") == "<pre><code><strong>x</strong></code></pre>"


def test_limitation_no_paragraph_wrapping():
    # Loose text is not wrapped in <p>.
    assert md("just text") == "just text"


def test_limitation_empty_link_is_literal():
    # A link needs non-empty text and URL runs.
    assert md("[]()") == "[]()"


# ── Runbook ───────────────────────────────────────────────────────────────────
# Run this file directly to transpile a real Markdown file and write the HTML
# output to `tests/demos/output` for manual inspection.
if __name__ == "__main__":
    OUTPUT = Path(__file__).resolve().parent / "output"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = (RESOURCES / "sample.md").read_text("utf-8")
    out = md(source)
    (OUTPUT / "sample.html").write_text(out, "utf-8")
    print(f"Wrote sample.html to {OUTPUT}")
