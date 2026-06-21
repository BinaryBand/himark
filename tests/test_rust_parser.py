"""Tests for the native (Rust) parser backend (`himark/parser/rust.py`).

`RustParser` must produce trees that are semantically identical to `PythonParser`
— the engine is backend-agnostic and must work identically regardless of which
parser produced the tree.  These tests verify parity on a spread of patterns and
confirm the seam swap API works correctly.  Skip when the extension isn't built.
"""

import pytest

from himark import parser
from himark.engine import execute, find
from himark.parser import PythonParser, RustParser, using_parser
from himark.parser.rust import RUST_PARSER_AVAILABLE

pytestmark = pytest.mark.skipif(
    not RUST_PARSER_AVAILABLE, reason="himark_rs not built"
)

PY = PythonParser()
RS = RustParser()


# ── Node-level parity ─────────────────────────────────────────────────────────


def _tree(parser_impl, source):
    with using_parser(parser_impl):
        return parser.parse(source)


def _trees_equal(a, b):
    """Structural equality of two tree lists (ignoring fixed_point)."""
    import json
    from himark.parser.rust import _from_json_root
    import himark_rs as rs_mod

    # Serialise both via the Rust JSON representation and compare
    rs_json = rs_mod.parse(source if (source := None) else source)  # noqa: F821
    # Simpler: compare repr of the dataclass trees
    return repr(a) == repr(b)


PATTERNS = [
    r"{a..z}[1..]",
    r"{0:@d:255}",
    r"{!\ }[1..]",
    r"{{@d}}[1..]",
    r"{cat,dog}",
    r"{{a,A},{b,B},{c,C}}[3]",
    r"{@^}{!\n}[1..]",
    r"{abc}{$0}",
    r"{1$2.3}",
    r"{#0}",
    r"{!{x,y,z}}[1..]",
    r"{0:@d:255}{.}{0:@d:255}{.}{0:@d:255}{.}{0:@d:255}",
    r'{!\ }[1..] => "<b>{{.}}</b>"',
]


@pytest.mark.parametrize("source", PATTERNS)
def test_rust_parser_tree_matches_python(source):
    py_trees = PY.parse(source)
    rs_trees = RS.parse(source)
    assert len(py_trees) == len(rs_trees), (
        f"Step count mismatch for {source!r}: "
        f"python={len(py_trees)} rust={len(rs_trees)}"
    )
    for i, (py_root, rs_root) in enumerate(zip(py_trees, rs_trees)):
        assert repr(py_root) == repr(rs_root), (
            f"Tree mismatch at step {i} for {source!r}:\n"
            f"  python: {py_root!r}\n"
            f"  rust:   {rs_root!r}"
        )


# ── End-to-end execution parity ───────────────────────────────────────────────


EXEC_CASES: list[tuple[str, str, list[str]]] = [
    (r"{!\ }[1..]", "hello world foo", ["hello", "world", "foo"]),
    # Value range: greedy decimal match up to the written width of 255 (3 digits)
    (r"{0:@d:255}", "go 42 200 999 7 here", ["42", "200", "99", "9", "7"]),
    # Homogeneous repetition: {a..z}[3] = three of the *same* letter (aaa, bbb, ...)
    (r"{a..z}[3]", "aaa bbb zzz cat", ["aaa", "bbb", "zzz"]),
    (r"{{@d}}[1..]", "abc 123 def 456 ghi", ["123", "456"]),
    (r"{cat,dog}", "I have a dog and a cat", ["dog", "cat"]),
]


@pytest.mark.parametrize("pattern,text,expected", EXEC_CASES)
def test_rust_parser_execution_matches_expected(pattern, text, expected):
    with using_parser(RS):
        steps = parser.parse(pattern)
    result = execute(steps, text)
    assert result == expected


@pytest.mark.parametrize("pattern,text,expected", EXEC_CASES)
def test_rust_parser_matches_python_parser_execution(pattern, text, expected):
    py_steps = PY.parse(pattern)
    rs_steps = RS.parse(pattern)
    assert execute(py_steps, text) == execute(rs_steps, text)


# ── Seam API ──────────────────────────────────────────────────────────────────


def test_set_parser_swaps_backend():
    prev = parser.get_parser()
    try:
        parser.set_parser(RS)
        assert parser.get_parser() is RS
        steps = parser.parse(r"{a..z}[1..]")
        assert len(steps) == 1
    finally:
        parser.set_parser(prev)


def test_using_parser_context_manager():
    assert isinstance(parser.get_parser(), PythonParser)
    with using_parser(RS) as active:
        assert active is RS
        assert parser.get_parser() is RS
        steps = parser.parse(r"{!\ }[1..]")
        assert execute(steps, "hi there") == ["hi", "there"]
    assert isinstance(parser.get_parser(), PythonParser)


def test_using_parser_restores_on_error():
    assert isinstance(parser.get_parser(), PythonParser)
    try:
        with using_parser(RS):
            raise RuntimeError("deliberate")
    except RuntimeError:
        pass
    assert isinstance(parser.get_parser(), PythonParser)


# ── Error propagation ─────────────────────────────────────────────────────────


def test_rust_parser_raises_compile_error_on_bad_input():
    from himark.models.exceptions import CompileError

    with pytest.raises(CompileError):
        RS.parse("{unclosed")


# ── Multi-step chains ─────────────────────────────────────────────────────────


def test_rust_parser_chain_step_count():
    steps = RS.parse(r"{!\ }[1..] => <b>{{.}}</b>")
    assert len(steps) == 2


def test_rust_parser_chain_execution():
    steps = RS.parse(r'{!\ }[1..] => "<b>{{.}}</b>"')
    from himark.engine import splice
    result = splice(steps, "hello world")
    assert result == "<b>hello</b> <b>world</b>"
