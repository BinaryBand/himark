"""The HMK-self-hosted Markdown tidy (`himark/scripts/md_format.hmk`).

A second dogfooding formatter, the Markdown sibling of `hmk_format.hmk`. We pin the
line-local tidies (file edges, trailing whitespace, blank runs, ATX heading
spacing, bullet normalization), that they stay idempotent, and — crucially — that
the **masking pre-pass** protects fenced ``` … ``` code: messy interior spacing, a
`*` that is not a bullet, and a `##` that is not a heading all survive verbatim.
"""

from pathlib import Path

from himark.tools import precompiled

SCRIPT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "md_format.hmk"
RESOURCES = Path(__file__).resolve().parent / "resources"
OUTPUT = Path(__file__).resolve().parent / "output"
_PIPELINE = precompiled.compile_pipeline(precompiled.load_script(SCRIPT))


def fmt(src: str) -> str:
    return precompiled.apply(_PIPELINE, src)


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
        "# Heading\n\nIntro paragraph.\n\n## Section\n"
        "- item one\n- item two\n  - nested item\n\n"
        "```py\ndef  f(x):\n    y = *x   \n    ##  not a heading\n```\n\nDone.\n"
    )
    assert fmt(out) == out  # idempotent


# Runbook: write the formatted fixture to `tests/demos/output` for manual inspection
if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    src = (RESOURCES / "messy.md").read_text("utf-8")
    (OUTPUT / "formatted_messy.md").write_text(fmt(src), "utf-8")
    print(f"Wrote formatted_messy.md to {OUTPUT}")
