// Split a `.hmk` script into its statement strings — a faithful TypeScript port
// of himark's `precompiled.split_statements`, so a script loaded as a default
// project breaks into exactly the expressions the engine would run.
//
// Rules (all at brace/quote depth 0, so braces, quoted templates and `=>`/`//`
// inside them are never misread): `//` starts a line comment; a blank line is
// ignored; a line beginning with `=>` continues the previous statement; any
// other line starts a new one.

function logicalLines(text: string): string[] {
  const lines: string[] = [];
  let buf = "";
  let depth = 0;
  let inq = false;
  let i = 0;
  const n = text.length;
  while (i < n) {
    const c = text[i];
    if (c === "\\" && i + 1 < n) {
      buf += text.slice(i, i + 2);
      i += 2;
      continue;
    }
    if (depth === 0 && !inq && c === "/" && text[i + 1] === "/") {
      const j = text.indexOf("\n", i);
      const end = j === -1 ? n : j;
      buf += text.slice(i, end);
      i = end;
      continue;
    }
    if (c === "\n" && depth === 0 && !inq) {
      lines.push(buf);
      buf = "";
    } else if (c === '"') {
      inq = !inq;
      buf += c;
    } else {
      if (!inq) depth += (c === "{" ? 1 : 0) - (c === "}" ? 1 : 0);
      buf += c;
    }
    i += 1;
  }
  lines.push(buf);
  return lines;
}

function stripComment(line: string): string {
  let depth = 0;
  let inq = false;
  let i = 0;
  while (i < line.length) {
    const c = line[i];
    if (c === "\\" && i + 1 < line.length) {
      i += 2;
      continue;
    }
    if (c === '"') inq = !inq;
    else if (!inq) {
      if (c === "/" && depth === 0 && line[i + 1] === "/") return line.slice(0, i);
      depth += (c === "{" ? 1 : 0) - (c === "}" ? 1 : 0);
    }
    i += 1;
  }
  return line;
}

export function splitStatements(text: string): string[] {
  const statements: string[] = [];
  let current: string[] = [];
  for (const raw of logicalLines(text)) {
    const line = stripComment(raw).replace(/\s+$/, "");
    if (!line.trim()) continue;
    if (line.trimStart().startsWith("=>")) {
      current.push(line);
    } else {
      if (current.length) statements.push(current.join("\n"));
      current = [line];
    }
  }
  if (current.length) statements.push(current.join("\n"));
  return statements;
}
