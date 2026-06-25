"""Guards against drift between docs/HMK.md and the implementation."""

import re
from pathlib import Path

from himark import parser
from himark.engine import execute, find_matches
from himark.parser.macros import MACROS

DOC = (Path(__file__).parent.parent / "docs" / "HMK.md").read_text("utf-8")


def matches(pattern, text):
    trees = parser.parse(pattern)
    return [m.text for m in find_matches(trees[0], text)]


def _doc_section(title):
    """The body of a `## title` section, up to the next `## ` heading or `---`."""
    body = DOC.split(f"\n## {title}\n", 1)[1]
    return re.split(r"\n## |\n---", body, maxsplit=1)[0]


def test_doc_macro_table_matches_macros_toml():
    # Scope to the Macros section's table — `@ed` also appears as an operand in
    # the Carriers/operators table, but it is a library alphabet, not a text macro.
    doc_names = set(re.findall(r"^\| `@(\w+)`", _doc_section("Macros"), re.MULTILINE))
    assert doc_names == set(MACROS)


def test_doc_congruence_pair_repetition():
    # Spec headline: a bare class repeats homogeneously ({a,A}[2] = aa/AA); the
    # heterogeneous (every-casing) form is the nested {{a,A}}[2].
    assert matches("{a,A}[2]", "aa aA Aa AA ab") == ["aa", "AA"]
    assert matches("{{a,A}}[2]", "aa aA Aa AA ab") == ["aa", "aA", "Aa", "AA"]


def test_doc_captures_example():
    # The Captures section: {#}[1..]{Sphinx}{of{black}{quartz}} numbers groups
    # 0,1,2 left-to-right, with {black}/{quartz} as sub-captures of group 2.
    ms = find_matches(
        parser.parse("{#}[1..]{Sphinx}{of{black}{quartz}}")[0],
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


def test_doc_b256_value_filter_example():
    # The Filters section: a group accessor carries its alphabet, so b256 reads
    # '256' as the value 256 and emits it as two big-endian bytes.
    assert execute(parser.parse('{@d:0..65535} => "{{ 0$0 | b256(2) }}"'), "256") == [
        "\x01\x00"
    ]


def test_doc_primitives_vs_objects():
    # Headline model: a comma-list is ordered primitives; nesting makes an object
    # whose faces are interchangeable. So `{a,A}[2]` stays in one point (aa/AA),
    # `{{a,A}}[2]` frees the faces (all four), and a run over an alphabet of
    # objects repeats one object without flattening (`{{a,A},{c,C}}[2]` = 8).
    assert matches("{a,A}[2]", "aa aA Aa AA") == ["aa", "AA"]
    assert matches("{{a,A}}[2]", "aa aA Aa AA") == ["aa", "aA", "Aa", "AA"]
    assert len(matches("{{a,A},{c,C}}[2]", "aa aA Aa AA cc cC Cc CC")) == 8
    # `{a,b}` is `{a..b}`: ordered, so a bound is value-ordered, not folded.
    assert matches("{{a,b,c}:a..b}", "a b c") == ["a", "b"]


def test_doc_band_grammar_examples():
    # The Bands section: a band is `{payload:band}` — the payload alphabet
    # restricted by a `..` range, a single value, or a `,`-union of either.
    assert matches("{@d:0..255}", "0 200 255 256") == ["0", "200", "255", "25", "6"]
    assert matches("{@d:5}", "4 5 6") == ["5"]  # single value over a typed head
    assert matches("{a,b,g..z:m..p}", "a g m n p z") == ["m", "n", "p"]
    assert matches("{0..9:9..12,1..5}", "0 1 5 6 9 12 13") == ["1", "5", "9", "12", "1", "3"]
    assert matches("{{a..z}:b}", "a b c") == ["b"]  # braced-universe head
    # Drop the prefix for an ambient band; an open end keeps one side unbounded.
    assert matches("{@d:0..}", "7") == ["7"]
    assert matches("{@l:aa..zz}", "aa a9 zz") == ["aa", "zz"]


def test_doc_band_literal_colons():
    # "When `:` separates": the colon is a band separator only for a typed head
    # or a band-side `..`. A plain-literal head with a value-only right side keeps
    # every colon literal — no escaping needed.
    assert matches("{12:30}", "12:30 12:31") == ["12:30"]
    assert matches("{std::vector}", "std::vector x") == ["std::vector"]
    assert matches("{https://x.com}", "go to https://x.com now") == ["https://x.com"]
    # A class whose member is `:` is a union, not a band (the colon is a point).
    assert sorted(matches("{ ,:,-}", "a:b-c d")) == [" ", "-", ":"]


def test_doc_word_anchors():
    # The Anchors section: `@<`/`@>` are a `@w` <-> non-`@w` boundary, zero-width.
    assert matches("{@<}{@w:a..zzzzz}{@>}", "hi there") == ["hi", "there"]
    assert len(matches("{@<}{a,b,c}", "a b c")) == 3  # three word starts
    assert matches("{foo}{@>}", "foo foobar") == ["foo"]  # @> only at a boundary


def test_doc_filters():
    # The Filters section: sha512/pad/uint plus `le`/`be` endianness on b256/uint.
    assert execute(parser.parse('{@d:0..} => "{{ 0$0 | pad(4) }}"'), "7") == ["0007"]
    assert execute(
        parser.parse('{@d:0..65535} => "{{ 0$0 | b256(2) | uint }}"'), "258"
    ) == ["258"]
    # `v | b256(n) | uint` round-trips when endianness matches.
    assert execute(
        parser.parse('{@d:0..65535} => "{{ 0$0 | b256(2,le) | uint(le) }}"'), "258"
    ) == ["258"]
    # b256(le) reverses the byte order of the big-endian form.
    assert execute(
        parser.parse('{@d:0..65535} => "{{ 0$0 | b256(2,le) | hex }}"'), "258"
    ) == ["0201"]
    assert execute(
        parser.parse('{@d:0..65535} => "{{ 0$0 | b256(2) | hex }}"'), "258"
    ) == ["0102"]
    import hashlib

    sha512_hex = execute(
        parser.parse('{!@s}[1..] => "{{ 0$0 | sha512 | hex }}"'), "abc"
    )
    assert sha512_hex == [hashlib.sha512(b"abc").hexdigest()]
