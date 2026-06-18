"""Tests for the v0.9.3 engine features: count unions/stride/laziness, the
homogeneity flip, fuzzy `~k`, and the transformer rework (eager-commit branches,
`|` filters, `{{> }}` payload, `@^`/`@$` anchors)."""

from marky import parser
from marky.engine import execute, find_matches


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

    from marky.models.exceptions import CompileError

    with pytest.raises(CompileError):
        m("{a}[2....2]", "aa")


def test_greedy_backs_off():
    # Greedy repetition backs off so the tail can match ({#0} = the run's length).
    assert m("{a}[1..]x{#0}", "aaax2") == ["aax2"]


def test_lazy_ends_at_nearest():
    # `[..<y]` is lazy: the run ends at the nearest following match.
    assert m("{!|}[..<99]{|}", "ab|cd|ef") == ["ab|", "cd|"]


def test_lazy_extends_until_match():
    # Lazy still extends as far as needed for the tail to match.
    assert m("{a}[1..<5]{b}", "aaab") == ["aaab"]


# ── Homogeneity: bare is same-string, {{U}} is heterogeneous ──────────────────


def test_bare_class_is_homogeneous():
    assert m("{a,A}[2]", "aa aA Aa AA") == ["aa", "AA"]


def test_nested_class_is_heterogeneous():
    assert m("{{a,A}}[2]", "aa aA Aa AA") == ["aa", "aA", "Aa", "AA"]


def test_heterogeneous_no_cross_group():
    # A heterogeneous run stays within one group: with `-` and `*` as separate
    # single-member groups, a run never crosses from one to the other.
    hr = "{{{-},{*}}}[3..]"
    assert m(hr, "---") == ["---"]
    assert m(hr, "-*-") == []


def test_nested_range_is_heterogeneous():
    assert m("{{a..z}}[3]", "abc") == ["abc"]


def test_complement_run_is_heterogeneous():
    # A bare complement run stays a heterogeneous run of non-X characters.
    assert m(r"{!\ }[1..]", "hi there") == ["hi", "there"]


# ── Fuzzy `~k` ────────────────────────────────────────────────────────────────


def test_fuzzy_within_distance():
    assert m("{cat}~1", "cat cot cap bat ct caat") == [
        "cat",
        "cot",
        "cap",
        "bat",
        "ct",
        "caat",
    ]


def test_fuzzy_rejects_far():
    assert m("{cat}~1", "dog xyz") == []


def test_fuzzy_token_union():
    assert m("{cat,dog}~1", "cat dig") == ["cat", "dig"]


def test_fuzzy_operand_must_be_tokens():
    import pytest

    from marky.models.exceptions import CompileError

    with pytest.raises(CompileError):
        m("{a..z}~1", "abc")


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

    from marky.models.exceptions import CompileError

    with pytest.raises(CompileError):
        ex('{a} => "{{ . | nope }}"', "a")


def test_payload_marker_splits_doc_and_pipe():
    # {{> }} sends the full render to the document but only the payload downstream.
    out = ex('{#}[1..]{!{\\n}}[1..] => "<h{{#0}}>{{> $1 }}</h{{#0}}>" => "[{{.}}]"', "#Hi")
    assert out == ["<h1>[Hi]</h1>"]


def test_two_payload_markers_raise():
    import pytest

    from marky.models.exceptions import CompileError

    with pytest.raises(CompileError):
        ex('{a} => "{{> . }}{{> . }}"', "a")


def test_anchor_start():
    assert m("{@^}{x}", "x yx x") == ["x"]


def test_anchor_end():
    assert m("{cat}{@$}", "a cat cat") == ["cat"]
