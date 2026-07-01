"""himark CLI -- run, compile, exec, check, and fmt HMK scripts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from himark.models.compiled import Step, Template

app = typer.Typer(
    name="himark",
    help="HMK -- pattern-matching and text-transformation language.",
    no_args_is_help=True,
)

_SCRIPTS_DIR = Path(__file__).parent / "scripts"
_FORMAT_SCRIPT = _SCRIPTS_DIR / "format_hmk.hmk"


# ── internal helpers ──────────────────────────────────────────────────────────


def _read(path: Path | None) -> str:
    return sys.stdin.read() if path is None else path.read_text("utf-8")


def _write(text: str, dest: Path | None) -> None:
    if dest is None:
        sys.stdout.write(text)
    else:
        dest.write_text(text, "utf-8")
        typer.echo(f"wrote {dest}", err=True)


def _die(msg: str) -> None:
    typer.echo(f"error: {msg}", err=True)
    raise typer.Exit(1)


def _step_to_json(step: Step) -> dict:
    d = step.to_json()
    if isinstance(step, Template):
        d["kind"] = "template"
    return d


# ── root callback (--version) ─────────────────────────────────────────────────


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    if version:
        try:
            from importlib.metadata import version as _v

            typer.echo(f"himark {_v('himark')}")
        except Exception:
            typer.echo("himark (development)")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


# ── commands ──────────────────────────────────────────────────────────────────


@app.command()
def run(
    script: Path = typer.Argument(..., help="Path to a .hmk script file."),
    target: Optional[Path] = typer.Argument(
        None, help="Input file to transform (reads stdin if omitted)."
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write result to file (stdout if omitted)."
    ),
    in_place: bool = typer.Option(
        False, "--in-place", "-i", help="Overwrite the target file in place."
    ),
) -> None:
    """Run a .hmk script on a file or stdin."""
    from himark.engine import run_pipeline
    from himark.models.exceptions import CompileError
    from himark.parser._script import load_script

    if in_place and target is None:
        _die("--in-place requires a target file argument")
        return

    try:
        pipeline = load_script(str(script))
        text = _read(target)
        result = run_pipeline(pipeline, text)
    except (CompileError, OSError, RuntimeError) as e:
        _die(str(e))
        return

    dest = target if in_place else output
    _write(result, dest)


@app.command(name="exec")
def exec_cmd(
    expr: str = typer.Argument(
        ..., help="A single HMK statement (e.g. '{a..z} => \"[{{$}}]\"')."
    ),
    target: str = typer.Argument(..., help="Target string to transform."),
    matches: bool = typer.Option(
        False,
        "--matches",
        "-m",
        help="Print each match on its own line instead of splicing in-place.",
    ),
) -> None:
    """Execute a single HMK expression on a string and print the result."""
    from himark.engine import execute, splice
    from himark.models.exceptions import CompileError
    from himark.parser import parse

    try:
        steps = parse(expr)
    except CompileError as e:
        _die(str(e))
        return

    try:
        if matches:
            results = execute(steps, target)
            sys.stdout.write("\n".join(results))
            if results:
                sys.stdout.write("\n")
        else:
            sys.stdout.write(splice(steps, target))
    except (RuntimeError, CompileError) as e:
        _die(str(e))


@app.command(name="compile")
def compile_cmd(
    script: Path = typer.Argument(..., help="Path to a .hmk script file."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file (stdout if omitted)."
    ),
) -> None:
    """Compile a .hmk script to a JSON pipeline for inspection or external use."""
    from himark.models.exceptions import CompileError
    from himark.parser._script import load_script

    try:
        pipeline = load_script(str(script))
    except (CompileError, OSError) as e:
        _die(str(e))
        return

    data = [[_step_to_json(s) for s in stmt] for stmt in pipeline]
    _write(json.dumps(data, indent=2, default=list) + "\n", output)


@app.command()
def check(
    scripts: list[Path] = typer.Argument(
        ..., help="One or more .hmk script files to validate."
    ),
) -> None:
    """Validate .hmk scripts for syntax errors without running them."""
    from himark.models.exceptions import CompileError
    from himark.parser._script import load_script

    errors = 0
    for path in scripts:
        try:
            load_script(str(path))
            typer.echo(f"ok  {path}")
        except (CompileError, OSError) as e:
            typer.echo(f"err {path}: {e}", err=True)
            errors += 1
    if errors:
        raise typer.Exit(1)


@app.command()
def fmt(
    script: Path = typer.Argument(..., help="Path to a .hmk script file to format."),
    check_only: bool = typer.Option(
        False,
        "--check",
        help="Exit non-zero if the file would change, without writing.",
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file (overwrites input if omitted)."
    ),
) -> None:
    """Format a .hmk script using the built-in HMK formatter."""
    from himark.engine import run_pipeline
    from himark.models.exceptions import CompileError
    from himark.parser._script import load_script

    if not _FORMAT_SCRIPT.exists():
        _die(f"built-in formatter not found at {_FORMAT_SCRIPT}")
        return

    try:
        fmt_pipeline = load_script(str(_FORMAT_SCRIPT))
        source = script.read_text("utf-8")
        result = run_pipeline(fmt_pipeline, source)
    except (CompileError, OSError, RuntimeError) as e:
        _die(str(e))
        return

    if check_only:
        if result != source:
            typer.echo(f"would reformat {script}", err=True)
            raise typer.Exit(1)
        return

    _write(result, output or script)
