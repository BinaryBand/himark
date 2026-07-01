"""The core matching commands — `execute` (match + transform) and `find` (locate).

Each command is a plain Typer-typed function; `main.py` registers them on the
top-level app, and this module exposes its own `app` so the pair can also be run
standalone (`python -m himark.tools.query …`).
"""

import json
import sys
from pathlib import Path

import typer

from himark import parser
from himark.engine import deltas, execute, find
from himark.models.exceptions import CompileError


def _str_or_file(value: str) -> str:
    p = Path(value)
    return p.read_text().strip() if p.is_file() else value


def _resolve_pattern(pattern: str) -> str:
    if pattern == "-":
        return sys.stdin.read().strip()
    return _str_or_file(pattern)


def _emit_json_error(exc: CompileError) -> None:
    """In `--json` mode a compile error is structured JSON on stderr, exit 1, so
    callers never have to scrape a traceback."""
    typer.echo(json.dumps({"error": str(exc)}), err=True)
    raise typer.Exit(code=1)


def execute_cmd(
    pattern: str = typer.Argument(
        help="HMK pattern with template (e.g. '{a..z}[1..] => <b>{{$}}</b>'), file path, or '-' for stdin"
    ),
    target: str = typer.Argument(help="String to match against, or a file path"),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit per-branch deltas as a JSON array of {start, end, text}.",
    ),
) -> None:
    """Match TARGET against PATTERN and print each rendered match, one per line.

    `--json` instead prints a delta per branch — {start, end, text} — where text
    is the rendered replacement for that match. Splicing the deltas back over the
    input gives the in-place transform.
    """
    try:
        trees = parser.parse(_resolve_pattern(pattern))
        tgt = _str_or_file(target)
        if json_out:
            payload = [
                {"start": s, "end": e, "text": txt} for s, e, txt in deltas(trees, tgt)
            ]
            typer.echo(json.dumps(payload))
            return
        result = execute(trees, tgt)
    except CompileError as exc:
        if json_out:
            _emit_json_error(exc)
        raise

    for line in result:
        typer.echo(line)


def find_cmd(
    pattern: str = typer.Argument(
        help="HMK pattern (e.g. '{a..z}[1..]'), file path, or '-' for stdin"
    ),
    target: str = typer.Argument(help="String to search in, or a file path"),
    json_out: bool = typer.Option(
        False, "--json", help="Emit matches as a JSON array of {start, end}."
    ),
) -> None:
    """Find all matches of PATTERN in TARGET and print their start and end positions."""
    try:
        trees = parser.parse(_resolve_pattern(pattern))
        spans = find(trees, _str_or_file(target))
    except CompileError as exc:
        if json_out:
            _emit_json_error(exc)
        raise

    if json_out:
        typer.echo(json.dumps([{"start": s, "end": e} for s, e in spans]))
    else:
        for start, end in spans:
            typer.echo(f"{start} {end}")


app = typer.Typer(help="Match and transform text with HMK patterns.")
app.command(name="execute")(execute_cmd)
app.command(name="find")(find_cmd)


if __name__ == "__main__":
    app()
