"""The HMK-self-hosted cosmetic tidy (`himark/scripts/format_hmk.hmk`).

A dogfooding experiment written entirely in HMK. We pin the line-local tidies
(trailing whitespace, blank runs, file edges, arrow spacing) and that they stay
idempotent — and, crucially, that the script's **masking pre-pass** protects
template interiors: an inline `=>`, odd spacing, or an escaped quote inside a
`"…"` template is left untouched while real arrows are canonicalized.
"""

from pathlib import Path

from himark import engine, parser

FMT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "format_hmk.hmk"
_PIPELINE = parser.load_script(str(FMT))


def tidy(src: str) -> str:
    return engine.run_pipeline(_PIPELINE, src)


def test_collapses_blank_runs():
    assert tidy("{a}\n\n\n\n{b}\n") == "{a}\n\n{b}\n"


def test_strips_trailing_whitespace():
    assert tidy('{a} => "x"   \n') == '{a} => "x"\n'


def test_indents_continuations():
    assert tidy('{a} => "x"\n   => {b}\n') == '{a} => "x"\n    => {b}\n'


def test_trims_file_edges():
    assert tidy("\n\n{a}\n\n\n") == "{a}\n"


def test_everything_at_once_is_idempotent():
    messy = '\n\n{a} => "x"\t\n   => {b}\n\n\n\n{c}   \n\n\n'
    once = tidy(messy)
    assert once == '{a} => "x"\n    => {b}\n\n{c}\n'
    assert tidy(once) == once


# ── Arrow spacing (canonicalized via the masking pre-pass) ────────────────────


def test_inline_arrow_spacing_collapses_to_one_space():
    assert tidy('{a}   =>   "x"\n') == '{a} => "x"\n'


def test_tab_before_arrow_becomes_one_space():
    assert tidy('{a}\t=> "x"\n') == '{a} => "x"\n'


def test_arrow_inside_comment_is_left_alone():
    # An inline `=>` is normalized only after a step end (`}` `»` `]`), so a `=>`
    # in a comment keeps its spacing.
    assert tidy("//  step =>   then\n") == "//  step =>   then\n"
    assert tidy("//        =>\n") == "//        =>\n"


# ── Masking: template interiors are protected ─────────────────────────────────


def test_arrow_inside_template_is_untouched():
    # A literal `=>` inside a "…" template is not a pipeline arrow; the mask
    # pre-pass hides it, so its surrounding spacing is preserved verbatim.
    assert tidy('{x} => "a => b"\n') == '{x} => "a => b"\n'
    assert tidy('{x} => "a  =>  b"\n') == '{x} => "a  =>  b"\n'


def test_escaped_quote_inside_template_survives():
    assert tidy('{z} => "say \\"hi\\""\n') == '{z} => "say \\"hi\\""\n'


def test_multiline_brace_interior_is_preserved():
    # A brace group spanning lines keeps its interior indentation (the arrow and
    # whitespace rules are line-local and do not reach inside it).
    src = '{a,\n    {b,c}\n} => "x"\n'
    assert tidy(src) == src


def test_multistep_chain_spaces_each_arrow():
    assert tidy('{a}=>{b}=>"x"\n') == '{a} => {b} => "x"\n'


def test_literal_brace_pattern_is_preserved():
    # `{\{,\}}` (a union of literal `{` and `}`) is a pattern, not a template;
    # fmt only canonicalizes the arrow after its `]`.
    assert tidy('{\\{,\\}}[1..]=>"x"\n') == '{\\{,\\}}[1..] => "x"\n'


def test_leading_whitespace_on_statement_is_outdented():
    # The brace-newline mask lets fmt tell a real statement line from a
    # brace-continuation line, so a hand-indented statement is out-dented.
    assert tidy('{a} => "x"\n   {b} => "y"\n') == '{a} => "x"\n{b} => "y"\n'


def test_multiline_brace_indentation_is_protected_when_outdenting():
    # The out-dent rule must NOT reach inside a multi-line brace: its interior
    # newlines are masked, so the indented `{d,e}` line keeps its indentation.
    src = '{a,{b,c,\n    {d,e}\n}}[1..] => "x"\n'
    assert tidy(src) == src


# Runbook: write the formatted sample to `tests/demos/output` for manual inspection
if __name__ == "__main__":
    RES = Path(__file__).resolve().parent / "resources"
    OUT = Path(__file__).resolve().parent / "output"
    OUT.mkdir(parents=True, exist_ok=True)
    src = (RES / "sample.hmk").read_text("utf-8")
    (OUT / "formatted_sample.hmk").write_text(tidy(src), "utf-8")
    print(f"Wrote formatted_sample.hmk to {OUT}")
