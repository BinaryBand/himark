# Himark Specification

**Version:** 0.9.3-experimental  
**Status:** Draft Specification  
**License:** CC0 1.0 Universal (Public Domain)

<!-- cspell:words himark -->

---

A pattern is built from **universes** and a small set of operators. A universe `{...}` is a virtual set of strings or characters. As a pattern, it matches **exactly one** of its elements and occupies one position.

| Operator    | Name                     | Role                                                                   |
| ----------- | ------------------------ | ---------------------------------------------------------------------- |
| `{...}`     | **Universe**             | a set of strings/chars; matches one element                            |
| `,`         | **Union**                | combine universes (`{a,b}` is `a` or `b`)                              |
| `..`        | **Range**                | ordered bounds within one alphabet (`{a..z}`, `{aa..zz}`)              |
| `!{...}`    | **Subtractive universe** | everything _not_ in `{...}`, from the ambient universe (Unicode)       |
| `{x:...:y}` | **Bounds**               | restricted a universe to values `x`-`y` inclusive (`{x::y}` = ambient) |
| `[count]`   | **Repetition**           | a count universe over base-10 integers (`[n]`, `[x..y]`, `[a,b,c]`)    |
| `{...}~k`   | **Fuzzy**                | the universe within edit distance `k` of a token (`{cat}~1`)           |
| `=>`        | **Pipe**                 | feed each match into the next transformation                           |

**Every `{...}` matches one position**, holding one **point** of the universe. A point is a **primitive** (one char or string) or an **object** (a nested universe `{...}`) whose members are **interchangeable**. A run is an explicit `[count]` repeating **one point**: a primitive repeats as its spelling, an object lets each position take **any** of its members independently.

```proto
{a,A}[2]          // primitives a, A -- 'aa', 'AA'
{{a,A}}[2]        // one object {a,A} -- members free: 'aa', 'aA', 'Aa', 'AA'
{a..z}[3]         // primitives -- 'aaa', 'bbb'
{{a..z}}[3]       // one object -- any three letters: 'abc', 'zzz'
{{a,A},{c,C}}[2]  // two objects -- one repeated: 'aa','aA','Aa','AA' or 'cc','cC','Cc','CC'
```

---

## Macros

| Name     | Expands to                  |
| -------- | --------------------------- |
| `@d`     | `0..9`                      |
| `@l`     | `a..z`                      |
| `@u`     | `A..Z`                      |
| `@s`     | `\n,\r, ,\t`                |
| `@w`     | `{a,A},{b,B},...,{z,Z},_`   |
| `@x`     | `!{@s}`                     |
| `@hex`   | `{@d},{{@w}:f}`             |
| `@b32`   | `{@d},{{@w}:v}`             |
| `@b58`   | `{@d},{@u},{@l},!{0,I,O,l}` |
| `@b64`   | `{@d},{@l},{@u},+,/`        |
| `@b256`  | U+0000-U+00FF (every byte)  |
| `@ascii` | U+0000-U+007F               |
| `@uni`   | U+0000-U+10FFFF             |

> **Note:** `@w` enumerates each letter and its capital as one congruence class (`{a,A}`, `{b,B}`, ...), so `a` and `A` share one ordered position. `@hex` and `@b32` (RFC 4648 $\S7$) slice `@w`, so they stay base 16 / base 32 **and** case-insensitive at once (see [Congruence](#congruence)).

---

## Anchors

`@\^` / `@$` match the start / end of a **line** (position 0 or just after / just before a `\n`); `@^\^` / `@$$` match the start / end of the whole **scope** (the text a stage sees). All four are **not** alphabets -- they are zero-width and capture nothing, so a line-start header is `{@^}{#}[1..6]{ }[1..]{!\n}[1..]`. They are primitives, not macros, so they live here rather than in the table above.

---

## Universes

A universe is a set. Its atoms are characters and strings; `,` unions them, `..` bounds them into an ordered range, and **adjacency** -- writing universes side by side -- concatenates them into their Cartesian product.

```proto
{a}               // one-element universe {a}
{abc}             // one-element universe {abc} (one string)
{a,b,c}           // union: a or b or c
{cat,dog}         // union of two strings
{a..z}            // the single chars a through z
{aa..zz}          // every string from 'aa' to 'zz' by value (Unicode)
{a..z}{A..Z}      // adjacency: a lowercase then an uppercase (aA,aB,...,zZ)
{a..b}{cd}{e..f}  // three adjacent universes: {acde,acdf,bcde,bcdf}
```

> **Note:** `..` is always a one-axis range; `{a..z}..{A..Z}` (a range between two _sets_) has no single ordering and is rejected -- write `{a..z}{A..Z}` for the Cartesian product, `{a..z,A..Z}` for either case, or `{{a,A},...,{z,Z}}` for case-folded positions.

A universe always matches **one** of its elements (one position). `{a..z}` matches one letter; `{cat,dog}` matches one of the two words. A run is an explicit `[count]` (see [Repetition](#repetition)).

> **Note:** an unnamed multi-character range is over **ambient Unicode**, not letters. `{aa..zz}` is `{aa:@uni:zz}` -- the whole value band from `aa` to `zz`, including non-letter strings whose value falls between. For "two lowercase letters," name the alphabet: `{aa:@l:zz}`.

### Congruence

A bare `,` **lists points**: `{a,b}` is an alphabet of two primitives -- the same set as `{a..b}` (a range is just a compact list). Congruence -- folding several spellings into **one** interchangeable point -- comes from **nesting**. A `{...}` used as a member of an enclosing universe is an **object**, and its faces are spellings of a single position that share one value. That shared value is what bounds and references compare by:

```proto
{a,b}                  // two primitive points (identical to {a..b})
{{a,A}}                // a single position spelled 'a' or 'A'
{{a,A},{b,B}}          // an ordered alphabet of folded positions
{{one,ett},{two, två}} // an object's faces can be strings
```

> **Note:** the fold lives in the brace depth so a top-level `{a,A}` is just the two-primitive alphabet (`a` or `A`). `{{a,A}}` folds them into a one case-insensitive position. Named alphabets already nest where they fold: `{@w}` is `{{a,A},{b,B},…}`, which is why `@w`, `@hex`, and `@b32` are case-insensitive (see [Macros](#macros)).

---

## Bounds

`{x:U:y}` **inclusively** restricts the universe `U` to the values from `x` to `y` by positional value (most-significant first). `{x::y}` uses the ambient universe (Unicode). Either bound may be omitted.

```proto
{0:@d:255}    // decimal values 0 through 255
{0::255}      // omitted middle = @uni
{aa:@l:zz}    // two-letter lowercase strings 'aa' through 'zz'
{000:@d:999}  // fixed three-wide decimals (the floor sets the width)
```

The two written widths set the field width -- narrower is the minimum, wider the maximum. Equal widths fix it: `{000:@d:999}` is exactly three wide, so `007` and `042` match but `7` does not. A narrower ceiling relaxes it: `{000:@d:9}` accepts `9` at any width between the two. So a fixed width is just floor and ceiling at one width; there is no separate padding operator.

|        | `{0:@d:90}`  | `{000:@d:90}` | `{0:@d:090}` | `{000:@d:090}` |
| ------ | ------------ | ------------- | ------------ | -------------- |
| `9`    | $\checkmark$ |               | $\checkmark$ |                |
| `90`   | $\checkmark$ | $\checkmark$  | $\checkmark$ |                |
| `090`  |              | $\checkmark$  | $\checkmark$ | $\checkmark$   |
| `0090` |              |               |              |                |

### Subtraction

`!{...}` is the **subtractive universe** -- every value of the ambient universe (Unicode) _not_ in `{...}`. Alone it draws from the full Unicode set. As a union, it subtracts from the others.

```proto
!{a}                   // any character except 'a'
!{|,\n}                // any character except '|' or newline
{@d,@l,@u,!{0,l,I,O}}  // base58: digits and letters, minus the four ambiguous characters
```

> Like any universe, a subtractive universe matches one position.

---

## Fuzzy

`{token}~k` is the universe of **all strings within edit distance `k`** of a token. It matches one element, captures the **actual** matched text, and composes with `[count]`, captures, and references like any `{...}`. `k` is explicit and required -- there is no implicit fuzz.

```proto
{cat}~1         // 'cat', 'cap', 'cot', 'at', 'cart', ... (Levenshtein distance <= 1)
{cat,dog}~1     // within distance 1 of either token
{cat:@l:cat}~1  // distance <= 1, with only lowercase letters bridging the gap
```

The operand is a token, a token union, or an alphabet-annotated token `{token:A:token}` -- a finite set has a well-defined neighbourhood; a non-singleton range or subtractive universe does not. The edits draw from the operand's own alphabet: bare `{cat}` is `{cat:@uni:cat}`, so any character may bridge (hence `cap`, `cot`, `cart`); `{cat:@l:cat}~1` narrows that to lowercase, rejecting `c@t`. A token must be spellable in its alphabet, so `{Cat:@l:Cat}` is a compile error. Distance is **Levenshtein**; ties break by smallest distance, then longest span, then leftmost. Like `@uni`, the neighbourhood is matched by an automaton, never enumerated.

---

## Repetition

`[count]` repeats the preceding universe. The count is itself a **universe** -- the same algebra as `{...}`, but over the ambient set of **base-10 non-negative integers** instead of Unicode. A bare number is exact, `,` unions counts, and `..` is a range:

| Form      | Meaning                         |
| --------- | ------------------------------- |
| `[n]`     | exactly `n`                     |
| `[x..]`   | `x` or more                     |
| `[..y]`   | up to `y`                       |
| `[x..y]`  | `x` to `y`                      |
| `[..]`    | any positive integer            |
| `[a,b,c]` | exactly `a`, `b`, or `c` times  |
| `[..<y]`  | lazy: up to `y`, shortest first |

Only the integer operators carry over: adjacency is meaningless (a count is one number), and a non-integer count alphabet (`[a..z]`, `[!{@s}]`) is a compile error. Because the count is a universe, references fit: `[#i]` repeats as group `i` did (see [Self-references](#self-references)), and `[#0..#1]` ranges between two captured counts.

A run is **greedy** by default: it takes the longest count in range that still lets the rest match, backing off toward the floor if the tail fails -- so `{!\ }[1..]` is a whole word. `[..<y]` is **lazy**: shortest first, ending at the **nearest** following match (for a terminator you cannot exclude from the run's class). The ceiling is the search **budget** -- a greedy `[x..y]` backs off no further than `x` -- so `[..]` (open) is the only unbounded scan.

`[n]` repeats **one point**. A **primitive** repeats verbatim (`{a..z}[3]` is `aaa`). An **object**'s members are interchangeable, so each position takes any of them (`{{a..z}}[3]` is any three letters). Repeating an object stays within universe `{{a,A},{c,C}}[2]` is `{a,A}{a,A}` or `{c,C}{c,C}`, never a cross like `ac`.

```proto
{a..z}[3]                    // primitive: the same letter three times (e.g. 'aaa','bbb')
{{a..z}}[3]                  // object: any three letters, each free (e.g. 'abc','xyz')
{{a,A},{c,C}}[2]             // one object repeated (e.g. 'aa','aA','Aa','AA' or 'cc','cC','Cc','CC')
{a..z}[2,4,6]                // the same letter 2, 4, or 6 times -- a union, not a step
{{|}{!{|,\n}}[1..]}[2..]{|}  // two or more '|'+cell units, each cell different
```

> **Note:** A range may take a **stride** as a third segment -- `[0..100..2]` is every second count, `{a..z..2}` every second letter. A stride needs both bounds (always finite); an open-ended stride is not allowed. Prefer a union (`[2,4,6]`, `{a,c,e}`) for a handful of values; reach for `..s` only when enumerating would be unwieldy.

---

## Captures

Every `{...}` creates a capture group, numbered left to right from **0**. A grouping brace nests its inner braces as **sub-captures**. A repeated group (`[count]`) captures its full matched text as one string, not one capture per repetition.

Given the input `"### Sphinx of black quartz, judge my vow!"` and the expression `{#}[1..]{ }{Sphinx}{of{black}{quartz}}`:

| Group | Text                      | Explanation                     |
| ----- | ------------------------- | ------------------------------- |
| full  | `### Sphinxofblackquartz` | The full matched text.          |
| 0     | `###`                     | Group 0                         |
| 1     | `Sphinx`                  | Group 1                         |
| 2     | `ofblackquartz`           | Group 2                         |
| 2.0   | `black`                   | First sub-group inside group 2  |
| 2.1   | `quartz`                  | Second sub-group inside group 2 |

> **Note:** Captures are addressable from a template via moustache references -- `{{ i$j }}` for stage `i`'s capture `j`, `{{ i$j.k }}` to descend into sub-captures, `{{ i$ }}` for that stage's whole text as a raw string, and `{{ . }}` for the text flowing into the current step -- a relative shorthand for the previous stage's `{{ i$ }}` (see [Transformers](#transformers)).

### Self-references

A pattern can refer back to what an earlier capture matched. Groups are numbered 0-based in document order (see [Captures](#captures)).

| Form    | Written in | Matches                                                           |
| ------- | ---------- | ----------------------------------------------------------------- |
| `{$i}`  | `{...}`    | the literal **text** that group `i` captured                      |
| `{#i}`  | `{...}`    | the decimal **repetition count** of group `i`                     |
| `[#i]`  | `[count]`  | repeat exactly as many times as group `i` did                     |
| `{N$M}` | `{...}`    | the text of pipeline stage `N`'s capture `M` (`{N$M.K}` descends) |
| `{N$}`  | `{...}`    | the whole text of pipeline stage `N` (raw string)                 |

```proto
{a..z}{$0}        // a doubled letter: 'aa', 'bb' (not 'ab')
{a}[1..]{x}{#0}   // an a-run, 'x', then its length: matches 'aaax3', not 'aax3'
{a}[2..]{-}[#0]   // as many '-' as there were 'a': 'aaa---', 'aa--'
```

`{$i}` and `{#i}` read the captures of the **current** match; `{N$M}` (and `{N$}` for the whole stage text) reads an earlier pipeline stage (`=>`-numbered, templates included) -- the matching-side counterpart of the moustache `{{ i$j }}` / `{{ i$ }}` accessors (see [Transformers](#transformers)).

> **Note:** In **matching** position a reference is always concrete text -- you match the literal characters the group captured. The text-vs-**value** distinction matters only in **template** position, where a filter may consume the reference: a **group** accessor carries the captured text together with the alphabet it matched under, a **whole-stage** accessor is a raw string (see [Filters](#filters)).

---

## Transformers

`=>` runs a chain of steps. Each step is a **query** (a matcher) or a **template** (plain text with no matchable `{...}`); the first step is a query. Each match of the first query starts a **branch**, and the rest of the chain transforms that branch's text independently. A branch's output is **whatever it has committed**:

- a **query** matches within the branch and commits each match's transform in place, keeping the text between. A query that matches nothing **stops** the branch; if nothing is committed yet, it produces no output -- so a query before the work is a **guard** that filters out non-matches.
- a **template** renders and **commits** it -- never rolled back. Templates are **not** terminal: a later query matches the rendered text, a later template wraps it. `{{.}}` is the flowing text, so templates compose (`... => "<b>{{.}}</b>" => "<i>{{.}}</i>"` yields `<i><b>...</b></i>`).

By default a template's whole render both writes to the document and flows downstream. To split the two, mark one accessor with `{{> ... }}`: that part is what the next stage sees, while the full render still lands in the document. At most one `{{> ... }}` may appear per template.

```proto
"# Hello" => {#}[1..6]{ }[1..]{!{\n}}[1..] => "<h{{#0}}>{{> $2 }}</h{{#0}}>"
// document gets "<h1>Hello</h1>"; the pipe continues with just "Hello"
```

Stages are numbered by `=>` position (templates included), so `{{ i$j }}` and `{N$M}` (or `{{ i$ }}` / `{N$}` for a whole stage) address any earlier step. The branches render two ways from the **same** result -- neither privileged:

- **list** -- the branch results, in order.
- **splice** -- each result laid back over its source span, the text between branches kept verbatim (the in-place transform).

```proto
{a..z}                              // the list of lowercase letters (one each)
{a..z} => <w>                       // list: '<w>' per letter -- splice: each letter becomes '<w>'
{cat} => "<b>{{.}}</b>"             // wrap each match
{table} => "<table>{{.}}</table>" => {{!{\n}}}[1..] => "<tr>{{.}}</tr>"   // nest: wrap, then wrap rows
```

### Filters

A moustache value may be piped through **filters** -- a fixed standard library of pure, deterministic transforms, in the `=>` spirit: `{{ accessor | f | g }}`. Filters are **template-only** (never in matching position), so the matcher stays declarative.

A moustache reference is one of two kinds. A **group** accessor (`{{ i$j }}`, `{{ $j }}`) carries the captured text _together with the alphabet it matched under_ -- a **value**. A **whole-stage** accessor (`{{ i$ }}`), the flowing text `{{ . }}`, and the output of any string filter are **raw strings**. **String** filters read the text of either kind; a **value** filter needs the alphabet and is a compile error on a raw string.

| Filter     | Kind   | Effect                                                    |
| ---------- | ------ | --------------------------------------------------------- |
| `upper`    | string | uppercase                                                 |
| `lower`    | string | lowercase                                                 |
| `trim`     | string | strip leading/trailing space                              |
| `len`      | string | character count (as a number)                             |
| `hex`      | string | bytes → hexadecimal                                       |
| `sha256`   | string | SHA-256 digest of the byte string (32 raw bytes)          |
| `head(n)`  | string | the first `n` bytes                                       |
| `tail(n)`  | string | the last `n` bytes                                        |
| `b256(n)`  | value  | the reference's value as `n` big-endian base-256 bytes    |

```proto
{!{ }}[1..] => "<b>{{ . | upper }}</b>"   // wrap each word, uppercased
{cat}{dog} => "{{ 0$0 | len }}"           // '3'
{0:@d:65535} => "{{ 0$0 | b256(2) }}"     // '256' (value 256) → bytes 0x01 0x00
```

Filters take arguments Jinja-style (`{{ 0$0 | b256(25) }}`). The set is fixed and pure -- there are no user-defined filters and no I/O. The byte filters (`hex`, `sha256`, `b256`) work in a one-byte-per-code-point domain, so they chain (`… | b256(25) | sha256 | sha256`); applied to text outside that range they are a compile error.

### Quoting static text

Literal text may be written in double quotes, which is emitted verbatim with `\"`, `\\`, and `\n` escapes. A lone `'` is an ordinary character -- it is **not** a synonym for `"`.

```proto
{a} => "<b>"   // emits the literal text <b>
"it's fine"    // ' needs no escaping
```

---

## North Star Examples

Worked patterns, in the universe/bounds model.

**IPv4 address** -- four dotted octets, each a decimal value 0-255:

```proto
{0:@d:255}{.}{0:@d:255}{.}{0:@d:255}{.}{0:@d:255}
```

**Bitcoin P2PKH address** -- a `1` prefix then a base58 value bounded by the smallest and largest 25-byte addresses (length is the value bound, not a digit count):

```proto
{1}{111111111111111111111111:@b58:2n1XR4oJkmBdJMxhBGQGb96gQ88xUzxLFyG}
```

**Markdown $\to$ HTML** -- a pipeline in a `.hmk` script ([himark/scripts/md_html.hmk](himark/scripts/md_html.hmk)), run with `himark transpile`. For example, headers map the `#` count to the heading level:

```proto
{#}[1..6]{ }[1..]{!{\n}}[1..] => "<h{{#0}}>{{$2}}</h{{#0}}>"   // '##' -> <h2>...</h2>
```

### Script files (.hmk)

A `.hmk` file is a pipeline of HMK statements applied in order. One statement per logical line; a line beginning with `=>` continues the previous statement (multi-line chains), `//` starts a line comment, and blank lines separate -- all read at brace/quote depth 0, so `=>` and `//` inside `{...}` or `"..."` are content. Run one over a document with `himark transpile <doc> --script <file.hmk>` (output to stdout, or `--out <file>`).
