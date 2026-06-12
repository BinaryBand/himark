"""Tests for parser/phase0.py — statement splitting on the => transformer chain."""

from marky.parser.phase0 import split_statement


def steps(text: str) -> list[str]:
    return split_statement(text)[0]


def mode(text: str) -> bool:
    return split_statement(text)[1]


# ── Basic shapes ──────────────────────────────────────────────────────────────


def test_single_step_no_arrow():
    assert steps("{a..z}") == ["{a..z}"]


def test_pattern_and_template():
    assert steps("{a..z} => <b>{{.}}</b>") == ["{a..z}", "<b>{{.}}</b>"]


def test_chained_steps():
    assert steps("{a} => {b} => {c}") == ["{a}", "{b}", "{c}"]


def test_returns_steps_mode_and_pipes():
    assert split_statement("{x}") == (["{x}"], False, [False])


# ── Replace-mode arrow (=>+) ──────────────────────────────────────────────────


def test_extract_arrow_is_default():
    assert mode("{a..z} => <p>{{.}}</p>") is False


def test_replace_arrow_sets_mode():
    steps_, replace, piped = split_statement("{a..z} =>+ <p>{{.}}</p>")
    assert replace is True
    assert steps_ == ["{a..z}", "<p>{{.}}</p>"]  # the '+' is not in the template
    assert piped == [False, False]  # the first arrow's '+' is the replace flag


def test_replace_mode_taken_from_first_arrow():
    # The first arrow decides the mode; its '+' is stripped, never leaking
    # into a step.
    steps_, replace, piped = split_statement("{a} =>+ {b} => <x>{{.}}</x>")
    assert replace is True
    assert steps_ == ["{a}", "{b}", "<x>{{.}}</x>"]
    assert piped == [False, False, False]


def test_inner_plus_marks_pipe():
    # An inner '=>+' flags the step after it as piped.
    steps_, replace, piped = split_statement("{a} => {b} =>+ <x> => {c}")
    assert replace is False
    assert steps_ == ["{a}", "{b}", "<x>", "{c}"]
    assert piped == [False, False, True, False]


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
