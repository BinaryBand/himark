/*
 * GRAMMAR.g4 — an ANTLR4 grammar for the Himark (HMK) ANTLR branch (v0.12).
 *
 * This is the *surface* grammar: it describes what a human writes in a `.hmk`
 * script, in the `std.hmk` prelude, or as a one-off snippet — BEFORE any macro
 * expansion or structural rewrite.
 *
 * The four divergences from mainline:
 *   1. a band is `::`  — a single `:` is always literal text;
 *   2. no implicit first-step wrap — a step is an explicit run of constructs;
 *   3. `=>` / `<=>` are arrows only at top level — inside `{…}` or a count they
 *      are literal, and inside a `"…"` template they live inside one STRING token;
 *   4. `{{ }}` is template-only.
 *
 * Layering:
 *   • Comments and statement-splitting are a stateful pre-pass.
 *   • A `"…"` template is one opaque STRING token; its `{{ … }}` interiors are
 *     extracted by `_compiler` and each parsed by the `moustacheExpression` entry
 *     rule. The moustache is whitespace-insensitive, so `_compiler` strips the
 *     body's insignificant whitespace before this lexer (where a space is a token)
 *     sees it — the same pre-pass discipline queries use.
 *
 * Entry rules:
 *   script    — a whole comment-stripped `.hmk` pipeline file
 *   statement — one `=>` / `<=>` chain (a snippet)
 *   pattern   — one query (a snippet, no arrows)
 *   moustacheExpression — the interior of one `{{ … }}` (second layer)
 */
grammar GRAMMAR;

// ═════════════════════════════════════════════════════════════════════════════
// Parser
// ═════════════════════════════════════════════════════════════════════════════

script   : sp (scriptItem (sp scriptItem)*)? sp EOF ;
snippet  : sp statement sp EOF ;
patternOnly : sp pattern sp EOF ;

scriptItem : definition | statement ;
definition : AT NAME EQ pattern ;
sp        : NL* ;

statement : step (sp arrow sp step)* ;
arrow     : ARROW | FIXARROW ;

step      : template | pattern ;
template  : STRING ;

pattern   : factor+ ;
factor    : (braceGroup | complement | literalRun) count? ;

complement : BANG braceGroup ;
braceGroup : LBRACE band RBRACE ;

literalRun : (TEXT | ESC | HEX_ESC | DOT | RANGE | BAND | COMMA
             | NAME | INT | AT | DOLLAR | HASH | LT | GT
             | PIPE | LPAREN | RPAREN
             | PLUS | MINUS | STAR | SLASH | PERCENT
             | AMP | CARET | TILDE | BACKTICK)+ ;

count     : LBRACK countBody RBRACK ;
countBody : countArm (COMMA countArm)* ;
countArm  : countTerm RANGE countTerm        # closedCount
          | countTerm RANGE                  # openUpperCount
          | RANGE countTerm                  # openLowerCount
          | RANGE                            # fullOpenCount
          | countTerm                        # exactCount
          ;
countTerm : INT | countRef ;
countRef  : HASH INT ;

band      : universe BAND universe           # valueBand
          | BAND universe                   # ambientBand
          | sequence                        # sequenceBrace
          | universe                        # bareAlphabet
          ;

// A grouping/sequence brace: a concatenation containing at least one nested
// construct (`{of{black}{quartz}}`, `{{a,A}}`, `{!{x}!{y}[..]}`). seqText excludes
// top-level ',' '..' '::', so a real alphabet/band fails this alternative and falls
// through to bareAlphabet/valueBand. Listed before bareAlphabet so an input both
// could match (e.g. `{a{b}}`) resolves to a sequence.
sequence  : seqText? seqUnit (seqText | seqUnit)* ;
seqUnit   : braceGroup count? | complement count? ;
seqText   : seqAtom+ ;
seqAtom   : reference | anchor | macro | HEX_ESC | ESC | seqLit ;
// BANG is intentionally absent: a `!{…}` in a sequence is always a `complement`
// (a `seqUnit`), never literal text, matching the bareAlphabet `atom` precedence.
seqLit    : NAME | INT | TEXT | DOT | LT | GT | EQ
          | LPAREN | RPAREN | PIPE | AT | DOLLAR | HASH
          | LBRACK | RBRACK | ARROW | FIXARROW | NL
          | PLUS | MINUS | STAR | SLASH | PERCENT
          | AMP | CARET | TILDE | BACKTICK ;

universe  : arm (COMMA arm)* ;
arm       : term                             # single
          | term RANGE term                 # closedRange
          | term RANGE                       # openUpper
          | RANGE term                       # openLower
          ;
term      : atom+ ;

atom      : braceGroup count?
          | complement count?
          | reference
          | anchor
          | macro
          | HEX_ESC
          | ESC
          | litToken
          ;

litToken  : NAME | INT | TEXT | DOT | LT | GT | EQ
          | LPAREN | RPAREN | PIPE | BANG
          | AT | DOLLAR | HASH | LBRACK | RBRACK
          | ARROW | FIXARROW | NL
          | PLUS | MINUS | STAR | SLASH | PERCENT
          | AMP | CARET | TILDE | BACKTICK ;

reference : INT (DOLLAR | HASH) INT?
          | (DOLLAR | HASH) INT
          ;
anchor    : AT (LT LT? | GT GT?) ;
macro     : AT NAME ;

// The interior of one `{{ … }}` moustache (a second-layer entry rule). A tiny
// whitespace-insensitive expression: accessors (`.`, `$i`, `#i`, `2$0.1` a
// cross-stage dotted sub-capture), string/int literals, parenthesised
// `,`-concatenation, `|` filter pipes, and value operators (arithmetic
// `+ - * / %`, bitwise `& ^ ~ << >>` and backtick-or, in the precedence cascade
// below -- see docs/ALGEBRA.md). `_compiler` extracts the body and strips
// insignificant whitespace before this lexer sees it.
moustacheExpression : pipeExpr EOF ;
pipeExpr  : orExpr (PIPE filter)* ;
orExpr    : xorExpr (BACKTICK xorExpr)* ;
xorExpr   : andExpr (CARET andExpr)* ;
andExpr   : shiftExpr (AMP shiftExpr)* ;
shiftExpr : addExpr ((LT LT | GT GT) addExpr)* ;
addExpr   : mulExpr ((PLUS | MINUS) mulExpr)* ;
mulExpr   : unary ((STAR | SLASH | PERCENT) unary)* ;
unary     : TILDE unary | primary ;
primary   : LPAREN pipeExpr (COMMA pipeExpr)* RPAREN
          | accessor
          | INT
          | STRING
          ;
accessor  : INT? (DOLLAR | HASH) (INT (DOT INT)*)?
          | DOT
          ;
filter    : NAME ;

// ═════════════════════════════════════════════════════════════════════════════
// Lexer
// ═════════════════════════════════════════════════════════════════════════════

FIXARROW : '<=>' ;
ARROW    : '=>' ;
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
LPAREN   : '(' ;
RPAREN   : ')' ;
EQ       : '=' ;
LT       : '<' ;
GT       : '>' ;
PLUS     : '+' ;
MINUS    : '-' ;
STAR     : '*' ;
SLASH    : '/' ;
PERCENT  : '%' ;
AMP      : '&' ;
CARET    : '^' ;
TILDE    : '~' ;
BACKTICK : '`' ;
HEX_ESC  : '\\' ( 'x' HEXDIGIT HEXDIGIT
                | 'u' HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT
                | 'U' HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT ) ;
ESC      : '\\' . ;
INT      : [0-9]+ ;
NAME     : [A-Za-z_] [A-Za-z0-9_]* ;
NL       : ('\r'? '\n')+ ;
TEXT     : . ;
fragment HEXDIGIT : [0-9a-fA-F] ;