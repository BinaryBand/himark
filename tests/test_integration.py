"""Integration tests — north-star examples from docs/HMK.md."""

from marky import parser
from marky.engine import execute
from marky.engine import find_matches


def matches(pattern, text):
    trees = parser.parse(pattern)
    return [m.text for m in find_matches(trees[0], text)]


# ── IPv4 ──────────────────────────────────────────────────────────────────────

IPV4 = "{{@d}..255}{.}{{@d}..255}{.}{{@d}..255}{.}{{@d}..255}"


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
    # References are gone; a `=>` step emits a constant for each match.
    result = execute(parser.parse("{a..z} => <x>"), "ab cd")
    assert result == ["<x>", "<x>"]


def test_chain_of_patterns_narrows():
    # P => P feeds each match of the first pattern into the second.
    result = execute(parser.parse("{x}[1..] => {x}"), "xx y xxx")
    assert result == ["x", "x", "x", "x", "x"]


# ── Token class ──────────────────────────────────────────────────────────────


def test_http_token_class():
    result = matches("{http,https}", "https://example.com http://example.org")
    assert result == ["https", "http"]


# ── Pipes (inner =>+) ─────────────────────────────────────────────────────────


def test_pipe_requires_template():
    import pytest

    from marky.models.exceptions import CompileError

    with pytest.raises(CompileError):
        execute(parser.parse("{a} => {b} =>+ {c}"), "x")


def test_counted_group_open_ended():
    assert matches("{ab}[2..]", "ababab cd abab") == ["ababab", "abab"]
