"""Loader for macros.toml — the single source of Himark macros.

Every named alphabet is a plain text macro: `@name` expands to Himark source.
The engine holds no alphabet knowledge of its own; it only ever sees the
ranges, unions, and congruences the macros expand into.
"""

import tomllib
from pathlib import Path

_DATA = tomllib.loads((Path(__file__).parent / "macros.toml").read_text("utf-8"))

# name -> Himark source, expanded into the pattern before tokenizing
MACROS: dict[str, str] = _DATA.get("macros", {})
