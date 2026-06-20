# Project Marky

A small **Markdown** demo for the `md_html.hmk` transpiler.

## Features

- Headings and *emphasis*
- Inline `code` spans
- [Links](https://example.com) and lists

### Ordered

1. first
2. second
3. third

> A blockquote with a **bold** word.

Feature | Status
------- | ------
Tables  | works
Code    | masked

---

```python
# not a heading; **not** emphasis, a_b stays a_b
def hello(name):
    return f"hi {name}"  # [not](a-link)
```

Done with `**literal**` markdown left intact.
