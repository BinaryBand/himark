# marky

A pattern-matching and text-transformation language for people who find regex
write-only.

```hmk
{a..z}[1..] => <em>{{.}}</em>
{{@d}..255}{.}{{@d}..255}{.}{{@d}..255}{.}{{@d}..255}
{a..z} =>+ <p>{{.}}</p>
```

Patterns are readable, composable, and compile to **direct execution** — no
regex transpilation. The full language spec is [docs/HMK.md](docs/HMK.md); the
implementation map is [docs/.ARCHITECTURE.md](docs/.ARCHITECTURE.md).

Requires Python 3.11+.

---

## Install

```sh
poetry install --no-root
```

---

## Usage

Two commands: `execute` (match and transform) and `find` (locate matches).

```sh
poetry run marky execute '{a..z}[1..] => <em>{{.}}</em>' 'hi there'
# <em>hi</em>
# <em>there</em>

poetry run marky find '{{@d}..255}' '192.168.1.1'
# 0 3
# ...

# pattern and target may each be a file path or '-' for stdin
poetry run marky execute pattern.hmk target.txt
echo '{a..z}[1..]' | poetry run marky execute - 'hi there'

# --json emits structured deltas / spans instead of lines
poetry run marky execute '{a..z} =>+ <p>{{.}}</p>' 'a1b2c' --json
```

You can also run it as a module: `python -m marky execute '<pattern>' '<target>'`.

---

## The language in one screen

Three constructs: `{...}` matches, `{{...}}` templates, `[...]` repeats. They
compose as `{expr}[count]`.

### Classes and arithmetic

| Pattern       | Matches                             |
| ------------- | ----------------------------------- |
| `{abc}`       | the literal string `abc`            |
| `{a,b,c}`     | `a`, `b`, or `c`                    |
| `{a..z}`      | a run of lowercase letters          |
| `{{@d}..255}` | a decimal value from 0 to 255       |
| `{cat,dog}`   | the token `cat` or `dog`            |
| `{cat..dog}`  | any string between `cat` and `dog`  |
| `{!\|,\n}`    | a run containing no pipe or newline |

Operators (tightest to loosest): `..` range · `<->` congruence (case-fold) ·
`,` union · `!` subtract. Example: `{@d},{a..f}<->{A..F}` is case-folded hex.

### Macros

`@d` `@l` `@u` digits/lower/upper, `@s` whitespace, `@w` word, `@hex` `@b32`
`@b58` `@b64` encodings, `@ascii` `@uni` codepoint ranges. A macro expands to
HMK source before matching — see the [Macros table](docs/HMK.md#macros).

### Repetition

`[N]` exactly N · `[N..]` N or more · `[..N]` up to N · `[N..M]` · `[..]` any.
A **class** repeats by *value* (`{a..z}[3]` is `aaa`, `ababab`, …); a **grouping
brace** repeats by *shape*, so one pattern can walk a whole table.

### Templates

| Reference  | Resolves to                            |
| ---------- | -------------------------------------- |
| `{{.}}`    | the full matched text                  |
| `{{N}}`    | capture group N (0-based)              |
| `{{N.M}}`  | sub-group M of group N                 |
| `{{N..M}}` | groups N through M inclusive           |
| `{{#N}}`   | repeat count of group N                |
| `{{#N.M}}` | repeat count of sub-group M of group N |

Static template text can be quoted: `"<b>"{{1}}"</b>"`.

### Chaining and transformers

`=>` *extracts* — the statement returns the list of rendered matches. `=>+`
*splices* — each rendered match replaces its source span in place, returning the
whole text.

```hmk
{a..z} => <p>{{.}}</p>     # ["<p>a</p>", "<p>b</p>", ...]
{a..z} =>+ <p>{{.}}</p>    # "<p>a</p>1<p>b</p>2<p>c</p>"
```

A run of patterns (`P => P => ... => T`) narrows successively before the
trailing template renders. In a chained template the *references* are the
forward payload and the *literal* text is chrome that wraps the result.

---

## Develop

```sh
poetry run pytest                          # run the suite
poetry run ruff format . && poetry run ruff check . && poetry run ty check
```

The doc-sync tests ([tests/test_doc_sync.py](tests/test_doc_sync.py),
[tests/north_star/](tests/north_star/)) run spec examples verbatim and are the
safety net for engine changes. Working in this repo with Claude? Start from
[CLAUDE.md](CLAUDE.md).
