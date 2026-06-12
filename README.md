# marky

A pattern-matching and text-transformation language for people who find regex write-only.

```hmk
[a..z](1..) => <em>{{ . }}</em>
[done] => {{ . }} {{ :tada: }}
[0..][px||em||rem] => {{ 1 }}
<<\n>> => [#][ ][a..Z](1..) => <h1>{{ 2 }}</h1>
```

Patterns are readable, composable, and compile to direct execution — no regex transpilation.

---

## Install

```sh
poetry install --no-root
```

Requires Python 3.11+.

---

## Usage

```sh
poetry run marky '<pattern>' '<target>'

# file inputs work too
poetry run marky pattern.hmk target.txt

# pipe pattern to avoid shell quoting issues with || on Windows
echo '[a||b](1..)' | poetry run marky - 'aabbab'
```

---

## Pattern syntax

| Syntax      | Meaning                                        |
| ----------- | ---------------------------------------------- |
| `[abc]`     | Literal sequence                               |
| `[a\|\|b]`  | Alternation — `a` or `b`                       |
| `[a..z]`    | Range by Unicode codepoint                     |
| `[..]`      | Any single character                           |
| `[a..]`     | One or more word characters                    |
| `[0..]`     | One or more digits                             |
| `[ ..]`     | One or more whitespace                         |
| `[a](3)`    | Exactly 3                                      |
| `[a](1..)`  | One or more                                    |
| `[a](1..3)` | Between 1 and 3                                |
| `[[a..z]]`  | Negation — runs containing no lowercase letter |
| `<<sep>>`   | Split on separator                             |
| `^` `$`     | Line start / end anchors                       |

### Alphabets

```hmk
[0..f](hex)   [0..v](b32)   [1..z](b58)   [hello](i)
```

### Templates

```hmk
{{ . }}        full match
{{ 1 }}        capture group 1
{{ 1.2 }}      sub-group 1.2
{{ 1.2..3.1 }} span across groups
```

### Chaining

```hmk
<<\n>> => [#][ ][a..Z](1..) => <h1>{{ 2 }}</h1>
```

Each `=>` pipes matched text into the next step. Template variables refer to the immediately preceding match.

---

## Full spec

[docs/MKY.md](docs/MKY.md)
