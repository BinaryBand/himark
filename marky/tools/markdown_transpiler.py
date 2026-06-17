#!/usr/bin/env python3
"""Transpile docs/HMK.md to downloads/HMK.html by running a list of Himark commands.

A bare experiment: read the document and splice each Himark statement over it in
turn. The experimental core has no separators or numbered captures, so this is
deliberately minimal — the HTML-escape pass, which only needs constant templates.
Richer block/inline rules await the spec's North Star section (currently a TODO
in docs/HMK.md).

The fixed pipeline is parsed once and cached to a portable `.hmkc` artifact (see
`marky.tools.precompiled`); later runs load it and skip parsing. The artifact is
rebuilt whenever this file — the COMMANDS source — is newer, so editing the
commands regenerates it.

Run:  python -m marky.tools.markdown_transpiler   # write downloads/HMK.html
"""

from pathlib import Path

import typer

from marky.tools import precompiled

ROOT = Path(__file__).resolve().parents[2]
DOWNLOADS = ROOT / "downloads"
SRC = ROOT / "docs" / "HMK.md"
DST = DOWNLOADS / "HMK.html"
ARTIFACT = DOWNLOADS / "markdown.hmkc"  # in downloads/ so it's already git-ignored

COMMANDS = [
    r"{\&} => &amp;",  # escape & first, or it re-escapes the entities below
    r"{\<} => &lt;",  # escape <
    r"{\>} => &gt;",  # escape >
]


def _pipeline() -> precompiled.Pipeline:
    """The compiled COMMANDS pipeline, loaded from the cached artifact. Rebuilt
    when missing or older than this source file (a make-style freshness check)."""
    if (
        not ARTIFACT.exists()
        or ARTIFACT.stat().st_mtime < Path(__file__).stat().st_mtime
    ):
        DOWNLOADS.mkdir(parents=True, exist_ok=True)
        pipeline = precompiled.compile_pipeline(COMMANDS)
        precompiled.dump(pipeline, ARTIFACT)
        return pipeline
    return precompiled.load(ARTIFACT)


def transpile(text: str) -> str:
    return precompiled.apply(_pipeline(), text)


def transpile_cmd() -> None:
    """Transpile docs/HMK.md to downloads/HMK.html."""
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    DST.write_text(transpile(SRC.read_text("utf-8")), "utf-8")
    typer.echo(f"wrote {DST.relative_to(ROOT)}")


if __name__ == "__main__":
    typer.run(transpile_cmd)
