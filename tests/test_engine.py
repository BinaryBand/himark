"""Tests for the HMK execution engine.

Parametrized tests lock in known correct behaviour.
Hypothesis tests verify structural properties across arbitrary inputs.
"""

import pytest
from hypothesis import given, strategies as st

from himark import parser
from himark.engine import execute


def run(hmk: str, target: str) -> list[str]:
    return execute(parser.parse(hmk), target)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

printable = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126))
lowercase = st.text(alphabet="abcdefghijklmnopqrstuvwxyz")
digits    = st.text(alphabet="0123456789")
word      = st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


# ---------------------------------------------------------------------------
# Literals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    ("[a]",   "cat",   ["a"]),
    ("[a]",   "b",     []),
    ("[abc]", "xabcy", ["abc"]),
    ("[abc]", "abcabc", ["abc", "abc"]),
    ("[abc]", "ab",    []),
])
def test_literal(hmk, target, expected):
    assert run(hmk, target) == expected


@given(printable, printable)
def test_literal_matches_are_substrings(prefix, suffix):
    target = prefix + "abc" + suffix
    matches = run("[abc]", target)
    assert "abc" in matches


@given(printable)
def test_literal_match_content_is_correct(target):
    for m in run("[abc]", target):
        assert m == "abc"


# ---------------------------------------------------------------------------
# Alternation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    ("[a||c]",       "abcde",          ["a", "c"]),
    ("[hello||world]", "say hello world", ["hello", "world"]),
    ("[a||b||c]",    "abc",            ["a", "b", "c"]),
])
def test_alternation(hmk, target, expected):
    assert run(hmk, target) == expected


@given(printable)
def test_alternation_matches_only_valid_arms(target):
    for m in run("[a||b||c]", target):
        assert m in ("a", "b", "c")


# ---------------------------------------------------------------------------
# Ranges
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    ("[a..z](1..)", "hello world",   ["hello", "world"]),
    ("[A..Z](1..)", "Hello World",   ["H", "W"]),
    ("[0..9](1..)", "abc123def456",  ["123", "456"]),
    ("[a..Z](1..)", "Hello World",   ["Hello", "World"]),
])
def test_range(hmk, target, expected):
    assert run(hmk, target) == expected


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1))
def test_lowercase_range_matches_only_lowercase(s):
    for m in run("[a..z](1..)", s):
        assert all("a" <= c <= "z" for c in m)


@given(st.text(alphabet="0123456789", min_size=1))
def test_digit_range_matches_only_digits(s):
    for m in run("[0..9](1..)", s):
        assert all(c.isdigit() for c in m)


@given(st.characters(min_codepoint=ord("a"), max_codepoint=ord("z")))
def test_single_lowercase_char_always_matches_range(ch):
    assert run("[a..z]", ch) == [ch]


@given(st.characters(min_codepoint=ord("0"), max_codepoint=ord("9")))
def test_single_digit_always_matches_digit_range(ch):
    assert run("[0..9]", ch) == [ch]


# ---------------------------------------------------------------------------
# Shortcuts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    ("[0..]",  "abc123",     ["123"]),
    ("[a..]",  "hello world", ["hello", "world"]),  # word_chars matches both
    ("[ ..]",  "a  b",       ["  "]),
])
def test_shortcut(hmk, target, expected):
    assert run(hmk, target) == expected


@given(st.text(min_size=1))
def test_any_char_matches_single_character(s):
    matches = run("[..]", s)
    assert all(len(m) == 1 for m in matches)
    assert len(matches) == len(s)


@given(st.text(alphabet="0123456789", min_size=1))
def test_digit_shortcut_consumes_entire_run(s):
    matches = run("[0..]", s)
    assert matches == [s]


@given(st.text(alphabet=" \t", min_size=1))
def test_whitespace_shortcut_consumes_entire_run(s):
    matches = run("[ ..]", s)
    assert matches == [s]


# ---------------------------------------------------------------------------
# Repetition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    ("[a](2)",    "aaa",    ["aa"]),
    ("[a](1..)",  "aaabbb", ["aaa"]),
    ("[a](0..)",  "bbb",    []),
    ("[a](1..3)", "aaaa",   ["aaa", "a"]),
    ("[a](..3)",  "aaaa",   ["aaa", "a"]),
])
def test_repetition(hmk, target, expected):
    assert run(hmk, target) == expected


@given(st.integers(min_value=1, max_value=8), st.integers(min_value=1, max_value=8))
def test_exact_repetition_match_length(n, extra):
    target = "a" * (n + extra)
    matches = run(f"[a]({n})", target)
    assert all(len(m) == n for m in matches)
    assert len(matches) == (n + extra) // n


@given(st.integers(min_value=1, max_value=5), st.integers(min_value=1, max_value=5))
def test_range_repetition_respects_bounds(lo, hi_offset):
    hi = lo + hi_offset
    target = "a" * (hi * 3)
    matches = run(f"[a]({lo}..{hi})", target)
    assert all(lo <= len(m) <= hi for m in matches)


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    ("[hello][ ..][world]", "hello world",   ["hello world"]),
    ("[hello][ ..][world]", "hello  world",  ["hello  world"]),
    ("[a..z](1..)[.][a..z](1..)", "word.word ok", ["word.word"]),
])
def test_sequence(hmk, target, expected):
    assert run(hmk, target) == expected


# ---------------------------------------------------------------------------
# Transformers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    ("[a..z](1..) => <b>{{ . }}</b>",       "hello world",  ["<b>hello</b>", "<b>world</b>"]),
    ("[0..9](1..) => num:{{ . }}",           "abc123",       ["num:123"]),
    ("[hello||world] => {{ . }}!",          "say hello",    ["hello!"]),
])
def test_transformer(hmk, target, expected):
    assert run(hmk, target) == expected


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1))
def test_full_match_template_is_identity(s):
    plain       = run("[a..z](1..)", s)
    transformed = run("[a..z](1..) => {{ . }}", s)
    assert plain == transformed


# ---------------------------------------------------------------------------
# Separators
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    ("<<,>>",   "a,b,c",             ["a", "b", "c"]),
    ("<<,>>",   ",a,",               ["", "a", ""]),
    ("<</>>",   "red/green/blue",     ["red", "green", "blue"]),
    ("<<foo>>", "redfoogreenfooblue", ["red", "green", "blue"]),
])
def test_separator(hmk, target, expected):
    assert run(hmk, target) == expected


@given(st.lists(st.text(min_size=1, alphabet="abcde"), min_size=1))
def test_separator_parts_reassemble(parts):
    target = ",".join(parts)
    assert run("<<,>>", target) == parts


# ---------------------------------------------------------------------------
# Negation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    ("[[a]]",     "bcde",            ["bcde"]),
    ("[[a]]",     "bcade",           ["bc", "de"]),
    ("[[a]]",     "a",               []),
    ("[[a..z]]",  "ABCdeF",          ["ABC", "F"]),
    ("[[hello]]", "say hello world", ["say ", " world"]),
    ("[[a||b]]",  "cdab",            ["cd"]),
])
def test_negation(hmk, target, expected):
    assert run(hmk, target) == expected


@given(st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=1))
def test_negation_single_char_never_contains_excluded(s):
    for m in run("[[a]]", s):
        assert "a" not in m


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1))
def test_negation_lowercase_range_never_contains_lowercase(s):
    for m in run("[[a..z]]", s):
        assert all(not c.islower() for c in m)


# ---------------------------------------------------------------------------
# Captures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    ("[0..9](1..)[px||em||rem] => {{ 1 }}",           "12px solid",  ["12"]),
    ("[0..9](1..)[px||em||rem] => {{ 2 }}",           "12px solid",  ["px"]),
    ("[a..z](1..)[.][a..z](1..) => {{ 1 }}.{{ 3 }}", "word.word ok", ["word.word"]),
    ("[a..z](1..) => {{ 1 }}",                        "hello world", ["hello", "world"]),
])
def test_captures(hmk, target, expected):
    assert run(hmk, target) == expected


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1))
def test_capture_group1_identity(s):
    assert run("[a..z](1..)", s) == run("[a..z](1..) => {{ 1 }}", s)


# ---------------------------------------------------------------------------
# Integer ranges
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    ("[5..99]",    "12px",         ["12"]),
    ("[5..99]",    "100",          ["10"]),     # 100 > 99; "10" is in range
    ("[5..99]",    "4",            []),          # below range
    ("[0..99]",    "0",            ["0"]),
    ("[0..99]",    "00",           ["0", "0"]), # leading-zero string isn't canonical
    ("[10..999]",  "5abc42xyz100", ["42", "100"]),
    ("[0..9](1..)", "abc123",      ["123"]),     # existing behaviour unchanged
])
def test_integer_range(hmk, target, expected):
    assert run(hmk, target) == expected


@given(st.integers(min_value=0, max_value=99))
def test_integer_range_matches_value_in_bounds(n):
    assert run("[0..99]", str(n)) == [str(n)]


@given(st.integers(min_value=100, max_value=9999))
def test_integer_range_rejects_value_out_of_bounds(n):
    # A number > 99 should not match [0..99] as a whole, though a prefix might
    matches = run("[0..99]", str(n))
    for m in matches:
        assert 0 <= int(m) <= 99


# ---------------------------------------------------------------------------
# Chained transformations
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    # Two-step: filter then template (same as single => but exercises the chain path)
    (
        "[a..z](1..) => {{ . }}!",
        "hello world",
        ["hello!", "world!"],
    ),
    # Two-step: intermediate pattern narrows, template renders
    (
        "[hello||world] => {{ . }}?",
        "say hello",
        ["hello?"],
    ),
    # Three-step: separator splits, pattern filters, template wraps
    (
        "<<,>> => [a..z](1..) => <b>{{ . }}</b>",
        "red,42,blue",
        ["<b>red</b>", "<b>blue</b>"],
    ),
    # Three-step: separator, match heading pattern, extract group
    (
        "<<\n>> => [#][ ..][a..Z](1..) => {{ 3 }}",
        "# Hello\nnot a heading\n# World",
        ["Hello", "World"],
    ),
])
def test_chain(hmk, target, expected):
    assert run(hmk, target) == expected


# ---------------------------------------------------------------------------
# Case-insensitive (i)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    ("[hello](i)",        "say Hello",         ["Hello"]),
    ("[hello](i)",        "HELLO world",        ["HELLO"]),
    ("[hello](i)",        "hello HeLLo HELLO",  ["hello", "HeLLo", "HELLO"]),
    ("[a..z](1.., i)",    "Hello World",        ["Hello", "World"]),
    ("[A..Z](1.., i)",    "Hello World",        ["Hello", "World"]),
    ("[a||b](i)",         "aAbB",               ["a", "A", "b", "B"]),
    # Without (i), case-sensitive as before
    ("[hello]",           "Hello",              []),
    ("[a..z](1..)",       "Hello",              ["ello"]),
])
def test_case_insensitive(hmk, target, expected):
    assert run(hmk, target) == expected


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1))
def test_case_insensitive_literal_matches_upper(s):
    upper = s.upper()
    assert run(f"[{s}](i)", upper) == [upper]


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hmk, target, expected", [
    # Line-start anchor
    ("^[a..z](1..)",          "hello\nworld",   ["hello", "world"]),
    ("^[a..z](1..)",          "hello world",    ["hello"]),  # only first word is at line start
    # Line-end anchor
    ("[a..z](1..)$",          "hello\nworld",   ["hello", "world"]),
    ("[a..z](1..)$",          "hello world",    ["world"]),  # only last word is at line end
    # Both: full-line word match
    ("^[a..z](1..)$",         "hello\nworld",   ["hello", "world"]),
    ("^[a..z](1..)$",         "hi there\nbye",  ["bye"]),    # "hi there" has a space, no match
    # Document anchors
    ("^^[a..z](1..)",         "hello world",    ["hello"]),  # only pos=0 qualifies
    ("[a..z](1..)$$",         "hello world",    ["world"]),  # only pos=len(text) qualifies
    ("^^[a..z](1..)$$",       "hello",          ["hello"]),  # whole doc is one word
    ("^^[a..z](1..)$$",       "hello world",    []),         # space breaks it
    # Literal ^ and $ inside brackets are unaffected
    ("[^]",                   "a^b",            ["^"]),
    ("[$]",                   "a$b",            ["$"]),
])
def test_anchors(hmk, target, expected):
    assert run(hmk, target) == expected


@given(st.lists(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1), min_size=1))
def test_chain_separator_then_identity(parts):
    target = ",".join(parts)
    # Split by comma, then match each part, then render with {{ . }} — should give back the parts
    result = run("<<,>> => [a..z](1..) => {{ . }}", target)
    assert result == parts
