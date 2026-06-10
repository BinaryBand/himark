"""Tests for varied-repetition: variable count modifiers (n, m, …)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from marky import parser
from marky.engine import execute
from marky.utils.varied_rep import VarSpec, collect_var_specs, iter_bindings


def run(hmk: str, target: str) -> list[str]:
    return execute(parser.parse(hmk), target)


# ---------------------------------------------------------------------------
# Unit tests for varied_rep helpers
# ---------------------------------------------------------------------------


class TestVarSpec:
    def test_domain_bounded(self):
        assert list(VarSpec("n", lo=2, hi=4).domain(100)) == [2, 3, 4]

    def test_domain_unbounded_capped_by_max(self):
        assert list(VarSpec("n", lo=1, hi=None).domain(3)) == [1, 2, 3]

    def test_domain_empty_when_lo_exceeds_max(self):
        assert list(VarSpec("n", lo=5, hi=None).domain(3)) == []


class TestCollectVarSpecs:
    def test_bare_variable(self):
        tree = parser.parse("[a](n)")[0]
        specs = collect_var_specs(tree)
        assert "n" in specs
        assert specs["n"].lo == 1
        assert specs["n"].hi is None

    def test_no_variables(self):
        tree = parser.parse("[a](1..)")[0]
        assert collect_var_specs(tree) == {}

    def test_variable_with_upper_literal(self):
        # (2..n): var n is the upper bound; literal 2 floors it
        tree = parser.parse("[a](2..n)")[0]
        specs = collect_var_specs(tree)
        assert specs["n"].lo == 2
        assert specs["n"].hi is None

    def test_variable_with_lower_literal(self):
        # (n..3): var n is the lower bound; literal 3 caps it
        tree = parser.parse("[a](n..3)")[0]
        specs = collect_var_specs(tree)
        assert specs["n"].lo == 1
        assert specs["n"].hi == 3

    def test_two_occurrences_bounds_merged(self):
        # (2..n) and (n..4) across two brackets → n ∈ {2,3,4}
        tree = parser.parse("[a](2..n)[b](n..4)")[0]
        specs = collect_var_specs(tree)
        assert specs["n"].lo == 2
        assert specs["n"].hi == 4

    def test_two_independent_variables(self):
        tree = parser.parse("[a](n)[b](m)")[0]
        specs = collect_var_specs(tree)
        assert set(specs) == {"n", "m"}


class TestIterBindings:
    def test_single_bounded_var(self):
        specs = {"n": VarSpec("n", lo=2, hi=4)}
        bindings = list(iter_bindings(specs, max_count=10))
        # Largest first (greedy)
        assert bindings == [{"n": 4}, {"n": 3}, {"n": 2}]

    def test_no_vars_yields_empty_dict_once(self):
        assert list(iter_bindings({}, max_count=10)) == [{}]

    def test_two_vars_cartesian_product(self):
        specs = {"m": VarSpec("m", lo=1, hi=2), "n": VarSpec("n", lo=1, hi=2)}
        result = list(iter_bindings(specs, max_count=10))
        # Sorted by name (m, n), both descending → (2,2),(2,1),(1,2),(1,1)
        assert result == [
            {"m": 2, "n": 2},
            {"m": 2, "n": 1},
            {"m": 1, "n": 2},
            {"m": 1, "n": 1},
        ]

    def test_empty_domain_yields_nothing(self):
        specs = {"n": VarSpec("n", lo=5, hi=None)}
        assert list(iter_bindings(specs, max_count=3)) == []


# ---------------------------------------------------------------------------
# Engine integration: matching
# ---------------------------------------------------------------------------


class TestVariedRepMatching:
    @pytest.mark.parametrize(
        "target, expected",
        [
            ("ab", ["ab"]),  # n=1
            ("aabb", ["aabb"]),  # n=2
            ("aaabbb", ["aaabbb"]),  # n=3
            ("aab", ["ab"]),  # no n satisfies at pos=0; falls back to n=1 at pos=1
            ("ba", []),  # pattern is [a](n)[b](n), not [b..a]
        ],
    )
    def test_single_var_two_groups(self, target, expected):
        assert run("[a](n)[b](n)", target) == expected

    def test_greedy_prefers_larger_n(self):
        # At pos=0 in "aabb", n=2 is tried before n=1 and wins.
        assert run("[a](n)[b](n)", "aabb") == ["aabb"]

    def test_multiple_matches_independent_n(self):
        # Each match finds its own greedy n.
        assert run("[a](n)[b](n)", "aabbaabb") == ["aabb", "aabb"]

    def test_mixed_n_values_across_matches(self):
        # "ab" (n=1) then "aabb" (n=2)
        assert run("[a](n)[b](n)", "abaabb") == ["ab", "aabb"]

    def test_two_independent_variables(self):
        assert run("[a](n)[b](n)[c](m)[d](m)", "abcd") == ["abcd"]
        assert run("[a](n)[b](n)[c](m)[d](m)", "aabbccdd") == ["aabbccdd"]

    def test_bounded_variable(self):
        # n ∈ {2, 3}
        assert run("[a](2..n)[b](n..3)", "aabb") == ["aabb"]  # n=2
        assert run("[a](2..n)[b](n..3)", "aaabbb") == ["aaabbb"]  # n=3
        assert run("[a](2..n)[b](n..3)", "ab") == []  # n=1 out of range

    def test_single_variable_with_real_range(self):
        # [a..z](n) matches exactly n lowercase letters
        assert run("[a..z](n)", "abc") == ["abc"]  # n=3 (greedy, whole string)
        assert run("[a..z](n)", "ab1c") == ["ab", "c"]

    def test_variable_zero_length_not_matched(self):
        # n must be >= 1 (lo defaults to 1), so zero-length matches never occur.
        assert all(len(m) >= 1 for m in run("[a](n)", "aaa"))


# ---------------------------------------------------------------------------
# Engine integration: template {{ n }}
# ---------------------------------------------------------------------------


class TestVariedRepTemplate:
    def test_n_in_template(self):
        assert run("[a..z](n) => {{ . }}x{{ n }}", "hello") == ["hellox5"]

    def test_n_per_match(self):
        results = run("[a](n)[b](n) => {{ n }}", "aabbaabb")
        assert results == ["2", "2"]

    def test_n_and_group_in_template(self):
        # Group 1 = [a..z] match, n = count
        results = run("[a..z](n) => {{ 1 }} ({{ n }})", "hi")
        assert results == ["hi (2)"]

    def test_independent_vars_in_template(self):
        results = run("[a](n)[b](n)[c](m)[d](m) => {{ n }},{{ m }}", "aabbccdd")
        assert results == ["2,2"]


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


@given(st.integers(min_value=1, max_value=6))
def test_exact_variable_match_length(n):
    target = "a" * n + "b" * n
    result = run("[a](n)[b](n)", target)
    assert result == [target]


@given(st.integers(min_value=1, max_value=6))
def test_template_n_equals_match_length(n):
    target = "a" * n
    results = run("[a](n) => {{ n }}", target)
    assert results == [str(n)]
