# Himark Grammar (normative)

**Version:** 0.9.6-experimental
**Status:** Normative reference
**License:** CC0 1.0 Universal (Public Domain)

<!-- cspell:words himark moustache subtractive countref backref stageref unescape -->

This document fixes the **syntax** of Himark (HMK): what a parser must accept, how it tokenizes, and the tree each construct resolves to. It is the companion of [HMK.md](HMK.md) (which explains *meaning* and *behaviour*) and is meant to lock the surface language so future changes are deliberate.

The reference implementation is [himark/parser/](../himark/parser/) (phases 0–3), [himark/parser/_count.py](../himark/parser/_count.py), [himark/tools/precompiled.py](../himark/tools/precompiled.py) (the script/statement layer), and [himark/engine/_render.py](../himark/engine/_render.py) (templates). Where this grammar and the implementation disagree, **the implementation is authoritative** and the discrepancy is a bug in one of them.

---

## 1. Notation

A leaning EBNF:

| Form        | Meaning                                              |
| ----------- | ---------------------------------------------------- |
| `'x'`       | a literal terminal (the characters `x`)              |
| `a b`       | `a` followed by `b` (concatenation)                  |
| `a \| b`    | `a` or `b` (ordered: earlier alternatives win)       |
| `( a )`     | grouping                                             |
| `a?`        | zero or one `a`                                      |
| `a*`        | zero or more `a`                                     |
| `a+`        | one or more `a`                                      |
| `ANY`       | any single Unicode scalar value (U+0000–U+10FFFF)    |
| `« … »`     | a prose **constraint** the context-free form can't state |

Himark is **not** context-free: braces `{…}`, counts `[…]`, quotes `"…"`, and backslash escapes are matched by depth-aware scanning, and several productions depend on a sub-string being a *singleton* or *materialisable*. Such rules appear as `« Constraint: … »` annotations and are part of this specification.

Two scanning primitives are used throughout and assumed by every `*-top` rule:

- **Escape-skipping.** A backslash and the character after it (`\` `ANY`) are one unit and are never a delimiter — `\{`, `\,`, `\$`, `\` are literals.
- **Depth tracking.** `{` and `[` open depth; `}` and `]` close it (floored at 0). A *top-level* separator is one found at depth 0. (Quote depth is tracked only where stated — at the script-line and template layers, **not** by the `=>`/`<=` arrow splitter.)

---

## 2. The processing pipeline

A source file is lowered through fixed layers; each row is a grammar in this doc:

```
.hmk file
  └─ §3  Script        split into statements (logical lines, // comments, => continuation)
        └─ §4  Statement   split on top-level => / <= into ordered steps
              └─ §5  Preprocess  @macro expansion, structural rewrites, implicit {…} wrap
                    └─ §6  Tokens     {…}[…] braces, !{…}, "…" quotes, escapes, leaf text
                          └─ §7  σ-grammar  resolve each brace interior to a semantic node
                                §8  Counts     resolve each [count] modifier
        (template steps) §9  Moustache  {{ accessor | filter … }} rendering
```

Phases 0–3 (§4–§7) run per step; §3 and the `<=` rewrite (§4) run once per file.

---

## 3. Script files (`.hmk`)

A script is an ordered pipeline of statements, each spliced over the document in turn. Reference: [precompiled.py](../himark/tools/precompiled.py) `load_script` / `split_statements`.

```
script      = logical_line*
logical_line= ( ANY* )                  « split on newlines at brace/quote depth 0 »
```

A script is read into **statements** by these rules, each applied at brace **and quote** depth 0 (so braces, `[…]` counts, and quoted templates that span physical lines stay one logical line, and a `//` or `=>` inside them is content):

1. **Comment.** `//` and everything after it on a logical line is removed.
2. **Blank.** A line that is empty after comment-stripping and trimming is ignored.
3. **Continuation.** A logical line whose first non-space characters are `=>` *appends* to the current statement (a multi-line `=>` chain).
4. **New statement.** Any other non-blank logical line begins a new statement.

```hmk
{pattern}                 // a statement…
  => "template"           // …continued by a leading =>
  => {next pattern}       // a trailing comment is stripped at depth 0

{another statement}
```

> A `//` is a comment **only at depth 0**. Inside `{…}`, `[…]`, or `"…"` the two slashes are ordinary characters.

---

## 4. Statements, arrows, and steps

A statement is a chain of steps joined by a single arrow. Reference: [phase0.py](../himark/parser/phase0.py) (the `=>` splitter) and [precompiled.py](../himark/tools/precompiled.py) `_split_fixed_point`.

```
statement   = step ( arrow step )*
arrow       = '=>' | '<='
step        = ANY*                        « one inter-arrow slice, trimmed »
```

**Constraints**

- `« An arrow is recognised only at top level »` — depth-aware over `{…}` and `[…]`, skipping `\`-escapes. A lone `<` or `>` is plain text, so a template's `<strong>` is never read as an arrow.
- `« Arrow splitting does not track quote depth »` — an `=>` or `<=` at brace depth 0 *inside* a `"…"` template still splits. Keep arrows out of quoted text.
- **Fixed point.** A statement using `<=` is identical in shape to its `=>` form; every top-level `<=` is rewritten to `=>` and the statement's **first step** is flagged so the runner re-splices the whole statement until the document stops changing (see [HMK.md §Fixed point](HMK.md#fixed-point)). `<=` is an arrow **only at top level**; inside `{…}`/`[…]` it is plain text.

**Step roles.** The first step is always a **query** (a pattern/matcher). A later step is a **query** if it contains a matchable `{…}`, else a **template** (constant text rendered as-is). A step that *is* nothing but literal leaves is a template (reference: [_render.py](../himark/engine/_render.py) `is_template`).

---

## 5. Preprocessing (macros, rewrites, implicit wrap)

Per step, before tokenizing. Reference: [phase1.py](../himark/parser/phase1.py).

### 5.1 Macro expansion

```
macro_use   = '@' macro_name              « macro_name ∈ the macro table, §Appendix B »
```

`@name` (matched with a trailing word boundary, longest name first) is replaced by its source text. Expansion repeats until stable (max 10 passes); a name that never resolves — circular or undefined — is a **compile error**. A bare name with no `@` is literal text (`{dec}` matches the string `dec`).

### 5.2 Structural rewrites

Pre-tokenization sugar that inspects braces and renumbers groups (reference: [rewrites.py](../himark/parser/rewrites.py); because they are structural, they live as code rules there rather than in the declaration prelude):

| Surface form            | Rewrites to                         | Meaning                                   |
| ----------------------- | ----------------------------------- | ----------------------------------------- |
| `{X[#]}[1..]`           | a free first `X` + count-bound rest | self-binding repeat count                 |
| `[x..#]` `[#..y]` `[x..#..y]` | the bound folded into the free copy | constrain that bound count (`≥x`, `≤y`, `x..y`) |
| `{\|..}`                 | `{\|}[..]`                           | a pipe repeated any number of times       |

### 5.3 Implicit wrap

```
« If the FIRST step contains no '{' at all, it is wrapped: step → '{' step '}' »
```

So a bare first step like `a..z` is read as σ-arithmetic, not the literal text `a..z`. Later steps are **not** wrapped — a bare later step is a constant template.

---

## 6. Lexical structure (tokens)

A step is tokenized into a flat node list. Reference: [phase2.py](../himark/parser/phase2.py).

```
pattern     = token*
token       = escape | quoted | brace_group | subtractive | leaf

escape      = '\' ANY                     « see Appendix A »
quoted      = '"' qchar* '"'
qchar       = '\' ANY | ¬('"' | '\')
brace_group = '{' brace_body '}' count?
subtractive = '!' '{' brace_body '}' count?
count       = '[' count_body ']'
leaf        = ( ¬('{' | '"' | '!{' | '\') )+   « any run not starting a construct »
```

- `« '{' and '}' inside brace_body are balanced and depth-counted; \{ and \} are literal. »`
- A `quoted` literal is emitted/matched **verbatim** with escapes resolved. A lone `'` is an ordinary character — it is **not** a synonym for `"`.
- `subtractive` folds the leading `!` into the brace content (`!{X}` and the inner `{!X}` spelling resolve identically in §7).
- A `count` is recognised **only immediately after** a closing `}`.

---

## 7. The brace interior — the σ-grammar

The text inside a `{…}` (call it `brace_body`) resolves to exactly one semantic node. Reference: [phase3.py](../himark/parser/phase3.py) and [_shape.py](../himark/parser/_shape.py). Resolution is **ordered** — the first matching rule wins:

```
brace_body  = anchor
            | reference
            | bound
            | object            « whole body is one nested {…} »
            | grouping          « body concatenates constructs »
            | complement
            | alphabet
```

### 7.1 Anchors

```
anchor      = '@^' | '@$' | '@^^' | '@$$'
```

Zero-width, capture nothing: `@^`/`@$` = line start/end, `@^^`/`@$$` = scope start/end. The body must equal the anchor exactly (after trimming).

### 7.2 References (whole-brace)

Each consumes the **entire** brace (a `fullmatch`):

```
reference   = back_ref | count_ref | stage_ref
back_ref    = '$' digit+                  « text captured by group i »
count_ref   = '#' digit+                  « decimal repetition count of group i »
stage_ref   = digit+ '$' ( digit+ ( '.' digit+ )* )?   « stage N capture M(.K…); '{N$}' = whole stage »
```

`\$` is a literal, not a reference. Groups are numbered from **0** in document order (see §7.8).

### 7.3 Value bounds

```
bound       = floor ':' alphabet ':' ceiling      « exactly two TOP-LEVEL colons »
floor       = ( member | reference )?
ceiling     = ( member | reference )?
alphabet    = brace_body?                          « empty ⇒ ambient @uni »
```

`{floor:alphabet:ceiling}` restricts `alphabet` to the inclusive value band `floor`–`ceiling`; the two written widths set the field-width window. A literal colon in a class is escaped (`\:`). `« At least one of floor/ceiling must be present »` (`{:U:}` is an error). An endpoint may be a §7.2 reference (resolved at match time).

### 7.4 Objects (congruence nesting)

```
object      = '{' brace_body '}'          « the whole body is one nested brace »
```

- A **materialisable** inner (a flat class of primitives, e.g. `{{a,A}}`) folds its members into one congruence group → `GroupClassNode`.
- A **range/value** inner (e.g. `{{a..z}}`) stays a lazy heterogeneous run (a fresh match per repetition) → `HeterogeneousNode`.

### 7.5 Complement and exclusion

```
complement  = '!' brace_body              « subtractive universe: ambient minus body »
```

Inside an `alphabet` (§7.6), an arm beginning `!` is an **exclusion** rather than an include arm:

```
excl_arm    = '!' ( value | value '..' value | '{' set '}' )
```

A braced operand is a **set** — each member subtracts independently (`!{0,l,I,O}` drops all four). A multi-character excluded string is a **break**: it forbids any character that *begins* that string at the current position (this is how a greedy run stops at the nearest delimiter; see [HMK.md §Subtraction](HMK.md#subtraction)).

### 7.6 Alphabets — congruence (`,`) and range (`..`)

When the body is none of the above, it is an ordered alphabet of points:

```
alphabet    = arm ( ',' arm )*            « top-level commas »
arm         = range_part ( '..' range_part )*   « top-level '..' »
range_part  = '{' brace_body '}' | bare
bare        = ( escape | ¬(',' | '..' | '{' | '}') )*
```

**Constraints and resolution** (`_resolve_arm` / `_classify_arms`):

- `« Whitespace around ',' and '..' is significant »` — a space-padded arm is a compile error, **unless** the whole arm is purely whitespace (so `{ }` is a literal space) or it is a single nested-brace arm needing disambiguation space (`{ {a..z} }`). Escape a literal space as `\`.
- **One part, brace** → if the brace is a singleton (cardinality 1), a `LiteralNode` of its single value; else the wrapped universe, transparently (`{ {a..z} }` ≡ `{a..z}`).
- **One part, bare** → a `LiteralNode` of the unescaped text.
- **Two parts** (`x..y`): both single-char singletons → `CharRangeNode`; both multi-char singletons → a `ValueRangeNode` over ambient `@uni` (`{aa..zz}` ≡ `{aa:@uni:zz}`); `« an alphabet endpoint here is an error »` (a value bound uses `:`, not `..`).
- `« Three or more '..' parts is an error »`.
- **Congruence vs. union.** When every arm is materialisable, the comma-list is a `GroupClassNode` (so `{a,b}` ≡ `{a..b}`, and `{{a,A},{c,C}}` is two folded positions). If any arm is a range/value (`{a..z}`, `{@d}`), the list stays a lazy ordered `UnionNode`. A bare top-level `,` lists *primitive points*; folding into one interchangeable position comes from brace depth (`{{a,A}}`).

### 7.7 Grouping braces (sub-patterns)

A brace whose interior **concatenates constructs** — rather than being a single σ expression — is a grouping brace: one capture group whose nested braces are sub-captures. Reference: [_shape.py](../himark/parser/_shape.py) `is_sequence_brace`.

```
« grouping ⇔ the body is NOT a single σ expression, i.e. some ','/'..' part is
  not a σ atom. A σ atom is: empty, bare text, or exactly one {…} (optionally with
  an exact [N] count) surrounded only by whitespace. A {…} glued to adjacent text,
  two or more {…}, or a ranged/star count makes the body a grouping brace. A
  three-colon bound (§7.3) is always a single value universe, never a grouping. »
```

A grouping brace's interior is re-tokenized (§6) and re-resolved (§7) as a `SequenceNode`.

### 7.8 Captures

Every `{…}` is a capture group, numbered left-to-right from **0**. A grouping brace nests its inner braces as sub-captures (`2.0`, `2.1`, …). A repeated group captures its **full** matched text as one string, not one capture per repetition. (A `{$0}` self-reference is itself a capture group and shifts later indices.)

---

## 8. Repetition counts

A `[count]` after a brace repeats it. The count is its own universe over base-10 non-negative integers. Reference: [_count.py](../himark/parser/_count.py).

```
count_body  = count_ref | count_set | count_range
count_ref   = '#' digit+                  « repeat as many times as group i did »
count_set   = int ( ',' int )+            « exactly a, b, or c times (a union) »
count_range = int? ( '..' int? )?         « [n] | [x..] | [..y] | [x..y] | [..] »
int         = digit+
```

- `[n]` is exact (`min = max = n`). `[x..]` is `≥ x`; `[..y]` is `0..y`; `[..]` is any positive integer.
- `« A non-integer count alphabet ([a..z], [!{@s}]) is a compile error. »` Adjacency is meaningless in counts (a count is one number).
- Runs are **greedy**, backing off no further than the floor; there is no lazy operator (subtract a break instead — §7.5).

---

## 9. Templates (moustache)

A template step is literal text with embedded references. Reference: [_render.py](../himark/engine/_render.py).

```
template    = ( literal | moustache )*
moustache   = '{{' '>'? body '}}'         « '>' marks the downstream payload »
body        = ( accessor | current ) ( '|' filter )*
current     = '.'                         « the text flowing into this step »
accessor    = digit* ( '$' | '#' ) ( digit+ ( '.' digit+ )* )?
filter      = name ( '(' arg ')' )?
```

- `{{ i$j }}` = stage `i` capture `j`; `{{ i$j.k }}` descends into sub-captures; `{{ i$ }}` = the whole match of stage `i` (a raw string); `{{ i#j }}` = group `j`'s repetition count. A missing stage index defaults to the current/previous stage; `{{.}}` is the flowing text.
- `« At most one '{{> … }}' marker per template. »` Its accessor (and only it) is what the next stage sees; the full render still lands in the document.
- A `#` reference needs a capture index; an out-of-range index is a compile error.

### 9.1 Filters

A fixed, pure standard library — no user-defined filters, no I/O. Reference: [_render.py](../himark/engine/_render.py) `_FILTERS`.

| Filter     | Kind   | Effect                                              |
| ---------- | ------ | --------------------------------------------------- |
| `upper`    | string | uppercase                                           |
| `lower`    | string | lowercase                                           |
| `trim`     | string | strip leading/trailing space                        |
| `indent`   | string | prefix every line with one tab                      |
| `len`      | string | character count (as a number)                       |
| `hex`      | string | bytes → hexadecimal                                 |
| `sha256`   | string | SHA-256 digest of the byte string (32 raw bytes)    |
| `head(n)`  | string | the first `n` bytes                                 |
| `tail(n)`  | string | the last `n` bytes                                  |
| `b256(n)`  | value  | the reference's value as `n` big-endian base-256 bytes |

`« A value filter (b256) requires a group accessor over a {x:A:y} bound — the only reference carrying an alphabet. On any raw string it is a compile error. »` The byte filters work one-byte-per-code-point, so they chain (`… | b256(25) | sha256`).

---

## Appendix A: Escape table

The single escape table, applied wherever literal text is resolved (reference: [_text.py](../himark/parser/_text.py) `ESCAPES` / `unescape`):

| Escape | Resolves to            |
| ------ | ---------------------- |
| `\n`   | newline (U+000A)       |
| `\t`   | tab (U+0009)           |
| `\r`   | carriage return (U+000D) |
| `\\`   | backslash              |
| `\{`   | `{`                    |
| `\}`   | `}`                    |
| `\"`   | `"`                    |
| `\c`   | `c` itself, for any other character (`\!` → `!`, `\` → space, `\,` → `,`) |

An escaped character is never a delimiter, never an operator, and (for `\`) is a literal part of a value rather than insignificant padding.

---

## Appendix B: Macro table

The named alphabets, declared in the prelude [std.hmk](../himark/std.hmk) and loaded by [prelude.py](../himark/prelude.py). The engine has no built-in alphabet knowledge — it only ever sees the ranges and congruence classes these expand to.

| Name     | Expands to                  |
| -------- | --------------------------- |
| `@d`     | `0..9`                      |
| `@l`     | `a..z`                      |
| `@u`     | `A..Z`                      |
| `@s`     | `\n,\r, ,\t`                |
| `@w`     | `{{a,A},{b,B},…,{z,Z}},_`   |
| `@x`     | `!@s`                       |
| `@hex`   | `{@d},{:@w:f}`              |
| `@b32`   | `{@d},{:@w:v}`  (RFC 4648 §7) |
| `@b58`   | `{@d},{@u},{@l},!{0,l,I,O}` |
| `@b64`   | `{@d},{@l},{@u},+,/`        |
| `@ascii` | `U+0000..U+007F`            |
| `@uni`   | `U+0000..U+10FFFF`         |
| `@b256`  | `U+0000..U+00FF` (every byte) |

---

## Appendix C: Reserved behaviour and known limitations

These are intentional and part of the locked surface:

- **Single arrow.** There is exactly one transformation arrow, `=>`, plus its fixed-point form `<=`. There is no separate replace/substitute arrow — list and splice renderings come from the same branches.
- **Arrows and quotes.** Arrow splitting (§4) is depth-aware over `{…}`/`[…]` but **not** over `"…"`. Do not put `=>`/`<=` inside a quoted template at brace depth 0.
- **One looped statement.** `<=` loops a single statement; a *group* of statements cannot yet be looped together.
- **Contraction required.** A `<=` rule must contract toward a fixed point; a rule that grows the document (`{a} <= "aa"`) or oscillates is a compile-time error.
- **Counts are integers only.** A non-integer count alphabet is a compile error.
- **`'` is ordinary.** Only `"` delimits a quoted literal.

---

## Conformance

An implementation conforms if, for every input, it produces the same statement split (§3–§4), the same token stream (§6), the same resolved semantic node per brace (§7), the same count descriptor (§8), and the same template render (§9) as the reference parser in [himark/parser/](../himark/parser/). The test suite under [tests/](../tests/) — in particular the phase tests and the `.hmk` demos in [himark/scripts/](../himark/scripts/) — is the executable conformance set.
