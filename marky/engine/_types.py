"""Match results.

A `Match` is just the matched slice and its bounds — numbered captures were
dropped, so a template renders the whole match (`{{.}}`) or nothing.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class Match:
    text: str
    start: int
    end: int
