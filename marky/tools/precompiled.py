"""Pre-compile a pipeline of HMK statements into a portable artifact.

A *pipeline* is an ordered list of HMK statements (e.g. a Markdown → HTML
conversion), each spliced over the document in turn. Parsing those statements is
the dominant one-time cost — about 180 µs per statement, versus ~7 µs to lower
the AST and microseconds for the backend seam. The match loop (`engine/_run`) is
the only per-document cost that remains, and that is irreducible work.

So for a fixed pipeline run over many documents (or re-launched processes): parse
once with `compile_pipeline`, `dump` the parsed steps to a file, and `load` it
back to skip parsing entirely. `apply` runs the pipeline over a document.

Portability note: the artifact is a pickle of the typed AST, so it is portable as
a data file *alongside the marky library* — loading it needs `marky` importable
and broadly version-compatible. It is not a language-agnostic format. The lowered
matcher program is **not** stored (it recompiles lazily on first use, ~7 µs), so
the file stays small and free of engine objects.

Run:  python -m marky.tools.precompiled dump out.hmkc "<stmt>" ["<stmt>" …]
"""

from __future__ import annotations

import pickle
from pathlib import Path

import typer

from marky import parser
from marky.engine import splice
from marky.models import nodes_typed as t

_MAGIC = b"HMKC\x00"
_VERSION = 1

Pipeline = list[list[t.RootNode]]


def compile_pipeline(statements: list[str]) -> Pipeline:
    """Parse each HMK statement into its ordered step trees — the costly one-time
    work this module exists to cache. The result runs with `apply`."""
    return [parser.parse(s) for s in statements]


def apply(pipeline: Pipeline, text: str) -> str:
    """Run each statement's in-place splice over `text` in turn, returning the
    transformed document. The compile cache warms on the first document."""
    for steps in pipeline:
        text = splice(steps, text)
    return text


def dump(pipeline: Pipeline, path: str | Path) -> None:
    """Write `pipeline` to a portable artifact at `path`.

    The per-node compile cache is cleared first, so the file holds only the AST —
    no lowered matchers, no backend objects — keeping it small and recompiling
    lazily on load."""
    for steps in pipeline:
        for tree in steps:
            tree._compiled = None
            tree._compiled_by = None
    body = pickle.dumps(pipeline, protocol=pickle.HIGHEST_PROTOCOL)
    Path(path).write_bytes(_MAGIC + bytes([_VERSION]) + body)


def load(path: str | Path) -> Pipeline:
    """Load a pipeline written by `dump`, skipping parsing entirely. Raises
    `ValueError` if `path` is not a recognised, current-version artifact."""
    blob = Path(path).read_bytes()
    if blob[: len(_MAGIC)] != _MAGIC:
        raise ValueError(f"{path}: not an HMK compiled pipeline")
    version = blob[len(_MAGIC)]
    if version != _VERSION:
        raise ValueError(
            f"{path}: unsupported artifact version {version} (expected {_VERSION})"
        )
    return pickle.loads(blob[len(_MAGIC) + 1 :])


# ── CLI ───────────────────────────────────────────────────────────────────────


app = typer.Typer(help="Pre-compile HMK pipelines into portable artifacts.")


@app.command(name="dump")
def dump_cmd(
    path: str = typer.Argument(help="Output .hmkc artifact path."),
    statements: list[str] = typer.Argument(
        ..., help="HMK statements, in pipeline order."
    ),
) -> None:
    """Compile STATEMENTS and write a portable .hmkc artifact to PATH."""
    dump(compile_pipeline(statements), path)
    typer.echo(f"wrote {path}")


if __name__ == "__main__":
    app()
