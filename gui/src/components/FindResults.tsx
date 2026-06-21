import { useMemo } from "react";
import type { MatchSpan } from "../types";

interface Props {
  target: string;
  matches: MatchSpan[];
}

// The OUTPUT pane in Find mode: a dev-friendly breakdown of every match — its
// 1-based ordinal, the matched text (whitespace made visible), the byte span,
// its length, and the 1-based line:column where it starts.
export function FindResults({ target, matches }: Props) {
  // Precompute a newline offset table once, so line:column for each match is a
  // binary search rather than a re-scan of the whole document per match.
  const newlines = useMemo(() => {
    const idx: number[] = [];
    for (let i = 0; i < target.length; i++) {
      if (target[i] === "\n") idx.push(i);
    }
    return idx;
  }, [target]);

  if (matches.length === 0) {
    return <div className="find-empty">No matches.</div>;
  }

  return (
    <div className="find-results">
      <div className="find-summary">
        {matches.length} match{matches.length === 1 ? "" : "es"}
      </div>
      {matches.map((m, i) => {
        const text = target.slice(m.start, m.end);
        const { line, col } = lineCol(newlines, m.start);
        return (
          <div className="find-row" key={`${m.start}-${m.end}-${i}`}>
            <span className="find-idx">{i + 1}</span>
            <code className="find-text">{visible(text)}</code>
            <span className="find-meta">
              [{m.start}–{m.end}] · len {m.end - m.start} · L{line}:C{col}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// 1-based line/column of `offset`, from the sorted newline-offset table.
function lineCol(newlines: number[], offset: number): { line: number; col: number } {
  let lo = 0;
  let hi = newlines.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (newlines[mid] < offset) lo = mid + 1;
    else hi = mid;
  }
  const lineStart = lo === 0 ? 0 : newlines[lo - 1] + 1;
  return { line: lo + 1, col: offset - lineStart + 1 };
}

// Render whitespace visibly so a match on a newline/tab/space isn't invisible.
function visible(text: string): string {
  if (text === "") return "∅";
  return text.replace(/\n/g, "↵").replace(/\t/g, "→").replace(/ /g, "·");
}
