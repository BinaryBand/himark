"""End-to-end tests for the title-reconciliation demo (`himark/scripts/dedup.hmk`).

The script reconciles a podcast's two title columns (its YouTube episode titles
beside its RSS-feed titles, in a different order and surface text) into one CSV:
a matched episode shares a row — its YouTube form beside its feed form — and an
unmatched title keeps its own row with the other cell blank.

The match is HMK's **self-reference equality**: each title is keyed by its
normalized form (the YouTube-only `Episode NNN: ` counter stripped), and two lines
with the same key — one per column — are merged by `{$0}` matching the captured
key, re-spliced to a fixed point by `<=>` (both column orders). A MASK pass shields
commas inside quoted fields, restored at the end.

These tests pin each pass and the merge on small crafted inputs — cross-column
(both orders), unmatched fall-through, quoted fields, and the case/punctuation
near-misses the script documents as out of scope — then a slice of the real
`podcasts.csv` (fast on any backend). The cross-document self-reference scan is
~quadratic, so a 24-row slice is used for fast testing.
"""

import csv
import io
from pathlib import Path

from contextlib import nullcontext

import pytest

# (no Rust backend — Python only)
from himark import engine, parser

SCRIPT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "dedup.hmk"
RESOURCES = Path(__file__).resolve().parent / "resources"
OUTPUT = Path(__file__).resolve().parent / "output"
_PIPELINE = parser.load_script(str(SCRIPT))

HEADER = "youtube_title,podcast_title\n"


def dedup(text: str) -> str:
    return engine.run_pipeline(_PIPELINE, text)


def rows(text: str) -> list[list[str]]:
    """Reconcile `text` and parse the result as CSV (so quoted fields are
    honoured), header dropped."""
    return list(csv.reader(io.StringIO(dedup(text))))[1:]


def test_keeps_the_header():
    assert (
        dedup(HEADER + "Alpha,Beta\n").splitlines()[0] == "youtube_title,podcast_title"
    )


def test_matches_align_on_one_row_cross_column():
    # YouTube row 1's episode reappears as row 2's feed title — equal only once
    # the `Episode 791: ` counter is stripped — so they reconcile onto one row.
    src = (
        HEADER
        + "Episode 791: The Murder of Martha Moxley (Part 1),Some Other Feed\n"
        + "Episode 788: A Different Case,The Murder of Martha Moxley (Part 1)\n"
    )
    assert [
        "Episode 791: The Murder of Martha Moxley (Part 1)",
        "The Murder of Martha Moxley (Part 1)",
    ] in rows(src)


def test_matches_when_feed_appears_before_youtube():
    # The twin can sit *above* the YouTube row; the second `<=>` rule (P before Y)
    # catches that order.
    src = HEADER + ",The Big Case\nEpisode 5: The Big Case,Other\n"
    assert ["Episode 5: The Big Case", "The Big Case"] in rows(src)


def test_unmatched_youtube_title_keeps_its_own_row():
    src = HEADER + "Episode 7: Lonely Episode,Unrelated Feed\n"
    out = rows(src)
    assert ["Episode 7: Lonely Episode", ""] in out
    assert ["", "Unrelated Feed"] in out


def test_empty_youtube_cell_becomes_a_feed_only_row():
    # The tail of the real file is feed-only rows like `,Joel Rifkin`.
    assert rows(HEADER + ",Joel Rifkin\n") == [["", "Joel Rifkin"]]


def test_strips_listener_tales_prefix_to_match():
    src = HEADER + "Listener Tales 110: Spooky Playdates,X\nY,Spooky Playdates\n"
    assert ["Listener Tales 110: Spooky Playdates", "Spooky Playdates"] in rows(src)


def test_quoted_field_with_embedded_comma_stays_one_valid_cell():
    # The MASK pass shields the interior comma, so a quoted comma-bearing title
    # stays a single field on both sides — they match, and the output is valid CSV
    # (the comma is restored inside the quotes, not as a column break).
    src = (
        HEADER
        + '"A Tale, With a Comma",Some Feed\n'
        + 'Other Title,"A Tale, With a Comma"\n'
    )
    out = rows(src)
    assert all(len(r) == 2 for r in out)  # every row stays two columns
    assert ["A Tale, With a Comma", "A Tale, With a Comma"] in out


def test_near_miss_is_left_distinct():
    # Case/punctuation differences are not normalized away (documented scope), so
    # the two variants stay on separate rows rather than reconciling.
    src = (
        HEADER
        + "Episode 9: MAY BONUS EPISODE- Breaking Dawn,X\nY,May Bonus Episode: Breaking Dawn\n"
    )
    out = rows(src)
    assert ["Episode 9: MAY BONUS EPISODE- Breaking Dawn", ""] in out
    assert ["", "May Bonus Episode: Breaking Dawn"] in out


def test_real_slice_reconciles_a_known_twin():
    # YouTube row 1's "Martha Moxley (Part 1)" twins a later (quoted-row) feed
    # title; after MASK + normalization they reconcile onto one row.
    src = "".join(
        (RESOURCES / "podcasts.csv").read_text("utf-8").splitlines(keepends=True)[:9]
    )
    out = rows(src)
    assert [
        "Episode 791: The Murder of Martha Moxley (Part 1)",
        "The Murder of Martha Moxley (Part 1)",
    ] in out
    # Every output row has exactly two cells (valid 2-column CSV).
    assert all(len(r) == 2 for r in out)


def _parse_csv(text: str) -> list[list[str]]:
    """CSV-parse `text` directly (no second dedup pass, unlike `rows`)."""
    return list(csv.reader(io.StringIO(text)))



# ── Runbook ───────────────────────────────────────────────────────────────────
# Run this file directly to reconcile the real CSV into
# `tests/demos/output/deduped_titles.csv` for manual inspection. The whole file is
# only feasible on the native backend (the self-reference scan is ~quadratic), so
# this uses RustEngine when built, else a fast slice on Python.
if __name__ == "__main__":
    import time

    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows_in = (RESOURCES / "podcasts.csv").read_text("utf-8").splitlines(keepends=True)
    src = "".join(rows_in[:25])
    label = "python, 24-row slice"
    ctx = nullcontext()
    with ctx:
        t0 = time.perf_counter()
        result = dedup(src)
        elapsed = time.perf_counter() - t0
    (OUTPUT / "deduped_titles.csv").write_text(result, "utf-8")
    matched = sum(1 for r in _parse_csv(result)[1:] if len(r) == 2 and r[0] and r[1])
    print(
        f"Wrote deduped_titles.csv to {OUTPUT} ({label}, {elapsed:.1f}s): {matched} reconciled pairs"
    )
