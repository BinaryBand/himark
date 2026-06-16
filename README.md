# marky

A pattern-matching and text-transformation language for people who find regex write-only.

```hmk
{a..z}[1..]
{{@d}..255}{.}{{@d}..255}{.}{{@d}..255}{.}{{@d}..255}
{a..z} =>+ <p>
```

Patterns are readable, composable, and compile to **direct execution** — no regex transpilation. The full language spec is [docs/HMK.md](docs/HMK.md); the implementation map is [docs/.ARCHITECTURE.md](docs/.ARCHITECTURE.md).

> **Experimental algebra branch.** The `<->`, `{{…}}` (templates), and `>>` (run-until) constructs are removed here. Congruence comes from the brace grouping itself: `..` is the ordered axis, `,` the congruence axis.

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
poetry run marky execute '{a..z}[1..]' 'hi there'
# hi
# there

poetry run marky find '{{@d}..255}' '192.168.1.1'
# 0 3
# ...

# pattern and target may each be a file path or '-' for stdin
poetry run marky execute pattern.hmk target.txt
echo '{a..z}[1..]' | poetry run marky execute - 'hi there'

# --json emits structured deltas / spans instead of lines
poetry run marky execute '{a..z} =>+ <p>' 'a1b2c' --json
```

You can also run it as a module: `python -m marky execute '<pattern>' '<target>'`.

---

## The language in one screen

Two constructs: `{...}` matches, `[...]` repeats. They compose as `{expr}[count]`.

### Classes and arithmetic

| Pattern         | Matches                                 |
| --------------- | --------------------------------------- |
| `{abc}`         | the literal string `abc`                |
| `{a,A}`         | one congruence class: `a` or `A`        |
| `{a..z}`        | a run of lowercase letters              |
| `{{@d}..255}`   | a decimal value from 0 to 255           |
| `{cat,dog}`     | one class: the token `cat` or `dog`     |
| `{cat..dog}`    | any string between `cat` and `dog`      |
| `{{a,A},{b,B}}` | ordered alphabet of case-folded letters |
| `{!\|,\n}`      | a run containing no pipe or newline     |

Operators (tightest to loosest): `..` ordered range · `,` congruence class · `!` subtract. `..` and `,` are orthogonal axes — `{a,A}[2]` folds case (`aa`/`aA`/`Aa`/`AA`), while `{a..z}[2]` is the diagonal (`aa`/`bb`/…).

### Macros

`@d` `@l` `@u` digits/lower/upper, `@s` whitespace, `@w` word, `@hex` `@b32` `@b58` `@b64` encodings, `@ascii` `@uni` codepoint ranges. A macro expands to HMK source before matching — see the [Macros table](docs/HMK.md#macros).

### Repetition

`[N]` exactly N · `[N..]` N or more · `[..N]` up to N · `[N..M]` · `[..]` any. A **class** repeats by _value_ (`{a..z}[3]` is `aaa`, `ababab`, …); a **grouping brace** repeats by _shape_, so one pattern can walk a whole table.

### Chaining and transformers

`=>` _extracts_ — the statement returns the list of matches. `=>+` _splices_ — each match's span is replaced in place, returning the whole text. A trailing template step is constant text (this branch has no reference sub-language), and a run of patterns narrows successively.

```hmk
{a..z}                     # ["a", "b", "c", ...]
{a..z} => <p>              # ["<p>", "<p>", ...]   (constant per match)
{a..z} =>+ <p>             # "<p>1<p>2<p>"          (spliced in place)
```

Static text can be quoted to carry literal braces or spaces: `{a} => "<b>"`.

---

## Develop

```sh
poetry run pytest                          # run the suite
poetry run ruff format . && poetry run ruff check . && poetry run ty check
```

The doc-sync tests ([tests/test_doc_sync.py](tests/test_doc_sync.py),
[tests/north_star/](tests/north_star/)) run spec examples verbatim and are the safety net for engine changes. Working in this repo with Claude? Start from [CLAUDE.md](CLAUDE.md).
