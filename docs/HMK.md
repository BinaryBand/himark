# Himark Specification

**Version:** 0.6.2-draft  
**Status:** Draft Specification  
**License:** CC0 1.0 Universal (Public Domain)

<!-- cspell:words himark -->

---

Three constructs: `{...}` matches and captures, `<<...>>` spans and splits, `[...]` repeats.

| Construct | Role                      |
| --------- | ------------------------- |
| `{expr}`  | Match, capture, and class |
| `<<sep>>` | Span, split, and capture  |
| `[count]` | Repetition modifier       |

These compose as `{expr}[count]` and `<<sep>>`.

> **Note:** `{expr}` is implicitly identical to `{expr}[1]`.

---

## Shortcuts

Himark is designed to be strictly logically consistent at the cost of brevity. To combat over-verbosity, it uses text-based, pre-processing shortcuts.

### Implicit Containers

Every capture query is a finitely-bound alphabet, and every alphabet declaration in Himark must be `{}` or `<<>>` wrapped. If the leading pattern step contains no `{}` or `<<>>` construct at all, it is implicitly `{}` wrapped before tokenization. A step that already contains a construct is never rewrapped -- its bare text is literal. Steps after `=>` are never wrapped: a bare step there is a constant template (see Transformers).

> **E.g.:** `a..z` $\to$ `{a..z}`, `{{@d}..255}` stays as-is

### Macros

| Name     | Expands to                            |
| -------- | ------------------------------------- |
| `@d`     | `0..9`                                |
| `@l`     | `a..z`                                |
| `@u`     | `A..Z`                                |
| `@i`     | `{a<->A},{b<->B},` $\dots$ `,{z<->Z}` |
| `@s`     | `\n,\r, ,\t`                          |
| `@w`     | `{@i},_`                              |
| `@x`     | `!@s`                                 |
| `@hex`   | `{@d},{{@i}..f}`                      |
| `@b32`   | `{@d},{{@i}..v}` (RFC 4648 $\S7$)     |
| `@b58`   | `1..9,A..H,J..N,P..Z,a..k,m..z`       |
| `@b64`   | `{@d},{@i},+,/`                       |
| `@ascii` | U+0000-U+007F                         |
| `@uni`   | U+0000-U+10FFFF                       |

Macros may reference other macros; expansion repeats until the text is stable.

> **E.g.:** {@d} $\to$ {0..9}, {@l} $\to$ {a..z}

---

## Arithmetic

Expressions inside `{...}` and `<<...>>` are built from one type:

- **$\sigma$** -- an ordered alphabet; a bare string is a $\sigma$ with cardinality 1

| Operator | Role                                     |
| -------- | ---------------------------------------- |
| `..`     | Range between endpoints                  |
| `,`      | Union of $\sigma$'s                      |
| `<->`    | Congruence group                         |
| `!`      | Complement -- any value NOT in the group |

**Endpoint projection.** A $\sigma$ used as a `..` endpoint contributes an **alphabet** and an **extreme**. A singleton contributes its concrete value (alphabet = ambient Unicode). A class contributes its own alphabet, standing in for the natural extreme in its direction -- floor on the left, unbounded on the right.

| Written            | Alphabet  | Low         | High      |
| ------------------ | --------- | ----------- | --------- |
| `{a}`              | Unicode   | `a`         | `a`       |
| `{abc}`            | Unicode   | `abc`       | `abc`     |
| `{a..z}`           | a$\dots$z | `a`         | `z`       |
| `{m..{a..z}}`      | a$\dots$z | `m`         | unbounded |
| `{cat..dog}`       | Unicode   | `cat`       | `dog`     |
| `{{@d}..255}`      | decimal   | `0` (floor) | `255`     |
| `{128..{@d}}`      | decimal   | `128`       | unbounded |
| `{aa..{a..z}..zz}` | a$\dots$z | `aa`        | `zz`      |

A `{...}` is singleton when its inner expression has cardinality 1 **and** its count is exact (`[N]`, not a range).

> **Note:** An alphabet used as a `..` endpoint must have distinct symbols. `{{@d,@hex}..ff}` is an error -- the digits appear twice, so symbol values are ambiguous. Congruent spellings are one symbol, not duplicates: in `{{@hex}..ff}` the endpoint folds case, so `ff`, `fF`, and `FF` name the same value.

**Valid** -- `{a}[3]` $\to$ `aaa`
**Invalid** -- `{a..z}[3]` (inner has cardinality 26)
**Invalid** -- `{a}[2..4]` (count is a range).

```proto
{a..z,A..Z,0..9}  // alphanumeric
{a..z,!d..f}      // lowercase, excluding d, e, through f
{{@d}..255}       // decimal: 0, 1, through '255'
{{@hex}..ff}      // hex: 0, 1, through 'ff'
{m..{a..z}}       // lowercase: m, n, and upward
{m..{a..z}..zz}   // lowercase: m, n, through 'zz'
```

### Value Exclusion

!$\sigma$ and !$\sigma_1$..$\sigma_2$ exclude a value or contiguous sub-range from any range expression:

```proto
{aa..{a..z}..zz,!ff}       // 2-char lowercase, excluding 'ff'
{aa..{a..z}..zz,!ee..ff}   // 2-char lowercase, excluding 'ee', 'ef', 'fe', and 'ff'
{{@d}..255,!128..191}      // decimal 0, 1, through '255', excluding '128', '129', through '191'
```

### Padding

A plain value range matches only the **canonical** form of each value -- no leading zero characters, so every value corresponds to exactly one string. `{{@d}..255}` matches '7' but not '007'.

A multi-character lower endpoint sets a **minimum width**: values are zero-padded up to it, and canonical beyond it. `{aa..{a..z}..zz}` matches exactly the 2-char lowercase strings -- 'aa' is value 0 padded to width 2. Each value still has exactly one representation.

Padding relaxes the width:

| Form          | Width                              |
| ------------- | ---------------------------------- |
| `{N:expr}`    | Exactly `N`, zero-character padded |
| `{N..M:expr}` | `N` through `M`                    |
| `{:expr}`     | 1 through `len(max)`               |

```proto
{2:{@d}..99}     // '00', '01', through '99'
{3:{@d}..255}    // '000', '001', through '255'
{2..3:{@d}..255} // '00', '01', through '255'
{:{@d}..255}     // '0', '00', through '255'
```

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

## Grouped-class Alphabets

When `{...}` items are class expressions, the alphabet defines **equivalence groups** -- sets of surface forms mapping to the same abstract position. Each group is one letter regardless of the physical length of its members.

`<->` ($\leftrightarrow$) defines a **congruence group** -- a set of surface forms that are interchangeable at one position. Groups are enumerated; a multi-group class lists each group in its own brace:

```proto
{a<->A}                   // one group: 'a' and 'A' interchangeable
{{a<->A},{b<->B},{c<->C}} // 3 groups, enumerated
{{a<->bc},{def<->ghi}}    // 2 groups with multi-char tokens
```

Whitespace around `<->` is rejected; an escaped space (`'\ '`) is a literal part of the member. Multi-char members make congruence an **interleave** primitive -- a unit with and without a trailing separator are two spellings of one group:

```proto
{-\ <->-}[3..]                       // '---', '- - -', '-- -'; not '   '
{{-\ <->-},{*\ <->*},{_\ <->_}}[3..] // any Markdown horizontal rule
```

> **Note:** Group members must be singletons. A _range_ of congruence groups is written by enumerating them (`{{a<->A},..,{z<->Z}}`), not with `..` or class endpoints -- `{a<->A..z<->Z}` and `{{a..z}<->{A..Z}}` are errors. `{{a..z},{A..Z}}` is not a congruence either; it is a plain union of two classes.

Under `[count]`, repetition-equality is checked against the congruence group -- `a` and `A` count as the same value:

```proto
{a<->A}[2]               // 'aa', 'aA', 'Aa', 'AA' -- contrast {a,A}[2]: only 'aa' or 'AA'
{{a<->A},..,{z<->Z}}[2]  // same letter twice, any casing -- 'hh', 'hH', 'Hh', 'HH'; 'He' does not
```

---

## Repetition

`[count]` repeats the preceding `{...}`. Every repetition must match the same value as the first.

> **Note:** A count on `<<...>>` is a compile error; the syntax is reserved.

| Form   | Meaning      |
| ------ | ------------ |
| `N`    | Exactly N    |
| `N..`  | N or more    |
| `..N`  | Zero to N    |
| `N..M` | N to M       |
| `..`   | Zero or more |

```proto
{a..z}[3]     // same letter three times: 'aaa', 'bbb', through 'zzz'
{a..z}[2..5]  // same letter 2-5 times
{0..9}[..]    // same digit any number of times
```

The repeat count of any group is accessible as `{{#N}}`:

```proto
{#}[1..]{ }{!\n}      // n hashes then a line; {{#0}} = hash count
{a}[2..5]{b}[{{#0}}]  // [b] repeats same number of times as [a]
```

---

## Captures

Every `{...}` and `<<...>>` creates a capture group, numbered left to right from 0. Sub-captures use dot notation. The pattern root is transparent to indexing.

| Reference  | Resolves to                  |
| ---------- | ---------------------------- |
| `{{.}}`    | Full matched text            |
| `{{N}}`    | Group N                      |
| `{{N.M}}`  | Sub-group M of group N       |
| `{{N..M}}` | Groups N through M inclusive |
| `{{#N}}`   | Repeat count of group N      |

---

## Separators

`<<sep>>` captures the span between its bounding context and splits on every occurrence of `sep`. Lazy by default -- the right boundary resolves to the nearest match. `sep` may be a class: standalone, the input splits on every occurrence of the class; bounded, the class constrains the span.

<!-- cspell:disable -->

```proto
<<\n>>                          // split full input on newlines
<<>>                            // full input as one segment
<<!*>>                          // split on runs of anything but '*': '* * *' -> '*','*','*'
<<{a,b}>>                       // split on members: 'xaybz' -> 'x','y','z'
{X}<<sep>>{Y}                   // span from X to Y, split on sep
{aa<<{a..z}..zz>>aa} => {{.}}   // 'aaaaa', 'aabaa', through 'aazzaa'
{aa}<<{a..z}..zz>>{aa} => {{1}} // 'a', 'b', through 'zz'
```

<!-- cspell:enable -->

---

## Transformers

`=>` applies a replacement template to a match:

```proto
{**}<<>>{**} => <strong>{{1}}</strong>
{*}<<>>{*}   => <em>{{1}}</em>
```

Chains: `pattern => template => pattern => template`. `{{.}}` in a chained template is deferred -- it resolves to the result of applying the remaining chain to the current match, not the raw text.

Each step is a **pattern** (it contains `{}` or `<<>>` constructs and matches) or a **template** (it renders output). A template either contains `{{...}}` references or is bare text with no constructs at all -- a **constant template**, rendered as-is (`{\<} =>+ &lt;` replaces every `<` with `&lt;`). Two fold behaviors compose:

- At the **top level**, every match of the leading pattern is transformed, yielding one result per match; non-matches are dropped. A run of patterns (`pattern => pattern => ... => template`) narrows successively before the trailing template renders.
- A **deferred `{{.}}`** applies the remaining chain to the current match **in place** -- matched spans are replaced, surrounding text is preserved -- and the result is substituted for `{{.}}`.

```proto
{@d}[1..] => <{{.}}> => {@d} => #{{.}}   // '42' -> '<#4>', '<#2>'
```

### Extract vs. replace (`=>` / `=>+`)

The arrow has two forms, deciding the statement's output:

- `=>` **extracts** -- returns the list of rendered matches, dropping the text between them.
- `=>+` **replaces** -- splices each rendered match back into the source and returns the whole string, keeping the surrounding text verbatim. This is the document-transform mode: wrap the matches, keep the prose.

The statement's mode is taken from the **first** arrow.

```proto
{a..z} =>  <p>{{.}}</p>   // 'a1b2' -> ['<p>a</p>', '<p>b</p>']
{a..z} =>+ <p>{{.}}</p>   // 'a1b2' -> '<p>a</p>1<p>b</p>2'
{**<<>>**} =>+ <strong>{{0}}</strong>   // 'say **hi**' -> 'say <strong>hi</strong>'
```

### Pipes (inner `=>+`)

An **inner** `=>+` is a pipe: `pattern =>+ template` splices the template's output at the pattern's matches _within the current scope_, and the chain continues on the spliced text. Spans survive at scope granularity -- the outermost matches are the splice targets; piped stages are pure text computation. A piped splice **commits**: it is applied whether or not the rest of the chain matches.

```proto
{ }[1..] =>+ _                                     // top level: '+' on the first arrow is replace mode
<<\n>> =>+ {\ }[1..] =>+  => {-,*,_}[3..] => <hr>  // per line: drop spaces, then test the result
```

---

## North Star Examples

Patterns are whitespace-significant: any space written between constructs is a literal space the input must contain.

### Markdown translations

#### Headers

```proto
<<\n>> => {#}[1..6]{@s}[1..]<<>> => <h{{#0}}>{{2}}</h{{#0}}>
```

#### Decorators

```proto
{**<<>>**} => <strong>{{0}}</strong> // bold
{*<<>>*}   => <em>{{0}}</em>         // italic
{`<<>>`}   => <code>{{0}}</code>     // inline code
```

### Crypto Wallet Addresses

```proto
{1}{24..33:{@b58}}  // any valid Bitcoin address (P2PKH)
{0x}{40:{@hex}}     // any valid Ethereum address
```

> The above do not account for checksum verifications.

**IPv4:**

```proto
{{@d}..255}{.}{{@d}..255}{.}{{@d}..255}{.}{{@d}..255}
```

**Modest proposals:**

```proto
{{@d}..255}{.}<<{@d}..255>>[3]
{{@d}..255}{{\.{{@d}..255}}..{\.255}[3]}
{{@d}..255}{{.{{@d}..255}}..{.255}[3]}
```

| Written          | Alphabet             | Low  | High   |
| ---------------- | -------------------- | ---- | ------ |
| `{{@d}..255}`    | decimal              | `.1` | `.255` |
| `{.{{@d}..255}}` | '.0','.1',...,'.255' | `.1` | `.255` |

<!--
- Avoid using non-ASCII characters in this document
- Use '$\dots$' instead of '...' where context allows (e.g. not in codeblocks/comments)
- Use $\to$ instead of '->' where context allows
- Use $\leftrightarrow$ instead of '<->' where context allows
- '$\dots$/...' means arithmetic, '..' means Himark
- Codeblock: <series> // <note>: <0>, <1>, through <n>
- Definition: **<key>** -- <definition>
- Quote: > **Note:** <Note>.
- Quote: > **E.g.:** <Example>
- <char>, '<string>'
-->
