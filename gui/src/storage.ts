// Persistence layer — projects and test strings are saved to localStorage
// ("memory") keyed by name, so they survive reloads and can be re-loaded.

import type { Project, TestString } from "./types";

const PROJECTS_KEY = "himark.projects";
const TEST_STRINGS_KEY = "himark.testStrings";

function read<T>(key: string): Record<string, T> {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "{}") as Record<string, T>;
  } catch {
    return {};
  }
}

function write<T>(key: string, value: Record<string, T>): void {
  localStorage.setItem(key, JSON.stringify(value));
}

export function listProjects(): Project[] {
  return Object.values(read<Project>(PROJECTS_KEY)).sort((a, b) =>
    a.name.localeCompare(b.name),
  );
}

export function saveProject(project: Project): void {
  const all = read<Project>(PROJECTS_KEY);
  all[project.name] = project;
  write(PROJECTS_KEY, all);
}

export function deleteProject(name: string): void {
  const all = read<Project>(PROJECTS_KEY);
  delete all[name];
  write(PROJECTS_KEY, all);
}

export function listTestStrings(): TestString[] {
  return Object.values(read<TestString>(TEST_STRINGS_KEY)).sort((a, b) =>
    a.name.localeCompare(b.name),
  );
}

export function saveTestString(ts: TestString): void {
  const all = read<TestString>(TEST_STRINGS_KEY);
  all[ts.name] = ts;
  write(TEST_STRINGS_KEY, all);
}

export function deleteTestString(name: string): void {
  const all = read<TestString>(TEST_STRINGS_KEY);
  delete all[name];
  write(TEST_STRINGS_KEY, all);
}
