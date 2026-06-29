# Himark Payload Wire Format

This is the contract between the Himark **compiler** and any **executor**. The compiler (`himark/parser`) turns `.hmk` source into a tree of plain primitives; an executor — the bundled Python VM, or an independent reimplementation (e.g. Rust) — consumes that tree and runs it. The payload carries **no Python objects**: every value is a string, integer, boolean, `null`, or array, so it round-trips through JSON / MessagePack / CBOR unchanged.

A consumer needs **only** this document plus the language semantics in [HMK.md](HMK.md). It does not import or know about this codebase. Prelude variables (`@d`, `@hex`, …) are already expanded at compile time and baked into the payload, so no external alphabet definitions are required at run time.

> **Status.** The in-memory shapes below are emitted today by `himark/parser/_compiler.py`. The canonical JSON *envelope* (`version` / `statements` / per-step `kind`) and the `to_json` / `from_json` pair are the target described in [TODO.md](TODO.md) ("Portable payload"); `Template.to_json` already exists and should be aligned to the envelope here. JSON has no tuple type, so every tuple below is encoded as an **array**; an executor must read arrays **positionally**.

---

## 1. Document envelope

A compiled `.hmk` file is a **pipeline**: an ordered list of **statements**, each an ordered list of **steps**.

```json
{
  "version": 1,
  "statements": [
    [ <step>, <step>, ... ],
    ...
  ]
}
```

- `version` — payload schema version. Bump on any breaking change to an opcode, a sub-encoding, the filter set, or the envelope.
- `statements` — run in order; each is spliced over the document before the next begins.
- A statement's `fixed_point` flag (the `<=>` arrow) is carried on its **first step**. When set, the executor re-splices that statement until the document stops changing; otherwise it splices once. See [HMK.md](HMK.md) and `himark/engine/__init__.py` for the branch/splice model.

## 2. Step

Each step is either a **query** (a matcher `Program`) or a **template** (a renderer). The `kind` field discriminates them.

### 2.1 Query step

```json
{
  "kind": "query",
  "groups": <int>,            // total capture-group count (for allocation)
  "fixed_point": <bool>,      // only meaningful on a statement's first step
  "elements": [ <instruction>, ... ]
}
```

### 2.2 Template step

```json
{
  "kind": "template",
  "fixed_point": <bool>,
  "template": [ <part>, ... ]  // each part: a literal string, or {"m": <expr>}
}
```

A literal part is emitted verbatim. A `{"m": <expr>}` part is an interpolated moustache (`{{ … }}`); the executor evaluates `<expr>` (§7) and records where its value lands so it can flow downstream as its own branch.

## 3. Instruction

An instruction is an array `[opcode, <operand>, ...]`. The first element is the integer opcode (§4); the remaining elements are its operands in the fixed order given below. Most opcodes end with a **reps** operand (§5); `LIT` and `ANCHOR` are zero-width/uncounted and carry none.

## 4. Opcodes

| # | Name | Operands (after the opcode) |
|---|------|------------------------------|
| 0 | `LIT` | `text: str` — literal text matched verbatim. *(no reps)* |
| 1 | `ANCHOR` | `kind: int` — zero-width anchor; see §6. *(no reps)* |
| 2 | `CHAR` | `lo: int`, `hi: int`, `excl` (§8), `reps` (§5) — one code point in `[lo, hi]`. |
| 3 | `GROUP` | `groups` (§9), `het: bool`, `reps` — one position from an explicit symbol set. |
| 4 | `BACK_REF` | `group: int`, `reps` — re-match the text captured by group `group`. |
| 5 | `COUNT_REF` | `group: int`, `reps` — match the decimal spelling of group `group`'s repetition count. |
| 6 | `STAGE_REF` | `stage: int`, `path: [int]`, `reps` — match the text of pipeline `stage`'s capture at `path`. |
| 7 | `VALUE_RANGE` | `alph` (§10), `lo_val: int\|null`, `hi_val: int\|null`, `wmin: int`, `wmax: int\|null`, `excl` (§8), `reps` — static positional-value band. |
| 8 | `DYN_RANGE` | `alph` (§10), `lo_static: str\|null`, `hi_static: str\|null`, `lo_ref` (§11)`\|null`, `hi_ref` (§11)`\|null`, `excl` (§8), `reps` — value band with a reference endpoint resolved at match time. |
| 9 | *(reserved)* | unused — no opcode `9` is emitted. |
| 10 | `COMPLEMENT` | `inner_groups` (§9), `reps` — one position whose value is **not** in the inner alphabet. |
| 11 | `SEQ_GROUP` | `children: [<instruction>, ...]`, `reps` — a grouping brace: a sub-program that is one capture group whose inner instructions become sub-captures. |

`VALUE_RANGE` bounds: `lo_val` / `hi_val` are positional values in `alph` (`null` = open on that side); `wmin` / `wmax` are the inclusive width window in symbols (`wmax` `null` = unbounded). `DYN_RANGE`: for each side, use the static endpoint string when its `*_ref` is `null`, otherwise resolve the reference descriptor; recompute width/value bounds from the resolved endpoint.

## 5. Reps (repetition)

The repetition operand is one of:

| Encoding | Meaning |
|----------|---------|
| `[min, max]` | count in `[min, max]`; `max == -1` means unbounded. Exactly once is `[1, 1]`. |
| `["#", group]` | count reference `[#i]` — the count equals group `group`'s repetition count, resolved at match time. |
| `["=", [v1, v2, ...]]` | count set `[a,b,c]` — the count must be exactly one of these values. |

`null` is accepted as a synonym for `[1, 1]`, but the compiler always emits an explicit form.

## 6. Anchor kinds (`ANCHOR`)

| kind | Meaning |
|------|---------|
| 0 | line start |
| 1 | line end |
| 2 | document start |
| 3 | document end |

Anchors are zero-width and non-capturing.

## 7. Moustache expression (`Expr`)

A `{{ … }}` body compiles to a small expression tree. Each node is a JSON object:

| Node | Encoding | Meaning |
|------|----------|---------|
| literal | `{"lit": "<text>"}` | a string/integer literal, rendered as its own text. |
| current | `{"cur": true}` | `.` — the whole text flowing into this step (`{{.}}`). |
| reference | `{"ref": [stage, is_count, path]}` | a capture accessor. `stage`: pipeline stage index, or `null` for the current stage. `is_count`: `true` for the `#` sigil (a repetition count) vs `false` for `$` (text). `path`: dotted capture path as `[int]`, or `null` for the stage's whole text. A `#` always carries a `path`. |
| concat | `{"cat": [<expr>, ...]}` | parenthesised comma-concatenation `( a, b, … )` — parts joined. |
| filter | `{"filter": "<name>", "src": <expr>}` | a filter pipe `src \| name`. |

Filter names are a closed set: **`trim`**, **`indent`**. An executor must implement exactly these; an unknown filter is a payload it cannot run (treat as a version mismatch).

## 8. Exclusions (`excl`)

Exclusions are pre-normalised at compile time into a triple of buckets so the executor only tests, never parses:

```json
[ [<single>, ...], [[<lo>, <hi>], ...], [<literal>, ...] ]
```

- **singles** — 1-character strings; a candidate char is excluded if it equals one.
- **ranges** — `[lo, hi]` pairs of single chars; excluded if `lo <= ch <= hi` (ordinal compare).
- **literals** — multi-character strings; excluded if the text at the current position *starts with* one.

An empty bucket is `[]`. All three buckets empty means "no exclusions".

## 9. Group list (`groups` / `inner_groups`)

An ordered list of **symbol groups**: `[[str, ...], ...]`. Each inner array is one group of congruent surface forms that share a position/value (e.g. `{f,F}` → `["f", "F"]`); a plain member is a singleton group (`["a"]`). For a `GROUP`, `het` (heterogeneous) is `true` when the groups come from a congruence class whose members may differ across repetitions, and `false` when each repetition re-matches the same surface form. Members may be multi-character.

## 10. Alphabet descriptor (`alph`)

The positional alphabet a value band reads in:

| Encoding | Meaning |
|----------|---------|
| `["range", lo, hi]` | a virtual positional alphabet over the contiguous code-point range `[lo, hi]` (used for spans too large to materialise, e.g. `@uni`). The zero symbol is `lo`; base is `hi - lo + 1`. |
| `["groups", [[str], ...]]` | a materialised ordered symbol-group table (see §9). Value is positional in base = number of groups, most-significant first; congruent spellings share a value. |

## 11. Reference descriptor (`DYN_RANGE` endpoints)

A dynamic band endpoint resolves against earlier match state:

| Encoding | Meaning |
|----------|---------|
| `["back", group]` | the text captured by group `group`. |
| `["count", group]` | the decimal spelling of group `group`'s repetition count. |
| `["stage", stage, path]` | the text of pipeline `stage`'s capture at `path` (`path` is `[int]`). |

---

## 12. Worked example

Source: `@<{a,b} => "[{{.}}]"` — at a line start, match one `a` or `b`, then wrap it in brackets.

```json
{
  "version": 1,
  "statements": [
    [
      {
        "kind": "query",
        "groups": 1,
        "fixed_point": false,
        "elements": [
          [1, 0],
          [3, [["a"], ["b"]], false, [1, 1]]
        ]
      },
      {
        "kind": "template",
        "fixed_point": false,
        "template": ["[", {"m": {"cur": true}}, "]"]
      }
    ]
  ]
}
```

- `[1, 0]` — `ANCHOR` line-start.
- `[3, [["a"], ["b"]], false, [1, 1]]` — `GROUP` over `{a, b}`, homogeneous, exactly once.
- Template parts: literal `"["`, moustache `{{.}}` (current text), literal `"]"`.

---

## 13. Notes for implementers

- **Positional arrays.** Operands are read by position, not by key. Adding an operand to an opcode is a breaking change — bump `version`.
- **Tuples become arrays.** Any value the source calls a tuple (`path`, descriptors, reps) is a JSON array. Equality/round-trip must treat `(a, b)` and `[a, b]` as the same.
- **Unicode.** Symbol strings carry raw characters; serialise with `ensure_ascii=False` (or the binary format's native string type). Code points in `CHAR` / `["range", …]` are integer ordinals.
- **No prelude dependency.** Named alphabets are already lowered to `groups` / `range` descriptors; the executor needs nothing from `std.hmk`.
- **Conformance.** The reference oracle is the bundled Python VM (`himark/engine`). A new executor should match its output over the `tests/golden`, `tests/north_star`, and `tests/demos` corpora.
