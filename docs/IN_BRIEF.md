## Base arithmetic

**$\Sigma$** represents a finite alphabet, and **$\Delta$** represents a linear set of integers, therefore $\Sigma_\Delta = \bigcup (\Sigma^\Delta_i)$, where each member of $\Sigma^\Delta_i$ is congruent.

So, if $\Sigma$ = `{a,b,...,z}` and $\Delta$ = `{1,2,3}` then $\Sigma^\Delta$ = `{a,b,...,zzz}`.

If $\Delta$ = $\Z \bigcap [N, \infty)$, it is represented as `[N..]` with a vacant right-side argument.

Adding another layer, $\Sigma$ = `{{a,A},{b,B},...,{z,Z}}` become case-agnostic.

`{a..b}{cd}{e..f}` = `{acde,acdf,bcde,bcdf}`, therefore `{{{a..z}..zzzzz},!{a..b}{cd}{e..f}}` is valid, since:

- `{a..z}` limits the single character range to a 26-character sub-alphabet of Unicode
- `{a..b}{cd}{e..f}` fits inside `{a,b,...,zzzzz}`

The above assumes that the `..` operator collapses the left-side argument into its linear Cartesian product. Deeply nested sub-sets stay congruent.

`{{a,A},{b,B},...,{z,Z}}..{zz}`

## Self-referencing

Every `{...}` acts as a capture group that can be references via `$i` where `i` is the 'nth' captured, static string.

E.g. `{aaa..{a..z}..zzz}{-{$0}}[0..]` will match any three-letter, lowercase string and any subsequent occurrences if separated by a '-'.

Whereas `$i` accesses a capture's content, `#i` accesses it's repeat count.

E.g. `{aaa..{a..z}..zzz}[2..9]{ repeated {#0} times}` would capture `abcabcabc repeated 3 times` and skip `abcabcabc repeated 4 times`. However, it would capture `abcabcabc 2 times`, so watch out for unintended sub-matches.

Either `$` or `#` can be accessed within `{...}`, but only the latter can be accessed within `[...]`.

## Piping and transformations

`=>` feeds the previous matches' context into a subsequent expression where it can be templated via moustache notation; e.g. `{aaa..{a..z}..zzz}[2..9] => "<p>{{0$0}}</p>"`.

`$` and `#` accessors assume they're accessing content on the same expression. `{{i$0}}` overrides the default scope assumption to access any expression in the pipeline by its index `i`.

Mid-pipe template expressions only feed non-static values to the next link; e.g. `... => "<p>{{0$0}}</p>" => ...` drops "\<p>" and "\</p>" from the pipeline scope but appends it to the document.

Templates can concatenate string values when comma separated; e.g. `... => "{{0$0,2$1,1$2}}"`.

## Notes

A class occupies a **single position** -- by default it matches exactly one symbol.

Every range normalises to a three-part `{floor..A..ceiling}`: the middle `A` is the most-limiting (narrowest) alphabet among the operands -- ambient Unicode when none is named -- the floor is the left operand's minimum, and the ceiling is the right operand's maximum. So `{x}` is `{x..{@uni}..x}`, `{x..y}` is `{x..{@uni}..y}`, and an explicit middle (`{x..A..y}`) keeps `A`. It is a compile error when the ceiling cannot be spelled in `A` (`{{a..c}..zz}`).

### Assumptions

- **{a}** -- `a` exists on the Unicode plain by default since an alphabet was never explicitly assigned to it. It's the equivalent of `{a..{@uni}..a}`
- **{a..z}** -- `a` and `z` both exist on the Unicode plain so they can meet. `{a..{@uni}..z}`
- **{{a..z}..c}** -- Since `{a..z}` = `{a..{@uni}..z}` (a subset of Unicode) and `c` exists on the Unicode plain, the former becomes the limiting alphabet. `{a..{a..z}..c}`
- **{{a..z}..cc}** -- `{a..z}` is the limiting alphabet since `cc`'s Unicode alphabet is a super-set. `{a..{a..z}..cc}`
- **{{a,A},{b,B},...,{z,Z}}** -- Equivalent to `{a..{@uni}..z}` where every nested pair is functionally the same character as its partner.
- **{{a..c}..zz}** -- Compilation error since no-combination of `{a,b,c}` characters can meet `zz`. The right-side alphabet is not a subset of the left-side's.
- **{1}{24..33:{@b58}}** -- Any 20-byte string in base-58 with a leading '1'. AKA, a legacy Bitcoin address (ignoring checksums)
- **{1}{24..33:{@b58}} => "{{0\$, £hash(0\$)}}"** -- A legacy Bitcoin address including the checksum (as pseudo-script).
