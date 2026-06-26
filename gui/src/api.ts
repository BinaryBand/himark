import type { HighlightSpan, Mode, RunResult } from "./types";

// POST the request to the Vite middleware, which pipes it to bridge.py.
export async function runEngine(
  mode: Mode,
  expressions: string[],
  target: string,
): Promise<RunResult> {
  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, expressions, target }),
    });
    return (await res.json()) as RunResult;
  } catch (e) {
    return { error: e instanceof Error ? e.message : "request failed" };
  }
}

// Tokenize every `target` (the sidebar expressions) by running the highlight
// `patterns` over each — one request for the whole sidebar. Returns a span list
// per target, aligned to `targets`; failures degrade to no highlighting.
export async function highlightExpressions(
  patterns: string[],
  targets: string[],
): Promise<HighlightSpan[][]> {
  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "highlight", expressions: patterns, targets }),
    });
    const data = (await res.json()) as { highlights?: HighlightSpan[][] };
    return data.highlights ?? targets.map(() => []);
  } catch {
    return targets.map(() => []);
  }
}
