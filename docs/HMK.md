# Himark Specification

**Version:** 0.12.3 | **Status:** Draft | **License:** CC0 1.0 Universal (Public Domain)

<!-- cspell:words himark -->

---

## :jigsaw: Model

A statement has two first-class sides, joined by the **arrow** `=>`: a **query** that matches and a **template** that emits. This section models the query side -- a pattern; the operator tables below index both.

A pattern is **universes** plus operators. A universe `{...}` is a set of strings; as a pattern it matches **exactly one** element and fills **one position** -- that is all a brace is. Patterns compose by **adjacency**: universes side by side concatenate (Cartesian product), each adding one position. Everything else writes, narrows, or operates on a universe.

A bare `{...}` is **always an alphabet**; its punctuation picks which set: **literal** `{cat}`, **union** `{a,b}`, **range** `{a..z}`, **band** `{@d::0..9}`. Only a **leading sigil** changes the reading: `!{...}` subtracts, `@name` is a variable/anchor, `$`/`#`+index is a reference.

**Nesting** is the one structural device, split by whether a nested brace is a _member_ or an _adjacent factor_:

- **member** (comma-listed or lone) -> **object**: one position an enclosing operator sees as **one opaque point** -- it can't tell the interchangeable spellings ("faces") apart. `{{a,A}}` is one case-folded position. **Value-bearing** (see [Congruence](#congruence)).
- **adjacent** -> **grouping brace**: packaging so an operator binds the whole sequence. `{of{black}{quartz}}` is one operand. **Content-only** (see [Captures](#captures)).

```proto
{a,A}          // one alphabet, two points: 'a' or 'A'
{{a,A}}        // one object, one position: 'a'/'A' folded to one value
{cat}{dog}     // adjacency: two positions, 'catdog'
{{cat}{dog}}   // grouping: those two as one operand
```

**Match** -- the query side:

| Operator   | Name            | Role                                                 |
| ---------- | --------------- | ---------------------------------------------------- |
| `{...}`    | Universe        | set of strings; matches one element                  |
| `,`        | Union           | `{a,b}` is `a` or `b`                                |
| `..`       | Range / band    | value band in an alphabet (`{a..z}`, `{@d::0..255}`) |
| `{X}{Y}`   | Adjacency       | concatenate -- Cartesian product                     |
| `!{...}`   | Subtractive     | everything _not_ in `{...}` (ambient Unicode)        |
| `{U::...}` | Alphabet prefix | band over an alphabet (`{@d::0..9}`)                 |
| `[count]`  | Repetition      | base-10 count universe (`[n]`, `[x..y]`, `[a,b,c]`)  |

**Emit** -- the template side, inside `"..."`:

| Operator      | Name      | Role                                          |
| ------------- | --------- | --------------------------------------------- |
| `{{ ... }}`   | Moustache | emit a captured value into output             |
| `$i` `#i` `$` | Accessor  | a group's text / count, or `$` the current match  |
| `\|`          | Filter    | transform an emitted value (`trim`, `indent`) |
| `,`           | Concat    | join values in a moustache (parens only)      |

**Join** -- `=>` feeds each match into the next step; `<=>` re-applies over the whole document until it settles (a fixed point).

A position holds one **point** -- a **primitive** (one char/string) or an **object** (nested, interchangeable members). `[count]` repeats **one point** and is **unidimensional**: it sees only its own level, so a nested universe is one opaque object whose faces are free per position ([Congruence](#congruence) says why; [Repetition](#repetition) gives the count forms). Point **value** is fixed under [Values and ordering](#values-and-ordering).

---

## Variables

Named alphabets are declared in the **prelude** (`himark/std.hmk`), the single centralized declaration file loaded before every run. Each `@name = <source>` line binds a **named alphabet**: `@name` is a variable that resolves to that Himark source wherever it is used, so the engine holds no built-in alphabet knowledge -- it only ever sees the ranges and congruence classes the source resolves to. The shipped set:

| Name     | Expands to                     |
| -------- | ------------------------------ |
| `@d`     | `0..9`                         |
| `@l`     | `a..z`                         |
| `@u`     | `A..Z`                         |
| `@s`     | `\n,\r, ,\t`                   |
| `@w`     | `0..9,{a,A},{b,B},...,{z,Z},_` |
| `@hex`   | `{@w::0..f}`                   |
| `@b256`  | `U+0000..U+00FF` (every byte)  |
| `@ascii` | `U+0000..U+007F`               |
| `@uni`   | `U+0000..U+10FFFF`             |

---

## :anchor: Anchors

Zero-width, capture the empty string. A single angle is a **line** edge, a double angle the whole **document** edge; `<` is a start, `>` an end:

| Anchor        | Matches                                    |
| ------------- | ------------------------------------------ |
| `@<` / `@>`   | start / end of **line** (pos 0 or by `\n`) |
| `@<<` / `@>>` | start / end of the **document**            |

A whole line is `{@<}!{\n}[1..]{@>}`.

---

## Escaping

Backslash makes the next char literal. Only **framing** chars ever need it: `{` `}` `[` `]` `"` `\`, plus `$` `#` where they'd read as a reference, `=` where it would read as a definition's `=` (a literal top-level `=` is `\=`, or just `{=}`), and `::` where it would read as a band separator. A **single `:` is always literal** and never needs escaping; to write a literal **`::`** escape either colon (`\::`). All else (`(` `)` `.` `*` `+` `-` `?` `|` `:` ...) is already literal. Invisibles use C spellings `\n` `\r` `\t`; a space is a space. So `{(a|b)?}` matches the literal `(a|b)?`, and `{std\::vector}` matches the literal `std::vector`.

A code point is a fixed-width hex escape, C/Python spelling: `\xHH` (a byte), `\uHHHH` (BMP), `\UHHHHHHHH` (full plane). So `\x41` is `A`, and the byte alphabets are spelled `\x00..\xff` (`@b256`), `\x00..\U0010ffff` (`@uni`). Fixed width (not `\u{...}`) keeps the trailing hex from ever reading as a brace.

---

## Universes

`,` unions atoms, `..` bounds them into an ordered range, adjacency concatenates (Cartesian product). A universe matches **one** element; a run is an explicit `[count]`.

```proto
{a,b,c}        // a or b or c
{aa..zz}       // every string 'aa'..'zz' by value (Unicode)
{a..z}{A..Z}   // adjacency: aA,aB,...,zZ
```

> `..` is **one-axis**. `{a..z}..{A..Z}` (range between two sets) has no single order -> rejected; write `{a..z}{A..Z}` (product), `{a..z,A..Z}` (either case), or `{{a,A},...,{z,Z}}` (folded).
>
> An unnamed multi-char range is over **ambient Unicode**: `{aa..zz}` is the value band, including non-letter strings between. For "two lowercase letters": `{@l::aa..zz}`.

### Congruence

A bare `,` **lists points** the enclosing context can tell apart: `{a,b}` = `{a..b}`, two primitives. **Nesting hides the choice.** A `{...}` used as a _member_ becomes an **object** -- opaque to whatever encloses it, which sees one point and can't distinguish its faces. That indistinguishability _is_ congruence: to a value operator the faces share one ordinal; under `[count]` they're free per position, because the operator never sees which face it stamps.

```proto
{{a,A}}                       // one position, 'a' or 'A'
{{a,A}}[2]                    // free per position: 'aa','aA','Aa','AA'
{{color,colour},{gray,grey}}  // faces can be strings
```

> Congruence is brace depth: `{a,A}` two primitives an operator picks between, `{{a,A}}` one position it can't see into. `{@w}` nests where it folds (`{0..9,{a,A},...,_}`), so `@w`/`@hex` are case-insensitive.

---

## Values and ordering

Bands, counts, and references all read **value**. An alphabet is an **ordered sequence of points** with an **increment** (successor) and **equality**. Each point has a 0-based **ordinal** (its index in the alphabet in force -- a band's prefix, else ambient `@uni`). An **object** is opaque to a value operator -- its faces share one ordinal, so all spellings compare equal.

A single point's value is its ordinal. A string $p_0 \ldots p_{k-1}$ over alphabet size $b$ is positional, most-significant-first:

$$\text{value} = \sum_{i} \text{ordinal}(p_i) \cdot b^{k-1-i}$$

Over `@d` `255`=255; over `@l` `aa`=0, `zz`=675. Comparison is **by ordinal, never raw codepoint** (they coincide only for `@uni`, `@ascii`, `@b256`). This is why `@w` slices: ordinals put `a/A`=10 ... `f/F`=15 ... `z/Z`=35, `_`=36, so `0..f` is ordinals 0--15 and stops below `_`.

**A capture is `<alphabet, range, value>`** -- the alphabet matched under (codec), the range in force (band, which fixes **width**), the value (ordinal). The value is what a **band** or **reference** compares (`{@d::0..$0}`, `{$0}`).

It projects back to **text** -- the value rendered through its alphabet (codec + width), which is what `{{ $i }}` produces.

A **named** alphabet makes value meaningful: `{@d}` on "11" is integer 11; bare `{0..9}` on "11" is codepoints 49,49. `{@d}`"11" and `{@l}`"l" are both value 11 (different base/width, same value).

> **Matching position is concrete text** -- the triple is a template/value-time view. A reference re-matches the **exact text**: `{{a,A}}{$0}` matches `aa` or `AA`, never `aA`.

---

## Bands

A **band** restricts an alphabet's values. The alphabet is the **payload** (any universe); `::` adds a band -- a `..` range, a `,`-union of ranges/values, or a single value, over the alphabet's values. `{U::x..y}` restricts **inclusively** to values `x`..`y` by [value](#values-and-ordering) (MSB-first). Drop the prefix for an ambient band (`{::0..255}`); drop the band for the bare alphabet (`{@d}`).

```proto
{@d::0..255}        // decimal 0--255
{@d::5}             // single value '5' over a typed head
{a,b,g..z::m..p}    // bare alphabet, banded m--p
{::9..12,1..5}      // ambient union: 9,10,11,12,1,2,3,4,5
```

**When `::` separates.** A brace is a **band** when its body holds a **top-level `::`**: that first `::` splits the **payload** (left, the alphabet) from the **band** (right). Every other `::` and every single `:` is literal -- the escaping mechanics, and `{std\::vector}`, are under [Escaping](#escaping).

> The separator is purely structural: band-ness comes from a top-level `::` alone, with no inspection of the head or the right side. **Meaning** still wants a **typed head** for a single-value or union band: `{@d::5}` is `5` over `@d`, `{@d::1,3,5}` the set {1,3,5}. A lone-value band over a bare range (`{a..z::b}`) is degenerate -- the value just restates a literal, so write `{b}`.

Either endpoint may be omitted (`{@d::0..}` is $\geq 0$, `{@d::..255}` is $\leq 255$); **both** omitted is a compile error (write `{@d}`).

A band's **width follows endpoint widths**: `{@d::00..99}` is two wide, `{@d::000..999}` three, `{@d::0..999}` one-to-three (narrower endpoint = min, wider = max). For a fixed width regardless of value use a count (`{@d}[3]`) -- padding is never inferred from a bound's spelling.

An endpoint is a value, so a **reference** may stand in, resolved at match time by magnitude: `{@d::0..$0}` matches a decimal $\leq$ group 0 (width-agnostic -- more positions than the referent is larger), `{@d::$0..}` matches one $\geq$ it. A reference that didn't capture, or a referent outside the alphabet, does not resolve. `\$` is literal.

```proto
{@d}[1..],{@d::0..$0}    // two decimals, second <= first
```

### Subtraction

`!{...}` is the **subtractive universe**: one char that does **not begin any member of `{...}` at this position**. Plain complement is the one-char case (`!{a}` = any char but `a`); a union applies each member's condition. A **multi-char** member is a **break**: `!{ab}` is to `!{a,b}` as `{ab}` is to `{a,b}` -- comma lists members, adjacency makes one member. So a run `!{```}[1..]` stops at the **nearest** sequence -- scanning to a delimiter with no lazy operator:

```proto
{@d,@l,@u,!{0,l,I,O}}    // base58: digits + letters minus four ambiguous chars
{<!--}!{-->}[1..]{-->}   // HTML comment: body runs to the nearest -->
```

> A break is **not** per-char exclusion -- `!{()}` passes a lone `(` or `)`, stopping only before the sequence `()`. To exclude either: `!{(,)}`.

---

## Repetition

`[count]` repeats the preceding universe. The count is itself a **universe** over **base-10 non-negative integers**: bare = exact, `,` unions, `..` ranges; an omitted floor = **0**, an omitted ceiling = unbounded.

| Form      | Meaning          |
| --------- | ---------------- |
| `[n]`     | exactly `n`      |
| `[x..]`   | `x` or more      |
| `[..y]`   | 0 up to `y`      |
| `[x..y]`  | `x` to `y`       |
| `[..]`    | zero or more     |
| `[a,b,c]` | `a`, `b`, or `c` |

Only the integer operators apply: adjacency is meaningless, and a non-integer count (`[a..z]`, `[!{@s}]`) is a compile error. References fit: `[#i]` repeats as group `i` did, `[#0..#1]` ranges between two captured counts.

A run is **greedy**: it takes the longest count in range that still lets the rest match, backing toward the floor if the tail fails (no further than `x` for `[x..y]`) -- so `!{ }[1..]` is a whole word. No lazy operator: to stop at the **nearest** delimiter, subtract it.

`[n]` repeats **one point**: a primitive verbatim (`{a..z}[3]`=`aaa`), an object's members free (`{{a..z}}[3]` = any three letters). An **alphabet of objects** stays within one object: `{{a,A},{c,C}}[2]` is `{a,A}{a,A}` or `{c,C}{c,C}`, never a cross like `ac`. A **grouping brace** under `[count]` matches a **fresh instance per repetition**, captured as one string.

```proto
{a..z}[2,4,6]               // same letter 2, 4, or 6 times
{{|}!{|,\n}[1..]}[2..]{|}   // 2+ '|'+cell units, each cell different
```

---

## Captures

Every `{...}` in matching position is a **capture group**, numbered from **0** in source order (assigned when the opening brace is read). Numbering is **flat** -- each group takes the next number.

A **grouping brace** (a body that concatenates constructs) captures its full text as **one** group, one number; its inner braces aren't numbered (the same collapse `[count]` performs). A **bare** grouping brace is `{...}[1]`: `{1{am,pm}}` captures `1am`/`1pm` as one `$0`, where `{1}{am,pm}` captures the same text as two. Capture shape only.

Single-position constructs -- object `{{a,A}}`, band `{A::x..y}`, subtractive `!{...}`, reference -- are each **one** group regardless of inner braces. An **anchor** (`{@<}`) is the exception: zero-width and non-capturing, it takes **no** number, so the groups around it stay contiguous. A repeated group `{X}[n]` is one number, captured as one string.

Input `### Sphinxofblackquartz`, expression `{#}[1..]{ }{Sphinx}{of{black}{quartz}}`:

| Group | Text                      | Why                                         |
| ----- | ------------------------- | ------------------------------------------- |
| full  | `### Sphinxofblackquartz` | full match                                  |
| 0     | `###`                     | `{#}[1..]`                                  |
| 1     | space                     | `{ }` is a group                            |
| 2     | `Sphinx`                  | `{Sphinx}`                                  |
| 3     | `ofblackquartz`           | `{of{black}{quartz}}` grouping brace, whole |

> Group 3's inner `{black}`/`{quartz}` are structural, unnumbered (next sibling = `4`). To address separately, lift to top level: `{of}{black}{quartz}` -> `3,4,5`.
>
> Templates address captures via `{{ [stage]$[index] }}`: `{{ $ }}` current stage whole, `{{ $j }}` its group `j`, `{{ i$ }}` stage `i` whole, `{{ i$j }}` stage `i` group `j`.

### Self-references

A reference: optional **stage** (a leading number), **sigil** (`$` text, `#` count), optional **index** `i`. Groups 0-based in document order.

| Form             | Reads                                                     |
| ---------------- | --------------------------------------------------------- |
| `{$i}` / `{N$i}` | the **text** of group `i` -- current match, or stage `N`  |
| `{#i}` / `{N#i}` | the **count** of group `i` -- current match, or stage `N` |
| `{N$}`           | stage `N`'s **whole** text (plain text)                   |
| `[#i]` / `[N#i]` | (in a count) repeat as group `i` did                      |

```proto
{a..z}{$0}        // doubled letter: 'aa','bb' (not 'ab')
{a}[2..]{-}[#0]   // as many '-' as 'a': 'aaa---','aa--'
```

An index names a **top-level group** of the addressed step, resolved at **compile time** (an index naming no group is a compile error). At match time, a reference whose group exists but didn't capture (an unmatched alternative, a zero-count run) **does not match**. A bare `$`/`#` is literal (`\$` to be explicit); a sigil is a reference only with a stage or index, so `{#}` is `#` and `{#0}` is group 0's count.

> In **matching** position a reference re-matches concrete text; only a band endpoint (`{@d::0..$0}`) reads it as a **value** instead.

---

## :repeat: Transformers

`=>` runs a chain of steps -- each a **query** (matcher) or a **template** (plain text, no matchable `{...}`). The first step **bootstraps the branches**: a **query** starts one branch per match, while a leading **template** starts a single branch over the **whole document** (`{{$}}` is the entire input) -- so a bare leading template replaces the document and `"<wrap>{{$}}</wrap>"` wraps it. After the first step, **each step may be either, in any order**. Each branch is transformed independently and outputs **whatever it commits**:

- a **query** matches within the branch and commits each transform in place, keeping the text between. A query that matches nothing **stops** the branch (no output) -- so a leading query is a **guard**. To gate on a _computed_ value, a template emits it and a following query re-matches it (`{$0}` for equality, `{@d::0..$0}` for magnitude).
- a **template** renders and **commits** (never rolled back) and is **not** terminal: a later query matches the rendered text, a later template wraps it.

A template is literal text plus `{{ ... }}` moustaches. The full render **lands**; text outside the moustaches **decorates** -- it lands but never flows. **Each `{{ ... }}` is its own branch**: its value flows to the next step, is transformed there, and the result is spliced back over just that moustache, the decoration between kept. A template is thus a query's mirror -- a query branches per match, a template per moustache. Use the `,` form to flow several values as **one** branch: `"{{ ("<h", #0, ">") }}"` flows `<h1>` whole, where `"{{"<h"}}{{#0}}{{">"}}"` flows three. A template with **no** moustache flows its whole render as one branch.

> **Arrows are top-level only.** `=>` and `<=>` are recognised as arrows only outside every `{...}`, `[...]`, and `"..."`. Inside a quoted template they are literal text, so a template may contain `=>` freely and never needs to escape it. Keep arrows out of brace and count bodies too -- there they are literal.

Stages are numbered by `=>` position, **counting queries only** (a template doesn't advance the count), so `{{ i$j }}` and `{N$i}` stay stable when a template is inserted.

A statement's result is **(span, output)** pairs. The semantics is **splice**: every statement, at every depth, lays its outputs back over their spans and keeps the text between -- which lets templates compose, branches nest, and `<=>` iterate. A flat **list** (spans dropped) is just the **extraction** view of the same splice.

```proto
{#}[1..6]{ }[1..]!{\n}[1..] => "<h{{#0}}>{{$2}}</h{{#0}}>"   // "# Hello" -> "<h1>Hello</h1>"
{@d::0..}{=}{$0} => "ok" // gate: '7=7' passes, '7=8' is dropped
"<html>{{$}}</html>"     // leading template: wrap the whole document
```

### Fixed point

`<=>` instead of `=>` **re-splices over the whole document until the result stops changing** -- the splice version of a `while` loop. Each pass is an ordinary `=>` splice; passes repeat until one makes no change. Use it for input-dependent iteration: peel the innermost tag pair, mask an interior newline, swap an out-of-order pair until sorted.

```proto
{(}!{(,)}[..]{)} <=> "{{$1}}"                // strip innermost (...), deepest first
{@d::0..}{,}{@d::0..$0} <=> "{{$2}},{{$0}}"  // bubble-sort: swap adjacent out-of-order pairs
```

The rule must **contract** toward a fixed point; one that grows the document (`{a} <=> "aa"`) or oscillates never settles. The runner halts on a pass that lengthens or repeats a state; a provably non-contracting rule is rejected at compile time. Use `=>` for a single pass; only a single statement can be looped, not a whole group.

### Expressions

A `{{ ... }}` moustache holds one **expression** over captured values, and is recognised **only inside a quoted template**. Outside a quote, `{{` is two nested universe braces (an object) and carries no expression meaning -- a query never reads moustache syntax, and a template never reads universe syntax. To match a literal `{{` inside a quote, escape it (`\{{`).

A moustache evaluates to one **value**, rendered to text. Operands: accessors (`$` the current subject -- the whole text flowing into this step; `$i`, `#i`, `i$`, `i$j`, `i#j`), integer/string literals, and parentheses. A bare `$` is the whole match, so it differs from `$0`, the **first capture group** (groups are 0-based, not 1-based, so there is no "`$0` is the whole match" convention). `.` is a deprecated spelling of bare `$`. Two operators, tightest to loosest:

- `|` -- filter pipe (applies to everything on its left)
- `,` -- concatenate, **inside parentheses only**

Both left-associative; parens override. So `("<h", #0, ">")` is one value (the three concatenated), and `$2 | trim` pipes group 2 through a filter. The `{{`/`}}` boundaries set the expression context, so quotes inside are string delimiters.

### Filters

A moustache value may be piped through **filters** -- a small, fixed, native set of pure string transforms: `{{ accessor | f | g }}`. Filters are **template-only** (the matcher stays declarative) and take **no arguments**; everything in a template is text.

| Filter   | Effect                            |
| -------- | --------------------------------- |
| `trim`   | strip leading/trailing whitespace |
| `indent` | prefix every line with one tab    |

`indent` is a **line** filter -- a tab on every line -- so indentation **accumulates** under an inside-out wrap (each enclosing pass re-indents the body), which is how a nested block ends up as deep as its nesting.

---

## The `.hmk` file

A `.hmk` file is a **pipeline** -- an ordered list of [statements](#repeat-transformers), each spliced over the whole document in turn (the output of one is the input to the next). The file just **names the sequence**; the splice semantics are unchanged. Run one over a document with the CLI:

```sh
himark transpile in.md --script pipeline.hmk --out out.md
```

**One statement per logical line.** A statement may span several **physical** lines two ways: a `{...}` group or `"..."` template that runs long stays one logical line (a newline _inside_ a brace or quote does not end the statement), and a line whose first token is an **arrow** (`=>` / `<=>`) **continues** the previous statement -- the chain wrapped across lines for readability. Any other non-blank line **starts** a new statement; a blank line is ignored.

**`//` starts a line comment** -- but only at brace/quote **depth 0**, running to end of line. So a top-level `// note` is stripped, while `{//}` (a literal `//` alphabet) and a `http://...` inside a brace or template survive untouched.

**Insignificant whitespace is stripped in the same depth-aware pre-pass.** Spaces and tabs are literal text **only inside a `{...}` brace body or a `"..."` template** -- so `{ }` matches a space and `@s`'s ` ` member is the space character -- and are dropped everywhere else: around steps and arrows, between top-level constructs (`{a} {b}` == `{a}{b}`), and inside a `[count]` (`[1 .. 6]` == `[1..6]`).

```proto
// tidy: one statement, wrapped onto continuation lines
{@<}{#}[1..6]{ }[1..]!{\n}[1..]
  => "<h{{#0}}>{{$2}}</h{{#0}}>"     // a continuation line (leading arrow)

{ }[2..]{\n} => "<br/>\n"            // the next statement
```

**Definitions.** A script line `@name = <body>` binds `@name` to Himark source -- the **same mechanism** as a [prelude alphabet](#variables), scoped to this file. It is a definition, not a statement: the lone `=` (never `=>`) after the name marks it. The body is any pattern fragment, so a recurring shape is named once and reused:

```proto
@head = {@<}{#}[1..6]{ }[1..]      // an ATX head marker at line start
@eol  = !{\n}[1..]                 // the rest of a line

@head@eol => "<h{{#0}}>{{$2}}</h{{#0}}>"   // expands to the full heading rule
```

A definition resolves to its body wherever `@name` is used -- **as if inlined** -- and leaves no trace downstream (the compiled pipeline is identical to the hand-inlined one). Four rules keep them honest:

- **Lexical order.** A definition must precede the statements that use it; an unresolved `@name` is left as literal text, not flagged.
- **No shadowing, no redefinition.** A local name that collides with a prelude alphabet or an earlier local is a compile error -- a name is bound **once** (single-assignment), not reassigned.
- **Captures number over the inlined fragment.** `$i`/`#i` count groups by document order at the **use site** -- a resolved fragment's braces number where they land -- so a fragment is only safely composable when it carries no internal self-references. Above, the author must know `@head` exports groups 0--1 (`#0` is the heading level) and `@eol` adds group 2 (`$2`).
- **Templates are opaque.** A `@name` inside a `"…"` template is literal text, never resolved -- a template never reads alphabet syntax, just as a query never reads moustache syntax.

**The prelude.** `himark/std.hmk` is the same file shape, but its lines are **declarations**, not statements, and it loads **before every run**:

- `@name = <source>` binds a [named alphabet](#variables): `@name` resolves to that Himark source wherever used (`@d = 0..9`, `@hex = {@w::0..f}`). A script-local definition is the same form, scoped to one file.

A formal grammar for both file shapes (script and prelude) is in [`docs/GRAMMAR.g4`](./GRAMMAR.g4).
