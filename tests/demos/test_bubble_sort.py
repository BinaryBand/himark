"""End-to-end tests for the bubble-sort demo (`himark/scripts/bubble_sort.hmk`).

The script sorts a comma-separated list of base-10 values with no loop and no
arithmetic. The whole comparison is one range — a value bound whose ceiling is a
**reference** to the pair's first value (`{@d::0..$0}` matches "≤ a"), which is
width-agnostic. A comma-terminating PAD makes every value a complete token, the
SORT sweep uses the `<=>` fixed-point arrow (re-spliced until sorted, for a list
of any length), and an UNPAD strips the pad. These tests pin the sort on the
sample, a long reversed list, mixed widths, duplicates, and no trailing newline.
"""

from pathlib import Path

from himark import engine, parser

SCRIPT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "bubble_sort.hmk"
RESOURCES = Path(__file__).resolve().parent / "resources"
OUTPUT = Path(__file__).resolve().parent / "output"
_PIPELINE = parser.load_script(str(SCRIPT))


def sort(text: str) -> str:
    return engine.run_pipeline(_PIPELINE, text)


def test_sorts_the_sample():
    assert sort("42,5,317,8,90,256,73,1,640,29\n") == "1,5,8,29,42,73,90,256,317,640\n"


def test_mixed_widths_compare_by_value_not_lexicographically():
    # 9 < 90 < 100 by value (a naive lexicographic sort would put 100 before 90).
    assert sort("100,9,90\n") == "9,90,100\n"


def test_long_reversed_list_no_budget_limit():
    # 20 values reversed — past any fixed budget; the `<=>` fixed point sorts a
    # list of any length.
    vals = list(range(200, 0, -10))
    src = ",".join(str(v) for v in vals) + "\n"
    assert sort(src) == ",".join(str(v) for v in sorted(vals)) + "\n"


def test_already_sorted_is_unchanged():
    assert sort("1,5,8,42,640\n") == "1,5,8,42,640\n"


def test_duplicates_and_short_lists():
    assert sort("30,7,30,7,12\n") == "7,7,12,30,30\n"
    assert sort("2,1\n") == "1,2\n"
    assert sort("7\n") == "7\n"


def test_works_without_trailing_newline():
    assert sort("30,4,100,7") == "4,7,30,100"


def test_swap_reactivates_the_pair_to_its_left():
    # A swap can make the pair to its *left* newly out of order, so the fixed point
    # must re-examine positions before its last change. (An incremental sweep that
    # skipped the unchanged prefix would settle early here — `2,3,1` -> `2,1,3` — so
    # this pins that the prefix is never skipped.)
    assert sort("2,3,1") == "1,2,3"
    assert sort("5,4,3,2,1") == "1,2,3,4,5"


# Runbook: sort the sample file into `tests/demos/output` for manual inspection.
if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    src = (RESOURCES / "numbers.txt").read_text("utf-8")
    result = sort(src)
    (OUTPUT / "sorted_numbers.txt").write_text(result, "utf-8")
    print(src.strip(), "->", result.strip())
