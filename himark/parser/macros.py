"""Loader for macros.toml — the single source of `@name` macros.

Every named alphabet is a plain text macro: `@name` expands to Himark source.
The engine holds no alphabet knowledge of its own; it only ever sees the
ranges, unions, and congruences the macros expand into. This module parses
macros.toml once and exposes both `MACROS` and the raw `[[rewrites]]` rules
(`REWRITES`); the rewrite mechanics live in `parser/rewrites.py`.
"""

import tomllib
from pathlib import Path

_DATA = tomllib.loads((Path(__file__).parent / "macros.toml").read_text("utf-8"))

# name -> Himark source, expanded into the pattern before tokenizing
MACROS: dict[str, str] = _DATA.get("macros", {})

# `[[rewrites]]` rules — structural shortcuts read by `parser/rewrites.py`. Kept
# here so macros.toml is parsed once; each rule names a tool plus its parameters.
REWRITES: list[dict] = _DATA.get("rewrites", [])
