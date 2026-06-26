"""Integration tests — north-star examples from docs/HMK.md."""

from himark import parser
from himark.engine import execute
from himark.engine import find_matches


def matches(pattern, text):
    trees = parser.parse(pattern)
    return [m.text for m in find_matches(trees[0], text)]


# ── IPv4 ──────────────────────────────────────────────────────────────────────

IPV4 = "{@d::0..255}{.}{@d::0..255}{.}{@d::0..255}{.}{@d::0..255}"


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


# ── Output (`=>`): constant templates ────────────────────────────────────────


def test_constant_template():
    # A `=>` step emits a constant for each match. A word is a non-space run
    # {!\ }[1..] — a bare class is one position.
    result = execute(parser.parse(r"{!\ }[1..] => <x>"), "ab cd")
    assert result == ["<x>", "<x>"]


def test_chain_of_patterns_narrows():
    # P => P keeps each first-query match whose text the second query also matches,
    # transforming in place (here the inner {x} is identity, so the run is kept).
    result = execute(parser.parse("{x}[1..] => {x}"), "xx y xxx")
    assert result == ["xx", "xxx"]


# ── Token class ──────────────────────────────────────────────────────────────


def test_http_token_class():
    result = matches("{http,https}", "https://example.com http://example.org")
    assert result == ["https", "http"]


# ── Non-terminal templates ────────────────────────────────────────────────────


def test_template_is_not_terminal():
    # A template's render flows on: a later query matches it, a later template
    # wraps it ({{.}} composes).
    out = execute(parser.parse('{cat} => "<a>{{.}}</a>" => "<b>{{.}}</b>"'), "cat")
    assert out == ["<b><a>cat</a></b>"]


def test_counted_group_open_ended():
    assert matches("{ab}[2..]", "ababab cd abab") == ["ababab", "abab"]
