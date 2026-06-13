"""Tests for engine/_match.py — match semantics."""

from marky import parser
from marky.engine import execute
from marky.engine import find_matches


def matches(pattern, text):
    trees = parser.parse(pattern)
    return [m.text for m in find_matches(trees[0], text)]


def match_one(pattern, text):
    result = matches(pattern, text)
    assert len(result) == 1
    return result[0]


# The 26-letter case-fold class, written as enumerated congruence groups. (The
# `{a<->A..z<->Z}` / `{{a..z}<->{A..Z}}` range sugar was dropped; this is what it
# compiled to — a single group-class.)
CASE_FOLD = (
    "{" + ",".join(f"{{{c}<->{c.upper()}}}" for c in "abcdefghijklmnopqrstuvwxyz") + "}"
)


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
    # {a..z} is unbounded: it matches a whole lowercase string as one run.
    result = matches("{a..z}", "hello world")
    assert result == ["hello", "world"]


def test_char_range_no_match():
    assert matches("{a..m}", "z") == []


# ── named_alpha ───────────────────────────────────────────────────────────────


def test_named_alpha_dec():
    result = matches("{@d}", "a1b2c3")
    assert result == ["1", "2", "3"]


def test_named_alpha_hex():
    # hex = {@d},{{@w}..f}: one folded base-16 alphabet, so a mixed hex run
    # like "0af" matches as a single unit.
    result = matches("{@hex}", "xyz0af")
    assert result == ["0af"]


def test_named_alpha_hex_case_insensitive():
    # @w carries the case fold, so 'a' and 'F' are hex digits in one alphabet
    # and "0aF" is a single contiguous run.
    result = matches("{@hex}", "0aF g9C")
    assert result == ["0aF", "9C"]


def test_named_alpha_hex_rejects_non_hex():
    assert matches("{@hex}", "ghz") == []


def test_hex_value_range_folds_case():
    # {{@hex}..ff}: congruent spellings share a value, so 'FF' is also 255.
    assert matches("{{@hex}..ff}", "ff FF 100") == ["ff", "FF", "10", "0"]


# ── upper_bound ───────────────────────────────────────────────────────────────


def test_upper_bound_dec():
    result = matches("{{@d}..255}", "192 300 10 999")
    assert "192" in result
    assert "10" in result
    assert "300" not in result
    assert "999" not in result


def test_upper_bound_hex():
    # Canonical form only: '0f' is not the canonical spelling of value 15,
    # so it matches as '0' then 'f'.
    result = matches("{{@hex}..ff}", "0f 100 ff ab")
    assert "0f" not in result
    assert "0" in result and "f" in result
    assert "ff" in result
    assert "100" not in result


def test_upper_bound_ascii_virtual():
    # ascii is materializable, so it works as a value-range bound by codepoint.
    result = matches("{{@ascii}..A}", "A B")
    assert "A" in result  # ord 'A' == 65, within bound
    assert "B" not in result  # ord 'B' == 66, over bound


def test_uni_as_bound_raises():
    import pytest

    from marky.models.exceptions import CompileError

    with pytest.raises(CompileError):
        matches("{{@uni}..A}", "xyz")


# ── lower_bound ───────────────────────────────────────────────────────────────


def test_lower_bound_dec():
    result = matches("{128..{@d}}", "64 128 255 300")
    assert "128" in result
    assert "255" in result
    assert "64" not in result


# ── bounded_range ─────────────────────────────────────────────────────────────


def test_bounded_range():
    # Decimal values 10–99
    result = matches("{10..{@d}..99}", "5 10 50 99")
    assert "10" in result
    assert "50" in result
    assert "99" in result
    assert "5" not in result


# ── Value exclusion on ranges ─────────────────────────────────────────────────


def test_exclusion_subrange_on_upper_bound():
    # 0–255 excluding 128–191; 130 is excluded, 100 and 200 are kept
    result = matches("{{@d}..255,!128..191}", "130 100 200")
    assert "100" in result
    assert "200" in result
    assert "130" not in result


def test_exclusion_single_value():
    # 0–255 excluding exactly 200
    result = matches("{{@d}..255,!200}", "199 200 201")
    assert "199" in result
    assert "201" in result
    assert "200" not in result


def test_exclusion_char_range_stress():
    # {a..z,!d..f} is an unbounded alphabet minus d-f: excluded chars split the
    # greedy lowercase run; they must never appear in a match.
    text = "abcdefghijklmnopqrstuvwxyz" * 50
    result = matches("{a..z,!d..f}", text)

    expected = []
    run = ""
    for ch in text:
        if "a" <= ch <= "z" and not ("d" <= ch <= "f"):
            run += ch
        else:
            if run:
                expected.append(run)
                run = ""
    if run:
        expected.append(run)

    assert result == expected


def test_exclusion_named_alpha_units():
    # Exclusions filter whole matched units of the union: a lone 'f' run is
    # dropped, while a longer run like 'af' is not the excluded value.
    assert matches("{@hex,!f}", "f a 12") == ["a", "12"]


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


# ── Canonical form (spec 0.6.0) ───────────────────────────────────────────────


def test_canonical_rejects_leading_zeros():
    # '007' is not the canonical spelling of 7; it matches as three values.
    assert matches("{{@d}..255}", "007") == ["0", "0", "7"]


def test_lower_endpoint_sets_minimum_width():
    # {aa..{a..z}..zz} matches exactly the 2-char lowercase strings: values
    # are zero-padded to the lower endpoint's written width, canonical beyond.
    result = matches("{aa..{a..z}..zz}", "aa ab zz a aab")
    assert "aa" in result
    assert "ab" in result
    assert "zz" in result
    assert "a" not in result  # below minimum width
    assert "aab" not in result  # leading zero beyond minimum width


def test_duplicate_symbols_in_value_alphabet_raise():
    import pytest

    from marky.models.exceptions import CompileError

    # The digits appear twice; symbol values would be ambiguous.
    with pytest.raises(CompileError):
        matches("{{@d,@hex}..ff}", "ff")


# ── Padding ──────────────────────────────────────────────────────────────────


def test_fixed_padding_enforces_bound():
    # {3: {@d}..255} matches exactly 3 digits whose value is ≤ 255
    result = matches("{3: {@d}..255}", "042 999 256 255")
    assert "042" in result
    assert "255" in result
    assert "999" not in result
    assert "256" not in result


def test_fixed_padding_rejects_wrong_width():
    # "12" is only 2 chars; with no leading zero it cannot satisfy width 3
    assert matches("{3: {@d}..255}", "12") == []


def test_width_range_padding():
    # {2..3:{@d}..255}: widths 2-3, leading zeros allowed, value bounded.
    result = matches("{2..3:{@d}..255}", "00 042 255")
    assert "00" in result
    assert "042" in result
    assert "255" in result
    assert matches("{2..3:{@d}..255}", "7") == []  # below minimum width


def test_variable_padding_caps_width_at_len_max():
    # {:{@d}..255} accepts widths 1 through len('255') = 3, never 4.
    result = matches("{:{@d}..255}", "0042")
    assert "0042" not in result
    assert "004" in result  # the 3-wide window is the greedy match


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
    result = matches("{{a<->A},{b<->B}}", "aBAb zz")
    assert result == ["aBAb"]


def test_group_class_multichar_tokens():
    # Multi-char group members are matched as whole tokens, not loose chars.
    result = matches("{{a<->bc},{def<->ghi}}", "bcghi")
    assert result == ["bcghi"]


def test_group_class_rejects_partial_token():
    # 'b' alone is not a member ('bc' is); a lone 'b' must not start a match.
    result = matches("{{a<->bc},{x<->yz}}", "byz")
    assert result == ["yz"]  # no-anchor: 'yz' still matches as a sub-token


def test_group_class_interleave():
    # Congruence of "char + escaped space" and "char" spellings makes [count]
    # an interleave: separators optional between repetitions, never alone.
    hr = "{{-\\ <->-},{*\\ <->*},{_\\ <->_}}[3..]"
    assert matches(hr, "---") == ["---"]
    assert matches(hr, "- - -") == ["- - -"]
    assert matches(hr, "* * *") == ["* * *"]
    assert matches(hr, "-- -") == ["-- -"]
    assert matches(hr, "--") == []  # too short
    assert matches(hr, "-*-") == []  # mixed rule chars are different groups
    assert matches(hr, "    ") == []  # a space is a spelling, not a unit


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
    assert matches("{{@d}..255}[2]", "2525") == ["2525"]


def test_grouped_word_repetition_case_folded():
    # Spec headline: same word twice, any casing. "Hello" then "HELLO".
    assert matches(CASE_FOLD + "[2]", "HelloHELLO") == ["HelloHELLO"]


def test_grouped_word_repetition_mixed():
    # "ab" and "AB" are group-equal (a<->A, b<->B).
    assert matches(CASE_FOLD + "[2]", "abAB") == ["abAB"]


def test_multichar_group_repetition():
    # Repetition-equality is group-based even for multi-char members:
    # 'a' and 'bc' share a group, so repetitions may differ in surface length.
    result = matches("{a<->bc}[2]", "abc aa bcbc bca xy")
    assert "abc" in result
    assert "aa" in result
    assert "bcbc" in result
    assert "bca" in result
    assert "xy" not in result


# ── Template rendering ────────────────────────────────────────────────────────


def test_template_full_match():
    result = execute(parser.parse("{hello} => <b>{{.}}</b>"), "say hello")
    assert result == ["<b>hello</b>"]


# ── enumerated case-fold class (replaces the dropped zip-range sugar) ─────────


def test_case_fold_class_matches_letter_sequence():
    # The enumerated 26-pair class matches any [a-z, A-Z] run, case-insensitively.
    result = matches(CASE_FOLD, "Hello 123 World")
    assert "Hello" in result
    assert "World" in result
    assert "123" not in result


def test_case_fold_class_rejects_non_alpha():
    assert matches(CASE_FOLD, "123") == []


def test_class_zip_matches_case_fold():
    # {{a..z}<->{A..Z}} zips the two classes into one folded alphabet.
    assert matches("{{a..z}<->{A..Z}}", "Hello 123") == ["Hello"]


def test_zip_cardinality_mismatch_raises():
    import pytest

    from marky.models.exceptions import CompileError

    # a(1) <-> A..z(58) <-> Z(1): unequal tracks cannot zip.
    with pytest.raises(CompileError):
        matches("{a<->A..z<->Z}", "x")


# ── variable-width padding ────────────────────────────────────────────────────


def test_variable_padding_matches_values_in_bound():
    # {:{@d}..255} delegates to the inner upper_bound, accepting any valid width.
    result = matches("{:{@d}..255}", "0 9 99 255 256 999")
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


# ── named alphabets: b32, b64 ────────────────────────────────────────────────


def test_named_alpha_b32():
    # b32 = {@d},{{@w}..v} (RFC 4648 §7), one folded alphabet. Letters w-z are
    # outside the bound, so "01v" is one run and "wxyz" matches nothing.
    assert matches("{@b32}", "01v wxyz") == ["01v"]


def test_named_alpha_b64():
    # b64 = {@d},{@l},{@u},+,/ — case-sensitive (a != A), one 64-symbol alphabet,
    # so a run of base64 chars matches as a single unit.
    assert matches("{@b64}", "Az+/ !") == ["Az+/"]
