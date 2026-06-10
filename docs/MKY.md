# Marky

**Version:** 0.1.0-draft  
**Status:** Draft Specification  
**License:** CC0 1.0 Universal (Public Domain)

---

`[...]` and `<<...>>` are the primary constructs — they match and capture. `{...}` and `(...)` are modifiers that refine a capture's character class and repetition. Neither modifier is valid without an accompanying primary construct.

| Construct | Role                     |
| --------- | ------------------------ |
| `[text]`  | Match and capture        |
| `<<sep>>` | Span, split, and capture |
| `{class}` | Character class modifier |
| `(count)` | Repetition modifier      |

Every `[...]` and `<<...>>` implicitly carries `{unicode}` and `(1)` unless overridden. These compose as `{class}[range](count)` and `{class}<<sep>>(count)`, with modifiers optional.

---

## Formal Rules

### Implicit defaults

Every construct expands to the full `{class}[range](count)` form. Omitted components take these defaults:

| Written      | Expands to            |
| ------------ | --------------------- |
| `[...]`      | `{unicode}[...](1)`   |
| `{...}[...]` | `{...}[...](1)`       |
| `[...](...)` | `{unicode}[...](...)` |
| `{...}`      | `{...}[..](1)`        |
| `(...)`      | compile error         |

`{...}` standing alone is a shortcut exception to the modifier-requires-primary rule. It expands to `{...}[..](1)` at parse time before semantic analysis. `{...}` = `{...}[..]` = `{...}[..](1)` are all equivalent.

> `<<...>>` is interchangeable with `[...]` in the first three rows. The `{...}` shorthand expands to `[..]` specifically — `<<..>>` has no equivalent shorthand.

### Full-range wildcard

`[..]` matches the full range of the associated class — any value the class can produce. With the implicit `{unicode}` class, `[..]` matches any single character.

```proto
{a..z}[..]   // any one lowercase letter     (same as {a..z}[a..z])
{hex}[..]    // any one hex character         (same as {hex}[0..f])
[..]         // any one unicode character
```

### Count ranges

| Form   | Meaning                        |
| ------ | ------------------------------ |
| `N`    | Exactly N                      |
| `N..`  | N or more                      |
| `..N`  | Zero to N (sugar for `0..N`)   |
| `N..M` | N to M                         |
| `..`   | Zero or more (sugar for `0..`) |

`(..)` and `(0..)` are identical.

---

## Match

`[text]` matches a literal string and captures it.

```proto
[a]       // 'a'
[**]      // '**'
[hello]   // 'hello'
[\n]      // newline
```

> A top-level expression without outer brackets is implicitly one group. Therefore, a lone `abc` is equivalent to `[abc]`.

## Character Classes

`{...}` is a class modifier on a following `[...]` or `<<...>>`. It declares the valid character set using `..` (range) and `,` (ordered join and enumeration).

```proto
{a..z}                // a through z
{0..9}                // digits
{a,e,i,o,u}           // enumerated chars
{0..9,a..f}           // hex: 0–9 then a–f
{a..z,A..Z,0..9}      // alphanumeric
```

Unicode codepoint order is the default for all ranges. No implicit inference.

### Class complement

`{!...}` matches any character NOT in the class.

```proto
{!*}         // not '*'
{!\n}        // not newline
{!a..z}      // not a lowercase letter
{a..z,!d..f} // lowercase letter, not d, e, or f
```

### Named alphabets

Named alphabets are aliases for `,`-joined ranges.

| Alias | Expands to                |
| ----- | ------------------------- |
| `dec` | `0..9`                    |
| `hex` | `0..9,a..f`               |
| `b32` | `0..9,a..v` (RFC 4648 §7) |
| `b58` | `1..9,A..Z,a..z,!I,!O,!l` |
| `b64` | `A..Z,a..z,0..9,+,/`      |

```proto
{b58}[1..z]    // one base58 character
{hex}[0..f]    // one hex character
```

## Value Ranges

`{class}[min..max]` matches strings whose value falls within a range. Values are interpreted as positional integers in the alphabet defined by the class, with the first character in class order as digit zero. Strings must be in canonical form — no leading zeros, where the zero character is the first character in class order — unless the `:` padding prefix is used.

```proto
{dec}[5..99]        // '5' to '99'
{dec}[0..255]       // any decimal 0–255
{hex}[0..ff]        // '0' to 'ff'
{b58}[1..z]         // base58 '1' to 'z' (single char)
{a..z}[a..zzz]      // lowercase strings 1–3 chars, canonical ('aa', 'ab', 'aaa' … excluded)
{a..z}[a..]         // any lowercase string, unbounded
```

### Value exclusion

`,!value` excludes a specific string from the range. `,!min..max` excludes a contiguous sub-range of values.

```proto
{a..z}[aa..zz,!ff]       // any 2-char lowercase string, excluding 'ff'
{a..z}[aa..zz,!ee..ff]   // any 2-char lowercase string, excluding 'ee' and 'ff'
{dec}[0..255,!128..191]  // decimal 0–255, excluding 128–191
```

### Padding

`[N:min..max]` fixes the width to exactly `N` characters. `[:min..max]` accepts any width from 1 up to `len(max)`, allowing leading zeros. The upper bound must be a literal string when using `[:]`; use `[N:]` when the upper bound is not fixed.

```proto
{dec}[2:0..99]    // '00' to '99' (exactly 2 digits)
{dec}[3:0..255]   // '000' to '255' (exactly 3 digits)
{dec}[:0..255]    // '0', '00', '000' through '255' — any width up to 3
{dec}[:..255]     // Same as '{dec}[:0..255]'
{hex}[2:0..ff]    // '00' to 'ff'
{a..z}[:a..zzz]   // 'a'..'z', 'aa'..'zz', 'aaa'..'zzz' — leading 'a's accepted
```

## Repetition

`(count)` is a repetition modifier on the preceding `[...]` or `<<...>>`. It enforces content equality — every repetition must match the same value as the first.

```proto
{a..z}[a..z](2)    // same letter twice: 'aa', 'bb', …
{a..z}[a..z](2..5) // same letter 2–5 times
{0..9}[0..9](1..)  // same digit one or more times
[ab](3)            // 'ababab'
[#](n)             // n hash chars, n bound as variable
[#](2..n)          // n hash chars where n is at least 2
[#](2..n..5)       // n hash chars where n is between 2 and 5
```

### Varied repetition

Variable letters bind at first occurrence (left-to-right) and must be consistent.

```proto
[#](n) {!\n}[..](m)   // n hashes then m non-newline chars, n and m independent
```

A conflicting variable bound is a compile error.

## Negation

`{!class}[..]` matches maximal runs of characters not in the class.

```proto
{!*}[..]        // runs with no '*'
{!\n}[..]       // runs not containing newline (= one line of text)
{!a..z}[..]     // runs not containing any lowercase letter
```

## Sequences

Constructs placed adjacently match left to right. Whitespace between constructs is insignificant.

```proto
[hello][ ][world]                          // 'hello world'
[**]<<>>[**]                               // bold: from '**' to nearest '**'
{dec}[0..255] [.] {dec}[0..255]            // 'N.N'
{dec}[0..255] [.] {dec}[0..255]
  [.] {dec}[0..255] [.] {dec}[0..255]      // IPv4
```

## Alternation

`||` separates alternative patterns. Alternation binds less tightly than sequencing.

```proto
[hello] || [world]
{dec}[0..255] || {hex}[0..ff]
[1]{b58}[a..] || [3]{b58}[a..]             // P2PKH or P2SH
```

## Captures

Every `[...]` and `<<...>>` creates a capture group, numbered left to right from 0. `{...}` and `(...)` modifiers do not create groups. Sub-captures within a group use dot notation and are also 0-indexed.

```proto
[**]<<>>[**]
// Group 0: [**]   Group 1: <<>>   Group 2: [**]

{dec}[0..255] [.] {dec}[0..255] [.] {dec}[0..255] [.] {dec}[0..255]
// Groups 0,2,4,6: each {dec}[0..255]   Groups 1,3,5: each [.]
```

The pattern root is transparent to indexing — references start from the root's children. This applies whether the root is implicit or an explicit outer `[...]`, so wrapping a pattern in `[...]` does not renumber internal references. Only the outermost level is transparent; any non-root `[...]` occupies an index normally.

```proto
[[a][b]][c]
// {{0}} = [[a][b]],  {{0.0}} = [a],  {{0.1}} = [b],  {{1}} = [c]
```

Capture references:

| Reference  | Resolves to                        |
| ---------- | ---------------------------------- |
| `{{.}}`    | Full matched text                  |
| `{{0}}`    | First capture group                |
| `{{N}}`    | Capture group N (0-indexed)        |
| `{{N.M}}`  | Sub-group M of group N (0-indexed) |
| `{{N..M}}` | Groups N through M inclusive       |

## Nesting

The range slot `[...]` in a value range expression accepts a nested Marky pattern, allowing complex range definitions.

```proto
{b58}[ [1] {b58}[a..] ]          // b58 string that itself starts with '1'
{dec}[ {dec}[0..255](4) ]        // decimal encoding of a 4-repetition pattern
```

## Transformers

`=>` applies a replacement template to a match.

| Variable   | Resolves to                                 |
| ---------- | ------------------------------------------- |
| `{{.}}`    | Full matched text (or deferred — see below) |
| `{{N}}`    | Capture group N (0-indexed)                 |
| `{{N.M}}`  | Sub-group M of group N                      |
| `{{N..M}}` | Groups N through M inclusive                |
| `{{n}}`    | Varied-repetition count variable n          |

```proto
[**]<<>>[**] => <strong>{{1}}</strong>
[*]<<>>[*]   => <em>{{1}}</em>
```

### Linear chains

`pattern => template1 => pattern2 => template2` — the output of each template becomes the input for the next pattern match.

```proto
[X][Y] => {{0}}   // positive lookahead: keep X, discard Y
[X][Y] => {{1}}   // positive lookbehind: discard X, keep Y
```

### Nested chains

When a chain contains further `pattern => template` pairs after a template, `{{.}}` in that template is **deferred** — it resolves to the result of applying the remaining chain to the current match, not the raw matched text. Execution proceeds inside-out.

```proto
P1 => <outer>{{.}}</outer> => P2 => <inner>{{.}}</inner>
```

1. `P2` matches within each `P1` match and produces `<inner>…</inner>`
2. `P1`'s template wraps that result: `<outer><inner>…</inner></outer>`

**Markdown table** (basic — all cells as `<td>`):

```proto
[*table] => <table>{{.}}</table>
  => [*row]  => <tr>{{.}}</tr>
  => [*cell] => <td>{{.}}</td>
```

Each level's `{{.}}` defers to the transformed output of the levels below it. The chain executes deepest-first: cells resolve, then rows wrap them, then the table wraps rows.

> `[*...]` represents placeholder queries in the above example.

## Separators

`<<sep>>` captures the span between its bounding context and splits it on every occurrence of `sep`. With no sep, the full span is returned as one unsplit segment. The right boundary resolves to the **nearest** match — `<<>>` is lazy by default.

```proto
<<\n>>            // split full input on newlines
<<>>              // full input as one segment
[X]<<sep>>[Y]     // span from X to Y, split on sep; X and Y captured as separate groups
```

---

## Reference

### Escape sequences

| Sequence | Meaning           |
| -------- | ----------------- |
| `\\`     | Literal backslash |
| `\[`     | Literal `[`       |
| `\]`     | Literal `]`       |
| `\{`     | Literal `{`       |
| `\}`     | Literal `}`       |
| `\t`     | Tab               |
| `\n`     | Newline           |
| `\r`     | Carriage return   |

---

## North Star Examples

### Bitcoin P2PKH address (no checksum)

```proto
[1] {b58}[11111111111111111111111..zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz]
```

--or--

```proto
[1]{b58}[[1](23)..[z](33)]
```

- `[1]` — literal version byte for P2PKH
- `{b58}[...]` — 24–33 base58 chars in valid payload range

P2PKH or P2SH:

```proto
  [1] {b58}[1(24)..z(33)]
||[3] {b58}[1(24)..z(33)]
```

### Markdown → HTML

**Headings** (`#`–`######`):

```proto
<<\n>> => [#](1..n..6) [ ] {!\n}[..] => <h{{n}}>{{2}}</h{{n}}>
```

**Bold**:

```proto
[**<<>>**] => <strong>{{0.0}}</strong>
```

**Italic**:

```proto
[*<<>>*] => <em>{{0.0}}</em>
```

**Inline code**:

```proto
[`]<<>>[`] => <code>{{1}}</code>
```

**Link**:

```proto
[\[<<>>\]] [(<<>>)] => <a href="{{1.0}}">{{0.0}}</a>
```

**Paragraph** (blank-line separated):

```proto
<<\n\n>> => <p>{{.}}</p>
```
