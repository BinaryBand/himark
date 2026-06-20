"""End-to-end tests for the HTML formatter (`himark/scripts/html_format.hmk`).

The script pretty-prints and normalizes HTML one tab per nesting level using a
stackless, inside-out fixed point (`<=`): leaf constructs (comments, DOCTYPE,
void/self-closing tags) are marked as `⟦ ⟧` sentinel blocks, then the WRAP rule
peels each *innermost* tag pair until none remain, re-tabbing the body each pass
so depth accumulates. Inter-tag whitespace is normalized away and re-derived, so
the formatter is idempotent. These tests pin the structure, the real-markup
features (attributes, voids, comments, DOCTYPE), and idempotence.
"""

from pathlib import Path

from himark.tools import precompiled

SCRIPT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "html_format.hmk"
RESOURCES = Path(__file__).resolve().parent / "resources"
_PIPELINE = precompiled.compile_pipeline(precompiled.load_script(SCRIPT))


def run(text: str) -> str:
    return precompiled.apply(_PIPELINE, text)


# ── Structure ─────────────────────────────────────────────────────────────────


def test_single_leaf():
    assert run("<p>hi</p>") == "<p>\n\thi\n</p>"


def test_nested_pair_indents_one_level():
    assert run("<a><b>x</b></a>") == "<a>\n\t<b>\n\t\tx\n\t</b>\n</a>"


def test_siblings_land_on_their_own_lines():
    assert run("<a><b>x</b><c>y</c></a>") == (
        "<a>\n\t<b>\n\t\tx\n\t</b>\n\t<c>\n\t\ty\n\t</c>\n</a>"
    )


def test_depth_accumulates():
    out = run("<html><body><p>hi</p></body></html>")
    assert out == (
        "<html>\n\t<body>\n\t\t<p>\n\t\t\thi\n\t\t</p>\n\t</body>\n</html>"
    )


def test_arbitrary_depth_indents_completely():
    # The `<=` fixed point peels until no tag pair is left — no depth limit.
    names = [chr(ord("a") + i) for i in range(16)]
    src = "".join(f"<{n}>" for n in names) + "x" + "".join(f"</{n}>" for n in reversed(names))
    out = run(src)
    assert out.splitlines()[16] == "\t" * 16 + "x"


def test_backref_requires_matching_tag_names():
    # `<x>..</y>` is not a pair, so it is left untouched (no `{$1}` match).
    assert run("<x>oops</y>") == "<x>oops</y>"


# ── Real markup ───────────────────────────────────────────────────────────────


def test_attributes_are_preserved_and_not_matched_in_the_close():
    assert run('<a href="/x" class="y">hi</a>') == '<a href="/x" class="y">\n\thi\n</a>'


def test_void_elements_are_leaves_on_their_own_line():
    assert run('<head><meta charset="utf-8"><hr></head>') == (
        '<head>\n\t<meta charset="utf-8">\n\t<hr>\n</head>'
    )


def test_self_closing_tag_is_a_leaf():
    assert run('<div><img src="x"/></div>') == '<div>\n\t<img src="x"/>\n</div>'


def test_comment_is_preserved_as_a_leaf():
    assert run("<div><!-- note --><p>x</p></div>") == (
        "<div>\n\t<!-- note -->\n\t<p>\n\t\tx\n\t</p>\n</div>"
    )


def test_doctype_stays_on_the_top_line():
    assert run("<!DOCTYPE html><html><body>x</body></html>") == (
        "<!DOCTYPE html>\n<html>\n\t<body>\n\t\tx\n\t</body>\n</html>"
    )


# ── Normalization & idempotence ───────────────────────────────────────────────


def test_inter_tag_whitespace_is_normalized():
    # Pre-existing indentation/newlines between tags are collapsed and re-derived.
    assert run("<ul>\n  <li>a</li>\n  <li>b</li>\n</ul>") == (
        "<ul>\n\t<li>\n\t\ta\n\t</li>\n\t<li>\n\t\tb\n\t</li>\n</ul>"
    )


def test_is_idempotent():
    src = (RESOURCES / "sample.html").read_text("utf-8").strip()
    once = run(src)
    assert run(once) == once


def test_strip_whitespace_recovers_source():
    # The pipeline only adds tabs/newlines around a compact, well-formed tree, so
    # removing them returns the input (spaces inside attributes are kept).
    for src in [
        "<p>hi</p>",
        '<a href="/x">hi</a>',
        "<ul><li>a</li><li>b</li></ul>",
    ]:
        assert run(src).replace("\n", "").replace("\t", "") == src


# ── Runbook ───────────────────────────────────────────────────────────────────
# Run this file directly to format a real HTML file and write the result to
# `tests/demos/output` for manual inspection.
if __name__ == "__main__":
    OUTPUT = Path(__file__).resolve().parent / "output"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    html = (RESOURCES / "sample.html").read_text("utf-8").strip()
    (OUTPUT / "formatted_sample.html").write_text(run(html), "utf-8")
    print(f"Wrote formatted_sample.html to {OUTPUT}")
