"""Script-local definitions: a `.hmk` line `@name = <body>` binds `@name` to a
pattern fragment, scoped to that file and expanded textually before tokenizing
(see `parser.compile_script`). These pin the loader's classification,
scope/collision rules, and the invariant that a definition leaves no trace in the
compiled pipeline."""

import pytest

from himark import engine, parser
from himark.models.exceptions import CompileError


def _run(source: str, text: str) -> str:
    return engine.run_pipeline(parser.compile_script(source), text)


def test_definition_expands_and_runs():
    # The DRY heading rule from the spec: two fragments compose into the full ATX
    # heading statement; anchors are unnumbered, so #0 is the level and $2 the text.
    src = (
        "@head = {@line_start}{#}[1..6]{ }[1..]\n"
        "@eol  = !{\\n}[1..]\n"
        '@head@eol => "<h{{#0}}>{{$2}}</h{{#0}}>"\n'
    )
    assert _run(src, "## Hello\n# World") == "<h2>Hello</h2>\n<h1>World</h1>"


def test_definition_leaves_no_trace():
    # A defined script and the hand-inlined statement compile to identical pipelines
    # — definitions are a source convenience, invisible downstream.
    defined = parser.compile_script('@n = {@d}[1..]\n@n{\\,}@n => "{{$0}}+{{$1}}"\n')
    inlined = parser.compile_pipeline(['{@d}[1..]{\\,}{@d}[1..] => "{{$0}}+{{$1}}"'])
    assert defined == inlined


def test_definition_is_lexically_scoped():
    # A definition is visible only to statements that follow it; the classifier
    # keys on the lone `=` after the name, never the `=>` arrow.
    assert _run('@x = {a}\n@x => "Z"', "a b a") == "Z b Z"


def test_definition_can_reference_earlier_definition_and_prelude():
    # Local defs share one fixed-point expansion with the prelude, so a def may
    # reference an earlier def or a prelude variable (@d).
    src = '@digits = {{@d}}[1..]\n@pair = @digits{\\,}@digits\n@pair => "ok"'
    assert _run(src, "12,34 x") == "ok x"


def test_definition_shadowing_prelude_variable_errors():
    with pytest.raises(CompileError, match="shadows a prelude declaration"):
        parser.compile_script("@d = {x}")


def test_definition_redefinition_errors():
    with pytest.raises(CompileError, match="already defined"):
        parser.compile_script("@x = {a}\n@x = {b}")


def test_fixed_point_arrow_still_flagged_with_defs():
    # A `<=>` statement keeps its fixed-point flag when its head comes from a def.
    src = '@paren = {(}!{(,)}[..]{)}\n@paren <=> "{{$1}}"'
    pipeline = parser.compile_script(src)
    assert pipeline[0][0].fixed_point is True
    assert _run(src, "a(b(c)d)e") == "abcde"
