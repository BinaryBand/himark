# TODO

## Performance

- [ ] **Look-ahead ladder** — replace the single `[..3000]` QUICK window in `dedup.hmk` with a geometric ladder (`[..300]`, `[..3000]`, `[..30000]`) before the unbounded sweep, so near twins clear at the cheapest bounded scan and the unbounded pass runs on only the far-apart stragglers.

- [ ] **Key-prefix blocking** — partition `dedup.hmk` lines into buckets by the first few characters of the normalized key before the MATCH pass, so each cross-document scan stays within O(n/k) rows per bucket and singletons in a Y-only or P-only bucket retire without scanning the full file.

- [ ] **Radix sort + linear merge** — sort `dedup.hmk` lines by normalized key using a character-by-character radix distribution pass (O(L·n), no back-reference scan), so equal-key Y/P pairs become adjacent and the MATCH rule reduces to a bounded look-ahead instead of a quadratic unbounded sweep.

- [ ] **Key fingerprinting** — hash each normalized title key to a short fixed-width fingerprint (using the `b256`/`uint` filters) so `{$0}` back-reference comparisons are O(fingerprint length) rather than O(title length); keep the original key for a verify step after each fingerprint match.

- [ ] **Retire proven singletons early** — once a keyed `dedup.hmk` line has been scanned against the whole file with no partner, move it past the `§` skip guard so later MATCH sweeps stop re-scanning it; the ~793 unmatched singletons are what each fixed-point pass currently re-pays.

- [ ] **Segmented fixed-point document** — `splice_to_fixed_point` rebuilds the entire document (`"".join`) every pass, so the settled tail is re-copied even when only a small region changed; keep the document as head + frozen-tail segments and re-splice only the dirty region. This is the real ceiling on the incremental fixed point: the safe scan-prune (only begin matches before the last change) is inert on bubble_sort/dedup because their edits span the document, and where edits *do* localize the per-pass full rebuild dominates instead.

- [ ] **Bounded-width prefix skip** — the incremental sweep only prunes the tail because a forward-reading rule can begin a match before a change and read into it; for a statically bounded-width pattern (no open-ended `[..]`/value bound) the reach is finite, so the sweep could also skip the prefix up to `first_change − max_width`, giving local contracting rules a tight dirty-window scan. Needs a max-match-width analysis over the compiled program.
