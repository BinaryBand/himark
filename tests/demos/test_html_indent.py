"""End-to-end tests for the HTML pretty-printer (`himark/scripts/html_indent.hmk`).

The script indents nested tag pairs one tab per level using a stackless,
inside-out fixed point: each pass formats the current *innermost* unformatted
pair (a pair whose body holds no raw `<`), marks its tags with `⟦ ⟧` sentinels so
its parent becomes innermost next pass, and `| indent` re-tabs the body every
pass so depth accumulates. The number of wrap passes in the script is the depth
*budget* (12 levels); these tests pin the formatting on small inputs, check the
"strip whitespace recovers the source" invariant, and confirm graceful behaviour
when nesting exceeds the budget.
"""

from pathlib import Path

from himark.tools import precompiled

SCRIPT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "html_indent.hmk"
RESOURCES = Path(__file__).resolve().parent / "resources"
_PIPELINE = precompiled.compile_pipeline(precompiled.load_script(SCRIPT))


def run(text: str) -> str:
    return precompiled.apply(_PIPELINE, text)


def test_single_leaf():
    assert run("<p>hi</p>") == "<p>\n\thi\n</p>"


def test_nested_pair_indents_one_level():
    assert run("<a><b>x</b></a>") == "<a>\n\t<b>\n\t\tx\n\t</b>\n</a>"


def test_siblings_land_on_their_own_lines():
    # Adjacent `</b><c>` with no whitespace between them are still separated —
    # each formatted block carries a leading newline.
    assert run("<a><b>x</b><c>y</c></a>") == (
        "<a>\n\t<b>\n\t\tx\n\t</b>\n\t<c>\n\t\ty\n\t</c>\n</a>"
    )


def test_depth_accumulates():
    out = run("<html><body><p>hi</p></body></html>")
    assert out == (
        "<html>\n"
        "\t<body>\n"
        "\t\t<p>\n"
        "\t\t\thi\n"
        "\t\t</p>\n"
        "\t</body>\n"
        "</html>"
    )


def test_backref_requires_matching_tag_names():
    # `<x>..</y>` is not a pair, so it is left untouched (no `{$1}` match).
    assert run("<x>oops</y>") == "<x>oops</y>"


def test_strip_whitespace_recovers_source():
    # The pipeline only *adds* tabs and newlines around a well-formed tree with
    # no edge-whitespace in its text, so removing them returns the input exactly.
    for src in [
        "<p>hi</p>",
        "<a><b>x</b><c>y</c></a>",
        "<ul><li>a</li><li>b</li></ul>",
        "<doc><sec><h>title</h><p>body</p></sec></doc>",
    ]:
        out = run(src)
        assert out.replace("\n", "").replace("\t", "") == src


def test_arbitrary_depth_indents_completely():
    # The `<=` fixed point peels until no tag pair is left, so there is no depth
    # limit — a 16-deep document (past the old 12-pass budget) indents fully.
    names = [chr(ord("a") + i) for i in range(16)]
    src = "".join(f"<{n}>" for n in names) + "x" + "".join(f"</{n}>" for n in reversed(names))
    out = run(src)
    assert out.splitlines()[16] == "\t" * 16 + "x"  # the innermost text, 16 tabs deep
    assert out.replace("\n", "").replace("\t", "") == src  # lossless


def test_inline_mixed_content_splits_at_child_boundaries():
    # Text mixed with an inline child: the child is pulled onto its own indented
    # lines; surrounding text rides with the nearest boundary.
    out = run("<p>text <b>bold</b> more</p>")
    assert "<b>\n\t\tbold\n\t</b>" in out
    assert out.replace("\n", "").replace("\t", "") == "<p>text <b>bold</b> more</p>"


# ── Runbook ───────────────────────────────────────────────────────────────────
# Run this file directly to indent a real HTML file and write the result to
# `tests/demos/output` for manual inspection.
if __name__ == "__main__":
    OUTPUT = Path(__file__).resolve().parent / "output"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    html = (RESOURCES / "sample.html").read_text("utf-8").strip()
    out = run(html)
    (OUTPUT / "indented_sample.html").write_text(out, "utf-8")
    print(f"Wrote indented_sample.html to {OUTPUT}")
