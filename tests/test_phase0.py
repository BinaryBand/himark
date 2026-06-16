"""Tests for parser/phase0.py — statement splitting on the => transformer chain."""

from marky.parser.phase0 import split_statement as steps


# ── Basic shapes ──────────────────────────────────────────────────────────────


def test_single_step_no_arrow():
    assert steps("{a..z}") == ["{a..z}"]


def test_pattern_and_template():
    assert steps("{a..z} => <b>{{0$}}</b>") == ["{a..z}", "<b>{{0$}}</b>"]


def test_chained_steps():
    assert steps("{a} => {b} => {c}") == ["{a}", "{b}", "{c}"]


def test_returns_step_list():
    assert steps("{x}") == ["{x}"]


# ── Whitespace handling ───────────────────────────────────────────────────────


def test_trims_whitespace_around_arrows():
    assert steps("  {a}   =>   {b}  ") == ["{a}", "{b}"]


def test_internal_whitespace_preserved():
    assert steps("{#}[1..6] { } {!\\n} => out") == ["{#}[1..6] { } {!\\n}", "out"]


# ── Arrow protection inside delimiters ────────────────────────────────────────


def test_arrow_inside_braces_not_split():
    # The => lives at brace depth 1, so it is not a step boundary.
    assert steps("{a=>b}") == ["{a=>b}"]


def test_real_arrow_after_balanced_delimiters():
    # {**} braces are balanced; only the top-level => splits.
    assert steps("{**}{!**}{**} => <strong>{{0$}}</strong>") == [
        "{**}{!**}{**}",
        "<strong>{{0$}}</strong>",
    ]
