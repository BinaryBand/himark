import type { Mode, RunResult } from "./types";

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
