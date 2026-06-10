# Marky

**Version:** 0.1.0-draft  
**Status:** Draft Specification  
**License:** CC0 1.0 Universal (Public Domain)

---

The three primary constructs:

| Construct | Role                        |
| --------- | --------------------------- |
| `[text]`  | Literal match               |
| `{class}` | Character class / alphabet  |
| `(count)` | Content-equality repetition |

These compose: `{class}[range](count)`, with any subset valid.

---

## Literals

`[text]` matches a literal string. Does not create a capture group.

```proto
[a]       // 'a'
[**]      // '**'
[hello]   // 'hello'
[\n]      // newline
```

## Character Classes

`{...}` declares a character class using `..` (range) and `,` (ordered join and enumeration).

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

Named alphabets are aliases for `,`-joined ranges and are second-class.

| Alias | Expands to                |
| ----- | ------------------------- |
| `dec` | `0..9`                    |
| `hex` | `0..9,a..f`               |
| `b32` | `0..9,a..v` (RFC 4648 §7) |
| `b58` | `1..9,A..Z,a..z,!I,!O,!l` |
| `b64` | `A..Z,a..z,0..9,+,/`      |

```proto
{b58}    // one base58 character
{hex}    // one hex character
```

## Value Ranges

`{class}[min..max]` matches strings whose value falls between `min` and `max`. Values are interpreted as positional integers in the alphabet defined by the class, with the first character in class order as digit zero. By default, strings must be in canonical form — no leading zeros, where the zero character is the first character in class order.

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
{hex}[2:0..ff]    // '00' to 'ff'
{a..z}[:a..zzz]   // 'a'..'z', 'aa'..'zz', 'aaa'..'zzz' — leading 'a's accepted
```

## Repetition

`(count)` enforces content equality — every repetition must match the same value as the first. Applies to the immediately preceding construct.

```proto
{a..z}(2)          // same letter twice: 'aa', 'bb', …
{a..z}(2..5)       // same letter 2–5 times
{0..9}(1..)        // same digit one or more times
[ab](3)            // 'ababab'
[#](n)             // n hash chars, n bound as variable
[#](2..n)          // n hash chars where N is at least 2
[#](2..n..5)       // n hash chars where N is between 2 and 5
```

### Varied repetition

Variable letters bind at first occurrence (left-to-right) and must be consistent.

```proto
[#](n) {!\n}[a..](m)   // n hashes then m non-newline chars, n and m independent
```

A conflicting variable bound is a compile error.

## Negation

`{!}[..]` matches maximal runs of characters not containing `pattern`.

```proto
{!*}[..]        // runs with no '*'
{!\n}[..]       // runs not containing newline (= one line of text)
{!a..z}[..]     // runs not containing any lowercase word
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

`||` separates alternative patterns at any level.

```proto
[hello] || [world]
{dec}[0..255] || {hex}[0..ff]
[1]{b58}[a..] || [3]{b58}[a..]             // P2PKH or P2SH
```

## Captures

`{...}` and `{...}[...]` constructs create numbered capture groups, left to right. Literals `[...]` do not capture. Nested groups use dot notation.

```proto
[**]<<>>[**]
// Group 1: <<>>

{dec}[0..255] [.] {dec}[0..255] [.] {dec}[0..255] [.] {dec}[0..255]
// Groups 1–4: each {dec}[0..255]
```

## Nesting

The range slot `[...]` in a value range expression accepts a nested Marky pattern, allowing complex range definitions.

```proto
{b58}[ [1] {b58}[a..] ]          // b58 string that itself starts with '1'
{dec}[ {dec}[0..255](4) ]        // decimal encoding of a 4-repetition pattern
```

## Transformers

`=>` applies a replacement template to a match.

| Variable  | Resolves to                                 |
| --------- | ------------------------------------------- |
| `{{.}}`   | Full matched text (or deferred — see below) |
| `{{N}}`   | Capture group N                             |
| `{{N.M}}` | Sub-group M of group N                      |
| `{{n}}`   | Varied-repetition count variable n          |

```proto
[**]<<>>[**] => <strong>{{1}}</strong>
[*]<<>>[*]   => <em>{{1}}</em>
```

### Linear chains

`pattern => template1 => pattern2 => template2` — the output of each template becomes the input for the next pattern match.

```proto
[X][Y] => {{1}}   // positive lookahead: keep X, discard Y
[X][Y] => {{2}}   // positive lookbehind: discard X, keep Y
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

`<<sep>>` splits the input on a delimiter, producing segments.

```proto
<<\n>>            // split on newlines
<<>>              // no split — full span as one segment
[X <<sep>> Y]     // span from X to Y, split on sep
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
<<\n>> => [#](1..n..6) [ ] {!\n}[..] => <h{{n}}>{{1}}</h{{n}}>
```

**Bold**:

```proto
[**]<<>>[**] => <strong>{{1}}</strong>
```

**Italic**:

```proto
[*]<<>>[*] => <em>{{1}}</em>
```

**Inline code**:

```proto
[`]<<>>[`] => <code>{{1}}</code>
```

**Link**:

```proto
[\[]<<>>[\]] [(]<<>>[)] => <a href="{{2}}">{{1}}</a>
```

**Paragraph** (blank-line separated):

```proto
<<\n\n>> => <p>{{.}}</p>
```
