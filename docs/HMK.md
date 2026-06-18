# Himark Specification

**Version:** 0.9.0-experimental  
**Status:** Draft Specification  
**License:** CC0 1.0 Universal (Public Domain)

<!-- cspell:words himark -->

---

A pattern is built from **universes** and a small set of operators over them. A universe `{...}` is a virtual set of strings or characters; as a pattern it matches **exactly one** of its elements -- one position.

| Operator    | Role                                                                                                  |
| ----------- | ----------------------------------------------------------------------------------------------------- |
| `{...}`     | **Universe** -- a set of strings/characters; matches one element                                      |
| `,`         | **Union** -- combine universes (`{a,b}` is `a` or `b`)                                                |
| `..`        | **Range** -- ordered bounds within one alphabet (`{a..z}`, `{aa..zz}`)                                |
| `{X}{Y}`    | **Adjacency** -- concatenation; the Cartesian product of universes (`{a..z}{A..Z}` $\to$ `aA`...`zZ`) |
| `!{...}`    | **Subtractive universe** -- everything _not_ in `{...}`, from the ambient universe (Unicode)          |
| `{x:...:y}` | **Bounds** -- the inner universe, restricted to values `x`-`y` inclusive (`{x::y}` = ambient)         |
| `[x:y:z]`   | **Repetition** -- minimum `x`, maximum `y`, step `z`                                                  |
| `=>`        | **Pipe** -- feed each match into the next transformation                                              |

**Every `{...}` matches one position.** A run is always an explicit `[count]`. A bare `{U}[n]` repeats **homogeneously** -- the _same_ matched value, `n` times. To repeat **heterogeneously** -- a fresh match each time -- nest the universe in a group: `{{U}}[n]`.

```proto
{a,A}[2]     // homogeneous: 'aa', 'AA'
{{a,A}}[2]   // heterogeneous: 'aa', 'aA', 'Aa', 'AA'
{a..z}[3]    // homogeneous: 'aaa', 'bbb'
{{a..z}}[3]  // heterogeneous: any three letters, 'abc'
```

This is the experimental algebra branch: the `<->` and `>>` operators and the old `{{...}}` reference sublanguage have been removed. References return as **moustache** template accessors (see [Captures](#captures), [Transformers](#transformers)) and pattern [self-references](#self-references).

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
| `@hex`   | `{@d},{{@w}..f}`            |
| `@b32`   | `{@d},{{@w}..v}`            |
| `@b58`   | `{@d},{@u},{@l},!{0,I,O,l}` |
| `@b64`   | `{@d},{@l},{@u},+,/`        |
| `@ascii` | U+0000-U+007F               |
| `@uni`   | U+0000-U+10FFFF             |

> **Note:** `@w` enumerates each letter and its capital as one congruence class (`{a,A}`, `{b,B}`, ...), so `a` and `A` share one ordered position. `@hex` and `@b32` (RFC 4648 $\S7$) slice `@w`, so they stay base 16 / base 32 **and** case-insensitive at once (see [Congruence](#congruence)).

---

## Universes

A universe is a set. Its atoms are characters and strings; `,` unions them, `..` bounds them into an ordered range, and **adjacency** -- writing universes side by side -- concatenates them into their Cartesian product.

```proto
{a}               // the one-element universe {a}
{abc}             // the one-element universe {abc} (one string)
{a,b,c}           // union: a or b or c
{cat,dog}         // union of two strings
{a..z}            // range: the single characters a through z
{aa..zz}          // range over a two-wide *Unicode* value space -- every string from 'aa' to 'zz' by value
{a..z}{A..Z}      // adjacency: a lowercase then an uppercase -- the product aA, aB, ..., zZ
{a..b}{cd}{e..f}  // adjacency of three universes: {acde, acdf, bcde, bcdf}
```

> **Note:** the Cartesian product comes from **adjacency**, not from `..`. `..` is always a one-axis range; `{a..z}..{A..Z}` (a range between two _sets_) has no single ordering and is rejected -- write `{a..z}{A..Z}` for the product, `{a..z,A..Z}` for either case, or `{{a,A},...,{z,Z}}` for case-folded positions.

A universe always matches **one** of its elements (one position). `{a..z}` matches one letter; `{cat,dog}` matches one of the two words. A run is an explicit `[count]` (see [Repetition](#repetition)).

> **Note:** an unnamed multi-character range is over **ambient Unicode**, not over letters. `{aa..zz}` is `{aa:@uni:zz}`, so it is the whole value band from `aa` to `zz` -- every two-wide string whose value falls between them, including non-letter ones like 'b:fire:' (its first position `b` lands inside `a`-`z`). To mean "two lowercase letters," name the alphabet: `{aa:@l:zz}`.

### Congruence

`,` makes its members **interchangeable** -- one position with several spellings. This matters under bounds and references, where congruent spellings share a value:

```proto
{a,A}            // one position, two spellings: 'a' or 'A'
{{a,A},{b,B}}    // an ordered alphabet of folded positions (a < b, each case-folded)
```

---

## Bounds

`{x:U:y}` restricts the universe `U` to the values from `x` to `y`, **inclusive**, by positional value (most-significant first). `{x::y}` uses the ambient universe (Unicode). Either bound may be omitted.

```proto
{0:@d:255}    // decimal values 0 through 255
{0::255}      // same, over the ambient universe
{aa:@l:zz}    // two-letter lowercase strings 'aa' through 'zz'
{000:@d:999}  // fixed three-wide decimals -- '007' matches (the floor sets the width)
```

The two bounds' written widths set the field width: the narrower is the minimum, the wider the maximum. Equal widths fix it -- `{000:@d:999}` is exactly three wide, so `007` and `042` match but `7` does not. A narrower ceiling relaxes it -- `{000::9}` accepts the value `9` at any width from the ceiling's up to the floor's: `9`, `09`, and `009`. A fixed width is therefore a floor and ceiling written at the same width; there is no separate padding operator.

All four cap the value at `90`; every row is that value, so only the width window decides. Windows: `{0::90}` is 1-2, `{000::90}` is 2-3, `{0::090}` is 1-3, `{000::090}` is exactly 3.

|        | `{0::90}`    | `{000::90}`  | `{0::090}`   | `{000::090}` |
| ------ | ------------ | ------------ | ------------ | ------------ |
| `9`    | $\checkmark$ |              | $\checkmark$ |              |
| `90`   | $\checkmark$ | $\checkmark$ | $\checkmark$ |              |
| `090`  |              | $\checkmark$ | $\checkmark$ | $\checkmark$ |
| `0090` |              |              |              |              |

### Subtraction

`!{...}` is the **subtractive universe** -- every value of the ambient universe (Unicode) _not_ in `{...}`. Alone it draws from the full Unicode set; as a union arm it subtracts from the others:

```proto
!{a}                   // any character except 'a'
!{|,\n}                // any character except '|' or newline
{@d,@l,@u,!{0,l,I,O}}  // base58: digits and letters, minus the four ambiguous characters
```

A subtractive universe matches one position, like any universe; a run is `[count]`, nested for a heterogeneous run (`{!{|,\n}}[1:]` is a run of cell text).

---

## Repetition

`[x:y:z]` repeats the preceding universe: minimum `x`, maximum `y`, step `z`. Omit a field to leave it open; `[n]` is exactly `n`.

| Form      | Meaning                    |
| --------- | -------------------------- |
| `[n]`     | exactly `n`                |
| `[x:]`    | `x` or more                |
| `[:y]`    | up to `y`                  |
| `[x:y]`   | `x` to `y`                 |
| `[x:y:z]` | `x` to `y` in steps of `z` |
| `[:]`     | any number                 |

A bare `{U}[n]` repeats **homogeneously** -- the same matched value. A nested `{{U}}[n]` repeats **heterogeneously** -- a fresh match per rep. A grouping brace (a `{...}` holding a concatenation of universes) likewise repeats by **shape**, so one pattern can walk a homogeneous block -- the cells of a row, the rows of a table.

```proto
{a..z}[3]                    // 'aaa', 'bbb' -- the same letter three times
{{a..z}}[3]                  // 'abc', 'xyz' -- any three letters
{a..z}[2:6:2]                // the same letter 2, 4, or 6 times
{{|}{!{|,\n}}[1:]}[2:]{|}    // two or more '|'+cell units, each cell different
```

---

## Captures

Every `{...}` creates a capture group, numbered left to right from **0**. A grouping brace nests its inner braces as **sub-captures**. A repeated group (`[count]`) captures its full matched text as one string, not one capture per repetition.

Given the input `"### Sphinx of black quartz, judge my vow!"` and the expression `{#}[1:]{Sphinx}{of{black}{quartz}}`:

| Group | Text                     | Explanation                     |
| ----- | ------------------------ | ------------------------------- |
| full  | `###Sphinxofblackquartz` | The full matched text.          |
| 0     | `###`                    | Group 0                         |
| 1     | `Sphinx`                 | Group 1                         |
| 2     | `ofblackquartz`          | Group 2                         |
| 2.0   | `black`                  | First sub-group inside group 2  |
| 2.1   | `quartz`                 | Second sub-group inside group 2 |

> **Note:** Captures are addressable from a template via moustache references -- `{{ i$j }}` for stage `i`'s capture `j`, `{{ i$j.k }}` to descend into sub-captures, and `{{ . }}` for the text flowing into the step (see [Transformers](#transformers)).

### Self-references

A pattern can refer back to what an earlier capture matched. Groups are numbered 0-based in document order (see [Captures](#captures)).

| Form    | Written in | Matches                                                           |
| ------- | ---------- | ----------------------------------------------------------------- |
| `{$i}`  | `{...}`    | the literal **text** that group `i` captured                      |
| `{#i}`  | `{...}`    | the decimal **repetition count** of group `i`                     |
| `[#i]`  | `[count]`  | repeat exactly as many times as group `i` did                     |
| `{N$M}` | `{...}`    | the text of pipeline stage `N`'s capture `M` (`{N$M.K}` descends) |

```proto
{a..z}{$0}        // a doubled letter: 'aa', 'bb' (not 'ab')
{a}[1:]{x}{#0}    // an a-run, 'x', then its length: matches 'aaax3', not 'aax3'
{a}[2:]{-}[#0]    // as many '-' as there were 'a': 'aaa---', 'aa--'
```

`{$i}` and `{#i}` read the captures of the **current** match; `{N$M}` reads an earlier pipeline stage (`=>`-numbered, templates included) -- the matching-side counterpart of the moustache `{{ i$j }}` accessor (see [Transformers](#transformers)).

---

## Transformers

`=>` runs a chain of steps. Each step is a **query** (a matcher) or a **template** (plain text with no matchable `{...}`); the first step is a query. Each match of the first query starts a **branch**, and the rest of the chain transforms that branch's text independently:

- a **query** matches within the branch's text and splices each match's transform back in place, keeping the text between matches; a query that matches nothing **drops the entire branch** -- its partial transform is discarded, not emitted. That is how a chain filters: a branch survives only if every query stage matches.
- a **template** renders, and the chain continues on its render. Templates are **not** terminal: a later query matches the rendered text, and a later template wraps it. `{{.}}` is the flowing text, so templates compose (`... => "<b>{{.}}</b>" => "<i>{{.}}</i>"` yields `<i><b>...</b></i>`).

Stages are numbered by `=>` position (templates included), so `{{ i$j }}` and `{N$M}` address any earlier step. The branches render two ways from the **same** result -- neither privileged:

- **list** -- the branch results, in order.
- **splice** -- each result laid back over its source span, the text between branches kept verbatim (the in-place transform).

```proto
{a..z}                              // the list of lowercase letters (one each)
{a..z} => <w>                       // list: '<w>' per letter -- splice: each letter becomes '<w>'
{cat} => "<b>{{.}}</b>"             // wrap each match
{table} => "<table>{{.}}</table>" => {{!{\n}}}[1:] => "<tr>{{.}}</tr>"   // nest: wrap, then wrap rows
```

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

**Markdown $\to$ HTML** -- a pipeline in a `.hmk` script ([marky/scripts/md_html.hmk](marky/scripts/md_html.hmk)), run with `marky transpile`. For example, headers map the `#` count to the heading level:

```proto
{#}[1:6]{ }[0:]{!{\n}}[1:] => "<h{{#0}}>{{$2}}</h{{#0}}>"   // '##' -> <h2>...</h2>
```

### Script files (.hmk)

A `.hmk` file is a pipeline of HMK statements applied in order. One statement per logical line; a line beginning with `=>` continues the previous statement (multi-line chains), `//` starts a line comment, and blank lines separate -- all read at brace/quote depth 0, so `=>` and `//` inside `{...}` or `"..."` are content. Run one over a document with `marky transpile <doc> --script <file.hmk>` (output to stdout, or `--out <file>`).
