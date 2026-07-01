# Himark Value Algebra -- Unified Universe Model

**Status:** Design proposal (not yet implemented) | **Depends on:** [HMK.md](HMK.md)

This note pins the value model for **arithmetic and bitwise operators inside templates** (`{{ ... }}`). It is a forward-looking design settled in discussion, not a description of shipped behavior. The motivating goal is to build a **crypto layer (SHA-256, base58check) entirely in L2** (`himark/std.hmk`), so the engine knows nothing about specific transforms -- it exposes a small set of primitive operators, and everything else is declared in Himark source. This document defines those primitives; the far-future SHA-256 work and any `@filter` declaration form are out of scope here (see [Open questions](#open-questions)).

## The one object: a universe

Everything -- a captured group, a named alphabet, a literal -- is the **same object**: a **universe**, the triple `<alphabet, band, value>` already named in [HMK.md](HMK.md#values-and-ordering).

- **alphabet** -- the codec: an ordered list of building-block strings/characters, with a successor and equality. Fixes how a value renders back to text (base + per-position spelling).
- **band** -- the range in force, `[lo, hi]`, which fixes **width** and a **cardinality** $n = hi - lo + 1$.
- **value** -- the ordinal, an integer.

A named alphabet declaration `@alpha = {...}` is just a universe whose band is the alphabet's full range (`@alpha[0]..@alpha[-1]`) and whose **value is $0$** (it is used as a codec, so the value is irrelevant until it participates in an operation). Because alphabets and captures are one type, the operator algebra is uniform: there is no separate "alphabet vs value" case to handle.

## Value is absolute (band-independent)

A universe's value is its **absolute positional ordinal** (base-$b$, most-significant-first), independent of any band. Over `@d`, `"50"` is $50$ whether or not a band is in force. This is load-bearing and must not change:

- It is the **common scale** that makes references-as-endpoints work. `{@d::0..$0}` compares `$0`'s value against candidate values; that only means anything if both sit on one band-independent scale.
- It makes **cross-alphabet arithmetic trivial**: two values are already integers on the same axis, so `$0 - $1` is plain integer subtraction with no "convert to a common representation" step.

> Rejected alternative: **offset encoding** (store `value - lo`, so `50` in `{@d::50..150}` becomes $0$). It looks like it simplifies overflow, but it destroys the band-independent scale above -- a captured `$0` would no longer have a stable value across bands, breaking `{@d::0..$0}` -- and it does not even help bitwise ops (a $0..100$ field still is not a power of 2). Do not offset-encode.

## Operators are total

Every binary operator is defined over **any** two universes. The engine computes on the integer values with a fixed alphabet rule and **never traps**. Whether a given combination is *meaningful* is a separate, static concern pushed to an L2/lint layer that never touches the engine -- the same stance the spec already takes for alphabets ("the engine holds no built-in alphabet knowledge"). So `@uni * @hex` evaluates ($0 \cdot 0 = 0$, rendered under `@uni`): total, deterministic, harmless, and flagged as non-meaningful upstream if anyone cares.

Evaluation of a binary node `a OP b`:

1. **Value:** integer `value(a) OP value(b)` (in $\mathbb{Z}$; may be negative or exceed any band).
2. **Alphabet:** the result takes the **left operand's alphabet** (LHS wins). Threaded through the precedence tree, so `$0 + $1 * $2` is deterministic (each node inherits its own LHS operand's alphabet).
3. **Band:** the result takes the left operand's band.
4. **Render:** normalize the raw integer onto that band (below), then encode through the alphabet + width.

Because operators are total, **render must be total too**: it must map *any* integer in $\mathbb{Z}$ onto `[lo, hi]`.

## The operator set

The primitives exposed inside `{{ ... }}`, over universe values:

- `|` -- filter pipe (applies to everything on its left).
- `,` -- concatenate (parens only; result is always a `@uni` string).
- `+` `-` `*` `/` `%` -- arithmetic.
- `&` `` ` `` `^` `~` `<<` `>>` -- bitwise and, or, xor, not, left shift, right shift.

Two spellings are forced by existing syntax:

- **Or is the backtick `` ` ``, not `|`.** `|` is the filter pipe, so infix or cannot reuse it.
- **`%` is modulo** -- the same reduction [Normalize](#normalize-one-modular-map) performs, exposed as an operator. It is free because the filter-declaration sigil moved to a keyword.

Every arithmetic result is "unsigned" only in the sense of this algebra: the raw integer is [normalized](#normalize-one-modular-map) onto the LHS band's $\mathbb{Z}/n\mathbb{Z}$ ring, so a subtraction that would go negative wraps by $\bmod\ n$ rather than producing a signed value. This requires a band to supply $n$; bitwise additionally wants that band to be a power of two (below).

### Division and modulo are total

Operators never trap, so the zero cases must be defined, not errors:

$$x / 0 = 0 \qquad x \bmod 0 = 0$$

The choice of $0$ is arbitrary but fixed -- what matters is that `/` and `%` remain total maps like every other operator, so a pipeline never faults on data.

## Normalize: one modular map

Collapsing a raw integer `v` onto band `[lo, hi]` with cardinality $n = hi - lo + 1$ is a single operation:

$$\text{result} = lo + \big((v - lo) \bmod n\big)$$

using **floored mod** (result always in $[0, n)$, so negatives wrap correctly). There is no "if below min" special case -- floored mod handles it.

Worked example, band `{@d::7..11}`, $n = 5$:

| raw `v` | $(v - lo) \bmod n$ | result |
| ------- | ------------------ | ------ |
| `4`     | $(-3) \bmod 5 = 2$ | `9`    |
| `15`    | $8 \bmod 5 = 3$    | `10`   |
| `12`    | $5 \bmod 5 = 0$    | `7`    |

The band is a 5-cycle based at 7, so `15` lands on `10` (not `9`; the earlier hand-derivation slipped by reducing mod the max first -- do not; reduce mod the cardinality, offset from `lo`).

This makes **additive** ops (`+`, `-`, `*`) meaningful over **any** band -- each band is a clean $\mathbb{Z}/n\mathbb{Z}$ ring.

## Bitwise ops: total everywhere, meaningful only over $2^k$

Bitwise ops (`&`, `` ` ``, `^`, `~`, `<<`, `>>`) run on the raw integer and then go through the **same** normalize step, so they are total on every band. But they are only **meaningful** when $n$ is a power of two. Over `{@d::0..200}`, `x << 1` normalizes to `(2x) mod 201` -- multiply-mod-$n$ in a bitwise costume; the "bits" never existed because the band is not a bit-field.

Consequently:

- Bitwise over a $2^k$ band (`@b256`, a declared 32-bit word alphabet) has real semantics: wrap is mod $2^{\text{width}}$, exactly like a C `uintN_t`. This is what the crypto layer uses.
- Bitwise over a non-$2^k$ band is **not a compile error** -- it runs and produces a defined answer. It is a **lint warning** in L2 ("bitwise op over non-$2^k$ band"), not an engine concern.

This is the one place the `(min..max)` band does not carry everything for free: bit-width wants a power-of-two cardinality. Everywhere else the algebra is uniform.

## Casts: LHS-wins is the cast

Because a binary op **must** choose a result alphabet anyway, "LHS wins" **is** the casting mechanism -- no separate semantic is needed. With alphabets carrying value $0$, `@hex + $0` evaluates to `value($0)` rendered under `@hex`: an identity op that forces the alphabet, i.e. a cast to hex.

For readability, `{{ $0 | @hex }}` is **sugar** for the same LHS-wins render ("recode `$0` under hex"). It reuses the existing filter pipe and avoids making the reader recall that `+` is identity and alphabets are value-$0$. Same single semantic, one clearer spelling.

## Summary

- Universe = `<alphabet, band, value>`; captures, alphabets, and literals are one type.
- Value stays **absolute** (band-independent). Never offset-encode.
- Operators are **total**: integer op on values, **LHS alphabet wins**, result band from LHS, then normalize + render. Or is the backtick (`|` is the filter pipe); `x/0 = x \bmod 0 = 0`.
- Normalize is $lo + ((v - lo) \bmod n)$ with floored mod. Additive ops (`+`, `-`, `*`, `%`) are meaningful over any band.
- Bitwise ops are total everywhere but meaningful only over $2^k$ bands; lint-flag the rest.
- Casts fall out of LHS-wins; `| @alpha` is readable sugar.
- **Meaningfulness is an L2/lint concern; the engine never traps.**

## Open questions

- A **precedence/associativity table** for [the operator set](#the-operator-set) (must interleave cleanly with the existing `|` filter pipe and the parens-only `,` concat).
- A **custom-filter declaration** form for `himark/std.hmk` (`@filter name = <expr over a distinguished input>`), distinct from the `@name = <source>` alphabet binding.
- **SHA-256 in L2** (far future). It needs iteration + multi-register state, which a unary expression cannot express; the likely path is a multi-pass `<=>` pipeline with state materialized as text, or an unrolled form with local bindings. A text-splice hash is a **completeness demo**, not a throughput path -- a native fast lane behind the same L2 signature stays an option.
