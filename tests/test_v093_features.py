"""Tests for the v0.9.3 engine features: count unions, the homogeneity
flip, and the transformer rework (eager-commit branches, `|` filters,
branch-per-moustache flow, `@<`/`@>` anchors)."""

from himark import parser
from himark.engine import execute, find_matches


def m(pattern, text):
    return [x.text for x in find_matches(parser.parse(pattern)[0], text)]


def ex(pattern, text):
    return execute(parser.parse(pattern), text)


# ── Repetition: unions, greedy backoff ────────────────────────────────────────


def test_count_union():
    # [a,b,c] repeats exactly a, b, or c times.
    assert m("{a}[1,3]", "a aa aaa aaaa") == ["a", "a", "a", "aaa", "aaa", "a"]


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
    assert m("{{a,b,c}::a..b}", "a b c") == ["a", "b"]
    assert m("{{{a,b,c}}::a..b}", "a b c") == ["a", "b", "c"]


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
    assert ex('{!x}[1..] => "{{ . | trim }}"', " hi ") == ["hi"]


def test_filter_indent_prefixes_each_line():
    # `indent` is a line filter: a tab on every line, so it accumulates under an
    # inside-out wrap (see scripts/html_format.hmk).
    assert ex(r'{!x}[1..] => "{{ . | indent }}"', "a\nb\nc") == ["\ta\n\tb\n\tc"]


def test_unknown_filter_raises():
    import pytest

    from himark.models.exceptions import CompileError

    with pytest.raises(CompileError):
        ex('{a} => "{{ . | nope }}"', "a")


def test_string_filter_still_works_on_value_accessor():
    # A value accessor degrades gracefully to its text under a string filter.
    assert ex('{@d::0..65535} => "{{ 0$0 | trim }}"', "256") == ["256"]


def test_decoration_lands_but_does_not_flow():
    # A template's literal text lands in the document but never flows downstream:
    # only the moustache value does, so the next query sees "x", not "<div>x</div>",
    # and {div} finds nothing — the render is left as-is.
    assert ex('{x} => "<div>{{.}}</div>" => {div} => "HIT"', "x") == ["<div>x</div>"]


def test_each_moustache_branches_independently():
    # Two moustaches are two branches: each flows and is transformed on its own,
    # with the decoration between them (the `<sep>`) kept in place.
    assert ex('{x} => "{{.}}<sep>{{.}}" => {!q}[1..] => "[{{.}}]"', "x") == [
        "[x]<sep>[x]"
    ]


def test_zero_moustache_template_flows_whole_render():
    # A template with no moustaches has nothing to single out, so its whole render
    # flows on as one branch — here {a} matches inside "ab" and is rewritten.
    assert ex('{x} => "ab" => {a} => "Z"', "x") == ["Zb"]


def test_line_anchor_start():
    # @< is a line start: position 0 or just after a newline.
    assert m("{@<}{x}", "x yx x") == ["x"]
    assert m("{@<}{x}", "ax\nx y") == ["x"]  # the line-start x, not the mid-line one


def test_line_anchor_end():
    # @> is a line end: end of text or just before a newline.
    assert m("{x}{@>}", "ax\nbx") == ["x", "x"]  # before the \n, and at the end
    assert m("{x}{@>}", "xa\nxb") == []  # neither x is at a line end


def test_document_anchor_start():
    # @<< is the document start: position 0 only, never mid-document.
    assert m("{@<<}{x}", "x\nx x") == ["x"]
    assert m("{@<<}{x}", "ax\nx") == []  # no x at position 0


def test_document_anchor_end():
    # @>> is the document end: the very end of the text, not a line break.
    assert m("{x}{@>>}", "x\nx") == ["x"]  # only the final x
