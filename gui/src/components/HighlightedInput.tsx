import { useEffect, useRef } from "react";
import type { MatchSpan } from "../types";

interface Props {
  value: string;
  onChange: (v: string) => void;
  matches: MatchSpan[];
}

// An editable textarea with a highlight layer painted behind it: a backdrop div
// renders the same text with <mark> around each match span, and a transparent
// textarea sits exactly on top. Both share identical metrics, and we mirror the
// textarea's scroll onto the backdrop, so the highlights track the caret.
export function HighlightedInput({ value, onChange, matches }: Props) {
  const backdropRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ta = textareaRef.current;
    const bd = backdropRef.current;
    if (!ta || !bd) return;
    const sync = () => {
      bd.scrollTop = ta.scrollTop;
      bd.scrollLeft = ta.scrollLeft;
    };
    ta.addEventListener("scroll", sync);
    return () => ta.removeEventListener("scroll", sync);
  }, []);

  return (
    <div className="highlight-wrap">
      <div className="highlight-backdrop" ref={backdropRef} aria-hidden>
        {renderSegments(value, matches)}
      </div>
      <textarea
        ref={textareaRef}
        className="highlight-textarea"
        spellCheck={false}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function renderSegments(text: string, matches: MatchSpan[]) {
  if (matches.length === 0) return text;
  const sorted = [...matches].sort((a, b) => a.start - b.start);
  const out: React.ReactNode[] = [];
  let pos = 0;
  sorted.forEach((m, i) => {
    if (m.start < pos) return; // skip overlaps — keep the first claim on a span
    if (m.start > pos) out.push(text.slice(pos, m.start));
    out.push(<mark key={i}>{text.slice(m.start, m.end)}</mark>);
    pos = m.end;
  });
  out.push(text.slice(pos));
  // A trailing newline must be padded so the backdrop's last line keeps height.
  return out.concat(text.endsWith("\n") ? "​" : "");
}
