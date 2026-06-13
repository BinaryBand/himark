import json
import sys
from pathlib import Path

import typer

from marky import parser
from marky.engine import execute, find
from marky.models.exceptions import CompileError

app = typer.Typer()


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


@app.command(name="execute")
def execute_cmd(
    pattern: str = typer.Argument(
        help="HMK pattern with template (e.g. '{a..z}[1..] => <b>{{.}}</b>'), file path, or '-' for stdin"
    ),
    target: str = typer.Argument(help="String to match against, or a file path"),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit per-match deltas as a JSON array of {start, end, text}.",
    ),
) -> None:
    """Match TARGET against PATTERN and print each transformed result.

    With `=>` the matches are printed one per line; with `=>+` the whole
    transformed text is printed as a single block. `--json` instead prints a
    delta per match — {start, end, text} — where text is the engine's rendered
    replacement for that match (the same per-match rendering `=>+` splices), so
    chains and deferred `{{.}}` are honoured. Splicing the deltas back over the
    input reproduces `=>+` exactly.
    """
    try:
        trees = parser.parse(_resolve_pattern(pattern))
        tgt = _str_or_file(target)
        if json_out:
            from marky.engine import _render_match, find_matches

            deltas = [
                {"start": m.start, "end": m.end, "text": _render_match(trees[1:], m)}
                for m in find_matches(trees[0], tgt)
            ]
            typer.echo(json.dumps(deltas))
            return
        result = execute(trees, tgt)
    except CompileError as exc:
        if json_out:
            _emit_json_error(exc)
        raise

    if isinstance(result, str):
        typer.echo(result)
    else:
        for line in result:
            typer.echo(line)


@app.command(name="find")
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
