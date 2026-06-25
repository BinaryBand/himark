"""End-to-end tests for the HTML formatter (`himark/scripts/html_format.hmk`).

The script pretty-prints and normalizes HTML one tab per nesting level using a
stackless, inside-out fixed point (`<=>`). Inline elements (<b>, <a>, <code>, …)
and their text are masked into `‹…›` sentinels so they stay on one line; only
block elements are broken out and indented. Leaf constructs (comments, DOCTYPE,
block-level void tags) are marked as `⟦…⟧`. Inter-tag whitespace is normalized
away and re-derived, so the formatter is idempotent. These tests pin the
structure, the real-markup features, the inline/block split, and idempotence.
"""

from pathlib import Path

from himark.tools import precompiled

SCRIPT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "html_format.hmk"
RESOURCES = Path(__file__).resolve().parent / "resources"
_PIPELINE = precompiled.compile_pipeline(precompiled.load_script(SCRIPT))


def run(text: str) -> str:
    return precompiled.apply(_PIPELINE, text)


# ── Block structure ───────────────────────────────────────────────────────────


def test_single_leaf():
    assert run("<p>hi</p>") == "<p>\n\thi\n</p>"


def test_nested_block_indents_one_level():
    assert run("<div><p>x</p></div>") == "<div>\n\t<p>\n\t\tx\n\t</p>\n</div>"


def test_block_siblings_each_on_own_lines():
    assert run("<ul><li>a</li><li>b</li></ul>") == (
        "<ul>\n\t<li>\n\t\ta\n\t</li>\n\t<li>\n\t\tb\n\t</li>\n</ul>"
    )


def test_depth_accumulates():
    assert run("<html><body><p>hi</p></body></html>") == (
        "<html>\n\t<body>\n\t\t<p>\n\t\t\thi\n\t\t</p>\n\t</body>\n</html>"
    )


def test_arbitrary_depth_indents_completely():
    # The `<=>` fixed point peels until no pair is left — no depth limit. Names are
    # non-inline (`t0`…`t15`) so every level is a block that breaks out.
    names = [f"t{i}" for i in range(16)]
    src = (
        "".join(f"<{n}>" for n in names)
        + "x"
        + "".join(f"</{n}>" for n in reversed(names))
    )
    assert run(src).splitlines()[16] == "\t" * 16 + "x"


def test_backref_requires_matching_tag_names():
    assert run("<x>oops</y>") == "<x>oops</y>"


# ── Real markup: attributes, voids, comments, DOCTYPE ─────────────────────────


def test_block_attributes_preserved_not_matched_in_close():
    assert (
        run('<section id="intro">hi</section>')
        == '<section id="intro">\n\thi\n</section>'
    )


def test_block_void_elements_on_their_own_line():
    assert run('<head><meta charset="utf-8"><hr></head>') == (
        '<head>\n\t<meta charset="utf-8">\n\t<hr>\n</head>'
    )


def test_self_closing_tag():
    assert run('<div><img src="x"/></div>') == '<div>\n\t<img src="x"/>\n</div>'


def test_comment_preserved_as_leaf():
    assert run("<div><!-- note --><p>x</p></div>") == (
        "<div>\n\t<!-- note -->\n\t<p>\n\t\tx\n\t</p>\n</div>"
    )


def test_doctype_on_top_line():
    assert run("<!DOCTYPE html><html><body>x</body></html>") == (
        "<!DOCTYPE html>\n<html>\n\t<body>\n\t\tx\n\t</body>\n</html>"
    )


# ── Inline vs block ───────────────────────────────────────────────────────────


def test_inline_element_stays_on_one_line():
    assert run('<a href="/x">hi</a>') == '<a href="/x">hi</a>'


def test_inline_inside_block_is_not_split():
    assert run("<p>Some <b>bold</b> here.</p>") == "<p>\n\tSome <b>bold</b> here.\n</p>"


def test_nested_inline_kept_together():
    assert run("<p>A <b>x <i>y</i></b> z.</p>") == "<p>\n\tA <b>x <i>y</i></b> z.\n</p>"


def test_inline_void_stays_inline():
    assert run("<p>one<br>two</p>") == "<p>\n\tone<br>two\n</p>"


def test_inline_element_wrapping_block_falls_through_to_block():
    # An inline tag (`<a>`) whose body is block content can't be masked inline, so
    # it is formatted as a block instead.
    assert run('<a href="/x"><div>x</div></a>') == (
        '<a href="/x">\n\t<div>\n\t\tx\n\t</div>\n</a>'
    )


# ── Normalization & idempotence ───────────────────────────────────────────────


def test_inter_tag_whitespace_is_normalized():
    assert run("<ul>\n  <li>a</li>\n</ul>") == "<ul>\n\t<li>\n\t\ta\n\t</li>\n</ul>"


def test_is_idempotent():
    src = (RESOURCES / "sample.html").read_text("utf-8").strip()
    once = run(src)
    assert run(once) == once


# ── Runbook ───────────────────────────────────────────────────────────────────
# Run this file directly to format a real HTML file and write the result to
# `tests/demos/output` for manual inspection.
if __name__ == "__main__":
    OUTPUT = Path(__file__).resolve().parent / "output"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    html = (RESOURCES / "sample.html").read_text("utf-8").strip()
    (OUTPUT / "formatted_sample.html").write_text(run(html), "utf-8")
    print(f"Wrote formatted_sample.html to {OUTPUT}")
