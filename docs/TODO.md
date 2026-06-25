# TODO

## Performance

- [x] ~~**Deferred capture materialization**~~ — **done (general engine win).** The match loop built each capture's text slice and `reps[:k]` trim on *every* backtracking count it tried, so a long `[..]`/`[1..]` run that backs off toward a constraining continuation cost O(L²). Captures now defer both (text re-derived from the absolute span on demand by the rare back-reference that reads one mid-match, trimmed once at `_finalize`). Helps any backtracking-heavy pattern: dedup **n=80 6.9→2.9s, n=120 17.1→5.2s** (speedup grows with n — order cut, not a constant), and field-length scaling went from quadratic to ~linear (**41→5.8s** at 4× field width). Identical output; all tests pass.

- [x] ~~**Look-ahead ladder**~~ — **tested, harmful (do not pursue).** A geometric ladder of QUICK windows (`[..300]/[..3000]/[..30000]`, etc.) ran **1.4–3× slower** than the single `[..3000]` pass on 80/120-row slices (identical output): each extra bounded sweep re-scans every partnerless singleton, and that overhead outweighs the unbounded passes it saves. The single tuned window stays.

- [ ] **Key-prefix blocking** — partition `dedup.hmk` lines into buckets by the first few characters of the normalized key before the MATCH pass, so each cross-document scan stays within O(n/k) rows per bucket and singletons in a Y-only or P-only bucket retire without scanning the full file.

- [ ] **Radix sort + linear merge** — sort `dedup.hmk` lines by normalized key using a character-by-character radix distribution pass (O(L·n), no back-reference scan), so equal-key Y/P pairs become adjacent and the MATCH rule reduces to a bounded look-ahead instead of a quadratic unbounded sweep.

- [ ] **Key fingerprinting** — hash each normalized title key to a short fixed-width fingerprint (using the `b256`/`uint` filters) so `{$0}` back-reference comparisons are O(fingerprint length) rather than O(title length); keep the original key for a verify step after each fingerprint match.

- [ ] **Retire proven singletons early** — once a keyed `dedup.hmk` line has been scanned against the whole file with no partner, move it past the `§` skip guard so later MATCH sweeps stop re-scanning it; the ~793 unmatched singletons are what each fixed-point pass currently re-pays.

- [ ] **Segmented fixed-point document** — `splice_to_fixed_point` rebuilds the entire document (`"".join`) every pass, so the settled tail is re-copied even when only a small region changed; keep the document as head + frozen-tail segments and re-splice only the dirty region. This is the real ceiling on the incremental fixed point: the safe scan-prune (only begin matches before the last change) is inert on bubble_sort/dedup because their edits span the document, and where edits *do* localize the per-pass full rebuild dominates instead.

- [ ] **Bounded-width prefix skip** — the incremental sweep only prunes the tail because a forward-reading rule can begin a match before a change and read into it; for a statically bounded-width pattern (no open-ended `[..]`/value bound) the reach is finite, so the sweep could also skip the prefix up to `first_change − max_width`, giving local contracting rules a tight dirty-window scan. Needs a max-match-width analysis over the compiled program.
