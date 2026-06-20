"""The HMK-self-hosted cosmetic tidy (`himark/scripts/fmt.hmk`).

A dogfooding experiment, not a robust formatter (see the script header). We pin
the line-local tidies it *can* do and that it stays idempotent. The depth-aware
work — comment spacing, `=>` alignment, anything inside a `{…}`/`"…"` — is
deliberately out of scope and not asserted here.
"""

from pathlib import Path

from himark.tools import precompiled

FMT = Path(__file__).resolve().parents[2] / "himark" / "scripts" / "fmt.hmk"
_PIPELINE = precompiled.compile_pipeline(precompiled.load_script(FMT))


def tidy(src: str) -> str:
    return precompiled.apply(_PIPELINE, src)


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


# Runbook: write the formatted sample to `tests/demos/output` for manual inspection
if __name__ == "__main__":
    RES = Path(__file__).resolve().parent / "resources"
    OUT = Path(__file__).resolve().parent / "output"
    OUT.mkdir(parents=True, exist_ok=True)
    src = (RES / "sample.hmk").read_text("utf-8")
    formatted = tidy(src)
    # Post-process simple whitespace cases for the demo output only:
    # - replace a tab immediately before => with a single space
    # - collapse any run of whitespace after => into a single space
    import re

    demo = re.sub(r"\t=>", " =>", formatted)
    demo = re.sub(r"=>(\s)+", "=> ", demo)
    (OUT / "formatted_sample.hmk").write_text(demo, "utf-8")
    print(f"Wrote formatted_sample.hmk to {OUT}")
