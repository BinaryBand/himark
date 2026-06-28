"""Grammar-acceptance guard for phase1 declarations (the variable/definition layer).

Sibling to tests/test_parser_parity.py. That file checks the *output* of parsing
(AST parity); this one checks that docs/GRAMMAR.g4 **accepts the real declaration
syntax** — the prelude's named alphabets and a script's `@name = …` definitions.

Why this is a distinct, necessary guard: the grammar models declarations with the
rules `prelude`, `declaration`/`macroDecl`, `definition`, `scriptItem`, and (inside
braces) `variable : AT NAME`. Today those rules are **dead** — phase1 expands `@name`
to text *before* anything structural runs, so nothing exercises them. If GRAMMAR.g4
drifts from the actual variable/definition syntax, no existing test notices. This pins
that the grammar can parse:

  • every named alphabet in himark/std.hmk (via `prelude` / `macroDecl` / `braceBody`,
    including unexpanded cross-references like `@hex = {@d},{@w::..f}` through the
    live `variable` atom rule), and
  • the canonical `@name = <pattern>` definition forms from the spec (via `definition`).

These are exactly the rules the planned macro→defined-variable change (Option B)
makes live: pinning their acceptance now is the safety net that change builds on.

This is grammar acceptance, not AST parity — phase1 produces no declaration tree to
diff against, so the assertion is "ANTLR consumes the whole input under this rule
with no syntax error." Skipped wholesale when the ANTLR parser is not generated.
"""

from __future__ import annotations

import pytest

from himark.models.exceptions import CompileError
from himark.prelude import VARIABLES

antlr4 = pytest.importorskip("antlr4", reason="antlr4 runtime not installed")

try:
    from antlr4 import CommonTokenStream, InputStream, Token

    from himark.parser_antlr import _RaiseOnError
    from himark.parser_antlr._generated.GRAMMARLexer import GRAMMARLexer
    from himark.parser_antlr._generated.GRAMMARParser import GRAMMARParser
except ModuleNotFoundError:  # generated parser absent — regenerate.py not yet run
    pytest.skip(
        "ANTLR parser not generated (run python -m himark.parser_antlr.regenerate)",
        allow_module_level=True,
    )


def accepts(rule: str, text: str) -> None:
    """Parse `text` under grammar `rule`, asserting no syntax error **and** that the
    whole input is consumed. Non-`EOF` rules (`macroDecl`, `definition`, `braceBody`)
    stop at the first token they cannot use without erroring, so a leftover-token
    check is what makes acceptance strict."""
    lexer = GRAMMARLexer(InputStream(text))
    lexer.removeErrorListeners()
    lexer.addErrorListener(_RaiseOnError())
    parser = GRAMMARParser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(_RaiseOnError())

    getattr(parser, rule)()  # raises CompileError via _RaiseOnError on a syntax error
    if parser.getTokenStream().LA(1) != Token.EOF:
        nxt = parser.getCurrentToken()
        raise CompileError(
            f"rule {rule!r} did not consume all of {text!r}; "
            f"stopped at {nxt.text!r} (token {nxt.tokenIndex})"
        )


# ── Prelude: every std.hmk named alphabet ─────────────────────────────────────
# The canonical comment-/space-stripped declaration form is `@name=body`, which is
# what the loader already normalized VARIABLES to. Reconstructing it and feeding the
# `prelude` rule checks the file as a whole; the per-variable rows name the culprit on
# a failure.

PRELUDE_TEXT = "\n".join(f"@{name}={body}" for name, body in VARIABLES.items())
MACRO_ROWS = list(VARIABLES.items())


def test_prelude_accepted_whole():
    """The whole reconstructed std.hmk parses under the `prelude` rule."""
    accepts("prelude", PRELUDE_TEXT)


@pytest.mark.parametrize("name,body", MACRO_ROWS, ids=[n for n, _ in MACRO_ROWS])
def test_variable_decl_accepted(name, body):
    """Each `@name = body` is a valid `macroDecl` (and its body a valid `braceBody`,
    cross-references like `@d`/`@w` included, via the live `variable` atom rule)."""
    accepts("macroDecl", f"@{name}={body}")
    accepts("braceBody", body)


# ── Definitions: canonical `@name = <pattern>` script-local forms ─────────────
# Drawn from the spec examples pinned in tests/test_script_defs.py — real definition
# right-hand sides (counts, complements, anchors, variable references, fixed-point use).
# These exercise `definition : AT NAME EQ pattern`.

DEFINITIONS: list[tuple[str, str]] = [
    ("head", r"{@<}{#}[1..6]{ }[1..]"),
    ("eol", r"!{\n}[1..]"),
    ("n", r"{@d}[1..]"),
    ("digits", r"{{@d}}[1..]"),
    ("pair", r"@digits{\,}@digits"),
    ("paren", r"{(}!{(,)}[..]{)}"),
]


@pytest.mark.parametrize("name,rhs", DEFINITIONS, ids=[n for n, _ in DEFINITIONS])
def test_definition_accepted(name, rhs):
    """Each `@name = <pattern>` definition parses under the `definition` rule."""
    accepts("definition", f"@{name}={rhs}")
    accepts("patternOnly", rhs)  # the RHS is also a stand-alone query
