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

E.g. `{aaa..{a..z}..zzz}[2..9]{ repeated {#0} times}` would capture `aaabbbccc repeated 3 times` and skip `aaabbbccc repeated 4 times`. However, it would capture `aaabbbccc 2 times`, so watch out for unintended sub-matches.

Since `[...]` always expects base-10 integers, it will accept `#` arguments, assuming it is a lone index key or a range where the left-side argument does not exceed the right.

Either `$` or `#` can be accessed within `{...}`, but only the latter can be accessed within `[...]`.

## Piping and transformations

`=>` feeds the previous matches' context into a subsequent expression where it can be templated via moustache notation; e.g. `{aaa..{a..z}..zzz}[2..9] => "<p>{{0$0}}</p>"`.

`$` and `#` accessors assume they're accessing content on the same expression. `{{i$0}}` overrides the default scope assumption to access any expression in the pipeline by its index `i`.

Mid-pipe template expressions only feed non-static values to the next link; e.g. `... => "<p>{{0$0}}</p>" => ...` drops "\<p>" and "\</p>".

## Notes

A class occupies a **single position** -- by default it matches exactly one symbol. Length is never implicit; it is always declared, by a `[\Delta]` count (`{a..z}[3]` $\to$ `aaa`), a padding width (`{3:{@d}..255}`), or the written width of a value-range endpoint (`{aaa..{a..z}..zzz}` $\to$ three symbols). So a bare `{a..z}` is one letter, and a run is the explicit `{a..z}[1..]`. Factoring length out of the class is what makes the equivalences below hold in any position, not only as `..` endpoints.

Assuming...

- **{a}** -- `a` exists on the Unicode plain by default since an alphabet was never explicitly assigned to it. It's the equivalent of `{a..{@uni}..a}`.
- **{a..z}** -- `a` and `z` both exist on the Unicode plain so they can meet -- one symbol from that range. `{a..{@uni}..z}` (a run is the explicit `{a..z}[1..]`).
- **{{a..z}..c}** -- Since `{a..z}` = `{a..{@uni}..z}` (a subset of Unicode) and `c` exists on the Unicode plain, the former becomes the limiting alphabet. `{a..{a..z}..c}`
- **{{a..z}..cc}** -- `{a..z}` is the limiting alphabet since `cc`'s Unicode alphabet is a super-set. `{a..{a..z}..cc}`
- **{{a,A},{b,B},...,{z,Z}}** -- Equivalent to `{a..{@uni}..z}` where every nested pair is functionally the same character as its partner.
- **{{a..c}..zz}** -- Compile error since no-combination of `{a,b,c}` characters can meet `zz`. The right-side alphabet is not a subset of the left-side's.
