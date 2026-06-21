// Default content bundled from the repo: the `.hmk` scripts become starter
// projects (one toggleable expression per statement) and the demo resources
// become starter test strings. Vite inlines these at build time via the raw
// glob imports below (server.fs.allow lets it read outside gui/).

import { splitStatements } from "./hmk";
import { newId, type Project, type TestString } from "./types";

const scriptFiles = import.meta.glob("../../himark/scripts/*.hmk", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const resourceFiles = import.meta.glob(
  "../../tests/demos/resources/*.{txt,md,hmk,html,csv}",
  { query: "?raw", import: "default", eager: true },
) as Record<string, string>;

function basename(path: string): string {
  return path.split("/").pop() ?? path;
}

export const defaultProjects: Project[] = Object.entries(scriptFiles)
  .map(([path, source]) => ({
    name: basename(path),
    expressions: splitStatements(source).map((text) => ({
      id: newId(),
      text,
      enabled: true,
    })),
  }))
  .filter((p) => p.expressions.length > 0)
  .sort((a, b) => a.name.localeCompare(b.name));

export const defaultTestStrings: TestString[] = Object.entries(resourceFiles)
  .map(([path, text]) => ({ name: basename(path), text }))
  .sort((a, b) => a.name.localeCompare(b.name));
