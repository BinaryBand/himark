"""Integration tests — north-star examples from docs/HMK.md."""

from marky import parser
from marky.engine import execute
from marky.engine._match import find_matches


def matches(pattern, text):
    trees = parser.parse(pattern)
    return [m.text for m in find_matches(trees[0], text)]


# ── IPv4 ──────────────────────────────────────────────────────────────────────

IPV4 = "{{dec}..255}{.}{{dec}..255}{.}{{dec}..255}{.}{{dec}..255}"


def test_ipv4_valid():
    assert matches(IPV4, "192.168.1.1") == ["192.168.1.1"]


def test_ipv4_loopback():
    assert matches(IPV4, "127.0.0.1") == ["127.0.0.1"]


def test_ipv4_max():
    assert matches(IPV4, "255.255.255.255") == ["255.255.255.255"]


def test_ipv4_first_octet_no_leading_256():
    # 256 > 255, so the engine won't match starting at the "2" but will find
    # "56.0.0.1" starting at position 1 — expected sub-match behavior without anchors
    result = matches(IPV4, "256.0.0.1")
    assert "256.0.0.1" not in result  # 256 exceeds the bound


def test_ipv4_in_text():
    result = matches(IPV4, "host 10.0.0.1 is up")
    assert "10.0.0.1" in result


# ── Literal matching ──────────────────────────────────────────────────────────


def test_literal_pattern():
    assert matches("{hello}", "say hello world") == ["hello"]


def test_multiple_brace_groups():
    trees = parser.parse("{a..z}{0..9}")
    ms = find_matches(trees[0], "a1 b2 c3")
    assert [m.text for m in ms] == ["a1", "b2", "c3"]


# ── Repetition equality ───────────────────────────────────────────────────────


def test_same_char_three_times():
    result = matches("{a..z}[3]", "aaa bbb abc")
    assert set(result) == {"aaa", "bbb"}


def test_same_digit_twice():
    result = matches("{0..9}[2]", "11 22 12 33")
    assert set(result) == {"11", "22", "33"}


# ── Template rendering ────────────────────────────────────────────────────────


def test_template_wrap():
    result = execute(parser.parse("{hello} => [{{0}}]"), "say hello")
    assert result == ["[hello]"]


def test_template_full_match():
    result = execute(parser.parse("{a..z} => <{{.}}>"), "abc")
    assert result == ["<a>", "<b>", "<c>"]


# ── Chained transformers (alternating pattern => template) ────────────────────


def test_chain_deferred_full_match():
    # P => T => P => T. {{.}} in the first template is deferred: it resolves to
    # the result of applying the remaining chain (`{dec} => #{{.}}`) to the match.
    result = execute(parser.parse("{dec}[1..] => <{{.}}> => {dec} => #{{.}}"), "42")
    assert result == ["<#4>", "<#2>"]


def test_chain_deferred_preserves_surrounding_text():
    # The deferred chain transforms in place — non-matched characters survive.
    result = execute(
        parser.parse("{x}<<>>{x} => [{{.}}] => {dec} => #{{.}}"), "x a4b2 x"
    )
    assert result == ["[x a#4b#2 x]"]


def test_chain_filter_then_template_still_works():
    # A run of patterns before a single trailing template (filter style) is
    # unchanged: non-matching lines are dropped.
    result = execute(
        parser.parse("<<\n>> => {#}[1..6]{ }{!\n} => <h{{#0}}>{{2}}</h{{#0}}>"),
        "## Hello\nplain line\n### World",
    )
    assert result == ["<h2>Hello</h2>", "<h3>World</h3>"]


# ── Separator ─────────────────────────────────────────────────────────────────


def test_separator_splits_lines():
    trees = parser.parse("<<\n>>")
    ms = find_matches(trees[0], "line1\nline2\nline3")
    assert [m.text for m in ms] == ["line1", "line2", "line3"]


def test_separator_empty_captures_all():
    trees = parser.parse("<<>>")
    ms = find_matches(trees[0], "hello world")
    assert len(ms) == 1
    assert ms[0].text == "hello world"


# ── Token set ────────────────────────────────────────────────────────────────


def test_http_token_set():
    result = matches("{http,https}", "https://example.com http://example.org")
    assert result == ["https", "http"]
