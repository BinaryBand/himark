"""Golden-corpus behavioural pin.

This is the safety net for the architectural roadmap in the North Star plan: it
snapshots *what HMK does today* so that any internal refactor (a `Program` IR, a
bytecode VM, moving execution between layers) can be proven behaviour-preserving
by a byte-for-byte comparison, independent of the unit tests.

Two corpora, both run on the **default** backend (deterministic, always present):

  * **Pipelines** — each shipped `.hmk` demo script applied to its real input
    resource; the spliced document is compared to a stored `golden/pipelines/*.out`.
  * **Matcher** — a broad spread of standalone patterns (every language feature:
    ranges, value bounds, unions, complements/breaks, congruence, het objects,
    anchors, back/count references, repetition, grouping braces) matched against
    fixed text; the full `Match` tree (text, spans, reps, sub-captures) is compared
    to `golden/matcher.json`.

Regenerate after an *intended* behaviour change:  `HIMARK_UPDATE_GOLDEN=1 pytest
tests/test_golden.py`  — then eyeball the diff before committing.
"""

import json
import os
from pathlib import Path

import pytest

from himark import parser
from himark.models.compiled import Program
from himark.engine import find_matches
from himark import engine

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "himark" / "scripts"
RESOURCES = Path(__file__).resolve().parent / "demos" / "resources"
GOLDEN = Path(__file__).resolve().parent / "golden"

_UPDATE = bool(os.environ.get("HIMARK_UPDATE_GOLDEN"))


# ── Pipeline corpus ───────────────────────────────────────────────────────────
# (name, script, input resource, slice) — `slice` trims the input so every case
# stays fast on the pure-Python backend (the dedup self-reference scan is ~quadratic).
def _whole(t: str) -> str:
    return t


def _strip(t: str) -> str:
    return t.strip()


def _head9(t: str) -> str:
    return "".join(t.splitlines(keepends=True)[:9])


PIPELINES = [
    ("btc_extract", "btc_extract.hmk", "addresses.txt", _whole),
    ("bubble_sort", "bubble_sort.hmk", "numbers.txt", _whole),
    ("hmk_format", "format_hmk.hmk", "sample.hmk", _whole),
    ("md_format", "format_md.hmk", "messy.md", _whole),
    ("html_format", "format_html.hmk", "sample.html", _strip),
    ("md_html", "md_html.hmk", "sample.md", _whole),
    ("dedup", "dedup.hmk", "podcasts.csv", _head9),
]


@pytest.mark.parametrize(
    "name,script,resource,slice_", PIPELINES, ids=[p[0] for p in PIPELINES]
)
def test_pipeline_golden(name, script, resource, slice_):
    pipeline = parser.load_script(str(SCRIPTS / script))
    src = slice_((RESOURCES / resource).read_text("utf-8"))
    out = engine.run_pipeline(pipeline, src)

    path = GOLDEN / "pipelines" / f"{name}.out"
    if _UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(out, "utf-8")
        return
    assert path.exists(), f"missing golden {path} — run HIMARK_UPDATE_GOLDEN=1 pytest"
    assert out == path.read_text("utf-8"), (
        f"{name} pipeline output drifted from golden; "
        f"if intended, regenerate with HIMARK_UPDATE_GOLDEN=1"
    )


# ── Matcher corpus ────────────────────────────────────────────────────────────
# (id, pattern, text) — one row per language feature, so a refactor that breaks
# any construct fails here with a precise capture-tree diff.
MATCHER = [
    ("char_range_run", r"{a..z}[1..]", "hello world 42"),
    ("het_digit_run", r"{{@d}}[1..]", "ab123cd45ef"),
    ("value_bound", r"{@d::0..255}", "go 42 200 999 7 here"),
    ("dyn_value_range", r"{{@d}}[1..]\,{@d::0..$0}", "9,4 and 3,7"),
    ("union_strings", r"{cat,dog}", "a dog and a cat"),
    ("congruence_fold", r"{{a,A},{c,C}}[2]", "aA Cc xx aa Ca"),
    ("back_ref_repeat", r"{abc}{$0}[0..]", "abcabcabc and abc"),
    ("count_ref", r"{a}[2..]{-}[#0]", "aaa--- then aa--"),
    ("complement_break", r"!{x,y}[1..]", "abxcdyef"),
    ("multichar_break", r"{<!--}!{-->}[1..]{-->}", "<!--note-->tail"),
    ("anchored_line", r"{@<}!{\n}[1..]{\n}", "one\ntwo\nthree\n"),
    ("value_range_uni", r"{aa..zz}", "  aa zz mid"),
    ("grouping_subs", r"{of {black} {quartz}}", "of black quartz here"),
    (
        "captures_example",
        r"{#}[1..]{ }{Sphinx}{ }{of {black} {quartz}}",
        "### Sphinx of black quartz, judge my vow!",
    ),
    ("exclusion_range", r"{a..z,!{m..p}}[1..]", "abcmnopxyz"),
]


def _norm_capture(c) -> dict:
    return {
        "text": c.text,
        "span": list(c.span),
        "reps": list(c.reps),
        "alphabet": c.alphabet is not None,
        "subs": [
            {"text": s.text, "span": list(s.span), "reps": list(s.reps)} for s in c.subs
        ],
    }


def _norm_matches(pattern: str, text: str) -> dict:
    tree = parser.parse(pattern)[0]
    assert isinstance(tree, Program)
    matches = find_matches(tree, text)
    return {
        "pattern": pattern,
        "text": text,
        "matches": [
            {
                "text": m.text,
                "span": [m.start, m.end],
                "captures": [_norm_capture(c) for c in m.captures],
            }
            for m in matches
        ],
    }


_MATCHER_GOLDEN = GOLDEN / "matcher.json"


def _build_matcher_corpus() -> dict:
    return {mid: _norm_matches(pat, txt) for mid, pat, txt in MATCHER}


def test_matcher_golden_corpus():
    built = _build_matcher_corpus()
    if _UPDATE:
        _MATCHER_GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _MATCHER_GOLDEN.write_text(
            json.dumps(built, indent=2, ensure_ascii=False) + "\n", "utf-8"
        )
        return
    assert _MATCHER_GOLDEN.exists(), (
        f"missing golden {_MATCHER_GOLDEN} — run HIMARK_UPDATE_GOLDEN=1 pytest"
    )
    expected = json.loads(_MATCHER_GOLDEN.read_text("utf-8"))
    # Compare per-id so a drift names the exact pattern that changed.
    assert set(built) == set(expected), "matcher corpus ids changed"
    for mid in MATCHER:
        key = mid[0]
        assert built[key] == expected[key], (
            f"matcher behaviour for {key!r} ({mid[1]!r}) drifted from golden; "
            f"if intended, regenerate with HIMARK_UPDATE_GOLDEN=1"
        )
