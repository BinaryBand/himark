"""Declared filters in L2 (docs/TODO.md Step 3).

Filters are no longer a native engine set: `@name = <pipeline>` in `himark/std.hmk`
(or a script-local def) declares one, invoked at a `| name` moustache pipe. A body
that is a single `{{ … }}` moustache is **value-shaped** (evaluated with `$` bound
to the subject universe, so alphabet + band survive); any richer pipeline is
**document-shaped** (run over the subject's text). These pin both application paths,
filter chaining, the shipped `trim`/`indent`, and the unknown-filter error.
"""

import pytest

from himark import engine, parser
from himark.models.exceptions import CompileError


def _run(source: str, text: str) -> str:
    return engine.run_pipeline(parser.compile_script(source), text)


# ── Value-shaped filters preserve the subject's band (docs/ALGEBRA.md) ─────────


def test_value_filter_preserves_band():
    # `@double` is a single-moustache body -> value-shaped: `$` is the banded
    # capture universe, so `$ * 2` keeps the LHS width and wraps mod the band.
    src = '@double = "{{ $ * 2 }}"\n{@d::0..255} => "{{ $0 | double }}"'
    assert _run(src, "09") == "18"  # 9*2=18, kept at the 2-symbol width
    assert _run(src, "200") == "144"  # 400 mod 256 = 144, at the 3-symbol width


def test_bitwise_value_filter():
    src = '@hi = "{{ $ >> 4 }}"\n{@d::0..255} => "{{ $0 | hi }}"'
    assert _run(src, "255") == "015"  # 255 >> 4 = 15, kept at the 3-symbol LHS width


def test_value_filter_chaining():
    # `x | a | b` applies left-to-right; both are band-preserving value filters.
    src = (
        '@double = "{{ $ * 2 }}"\n'
        '@inc = "{{ $ + 1 }}"\n'
        '{@d::0..255} => "{{ $0 | double | inc }}"'
    )
    assert _run(src, "09") == "19"  # (9*2)+1


# ── Document-shaped filters run their pipeline over the subject text ───────────


def test_document_filter_wraps_subject():
    # A body with literal decoration is document-shaped: spliced over the text.
    src = '@wrap = "<{{$}}>"\n!{ }[1..] => "{{ $ | wrap }}"'
    assert _run(src, "hi there") == "<hi> <there>"


def test_document_filter_query_pipeline():
    # A `=>` body is document-shaped: `@rstrip` runs over the whole matched subject.
    src = '@rs = {{@s}}[1..]{@doc_end} => ""\n!{Q}[1..] => "[{{ $ | rs }}]"'
    assert _run(src, "hi   ") == "[hi]"  # trailing whitespace stripped by the filter


# ── Shipped filters, now L2 ────────────────────────────────────────────────────


def test_trim_is_str_strip():
    src = '!{Q}[1..] => "[{{ $ | trim }}]"'
    assert _run(src, "  \t a b \n ") == "[a b]"


def test_indent_tabs_every_line():
    src = '!{Q}[1..] => "{{ $ | indent }}"'
    assert _run(src, "a\nb") == "\ta\n\tb"


# ── Errors ─────────────────────────────────────────────────────────────────────


def test_unknown_filter_is_a_compile_error():
    with pytest.raises(
        CompileError, match="Unknown template filter or alphabet: 'nope'"
    ):
        parser.compile_script('!{x}[1..] => "{{ $ | nope }}"')
