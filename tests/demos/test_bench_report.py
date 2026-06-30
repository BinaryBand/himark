"""The HMK-self-hosted benchmark-report builder (`himark/scripts/bench_report.hmk`).

Turns the JSON `tests/benchmarks/bench.py` writes into a Markdown report: an H1, a
metadata bullet list, and one table row per result (the per-iteration `times_ms`
array dropped). We pin each pass (title, metadata, table header, the object->row
collapse) and the end-to-end render of a small fixture, including the awkward
cases: a final object with no trailing comma, `slash/dash` and underscore workload
names, and JSON's trailing-zero-stripped numbers (`4.32`, not `4.320`).
"""

from pathlib import Path

from himark import engine, parser

SCRIPT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "bench_report.hmk"
RESOURCES = Path(__file__).resolve().parent / "resources"
OUTPUT = Path(__file__).resolve().parent / "output"
_PIPELINE = parser.load_script(str(SCRIPT))


def report(src: str) -> str:
    return engine.run_pipeline(_PIPELINE, src)


# A one-result document, the smallest input that exercises every pass. The single
# object is the last (and only) element, so it carries no trailing comma.
def _doc(body: str) -> str:
    return (
        "{\n"
        '  "timestamp": "2026-01-02T03:04:05.000000+00:00",\n'
        '  "n": 5,\n'
        '  "warmup": 2,\n'
        '  "results": [\n'
        f"{body}"
        "  ]\n"
        "}\n"
    )


def _obj(
    engine_: str,
    workload: str,
    mean: str,
    mn: str,
    mx: str,
    stdev: str,
    last: bool,
) -> str:
    comma = "" if last else ","
    return (
        "    {\n"
        f'      "engine": "{engine_}",\n'
        f'      "workload": "{workload}",\n'
        f'      "mean_ms": {mean},\n'
        f'      "min_ms": {mn},\n'
        f'      "max_ms": {mx},\n'
        f'      "stdev_ms": {stdev},\n'
        '      "times_ms": [\n'
        f"        {mean},\n        {mn},\n        {mx}\n"
        "      ]\n"
        f"    {chr(125)}{comma}\n"
    )


# ── Header passes ─────────────────────────────────────────────────────────────


def test_title_and_metadata():
    out = report(_doc(_obj("go", "btc_extract", "4.0", "3.9", "4.1", "0.1", last=True)))
    assert out.startswith(
        "# Benchmark Results\n\n"
        "- **Generated:** 2026-01-02T03:04:05.000000+00:00\n"
        "- **Iterations (n):** 5\n"
        "- **Warmup:** 2\n\n"
    )


def test_table_header_and_alignment_rule():
    out = report(_doc(_obj("go", "btc_extract", "4.0", "3.9", "4.1", "0.1", last=True)))
    assert (
        "| Engine | Workload | Mean (ms) | Min (ms) | Max (ms) | Stdev (ms) |\n"
        "| --- | --- | ---: | ---: | ---: | ---: |\n"
    ) in out


# ── The object -> row collapse ────────────────────────────────────────────────


def test_object_becomes_one_row_times_dropped():
    out = report(
        _doc(_obj("cpp", "md_html", "9.09", "7.86", "11.5", "1.43", last=True))
    )
    assert out.rstrip("\n").endswith("| cpp | md_html | 9.09 | 7.86 | 11.5 | 1.43 |")
    # The per-iteration array never reaches the output.
    assert "times_ms" not in out
    assert "[" not in out


def test_slash_and_dash_workload_name_survives():
    out = report(
        _doc(_obj("rust", "bs/rev-200", "113", "107", "117", "5.4", last=True))
    )
    assert "| rust | bs/rev-200 | 113 | 107 | 117 | 5.4 |" in out


def test_multiple_objects_one_row_each():
    body = _obj("go", "a", "1.0", "1.0", "1.0", "0.0", last=False) + _obj(
        "rust", "b", "2.0", "2.0", "2.0", "0.0", last=True
    )
    out = report(_doc(body))
    rows = [ln for ln in out.splitlines() if ln.startswith("| ") and "---" not in ln]
    assert rows[-2:] == [
        "| go | a | 1.0 | 1.0 | 1.0 | 0.0 |",
        "| rust | b | 2.0 | 2.0 | 2.0 | 0.0 |",
    ]


# ── No JSON scaffolding leaks through ─────────────────────────────────────────


def test_json_scaffolding_is_fully_stripped():
    out = report(_doc(_obj("go", "x", "1.0", "1.0", "1.0", "0.0", last=True)))
    for leak in ('"engine"', '"results"', '"timestamp"', "]", "}", "{"):
        assert leak not in out
    assert out.endswith("|\n")  # ends on the last table row, nothing after


# ── End-to-end on the committed fixture ───────────────────────────────────────


def test_fixture_renders_expected_report():
    out = report((RESOURCES / "bench_results.json").read_text("utf-8"))
    assert out == (
        "# Benchmark Results\n\n"
        "- **Generated:** 2026-06-30T16:42:16.467599+00:00\n"
        "- **Iterations (n):** 3\n"
        "- **Warmup:** 1\n\n"
        "| Engine | Workload | Mean (ms) | Min (ms) | Max (ms) | Stdev (ms) |\n"
        "| --- | --- | ---: | ---: | ---: | ---: |\n"
        "| cpp | btc_extract | 4.32 | 3.888 | 5.411 | 0.621 |\n"
        "| rust | bs/rev-200 | 113.336 | 107.15 | 117.234 | 5.417 |\n"
    )


# Runbook: write the rendered report to `tests/demos/output` for manual inspection
if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    src = (RESOURCES / "bench_results.json").read_text("utf-8")
    (OUTPUT / "bench_report.md").write_text(report(src), "utf-8")
    print(f"Wrote bench_report.md to {OUTPUT}")
