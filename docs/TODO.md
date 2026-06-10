# TODO (Marky)

- [ ] Value range semantics are undefined
  - The spec says matching is "under the class ordering" but the examples imply numeric semantics.
- [ ] `<<sep>>` semantics are under-defined
  - `<<\n>>`, `<<>>`, `[**]<<>>[**]` don't follow a single, coherent rule.
- [ ] `[...]` is overloaded without disambiguation rules
- [ ] Does `<<sep>>` form a capture group?
- [ ] Three-argument repetition range `2..n..5` is unexplained
- [ ] Alternation precedence is unspecified
  - `||` separates alternative patterns at any level" — but is `[a][b] || [c]` parsed as `([a][b]) || [c]` or `[a]([b] || [c])`?
- [ ] Complement inside value ranges creates two exclusion syntaxes
  - How does `!` behave inside `{}` vs inside `[]`?
- [ ] Formalize transformer chain nesting notation
- [ ] Define per-character exclusion syntax
