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
a data file *alongside the himark library* — loading it needs `himark` importable
and broadly version-compatible. It is not a language-agnostic format. The lowered
matcher program is **not** stored (it recompiles lazily on first use, ~7 µs), so
the file stays small and free of engine objects.

Run:  python -m himark.tools.precompiled dump out.hmkc "<stmt>" ["<stmt>" …]
"""

from __future__ import annotations

import pickle
from pathlib import Path

import typer

from himark import parser
from himark.engine import splice
from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError

_MAGIC = b"HMKC\x00"
_VERSION = 1

Pipeline = list[list[t.RootNode]]


def compile_pipeline(statements: list[str]) -> Pipeline:
    """Parse each HMK statement into its ordered step trees — the costly one-time
    work this module exists to cache. The result runs with `apply`.

    A statement whose arrow is `<=` (fixed-point) is parsed like its `=>` form,
    and its first step is flagged so `apply` re-splices it until the document
    settles (see `_split_fixed_point`)."""
    pipeline: Pipeline = []
    for s in statements:
        converted, loop = _split_fixed_point(s)
        steps = parser.parse(converted)
        if loop and steps:
            steps[0].fixed_point = True
        pipeline.append(steps)
    return pipeline


def _split_fixed_point(statement: str) -> tuple[str, bool]:
    """Rewrite each top-level `<=` arrow to `=>`, returning `(text, used_<=)`.

    Depth-aware over `{…}` / `[…]` and skipping `\\`-escapes, like the `=>`
    splitter — so a `<=` inside a brace or count is left alone. (A `<=` inside a
    quoted template is not distinguished, the same limitation `=>` has.)"""
    out: list[str] = []
    depth = 0
    found = False
    i = 0
    n = len(statement)
    while i < n:
        ch = statement[i]
        if ch == "\\" and i + 1 < n:
            out.append(statement[i : i + 2])
            i += 2
            continue
        if ch == "<" and statement[i + 1 : i + 2] == "=" and depth == 0:
            out.append("=>")
            found = True
            i += 2
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth = max(0, depth - 1)
        out.append(ch)
        i += 1
    return "".join(out), found


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
    template spanning physical lines stays one logical line.

    A `//` line comment at depth 0 is **inert**: its text is kept (so a trailing
    comment rides along to `_strip_comment`) but its `"`/`{`/`}` are not tracked,
    so an unbalanced quote or brace inside a comment cannot corrupt the split.
    A `//` inside a brace or quote is content, never a comment."""
    lines: list[str] = []
    buf: list[str] = []
    depth = 0
    inq = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            buf.append(text[i : i + 2])
            i += 2
            continue
        if depth == 0 and not inq and c == "/" and text[i + 1 : i + 2] == "/":
            j = text.find("\n", i)  # skip the comment body, up to (not past) \n
            end = n if j == -1 else j
            buf.append(text[i:end])
            i = end
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
    transformed document. The compile cache warms on the first document. A
    `<=` (fixed-point) statement is re-spliced until the text stops changing."""
    for steps in pipeline:
        if steps and steps[0].fixed_point:
            text = _splice_to_fixed_point(steps, text)
        else:
            text = splice(steps, text)
    return text


def _splice_to_fixed_point(steps: list[t.RootNode], text: str) -> str:
    """Re-splice `steps` over `text` until a pass changes nothing (the fixed
    point). A contracting rule settles in at most a few passes per unit of input,
    so the guards only trip on a rule that does not converge — a `CompileError`.
    Two guards: a pass count (catches oscillators), and a size bound (catches a
    grower like `{a} <= "aa"` before it exhausts memory)."""
    cap = 8 * len(text) + 1024
    size_limit = 64 * len(text) + 65536
    for _ in range(cap):
        nxt = splice(steps, text)
        if nxt == text:
            return text
        if len(nxt) > size_limit:
            break
        text = nxt
    raise CompileError(
        "a `<=` statement did not settle: the rule is not contracting toward a "
        "fixed point (it grows or oscillates). Use `=>` for a single pass."
    )


def dump(pipeline: Pipeline, path: str | Path) -> None:
    """Write `pipeline` to a portable artifact at `path`.

    The AST carries no engine state — the lowered-program cache lives in the
    engine's `Runtime`, not on the nodes — so the file holds only the AST (no
    matchers, no backend objects), stays small, and recompiles lazily on load."""
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
