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
- [ ] **Step 3 -- declared filters in L2.** A filter-declaration form for `himark/std.hmk`; move `trim`/`indent` (and the value filters) out of the engine, unifying filter and query as one declared pipeline.
- [ ] **Step 4 -- declarative anchors.** Zero-width, queryable, non-rendering anchors carried out-of-band (parallel offset structure updated on every splice), with named classes; retire `scripts/dedup.hmk`'s Unicode sentinels and drop the hardcoded `@<`/`@>>` in favor of L2 declarations over the one primitive doc-boundary anchor.

## Engines (archived while the grammar settles)

The five `sandbox/` ports (rust, go, cpp, java, and the standalone `engine.py`) are **archived**: `himark.engine.run_pipeline` now runs the **in-process** Python engine (`himark/engine/`, the oracle) so there is one implementation to evolve through Steps 2-4. Files stay on disk; the conftest no longer builds any. Re-port later, then re-enable per-engine validation.

- [ ] Re-port the value-aware evaluator + operators to the fast backends once the grammar re-stabilizes, and restore the cross-engine golden/bench checks. Select a port with `HMK_ENGINE=rust|go|cpp|java|python` (build it by hand first); `tests/benchmarks/bench.py` needs those builds to be meaningful again.

## Maybe

- [x] Add Go and C/C++ single-file engine implementations -- Go (`sandbox/engine.go`) and C++ (`sandbox/engine.cpp`) both ship; all five engines are byte-identical on the golden corpus. (Now archived -- see above.)
- [ ] Consider updating arithmetic universes joined by an operator adopt the RHS alphabet. That way `| @alpha` goes from being readable sugar to a first class mechanic.
