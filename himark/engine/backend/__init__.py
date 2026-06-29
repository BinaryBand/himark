"""The matching backend — the opcode VM and its shared types.

The parser already compiled the query to a `Program`; `python.prepare` lowers it
to VM-ready instructions, and `python.find_matches` runs them against text.
"""

from himark.engine.backend.python import find_matches, prepare
from himark.engine.backend._types import Capture, Match
from himark.models.alphabet import MAX_SYMBOLS, Alphabet, RangeAlphabet

__all__ = [
    "find_matches",
    "prepare",
    "Match",
    "Capture",
    "Alphabet",
    "RangeAlphabet",
    "MAX_SYMBOLS",
]
