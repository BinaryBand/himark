"""ANTLR-backed front-end for the parser (see docs/GRAMMAR.g4).

Pipeline:
  • ANTLR is the whole front-end: the generated lexer+parser (`_generated/GRAMMAR*`)
    turns a statement into a validated parse tree, splitting the `=>`/`<=>` chain in
    the grammar itself (a `"…"` template is one STRING token, so an arrow inside it is
    literal) — no hand-rolled pre-pass. `@name` is left intact as a `macro` atom, with
    script-local top-level `@name` text-expanded per step (see below).
  • A visitor-based `_AstBuilder` (in `_builder.py`) walks the CST: it replaces the
    old `_Resolver` class's manual `isinstance` dispatch with ANTLR's double-dispatch
    visitor pattern. Each labeled grammar alternative gets a `visit*` method.

The CST→AST *decisions* live on the model, not here: each leaf/value node builds itself
from a parser-agnostic view (`himark.models.cst_view`) — `AnchorNode.from_view`,
`reference_from_view`, `ValueRangeNode.from_range_view`. This module only reads the parse
tree and hands across a tech-neutral view, so the same `from_view` code serves any
front-end. Composite nodes (union, complement, sequence, brace) are plain composition of
already-resolved children.

Why variables, not text macros: textual `@name` substitution is context-blind — it
expands inside `"…"` templates, depends on a fixed-point cap, and renumbers captures by
splice position. Structural resolution is referentially transparent: `@name` denotes a
fixed node wherever it appears, and a template is an opaque string the `macro` rule never
sees. The reference keeps text macros (it is the parity oracle); the harness proves they
agree.

A few non-corpus edge forms still raise `NotImplementedError` (e.g. the `N#` stage
count-ref, which has no reference node; open-ended bare `..` ranges).

Entry point: `parse(text, variables=None) -> list[RootNode]`, matching
`himark.parser.parse` so the candidate plugs into the harness unchanged.
"""

from __future__ import annotations

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from himark.models import nodes_typed as t
from himark.models.exceptions import CompileError
from himark.parser._builder import _AstBuilder
from himark.parser._helpers import (
    strip_insignificant_ws,
    text_expand_variables,
    unescape,
)

# The generated lexer/parser (`_generated/GRAMMAR*`) are a git-ignored build product
# of docs/GRAMMAR.g4 — see regenerate.py. They are imported lazily (inside
# `_make_parser`) so this package still imports when they are absent (e.g. on
# a fresh checkout before regeneration); only an actual `parse` call needs them.
try:  # pragma: no cover - typing-only convenience when generated code is present
    from himark.parser._generated.GRAMMARParser import GRAMMARParser
except ModuleNotFoundError:  # pragma: no cover - parser not generated yet
    GRAMMARParser = None  # type: ignore[invalid-assignment]


# ── ANTLR plumbing ────────────────────────────────────────────────────────────


class _RaiseOnError(ErrorListener):
    """Turn ANTLR's default recover-and-print into a hard `CompileError`, so a
    malformed pattern fails the same way the reference parser does."""

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        raise CompileError(f"ANTLR syntax error at {line}:{column}: {msg}")


def _make_parser(src: str) -> "GRAMMARParser":
    from himark.parser._generated.GRAMMARLexer import GRAMMARLexer
    from himark.parser._generated.GRAMMARParser import GRAMMARParser

    lexer = GRAMMARLexer(InputStream(src))
    lexer.removeErrorListeners()
    lexer.addErrorListener(_RaiseOnError())
    parser = GRAMMARParser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(_RaiseOnError())
    return parser


def _parse_pattern_tree(src: str) -> "GRAMMARParser.PatternOnlyContext":
    return _make_parser(src).patternOnly()


def _parse_snippet_tree(src: str) -> "GRAMMARParser.SnippetContext":
    """Parse a whole `=>`/`<=>` statement chain. The grammar itself splits the
    chain (a `"…"` template is one STRING token, so a `=>` inside it is literal;
    braces/counts nest), so there is no hand-rolled top-level arrow scan."""
    return _make_parser(src).snippet()


# ── Public entry point ────────────────────────────────────────────────────────


def parse(text: str, variables: dict[str, str] | None = None) -> list[t.RootNode]:
    """ANTLR-backed `parse`, signature-compatible with `himark.parser.parse`.

    The depth-aware whitespace pre-pass, then ANTLR parses the whole `=>`/`<=>`
    statement chain (the grammar splits it — no hand-rolled arrow scan), and the
    visitor-based `_AstBuilder` resolves each step, with `@name` resolved as a
    scoped variable from `VARIABLES` overlaid with `variables`. A whole-step `"…"`
    template is one verbatim leaf (no variable expansion → no template leak); its
    moustaches are a separate layer. Out-of-slice constructs raise
    `NotImplementedError`.

    Script-local `variables` are text-expanded into each non-template pattern step
    before ANTLR tokenises it. ANTLR tokenises top-level `@name` as a `literalRun`
    (not a `macro` atom), so structural resolution alone would miss these
    references. Prelude variables stay structural — they only appear inside braces."""
    from himark.prelude import VARIABLES

    builder = _AstBuilder({**VARIABLES, **(variables or {})})
    roots: list[t.RootNode] = []
    text = strip_insignificant_ws(text)
    for step in _parse_snippet_tree(text).statement().step():
        template = step.template()
        if template is not None:
            # A whole-step `"…"` template is one verbatim leaf — no variable
            # expansion (no template leak); its moustaches are a separate layer.
            quoted = template.getText()
            roots.append(
                t.RootNode(children=[t.LeafNode(content=unescape(quoted[1:-1]))])
            )
            continue
        pattern = step.pattern()
        if variables:
            # Script-local `@name` lexes as a top-level `literalRun`, not a `macro`
            # atom, so structural resolution alone would miss it. Text-expand this
            # step's own source slice and re-parse it (templates are untouched —
            # they took the branch above).
            src = text[step.start.start : step.stop.stop + 1]
            pattern = _parse_pattern_tree(
                text_expand_variables(src, variables)
            ).pattern()
        roots.append(builder.resolve_pattern(pattern))
    return roots