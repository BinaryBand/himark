import sys
from pathlib import Path

import typer

from marky import parser
from marky.engine import execute, find

app = typer.Typer()


def _str_or_file(value: str) -> str:
    p = Path(value)
    return p.read_text().strip() if p.is_file() else value


def _resolve_pattern(pattern: str) -> str:
    if pattern == "-":
        return sys.stdin.read().strip()
    return _str_or_file(pattern)


@app.command(name="execute")
def execute_cmd(
    pattern: str = typer.Argument(
        help="HMK pattern with template (e.g. '{a..z}[1..] => <b>{{.}}</b>'), file path, or '-' for stdin"
    ),
    target: str = typer.Argument(help="String to match against, or a file path"),
) -> None:
    """Match TARGET against PATTERN and print each transformed result."""
    trees = parser.parse(_resolve_pattern(pattern))
    for result in execute(trees, _str_or_file(target)):
        typer.echo(result)


@app.command(name="find")
def find_cmd(
    pattern: str = typer.Argument(
        help="HMK pattern (e.g. '{a..z}[1..]'), file path, or '-' for stdin"
    ),
    target: str = typer.Argument(help="String to search in, or a file path"),
) -> None:
    """Find all matches of PATTERN in TARGET and print their start and end positions."""
    trees = parser.parse(_resolve_pattern(pattern))
    for start, end in find(trees, _str_or_file(target)):
        typer.echo(f"{start} {end}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
