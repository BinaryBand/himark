# TODO

## Performance

Speed hacks deliberately stripped (or forgone) on the `simplify` branch to keep the engine a "dumb" interpreter. Re-add these later **one at a time, behind a green test suite**, since each trades readability for speed. Ordered roughly best-effort-per-line-of-complexity first.

### 1. Per-program instruction cache

- **What:** Cache the VM-ready instructions produced by `prepare(program)`, keyed by `Program` identity, so a query is lowered once and reused. Previously `himark/engine/runtime.py` (`Runtime`) held a `dict[int, handle]` with a `weakref.finalize` to evict on GC.
- **Why it matters:** The branch model re-runs the *same* query across many branches (a nested transform matches the same pattern in every leaf). Without the cache, `prepare` re-bakes reps/alphabets/group-sorts on every call.
- **Catch:** Keying by `id()` needs the weakref finalizer to avoid stale entries when a `Program` is freed and a new one is allocated at the same address. Simplest re-add: cache on the `Program` object itself (a lazily-populated field) instead of a side dict.

### 2. Fixed-point tail-pruning (`stop` bound)

- **What:** In `splice_to_fixed_point`, remember where each pass's last real change ended and let the next pass only *begin* matches before that point (the settled tail is byte-identical, so re-scanning it for new starts is waste). Threaded a `stop` arg through `deltas` → `find_matches` → the VM's position loop (`limit = min(stop, n)`).
- **Why it matters:** ~1.4–1.6× on the full dedup file; the win grows with input size as the settled tail lengthens over many passes.
- **Catch:** Only the **tail** is safe to prune. The dual (skipping the prefix before the first change) is **unsafe** — a forward-reading rule can begin before the change and read into it (bubble_sort mis-sorts `2,3,1`). Re-add the `stop` parameter, not a `start` skip.

### 3. Pluggable native backend (the "Rust seam")

- **What:** Restore the backend indirection (`engine/backend/` with a `python` backend and a swappable `find_matches`/`prepare` interface) so a compiled native matcher (Rust/C) can be dropped in behind the same `Program` contract. The serialized `Program` is already portable (JSON/pickle) precisely to cross this seam.
- **Why it matters:** The Python VM is the floor on matching throughput; a native backend is the largest available win for hot patterns.
- **Catch:** Keep the `Program`/`Match` data contract backend-agnostic. A native backend must honour the same semantics (backtracking, capture spans, the `stop` bound from #2).

### 4. Static-reps fast path (skip deferred-capture machinery)

- **What:** When a repetition has no count-reference (`reps` is a plain min/max, not `[#i]`), the chosen count is known without backtracking captures. Materialize such captures eagerly instead of carrying the deferred `Capture.count >= 0` / `-1` settlement state through `_run_matcher` and `_finalize`.
- **Why it matters:** Removes per-attempt capture bookkeeping for the common case (most reps are static), shrinking the hot loop.
- **Catch:** Count-refs (`[#i]`) and back/stage-refs still *must* defer — resolution happens at match time. Split the path; don't delete the deferred branch.

### 5. Bake matcher objects into prepared instructions

- **What:** Have `prepare` attach a ready matcher object (with `match`/`accepts`/`equal_unit`) to each instruction so the hot loop calls a method directly, instead of dispatching on a kind string every attempt. (If Tier 4 of the simplify plan already introduced matcher objects for clarity, this is just moving their construction into `prepare`.)
- **Why it matters:** Eliminates repeated string-kind `switch`es and tuple unpacking in `_run_matcher` per position and per backtrack.
- **Catch:** Construction must stay in `prepare` (once per program), never in the match loop.

### 6. Memoize dynamic-range endpoints within a match pass

- **What:** `DYN_RANGE` recomputes endpoint text, width bounds (`wmin`/`wmax`), and value bounds from the referenced capture on *every* match attempt. References don't change during a single backtracking pass, so cache the resolved endpoints per pass.
- **Why it matters:** Avoids re-running `alphabet.value()` and width derivation on each retry of a value-band match.
- **Catch:** Stage-refs are data-dependent across positions — scope the memo to one start position / one `_run_program` invocation, and invalidate when the referent changes.

## Portable payload (cross-project IR)

Goal: let the parser/compiler emit a **platform-agnostic, versioned payload** that a separate project — Python *or* Rust, with no import of this codebase — can consume and execute. The IR was designed for this: instructions are `(opcode: int, *operands)` over primitives ([`models/opcodes.py`](opcodes.py)), the smart objects (`Alphabet`, `Reps`) are built engine-side in `prepare()` from primitive *descriptors*, and the prelude/variables are expanded at compile time so nothing external is needed at run time. This pairs with Performance #3 (the Rust seam): the payload spec is what makes a native backend pluggable.

What's missing to make it real:

- **Complete the serializer pair.** Only `Template.to_json()` exists; `Program.to_json` is referenced in docstrings but absent (the parser golden test hand-rolls it via `_tuples_to_lists`). Add `Program.to_json` and a top-level `pipeline_to_json` envelope: `{ "version": 1, "statements": [[step, …], …] }` with each step tagged query-vs-template and carrying its `fixed_point` flag (set per-statement by the runner, so it must be captured).
- **Add a deserializer.** There is no `from_json` anywhere. Add one so the payload round-trips back into runnable steps (both as the Python VM's input and as a reference for the Rust impl). Normalize JSON arrays → the positional tuples the VM expects (`path`, `("range", …)` / `("groups", …)` alphabet descriptors).
- **Write the wire-format spec (`docs/PAYLOAD.md`).** This *is* the contract for an external consumer: opcode integers (note `9` is unused, between `DYN_RANGE=8` and `COMPLEMENT=10`), each opcode's operand layout, the reps encoding (`[min,max]` / `["#",g]` / `["=",[…]]`), the alphabet-descriptor and ref-descriptor (`back`/`count`/`stage`) forms, anchor kinds (0–3), and the `Expr` JSON shape. Version it so opcode/filter/anchor drift is detectable.
- **Golden round-trip test.** Assert `from_json(to_json(steps))` executes identically to the steps directly, over the existing demo/north-star corpus.

Note: this is *additive* and somewhat orthogonal to the `simplify` branch's strip-it-down goal, so it's cleanest as its own follow-up once the simplification lands.
