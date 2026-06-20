"""Tests for the match engine — match semantics."""

from himark import parser
from himark.engine import execute, find_matches, splice


def matches(pattern, text):
    trees = parser.parse(pattern)
    return [m.text for m in find_matches(trees[0], text)]


def match_one(pattern, text):
    result = matches(pattern, text)
    assert len(result) == 1
    return result[0]


# The 26-letter case-fold class, written as enumerated congruence groups: each
# letter and its capital are one interchangeable position (`{a,A}`), and the
# outer braces order the 26 positions.
CASE_FOLD = (
    "{" + ",".join(f"{{{c},{c.upper()}}}" for c in "abcdefghijklmnopqrstuvwxyz") + "}"
)


# ── Literal ──────────────────────────────────────────────────────────────────


def test_literal_found():
    assert match_one("{hello}", "say hello world") == "hello"


def test_literal_not_found():
    assert matches("{hello}", "world") == []


def test_literal_multiple():
    result = matches("{hi}", "hi there, hi again")
    assert result == ["hi", "hi"]


def test_literal_closing_brace():
    # A literal `}` inside a group (`{\}}`) must match — the escaped brace is a
    # member, not the group's delimiter (regression for brace_end/split_top).
    assert matches(r"{\}}", "a}b}c") == ["}", "}"]
    assert matches(r"{\{}", "a{b") == ["{"]
    assert matches(r"{\{,\}}", "a{b}c") == ["{", "}"]  # union of `{` and `}`


# ── char_range ───────────────────────────────────────────────────────────────


def test_char_range_matches():
    # {a..z} is single-position: matches exactly one lowercase letter at a time.
    result = matches("{a..z}", "hello world")
    assert result == list("helloworld")


def test_char_range_no_match():
    assert matches("{a..m}", "z") == []


# ── named_alpha ───────────────────────────────────────────────────────────────


def test_named_alpha_dec():
    result = matches("{@d}", "a1b2c3")
    assert result == ["1", "2", "3"]


def test_named_alpha_hex():
    # @hex is one position (a single hex digit); a hex *string* is a bounded value
    # {0:@hex:fff} (width window 1–3, by the floor/ceiling widths).
    result = matches("{0:@hex:fff}", "xyz0af")
    assert result == ["0af"]


def test_named_alpha_b256_is_every_byte():
    # @b256 is the byte alphabet U+0000..U+00FF — one position per byte. 'a' and
    # 'ÿ' (U+00FF) are in range; 'Ā' (U+0100) is one past the top.
    assert matches("{@b256}", "aÿĀ") == ["a", "ÿ"]


def test_named_alpha_hex_case_insensitive():
    # @w carries the case fold, so 'a' and 'F' are one hex value; "0aF" is a
    # single value of width 3.
    result = matches("{0:@hex:fff}", "0aF g9C")
    assert result == ["0aF", "9C"]


def test_named_alpha_hex_rejects_non_hex():
    assert matches("{@hex}", "ghz") == []


def test_hex_value_range_folds_case():
    # {:@hex:ff}: congruent spellings share a value, so 'FF' is also 255.
    assert matches("{:@hex:ff}", "ff FF 100") == ["ff", "FF", "10", "0"]


# ── upper_bound (open floor) ──────────────────────────────────────────────────


def test_upper_bound_dec():
    result = matches("{:@d:255}", "192 300 10 999")
    assert "192" in result
    assert "10" in result
    assert "300" not in result  # over 255 → matches '30' then '0'
    assert "999" not in result


def test_upper_bound_hex():
    # The ceiling's width (2) is the max field width, so leading-zero padding is
    # allowed inside the window: '0f' (value 15, width 2) matches.
    result = matches("{:@hex:ff}", "0f 100 ff ab")
    assert "0f" in result
    assert "ff" in result
    assert "ab" in result
    assert "100" not in result  # width 3 > the 2-wide window


def test_upper_bound_ascii_virtual():
    # ascii is materializable, so it works as a value bound by codepoint.
    result = matches("{:@ascii:A}", "A B")
    assert "A" in result  # ord 'A' == 65, within bound
    assert "B" not in result  # ord 'B' == 66, over bound


def test_uni_as_bound_virtual():
    # @uni is too large to materialize, so the engine uses a virtual ord-based
    # alphabet: {x::y} normalises to {x:@uni:y} and matches by codepoint value.
    result = matches("{:@uni:A}", "A B")
    assert "A" in result  # ord 'A' == 65, within bound
    assert "B" not in result  # ord 'B' == 66, over bound


# ── lower_bound (open ceiling) ────────────────────────────────────────────────


def test_lower_bound_dec():
    result = matches("{128:@d:}", "64 128 255 300")
    assert "128" in result
    assert "255" in result
    assert "64" not in result


# ── bounded_range ─────────────────────────────────────────────────────────────


def test_bounded_range():
    # Decimal values 10–99
    result = matches("{10:@d:99}", "5 10 50 99")
    assert "10" in result
    assert "50" in result
    assert "99" in result
    assert "5" not in result


# ── Reference as a bound endpoint `{0:@d:$0}` ─────────────────────────────────


def test_value_bound_with_reference_ceiling():
    # `{0:@d:$0}` matches a value ≤ group 0's captured value — resolved at match
    # time. Width-agnostic: a value with more digits than the first is excluded.
    P = r"{0:@d:},{0:@d:$0}"
    assert matches(P, "5,3") == ["5,3"]  # 3 ≤ 5
    assert matches(P, "3,5") == []  # 5 ≤ 3 is false
    assert matches(P, "42,9") == ["42,9"]  # 9 ≤ 42 (different widths)
    assert matches(P, "7,7") == ["7,7"]  # equal is included


def test_value_bound_with_reference_floor():
    # A reference may also be the floor: `{$0:@d:}` matches a value ≥ the first.
    P = r"{0:@d:},{$0:@d:}"
    assert matches(P, "3,5") == ["3,5"]  # 5 ≥ 3
    assert matches(P, "5,3") == []  # 3 ≥ 5 is false


def test_value_bound_reference_undefined_fails():
    # A ceiling referencing a group that has not captured cannot match.
    assert matches(r"{0:@d:$3}", "5") == []


# ── Value exclusion on char-range classes ─────────────────────────────────────


def test_exclusion_char_range_stress():
    # {a..z,!d..f} is a single-position class: each non-excluded lowercase char
    # is an independent match; d, e, f are never matched.
    text = "abcdefghijklmnopqrstuvwxyz" * 50
    result = matches("{a..z,!d..f}", text)

    expected = [ch for ch in text if "a" <= ch <= "z" and not ("d" <= ch <= "f")]

    assert result == expected


def test_exclusion_full_alpha_stress():
    # {{a..z},!m..p} is single-position: each char in a-z except m-p is one match.
    text = ("abcdefghijklmnop" * 40) + "qrstuvwxyz"
    result = matches("{{a..z},!m..p}", text)

    expected = [ch for ch in text if "a" <= ch <= "z" and not ("m" <= ch <= "p")]

    assert result == expected


def test_duplicate_symbols_in_value_alphabet_raise():
    import pytest

    from himark.models.exceptions import CompileError

    # The digits appear twice; symbol values would be ambiguous.
    with pytest.raises(CompileError):
        matches("{:{@d,@hex}:ff}", "ff")


# ── Width window (the two bounds' widths set the field width) ──────────────────


def test_width_window_ipv4_octet():
    # {0:@d:255}: value 0–255, width 1–3 (floor 1-wide, ceiling 3-wide).
    result = matches("{0:@d:255}", "0 7 42 255 256")
    assert "0" in result and "42" in result and "255" in result
    assert "256" not in result  # over 255 → matches '25' then '6'


def test_width_window_fixed_three_wide():
    # Equal widths fix the field: {000:@d:999} is exactly 3 wide.
    result = matches("{000:@d:999}", "7 042 007 1234")
    assert "042" in result and "007" in result
    assert "7" not in result  # below the 3-wide window
    assert "1234" not in result  # wider than the window → '123' then '4'


def test_width_window_narrow_ceiling_relaxes():
    # {000:@d:9} accepts value 9 at any width from the ceiling's (1) up to the
    # floor's (3): '9', '09', '009' — but not '0009'.
    result = matches("{000:@d:9}", "9 09 009 0009")
    assert "9" in result and "09" in result and "009" in result
    assert "0009" not in result  # 4 wide > the window


# ── multi-char range (value bound over @uni: {cat..dog} == {cat:@uni:dog}) ────


def test_multi_char_range_equal_length():
    result = matches("{cat..dog}", "cat cau dof dog elk")
    assert result == ["cat", "cau", "dof", "dog"]


def test_multi_char_range_excludes_out_of_range():
    assert matches("{cat..dog}", "aaa zzz") == []


# ── Congruence classes (comma folds to one class) ────────────────────────────


def test_token_class():
    result = matches("{cat,dog}", "I have a cat and a dog and a bird")
    assert result == ["cat", "dog"]


def test_token_class_longest_first():
    result = matches("{http,https}", "https://x http://y")
    assert result == ["https", "http"]


def test_bare_chars_one_class():
    result = matches("{a,e,i,o,u}", "hello")
    assert result == ["e", "o"]


def test_congruence_pair_is_case_agnostic():
    # A bare class repeats homogeneously (same matched string), so `{a,A}[2]` is
    # aa/AA; the heterogeneous (every-casing) form is the nested `{{a,A}}[2]`.
    assert matches("{a,A}[2]", "aa aA Aa AA ab") == ["aa", "AA"]
    assert matches("{{a,A}}[2]", "aa aA Aa AA ab") == ["aa", "aA", "Aa", "AA"]


def test_het_object_over_union_frees_every_member():
    # HMK.md §Repetition: `{{U}}` is one object whose members are interchangeable,
    # so each position takes *any* of them. Over a union of ranges that means a
    # mix is allowed — `{{0..9,a..f}}[8]` is any 8 hex digits, not 8 identical
    # ones (which is what the bare alphabet `{0..9,a..f}[8]` repeats).
    assert matches("{{0..9,a..f}}[3]", "c29 cab fff") == ["c29", "cab", "fff"]
    assert matches("{{0..9,a..f}}[8]", "c29b7d93") == ["c29b7d93"]
    assert matches("{0..9,a..f}[3]", "c29 fff") == ["fff"]  # bare class: same char


def test_het_object_of_objects_stays_in_one_group():
    # The contrast: an alphabet of *objects* repeats one object, never crossing —
    # `{{a,A},{c,C}}[2]` is aa/aA/Aa/AA or cc/cC/Cc/CC, but never 'ac'.
    assert matches("{{a,A},{c,C}}[2]", "aA cC ac") == ["aA", "cC"]


def test_ordered_class_of_classes():
    # {{a,A},{b,B}} is an ordered (two-symbol) alphabet of folded positions; a
    # bounded value over it (width up to 4) matches a folded a/b string.
    result = matches("{aa:{{a,A},{b,B}}:bbbb}", "aBAb zz")
    assert result == ["aBAb"]


def test_class_rejects_partial_token():
    # 'b' alone is not a member ('bc' is); a lone 'b' must not start a match.
    result = matches("{{a,bc},{x,yz}}", "byz")
    assert result == ["yz"]  # no-anchor: 'yz' still matches as a sub-token


def test_class_interleave():
    # A heterogeneous run (a fresh member per rep) is the nested `{{…}}[3..]`
    # form: "char + escaped space" and "char" spellings interleave.
    hr = "{{{-\\ ,-},{*\\ ,*},{_\\ ,_}}}[3..]"
    assert matches(hr, "---") == ["---"]
    assert matches(hr, "- - -") == ["- - -"]
    assert matches(hr, "* * *") == ["* * *"]
    assert matches(hr, "-- -") == ["-- -"]
    assert matches(hr, "--") == []  # too short
    assert matches(hr, "-*-") == []  # mixed rule chars are different groups
    assert matches(hr, "    ") == []  # a space is a spelling, not a unit


def test_congruence_with_whitespace_member():
    # A class member may be whitespace: `{a,\ }` folds 'a' and ' ' into one
    # position; the nested `{{…}}[1..]` repeats it heterogeneously over the class.
    assert matches("{{a,\\ }}[1..]", "a a") == ["a a"]


# ── complement ────────────────────────────────────────────────────────────────


def test_complement_newline():
    # {!\n} is one non-newline char; a run is [1..], repeated heterogeneously.
    result = matches("{!\n}[1..]", "line one\nline two")
    assert result == ["line one", "line two"]


def test_complement_char_range():
    # {!a..z}[1..] matches entire runs of non-lowercase chars (heterogeneous).
    result = matches("{!a..z}[1..]", "a1B2c3")
    assert "1B2" in result
    assert "3" in result
    assert "a" not in result
    assert "c" not in result


def test_subtractive_universe_outside_brace():
    # HMK.md §Subtraction: `!{X}` (bang outside the brace) is the canonical
    # subtractive universe and resolves identically to the inner `{!X}` spelling.
    assert matches("!{a}", "abc") == ["b", "c"]
    assert matches("!{a}", "abc") == matches("{!a}", "abc")
    # A multi-member operand subtracts each member.
    assert matches("!{|,\n}", "a|b") == ["a", "b"]
    # Composes with a run and with adjacency like any universe.
    assert matches("!{a}[1..]", "xxax") == ["xx", "x"]
    assert matches("{a}!{b}", "axac") == ["ax", "ac"]


def test_multi_char_subtraction_is_a_break():
    # HMK.md §Subtraction: a multi-character subtracted member makes `!{X}` a
    # break — one char that does not *begin* X — so a run stops at the nearest X.
    assert matches("{!{xy}}[1..]", "aabxycc") == ["aab", "ycc"]  # run halts before xy
    assert matches("!{xy}", "axyb") == ["a", "y", "b"]  # only the 'x' of xy is skipped
    # The fenced-code use: a body run halts at the nearest closing fence, so
    # adjacent blocks stay separate (no lazy operator needed).
    body = "{```}{\\n}{!{\\n```}}[0..]{\\n}{```}"
    assert matches(body, "```\nA\n```\n```\nB\n```") == ["```\nA\n```", "```\nB\n```"]


def test_multi_char_subtraction_union_breaks_on_either():
    # A union of multi-char members breaks on whichever delimiter comes first.
    assert matches("{!{```,~~~}}[1..]", "aa```bb~~~cc") == ["aa", "``bb", "~~cc"]


# ── Repetition equality ───────────────────────────────────────────────────────


def test_exact_count_same_char():
    # An ordered range repeats by value: `[3]` is the diagonal (equal reps).
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
    # A bare class repeats homogeneously (same token twice); a mixed pair needs
    # the heterogeneous nested form `{{cat,dog}}[2]`.
    assert matches("{cat,dog}[2]", "catcat dogdog catdog") == ["catcat", "dogdog"]
    assert "catdog" in matches("{{cat,dog}}[2]", "catdog")


def test_variable_number_repetition():
    # First unit backs off from greedy "252" to "25" so 25+25 matches.
    assert matches("{:@d:255}[2]", "2525") == ["2525"]


# Note: word-level congruent repetition (CASE_FOLD[2] = "same word, any casing,
# twice") has no single-position form — `{:CASE_FOLD}` matches one case-folded
# word, but its `[count]` repeats the *value*, not the word — so those cases are
# intentionally dropped under the single-position model.


def test_multichar_class_repetition():
    # A bare multi-char class repeats homogeneously (same token), so `{a,bc}[2]`
    # is 'aa'/'bcbc' but not the mixed 'abc'. The heterogeneous nested form mixes.
    assert matches("{a,bc}[2]", "aa bcbc abc") == ["aa", "bcbc"]
    het = matches("{{a,bc}}[2]", "abc aa bcbc bca xy")
    assert "abc" in het and "aa" in het and "bcbc" in het and "bca" in het
    assert "xy" not in het


# ── enumerated case-fold class ────────────────────────────────────────────────


def test_case_fold_class_matches_letter_sequence():
    # A case-folded word is a value over the 26-symbol alphabet (here 5 wide).
    result = matches("{aaaaa:" + CASE_FOLD + ":zzzzz}", "Hello 123 World")
    assert "Hello" in result
    assert "World" in result
    assert "123" not in result


def test_case_fold_class_rejects_non_alpha():
    assert matches("{aaaaa:" + CASE_FOLD + ":zzzzz}", "123") == []


def test_class_to_class_range_unsupported():
    import pytest

    from himark.models.exceptions import CompileError

    # The {a..z}..{A..Z} range sugar is gone; enumerate folded pairs instead.
    with pytest.raises(CompileError):
        matches("{{a..z}..{A..Z}}", "x")


# ── Captures ──────────────────────────────────────────────────────────────────


def test_capture_groups_numbered():
    ms = find_matches(parser.parse("{@d}{@l}")[0], "1a 2b")
    assert [m.groups for m in ms] == [["1", "a"], ["2", "b"]]


def test_grouping_brace_sub_captures():
    # A grouping brace is one capture whose nested braces are sub-captures.
    ms = find_matches(parser.parse("{of{black}{quartz}}")[0], "ofblackquartz")
    assert len(ms) == 1
    assert ms[0].groups == ["ofblackquartz"]
    assert ms[0].sub_groups == [["black", "quartz"]]


def test_grouping_brace_repetition_is_structural():
    # A grouping brace is a *shape*: each repetition re-matches the shape, with
    # content free between reps — unlike an atomic class, which repeats by value.
    row = r"{{|}{!|,\n}[1..]}[2]{|}"
    assert matches(row, "| a | bb |") == ["| a | bb |"]


# ── Output (`=>`): constant templates only ───────────────────────────────────


def test_constant_template_per_match():
    # A `=>` step emits a constant for every match. A word is a non-space run
    # {!\ }[1..] (heterogeneous), since a bare class is one position.
    assert execute(parser.parse(r"{!\ }[1..] => X"), "ab cd") == ["X", "X"]


def test_splice_constant_in_place():
    # `splice` lays the rendered branches back over the source, keeping the text
    # between matches verbatim.
    assert splice(parser.parse(r"{!-}[1..] => X"), "ab-cd") == "X-X"


def test_chained_patterns_narrow():
    # A run of patterns feeds each match of the first into the second.
    assert execute(parser.parse("{@d} => {:@d:9}"), "1 23 4") == ["1", "2", "3", "4"]


# ── named alphabets: b32, b64 ────────────────────────────────────────────────


def test_named_alpha_b32():
    # b32 = {@d},{:@w:v} (RFC 4648 §7). One position is one base32 symbol; w-z
    # are outside the alphabet. A bounded value matches a base32 string.
    assert matches("{@b32}", "01v wxyz") == ["0", "1", "v"]
    assert matches("{0:@b32:vvv}", "01v wxyz") == ["01v"]


def test_named_alpha_b64():
    # b64 = {@d},{@l},{@u},+,/ — case-sensitive, a 64-symbol alphabet. One
    # position is one base64 symbol; '!' and ' ' are outside it.
    assert matches("{@b64}", "Az+/ !") == ["A", "z", "+", "/"]


# ── Self-reference {$i}: match the text an earlier group captured ──────────────


def test_back_ref_repeats_captured_word():
    # group 0 is a 3-letter word; {-{$0}}[0..] then matches '-' + that same word,
    # zero or more times. The whole "abc-abc-abc" is one match.
    pat = "{aaa:@l:zzz}{-{$0}}[0..]"
    assert matches(pat, "abc-abc-abc") == ["abc-abc-abc"]


def test_back_ref_mismatch_stops_repetition():
    # A differing word does not satisfy the back-ref, so only the first word is
    # part of the repeated run; the second matches on its own.
    pat = "{aaa:@l:zzz}{-{$0}}[0..]"
    assert matches(pat, "abc-xyz") == ["abc", "xyz"]


def test_back_ref_zero_reps():
    # With no separator-word to follow, [0..] matches zero reps: just the word.
    pat = "{aaa:@l:zzz}{-{$0}}[0..]"
    assert matches(pat, "abc") == ["abc"]


def test_back_ref_top_level_doubled_char():
    # {a..z}{$0} — a letter then the same letter. "aa" and "bb" double; "cd" does not.
    assert matches("{a..z}{$0}", "aa bb cd") == ["aa", "bb"]


def test_back_ref_undefined_group_fails():
    # {$0} with no prior group has nothing to reference, so it cannot match.
    assert matches("{$0}", "anything") == []


def test_back_ref_to_empty_capture_matches_zero_width():
    # A group that captured the empty string back-references as zero-width — a
    # required (`≥1`) back-ref of "" still matches without consuming. Here the
    # optional prefix is empty, so `{$0}` between the digits matches nothing.
    assert matches(r"{@d}[..]{9},{$0}{8}", "9,8") == ["9,8"]
    # And with a non-empty prefix the back-ref still demands the same text.
    assert matches(r"{@d}[..]{9},{$0}{8}", "19,18") == ["19,18"]
    assert matches(r"{@d}[..]{9},{$0}{8}", "19,28") == []


# ── Count-reference {#i}: match the decimal repeat count of an earlier group ───


def test_count_ref_matches_repeat_count():
    # group 0 repeats a 3-letter word [2..9]; {#0} is its repeat count rendered
    # in decimal, so "abcabcabc repeated 3 times" matches as a whole.
    pat = "{aaa:@l:zzz}[2..9]{ repeated {#0} times}"
    assert matches(pat, "abcabcabc repeated 3 times") == ["abcabcabc repeated 3 times"]


def test_count_ref_wrong_count_fails():
    # The trailing number must equal the actual repeat count.
    pat = "{aaa:@l:zzz}[2..9]{ repeated {#0} times}"
    assert matches(pat, "abcabcabc repeated 4 times") == []


def test_count_ref_backs_off_to_satisfy():
    # Greedy "aaa" is 3 reps and would need "x3"; with "x2" present the value-equal
    # backoff settles on "aa" (2 reps) so {#0} = 2 matches.
    assert matches("{a..z}[1..]x{#0}", "aaax2") == ["aax2"]


def test_count_ref_undefined_group_fails():
    assert matches("{#0}", "3") == []


# ── Count-position reference [#i]: repeat exactly group i's repeat count ───────


def test_count_position_ref_equal_counts():
    # group 0 repeats 'a'; {b}[#0] then matches exactly that many 'b's.
    assert matches("{a}[1..]-{b}[#0]", "aaa-bbb") == ["aaa-bbb"]


def test_count_position_ref_adapts():
    # A 2-rep group 0 demands exactly 2 b's.
    assert matches("{a}[1..]-{b}[#0]", "aa-bb") == ["aa-bb"]


def test_count_position_ref_caps_at_count():
    # [#0] is an exact count, so a 4th 'b' is left unconsumed.
    assert matches("{a}[1..]-{b}[#0]", "aaa-bbbb") == ["aaa-bbb"]


def test_count_position_ref_backs_off_when_short():
    # 3 a's would need 3 b's; with only 2 present the engine finds the 2=2 sub-match.
    assert matches("{a}[1..]-{b}[#0]", "aaa-bb") == ["aa-bb"]


# ── Template moustache {{ i$j }}: interpolate pipeline stage values ────────────


def test_moustache_whole_match():
    # {{0$}} (and bare {{$}}) interpolate the whole feeding match.
    assert execute(parser.parse('{0:@hex:fff} => "<{{0$}}>"'), "0af 12") == [
        "<0af>",
        "<12>",
    ]
    assert execute(parser.parse('{0:@hex:fff} => "<{{$}}>"'), "0af 12") == [
        "<0af>",
        "<12>",
    ]


def test_moustache_capture_indices():
    # {{0$0}} / {{0$1}} address individual capture groups; {{0$}} the whole match.
    out = execute(
        parser.parse('{cat}{dog} => "a={{0$0}} b={{0$1}} all={{0$}}"'), "catdog"
    )
    assert out == ["a=cat b=dog all=catdog"]


def test_moustache_count_ref():
    # {{0#0}} is the repetition count of group 0.
    assert execute(parser.parse('{a..z}[1..] => "n={{0#0}}"'), "aaa b") == [
        "n=3",
        "n=1",
    ]


def test_moustache_multi_stage_index():
    # Stages are numbered by => position, templates included: stage 0 is the
    # query, stage 1 the template before this one (addressable by its render).
    out = execute(parser.parse('{@d} => "<{{0$}}>" => "got {{1$}}"'), "1 2")
    assert out == ["got <1>", "got <2>"]


def test_moustache_splices_in_place():
    assert splice(parser.parse('{0:@hex:fff} => "<{{0$}}>"'), "0af-12") == "<0af>-<12>"


def test_moustache_capture_out_of_range_raises():
    import pytest

    from himark.models.exceptions import CompileError

    with pytest.raises(CompileError):
        execute(parser.parse('{cat} => "{{0$5}}"'), "cat")


def test_template_renders_chrome_and_refs():
    # The trailing template's literal chrome and its {{…}} refs both render.
    assert execute(parser.parse('{cat} => "<a>{{0$}}</a>"'), "cat") == ["<a>cat</a>"]


# ── Moustache sub-capture paths {{ i$j.k }}: descend into nested captures ──────


def test_moustache_subcapture_path():
    # A grouping brace's nested groups are sub-captures: 0$0.0 / 0$0.1 address them.
    out = execute(
        parser.parse('{{cat}{dog}} => "whole={{0$0}} a={{0$0.0}} b={{0$0.1}}"'),
        "catdog",
    )
    assert out == ["whole=catdog a=cat b=dog"]


def test_moustache_subcapture_deep():
    # A sub-capture that is itself a grouping brace descends further: 0$0.1.0/.1.
    out = execute(parser.parse('{{a}{{b}{c}}} => "x={{0$0.1.0}} y={{0$0.1.1}}"'), "abc")
    assert out == ["x=b y=c"]


def test_moustache_subcapture_count():
    # {{ i#j.k }} is the repeat count of a nested sub-capture.
    assert execute(parser.parse('{{cat}{dog}} => "n={{0#0.0}}"'), "catdog") == ["n=1"]


def test_moustache_subcapture_out_of_range_raises():
    import pytest

    from himark.models.exceptions import CompileError

    with pytest.raises(CompileError):
        execute(parser.parse('{{cat}{dog}} => "{{0$0.5}}"'), "catdog")


# ── Pattern stages are addressable by => position from a template ─────────────


def test_template_addresses_each_stage():
    # The template reaches stage 0 (the first query) and stage 1 (the narrowed
    # match) by index; the {a}{t} match is transformed in place within "catdog".
    out = execute(
        parser.parse('{cat}{dog} => {a}{t} => "s0={{0$}} s1={{1$}}"'), "catdog"
    )
    assert out == ["cs0=catdog s1=atdog"]


# ── Cross-stage references {N$M} in pattern position ──────────────────────────


def test_stage_ref_matches_earlier_capture():
    # {0$0}/{0$1}/{0$} match stage 0's captures / whole match; wrapping the match
    # shows which span each one found (the rest of the branch is kept in place).
    assert execute(parser.parse('{cat}{dog} => {0$0} => "[{{.}}]"'), "catdog") == [
        "[cat]dog"
    ]
    assert execute(parser.parse('{cat}{dog} => {0$1} => "[{{.}}]"'), "catdog") == [
        "cat[dog]"
    ]
    assert execute(parser.parse('{cat}{dog} => {0$} => "[{{.}}]"'), "catdog") == [
        "[catdog]"
    ]


def test_stage_ref_dotted_subcapture():
    # A pattern stage ref descends into sub-captures, like the moustache path.
    assert execute(parser.parse('{{cat}{dog}} => {0$0.1} => "[{{.}}]"'), "catdog") == [
        "cat[dog]"
    ]


def test_stage_ref_unresolvable_drops_branch():
    # A reference that can't resolve makes the query fail to match (branch drops),
    # rather than raising — patterns filter, they don't error.
    assert execute(parser.parse("{cat}{dog} => {0$5}"), "catdog") == []


def test_stage_ref_distinct_from_back_ref():
    # {$0} (within-pattern back-ref) and {0$0} (cross-stage ref) coexist.
    assert matches("{a..z}{$0}", "aa bb cd") == ["aa", "bb"]


# ── Non-terminal templates: compose, nest, filter ─────────────────────────────


def test_template_composes_via_flowing_text():
    # {{.}} is the flowing text, so a later template wraps the earlier render.
    out = execute(
        parser.parse('{cat} => "<table>{{.}}</table>" => "<super>{{.}}</super>"'),
        "cat",
    )
    assert out == ["<super><table>cat</table></super>"]


def test_query_after_template_matches_the_render():
    # A query after a template matches the rendered text and wraps each match.
    out = execute(parser.parse('{x} => "a-b-c" => {a..z} => "<{{.}}>"'), "x")
    assert out == ["<a>-<b>-<c>"]


def test_query_filters_branch_on_no_match():
    # A query that matches nothing in the branch drops it (filtering).
    assert execute(parser.parse("{cat}{dog} => {0$0}"), "catdog") == ["catdog"]
    assert execute(parser.parse("{cat}{dog} => {zzz}"), "catdog") == []
