# In brief

## Base arithmetic

**$\Sigma$** represents a finite alphabet, and **$\Delta$** represents a linear set of integers, therefore $\Sigma_\Delta = \bigcup (\Sigma^\Delta_i)$, where each member of $\Sigma^\Delta_i$ is congruent.

So, if $\Sigma$ = `{a,b,...,z}` and $\Delta$ = `{1,2,3}` then $\Sigma^\Delta$ = `{a,b,...,zzz}`.

If $\Delta$ = $\Z \bigcap [N, \infty)$, it is represented as `[N:]` with a vacant right-side argument.

Adding another layer, $\Sigma$ = `{{a,A},{b,B},...,{z,Z}}` become case-agnostic.

`{a..b}{cd}{e..f}` = `{acde,acdf,bcde,bcdf}`, therefore `{{a..z:zzzzz},!{{a..b}{cd}{e..f}}}` is valid, since:

- `{a..z}` limits the single character range to a 26-character sub-alphabet of Unicode
- `{a..b}{cd}{e..f}` fits inside `{a,b,...,zzzzz}`

Under the `..` operator,nested sub-sets stay congruent.

## Self-referencing

Every `{...}` acts as a capture group that can be referenced via `$i` where `i` is the 'nth' captured, static string.

E.g. `{a..z:aaa..zzz}{$0}[0..]` will match any three-letter lowercase string, and any of it's subsequent occurrences.

Whereas `$i` accesses a capture's content, `#i` accesses it's repetition count.

E.g. `{a..z:aaa..zzz}[2..9]{ repeated {#0} times}` would capture `abcabcabc repeated 3 times` and skip `abcabcabc repeated 4 times`.

Either `$` or `#` can be accessed within a `{...}`, but only the latter can be accessed within a `[...]`.

## Piping and transformations

`=>` feeds the previous matches' context into a subsequent expression where it can be templated via moustache notation; e.g. `{a..z:aaa..zzz}[2..9] => "" => "<p>{{ 0$0 }}</p>"`.

`$` and `#` accessors assume they're accessing content from the previous section. `{{ i$0 }}` overrides the default scope to access any expression in the pipeline by index `i`.

> **Note:** Every expression in a pipeline can be either a query or a template expression. If it's the former, it queries the previous expression as a Unicode string.

## Notes

A class occupies a **single position** -- by default it matches exactly one symbol.

Every range normalises to a banded alphabet `{A:floor..ceiling}`: the payload `A` is the most-limiting (narrowest) alphabet among the operands -- ambient Unicode when none is named -- the floor is the left operand's minimum, and the ceiling is the right operand's maximum. So `{x}` is `{@uni:x..x}`, `{x..y}` is `{@uni:x..y}`, and a named payload (`{A:x..y}`) keeps `A`. It is a compile error when the ceiling cannot be spelled in `A` (`{a..c:zz}`).`

### Assumptions

- **{a}** -- `a` exists on the Unicode plain by default since an alphabet was never explicitly assigned to it. It's the equivalent of `{@uni:a..a}`
- **`{a..z}`** -- `a` and `z` both exist on the Unicode plain so they can meet. `{@uni:a..z}`
- **`{a..z:c}`** -- Since `{a..z}` = `{@uni:a..z}` (a subset of Unicode) and `c` exists on the Unicode plain, the former becomes the limiting alphabet. `{a..z:c}`
- **`{a..z:cc}`** -- `{a..z}` is the limiting alphabet since `cc`'s Unicode alphabet is a super-set. `{a..z:a..cc}`
- **`{{a,A},{b,B},...,{z,Z}}`** -- Equivalent to `{@uni:a..z}` where every nested pair is functionally the same character as its partner.
- **`{a..c:zz}`** -- Compilation error since no-combination of `{a,b,c}` characters can meet `zz`. The right-side alphabet is not a subset of the left-side's.
- **`{1}{@d,@u,@l,!{0,l,I,O}:111111111111111111111111..2n1XR4oJkmBdJMxhBGQGb96gQ88xUzxLFyG}`** -- Any base-58 string with exactly 25-bytes. AKA, a legacy Bitcoin address (ignoring checksums).
- **`{1}{@d,@u,@l,!{0,l,I,O}:{1}[24]..2n1XR4oJkmBdJMxhBGQGb96gQ88xUzxLFyG}`** -- A legacy Bitcoin address (ignoring checksums) but shorter.

> **Note:** `0$0` returns a full variable with its respective alphabet and range values, whereas `0$` returns a raw string.

### Structural example

The **shape** of a base58check value -- a version byte, payload, and 4-byte checksum -- needs only `b256` and adjacency; decode the value to bytes, then slice by position:

```proto
{1}{@d,@u,@l,!{0,l,I,O}:111111111111111111111111..2n1XR4oJkmBdJMxhBGQGb96gQ88xUzxLFyG}
  => "{{ 0$0 | b256(25) }}"
  => {{@b256}}[21]{{@b256}}[4]   // $0 = 21-byte body (version + payload), $1 = checksum
```

> **Checksum validation is deferred.** Comparing the carried checksum against the double-SHA256 of the body is a derived (hash) transform -- a layer built on these byte primitives, not baked into the core (see [HMK.md](HMK.md), Filters). The structural match above is fully layer 1.
>
> `b256` reads a **group** accessor (`0$0`, or `$0` for the current stage) as the base-58-decoded integer — the alphabet and bounds ride along with the capture — and re-encodes it as 25 big-endian bytes. The **whole-stage** accessor `0$` is a raw string with no alphabet to decode, so a value filter cannot read it.
