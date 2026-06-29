#!/usr/bin/env python3
"""Run an HMK `.hmk` script over a text document.

Run: python -m himark.tools.transpiler doc.md                 # HTML to stdout
     python -m himark.tools.transpiler doc.md --out page.html # ...or to a file
     python -m himark.tools.transpiler data.txt --script my.hmk
"""

from pathlib import Path

import typer

from himark.engine import compile_script, run_pipeline

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "md_html.hmk"
DEFAULT_INPUT = ROOT / "docs" / "HMK.md"


def transpile(text: str, script: Path = DEFAULT_SCRIPT) -> str:
    """Run `script` over `text`, returning the transformed document."""
    return run_pipeline(compile_script(script.read_text("utf-8")), text)


def transpile_cmd(
    markdown: Path = typer.Argument(
        DEFAULT_INPUT, help="Input document to transpile (defaults to docs/HMK.md)."
    ),
    script: Path = typer.Option(
        DEFAULT_SCRIPT,
        "--script",
        "-s",
        help="HMK script to run (defaults to himark/scripts/md_html.hmk).",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Write result to a file instead of stdout.",
    ),
) -> None:
    result = transpile(markdown.read_text("utf-8"), script)
    if out:
        out.write_text(result, "utf-8")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(result)


if __name__ == "__main__":
    typer.run(transpile_cmd)
