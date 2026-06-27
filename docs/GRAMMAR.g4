/*
 * GRAMMAR.g4 — an ANTLR4 grammar for the Himark (HMK) ANTLR branch (v0.12).
 *
 * This is the *surface* grammar: it describes what a human writes in a `.hmk`
 * script, in the `std.hmk` prelude, or as a one-off snippet — BEFORE any macro
 * expansion or structural rewrite (`himark/parser/phase1`). The branch's four
 * divergences from mainline are exactly what let this be a clean, predicate-free
 * ANTLR grammar (see docs/HMK.md, "ANTLR branch"):
 *
 *   1. a band is `::`  — a single `:` is always literal text;
 *   2. no implicit first-step wrap — a step is an explicit run of constructs;
 *   3. `=>` / `<=>` are arrows only at top level — inside `{…}` or a count they
 *      are literal, and inside a `"…"` template they live inside one STRING token;
 *   4. `{{ }}` is template-only — outside a quote `{{` is two universe braces,
 *      inside a quote it opens a moustache (here, inside the STRING token).
 *
 * Layering (faithful to the implementation, not a shortcut):
 *
 *   • Comments and statement-splitting are a *stateful pre-pass*, not part of
 *     this grammar — exactly as `himark/tools/precompiled` strips `//` comments
 *     and splits logical lines before any pattern is parsed. A `//` is a comment
 *     only at brace/quote depth 0, so `{//}` (a literal) and `http://` survive;
 *     a depth-aware regex can't express that, so it stays a pre-pass. Feed this
 *     grammar comment-stripped source.
 *
 *   • A `"…"` template is one opaque STRING token here, just as the pattern
 *     parser (`phase0..3`) treats a template as literal text and the *renderer*
 *     (`himark/engine/_render`) separately parses each `{{ … }}` moustache. The
 *     moustache expression grammar is given below as its own entry rule,
 *     `moustacheExpression`, to be applied to the inside of each `{{ … }}`.
 *
 * Entry rules:
 *   script    — a whole comment-stripped `.hmk` pipeline file
 *   prelude   — a whole comment-stripped `std.hmk`
 *   statement — one `=>` / `<=>` chain (a snippet)
 *   pattern   — one query (a snippet, no arrows)
 *   moustacheExpression — the interior of one `{{ … }}` (second layer)
 */
grammar GRAMMAR;

// ═════════════════════════════════════════════════════════════════════════════
// Parser
// ═════════════════════════════════════════════════════════════════════════════

// ── File-level entry rules ───────────────────────────────────────────────────
// `script`/`prelude` parse a whole comment-stripped file. The `//`-comment and
// statement-splitting *pre-pass* (logical lines, continuations, blank lines) is a
// depth-aware stateful pass, not a token rule — it is documented in docs/HMK.md
// ("The .hmk file"). `snippet`/`patternOnly` parse a single statement / query.

script   : sp (scriptItem (sp scriptItem)*)? sp EOF ;
prelude  : sp (declaration (sp declaration)*)? sp EOF ;
snippet  : sp statement sp EOF ;
patternOnly : sp pattern sp EOF ;

// A script line is a statement or a local definition. A definition binds `@name`
// to a pattern fragment — the same construct as the prelude's `macroDecl`, scoped
// to one file. The lone `EQ` (never the `=>` arrow) after the name is what marks
// it; the pre-pass classifies the line before this grammar applies.
scriptItem : definition | statement ;
definition : AT NAME EQ pattern ;             // @head = {@<}{#}[1..6]{ }[1..]

// Insignificant newlines around arrows, steps, and declarations (a statement may
// break across lines on a leading arrow — the `.hmk` continuation form). Spaces
// and tabs are on the hidden channel (see `WS`), so only `NL` is visible here.
sp        : NL* ;

// ── Statements: an arrow-chain of steps ──────────────────────────────────────
// The chain may break across physical lines on a leading arrow (the `.hmk`
// continuation form), so whitespace/newlines may sit around an arrow.
statement : step (sp arrow sp step)* ;
arrow     : ARROW | FIXARROW ;

// A step is a quoted template or a query. The first step is a query in practice;
// the query-only / template-only split is semantic (enforced by the engine), so
// the grammar accepts either in any position.
step      : template
          | pattern
          ;

template  : STRING ;

// ── Query: a run of constructs, each optionally counted ──────────────────────
// Adjacency concatenates. A factor is a brace universe, a subtractive `!{…}`, or
// a bare literal run (no longer auto-wrapped — divergence 2). A `count` binds the
// construct to its left.
pattern   : factor+ ;
factor    : (braceGroup | complement | literalRun) count? ;

complement : BANG braceGroup ;
braceGroup : LBRACE braceBody RBRACE ;

// A top-level bare literal run: default-mode tokens that are neither a delimiter
// nor an arrow. (Spaces between braces in a snippet are literal text, matched
// verbatim, so WS belongs here.) `=>`/`<=>` are excluded — at top level they are
// always arrows (divergence 3).
literalRun : (TEXT | ESC | HEX_ESC | DOT | RANGE | BAND | COMMA
             | NAME | INT | AT | DOLLAR | HASH | CARET | LT | GT
             | PIPE | STAR | PLUS | LPAREN | RPAREN | EQ)+ ;

// ── Count `[…]` ──────────────────────────────────────────────────────────────
count     : LBRACK countBody RBRACK ;
countBody : countArm (COMMA countArm)* ;
countArm  : countTerm? RANGE countTerm?     // x.. / ..y / x..y / ..
          | countTerm                       // n  or  #  or  #i
          ;
countTerm : INT | countRef ;
countRef  : HASH INT? ;                      // # (self-bind) or #i (count-ref)

// ── Brace interior — the σ-grammar (`,` unions, `..` ranges, `::` bands) ──────
// Shared by `{…}` interiors and the prelude's `@name =` RHS. One top-level `::`
// splits payload from band (divergence 1); everything else is a union of arms,
// each an atom run with an optional `..` range.
braceBody : BANG? band ;
band      : universe (BAND universe)? ;
universe  : arm (COMMA arm)* ;
arm       : term (RANGE term?)?              // term, term.., term..term
          | RANGE term                       // ..term
          ;
term      : atom* ;                          // an atom run (may be empty)

// An atom is a nested brace, an inner subtractive arm, a reference, an anchor, a
// macro, an escape, or a single literal token. The literal set is broad on
// purpose: inside a brace, structure is carried only by `,` `..` `::` `{…}` `[…]`
// and `!{…}`; every other token (including `=>`, `<`, `>`, `|`, `(`, a single
// `.`, …) is literal text. A literal `,` `..` `::` is written escaped (`\,`, etc).
atom      : braceGroup count?
          | complement count?
          | reference
          | anchor
          | macro
          | HEX_ESC
          | ESC
          | litToken
          ;

litToken  : NAME | INT | TEXT | DOT | LT | GT | CARET | EQ
          | LPAREN | RPAREN | STAR | PLUS | PIPE | BANG
          | AT | DOLLAR | HASH | LBRACK | RBRACK
          | ARROW | FIXARROW ;

// `$i` text-ref, `#i` count-ref, `N$M.K…` cross-stage ref. A bare `$`/`#` with no
// index is literal (a `litToken` via the lexer), so a reference needs an index
// (or, for the stage form, an explicit `$`).
reference : DOLLAR INT
          | HASH INT
          | INT DOLLAR (INT (DOT INT)*)?
          ;
anchor    : AT (LT LT? | GT GT?) ;   // @< @> line, @<< @>> document
macro     : AT NAME ;

// ── Prelude declarations (`std.hmk`) ─────────────────────────────────────────
declaration : macroDecl ;
macroDecl   : AT NAME EQ braceBody ;          // @d = 0..9 , @hex = {@d},{@w::..f}

// ── Moustache expression (second layer — the inside of one `{{ … }}`) ─────────
// Applied to each `{{ … }}` interior. Operators,
// tightest to loosest: `*`  `+`  `|` (filter pipe)  `,` (concatenate, in parens).
moustacheExpression : GT? moustacheExpr EOF ; // `{{> … }}` payload marker is optional
moustacheExpr : pipeExpr ;
pipeExpr  : addExpr (PIPE filter)* ;
addExpr   : mulExpr (PLUS mulExpr)* ;
mulExpr   : primary (STAR primary)* ;
primary   : LPAREN moustacheExpr (COMMA moustacheExpr)* RPAREN
          | accessor
          | INT
          | STRING
          ;
accessor  : INT? (DOLLAR | HASH) (INT (DOT INT)*)?   // $  $i  #i  N$M  N$M.K
          | DOT                                       // `.` the current match/value
          ;
filter    : NAME (LPAREN filterArgs? RPAREN)? ;
filterArgs : filterArg (COMMA filterArg)* ;
filterArg  : INT | NAME ;

// ═════════════════════════════════════════════════════════════════════════════
// Lexer
// ═════════════════════════════════════════════════════════════════════════════
//
// No lexer modes and no semantic predicates: a `"…"` template is one STRING
// token, and `//` comments are a documented pre-pass (above), so the lexer never
// needs to know "am I inside a brace / quote / comment". `=>` `<=>` `::` tokenize
// the same everywhere; the *parser* decides whether each is structure (top level,
// brace separators) or literal text (inside a brace arm).

FIXARROW : '<=>' ;
ARROW    : '=>' ;

// A whole template. Escapes (`\"`, `\\`, `\{` to escape a moustache, …) keep it
// from closing early; the interior `{{ … }}` moustaches are a second layer.
STRING   : '"' ( '\\' . | ~["\\] )* '"' ;

LBRACE   : '{' ;
RBRACE   : '}' ;
LBRACK   : '[' ;
RBRACK   : ']' ;

BAND     : '::' ;
RANGE    : '..' ;
DOT      : '.' ;
COMMA    : ',' ;
BANG     : '!' ;
AT       : '@' ;
DOLLAR   : '$' ;
HASH     : '#' ;
PIPE     : '|' ;
STAR     : '*' ;
PLUS     : '+' ;
LPAREN   : '(' ;
RPAREN   : ')' ;
EQ       : '=' ;
LT       : '<' ;
GT       : '>' ;
CARET    : '^' ;

// A fixed-width hex code-point escape (`\xHH` / `\uHHHH` / `\UHHHHHHHH`); HEX_ESC
// wins over ESC by being longer. Any other `\X` is a one-char escape.
HEX_ESC  : '\\' ( 'x' HEXDIGIT HEXDIGIT
                | 'u' HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT
                | 'U' HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT ) ;
ESC      : '\\' . ;

INT      : [0-9]+ ;
NAME     : [A-Za-z_] [A-Za-z0-9_]* ;

NL       : ('\r'? '\n')+ ;

// Spaces/tabs are hidden: they still separate tokens (so two adjacent names stay
// two tokens) but the parser ignores them, matching the implementation where step
// whitespace is stripped (`phase0`) and a moustache expression skips whitespace
// (`engine/_render`). A literal space *inside* a brace (a `{ }` space alphabet)
// collapses to an empty arm — which the σ-grammar already permits — so the
// recognizer still accepts it.
WS       : [ \t]+ -> channel(HIDDEN) ;

// Any other single character (punctuation, Unicode, …) is literal text.
TEXT     : . ;

fragment HEXDIGIT : [0-9a-fA-F] ;
