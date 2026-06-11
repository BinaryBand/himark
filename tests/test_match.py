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


def test_named_alpha_hexi_case_insensitive():
    # hexi accepts both cases of hex digits.
    result = matches("{hexi}", "0aF g9C")
    assert result == ["0", "a", "F", "9", "C"]


def test_named_alpha_hexi_rejects_non_hex():
    assert matches("{hexi}", "ghz") == []


# ── upper_bound ───────────────────────────────────────────────────────────────


def test_upper_bound_dec():
    result = matches("{{dec}..255}", "192 300 10 999")
    assert "192" in result
    assert "10" in result
    assert "300" not in result
    assert "999" not in result


def test_upper_bound_hex():
    result = matches("{{hex}..ff}", "0f 100 ff ab")
    assert "0f" in result
    assert "ff" in result
    assert "100" not in result


def test_upper_bound_ascii_virtual():
    # ascii is materializable, so it works as a value-range bound by codepoint.
    result = matches("{{ascii}..A}", "A B")
    assert "A" in result  # ord 'A' == 65, within bound
    assert "B" not in result  # ord 'B' == 66, over bound


def test_uni_as_bound_raises():
    import pytest

    from marky.models.exceptions import CompileError

    with pytest.raises(CompileError):
        matches("{{uni}..A}", "xyz")


# ── lower_bound ───────────────────────────────────────────────────────────────


def test_lower_bound_dec():
    result = matches("{128..{dec}}", "64 128 255 300")
    assert "128" in result
    assert "255" in result
    assert "64" not in result


# ── bounded_range ─────────────────────────────────────────────────────────────


def test_bounded_range():
    # Decimal values 10–99
    result = matches("{10..{dec}..99}", "5 10 50 99")
    assert "10" in result
    assert "50" in result
    assert "99" in result
    assert "5" not in result


# ── Value exclusion on ranges ─────────────────────────────────────────────────


def test_exclusion_subrange_on_upper_bound():
    # 0–255 excluding 128–191; 130 is excluded, 100 and 200 are kept
    result = matches("{{dec}..255,!128..191}", "130 100 200")
    assert "100" in result
    assert "200" in result
    assert "130" not in result


def test_exclusion_single_value():
    # 0–255 excluding exactly 200
    result = matches("{{dec}..255,!200}", "199 200 201")
    assert "199" in result
    assert "201" in result
    assert "200" not in result


def test_exclusion_char_range_stress():
    # Stress Bug 1 on char_range: excluded chars must never match.
    text = "abcdefghijklmnopqrstuvwxyz" * 50
    result = matches("{a..z,!d..f}", text)
    expected = [ch for ch in text if "a" <= ch <= "z" and not ("d" <= ch <= "f")]
    assert result == expected


def test_exclusion_named_alpha_stress():
    # Stress Bug 1 on named_alpha: exclusions should filter matches.
    text = ("0123456789abcdefxyzABC" * 60) + "face"
    result = matches("{hex,!a..c,!f}", text)
    expected = [
        ch
        for ch in text
        if (ch in "0123456789abcdef") and not ("a" <= ch <= "c") and ch != "f"
    ]
    assert result == expected


def test_exclusion_full_alpha_stress():
    # Stress Bug 1 on full_alpha: excluded chars should split greedy runs.
    text = ("abcdefghijklmnop" * 40) + "qrstuvwxyz"
    result = matches("{{a..z},!m..p}", text)

    expected = []
    run = ""
    for ch in text:
        if "a" <= ch <= "z" and not ("m" <= ch <= "p"):
            run += ch
        else:
            if run:
                expected.append(run)
                run = ""
    if run:
        expected.append(run)

    assert result == expected


# ── Padding ──────────────────────────────────────────────────────────────────


def test_fixed_padding_enforces_bound():
    # {3: {dec}..255} matches exactly 3 digits whose value is ≤ 255
    result = matches("{3: {dec}..255}", "042 999 256 255")
    assert "042" in result
    assert "255" in result
    assert "999" not in result
    assert "256" not in result


def test_fixed_padding_rejects_wrong_width():
    # "12" is only 2 chars; with no leading zero it cannot satisfy width 3
    assert matches("{3: {dec}..255}", "12") == []


# ── string_range ─────────────────────────────────────────────────────────────


def test_string_range_equal_length():
    # All 3-char strings between 'cat' and 'dog' inclusive.
    result = matches("{cat..dog}", "cat cau dof dog elk")
    assert result == ["cat", "cau", "dof", "dog"]


def test_string_range_excludes_out_of_range():
    assert matches("{cat..dog}", "aaa zzz") == []


def test_string_range_equal_length_only():
    # Endpoints are both len 3; 2-char substrings like "do" are never tried.
    # "aaa" and "zzz" are outside the range, "do" is only 2 chars so no match.
    result = matches("{cat..dog}", "aaa zzz")
    assert result == []


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


# ── group_class ───────────────────────────────────────────────────────────────


def test_group_class_single_char():
    # Each position is one member of a group; any casing, any length.
    result = matches("{{a,A},{b,B}}", "aBAb zz")
    assert result == ["aBAb"]


def test_group_class_multichar_tokens():
    # Multi-char group members are matched as whole tokens, not loose chars.
    result = matches("{{a,bc},{def,ghi}}", "bcghi")
    assert result == ["bcghi"]


def test_group_class_rejects_partial_token():
    # 'b' alone is not a member ('bc' is); a lone 'b' must not start a match.
    result = matches("{{a,bc},{x,yz}}", "byz")
    assert result == ["yz"]  # no-anchor: 'yz' still matches as a sub-token


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


def test_token_repetition():
    result = matches("{cat,dog}[2]", "catcat dogdog catdog")
    assert "catcat" in result
    assert "dogdog" in result


def test_variable_number_repetition():
    # First unit backs off from greedy "252" to "25" so 25+25 matches.
    assert matches("{{dec}..255}[2]", "2525") == ["2525"]


def test_grouped_word_repetition_case_folded():
    # Spec headline: same word twice, any casing. "Hello" then "HELLO".
    assert matches("{{a,A}..{z,Z}}[2]", "HelloHELLO") == ["HelloHELLO"]


def test_grouped_word_repetition_mixed():
    # "ab" and "AB" are group-equal (a↔A, b↔B).
    assert matches("{{a,A}..{z,Z}}[2]", "abAB") == ["abAB"]


# ── Separator ─────────────────────────────────────────────────────────────────


def test_standalone_separator():
    trees = parser.parse("<<\n>>")
    from marky.engine._match import find_matches

    ms = find_matches(trees[0], "line1\nline2\nline3")
    assert [m.text for m in ms] == ["line1", "line2", "line3"]


def test_separator_span():
    # Groups joined by a literal space: {a} {b} {c} matches "a b c"
    trees = parser.parse("{a} {b} {c}")
    ms = find_matches(trees[0], "a b c")
    assert len(ms) == 1
    assert ms[0].groups == ["a", "b", "c"]


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


# ── zip_range ─────────────────────────────────────────────────────────────────


def test_zip_range_matches_letter_sequence():
    # {{a..z}..{A..Z}} — any sequence of chars drawn from [a-z, A-Z].
    result = matches("{{a..z}..{A..Z}}", "Hello 123 World")
    assert "Hello" in result
    assert "World" in result
    assert "123" not in result


def test_zip_range_rejects_non_alpha():
    assert matches("{{a..z}..{A..Z}}", "123") == []


# ── variable-width padding ────────────────────────────────────────────────────


def test_variable_padding_matches_values_in_bound():
    # {:{dec}..255} delegates to the inner upper_bound, accepting any valid width.
    result = matches("{:{dec}..255}", "0 9 99 255 256 999")
    assert "0" in result
    assert "9" in result
    assert "99" in result
    assert "255" in result
    assert "256" not in result
    assert "999" not in result


# ── complement on char range ──────────────────────────────────────────────────


def test_complement_char_range():
    # {!a..z} greedily matches entire runs of non-lowercase chars.
    # "a1B2c3" → "1B2" (between 'a' and 'c') and "3" (after 'c').
    result = matches("{!a..z}", "a1B2c3")
    assert "1B2" in result
    assert "3" in result
    assert "a" not in result
    assert "c" not in result


# ── named alphabets: b32, b64, b85 ───────────────────────────────────────────


def test_named_alpha_b32():
    # b32 = 0-9, a-v (RFC 4648 §7). Letters w-z are outside.
    result = matches("{b32}", "01v wxyz")
    assert "0" in result
    assert "1" in result
    assert "v" in result
    assert "w" not in result
    assert "x" not in result


def test_named_alpha_b64():
    # b64 = A-Z, a-z, 0-9, +, /
    result = matches("{b64}", "Az+/ !")
    assert "A" in result
    assert "z" in result
    assert "+" in result
    assert "/" in result
    assert " " not in result
    assert "!" not in result


def test_named_alpha_b85():
    # b85 = RFC 1924: 0-9, A-Z, a-z, !#$%&()*+-;<=>?@^_`{|}~
    result = matches("{b85}", "A! , ")
    assert "A" in result
    assert "!" in result
    assert "," not in result
    assert " " not in result


# ── separator with explicit bounds ────────────────────────────────────────────


def test_separator_bounded_span():
    # {(}<<>>{)} lazily spans from '(' to the nearest ')', capturing in between.
    trees = parser.parse("{(}<<>>{)}")
    ms = find_matches(trees[0], "say (hello world) done")
    assert len(ms) == 1
    assert ms[0].text == "(hello world)"
    assert ms[0].groups[0] == "("
    assert ms[0].groups[1] == "hello world"
    assert ms[0].groups[2] == ")"


def test_separator_bounded_multiple_spans():
    trees = parser.parse("{(}<<>>{)}")
    ms = find_matches(trees[0], "(one) and (two)")
    assert len(ms) == 2
    assert ms[0].groups[1] == "one"
    assert ms[1].groups[1] == "two"
