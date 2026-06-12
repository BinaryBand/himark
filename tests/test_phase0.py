"""Tests for parser/phase0.py — statement splitting on the => transformer chain."""

from marky.parser.phase0 import split_statement


def steps(text: str) -> list[str]:
    return split_statement(text)


# ── Basic shapes ──────────────────────────────────────────────────────────────


def test_single_step_no_arrow():
    assert steps("{a..z}") == ["{a..z}"]


def test_pattern_and_template():
    assert steps("{a..z} => <b>{{.}}</b>") == ["{a..z}", "<b>{{.}}</b>"]


def test_chained_steps():
    assert steps("{a} => {b} => {c}") == ["{a}", "{b}", "{c}"]


def test_returns_list():
    result = split_statement("{x}")
    assert result == ["{x}"]


# ── Whitespace handling ───────────────────────────────────────────────────────


def test_trims_whitespace_around_arrows():
    assert steps("  {a}   =>   {b}  ") == ["{a}", "{b}"]


def test_internal_whitespace_preserved():
    assert steps("{#}[1..6] { } {!\\n} => out") == ["{#}[1..6] { } {!\\n}", "out"]


# ── Arrow protection inside delimiters ────────────────────────────────────────


def test_arrow_inside_braces_not_split():
    # The => lives at brace depth 1, so it is not a step boundary.
    assert steps("{a=>b}") == ["{a=>b}"]


def test_arrow_inside_chevrons_not_split():
    assert steps("{x}<<=>>>{y}") == ["{x}<<=>>>{y}"]


def test_real_arrow_after_balanced_delimiters():
    # <<>> and {**} are balanced; only the top-level => splits.
    assert steps("{**}<<>>{**} => <strong>{{1}}</strong>") == [
        "{**}<<>>{**}",
        "<strong>{{1}}</strong>",
    ]


# ── North-star example ────────────────────────────────────────────────────────


def test_markdown_heading_chain():
    src = "<<\\n>> => {#}[1..6] { } {!\\n} => <h{{#0}}>{{2}}</h{{#0}}>"
    assert steps(src) == [
        "<<\\n>>",
        "{#}[1..6] { } {!\\n}",
        "<h{{#0}}>{{2}}</h{{#0}}>",
    ]
