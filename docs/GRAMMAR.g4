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
 *   • A `"…"` template is one opaque STRING token. The interior of a `{{ … }}`
 *     moustache is a *whitespace-insensitive* mini-language with dotted capture
 *     paths (`2$0.1`); it is compiled by `himark.parser._expr`, not by this
 *     grammar, since it cannot share this lexer (here whitespace is significant
 *     and a `.` is a token).
 *
 * Entry rules:
 *   script    — a whole comment-stripped `.hmk` pipeline file
 *   prelude   — a whole comment-stripped `std.hmk`
 *   statement — one `=>` / `<=>` chain (a snippet)
 *   pattern   — one query (a snippet, no arrows)
 */
grammar GRAMMAR;

// ═════════════════════════════════════════════════════════════════════════════
// Parser
// ═════════════════════════════════════════════════════════════════════════════

script   : sp (scriptItem (sp scriptItem)*)? sp EOF ;
prelude  : sp (declaration (sp declaration)*)? sp EOF ;
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
             | PIPE | LPAREN | RPAREN)+ ;

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
          | LBRACK | RBRACK | ARROW | FIXARROW | NL ;

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
          | ARROW | FIXARROW | NL ;

reference : INT (DOLLAR | HASH) INT?
          | (DOLLAR | HASH) INT
          ;
anchor    : AT (LT LT? | GT GT?) ;
macro     : AT NAME ;

declaration : macroDecl ;
macroDecl   : AT NAME EQ band ;

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
HEX_ESC  : '\\' ( 'x' HEXDIGIT HEXDIGIT
                | 'u' HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT
                | 'U' HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT HEXDIGIT ) ;
ESC      : '\\' . ;
INT      : [0-9]+ ;
NAME     : [A-Za-z_] [A-Za-z0-9_]* ;
NL       : ('\r'? '\n')+ ;
TEXT     : . ;
fragment HEXDIGIT : [0-9a-fA-F] ;