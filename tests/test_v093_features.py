"""Tests for the v0.9.3 engine features: count unions/stride, the homogeneity
flip, and the transformer rework (eager-commit branches, `|` filters,
`{{> }}` payload, `@^`/`@$` anchors)."""

from himark import parser
from himark.engine import execute, find_matches


def m(pattern, text):
    return [x.text for x in find_matches(parser.parse(pattern)[0], text)]


def ex(pattern, text):
    return execute(parser.parse(pattern), text)


# ── Repetition: unions, stride, greedy backoff, laziness ──────────────────────


def test_count_union():
    # [a,b,c] repeats exactly a, b, or c times.
    assert m("{a}[1,3]", "a aa aaa aaaa") == ["a", "a", "a", "aaa", "aaa", "a"]


def test_count_stride():
    # [x..y..s] is a strided range of counts.
    assert m("{a}[2..6..2]", "a aa aaaa aaaaaa") == ["aa", "aaaa", "aaaaaa"]


def test_range_stride():
    # {a..z..2} is every second letter as one ordered alphabet.
    assert m("{a..z..2}", "abcdef") == ["a", "c", "e"]


def test_strided_count_needs_upper_bound():
    import pytest

    from himark.models.exceptions import CompileError

    with pytest.raises(CompileError):
        m("{a}[2....2]", "aa")


def test_greedy_backs_off():
    # Greedy repetition backs off so the tail can match ({#0} = the run's length).
    assert m("{a}[1..]x{#0}", "aaax2") == ["aax2"]


def test_multi_char_break_replaces_lazy_to_nearest():
    # There is no lazy operator; a multi-char break scans up to the nearest
    # delimiter the run cannot cross (the old `{!|}[..<99]{|}` lazy idiom).
    assert m("{!|}[1..]{|}", "ab|cd|ef") == ["ab|", "cd|"]


# ── Points: primitives vs objects (comma lists vs nesting) ────────────────────


def test_bare_class_is_primitives():
    # Bare `{a,A}` is two primitive points: a run stays in one, so 'aa'/'AA'.
    assert m("{a,A}[2]", "aa aA Aa AA") == ["aa", "AA"]


def test_nested_class_is_one_object():
    # `{{a,A}}` is one object (a fold): a run takes any face each position.
    assert m("{{a,A}}[2]", "aa aA Aa AA") == ["aa", "aA", "Aa", "AA"]


def test_object_run_does_not_flatten():
    # `{{a,A},{c,C}}[2]` repeats ONE object (&² or %²) with faces free — eight
    # results, never a cross like 'ac'.
    assert m("{{a,A},{c,C}}[2]", "aa aA Aa AA cc cC Cc CC ac") == [
        "aa",
        "aA",
        "Aa",
        "AA",
        "cc",
        "cC",
        "Cc",
        "CC",
    ]


def test_comma_list_is_ordered_like_range():
    # `{a,b,c}` is the ordered alphabet `{a..c}`, so a bound rejects out-of-range
    # 'c' (value 2 > ceiling 'b'); the fold would be `{{a,b,c}}`.
    assert m("{a:{a,b,c}:b}", "a b c") == ["a", "b"]
    assert m("{a:{{a,b,c}}:b}", "a b c") == ["a", "b", "c"]


def test_no_cross_group():
    # A run stays within one group: `{{-},{*}}` is an ordered alphabet of two
    # single-member objects, so a run never crosses from one to the other.
    # (Folding them into one object would be `{{{-},{*}}}`, which *does* mix.)
    hr = "{{-},{*}}[3..]"
    assert m(hr, "---") == ["---"]
    assert m(hr, "-*-") == []


def test_nested_range_is_heterogeneous():
    assert m("{{a..z}}[3]", "abc") == ["abc"]


def test_complement_run_is_heterogeneous():
    # A bare complement run stays a heterogeneous run of non-X characters.
    assert m(r"{!\ }[1..]", "hi there") == ["hi", "there"]


# ── Transformers: eager-commit, filters, payload, anchors ─────────────────────


def test_eager_commit_keeps_render():
    # A query that matches nothing after a template keeps the committed render.
    assert ex('{cat} => "<b>{{.}}</b>" => {zzz}', "cat") == ["<b>cat</b>"]


def test_guard_before_template_filters():
    # A non-matching query before any template drops the branch (filtering).
    assert ex('{cat}{dog} => {zzz} => "X"', "catdog") == []


def test_filter_pipe():
    assert ex('{!\\ }[1..] => "{{ . | upper }}"', "hi there") == ["HI", "THERE"]


def test_filter_len():
    assert ex('{cat}{dog} => "{{ 0$0 | len }}"', "catdog") == ["3"]


def test_unknown_filter_raises():
    import pytest

    from himark.models.exceptions import CompileError

    with pytest.raises(CompileError):
        ex('{a} => "{{ . | nope }}"', "a")


def test_b256_value_filter_reads_capture_as_number():
    # A group accessor carries the alphabet it matched under, so b256 reads '256'
    # as the base-10 value 256 and re-encodes it as two big-endian bytes.
    assert ex('{0:@d:65535} => "{{ 0$0 | b256(2) }}"', "256") == ["\x01\x00"]


def test_b256_on_raw_string_stage_ref_raises():
    import pytest

    from himark.models.exceptions import CompileError

    # `0$` is the whole stage text — a raw string with no alphabet, so a value
    # filter cannot read it as a number.
    with pytest.raises(CompileError):
        ex('{0:@d:65535} => "{{ 0$ | b256(2) }}"', "256")


def test_b256_overflow_raises():
    import pytest

    from himark.models.exceptions import CompileError

    with pytest.raises(CompileError):
        ex('{0:@d:65535} => "{{ 0$0 | b256(1) }}"', "256")


def test_string_filter_still_works_on_value_accessor():
    # A value accessor degrades gracefully to its text under a string filter.
    assert ex('{0:@d:65535} => "{{ 0$0 | len }}"', "256") == ["3"]


def test_sha256_filter_matches_standard_vector():
    import hashlib

    out = ex('{!\\ }[1..] => "{{ . | sha256 | hex }}"', "abc")
    assert out == [hashlib.sha256(b"abc").hexdigest()]


def test_byte_filters_chain_double_sha_over_b256():
    import hashlib

    out = ex('{0:@d:65535} => "{{ 0$0 | b256(2) | sha256 | sha256 | hex }}"', "256")
    expected = hashlib.sha256(
        hashlib.sha256((256).to_bytes(2, "big")).digest()
    ).hexdigest()
    assert out == [expected]


def test_b58_decodes_as_bitcoin_base58_value():
    # @b58 already works as a value alphabet: '21' is base-58 value 58, so b256(1)
    # emits the single byte 0x3a.
    assert ex('{1:@b58:zz} => "{{ 0$0 | b256(1) | hex }}"', "21") == ["3a"]


def test_base58_value_to_double_sha256_pipeline():
    # The aspirational target, end to end: match a base-58 value, decode it to
    # bytes, and run Bitcoin's double-SHA256 — checked against an independent
    # base-58 decode. This is the whole typed-value seam working on real shape.
    import hashlib

    btc = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    token = "abc"
    iv = 0
    for c in token:
        iv = iv * 58 + btc.index(c)
    expected = hashlib.sha256(
        hashlib.sha256(iv.to_bytes(8, "big")).digest()
    ).hexdigest()
    out = ex('{1:@b58:zzzzz} => "{{ 0$0 | b256(8) | sha256 | sha256 | hex }}"', token)
    assert out == [expected]


def test_payload_marker_splits_doc_and_pipe():
    # {{> }} sends the full render to the document but only the payload downstream.
    out = ex(
        '{#}[1..]{!{\\n}}[1..] => "<h{{#0}}>{{> $1 }}</h{{#0}}>" => "[{{.}}]"', "#Hi"
    )
    assert out == ["<h1>[Hi]</h1>"]


def test_two_payload_markers_raise():
    import pytest

    from himark.models.exceptions import CompileError

    with pytest.raises(CompileError):
        ex('{a} => "{{> . }}{{> . }}"', "a")


def test_line_anchor_start():
    # @^ is a line start: position 0 or just after a newline.
    assert m("{@^}{x}", "x yx x") == ["x"]
    assert m("{@^}{x}", "ax\nx y") == ["x"]  # the line-start x, not the mid-line one


def test_line_anchor_end():
    # @$ is a line end: end of text or just before a newline.
    assert m("{x}{@$}", "ax\nbx") == ["x", "x"]  # before the \n, and at the end
    assert m("{x}{@$}", "xa\nxb") == []  # neither x is at a line end


def test_scope_anchor_start():
    # @^^ is the scope start: position 0 only, never mid-document.
    assert m("{@^^}{x}", "x\nx x") == ["x"]
    assert m("{@^^}{x}", "ax\nx") == []  # no x at position 0


def test_scope_anchor_end():
    # @$$ is the scope end: the very end of the text, not a line break.
    assert m("{x}{@$$}", "x\nx") == ["x"]  # only the final x
