# Himark

A pattern-matching and text-transformation language for people who find regex write-only.

```hmk
{!\ }[1..]                                             // a word: a run of non-spaces
{0:@d:255}{.}{0:@d:255}{.}{0:@d:255}{.}{0:@d:255}      // an IPv4 address
{!\ }[1..] => "<p>{{.}}</p>"                           // wrap each word in <p>
```

Patterns are readable, composable, and compile to **direct execution** -- no regex transpilation. The full language spec is [docs/HMK.md](docs/HMK.md).

Requires Python 3.11+.

---

## Install

```sh
poetry install
```

After install, `himark` is available as a shell command. During development you can also run `python -m himark`.

---

## Usage

### Run a script over a file

```sh
himark run script.hmk input.txt            # stdout
himark run script.hmk input.txt -o out.txt # to a file
himark run script.hmk input.txt --in-place # overwrite source
cat input.txt | himark run script.hmk      # stdin
```

### Inline expression

```sh
himark exec '{!\ }[1..] => "<b>{{.}}</b>"' "hello world"
# <b>hello</b> <b>world</b>

himark exec '{a..z}' "hello" --matches     # one match per line
# h
# e
# l
# l
# o
```

### Validate scripts

```sh
himark check script.hmk                    # ok  / err per file, exit 1 on any failure
himark check himark/scripts/*.hmk
```

### Format a .hmk file

```sh
himark fmt script.hmk                      # format in place
himark fmt script.hmk -o formatted.hmk    # write to new file
himark fmt script.hmk --check             # CI-safe: exit 1 if formatting needed
```

### Inspect the compiled pipeline

```sh
himark compile script.hmk                  # JSON pipeline to stdout
himark compile script.hmk -o pipeline.json
```

---

## The language in one screen

Two constructs: `{...}` matches, `[...]` repeats. They compose as `{expr}[count]`.

### Classes and arithmetic

| Pattern        | Matches                                      |
| -------------- | -------------------------------------------- |
| `{abc}`        | the literal string `abc`                     |
| `{a,A}`        | one congruence class: `a` or `A`             |
| `{a..z}`       | **one** lowercase letter (a single position) |
| `{!\ }[1..]`   | a run of non-spaces (a word)                 |
| `{0:@d:255}`   | a decimal value from 0 to 255                |
| `{cat,dog}`    | one class: the token `cat` or `dog`          |
| `{cat..dog}`   | any string between `cat` and `dog`           |
| `{0:@hex:fff}` | a hex value, 1 to 3 digits wide              |

**Every `{...}` matches one position** -- one symbol or one value. A _run_ comes only from `[count]`: `{!\ }[1..]` (a run of non-spaces) or `{a,b,c}[1..]` (a run drawn from a class). Repetition is heterogeneous for a complement or congruence class (`{a,A}[2]` -> `aa`/`aA`/`Aa`/`AA`) but homogeneous for an ordered range (`{a..z}[3]` -> `aaa`/`bbb`). A multi-symbol **value** is a `:`-bound -- `{x:U:y}`, where the floor/ceiling widths set the field width (`{0:@d:255}`, `{0:@hex:fff}`). Operators: `..` ordered range, `,` congruence class, `!` subtract, `:` value bound.

### Variables

`@d` `@l` `@u` digits/lower/upper, `@s` whitespace, `@w` word, `@hex` `@b32` `@b58` `@b64` encodings, `@ascii` `@uni` codepoint ranges. A variable resolves to HMK source before matching -- see the [Variables table](docs/HMK.md#variables).

### Repetition

`[N]` exactly N, `[N..]` N or more, `[..N]` up to N, `[N..M]` between N and M, `[..]` any. A **class** repeats by _value_ (`{a..z}[3]` is `aaa`, `bbb`, ... -- three of the _same_ letter, since `{a..z}` is one position); a **grouping brace** repeats by _shape_, so one pattern can walk a whole table.

### Chaining and templates

`=>` chains steps. The first step is a query; each of its matches starts a **branch** the rest of the chain transforms. A later query splices its matches (matching nothing **drops** the branch -- that is how a chain filters); a **template** renders and the chain continues on its render, so templates compose. `{{.}}` is the text flowing into the step; `{{ i$j }}` reaches an earlier stage's capture `j`.

```hmk
{!\ }[1..]                       // ["hi", "there"]   (the list of matches)
{!\ }[1..] => "<p>{{.}}</p>"     // ["<p>hi</p>", "<p>there</p>"]
```

The same branches render two ways: a **list** of results (`exec --matches`), or **spliced** back over the source in place (the default). Static text is quoted to carry literal braces or spaces and to hold moustache references: `{a} => "<b>{{.}}</b>"`.

---

## Develop

```sh
poetry run pytest                    # auto-formats with ruff before the run; then full suite
poetry run pytest tests/test_lint.py # lint / type / dead-code / import-arch gates only
```

The doc-sync tests ([tests/test_doc_sync.py](tests/test_doc_sync.py), [tests/north_star/](tests/north_star/)) run spec examples verbatim and are the safety net for engine changes. Working in this repo with Claude? Start from [CLAUDE.md](CLAUDE.md).
