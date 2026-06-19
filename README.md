# Himark

A pattern-matching and text-transformation language for people who find regex write-only.

```hmk
{!\ }[1..]                                             # a word: a run of non-spaces
{0:@d:255}{.}{0:@d:255}{.}{0:@d:255}{.}{0:@d:255}      # an IPv4 address
{!\ }[1..] => "<p>{{.}}</p>"                           # wrap each word in <p>
```

Patterns are readable, composable, and compile to **direct execution** — no regex transpilation. The full language spec is [docs/HMK.md](docs/HMK.md); the implementation map is [docs/.ARCHITECTURE.md](docs/.ARCHITECTURE.md).

> **Experimental algebra branch.** The `<->` and `>>` (run-until) operators and the old `{{…}}` reference sublanguage are removed here; congruence comes from the brace grouping itself (`..` ordered, `,` congruence). References return as **moustache** template accessors (`{{.}}`, `{{ i$j }}`) and pattern self-references (`{$i}`/`{#i}`/`{N$M}`).

Requires Python 3.11+.

---

## Install

```sh
poetry install --no-root
```

---

## Usage

Commands: `execute` (match and transform), `find` (locate matches), `transpile` (run a `.hmk` script over a document), and `pipeline` (pre-compile scripts).

```sh
poetry run himark execute '{!\ }[1..]' 'hi there'
# hi
# there

poetry run himark find '{0:@d:255}' '192.168.1.1'
# 0 3
# ...

# pattern and target may each be a file path or '-' for stdin
poetry run himark execute pattern.hmk target.txt
echo '{!\ }[1..]' | poetry run himark execute - 'hi there'

# --json emits structured deltas / spans instead of lines
poetry run himark execute '{!\ }[1..] => "<p>{{.}}</p>"' 'a hi b' --json

# run a multi-statement .hmk script over a document (HTML to stdout, or --out file)
poetry run himark transpile doc.md --script himark/scripts/md_html.hmk
```

You can also run it as a module: `python -m himark execute '<pattern>' '<target>'`.

---

## The language in one screen

Two constructs: `{...}` matches, `[...]` repeats. They compose as `{expr}[count]`.

### Classes and arithmetic

| Pattern         | Matches                                       |
| --------------- | --------------------------------------------- |
| `{abc}`         | the literal string `abc`                      |
| `{a,A}`         | one congruence class: `a` or `A`              |
| `{a..z}`        | **one** lowercase letter (a single position)  |
| `{a,A}`         | one congruence class: `a` or `A`              |
| `{!\ }[1..]`    | a run of non-spaces (a word)                  |
| `{0:@d:255}`    | a decimal value from 0 to 255                 |
| `{cat,dog}`     | one class: the token `cat` or `dog`           |
| `{cat..dog}`    | any string between `cat` and `dog`            |
| `{0:@hex:fff}`  | a hex value, 1 to 3 digits wide               |

**Every `{…}` matches one position** — one symbol or one value. A *run* comes only from `[count]`: `{!\ }[1..]` (a run of non-spaces) or `{a,b,c}[1..]` (a run drawn from a class). Repetition is heterogeneous for a complement or congruence class (`{a,A}[2]` → `aa`/`aA`/`Aa`/`AA`) but homogeneous for an ordered range (`{a..z}[3]` → `aaa`/`bbb`). A multi-symbol **value** is a `:`-bound — `{x:U:y}`, where the floor/ceiling widths set the field width (`{0:@d:255}`, `{0:@hex:fff}`). Operators: `..` ordered range · `,` congruence class · `!` subtract · `:` value bound.

### Macros

`@d` `@l` `@u` digits/lower/upper, `@s` whitespace, `@w` word, `@hex` `@b32` `@b58` `@b64` encodings, `@ascii` `@uni` codepoint ranges. A macro expands to HMK source before matching — see the [Macros table](docs/HMK.md#macros).

### Repetition

`[N]` exactly N · `[N..]` N or more · `[..N]` up to N · `[N..M]` · `[..]` any. A **class** repeats by *value* (`{a..z}[3]` is `aaa`, `bbb`, … — three of the *same* letter, since `{a..z}` is one position); a **grouping brace** repeats by *shape*, so one pattern can walk a whole table.

### Chaining and transformers

`=>` chains steps. The first step is a query; each of its matches starts a **branch** the rest of the chain transforms. A later query splices its matches (matching nothing **drops** the branch — that is how a chain filters); a **template** renders and the chain continues on its render, so templates compose. `{{.}}` is the text flowing into the step; `{{ i$j }}` reaches an earlier stage's capture `j`.

```hmk
{!\ }[1..]                       # ["hi", "there"]   (the list of matches)
{!\ }[1..] => "<p>{{.}}</p>"     # ["<p>hi</p>", "<p>there</p>"]
```

The same branches render two ways: a **list** of results, or **spliced** back over the source in place (`--json` emits the spliceable `{start, end, text}` deltas). Static text is quoted to carry literal braces or spaces and to hold moustache references: `{a} => "<b>{{.}}</b>"`.

---

## Develop

```sh
poetry run pytest                          # run the suite
poetry run ruff format . && poetry run ruff check . && poetry run ty check
```

The doc-sync tests ([tests/test_doc_sync.py](tests/test_doc_sync.py),
[tests/north_star/](tests/north_star/)) run spec examples verbatim and are the safety net for engine changes. Working in this repo with Claude? Start from [CLAUDE.md](CLAUDE.md).
