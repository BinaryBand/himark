# Himark (HMK) — VS Code syntax highlighting

A minimal VS Code extension that adds syntax highlighting and basic editing
support (line comments, bracket matching, auto-close) for Himark `.hmk` scripts.

It is a TextMate grammar, so it highlights by token shape — see
[`../../docs/GRAMMAR.md`](../../docs/GRAMMAR.md) for the language it follows.

## What it highlights

| Token | Scope | Example |
| --- | --- | --- |
| Line comments | `comment.line` | `// tidy the file edges` |
| Pipeline arrows | `keyword.operator.arrow` | `=>`, `<=` |
| Quoted templates | `string.quoted.double` | `"<h{{#0}}>"` |
| Moustache refs & filters | `variable.other.accessor`, `support.function.filter` | `{{ 0$0 \| b256(25) }}` |
| `{ … }` universes | `meta.group` + punctuation | `{a..z}`, `{cat,dog}` |
| Macros | `support.constant.macro` | `@d`, `@w`, `@hex` |
| Anchors | `keyword.control.anchor` | `@^`, `@$`, `@^^`, `@$$` |
| Self/stage references | `variable.language.reference` | `$0`, `#0`, `1$2.3` |
| Operators | `keyword.operator` | `,` `..` `:` `!` |
| `[ … ]` counts | `meta.count` + `constant.numeric` | `[1..6]`, `[#0]` |
| Escapes | `constant.character.escape` | `\{`, `\,`, `\"` |

## Install (local)

**Option A — symlink into your user extensions** (fastest for hacking on it):

```sh
ln -s "$(pwd)/editors/vscode" ~/.vscode/extensions/himark-hmk
```

Then reload VS Code (Developer: Reload Window). Open any `.hmk` file.

**Option B — package and install a `.vsix`:**

```sh
npm install -g @vscode/vsce
cd editors/vscode && vsce package
code --install-extension himark-hmk-0.1.0.vsix
```

## Notes / limits

TextMate grammars match by regex, not a real parser, so — like the formatters in
`himark/scripts/` — a few shape-ambiguous cases are approximate: a `//` is treated
as a comment outside strings/braces, and very deep nesting is colored generically.
This is highlighting only; it does not run or validate patterns.
