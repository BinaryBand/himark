"""Tests for engine/_match.py — match semantics."""

from marky import parser
from marky.engine import execute
from marky.engine._match import find_matches


def matches(pattern, text):
    trees = parser.parse(pattern)
    return [m.text for m in find_matches(trees[0], text)]


def match_one(pattern, text):
    result = matches(pattern, text)
    assert len(result) == 1
    return result[0]


# ── Literal ──────────────────────────────────────────────────────────────────


def test_literal_found():
    assert match_one("{hello}", "say hello world") == "hello"


def test_literal_not_found():
    assert matches("{hello}", "world") == []


def test_literal_multiple():
    result = matches("{hi}", "hi there, hi again")
    assert result == ["hi", "hi"]


# ── char_range ───────────────────────────────────────────────────────────────


def test_char_range_matches():
    result = matches("{a..z}", "hello")
    assert result == ["h", "e", "l", "l", "o"]


def test_char_range_no_match():
    assert matches("{a..m}", "z") == []


# ── named_alpha ───────────────────────────────────────────────────────────────


def test_named_alpha_dec():
    result = matches("{dec}", "a1b2c3")
    assert result == ["1", "2", "3"]


def test_named_alpha_hex():
    result = matches("{hex}", "xyz0af")
    assert result == ["0", "a", "f"]


# ── upper_bound ───────────────────────────────────────────────────────────────


def test_upper_bound_dec():
    result = matches("{{dec}..255}", "192 300 10 999")
    assert set(result) == {"192", "10"}


def test_upper_bound_hex():
    result = matches("{{hex}..ff}", "0f 100 ff ab")
    assert "0f" in result
    assert "ff" in result
    assert "100" not in result


# ── lower_bound ───────────────────────────────────────────────────────────────


def test_lower_bound_dec():
    result = matches("{128..{dec}}", "64 128 255 300")
    assert "128" in result
    assert "255" in result
    assert "64" not in result


# ── bounded_range ─────────────────────────────────────────────────────────────


def test_bounded_range():
    result = matches("{aa..{a..z}..zz}", "aa bb zz aa hello zzz")
    assert set(result) == {"aa", "bb", "zz"}


# ── token_set ─────────────────────────────────────────────────────────────────


def test_token_set():
    result = matches("{cat,dog}", "I have a cat and a dog and a bird")
    assert result == ["cat", "dog"]


def test_token_set_order():
    result = matches("{http,https}", "https://x http://y")
    assert result == ["https", "http"]


# ── union ─────────────────────────────────────────────────────────────────────


def test_union_chars():
    result = matches("{a,e,i,o,u}", "hello")
    assert result == ["e", "o"]


# ── complement ────────────────────────────────────────────────────────────────


def test_complement_newline():
    result = matches("{!\n}", "line one\nline two")
    assert result == ["line one", "line two"]


# ── Repetition equality ───────────────────────────────────────────────────────


def test_exact_count_same_char():
    result = matches("{a..z}[3]", "aaa bbb abc xyz")
    assert set(result) == {"aaa", "bbb"}


def test_exact_count_wrong():
    assert matches("{a..z}[3]", "abc") == []


def test_count_range():
    result = matches("{a..z}[2..3]", "aa bbb c")
    assert "aa" in result
    assert "bbb" in result
    assert "c" not in result


# ── Separator ─────────────────────────────────────────────────────────────────


def test_standalone_separator():
    trees = parser.parse(r"<<\n>>")
    from marky.engine._match import find_matches

    ms = find_matches(trees[0], "line1\nline2\nline3")
    assert [m.text for m in ms] == ["line1", "line2", "line3"]


def test_separator_span():
    result = matches("{a}{b} {c}", "a b c")
    # leaf " " separates groups
    assert result == ["a", "b", "c"]


# ── Captures ─────────────────────────────────────────────────────────────────


def test_capture_groups():
    trees = parser.parse("{a..z}{0..9}")
    from marky.engine._match import find_matches

    ms = find_matches(trees[0], "a1 b2")
    assert len(ms) == 2
    assert ms[0].groups == ["a", "1"]
    assert ms[1].groups == ["b", "2"]


def test_count_refs_recorded():
    trees = parser.parse("{a..z}[3]")
    from marky.engine._match import find_matches

    ms = find_matches(trees[0], "aaa")
    assert ms[0].count_refs[0] == 3


# ── Template rendering ────────────────────────────────────────────────────────


def test_template_group_ref():
    result = execute(parser.parse("{a..z} => [{{0}}]"), "x")
    assert result == ["[x]"]


def test_template_full_match():
    result = execute(parser.parse("{hello} => <b>{{.}}</b>"), "say hello")
    assert result == ["<b>hello</b>"]
