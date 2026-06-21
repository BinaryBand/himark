import { useEffect, useMemo, useState } from "react";
import { defaultTestStrings } from "../defaults";
import * as store from "../storage";
import { newId, type TestTab } from "../types";

const blank = (): TestTab => ({ id: newId(), name: "untitled", text: "" });

// Owns the open test-string tabs: their state, the load-on-mount / save-on-change
// persistence, and the add/close/rename/edit operations. Keeping it here (rather
// than spread through the App component) makes the tab lifecycle one unit.
export function useTabs() {
  const seed = useMemo(() => {
    const saved = store.loadTabs();
    if (saved) return saved;
    const first = defaultTestStrings[0];
    const tab: TestTab = {
      id: newId(),
      name: first?.name ?? "scratch",
      text: first?.text ?? "",
    };
    return { tabs: [tab], activeId: tab.id };
  }, []);

  const [tabs, setTabs] = useState<TestTab[]>(seed.tabs);
  const [activeId, setActiveId] = useState(seed.activeId);

  // Persist the whole working set whenever it changes.
  useEffect(() => store.saveTabs(tabs, activeId), [tabs, activeId]);

  const activeTab = tabs.find((t) => t.id === activeId) ?? tabs[0];

  const setActiveText = (text: string) =>
    setTabs((ts) => ts.map((t) => (t.id === activeId ? { ...t, text } : t)));

  const addTab = (tab: TestTab = blank()) => {
    setTabs((ts) => [...ts, tab]);
    setActiveId(tab.id);
  };

  const closeTab = (id: string) => {
    const remaining = tabs.filter((t) => t.id !== id);
    if (remaining.length === 0) {
      addTab(); // never leave zero tabs
      return;
    }
    setTabs(remaining);
    if (id === activeId) setActiveId(remaining[remaining.length - 1].id);
  };

  const renameTab = (id: string, name: string) =>
    setTabs((ts) => ts.map((t) => (t.id === id ? { ...t, name } : t)));

  return {
    tabs,
    activeId,
    activeTab,
    setActiveId,
    setActiveText,
    addTab,
    closeTab,
    renameTab,
  };
}
