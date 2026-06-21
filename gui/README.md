# Himark Tester

A React + TypeScript playground for HMK. Edit a list of toggleable expressions,
point them at a test string, and watch matches highlight (**Find**) or the
pipeline transform the document live (**Execute**).

```sh
cd gui
npm install
npm run dev          # http://localhost:5173
```

The dev server runs the real engine: `vite.config.ts` installs a `/api/run`
middleware that pipes each request to [`bridge.py`](bridge.py), which imports
`himark` directly. It uses the repo's `.venv` interpreter by default — override
with `HIMARK_PYTHON=/path/to/python`.

## What it does

- **Find** — paints every enabled expression's matches over the test string.
- **Execute** — runs the enabled expressions as a pipeline (each spliced over the
  whole document in order, exactly as a `.hmk` script runs) and shows the result.
  The OUTPUT badge counts splices applied; in Find it counts matches.

## Save / load (memory)

Projects (a named list of toggleable expressions) and test strings persist to
`localStorage`. Use the **Project** and **Test** menus in the top bar to save the
current one under a name, or load/delete a saved one.

### Bundled defaults

Loaded ready to use (not deletable):

- **Projects** — every script in [`himark/scripts/`](../himark/scripts), split
  into one toggleable expression per statement.
- **Test strings** — the demo targets in
  [`tests/demos/resources/`](../tests/demos/resources).
