# Himark Specification

**Version:** 0.0.1-experimental  
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
| `@hex`   | `{@d},{{@w}..f<->F}`        |
| `@b32`   | `{@d},{{@w}..v<->V}`        |
| `@b58`   | `{@d},{@u},{@l},!{0,I,O,l}` |
| `@b64`   | `{@d},{@l},{@u},+,/`        |
| `@ascii` | U+0000-U+007F               |
| `@uni`   | U+0000-U+10FFFF             |

> **Note:** `@hex` and `@b32` (RFC 4648 $\S7$) fold case with `<->` (see [Congruence](#congruence)), so `a` and `A` share one position -- the alphabets stay base 16 and base 32, and either casing matches.

---

## Arithmetic

- **$\sigma$** -- an ordered alphabet; a bare string is a $\sigma$ with cardinality 1

| Operator | Role                                                 |
| -------- | ---------------------------------------------------- |
| `..`     | Range between endpoints                              |
| `<->`    | Congruence -- zip two equal-length $\sigma$'s to one |
| `,`      | Union of $\sigma$'s                                  |
| `!`      | Complement -- subtract a $\sigma$ from the group     |

Precedence binds tightest to loosest: `..` then `<->` then `,`. So `{a..f<->A..F}` is `(a..f)<->(A..F)`, and `{@d,a..f<->A..F}` unions the digits with that zip. The `!` complement subtracts within a union (see [Value Exclusion](#value-exclusion)).

**Endpoint projection.** A $\sigma$ used as a `..` endpoint contributes an **alphabet** and an **extreme**. A singleton contributes its concrete value (alphabet = ambient Unicode). A class contributes its own alphabet, standing in for the natural extreme in its direction -- floor on the left, unbounded on the right.

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

`!`$\sigma$ is the complement of $\sigma$. Inside a union the positive arms set the universe and the `!` arms **subtract** from it, so `{...,!`$\sigma$`}` is "everything written, minus $\sigma$". The operand is any $\sigma$ -- a value, a sub-range, or a set:

```proto
{aa..{a..z}..zz,!ff}       // 2-char lowercase, excluding 'ff'
{aa..{a..z}..zz,!ee..ff}   // 2-char lowercase, excluding 'ee', 'ef', 'fe', and 'ff'
{{@d}..255,!128..191}      // decimal 0, 1, through '255', excluding '128', '129', through '191'
{@d,@l,@u,!{0,l,I,O}}      // base58: digits and letters minus the four ambiguous glyphs
```

With no positive arm the universe defaults to the ambient alphabet, so `{!x}` is "any value except `x`" -- e.g. `{!**}` matches a run up to the next `**`.

---

## String-Token Alphabets

When comma-separated items inside `{...}` are multi-character, the class defines a string-token alphabet -- each item is a discrete token (singleton $\sigma$).

```proto
{cat,dog}     // 'cat' or 'dog'
{http,https}  // 'http' or 'https'
```

Token order matches write order. `..` between string tokens defines a lexicographic range -- any string between the two endpoints inclusive:

```proto
{cat,dog,fish}   // 'cat', 'dog', or 'fish'
{cat..dog}       // 'cat', 'cau', through 'dog'
```

> **Note:** Declaring a multi-character range without an explicit $\sigma$ means it uses Unicode by default. `{cat..dog}` includes 'cat', 'dog', and 'cup', but it also includes c$\lambda$t.

---

## Congruence

`<->` ($\leftrightarrow$) **zips** two $\sigma$'s position-wise into one folded alphabet: it pairs `L[i]` with `R[i]`, and the i-th position then accepts either spelling. The result keeps `L`'s ordering and cardinality -- only the surface forms fold, never the value axis. So `a` and `A` are one _position_ (`value('a') = value('A')`), not two.

```proto
{a<->A}                // 1 position: 'a' or 'A'        (the cardinality-1 zip)
{{a..z}<->{A..Z}}      // 26 positions: {a,A},{b,B},...,{z,Z}
{cat,dog}<->{CAT,DOG}  // 2 positions: {cat,CAT},{dog,DOG}
```

The enumerated form is just this zip written out -- a union of singleton zips -- so both forms below denote the same 3-position alphabet:

```proto
{a..c}<->{A..C}            // zip of two ranges
{{a<->A},{b<->B},{c<->C}}  // the same thing, written out
```

**Rules.**

- **Equal cardinality.** `|L|` must equal `|R|`; otherwise it is a compile error. `{a..z}<->{A..C}` (26 vs 3) is rejected -- a mismatch is an incoherent claim ("these 26 letters are those 3"), not a request to truncate.
- **Distinct spellings** when the result is used for value (a `..` endpoint or `[count]`): every spelling must name exactly one position. `{a..c}<->{b..d}` reuses `b` and `c` across positions, so it is rejected.
- **n-ary, per-position commutative.** `{\n<->\r<->\r\n}` folds the three newline spellings into one position; order within a position does not matter.

Under `[count]`, repetition-equality is checked against the _position_, so the folded spellings count as the same value:

```proto
{a<->A}[2]               // 'aa', 'aA', 'Aa', 'AA' -- contrast {a,A}[2]: only 'aa' or 'AA'
{{a..z}<->{A..Z}}[2]     // same letter twice, any casing -- 'hh', 'hH', 'Hh', 'HH'; 'He' does not
```

Folding is the one thing union and range cannot express: it collapses two ordered tracks onto a single axis _without_ losing place value, which is why `@hex` can be base-16 and case-insensitive at once (`{@d},{a..f}<->{A..F}`).

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

## Transformers

`=>` applies a replacement template to a match:

```proto
{**}{!**}{**} => {!**} => <strong>{{.}}</strong>
{*}{!*}{*}    => {!*}  => <em>{{.}}</em>
```

Chains: `pattern => template => pattern => template`. `{{.}}` in a chained template is deferred -- it resolves to the result of applying the remaining chain to the current match, not the raw text.

- At the **top level**, every match of the leading pattern is transformed, yielding one result per match; non-matches are dropped. A run of patterns (`pattern => pattern => ... => template`) narrows successively before the trailing template renders.
- A **deferred `{{.}}`** applies the remaining chain to the current match **in place** -- matched spans are replaced, surrounding text is preserved -- and the result is substituted for `{{.}}`.

### Extract vs. replace (`=>` / `=>+`)

The arrow has two forms, deciding the statement's output:

- `=>` **extracts** -- returns the list of rendered matches, dropping the text between them.
- `=>+` **replaces** -- splices each rendered match back into the source and returns the whole string, keeping the surrounding text verbatim. This is the document-transform mode: wrap the matches, keep the prose.

The statement's mode is taken from the **first** arrow.

```proto
{a..z} =>  <p>{{.}}</p>   // 'a1b2' -> ['<p>a</p>', '<p>b</p>']
{a..z} =>+ <p>{{.}}</p>   // 'a1b2' -> '<p>a</p>1<p>b</p>2'
```

---

## North Star Examples

TODO
