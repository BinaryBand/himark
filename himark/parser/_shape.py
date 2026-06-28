"""Shape detection for a `{…}` brace interior.

Answers one question for phase3: is a brace's interior a single **σ-grammar
alphabet** expression (built from `..` and `,`), or a **concatenation** of
constructs — a grouping brace / sub-pattern (`{of{black}{quartz}}`)? This is a
pure predicate over the interior text; resolving the brace stays in phase3.
"""

import re

from himark.models import nodes_typed as t
from himark.parser import phase2
from himark.parser._text import brace_end, split_top, strip_unescaped


def is_sequence_brace(content: str) -> bool:
    """True if a brace's interior is a *grouping* — either a concatenation of
    constructs (`{of{black}{quartz}}`) or a single nested brace (`{{X}}`). Only a
    pure σ-expression (alphabet: `..`, `,`, `::` only) returns False.

    The σ-grammar has no concatenation operator: every `,`/`..`-separated part is
    bare text or exactly one `{…}` atom. A part that glues a construct onto
    adjacent text — or holds more than one construct — is a sub-pattern.
    A content that is itself one brace is a single-child grouping.
    """
    stripped = strip_unescaped(content)
    if stripped.startswith("{") and brace_end(stripped) == len(stripped):
        return True  # {{X}} — single-child grouping brace
    if len(split_top("::", content)) >= 2:
        return False  # a `{alphabet::floor..ceiling}` band is one value universe
    body = content
    if body.startswith("!"):
        body = body[1:]
    for arm in split_top(",", body):
        for part in split_top("..", arm):
            if not _is_sigma_atom(part):
                return True
    return False


def _is_sigma_atom(part: str) -> bool:
    """True if `part` is a valid σ atom: bare text, or a single `{…}` (optionally
    with an exact `[N]` count) surrounded only by whitespace. A construct glued
    to text, several constructs, or a ranged count is a sub-pattern fragment."""
    part = strip_unescaped(part)
    if part.startswith("!"):
        part = part[1:].strip()  # a `!` complement/exclusion arm, e.g. !{0,l,I,O}
    if not part:
        return True
    children = phase2.parse(part).children
    constructs = [c for c in children if isinstance(c, t.BraceGroupNode)]
    if not constructs:
        return True  # bare token (a..z, cat, etc.)
    if len(constructs) > 1:
        return False
    only = constructs[0]
    if any(isinstance(c, t.LeafNode) and c.content.strip() for c in children):
        return False  # a brace glued to adjacent literal text → concatenation
    if only.count_src is not None and not re.fullmatch(r"\d+", only.count_src.strip()):
        return False  # a ranged/star count is repetition, not a σ singleton
    return True
