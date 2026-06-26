"""Tests for the native (Rust) backend (`himark/engine/backend/rust.py`).

`RustEngine` runs the structural subset of the language in Rust and falls back to
`PythonEngine` for everything else, so its results must match the Python backend
exactly. These tests pin that parity on a spread of supported patterns (asserting
they actually take the Rust path), confirm value/reference patterns fall back, and
check the `dedup.hmk` pipeline is byte-identical across backends. They skip when
the extension isn't built.

To exercise the *whole* suite under Rust: `HIMARK_RUST=1 pytest` (see conftest).
"""

import pytest

from himark import parser
from himark.engine import PythonEngine, RustEngine, using_backend
from himark.engine.backend.rust import RUST_AVAILABLE
from himark.tools import precompiled

pytestmark = pytest.mark.skipif(not RUST_AVAILABLE, reason="himark_rs not built")

PY = PythonEngine()


def _matches(engine, pattern: str, text: str):
    compiled = engine.compile(parser.parse(pattern)[0])
    return engine.run(compiled, text)


def _norm(ms):
    """A comparable view of a match list: text, span, and capture shape. The
    capture's value alphabet is reduced to present/absent — distinct `Alphabet`
    instances are equal in content but not by identity, and the Rust subset never
    produces one anyway (only the Python fallback does, for `{A:x..y}` bounds)."""
    return [
        (
            m.text,
            m.start,
            m.end,
            [(c.text, c.span, c.reps, c.alphabet is not None) for c in m.captures],
        )
        for m in ms
    ]


# Patterns inside the Rust subset (must take the Rust path *and* match Python).
SUPPORTED = [
    (r"{a..z}[1..]", "hello world 42"),
    (r"{{@d}}[1..]", "ab123cd45ef"),
    (r"{@<}{!\n}[1..]{\n}", "one\ntwo\nthree\n"),
    (r"{!{x,y}}[1..]", "abxcdyef"),
    (r"{cat,dog}", "a dog and a cat"),
    (r"{{a,A},{c,C}}[2]", "aA Cc xx aa Ca"),
    (r"{abc}{$0}[0..]", "abcabcabc and abc"),  # back-reference repetition
    (r"{@<}{!{¤,\n}}[1..]{¤}{!\n}[1..]{\n}", "key¤val\nk2¤v2\n"),  # dedup-shaped
]


@pytest.mark.parametrize("pattern,text", SUPPORTED)
def test_rust_path_matches_python(pattern, text):
    rs = RustEngine()
    tag, _ = rs.compile(parser.parse(pattern)[0])
    assert tag == "rs", f"{pattern!r} should run on Rust, fell back to {tag}"
    assert _norm(_matches(rs, pattern, text)) == _norm(_matches(PY, pattern, text))


def test_static_value_bound_falls_back_and_still_matches():
    rs = RustEngine()
    tag, _ = rs.compile(parser.parse(r"{@d::0..255}")[0])
    assert tag == "py"  # value arithmetic is out of subset
    text = "go 42 200 999 7 here"
    assert _norm(_matches(rs, r"{@d::0..255}", text)) == _norm(
        _matches(PY, r"{@d::0..255}", text)
    )


def test_reference_value_bound_falls_back():
    # bubble_sort.hmk's compare-and-swap uses {@d::0..$0} (a dynamic value range).
    rs = RustEngine()
    tag, _ = rs.compile(parser.parse(r"{{@d}}[1..]\,{@d::0..$0}")[0])
    assert tag == "py"


def test_dedup_pipeline_is_identical_across_backends():
    rows = open("tests/demos/resources/podcasts.csv").read().splitlines(keepends=True)
    src = "".join(rows[:25])

    def run(engine):
        with using_backend(engine):
            pipe = precompiled.compile_pipeline(
                precompiled.load_script("himark/scripts/dedup.hmk")
            )
            return precompiled.apply(pipe, src)

    assert run(RustEngine()) == run(PY)


# ── Benchmark runbook (not a hard assertion) ──────────────────────────────────
if __name__ == "__main__":
    import time

    rows = open("tests/demos/resources/podcasts.csv").read().splitlines(keepends=True)
    src = "".join(rows[:60])  # a slice big enough to show the gap, fast enough to wait

    def bench(engine):
        with using_backend(engine):
            pipe = precompiled.compile_pipeline(
                precompiled.load_script("himark/scripts/dedup.hmk")
            )
            t0 = time.perf_counter()
            out = precompiled.apply(pipe, src)
        return time.perf_counter() - t0, out

    pt, po = bench(PY)
    rt, ro = bench(RustEngine())
    assert po == ro, "outputs diverged!"
    print(
        f"dedup on 60 rows:  python {pt:.2f}s   rust {rt:.2f}s   speedup {pt / rt:.1f}x"
    )
