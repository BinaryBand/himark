# Himark

**Version:** 0.4.2
**Status:** Draft Specification
**License:** CC0 1.0 Universal (Public Domain)

---

Himark uses the `.hmk` file extension, designed for pattern matching and text processing.

## Escaping

The backslash `\` escapes metacharacter pairs that have no bracket alternative, and provides control character shorthands.

| Escape | Matches |
| ------ | ------- |
| `\\` | Literal backslash |
| `\[` `\]` | Literal `[` or `]` |
| `\{` `\}` | Literal `{` or `}` — required only when adjacent to another (e.g. `\}}` emits `}}` in template output) |
| `\t` `\n` `\r` | Tab, newline, carriage return |

Characters that form two-character operators (`..`, `||`, `<<`, `>>`, `{{`, `}}`) are already literal when used alone and do not need escaping. Anchor characters (`^`, `$`) are literal inside `[ ]`; use `[^]` or `[$]` to match them within a sequence.

## Basic Examples

```proto
[a]                  // r/a/
[abc]                // r/abc/
[a||c]               // r/a|c/
[hello||world]       // r/(hello)|(world)/
[hello][ ..][world]  // 'hello world', 'hello  world', …
[a..z][.][a..z]      // word.word
```

## Ranges

Ranges use **Unicode codepoint order**. UTF-8 and UTF-16 are encodings of the same codepoints and are not a distinct factor in range resolution. Inference order: if both endpoints are decimal digits → b10; otherwise → Unicode codepoint order.

**Mixed-type endpoints** — one endpoint a decimal digit, the other not — are a compile error. Use explicit alternation instead: `[0..9||a..f]`.

**Cross-case shorthand** fires when both conditions hold: (1) the left endpoint has a higher codepoint than the right, and (2) the left is a lowercase ASCII letter and the right is an uppercase ASCII letter. The range expands to the union of two ascending sub-ranges, each running from its endpoint to the edge of its case. `[a..Z]` = `[a..z||A..Z]`. `[b..A]` = `[b..z||A..Z]` — note this excludes `'a'`. When in doubt, spell out both sub-ranges explicitly.

The ascending range `[A..z]` is valid but includes the six punctuation characters between `'Z'` and `'a'` (codepoints 91–96: `` [\]^_` ``). This is rarely intended; prefer `[a..Z]`.

```proto
[a..z]       // r/[a-z]/
[A..Z]       // r/[A-Z]/
[a..Z]       // r/[a-zA-Z]/
[a..c||H]    // r/[a-c]|H/
[a..c||F..H] // r/[a-c]|[F-H]/
```

### Shortcuts

```proto
[..]   // any single character
[0..]  // one or more decimal digits
[a..]  // one or more word characters ([a-zA-Z0-9_])
[ ..]  // one or more whitespace characters
```

The shortcuts `[0..]`, `[a..]`, and `[ ..]` are fixed shorthands, not open-ended ranges. For exact digit counts, use a closed range: `[0..9](2)`.

Integer value ranges match canonical strings with no leading zeros (except `'0'` itself). `[5..99]` can match `"10"` inside `"100"` since Himark matches strings, not semantic integer tokens.

```proto
[5..99]  // integers 5 to 99 — no leading zeros
```

### Alternate alphabets

b10 and Unicode codepoint order are inferred automatically. The alphabets below require explicit modifiers. Alphabets where case carries no distinct value are case-agnostic; use `(i)` on any pattern for case-insensitive matching.

```proto
[0..9](b10)  // Decimal — explicit override (alias: dec)
[0..f](hex)  // Hexadecimal, case-agnostic (alias: b16)
[0..v](b32)  // Base32, case-agnostic (RFC 4648 §7)
[1..z](b58)  // Base58
[A../](b64)  // Base64
[hello](i)   // Matches 'hello', 'Hello', 'HELLO', etc.
```

### Multi-character ranges

Without a `pad` argument, ranges match canonical integer strings (no leading zeros). `pad:N` produces fixed-width strings: both endpoints are zero-padded to the same width, which is the smallest multiple of `N` that is ≥ the length of the wider endpoint. All matched strings have exactly that width.

```proto
[0..99]              // integers 0 to 99
[0..ff](hex)         // hex integers 0 to 255
[0..99](pad:2)       // 2-char decimal strings "00" to "99"
[0..ff](hex, pad:2)  // 2-char hex strings "00" to "ff"
[f..fff](hex, pad:4) // 4-char hex strings "000f" to "0fff"
                     // (pad:4 because "fff" is 3 chars → next multiple of 4 is 4)
```

## Negation

`[[pattern]]` matches maximal runs of characters that do not contain `pattern`. Semantics depend on the content type:

- **Single character or character range** → complement character class: runs consisting entirely of characters outside the set.
- **Sequence or alternation** → tempered match: runs that contain no occurrence of any given sequence or word.

```proto
[[a]]            // Runs with no 'a'                     → r/[^a]+/g
[[a..z]]         // Runs with no lowercase letter        → r/[^a-z]+/g
[[abc]]          // Runs not containing the sequence 'abc'
[[hello||world]] // Runs containing neither 'hello' nor 'world'
```

To negate a character alternation (class complement) rather than exclude sequences, use single-character alternatives: `[[a||b||c]]` = runs containing no `'a'`, `'b'`, or `'c'`.

Overlapping candidates merge into the longest non-overlapping run. Negation of negation (`[[[[a]]]]`) and negation with a repetition modifier (`[[a]](0..)`) are not supported.

## Repetition

Repetition is a count modifier on any `[...]` group. A bare group without a count modifier matches exactly once.

| Form | Meaning |
| ---- | ------- |
| `[a]` | Exactly once |
| `[a](2)` | Exactly 2 |
| `[a](1..)` | One or more |
| `[a](0..)` | Zero or more |
| `[a](1..3)` | Between 1 and 3 |
| `[a](..3)` | Zero to 3 |
| `[a\|\|b](2)` | Exactly 2 of `a` or `b` |
| `[a](0.., ?)` | Zero or more, lazy |

The lazy flag `?` is a second argument to the count modifier and may be combined with any count: `[a](1.., ?)` = one or more, lazy.

Multiple option groups are accepted as equivalent to comma separation: `[0..f](hex)(1..)` is the same as `[0..f](hex, 1..)`. The two-group form can be easier to read when combining an alphabet modifier with a repetition modifier.

### Varied repetition

Variable letters (single alphabetic characters) bind to the count at their first occurrence (left-to-right). All uses of the same variable must resolve to the same count. When a numeric literal appears adjacent to a variable in the min or max position of a count modifier, the literal is a **bound on the variable** — the variable still enforces exact equality across all its occurrences.

```proto
[a](n)[b](n)              // 'ab' or 'aabb', not 'aab'
[a](2..n)[b](n..3)        // n ∈ {2,3}; a-count = b-count = n
                          // Matches 'aabb' (n=2) or 'aaabbb' (n=3)
[a](n)[b](n)[c](m)[d](m)  // n and m are independent variables
```

A conflicting variable bound (e.g. min > max after substitution) is a compile error.

## Captures

Groups are defined by `[...]` and `<<...>>` delimiters and numbered left-to-right from 1 at the top level. Nested groups use dot notation. All groups capture; to ignore a captured group, omit its reference in the transformer template.

```proto
[0..](1..)[px||em||rem]
// Group 1: [0..]
// Group 2: [px||em||rem]
```

Alternation branches within a single `[...]` group do not create sub-groups — the whole bracket is one group regardless of how many `||` alternatives it contains.

| Reference | Resolves to |
| --------- | ----------- |
| `{{ 1 }}`, `{{ 2 }}` | Top-level group content by position |
| `{{ 1.1 }}`, `{{ 2.3 }}` | Sub-group content by position |
| `{{ 1.2..3.1 }}` | Concatenated content from the start of group 1.2 through the end of group 3.1 (inclusive, left-to-right) |

## Separators

| Expression | Target | Result |
| ---------- | ------ | ------ |
| `<</>>` | 'red/green/blue' | 'red', 'green', 'blue' |
| `<<foo>>` | 'redfoogreenfooblue' | 'red', 'green', 'blue' |

Consecutive, leading, or trailing separators produce empty strings: `'red//blue'` with `<</>>` → `'red'`, `''`, `'blue'`.

## Transformers

Inside a template, `{{ expr }}` interpolates a value; a lone `{` or `}` inside any `{{ }}` pair is literal unless part of a two-character operator (e.g. `}}`). To emit a literal `}}` in template output, write `\}}`. Whitespace around expression content is insignificant (`{{ . }}` and `{{.}}` are equivalent).

Template variables:

| Variable | Resolves to |
| -------- | ----------- |
| `{{ . }}` | Full matched text |
| `{{ n }}` | Varied-repetition count bound to variable `n` |
| `{{ 1 }}`, `{{ 1.2 }}` | Captured group by position |
| `{{ 1.2..3.1 }}` | Span from start of group 1.2 to end of group 3.1 |
| `{{ :emoji: }}` | Emoji shortcode → grapheme cluster |
| `{{ $expr$ }}` | LaTeX expression → Unicode |

```proto
[selector] => <template>{{ . }}</template>
^<<#>>$ => <h1>{{ . }}</h1>
<</>> => <p>{{ . }}</p>
[a..z](n) => <b>{{ . }}</b>×{{ n }}
[done] => {{ . }} {{ :tada: }}
[rad] => {{ $\pi$ }}/{{ . }}
[0..][px||em||rem] => {{ 1 }}
```

### Chained transformations

A pattern may contain multiple groups. The template then selects which group(s) to emit, expressing assertions that regex would encode as lookahead or lookbehind:

| Regex | HMK equivalent |
| ----- | -------------- |
| `X(?=Y)` — positive lookahead | `[X][Y] => {{ 1 }}` |
| `(?<=X)Y` — positive lookbehind | `[X][Y] => {{ 2 }}` |

A transformer may also chain multiple `=>` steps. Each intermediate step is itself a pattern; `=>` pipes the **full matched text** of the current step as the input domain for the next. The final `=>` leads to a template. Template variables (`{{ . }}`, `{{ 1 }}`, etc.) always refer to the immediately preceding pattern's match.

```proto
<<\n>> => [#][ ][a..Z](1..) => <h1>{{ 2 }}</h1>
// Split by newline, then match heading lines, then emit the title text in <h1>
```

Intermediate group selection — narrowing what passes to the next step via a `{{ }}` expression mid-chain — is not supported. If only a specific group is needed as input to a subsequent pattern, restructure the first pattern to match that group directly, or use two independent statements.

## Reference

### Anchors

```proto
^   // Start of a line (literal inside [])
$   // End of a line (literal inside [])
^^  // Start of the document
$$  // End of the document
```

General word-boundary assertions are not currently supported.

### Whitespace significance

Outside group delimiters (`[ ]`, `<<...>>`) and template blocks, whitespace between tokens is insignificant. Inside `[ ]`, spaces are literal — `[ ]` matches exactly one space character. Use `[ ..]` for any-whitespace sequences and `\t`, `\n` for specific control characters.

```proto
[a..z](1..3)         // same as [a..z] (1..3)
[hello world]        // matches the literal string 'hello world' (one space)
[hello][ ..][world]  // matches 'hello world', 'hello  world', 'hello\tworld', etc.
```

### File composition

A `.hmk` file is a sequence of statements evaluated top-to-bottom in a single pass over the input.

- **Pattern statements** collect all non-overlapping matches (left-to-right, greedy by default).
- **Transformer statements** apply the first matching rule at each position; at most one transformer fires per input position per pass.

Each statement acts on the **original input independently** — statements do not pipe into one another. A transformer `[X] => T` does not feed its output as the input to the next statement.

A transformer statement produces a **list of results**, one per match. For a single-step transformer, the pattern yields an ordered list of match objects; each match object carries the full matched text and any captured groups. The template is applied to each match object in turn, resolving `{{ . }}`, `{{ 1 }}`, and other variables from that match. The final output is the list of resolved strings in match order.

For a chained transformer (`P1 => P2 => ... => T`), each intermediate pattern is applied to the full matched text of the previous step. The list expands or contracts at each step — a match that yields no result in an intermediate step produces no output. See [Chained transformations](#chained-transformations).

### Comments

```proto
// Single-line comment

/*
  Multiline comment
*/
```
