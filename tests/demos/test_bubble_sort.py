"""End-to-end tests for the bubble-sort demo (`himark/scripts/bubble_sort.hmk`).

The script sorts a comma-separated list of single base-10 digits with no loop and
no arithmetic: each *sweep* is nine range-based compare-and-swap rules, and the
sweep is unrolled to a fixed budget (9 sweeps — enough for any 10-value list).
These tests pin the sort on the shipped sample and a worst-case reversed list,
and check that already-sorted input is a no-op.
"""

from pathlib import Path

from himark.tools import precompiled

SCRIPT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "bubble_sort.hmk"
RESOURCES = Path(__file__).resolve().parent / "resources"
OUTPUT = Path(__file__).resolve().parent / "output"
_PIPELINE = precompiled.compile_pipeline(precompiled.load_script(SCRIPT))


def sort(text: str) -> str:
    return precompiled.apply(_PIPELINE, text)


def test_sorts_the_sample():
    assert sort("5,2,8,1,9,3,7,0,6,4") == "0,1,2,3,4,5,6,7,8,9"


def test_sorts_worst_case_reversed_ten():
    assert sort("9,8,7,6,5,4,3,2,1,0") == "0,1,2,3,4,5,6,7,8,9"


def test_already_sorted_is_unchanged():
    assert sort("0,1,2,3,4,5,6,7,8,9") == "0,1,2,3,4,5,6,7,8,9"


def test_duplicates_and_short_lists():
    assert sort("3,3,1,2,1") == "1,1,2,3,3"
    assert sort("2,1") == "1,2"
    assert sort("7") == "7"


def test_trailing_newline_is_preserved():
    assert sort("3,1,2\n") == "1,2,3\n"


# Runbook: sort the sample file into `tests/demos/output` for manual inspection.
if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    src = (RESOURCES / "numbers.txt").read_text("utf-8")
    result = sort(src)
    (OUTPUT / "sorted_numbers.txt").write_text(result, "utf-8")
    print(src.strip(), "->", result.strip())
