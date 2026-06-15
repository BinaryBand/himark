# Himark Specification

**Version:** 0.8.0-experimental  
**Status:** Draft Specification  
**License:** CC0 1.0 Universal (Public Domain)

<!-- cspell:words himark -->

---

Two constructs: `{...}` matches, and `[...]` repeats.

| Construct | Role                |
| --------- | ------------------- |
| `{expr}`  | Match and class     |
| `[count]` | Repetition modifier |

These compose as `{expr}[count]` where `{expr}` is implicitly identical to `{expr}[1]`.

This is the experimental algebra branch: the `<->`, `{{...}}`, and `>>`
constructs have been removed, and congruence is now expressed through the brace
grouping itself (see [Congruence](#congruence)).

---

## Macros

| Name     | Expands to                  |
| -------- | --------------------------- |
| `@d`     | `0..9`                      |
| `@l`     | `a..z`                      |
| `@u`     | `A..Z`                      |
| `@s`     | `\n,\r, ,\t`                |
| `@w`     | `{a,A},{b,B},...,{z,Z},_`   |
| `@x`     | `!@s`                       |
| `@hex`   | `{@d},{{@w}..f}`            |
| `@b32`   | `{@d},{{@w}..v}`            |
| `@b58`   | `{@d},{@u},{@l},!{0,I,O,l}` |
| `@b64`   | `{@d},{@l},{@u},+,/`        |
| `@ascii` | U+0000-U+007F               |
| `@uni`   | U+0000-U+10FFFF             |

> **Note:** `@w` enumerates each letter and its capital as one congruence class (`{a,A}`, `{b,B}`, ...), so `a` and `A` share one ordered position. `@hex` and `@b32` (RFC 4648 $\S7$) slice `@w`, so they stay base 16 / base 32 **and** case-insensitive at once (see [Congruence](#congruence)).

---

## Arithmetic

**$\Sigma$** represents an ordered alphabet. **$\sigma$** represents a singleton value (equivalently, a one-element alphabet).

| Operator | Role                                                   |
| -------- | ------------------------------------------------------ |
| `..`     | Ordered range between endpoints ($\leq$)               |
| `,`      | Congruence class -- interchangeable spellings ($\sim$) |
| `!`      | Subtract a $\Sigma$ from the group                     |

The two axes are orthogonal: `..` builds an **ordered** range (distinct positions, a value axis), while `,` folds its members into **one** congruence class (interchangeable spellings of a single position). A $\Sigma$ used as a `..` endpoint contributes an **alphabet** and an **extreme**. A singleton $\sigma$ contributes its concrete value (alphabet = ambient Unicode). A class contributes its own alphabet, standing in for the natural extreme in its direction -- floor on the left, unbounded on the right.

> **Note:** Precedence binds tightest to loosest: `..` then `,`.

| Written          | Alphabet               | Low   | High      |
| ---------------- | ---------------------- | ----- | --------- |
| `{a}`            | Unicode                | `a`   | `a`       |
| `{abc}`          | Unicode                | `abc` | `abc`     |
| `{a,b,c}`        | one class {a,b,c}      | --    | --        |
| `{a..z,!d..f}`   | a$\dots$z$\notin$d,e,f | `a`   | unbounded |
| `{a..z}`         | a$\dots$z              | `a`   | unbounded |
| `{m..{@l}}`      | $a\dots$z              | `m`   | unbounded |
| `{{@l}..m}`      | $a\dots$z              | `a`   | `m`       |
| `{cat..dog}`     | Unicode                | `cat` | `dog`     |
| `{{@d}..255}`    | decimal                | `0`   | `255`     |
| `{128..{@d}}`    | decimal                | `128` | unbounded |
| `{aa..{@l}..zz}` | a$\dots$z              | `aa`  | `zz`      |
| `{a}[3]`         | Unicode                | `aaa` | `aaa`     |
| `{a..z}[3]`      | a$\dots$z              | `aaa` | unbounded |
| `{a}[2..4]`      | a$\dots$z              | `aa`  | `aaaa`    |

> **Note:** `{a..z}[3]` can be any string of any length of lowercase triples including 'aaa', 'ababab', and 'barbarbar'.

### Value Exclusion

Inside a range the positive arms set the universe and the `!` arms **subtract** from it, so `{...,!`$\Sigma$`}` is "everything written, minus $\Sigma$".

```proto
{aa..{a..z}..zz,!ff}       // 2-char lowercase, excluding 'ff'
{aa..{a..z}..zz,!ee..ff}   // 2-char lowercase, excluding 'ee', 'ef', 'fe', and 'ff'
{{@d}..255,!128..191}      // decimal 0, 1, through '255', excluding '128', '129', through '191'
{@d,@l,@u,!{0,l,I,O}}      // base58: digits and letters minus the four ambiguous glyphs
```

> **Note:** With no positive arm the universe defaults to the ambient alphabet, so `{!x}` is "any Unicode value except `x`" -- e.g. `{!**}` matches a run up to the next `**`.

---

## Congruence

`,` folds its members into one **congruence class** ($\sim$): a single position with several interchangeable spellings. This is the orthogonal partner of `..` -- where `..` is the ordered value axis, `,` is the equality axis.

```proto
{a,A}          // one position, two spellings: 'a' or 'A'
{cat,dog}      // one position, two spellings: 'cat' or 'dog'
{a,b,c}        // one position, three spellings
```

To build an **ordered alphabet of folded positions**, enumerate the classes -- the outer braces order the positions, each inner `{...}` is one class:

```proto
{{a,A},{b,B},{c,C}}   // 3 ordered positions, each case-folded
{{a,A},{b,B},...,{z,Z}}  // the 26-letter case-fold alphabet (this is @w)
```

Under `[count]`, repetition-equality is checked against the **class**, not the literal spelling, so congruent spellings count as the same unit:

```proto
{a,A}[2]              // 'aa', 'aA', 'Aa', 'AA'  (case folds)
{{a,A},{b,B}}[2]      // 'ab', 'aB', 'Ab', 'AB', and the same for repeats of one letter
                      // -- but 'a' then 'b' are different positions, so each rep is one class
{a,bc}[2]             // 'a' and 'bc' share a class, so 'abc', 'aa', 'bcbc' all repeat equally
```

This is `(\Sigma, \leq, \sim)` realized with one primitive: `..` reads the order `\leq`, `,` reads the congruence `\sim`, and `[count]` is the `\sim`-congruent power. The literal-identity relation is the finest `\sim` (every spelling its own class); a comma-list coarsens it.

> **Note:** A class-to-class **range** (`{a..z}..{A..Z}`) is rejected -- two classes have no shared ordering. Enumerate the folded pairs as a class of classes (`{{a,A},...,{z,Z}}`) instead.

A class member may be an escaped whitespace spelling, which makes `[count]` an interleave (a separator that is optional between repetitions, never alone):

```proto
{{-\ ,-},{*\ ,*}}[3..]   // '---', '- - -', '-- -' (rule chars, optional spaces)
```

---

## Repetition

`[count]` repeats the preceding `{...}`.

| Form   | Meaning      |
| ------ | ------------ |
| `N`    | Exactly N    |
| `N..`  | N or more    |
| `..N`  | Zero to N    |
| `N..M` | N to M       |
| `..`   | Zero or more |

What "repeats" means depends on what is repeated:

- A **class** (an alphabet -- `{a..z}`, `{cat,dog}`, a value range) repeats **by value**: every repetition matches the same value (or congruence class) as the first.
- A **grouping brace** (a `{...}` whose interior is a sequence of constructs) repeats **by shape**: each repetition re-matches the structure, and its content may differ between repetitions.

```proto
{a..z}[3]     // class: same string three times -- 'aaa', 'ababab', through 'barbarbar'
{a..z}[2..5]  // class: same string 2-5 times
{0..9}[..]    // class: same string any number of times
{{|}{!|,\n}}[3]   // grouping brace: three '|'+cell units, each a different cell
```

The structural form is what lets a single pattern walk a homogeneous block -- e.g. the cells of a row, repeated by shape so each cell may hold different text.

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

## Captures

Every `{...}` creates a capture group, numbered left to right from **0**. A grouping brace nests its inner braces as **sub-captures**.

Given the input `"### Sphinx of black quartz, judge my vow!"` and the expression `{#}[1..]{Sphinx}{of{black}{quartz}}`:

| Group     | Text                     | Explanation                     |
| --------- | ------------------------ | ------------------------------- |
| full      | `###Sphinxofblackquartz` | The full matched text.          |
| 0         | `###`                    | Group 0                         |
| 1         | `Sphinx`                 | Group 1                         |
| 2         | `ofblackquartz`          | Group 2                         |
| 2.0       | `black`                  | First sub-group inside group 2  |
| 2.1       | `quartz`                 | Second sub-group inside group 2 |

> **Note:** The capture structure is available on each `Match` (`groups`, `sub_groups`, spans); this branch has no reference sub-language for splicing them into output.

---

## Transformers

`=>` runs a chain of steps: `pattern => pattern => ... => template`.

- A run of patterns (`pattern => pattern`) narrows successively: each match of one pattern is fed to the next.
- A trailing **template** step (text with no matchable `{...}`) emits its constant text once per match.
- `=>` **extracts** -- the statement returns the list of rendered matches.
- `=>+` **replaces** -- it splices each rendered match back into the source and returns the whole string, leaving the text between matches verbatim.

```proto
{a..z}                 // extract: the list of lowercase runs
{a..z} => <w>          // extract: '<w>' once per run
{a..z} =>+ <w>         // replace: each run becomes '<w>' in place
{@d} => {{@d}..9}      // narrow: digits, then single values 0-9
```

### Quoting static text

Literal text may be written in double quotes, which is emitted verbatim with `\"`, `\\`, and `\n` escapes. A lone `'` is an ordinary character -- it is **not** a synonym for `"`.

```proto
{a} => "<b>"   // emits the literal text <b>
"it's fine"    // ' needs no escaping
```

---

## North Star Examples

TODO
