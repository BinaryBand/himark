// Persistence layer — projects and test strings are saved to localStorage
// ("memory") keyed by name, so they survive reloads and can be re-loaded.

import type { Project, TestTab, TestString } from "./types";

const PROJECTS_KEY = "himark.projects";
const TEST_STRINGS_KEY = "himark.testStrings";
const TABS_KEY = "himark.tabs";

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

// A named-entry store keyed by `name`: list (sorted), upsert, and remove. Both
// projects and test strings are exactly this, so they share one implementation.
function listNamed<T extends { name: string }>(key: string): T[] {
  return Object.values(read<T>(key)).sort((a, b) => a.name.localeCompare(b.name));
}

function saveNamed<T extends { name: string }>(key: string, item: T): void {
  const all = read<T>(key);
  all[item.name] = item;
  write(key, all);
}

function deleteNamed(key: string, name: string): void {
  const all = read<unknown>(key);
  delete all[name];
  write(key, all);
}

export const listProjects = () => listNamed<Project>(PROJECTS_KEY);
export const saveProject = (project: Project) => saveNamed(PROJECTS_KEY, project);
export const deleteProject = (name: string) => deleteNamed(PROJECTS_KEY, name);

export const listTestStrings = () => listNamed<TestString>(TEST_STRINGS_KEY);
export const saveTestString = (ts: TestString) => saveNamed(TEST_STRINGS_KEY, ts);
export const deleteTestString = (name: string) => deleteNamed(TEST_STRINGS_KEY, name);

// The open tabs persist as a whole (the working set), so a reload restores the
// exact tabs and which one was active.
export function loadTabs(): { tabs: TestTab[]; activeId: string } | null {
  try {
    const raw = localStorage.getItem(TABS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { tabs: TestTab[]; activeId: string };
    return parsed.tabs?.length ? parsed : null;
  } catch {
    return null;
  }
}

export function saveTabs(tabs: TestTab[], activeId: string): void {
  localStorage.setItem(TABS_KEY, JSON.stringify({ tabs, activeId }));
}
