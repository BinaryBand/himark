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


def test_ipv4_out_of_range():
    assert matches(IPV4, "256.0.0.1") == []


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
