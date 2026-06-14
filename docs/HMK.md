# Himark Specification

**Version:** 0.7.2-experimental  
**Status:** Draft Specification  
**License:** CC0 1.0 Universal (Public Domain)

<!-- cspell:words himark -->

---

Three constructs: `{...}` matches, `{{...}}` templates, and `[...]` repeats.

| Construct  | Role                |
| ---------- | ------------------- |
| `{expr}`   | Match and class     |
| `{{expr}}` | Template            |
| `[count]`  | Repetition modifier |

These compose as `{expr}[count]` where `{expr}` is implicitly identical to `{expr}[1]`.

---

## Macros

| Name     | Expands to                  |
| -------- | --------------------------- |
| `@d`     | `0..9`                      |
| `@l`     | `a..z`                      |
| `@u`     | `A..Z`                      |
| `@s`     | `\n,\r, ,\t`                |
| `@w`     | `{@l}<->{@u},_`             |
| `@x`     | `!@s`                       |
| `@hex`   | `{@d},{{@w}..f}`            |
| `@b32`   | `{@d},{{@w}..v}`            |
| `@b58`   | `{@d},{@u},{@l},!{0,I,O,l}` |
| `@b64`   | `{@d},{@l},{@u},+,/`        |
| `@ascii` | U+0000-U+007F               |
| `@uni`   | U+0000-U+10FFFF             |

> **Note:** `@hex` and `@b32` (RFC 4648 $\S7$) fold case with `<->` (see [Congruence](#congruence)), so `a` and `A` share one position -- the alphabets stay base 16 and base 32, and either casing matches.

---

## Arithmetic

**$\Sigma$** represents an ordered alphabet. **$\sigma$** represents a singleton value (equivalently, a one-element alphabet).

| Operator | Role                                         |
| -------- | -------------------------------------------- |
| `..`     | Range between endpoints                      |
| `<->`    | Congruence -- zip two equal-length $\Sigma$s |
| `,`      | Union of $\Sigma$s                           |
| `!`      | Subtract a $\Sigma$ from the group           |

A $\Sigma$ used as a `..` endpoint contributes an **alphabet** and an **extreme**. A singleton $\sigma$ contributes its concrete value (alphabet = ambient Unicode). A class contributes its own alphabet, standing in for the natural extreme in its direction -- floor on the left, unbounded on the right.

> **Note:** Precedence binds tightest to loosest: `..` then `<->` then `,`.

| Written                | Alphabet               | Low   | High      |
| ---------------------- | ---------------------- | ----- | --------- |
| `{a}`                  | Unicode                | `a`   | `a`       |
| `{abc}`                | Unicode                | `abc` | `abc`     |
| `{a,b,c}`              | a,b,c                  | `a`   | `c`       |
| `{a..z,!d..f}`         | a$\dots$z$\notin$d,e,f | `a`   | unbounded |
| `{a..z}`               | a$\dots$z              | `a`   | unbounded |
| `{m..{@l}}`            | $a\dots$z              | `m`   | unbounded |
| `{{@l}..m}`            | $a\dots$z              | `a`   | `m`       |
| `{cat..dog}`           | Unicode                | `cat` | `dog`     |
| `{{@d}..255}`          | decimal                | `0`   | `255`     |
| `{128..{@d}}`          | decimal                | `128` | unbounded |
| `{aa..{@l}..zz}`       | a$\dots$z              | `aa`  | `zz`      |
| `{a}[3]`               | Unicode                | `aaa` | `aaa`     |
| `{a..z}[3]`            | a$\dots$z              | `aaa` | unbounded |
| `{a}[2..4]`            | a$\dots$z              | `aa`  | `aaaa`    |
| `{@d},{a..f}<->{A..F}` | hex (case-folded)      | `0`   | unbounded |

> **Note:** `{a..z}[3]` can be any string of any length of lowercase triples including 'aaa', 'ababab', and 'barbarbar'.

### Value Exclusion

Inside a union the positive arms set the universe and the `!` arms **subtract** from it, so `{...,!`$\Sigma$`}` is "everything written, minus $\Sigma$".

```proto
{aa..{a..z}..zz,!ff}       // 2-char lowercase, excluding 'ff'
{aa..{a..z}..zz,!ee..ff}   // 2-char lowercase, excluding 'ee', 'ef', 'fe', and 'ff'
{{@d}..255,!128..191}      // decimal 0, 1, through '255', excluding '128', '129', through '191'
{@d,@l,@u,!{0,l,I,O}}      // base58: digits and letters minus the four ambiguous glyphs
```

> **Note:** With no positive arm the universe defaults to the ambient alphabet, so `{!x}` is "any Unicode value except `x`" -- e.g. `{!**}` matches a run up to the next `**`.

---

## String-Token Alphabets

Comma-separated items inside `{...}` can be multi-character. The class defines a string-token alphabet where each item is a discrete token (singleton $\sigma$).

```proto
{cat,dog}     // 'cat' or 'dog'
{http,https}  // 'http' or 'https'
```

Token order matches write order. `..` between string tokens defines a lexicographic range. Any string between the two endpoints inclusive.

```proto
{cat,dog,fish}   // 'cat', 'dog', or 'fish'
{cat..dog}       // 'cat', 'cau', through 'dog'
```

> **Note:** Multi-character ranges without an explicitly declared $\Sigma$ use Unicode by default, so `{cat..dog}` can include 'c$\lambda$t'.

---

## Repetition

`[count]` repeats the preceding `{...}`. Every repetition must match the same value as the first.

| Form   | Meaning      |
| ------ | ------------ |
| `N`    | Exactly N    |
| `N..`  | N or more    |
| `..N`  | Zero to N    |
| `N..M` | N to M       |
| `..`   | Zero or more |

```proto
{a..z}[3]     // same string three times: 'aaa', 'ababab', through 'barbarbar'
{a..z}[2..5]  // same string 2-5 times
{0..9}[..]    // same string any number of times
```

---

### Padding

A plain value range matches only the **canonical** form of each value. `{{@d}..255}` matches '7' but not '007'. Padding relaxes the width:

| Form          | Width                |
| ------------- | -------------------- |
| `{N:expr}`    | Exactly `N`          |
| `{N..M:expr}` | `N` through `M`      |
| `{:expr}`     | 1 through `len(max)` |

```proto
{2:{@d}..99}     // '00', '01', through '99'
{3:{@d}..255}    // '000', '001', through '255'
{2..3:{@d}..255} // '00', '000', through '255'
{:{@d}..255}     // '0', '00', through '255'
```

---

## Congruence

`<->` ($\leftrightarrow$) **zips** two $\Sigma$s position-wise into one folded alphabet. It pairs `L[i]` with `R[i]`, and the i-th position then accepts either spelling. Only the surface forms fold, never the value axis. So `a` and `A` are one _position_ (`value('a') = value('A')`), not two.

```proto
{a<->A}                // 1 position: 'a' or 'A'        (the cardinality-1 zip)
{{a..z}<->{A..Z}}      // 26 positions: {a,A},{b,B},...,{z,Z}
{cat,dog}<->{CAT,DOG}  // 2 positions: {cat,CAT},{dog,DOG}
```

The enumerated form is just this zip written out -- a union of singleton zips -- so both forms below denote the same 3-position alphabet:

```proto
{a..c}<->{A..C}            // zip of two ranges
{{a<->A},{b<->B},{c<->C}}  // the same thing, written out
{a<->A}[2]                 // 'aa', 'aA', 'Aa', 'AA'
{{a..z}<->{A..Z}}[2]       // 'hh', 'hH', 'Hh', 'HH'; 'He' does not
```

> **Note:** Under `[count]`, repetition-equality is checked against the _position_, so the folded spellings count as the same value:

### Rules

- **Equal cardinality** -- `|L|` must equal `|R|` otherwise it is a compile error. E.g. `{a..z}<->{A..C}` (26 vs 3) is rejected.
- **Distinct spellings** -- Every spelling must name exactly one position. `{a..c}<->{b..d}` reuses `b` and `c` across positions, so it is rejected.
- **n-ary, per-position commutative** -- `{\n<->\r<->\r\n}` folds the three newline spellings into one position, so order within a position does not matter.

---

## Captures

Every `{...}` creates a capture group, numbered left to right from **0**. Sub-captures use dot notation.

| Reference  | Resolves to                  |
| ---------- | ---------------------------- |
| `{{.}}`    | Full matched text            |
| `{{N}}`    | Group N                      |
| `{{N.M}}`  | Sub-group M of group N       |
| `{{N..M}}` | Groups N through M inclusive |
| `{{#N}}`   | Repeat count of group N      |

So, given the input string: `"### Sphinx of black quartz, judge my vow!"` and the expression `{#}[1..] {Sphinx}{of{black}{quartz}}`:

| Reference  | Resolves to               | Explanation                     |
| ---------- | ------------------------- | ------------------------------- |
| `{{.}}`    | `### Sphinxofblackquartz` | The full matched text.          |
| `{{0}}`    | `###`                     | Group 0                         |
| `{{2}}`    | `ofblackquartz`           | Group 2                         |
| `{{2.0}}`  | `black`                   | First sub-group inside group 2  |
| `{{2.1}}`  | `quartz`                  | Second sub-group inside group 2 |
| `{{1..2}}` | `Sphinxofblackquartz`     | Span from group 1 to group 2.   |
| `{{#0}}`   | `3`                       | Repeat count of group 0         |

---

## Transformers

`=>` applies a replacement template to a match: `pattern => template => pattern => template`. `{{.}}` in a chained template is deferred to the next match expression.

- A run of patterns (`pattern => pattern => ... => template`) narrows successively before the trailing template renders.
- A **deferred `{{.}}`** applies the remaining chain to the current match **in place** -- matched spans are replaced, surrounding text is preserved.

```proto
{**}{!**}{**} => <strong>{{1}}</strong>
{*}{!*}{*} => <em>{{1}}</em>
```

---

## North Star Examples

TODO
