# TODO

## Performance

- [ ] **Look-ahead ladder** — replace the single `[..3000]` QUICK window in `dedup.hmk` with a geometric ladder (`[..300]`, `[..3000]`, `[..30000]`) before the unbounded sweep, so near twins clear at the cheapest bounded scan and the unbounded pass runs on only the far-apart stragglers.

- [ ] **Key-prefix blocking** — partition `dedup.hmk` lines into buckets by the first few characters of the normalized key before the MATCH pass, so each cross-document scan stays within O(n/k) rows per bucket and singletons in a Y-only or P-only bucket retire without scanning the full file.

- [ ] **Radix sort + linear merge** — sort `dedup.hmk` lines by normalized key using a character-by-character radix distribution pass (O(L·n), no back-reference scan), so equal-key Y/P pairs become adjacent and the MATCH rule reduces to a bounded look-ahead instead of a quadratic unbounded sweep.

- [ ] **Key fingerprinting** — hash each normalized title key to a short fixed-width fingerprint (using the `b256`/`uint` filters) so `{$0}` back-reference comparisons are O(fingerprint length) rather than O(title length); keep the original key for a verify step after each fingerprint match.
