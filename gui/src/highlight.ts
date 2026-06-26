// HMK syntax highlighting — the *tokenizing* lives in `gui/highlight.hmk` (HMK
// patterns run through the real engine via the bridge's "highlight" mode); this
// module owns the *styling*: it parses that script into ordered rules and maps
// each token class to a colour.

import rawScript from "../highlight.hmk?raw";
import type { HighlightSpan } from "./types";

export interface HighlightRule {
  className: string;
  pattern: string;
}

// Parse the tokenizer script into ordered (class, pattern) rules. A
// `// class: NAME` line names the class of the rules that follow it; every other
// non-comment, non-blank line is a find pattern. List order is precedence —
// later rules repaint earlier ones (so a string wins over the braces inside it).
function parseRules(src: string): HighlightRule[] {
  const rules: HighlightRule[] = [];
  let className = "";
  for (const line of src.split("\n")) {
    const s = line.trim();
    const tag = /^\/\/\s*class:\s*(\S+)/.exec(s);
    if (tag) {
      className = tag[1];
    } else if (s && !s.startsWith("//")) {
      rules.push({ className, pattern: s });
    }
  }
  return rules;
}

export const HIGHLIGHT_RULES = parseRules(rawScript);
export const HIGHLIGHT_PATTERNS = HIGHLIGHT_RULES.map((r) => r.pattern);

// The palette (this file's job — the styling the prompt asked TypeScript to own).
// A class absent here renders in the default text colour. Tuned for the dark
// theme in styles.css (`--bg: #0c111b`).
export const TOKEN_COLORS: Record<string, string> = {
  bracket: "#7f8ea3", // structural punctuation { } [ ]
  arrow: "#c678dd", // => / <=>
  anchor: "#e5c07b", // @< @> @<< @>>
  alphabet: "#61afef", // @d @w @hex …
  count: "#d19a66", // [1..] [#0]
  reference: "#56b6c2", // $0 $1
  escape: "#e06c75", // \n \, \{ …
  template: "#98c379", // "quoted" templates
  comment: "#6b7a90", // // line comments
};

export interface ColoredSegment {
  text: string;
  color?: string;
}

// Resolve overlapping token spans into a flat, gap-free list of coloured runs.
// Spans are applied in class order (the script's precedence), so a later class
// overwrites an earlier one per character; runs of equal colour are coalesced.
export function colorSegments(text: string, spans: HighlightSpan[]): ColoredSegment[] {
  const colorAt: (string | undefined)[] = new Array(text.length).fill(undefined);
  for (const sp of [...spans].sort((a, b) => a.cls - b.cls)) {
    const color = TOKEN_COLORS[HIGHLIGHT_RULES[sp.cls]?.className];
    if (!color) continue;
    for (let i = sp.start; i < sp.end && i < text.length; i++) colorAt[i] = color;
  }
  const segments: ColoredSegment[] = [];
  let i = 0;
  while (i < text.length) {
    const color = colorAt[i];
    let j = i + 1;
    while (j < text.length && colorAt[j] === color) j++;
    segments.push({ text: text.slice(i, j), color });
    i = j;
  }
  return segments;
}
