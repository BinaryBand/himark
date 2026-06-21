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

export interface RunResult {
  matches?: MatchSpan[];
  output?: string;
  count?: number;
  error?: string;
}

export function newId(): string {
  return Math.random().toString(36).slice(2, 10);
}
