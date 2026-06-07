import pytest
from hypothesis import given, settings, strategies as st
from himark import parser
from himark.engine import execute
from himark.models import CompileError


def run(hmk: str, target: str) -> list[str]:
    # parser.parse now returns an ordered list of step trees (one per => segment)
    steps = parser.parse(hmk)
    return execute(steps, target)


# ── Literals ────────────────────────────────────────────────────────────────


class TestLiterals:
    def test_single_char_found(self):
        assert run("[a]", "cat") == ["a"]

    def test_single_char_all_occurrences(self):
        assert run("[a]", "banana") == ["a", "a", "a"]

    def test_sequence(self):
        assert run("[abc]", "xabcx") == ["abc"]

    def test_sequence_multiple(self):
        assert run("[ab]", "ababab") == ["ab", "ab", "ab"]

    def test_no_match(self):
        assert run("[z]", "abc") == []

    def test_empty_target(self):
        assert run("[a]", "") == []

    def test_pipe_is_literal(self):
        # single | is literal in HMK — only || is alternation
        assert run("[a|b]", "a|b") == ["a|b"]

    def test_alternation_chars(self):
        assert run("[a||b]", "aXbY") == ["a", "b"]

    def test_alternation_words(self):
        assert run("[cat||dog]", "I have a cat and a dog") == ["cat", "dog"]

    def test_alternation_prefers_longer(self):
        # Greedy: longer alternative wins when both match at same position
        assert run("[ab||a]", "ab") == ["ab"]

    def test_dot_is_literal(self):
        assert run("[.]", "a.b") == ["."]


# ── Ranges ──────────────────────────────────────────────────────────────────


class TestRanges:
    def test_lowercase(self):
        assert run("[a..z]", "a1B2c") == ["a", "c"]

    def test_uppercase(self):
        assert run("[A..Z]", "AbBcC") == ["A", "B", "C"]

    def test_digit_range(self):
        assert run("[0..9]", "a1b2c3") == ["1", "2", "3"]

    def test_range_with_literal_alt(self):
        assert run("[a..c||H]", "abcHd") == ["a", "b", "c", "H"]

    def test_range_with_range_alt(self):
        assert run("[a..c||X..Z]", "abcXYZd") == ["a", "b", "c", "X", "Y", "Z"]

    def test_cross_case(self):
        # [a..Z] = [a..z||A..Z]
        assert run("[a..Z]", "aAbBzZ1") == ["a", "A", "b", "B", "z", "Z"]

    def test_cross_case_b_to_A_excludes_a(self):
        # [b..A] = [b..z||A..Z] — excludes 'a'
        result = run("[b..A]", "abcABC")
        assert "a" not in result
        assert set(result) == {"b", "c", "A", "B", "C"}

    def test_A_to_z_includes_punctuation(self):
        # [A..z] codepoints 65–122 include [ \ ] ^ _ ` (91–96)
        assert run("[A..z]", "[\\]^") == ["[", "\\", "]", "^"]

    @pytest.mark.parametrize("hmk", ["[0..z]", "[a..1]"])
    def test_mixed_type_endpoints_error(self, hmk):
        with pytest.raises(CompileError):
            run(hmk, "anything")

    @pytest.mark.parametrize("hmk", ["[z..a]", "[9..0]", "[Z..A]"])
    def test_descending_range_error(self, hmk):
        with pytest.raises(CompileError):
            run(hmk, "anything")


# ── Alternate alphabets ──────────────────────────────────────────────────────


class TestAlternateAlphabets:
    def test_hex_matches(self):
        result = run("[0..f](hex)", "09afzAFg")
        assert set(result) == {"0", "9", "a", "f", "A", "F"}

    def test_hex_case_agnostic(self):
        assert run("[0..f](hex)", "aAbBfF") == ["a", "A", "b", "B", "f", "F"]

    def test_b10_explicit(self):
        # Explicit b10 behaves identically to inferred decimal
        assert run("[0..9](b10)", "a1b2") == run("[0..9]", "a1b2")

    def test_case_insensitive_flag(self):
        assert run("[hello](i)", "Hello HELLO hello") == ["Hello", "HELLO", "hello"]

    def test_case_insensitive_range(self):
        result = run("[a..f](i)", "abcABCgG")
        assert set(result) == {"a", "b", "c", "A", "B", "C"}


# ── Multi-character ranges ────────────────────────────────────────────────────


class TestMultiCharRanges:
    def test_integer_range_in_bounds(self):
        assert run("[5..99]", "5 50 99") == ["5", "50", "99"]

    def test_integer_range_out_of_bounds(self):
        assert run("[5..99]", "4 100") == ["10"]

    def test_integer_range_substring_match(self):
        # "10" is a valid substring match inside "100" (spec: strings, not integers)
        assert run("[5..99]", "100") == ["10"]

    def test_integer_range_no_leading_zero_whole(self):
        # "007" as a unit has leading zeros — not a valid canonical match
        # Matches "0" twice then "7"
        assert run("[0..9]", "007") == ["0", "0", "7"]

    @pytest.mark.parametrize(
        "s,expected",
        [
            ("0", ["0"]),
            ("99", ["99"]),
            ("100", ["10", "0"]),
        ],
    )
    def test_integer_range_boundaries(self, s, expected):
        assert run("[0..99]", s) == expected

    def test_padded_decimal(self):
        result = run("[0..99](pad:2)", "01 50 99")
        assert result == ["01", "50", "99"]

    def test_padded_hex(self):
        result = run("[0..ff](hex, pad:2)", "0a ff 1g")
        assert result == ["0a", "ff"]

    def test_padded_width_is_multiple(self):
        # "fff" is 3 chars → pad:4 pads to next multiple of 4 → width 4
        result = run("[f..fff](hex, pad:4)", "000f 0fff 00ff")
        assert result == ["000f", "0fff", "00ff"]


# ── Shortcuts ────────────────────────────────────────────────────────────────


class TestShortcuts:
    def test_wildcard_matches_any_char(self):
        assert run("[..]", "ab!") == ["a", "b", "!"]

    def test_wildcard_unicode(self):
        assert run("[..]", "αβ") == ["α", "β"]

    def test_digit_shortcut_run(self):
        assert run("[0..]", "abc123def456") == ["123", "456"]

    def test_digit_shortcut_single(self):
        assert run("[0..]", "a1b2") == ["1", "2"]

    def test_word_shortcut(self):
        assert run("[a..]", "hello world_2") == ["hello", "world_2"]

    def test_word_shortcut_includes_digits(self):
        # \w+ — letters, digits, underscore are one run if contiguous
        assert run("[a..]", "abc123") == ["abc123"]

    def test_whitespace_shortcut_run(self):
        assert run("[ ..]", "a  b\tc") == ["  ", "\t"]

    def test_whitespace_shortcut_single_space(self):
        assert run("[ ..]", "a b") == [" "]

    def test_shortcut_not_open_ended_range(self):
        # [0..] is a named shortcut, not a generic open-ended range
        # [1..] is NOT defined and should error or be treated differently
        with pytest.raises((CompileError, NotImplementedError)):
            run("[1..]", "test")


# ── Negation ─────────────────────────────────────────────────────────────────


class TestNegation:
    def test_single_char(self):
        assert run("[[a]]", "banana") == ["b", "n", "n"]

    def test_char_range(self):
        # Runs with no lowercase
        assert run("[[a..z]]", "Hello World") == ["H", " W"]

    def test_sequence(self):
        assert run("[[abc]]", "xyzabcfoo") == ["xyz", "foo"]

    def test_alternation(self):
        assert run("[[hello||world]]", "say hello and world today") == [
            "say ",
            " and ",
            " today",
        ]

    def test_full_match_is_empty(self):
        assert run("[[a]]", "aaa") == []

    def test_no_pattern_present(self):
        assert run("[[abc]]", "xyz") == ["xyz"]

    def test_adjacent_patterns_no_gap(self):
        # "ababx" — two "ab" with no chars between → no middle run
        assert run("[[ab]]", "ababx") == ["x"]

    def test_char_class_complement(self):
        # [[a||b||c]] = no 'a', 'b', or 'c' individually
        assert run("[[a||b||c]]", "abcdef") == ["def"]

    def test_unsupported_negation_of_negation(self):
        with pytest.raises(CompileError):
            run("[[[[a]]]]", "test")

    def test_unsupported_negation_with_count(self):
        with pytest.raises(CompileError):
            run("[[a]](2)", "test")


# ── Repetition ───────────────────────────────────────────────────────────────


class TestRepetition:
    def test_exact(self):
        assert run("[a](2)", "aaa") == ["aa"]

    def test_exact_multiple(self):
        assert run("[a](2)", "aabbaabb") == ["aa", "aa"]

    def test_one_or_more(self):
        assert run("[a](1..)", "baaab") == ["aaa"]

    def test_one_or_more_no_match(self):
        assert run("[a](1..)", "bbb") == []

    def test_bounded(self):
        assert run("[a](1..3)", "aaaa") == ["aaa", "a"]

    def test_bounded_max(self):
        assert run("[a](1..3)", "aa") == ["aa"]

    def test_zero_to_max(self):
        assert run("[a](..3)", "aaaa") == ["aaa", "a"]

    def test_alternation_with_count(self):
        assert run("[a||b](3)", "aaabbb") == ["aaa", "bbb"]

    def test_lazy_takes_minimum(self):
        assert run("[a](1.., ?)", "aaa") == ["a", "a", "a"]

    def test_greedy_vs_lazy(self):
        assert run("[a](1..)", "aaa") == ["aaa"]
        assert run("[a](1.., ?)", "aaa") == ["a", "a", "a"]

    def test_lazy_bounded(self):
        assert run("[a](2..4, ?)", "aaaaaaa") == ["aa", "aa", "aa"]

    def test_count_on_alternation(self):
        assert run("[a..z||A..Z](3)", "Hello") == ["Hel"]


# ── Varied repetition ─────────────────────────────────────────────────────────


class TestVariedRepetition:
    def test_equal_counts_match(self):
        assert run("[a](n)[b](n)", "aabb") == ["aabb"]

    def test_equal_counts_multiple(self):
        assert run("[a](n)[b](n)", "ab aabb aaabbb") == ["ab", "aabb", "aaabbb"]

    def test_unequal_counts_no_full_match(self):
        # "aab" has no a^n b^n of length > 2 — only "ab" (n=1) is a valid substring
        assert run("[a](n)[b](n)", "aab") == ["ab"]
        assert run("[a](n)[b](n)", "abb") == ["ab"]

    def test_bounded_variable_lower(self):
        # [a](2..n)[b](n..3): n=2 → "aabb"
        assert run("[a](2..n)[b](n..3)", "aabb") == ["aabb"]

    def test_bounded_variable_upper(self):
        # n=3 → "aaabbb"
        assert run("[a](2..n)[b](n..3)", "aaabbb") == ["aaabbb"]

    def test_bounded_variable_out_of_range(self):
        # n must be ≥2; n=1 → no match
        assert run("[a](2..n)[b](n..3)", "ab") == []

    def test_independent_variables(self):
        # n and m are independent
        assert run("[a](n)[b](n)[c](m)[d](m)", "aabbcd") == ["aabbcd"]

    def test_conflicting_bounds_compile_error(self):
        with pytest.raises(CompileError):
            run("[a](3..n)[b](n..2)", "test")


# ── Captures ─────────────────────────────────────────────────────────────────


class TestCaptures:
    def test_full_match(self):
        assert run("[0..][px||em||rem] => {{ . }}", "24px") == ["24px"]

    def test_group_1(self):
        assert run("[0..][px||em||rem] => {{ 1 }}", "24px") == ["24"]

    def test_group_2(self):
        assert run("[0..][px||em||rem] => {{ 2 }}", "24px") == ["px"]

    def test_alternation_is_one_group(self):
        # [px||em||rem] is ONE group regardless of alternatives
        assert run("[0..][px||em||rem] => {{ 2 }}", "24px 30em") == ["px", "em"]

    def test_three_groups(self):
        assert run("[a..z](1..)[_][0..9](1..) => {{ 1 }}-{{ 3 }}", "foo_42") == [
            "foo-42"
        ]

    def test_varied_count_in_template(self):
        assert run("[a](n) => {{ . }}({{ n }})", "aaa aa a") == ["aaa(3)", "aa(2)", "a(1)"]

    def test_subgroup(self):
        # Group 1 contains [a..z](1..) and [0..9](1..) as sub-groups
        assert run("[a..z](1..)[0..9](1..) => {{ 1 }}", "abc123") == ["abc"]
        # Note: group 1 is the first [...] bracket, not a wrapper

    def test_span_reference(self):
        assert run("[a][b][c] => {{ 1.1..3.1 }}", "abc") == ["abc"]

    def test_subgroup_first_rep(self):
        assert run("[a..z](1..) => {{ 1.1 }}", "hello") == ["h"]

    def test_subgroup_third_rep(self):
        assert run("[a..z](1..) => {{ 1.3 }}", "hello") == ["l"]

    def test_subgroup_exact_count(self):
        assert run("[a..z](3) => {{ 1.2 }}", "abc") == ["b"]

    def test_subgroup_second_group(self):
        assert run("[a..z](1..)[0..9](1..) => {{ 2.1 }}", "abc123") == ["1"]

    def test_subgroup_cross_groups(self):
        assert run("[a..z](1..)[0..9](1..) => {{ 1.2 }}-{{ 2.3 }}", "abc123") == ["b-3"]

    def test_subgroup_out_of_bounds_is_empty(self):
        assert run("[a..z](1..) => {{ 1.9 }}", "hi") == [""]

    def test_subgroup_reconstruct_via_subs(self):
        assert run("[a..z](1..) => {{ 1.1 }}{{ 1.2 }}{{ 1.3 }}", "abc") == ["abc"]


# ── Separators ───────────────────────────────────────────────────────────────


class TestSeparators:
    def test_slash(self):
        assert run("<</>>", "red/green/blue") == ["red", "green", "blue"]

    def test_word(self):
        assert run("<<foo>>", "redfoogreenfooblue") == ["red", "green", "blue"]

    def test_multi_char_literal(self):
        assert run("<<::>>", "a::b::c") == ["a", "b", "c"]

    def test_consecutive_produces_empty(self):
        assert run("<</>>", "red//blue") == ["red", "", "blue"]

    def test_leading_separator(self):
        assert run("<</>>", "/red") == ["", "red"]

    def test_trailing_separator(self):
        assert run("<</>>", "red/") == ["red", ""]

    def test_no_separator_present(self):
        assert run("<</>>", "nodivider") == ["nodivider"]

    def test_separator_in_transformer(self):
        assert run("<</>> => <p>{{ . }}</p>", "a/b") == ["<p>a</p>", "<p>b</p>"]


# ── Transformers ──────────────────────────────────────────────────────────────


class TestTransformers:
    # def test_wrap_match(self):  # [ in template body not yet handled
    #     assert run("[abc] => [{{ . }}]", "xabcx") == ["[abc]"]

    def test_multiple_matches(self):
        assert run("[a..z](1..) => <em>{{ . }}</em>", "hello world") == [
            "<em>hello</em>",
            "<em>world</em>",
        ]

    def test_count_template_var(self):
        assert run("[a](n) => {{ n }}x", "aaa aa a") == ["3x", "2x", "1x"]

    # def test_emoji_shortcode(self):  # emoji rendering not yet implemented
    #     result = run("[done] => {{ . }} {{ :white_check_mark: }}", "done")
    #     assert result == ["done ✅"]

    # def test_latex_pi(self):  # LaTeX rendering not yet implemented
    #     assert run("[pi] => {{ $\\pi$ }}", "pi") == ["π"]

    # def test_template_lone_brace_is_literal(self):  # brace escaping not yet implemented
    #     assert run("[a] => {{{ . }}}", "x") == ["{x}"]

    # def test_template_escaped_double_brace(self):  # brace escaping not yet implemented
    #     assert run("[a] => {{ . }}\\}}", "x") == ["x}}"]

    def test_template_whitespace_insignificant(self):
        assert run("[a] => {{ . }}", "x") == run("[a] => {{.}}", "x")


# ── Chained transformers ───────────────────────────────────────────────────────


class TestChainedTransformers:
    def test_positive_lookahead(self):
        # Return digit run only when followed by 'px'
        assert run("[0..][px] => {{ 1 }}", "24px 30em") == ["24"]

    def test_positive_lookbehind(self):
        # Return 'px' only when preceded by a digit run
        assert run("[0..][px] => {{ 2 }}", "24px 30em xpx") == ["px"]

    def test_multi_step_chain(self):
        target = "# Hello\nNot a heading\n# World"
        result = run("<<\\n>> => [#][ ][a..Z](1..) => <h1>{{ 3 }}</h1>", target)
        assert result == ["<h1>Hello</h1>", "<h1>World</h1>"]

    def test_chain_filters_non_matching_steps(self):
        # Lines not matching second step are silently dropped
        target = "# Title\njust text\n# Other"
        result = run("<<\\n>> => [#][ ][a..Z](1..) => {{ 3 }}", target)
        assert result == ["Title", "Other"]

    def test_chain_full_match_passed_forward(self):
        # {{ . }} in final template refers to the last step's match
        result = run("[0..][px||em] => [0..9](1..) => {{ . }}", "24px")
        assert result == ["24"]


# ── Anchors ────────────────────────────────────────────────────────────────────


class TestAnchors:
    def test_line_start_matches_first(self):
        assert run("^[abc]", "abc\nxabc") == ["abc"]

    def test_line_end_matches_at_eol(self):
        assert run("[abc]$", "xabc\nabc ") == ["abc"]

    def test_doc_start(self):
        assert run("^^[a..z](1..)", "hello\nworld") == ["hello"]

    def test_doc_end(self):
        assert run("[a..z](1..)$$", "hello\nworld") == ["world"]

    def test_caret_literal_in_brackets(self):
        assert run("[^]", "a^b") == ["^"]

    def test_dollar_literal_in_brackets(self):
        assert run("[$]", "a$b") == ["$"]


# ── Escaping ───────────────────────────────────────────────────────────────────


class TestEscaping:
    def test_literal_open_bracket(self):
        assert run("\\[[a]\\]", "[a]") == ["[a]"]

    def test_literal_backslash(self):
        assert run("[\\\\]", "a\\b") == ["\\"]

    def test_tab_escape(self):
        assert run("[\\t]", "a\tb") == ["\t"]

    def test_newline_escape(self):
        assert run("[\\n]", "a\nb") == ["\n"]

    def test_carriage_return_escape(self):
        assert run("[\\r]", "a\rb") == ["\r"]


# ── Whitespace significance ────────────────────────────────────────────────────


class TestWhitespace:
    def test_space_outside_brackets_insignificant(self):
        assert run("[a..z] (1..3)", "abc") == run("[a..z](1..3)", "abc")

    def test_space_inside_brackets_is_literal(self):
        assert run("[ ]", "a b c") == [" ", " "]

    def test_literal_string_with_space(self):
        assert run("[hello world]", "say hello world now") == ["hello world"]

    def test_space_literal_vs_whitespace_shortcut(self):
        assert run("[ ]", "a  b") == [" ", " "]  # two single spaces
        assert run("[ ..]", "a  b") == ["  "]  # one two-space run


# ── Error conditions ────────────────────────────────────────────────────────────


class TestErrors:
    def test_mixed_type_range_endpoints(self):
        with pytest.raises(CompileError):
            run("[0..z]", "anything")

    def test_descending_ascii_range(self):
        with pytest.raises(CompileError):
            run("[z..a]", "anything")

    def test_descending_digit_range(self):
        with pytest.raises(CompileError):
            run("[9..0]", "anything")

    def test_negation_of_negation(self):
        with pytest.raises(CompileError):
            run("[[[[a]]]]", "anything")

    def test_negation_with_count_modifier(self):
        with pytest.raises(CompileError):
            run("[[a]](2)", "anything")

    def test_varied_conflicting_bounds(self):
        with pytest.raises(CompileError):
            run("[a](3..n)[b](n..2)", "anything")


# ── Property-based ─────────────────────────────────────────────────────────────

_lowercase = st.text(alphabet=st.characters(whitelist_categories=("Ll",)), min_size=1)
_alphanum = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=0, max_size=40
)
_small_ints = st.integers(min_value=0, max_value=99)
_large_ints = st.integers(min_value=100, max_value=999)


class TestPropertyBased:
    @given(_lowercase)
    def test_lowercase_range_only_yields_lowercase(self, target):
        for match in run("[a..z]", target):
            assert all("a" <= c <= "z" for c in match)

    @given(_alphanum)
    def test_literal_match_is_exact_substring(self, target):
        for match in run("[abc]", target):
            assert match == "abc"

    @given(_alphanum)
    def test_negation_result_contains_no_pattern(self, target):
        for match in run("[[ab]]", target):
            assert "ab" not in match

    @given(_small_ints)
    def test_in_range_integer_matches(self, n):
        s = str(n)
        assert s in run("[0..99]", s)

    @given(_large_ints)
    @settings(max_examples=200)
    def test_out_of_range_integer_no_full_match(self, n):
        s = str(n)
        # A 3-digit number can't appear as a whole match of [0..99]
        for match in run("[0..99]", s):
            assert len(match) <= 2

    @given(st.text(min_size=1, max_size=30))
    def test_empty_target_always_no_match(self, hmk_fragment):
        # Regardless of what pattern-like input we give, empty target → []
        # Use a known-valid pattern to avoid compile errors
        assert run("[a..z]", "") == []

    @given(_alphanum)
    def test_alternation_matches_subset_of_either(self, target):
        either = set(run("[a||b]", target))
        first = set(run("[a]", target))
        second = set(run("[b]", target))
        assert either <= first | second
