# TODO

## Performace

### Optimization

- [x] Ensure Rust runs with `cargo run --release` so we don't disable optimizations -- runner invokes the prebuilt `target/release` binary; conftest builds `--release`
- [x] Cache the VM-ready instructions produced by `prepare(program)`, keyed by `Program` identity -- in Rust `prepare_elements` runs once per statement and is reused across every splice position and fixed-point round (the subprocess handles one pipeline per invocation, so there is no cross-call reuse left to cache)
- [x] Bake matcher objects into prepared instructions -- `Char`/`Complement`/`ValueRange` now carry their baked matcher, dropping the per-call `excl`/`inner_groups`/`alph` clone from the hot loop (~3.75x on the base58 value-band workload)
- [x] A/B test various engines, optimizations, and languages -- `tests/bench/bench.py`
- [ ] Remember where each pass's last real change ended and let the next pass only *begin* matches before that point -- holds for fixed-point passes; semantically delicate (would diverge the Rust engine's strategy from the Python oracle), needs its own validated change
- [ ] Memoize dynamic-range endpoints within a match pass -- low value; endpoints resolve from per-position backtracking state, so a naive cache is unsafe

## Maybe

- [ ] Add Go and C/C++ single-file engine implementations.
