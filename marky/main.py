"""The `marky` CLI — thin Typer wiring over the tools in `marky.tools`.

No command logic lives here: each tool module owns its commands (and is runnable
standalone), and this file only assembles them into one app. Add a command by
writing the tool, then registering it below.
"""

import typer

from marky.tools import markdown_transpiler, precompiled, query

app = typer.Typer(help="HMK pattern matching and text transformation.")

app.command(name="execute")(query.execute_cmd)
app.command(name="find")(query.find_cmd)
app.command(name="transpile")(markdown_transpiler.transpile_cmd)
app.add_typer(precompiled.app, name="pipeline")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
