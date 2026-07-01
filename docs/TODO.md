# TODO

## Performace

### Optimization

- [x] Ensure Rust runs with `cargo run --release` so we don't disable optimizations -- runner invokes the prebuilt `target/release` binary; conftest builds `--release`
- [x] Cache the VM-ready instructions produced by `prepare(program)`, keyed by `Program` identity -- in Rust `prepare_elements` runs once per statement and is reused across every splice position and fixed-point round (the subprocess handles one pipeline per invocation, so there is no cross-call reuse left to cache)
- [x] Bake matcher objects into prepared instructions -- `Char`/`Complement`/`ValueRange` now carry their baked matcher, dropping the per-call `excl`/`inner_groups`/`alph` clone from the hot loop (~3.75x on the base58 value-band workload)
- [x] A/B test various engines, optimizations, and languages -- `tests/benchmarks/bench.py`
- [ ] Remember where each pass's last real change ended and let the next pass only *begin* matches before that point -- holds for fixed-point passes; semantically delicate (would diverge the Rust engine's strategy from the Python oracle), needs its own validated change

## Language evolution (per docs/.PROPOSAL.md, docs/ALGEBRA.md)

The through-line: shrink the engine to a minimal primitive core (the universe object, literals, operators, splice, the doc-boundary anchor) and push every convenience -- filters, line anchors, named sentinels -- into `himark/std.hmk`. Sequenced so each step unblocks the next.

- [x] **Step 0 -- `$` is the pipe subject.** Bare `$` now compiles to `ExCurrent` (the flowing subject); `.` kept as a deprecated alias (no grammar regen). Migrated `scripts/md_html.hmk` and the docs/help text; `$`-vs-`$0` gotcha documented in HMK.md.
- [x] **Step 1 -- value-aware evaluator (keystone).** `Universe` render value added in `engine/_render.py`; `_eval` returns a `Universe` and `render()` collapses it at the boundary. Captures carry their alphabet forward; identity `render`, so output is byte-identical (373 tests green). Band + operators are Step 2.
- [x] **Step 2 -- operators, one vertical slice then the set.** `ExBinOp`/`ExUnOp` + a moustache precedence cascade (filter `|` loosest down to unary `~`) with the full set live: arithmetic `+ - * / %`, bitwise `& ^ ~ << >>` and backtick-or, total (`x/0 = x%0 = 0`). Bands now thread from `VALUE_RANGE`/`DYN_RANGE` onto `Capture.band` and into `Universe`, so a `{A::lo..hi}` capture wraps mod `n` per ALGEBRA; the codec moved to `Alphabet.encode`/`RangeAlphabet.encode` (keeping the engine free of any parser import). `<<`/`>>` stay `LT LT`/`GT GT` so the `@<<` anchor is untouched. Tests in `tests/test_operators.py`.
- [x] **Step 3 -- declared filters in L2.** Filters are now declared, not native: `@name = <body>` binds an alphabet (a bare pattern) or a **filter** (an arrow/template body), told apart by body shape and invoked at a `| name` pipe. A single-moustache body is **value-shaped** (`$` binds to the subject universe, so band survives -- the crypto path); any richer body is **document-shaped** (run over the subject text via `run_pipeline`). The compiler resolves `| name` against a prelude+local registry and bakes the compiled body onto `ExFilter` (unknown name -> `CompileError`); the engine's native `_FILTERS` is gone. `trim`/`indent` moved to `std.hmk` (`trim` composes `lstrip`/`rstrip`; `indent` is two width-ful passes since a zero-width anchor never matches alone). Tests in `tests/test_filters.py`.
- [x] **Step 4 -- declarative anchors.** Two parts landed. (1) **Declarative line/doc anchors.** The engine keeps a single zero-width `LOOKAROUND` primitive (`direction`, `negate`, char class); all four anchors are declared in `std.hmk` over it -- `@doc_start = !<{@uni}` (negative lookbehind of any char = pos 0), `@line_start = !<!{\n}` (negative lookbehind of a non-newline), and the ahead forms -- named directly in a query (`{@line_start}`). So the doc-boundary anchor was *not* irreducible: negative polarity derives it too. (The old `@<`/`@>`/`@<<`/`@>>` glyph sugar has since been dropped -- there is one way to name an anchor.) Byte-identical (only the anchor opcode encoding changed). (2) **Out-of-band named anchors.** A `@name = anchor` declaration + a parallel `AnchorMap` (`himark/engine/_anchors.py`) carried beside the text through every splice, offset-remapped per delta (a mark inside a replaced span is dropped): `{@name}`/`!{@name}` match, `{{@name}}` emit, `{{/name}}` clear, all zero-width and non-rendering (`NAMED_ANCHOR` opcode; payload v2). Tests in `tests/test_anchors.py`. **Not done:** rewriting `dedup.hmk` onto named anchors -- its merge captures the text between a pair and re-emits it verbatim, and an out-of-band mark (unlike an in-text `¤`) does not ride along in captured text, so `¤`/`⸴` stay in-text delimiters by necessity (documented in the script; the never-emitted `§` wildcard *was* retired, `!{§}[..]` -> `{{@uni}}[..]`).

## Engines (archived while the grammar settles)

The five `sandbox/` ports (rust, go, cpp, java, and the standalone `engine.py`) are **archived**: `himark.engine.run_pipeline` now runs the **in-process** Python engine (`himark/engine/`, the oracle) so there is one implementation to evolve through Steps 2-4. Files stay on disk; the conftest no longer builds any. Re-port later, then re-enable per-engine validation.

- [ ] Re-port the value-aware evaluator + operators to the fast backends once the grammar re-stabilizes, and restore the cross-engine golden/bench checks. Select a port with `HMK_ENGINE=rust|go|cpp|java|python` (build it by hand first); `tests/benchmarks/bench.py` needs those builds to be meaningful again.

## Himark Scripts

- [ ] Add fuzzy distance filter for dedup script.
- [ ] Create a delta demo.

## Maybe

- [x] Add Go and C/C++ single-file engine implementations -- Go (`sandbox/engine.go`) and C++ (`sandbox/engine.cpp`) both ship; all five engines are byte-identical on the golden corpus. (Now archived -- see above.)
- [ ] Consider updating arithmetic universes joined by an operator adopt the RHS alphabet. That way `| @alpha` goes from being readable sugar to a first class mechanic.
