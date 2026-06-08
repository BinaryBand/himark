import sys
from pathlib import Path

import typer

from himark import parser
from himark.engine import execute

app = typer.Typer()


def _str_or_file(value: str) -> str:
    p = Path(value)
    return p.read_text().strip() if p.is_file() else value


@app.command()
def run(
    pattern: str = typer.Argument(
        help="HMK pattern, file path, or '-' to read from stdin"
    ),
    target: str = typer.Argument(help="String to match against, or a file path"),
) -> None:
    """Match TARGET against PATTERN and print each result."""
    if pattern == "-":
        pattern = sys.stdin.read().strip()
    else:
        pattern = _str_or_file(pattern)
    target = _str_or_file(target)
    trees = parser.parse(pattern)
    results = execute(trees, target)
    for result in results:
        typer.echo(result)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to listen on"),
) -> None:
    """Start a local HTTP server exposing the HMK engine as an API."""
    import uvicorn

    from himark.server import api

    typer.echo(f"Serving at http://{host}:{port}  (docs: http://{host}:{port}/docs)")
    uvicorn.run(api, host=host, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
