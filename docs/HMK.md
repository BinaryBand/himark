# Himark

**Version:** 0.1.0-draft  
**Status:** Draft Specification  
**License:** CC0 1.0 Universal (Public Domain)

---

Three constructs: `{...}` matches and captures, `<<...>>` spans and splits, `[...]` repeats.

| Construct | Role                      |
| --------- | ------------------------- |
| `{expr}`  | Match, capture, and class |
| `<<sep>>` | Span, split, and capture  |
| `[count]` | Repetition modifier       |

These compose as `{expr}[count]` and `<<sep>>[count]`.

---

## `{...}` Arithmetic

Expressions inside `{...}` are built from two types:

- **$\tau$** — any expression with cardinality 1: a bare string (`hello`, `a`, `ff`, `\n`), or a `{...}` whose only possible value is a single concrete string
- **$\alpha$** — an abstract group: a `{...}` expression representing every value it can produce

Every `{expr}` without an explicit count has an implicit `[1]`. This makes `{hello}` identical to `{hello}[1]` — and since it can only produce one value, it is $\tau$. The τ/α distinction is therefore about **cardinality**, not syntax: cardinality 1 is τ, cardinality > 1 is α.

| Form                         | Meaning                   |
| ---------------------------- | ------------------------- |
| $\tau$                       | Literal match             |
| $\tau_1$..$\tau_2$           | Character/string range    |
| $\alpha$                     | Full range                |
| $\alpha$..$\tau$             | Upper bound $\tau$        |
| $\tau$..$\alpha$             | Lower bound $\tau$        |
| $\tau_1$..$\alpha$..$\tau_2$ | Bounded range in $\alpha$ |
| $\alpha_1$..$\alpha_2$       | Zip (counts must match)   |

`,` joins expressions as a union. `{!expr}` is the complement — any value NOT in the group.

Which row applies is determined by cardinality. A bare string is always τ. A `{...}` sub-expression is τ if it is a singleton (e.g. `{z}[33]` → `"zzz…z"`), α otherwise.

```proto
{a..z, A..Z, 0..9}    // alphanumeric
{a..z, !d..f}         // lowercase, excluding d–f
```

Singleton `{...}` expressions used as bounds evaluate to their single concrete value at parse time:

```proto
{{1}[23]..{b58}..{z}[33]}  // b58 body bounded to the P2PKH value range
```

A `{...}` is singleton when its inner expression has cardinality 1 **and** its count is exact (`[N]`, not a range). `{a}[3]` → `"aaa"` ✓. `{a..z}[3]` ✗ (inner has cardinality 26). `{a}[2..4]` ✗ (count is a range).

```proto
{a..z, A..Z, 0..9}    // alphanumeric
{a..z, !d..f}         // lowercase, excluding d–f
```

### Value Exclusion

`,!σ` and `,!σ_1..σ_2` exclude a value or contiguous sub-range from any range expression:

```proto
{aa..{a..z}..zz, !ff}       // 2-char lowercase, excluding 'ff'
{aa..{a..z}..zz, !ee..ff}   // same, excluding 'ee' and 'ff'
{{dec}..255, !128..191}      // decimal 0–255, excluding 128–191
```

### Padding

`{N: expr}` fixes the match width to exactly `N` characters, padding with the alphabet's zero character. `{: expr}` accepts any width from 1 up to `len(max)`, allowing leading zeros.

```proto
{2: {dec}..99}    // '00' to '99'
{3: {dec}..255}   // '000' to '255'
{: {dec}..255}    // '0', '00', '000' through '255'
```

---

## Named Alphabets

Named alphabets expand to their equivalent class and act as $\alpha$ in arithmetic.

| Name    | Expands to                |
| ------- | ------------------------- |
| `dec`   | `0..9`                    |
| `hex`   | `0..9,a..f`               |
| `HEX`   | `0..9,A..F`               |
| `b32`   | `0..9,a..v` (RFC 4648 §7) |
| `b58`   | `1..9,A..Z,a..z,!I,!O,!l` |
| `b64`   | `A..Z,a..z,0..9,+,/`      |
| `b85`   | RFC 1924 Base85           |
| `ascii` | U+0000–U+007F             |
| `uni`   | U+0000–U+10FFFF           |

```proto
{{dec}..255}     // decimal 0–255
{{hex}..ff}      // hex 0–ff
{m..{a..z}}      // lowercase, from 'm' upward
{m..{a..z}..zz}  // lowercase, from 'm' to 'zz'
```

---

## String-Token Alphabets

When comma-separated items inside `{...}` are multi-character, the class defines a string-token alphabet — each item is a discrete token treated as $\tau$.

```proto
{cat,dog}     // 'cat' or 'dog'
{http,https}  // 'http' or 'https'
```

Token order matches write order. `..` between string tokens defines a lexicographic range — any string between the two endpoints inclusive:

```proto
{cat,dog,fish}   // 'cat', 'dog', or 'fish'
{cat..dog}       // cat,cau,...,dof,dog
```

---

## Grouped-class Alphabets

When `{...}` items are class expressions, the alphabet defines **equivalence groups** — sets of surface forms mapping to the same abstract position. Each group is one letter regardless of the physical length of its members.

Zip ($\alpha_1$..$\alpha_2$) steps through both classes in parallel:

```proto
{{a,A}..{z,Z}}       // 26 groups: a↔A, b↔B … z↔Z
{{a,A},{b,B},{c,C}}  // 3 groups, enumerated
{{a,bc},{def,ghi}}   // 2 groups with multi-char tokens
```

A grouped-class alphabet matches any string where each position satisfies one of the groups:

```proto
{{a,A}..{z,Z}}      // any word, any casing, any length
{{a,A}..{z,Z}}[2]   // same word twice — 'Hello' then 'hello' matches
```

---

## Repetition

`[count]` repeats the preceding `{...}` or `<<...>>`. Every repetition must match the same value as the first.

| Form   | Meaning      |
| ------ | ------------ |
| `N`    | Exactly N    |
| `N..`  | N or more    |
| `..N`  | Zero to N    |
| `N..M` | N to M       |
| `..`   | Zero or more |

```proto
{a..z}[3]     // same letter three times: 'aaa', 'bbb' …
{a..z}[2..5]  // same letter 2–5 times
{0..9}[..]    // same digit any number of times
```

The repeat count of any group is accessible as `{{#N}}`:

```proto
{#}[1..] { } {!\n}    // n hashes then a line; {{#0}} = hash count
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

`<<sep>>` captures the span between its bounding context and splits on every occurrence of `sep`. Lazy by default — the right boundary resolves to the nearest match.

```proto
<<\n>>         // split full input on newlines
<<>>           // full input as one segment
{X}<<sep>>{Y}  // span from X to Y, split on sep
```

---

## Transformers

`=>` applies a replacement template to a match:

```proto
{**}<<>>{**} => <strong>{{1}}</strong>
{*}<<>>{*}   => <em>{{1}}</em>
```

Chains: `pattern => template => pattern => template`. Each template output feeds the next match. `{{.}}` in a chained template is deferred — it resolves to the result of applying the remaining chain to the current match, not the raw text.

---

## Nesting

A `{...}` range expression may contain a full Himark sub-pattern, allowing complex structural constraints. Nesting syntax is not yet finalized — this section is a placeholder.

```proto
// intended: a b58 string whose first character is '1'
// syntax TBD
```

---

## North Star Examples

**Markdown headings:**

```proto
<<\n>> => {#}[1..6] { } {!\n} => <h{{#0}}>{{2}}</h{{#0}}>
```

**Bitcoin P2PKH address:**

```proto
{1}{11111111111111111111111..{b58}..zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz}
```

**IPv4:**

```proto
{{dec}..255} {.} {{dec}..255} {.} {{dec}..255} {.} {{dec}..255}
```
