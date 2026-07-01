"""Guards against drift between docs/HMK.md and the implementation."""

import re
from pathlib import Path

import pytest

from himark import parser
from himark.models.compiled import Program
from himark.engine import execute, find_matches
from himark.models.exceptions import CompileError
from himark.prelude import VARIABLES

DOC = (Path(__file__).parent.parent / "docs" / "HMK.md").read_text("utf-8")


def matches(pattern, text):
    trees = parser.parse(pattern)
    assert isinstance(trees[0], Program)
    return [m.text for m in find_matches(trees[0], text)]


def _doc_section(title):
    """The body of a `## title` section, up to the next `## ` heading or `---`."""
    body = DOC.split(f"\n## {title}\n", 1)[1]
    return re.split(r"\n## |\n---", body, maxsplit=1)[0]


def test_doc_variable_table_matches_prelude():
    # Scope to the Variables section's table — `@ed` also appears as an operand in
    # the Carriers/operators table, but it is a library alphabet, not a text variable.
    # The variable table is the doc face of the `std.hmk` prelude's `@name` lines.
    doc_names = set(
        re.findall(r"^\| `@(\w+)`", _doc_section("Variables"), re.MULTILINE)
    )
    assert doc_names == set(VARIABLES)


def test_doc_congruence_pair_repetition():
    # Spec headline: a bare class repeats homogeneously ({a,A}[2] = aa/AA); the
    # heterogeneous (every-casing) form is the nested {{a,A}}[2].
    assert matches("{a,A}[2]", "aa aA Aa AA ab") == ["aa", "AA"]
    assert matches("{{a,A}}[2]", "aa aA Aa AA ab") == ["aa", "aA", "Aa", "AA"]


def test_doc_captures_example():
    # The Captures section: {#}[1..]{Sphinx}{of{black}{quartz}} numbers groups
    # 0,1,2 left-to-right, with {black}/{quartz} as sub-captures of group 2.
    trees = parser.parse("{#}[1..]{Sphinx}{of{black}{quartz}}")
    assert isinstance(trees[0], Program)
    ms = find_matches(
        trees[0],
        "###Sphinxofblackquartz",
    )
    assert len(ms) == 1
    assert ms[0].groups == ["###", "Sphinx", "ofblackquartz"]
    assert ms[0].sub_groups[2] == ["black", "quartz"]


def test_doc_subtractive_universe_examples():
    # The Subtraction section writes the subtractive universe `!{X}` with the
    # bang *outside* the brace, standalone: `!{a}` is any char except 'a',
    # `!{|,\n}` any char except '|' or newline.
    assert matches("!{a}", "abc") == ["b", "c"]
    assert matches("!{|,\\n}", "a|b") == ["a", "b"]


def test_doc_primitives_vs_objects():
    # Headline model: a comma-list is ordered primitives; nesting makes an object
    # whose faces are interchangeable. So `{a,A}[2]` stays in one point (aa/AA),
    # `{{a,A}}[2]` frees the faces (all four), and a run over an alphabet of
    # objects repeats one object without flattening (`{{a,A},{c,C}}[2]` = 8).
    assert matches("{a,A}[2]", "aa aA Aa AA") == ["aa", "AA"]
    assert matches("{{a,A}}[2]", "aa aA Aa AA") == ["aa", "aA", "Aa", "AA"]
    assert len(matches("{{a,A},{c,C}}[2]", "aa aA Aa AA cc cC Cc CC")) == 8
    # `{a,b}` is `{a..b}`: ordered, so a bound is value-ordered, not folded.
    assert matches("{{a,b,c}::a..b}", "a b c") == ["a", "b"]


def test_doc_band_grammar_examples():
    # The Bands section: a band is `{payload:band}` — the payload alphabet
    # restricted by a `..` range, a single value, or a `,`-union of either.
    assert matches("{@d::0..255}", "0 200 255 256") == ["0", "200", "255", "25", "6"]
    assert matches("{@d::5}", "4 5 6") == ["5"]  # single value over a typed head
    assert matches("{a,b,g..z::m..p}", "a g m n p z") == ["m", "n", "p"]
    assert matches("{0..9::9..12,1..5}", "0 1 5 6 9 12 13") == [
        "1",
        "5",
        "9",
        "12",
        "1",
        "3",
    ]
    assert matches("{{a..z}::b}", "a b c") == ["b"]  # braced-universe head
    # Drop the prefix for an ambient band; an open end keeps one side unbounded.
    assert matches("{@d::0..}", "7") == ["7"]
    assert matches("{@l::aa..zz}", "aa a9 zz") == ["aa", "zz"]


def test_doc_band_literal_colons():
    # ANTLR branch: a brace is a band iff its body holds a top-level `::`. A single
    # `:` is always literal and needs no escape; a literal `::` is escaped `\::`.
    assert matches("{12:30}", "12:30 12:31") == ["12:30"]
    assert matches("{https://x.com}", "go to https://x.com now") == ["https://x.com"]
    assert matches(r"{std\::vector}", "std::vector x") == ["std::vector"]
    # A class whose member is `:` is a union, not a band (the colon is a point).
    assert sorted(matches("{ ,:,-}", "a:b-c d")) == [" ", "-", ":"]


def test_doc_band_double_colon_is_a_band():
    # The flip side: an unescaped top-level `::` makes a band, so a literal C++
    # qualified name must escape it. `{std::vector}` is now a band (alphabet `std`,
    # band `vector`), which is not a value alphabet — a compile error.
    with pytest.raises(CompileError):
        matches("{std::vector}", "std::vector x")


def test_doc_anchors():
    # The Anchors section: `@line_start`/`@line_end` are line edges, `@doc_start`/
    # `@doc_end` the document edges. All zero-width, named directly (no glyph sugar).
    assert matches("{@line_start}!{\n}[1..]{@line_end}", "hi\nthere") == ["hi", "there"]
    assert matches("{@doc_start}!{\n}[1..]", "hi\nthere") == ["hi"]  # first line only
    assert matches("!{\n}[1..]{@doc_end}", "hi\nthere") == ["there"]  # last line only


def test_doc_filters():
    # The Filters section: the closed native set is the string filters trim / indent.
    assert execute(parser.parse('!{x}[1..] => "{{ . | trim }}"'), "  hi  ") == ["hi"]
    assert execute(parser.parse('!{x}[1..] => "{{ . | indent }}"'), "a\nb") == [
        "\ta\n\tb"
    ]


def test_doc_filters_omit_deferred_crypto():
    # Hashes are deferred to a layer above the primitives — not core filters. (`hex`
    # is *not* here: `| hex` is a first-class alphabet cast now, see test_operators.)
    for gone in ("sha256", "sha512", "head", "tail"):
        with pytest.raises(CompileError):
            execute(parser.parse(f'{{@l}}[1..] => "{{{{ . | {gone} }}}}"'), "abc")


def test_doc_hex_code_point_escapes():
    # The Escaping section: `\xHH`/`\uHHHH`/`\UHHHHHHHH` are code-point escapes, so
    # the byte alphabets (@b256/@ascii/@uni) are spellable as text in the prelude.
    assert matches(r"{\x41}", "A B") == ["A"]
    assert matches(r"{\x41..\x43}", "ABCD") == ["A", "B", "C"]
    assert matches(r"{\U00000041}", "A B") == ["A"]
    # @b256 (declared `\x00..\xff`) still matches any byte, as before.
    assert matches("{@b256}", "AB") == ["A", "B"]
