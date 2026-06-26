import { useMemo } from "react";
import { colorSegments } from "../highlight";
import type { HighlightSpan } from "../types";

interface Props {
  value: string;
  spans: HighlightSpan[];
  enabled: boolean;
  onChange: (v: string) => void;
}

// An auto-growing expression editor with HMK syntax colouring: a backdrop layer
// renders the text as coloured token runs (from `colorSegments`) and a
// transparent textarea sits exactly on top, sharing identical metrics — the same
// overlay trick as HighlightedInput, but sized to its content for the sidebar.
export function HighlightedExpression({ value, spans, enabled, onChange }: Props) {
  const segments = useMemo(() => colorSegments(value, spans), [value, spans]);
  return (
    <div className="expr-hl-wrap" style={{ opacity: enabled ? 1 : 0.5 }}>
      <div className="expr-hl-backdrop" aria-hidden>
        {segments.map((s, i) =>
          s.color ? (
            <span key={i} style={{ color: s.color }}>
              {s.text}
            </span>
          ) : (
            s.text
          ),
        )}
        {/* A trailing newline (or empty value) needs a pad so the backdrop keeps
            the caret's line height. */}
        {value === "" || value.endsWith("\n") ? "​" : ""}
      </div>
      <textarea
        className="expr-hl-textarea"
        spellCheck={false}
        value={value}
        rows={1}
        placeholder="HMK expression…"
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
