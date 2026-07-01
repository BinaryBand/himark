"""Declarative anchors and out-of-band named anchors (docs/TODO.md Step 4).

The four line/doc anchors are no longer an engine primitive: each is declared in
`himark/std.hmk` as a negative **lookaround** (`@doc_start = !<{@uni}`,
`@line_start = !<!{\\n}`, ...) over the single zero-width `LOOKAROUND` opcode and
named directly in a query (`{@line_start}`) -- there is no glyph sugar. Separately, a
`@name = anchor` declaration
introduces an **out-of-band named anchor**: a zero-width, non-rendering mark carried
beside the text in a parallel `AnchorMap`, emitted by a `{{@name}}` template
directive, matched by `{@name}` / `!{@name}`, and cleared by `{{/name}}`. Marks are
never bytes in the text, so input cannot spoof them, and they are offset-remapped on
every splice.
"""

from himark import engine, parser


def _run(source: str, text: str = "") -> str:
    return engine.run_pipeline(parser.compile_script(source), text)


# ── Declarative line/doc anchors (byte-identical to the old engine anchors) ─────


def test_line_anchors_bracket_each_line():
    assert (
        _run('{@line_start}!{\n}[1..]{@line_end} => "[{{$0}}]"', "ab\ncd\nef")
        == "[ab]\n[cd]\n[ef]"
    )


def test_doc_start_matches_only_the_first_line():
    assert _run('{@doc_start}!{\n}[1..] => "X"', "ab\ncd") == "X\ncd"


def test_doc_end_matches_only_the_last_line():
    assert _run('!{\n}[1..]{@doc_end} => "Y"', "ab\ncd") == "ab\nY"


def test_line_start_after_consecutive_newlines():
    # An empty middle line has no non-newline run, so [1..] skips it; `@line_start`
    # still fires at the start of "a" and "b".
    assert (
        _run('{@line_start}!{\n}[1..]{@line_end} => "<{{$0}}>"', "a\n\nb")
        == "<a>\n\n<b>"
    )


def test_named_anchor_equals_its_lookaround_definition():
    # `@line_start` is declared as `!<!{\n}` in std.hmk; using the name and inlining
    # its raw lookaround must compile to the same match.
    named = '{@line_start}!{\n}[1..]{@line_end} => "[{{$0}}]"'
    raw = '{!<!{\n}}!{\n}[1..]{!>!{\n}} => "[{{$0}}]"'
    assert _run(named, "a\nb") == _run(raw, "a\nb") == "[a]\n[b]"


def test_raw_negative_lookaround_is_a_line_start():
    # `!<!{\n}` reads "no non-newline behind me" -- exactly a line start.
    assert _run('{!<!{\n}}!{\n}[1..] => "L"', "ab\ncd") == "L\nL"


# ── Out-of-band named anchors: emit / match / clear ─────────────────────────────


def test_marks_never_render():
    # A `{{@g}}` emit is zero-width and non-rendering -- no marker char in the output.
    assert _run('@g = anchor\n"a{{@g}}b{{@g}}c"') == "abc"


def test_emit_then_match_wraps_at_each_mark():
    # Emit a mark after X and after Y; a later query matches at each mark and wraps
    # the following character.
    src = '@g = anchor\n"X{{@g}}Y{{@g}}Z"\n{@g}{@uni} => "[{{$0}}]"'
    assert _run(src) == "X[Y][Z]"


def test_clear_removes_the_mark():
    # Emit g, then clear it; the later `{@g}` match finds nothing.
    src = '@g = anchor\n"X{{@g}}Y"\n"{{/g}}{{$}}"\n{@g}{@uni} => "[{{$0}}]"'
    assert _run(src) == "XY"


def test_negative_named_anchor_asserts_absence():
    # `!{@g}` is a zero-width "no mark here" assertion, not a character complement.
    src = '@g = anchor\n"A{{@g}}B"\n{@uni}!{@g} => "(x)"'
    assert _run(src) == "A(x)"


def test_undeclared_named_anchor_never_matches():
    # With nothing emitted, `{@g}` matches at no position (the map is empty).
    assert _run('@g = anchor\n{@g}{@uni} => "[{{$0}}]"', "abc") == "abc"


def test_undeclared_negative_always_passes():
    # ...and `!{@g}` passes everywhere (an un-spoofable wildcard: no byte is a mark).
    assert _run('@g = anchor\n{@uni}!{@g} => "."', "abc") == "..."


# ── Offset remap: marks track the text through length-changing splices ──────────


def test_mark_survives_a_growth_before_it():
    # A statement grows the text *before* the mark; the mark must shift to stay put.
    src = (
        "@g = anchor\n"
        '"ab{{@g}}c"\n'  # "abc", mark g at position 2 (before c)
        '{a} => "AAA"\n'  # "AAAbc"; g shifts 2 -> 4
        '{@g}{@uni} => "[{{$0}}]"'
    )
    assert _run(src) == "AAAb[c]"


def test_mark_strictly_inside_a_replaced_span_is_destroyed():
    src = (
        "@g = anchor\n"
        '"a{{@g}}bc"\n'  # "abc", mark g at 1 (inside "abc")
        '{abc} => "Z"\n'  # replace [0,3) with "Z" -> the interior mark is destroyed
        '{@g}{@uni} => "[{{$0}}]"'
    )
    assert _run(src) == "Z"


def test_mark_survives_a_fixed_point_loop():
    # A `<=>` fixed point rewrites (and grows) the text over several rounds; the mark
    # is carried and remapped across every round.
    src = (
        "@g = anchor\n"
        '"aaa{{@g}}b"\n'  # "aaab", mark g at 3 (before b)
        '{a} <=> "xy"\n'  # each a -> xy until none left: "xyxyxyb"; g shifts 3 -> 6
        '{@g}{@uni} => "[{{$0}}]"'
    )
    assert _run(src) == "xyxyxy[b]"
