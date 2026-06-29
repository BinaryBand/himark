#!/usr/bin/env python3
"""Run an HMK `.hmk` script over a text document.

The script is a pipeline of HMK statements (see `himark/scripts/md_html.hmk` for a
Markdown → HTML example); each is spliced over the document in turn. The parsed
pipeline is cached to a portable `.hmkc` artifact in `downloads/` and rebuilt when
the script file changes, so repeat runs skip parsing.

Run:  python -m himark.tools.transpiler doc.md                 # HTML to stdout
      python -m himark.tools.transpiler doc.md --out page.html # …or to a file
      python -m himark.tools.transpiler data.txt --script my.hmk
"""

from pathlib import Path

import typer

from himark.tools import precompiled

ROOT = Path(__file__).resolve().parents[2]
DOWNLOADS = ROOT / "downloads"
DEFAULT_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "md_html.hmk"
DEFAULT_INPUT = ROOT / "docs" / "HMK.md"


def _pipeline(script: Path) -> precompiled.Pipeline:
    """The compiled `script` pipeline, loaded from a cached `.hmkc` artifact in
    downloads/. Rebuilt when the artifact is missing, older than the script (a
    make-style freshness check), or written by an incompatible older version."""
    artifact = DOWNLOADS / f"{script.stem}.hmkc"
    if artifact.exists() and artifact.stat().st_mtime >= script.stat().st_mtime:
        try:
            return precompiled.load(artifact)
        except ValueError:
            pass  # stale/incompatible artifact — fall through and rebuild
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    pipeline = precompiled.compile_script(script.read_text("utf-8"))
    precompiled.dump(pipeline, artifact)
    return pipeline


def transpile(text: str, script: Path = DEFAULT_SCRIPT) -> str:
    """Run `script` over `text`, returning the transformed document."""
    return precompiled.apply(_pipeline(script), text)


def transpile_cmd(
    markdown: Path = typer.Argument(
        DEFAULT_INPUT, help="Input document to transpile (defaults to docs/HMK.md)."
    ),
    script: Path = typer.Option(
        DEFAULT_SCRIPT, "--script", help="The .hmk pipeline to run."
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Write output to this file instead of stdout."
    ),
) -> None:
    """Run an HMK script over a document; print the result, or --out to a file."""
    html = transpile(markdown.read_text("utf-8"), script)
    if out is None:
        typer.echo(html)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, "utf-8")
    typer.echo(f"wrote {out}", err=True)


if __name__ == "__main__":
    typer.run(transpile_cmd)
