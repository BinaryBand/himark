import { useEffect, useMemo, useRef, useState } from "react";
import { runEngine } from "./api";
import { HighlightedInput } from "./components/HighlightedInput";
import { SaveLoadMenu } from "./components/SaveLoadMenu";
import { defaultProjects, defaultTestStrings } from "./defaults";
import * as store from "./storage";
import {
  newId,
  type Expression,
  type Mode,
  type Project,
  type RunResult,
  type TestString,
} from "./types";

const STARTER_TARGET = defaultTestStrings[0]?.text ?? "type a test string here…\n";

export function App() {
  const [mode, setMode] = useState<Mode>("execute");
  const [expressions, setExpressions] = useState<Expression[]>([
    { id: newId(), text: '{@^}{-,*,_}[3..]{@$} => "<hr/>"', enabled: true },
  ]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [projectName, setProjectName] = useState("untitled");
  const [target, setTarget] = useState(STARTER_TARGET);
  const [testName, setTestName] = useState(defaultTestStrings[0]?.name ?? "scratch");
  const [result, setResult] = useState<RunResult>({});

  // Re-list saved items after every save/delete so the menus stay current.
  const [savedTick, setSavedTick] = useState(0);
  const savedProjects = useMemo(() => store.listProjects(), [savedTick]);
  const savedTests = useMemo(() => store.listTestStrings(), [savedTick]);

  const selected = expressions.find((e) => e.id === selectedId) ?? expressions[0];

  // Debounced run whenever the inputs change.
  const timer = useRef<number>();
  useEffect(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const active = expressions.filter((e) => e.enabled).map((e) => e.text);
      runEngine(mode, active, target).then(setResult);
    }, 200);
    return () => window.clearTimeout(timer.current);
  }, [mode, expressions, target]);

  // ── expression list ops ──────────────────────────────────────────────────
  const updateExpr = (id: string, patch: Partial<Expression>) =>
    setExpressions((xs) => xs.map((e) => (e.id === id ? { ...e, ...patch } : e)));
  const addExpr = () => {
    const e = { id: newId(), text: "{.}", enabled: true };
    setExpressions((xs) => [...xs, e]);
    setSelectedId(e.id);
  };
  const removeExpr = (id: string) =>
    setExpressions((xs) => xs.filter((e) => e.id !== id));

  // ── project + test string load/save ──────────────────────────────────────
  const loadProject = (p: Project) => {
    const exprs = p.expressions.map((e) => ({ ...e, id: newId() }));
    setExpressions(exprs);
    setSelectedId(exprs[0]?.id ?? "");
    setProjectName(p.name);
  };
  const loadTest = (t: TestString) => {
    setTarget(t.text);
    setTestName(t.name);
  };

  const projectItems = [
    ...defaultProjects.map((p) => ({ name: p.name, deletable: false })),
    ...savedProjects.map((p) => ({ name: p.name, deletable: true })),
  ];
  const testItems = [
    ...defaultTestStrings.map((t) => ({ name: t.name, deletable: false })),
    ...savedTests.map((t) => ({ name: t.name, deletable: true })),
  ];

  const matches = result.matches ?? [];
  const count = result.count ?? 0;

  return (
    <div className="app">
      <header className="topbar">
        <h1 className="brand">Himark Tester</h1>
        <div className="modes">
          {(["find", "execute"] as Mode[]).map((m) => (
            <button
              key={m}
              className={`mode-btn ${mode === m ? "active" : ""}`}
              onClick={() => setMode(m)}
            >
              {m[0].toUpperCase() + m.slice(1)}
            </button>
          ))}
        </div>
        <div className="topbar-menus">
          <SaveLoadMenu
            label={`Project: ${projectName}`}
            items={projectItems}
            onSave={(name) => {
              store.saveProject({ name, expressions });
              setProjectName(name);
              setSavedTick((t) => t + 1);
            }}
            onLoad={(name) => {
              const p =
                savedProjects.find((x) => x.name === name) ??
                defaultProjects.find((x) => x.name === name);
              if (p) loadProject(p);
            }}
            onDelete={(name) => {
              store.deleteProject(name);
              setSavedTick((t) => t + 1);
            }}
            defaultName={projectName}
          />
          <SaveLoadMenu
            label={`Test: ${testName}`}
            items={testItems}
            onSave={(name) => {
              store.saveTestString({ name, text: target });
              setTestName(name);
              setSavedTick((t) => t + 1);
            }}
            onLoad={(name) => {
              const t =
                savedTests.find((x) => x.name === name) ??
                defaultTestStrings.find((x) => x.name === name);
              if (t) loadTest(t);
            }}
            onDelete={(name) => {
              store.deleteTestString(name);
              setSavedTick((t) => t + 1);
            }}
            defaultName={testName}
          />
        </div>
      </header>

      <main className="panes">
        <section className="pane">
          <div className="pane-head">TEST STRING</div>
          <HighlightedInput
            value={target}
            onChange={setTarget}
            matches={mode === "find" ? matches : []}
          />
        </section>

        <section className="pane">
          <div className="pane-head">
            OUTPUT
            <span className="badge">{count}</span>
          </div>
          <div className="output">
            {result.error ? (
              <pre className="output-error">{result.error}</pre>
            ) : mode === "execute" ? (
              <pre className="output-text">{result.output}</pre>
            ) : (
              <HighlightedInput value={target} onChange={() => {}} matches={matches} />
            )}
          </div>
        </section>
      </main>

      <footer className="exprbar">
        <div className="tabs">
          {expressions.map((e) => (
            <div
              key={e.id}
              className={`tab ${selected?.id === e.id ? "active" : ""} ${
                e.enabled ? "" : "off"
              }`}
              onClick={() => setSelectedId(e.id)}
            >
              <input
                type="checkbox"
                checked={e.enabled}
                title="toggle"
                onClick={(ev) => ev.stopPropagation()}
                onChange={(ev) => updateExpr(e.id, { enabled: ev.target.checked })}
              />
              <span className="tab-text">{e.text || "(empty)"}</span>
              <button
                className="tab-close"
                title="remove"
                onClick={(ev) => {
                  ev.stopPropagation();
                  removeExpr(e.id);
                }}
              >
                ×
              </button>
            </div>
          ))}
          <button className="tab-add" title="add expression" onClick={addExpr}>
            +
          </button>
        </div>
        <textarea
          className="expr-editor"
          spellCheck={false}
          placeholder="HMK expression…"
          value={selected?.text ?? ""}
          onChange={(e) => selected && updateExpr(selected.id, { text: e.target.value })}
        />
      </footer>
    </div>
  );
}
