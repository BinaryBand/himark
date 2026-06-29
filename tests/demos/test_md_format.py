"""The HMK-self-hosted Markdown tidy (`himark/scripts/format_md.hmk`).

A second dogfooding formatter, the Markdown sibling of `format_hmk.hmk`. We pin the
line-local tidies (file edges, trailing whitespace, blank runs, ATX heading
spacing, bullet normalization), that they stay idempotent, and — crucially — that
the **masking pre-pass** protects fenced ``` … ``` code: messy interior spacing, a
`*` that is not a bullet, and a `##` that is not a heading all survive verbatim.
"""

from pathlib import Path

from himark import engine, parser

SCRIPT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "format_md.hmk"
RESOURCES = Path(__file__).resolve().parent / "resources"
OUTPUT = Path(__file__).resolve().parent / "output"
_PIPELINE = parser.load_script(str(SCRIPT))


def fmt(src: str) -> str:
    return engine.run_pipeline(_PIPELINE, src)


# ── Line-local tidies ─────────────────────────────────────────────────────────


def test_strips_trailing_whitespace():
    assert fmt("body   \n") == "body\n"


def test_collapses_blank_runs():
    assert fmt("a\n\n\n\n\nb\n") == "a\n\nb\n"


def test_trims_file_edges():
    assert fmt("\n\n# H\n\n\n") == "# H\n"


def test_heading_collapses_extra_spaces():
    assert fmt("##   Title\n") == "## Title\n"


def test_heading_inserts_missing_space():
    assert fmt("##Title\n") == "## Title\n"


def test_well_formed_heading_is_unchanged():
    assert fmt("### Title\n") == "### Title\n"


def test_seven_hashes_is_not_a_heading():
    # ATX headings are 1–6 deep; a 7-`#` run is left alone (no space inserted).
    assert fmt("####### x\n") == "####### x\n"


# ── Bullet normalization ──────────────────────────────────────────────────────


def test_star_and_plus_bullets_become_dash():
    assert fmt("para\n* a\n+ b\n") == "para\n- a\n- b\n"


def test_bullet_space_run_is_normalized():
    assert fmt("para\n*   spaced\n") == "para\n- spaced\n"


def test_bullet_indentation_is_preserved():
    assert fmt("para\n  + nested\n") == "para\n  - nested\n"


def test_emphasis_is_not_a_bullet():
    # `*emph*` has no space after the `*`, so it is prose, not a list marker.
    assert fmt("*emph* and text\n") == "*emph* and text\n"


# ── Unwrapping soft-wrapped paragraphs ────────────────────────────────────────


def test_unwraps_a_paragraph_to_one_line():
    assert fmt("one two\nthree four\nfive six\n") == "one two three four five six\n"


def test_unwrap_keeps_paragraph_breaks():
    assert fmt("a b\nc d\n\ne f\ng h\n") == "a b c d\n\ne f g h\n"


def test_unwrap_leaves_a_heading_on_its_own_line():
    # The heading is not pulled down, and the body below it still unwraps.
    assert fmt("# Title\nbody one\nbody two\n") == "# Title\nbody one body two\n"


def test_unwrap_does_not_merge_block_constructs():
    # Lists, blockquotes, tables, thematic breaks, and setext underlines each keep
    # their line breaks (their lines start with a marker the unwrap rule excludes).
    assert fmt("- a\n- b\n") == "- a\n- b\n"
    assert fmt("> q\n> r\n") == "> q\n> r\n"
    assert fmt("text here\n***\nmore here\n") == "text here\n***\nmore here\n"
    assert fmt("Title\n=====\n") == "Title\n=====\n"


# ── Joining soft-wrapped list-item continuations ──────────────────────────────


def test_joins_list_item_continuation():
    # A line indented 2–3 spaces with prose first is a soft-wrap of the item above:
    # the newline+indent collapses to a single space, onto the bullet line.
    assert fmt("- item one\n  wrapped tail\n- item two\n") == (
        "- item one wrapped tail\n- item two\n"
    )


def test_continuation_join_does_not_swallow_a_nested_bullet():
    # The continuation's first real char is a `-`, a marker the rule excludes, so
    # the nested item keeps its own line.
    assert fmt("- a\n  - nested\n") == "- a\n  - nested\n"


def test_continuation_join_keeps_a_blank_separated_loose_item():
    # A blank line before the indented line means a loose-list paragraph, not a
    # soft-wrap — the non-blank anchor leaves it alone.
    assert fmt("- a\n\n  loose para\n") == "- a\n\n  loose para\n"


# ── Fenced code is protected ──────────────────────────────────────────────────


def test_fenced_code_is_preserved_verbatim():
    src = "# H\n\n```py\ndef  f( ):\n    *x   \n   ##notheading\n```\nafter  \n"
    out = fmt(src)
    # The fence body keeps its double spaces, its `*x`, its `##`, and its trailing
    # whitespace — only the prose around it is tidied.
    assert "```py\ndef  f( ):\n    *x   \n   ##notheading\n```" in out
    assert out.endswith("after\n")  # the line after the fence is still tidied


# ── End-to-end on the messy fixture ───────────────────────────────────────────


def test_messy_fixture_is_fully_tidied_and_idempotent():
    out = fmt((RESOURCES / "messy.md").read_text("utf-8"))
    assert out == (
        "# Heading\n\n"
        "This intro paragraph is hard wrapped over a few lines.\n\n"
        "## Section\n- item one\n- item two\n  - nested item\n\n"
        "```py\ndef  f(x):\n    y = *x   \n    ##  not a heading\n```\n\nDone.\n"
    )
    assert fmt(out) == out  # idempotent


# Runbook: write the formatted fixture to `tests/demos/output` for manual inspection
if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    src = (RESOURCES / "messy.md").read_text("utf-8")
    (OUTPUT / "formatted_messy.md").write_text(fmt(src), "utf-8")
    print(f"Wrote formatted_messy.md to {OUTPUT}")
