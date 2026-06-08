import sys

import typer

from himark import parser
from himark.engine import execute

app = typer.Typer()


@app.command()
def run(
    pattern: str = typer.Argument(help="HMK pattern, or '-' to read from stdin"),
    target: str = typer.Argument(help="String to match against"),
) -> None:
    """Match TARGET against PATTERN and print each result."""
    if pattern == "-":
        pattern = sys.stdin.read().strip()
    trees = parser.parse(pattern)
    results = execute(trees, target)
    for result in results:
        typer.echo(result)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
