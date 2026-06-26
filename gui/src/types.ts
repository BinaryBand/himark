export type Mode = "find" | "execute";

export interface Expression {
  id: string;
  text: string;
  enabled: boolean;
}

export interface Project {
  name: string;
  expressions: Expression[];
}

export interface TestString {
  name: string;
  text: string;
}

// An open test-string tab — the working set across the top of the app.
export interface TestTab {
  id: string;
  name: string;
  text: string;
}

export interface MatchSpan {
  start: number;
  end: number;
}

// A tokenized span from the "highlight" bridge mode: `cls` indexes the
// highlight.hmk rule (and thus the token class) that matched it.
export interface HighlightSpan {
  start: number;
  end: number;
  cls: number;
}

export interface RunResult {
  matches?: MatchSpan[];
  output?: string;
  count?: number;
  error?: string;
}

export function newId(): string {
  return Math.random().toString(36).slice(2, 10);
}
