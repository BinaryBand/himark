# TODO

## Performace

### Optimization

- [ ] Ensure Rust runs with `cargo run --release` so we don't disable optimizations
- [ ] Cache the VM-ready instructions produced by `prepare(program)`, keyed by `Program` identity
- [ ] Remember where each pass's last real change ended and let the next pass only *begin* matches before that point
- [ ] Bake matcher objects into prepared instructions
- [ ] Memoize dynamic-range endpoints within a match pass
- [ ] A/B test various engines, optimizations, and languages

## Maybe

- [ ] Add Go and C/C++ single-file engine implementations.
