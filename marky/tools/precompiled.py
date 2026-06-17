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


# ── .hmk script files ─────────────────────────────────────────────────────────


def load_script(path: str | Path) -> list[str]:
    """Read a `.hmk` script file into its list of statement strings.

    A script holds one statement per logical line, optionally continued across
    physical lines by leading `=>` steps:

        {pattern}
          => "template"
          => {next pattern}      // a trailing comment

    Rules (all applied at brace/quote depth 0, so braces, quoted templates, and
    `=>`/`//` inside them are never misread): a `//` starts a line comment; a
    blank line is ignored; a line beginning with `=>` continues the previous
    statement; any other line starts a new one.
    """
    return split_statements(Path(path).read_text("utf-8"))


def split_statements(text: str) -> list[str]:
    """Split `.hmk` source into statement strings (see `load_script`)."""
    statements: list[str] = []
    current: list[str] = []
    for raw in _logical_lines(text):
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("=>"):
            current.append(line)
        else:
            if current:
                statements.append("\n".join(current))
            current = [line]
    if current:
        statements.append("\n".join(current))
    return statements


def _logical_lines(text: str) -> list[str]:
    """Split on newlines that sit at brace/quote depth 0, so a brace or quoted
    template spanning physical lines stays one logical line."""
    lines: list[str] = []
    buf: list[str] = []
    depth = 0
    inq = False
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            buf.append(text[i : i + 2])
            i += 2
            continue
        if c == "\n" and depth == 0 and not inq:
            lines.append("".join(buf))
            buf = []
        elif c == '"':
            inq = not inq
            buf.append(c)
        else:
            if not inq:
                depth += (c == "{") - (c == "}")
            buf.append(c)
        i += 1
    lines.append("".join(buf))
    return lines


def _strip_comment(line: str) -> str:
    """Remove a `//` line comment, ignoring `//` inside braces or quotes (so a
    `http://` in a template, or a `//` in a pattern, survives)."""
    depth = 0
    inq = False
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            i += 2
            continue
        if c == '"':
            inq = not inq
        elif not inq:
            if c == "/" and depth == 0 and line[i + 1 : i + 2] == "/":
                return line[:i]
            depth += (c == "{") - (c == "}")
        i += 1
    return line


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
