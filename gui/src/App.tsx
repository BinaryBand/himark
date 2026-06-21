import MenuIcon from "@mui/icons-material/Menu";
import AppBar from "@mui/material/AppBar";
import Badge from "@mui/material/Badge";
import Box from "@mui/material/Box";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";
import { useEffect, useMemo, useRef, useState } from "react";
import { runEngine } from "./api";
import { ExpressionSidebar } from "./components/ExpressionSidebar";
import { FindResults } from "./components/FindResults";
import { HighlightedInput } from "./components/HighlightedInput";
import { TestStringTabs } from "./components/TestStringTabs";
import { defaultProjects, defaultTestStrings } from "./defaults";
import * as store from "./storage";
import {
  newId,
  type Expression,
  type Mode,
  type Project,
  type RunResult,
  type TestString,
  type TestTab,
} from "./types";

const SIDEBAR_WIDTH = 320;

function initialTabs(): { tabs: TestTab[]; activeId: string } {
  const saved = store.loadTabs();
  if (saved) return saved;
  const first = defaultTestStrings[0];
  const tab: TestTab = {
    id: newId(),
    name: first?.name ?? "scratch",
    text: first?.text ?? "",
  };
  return { tabs: [tab], activeId: tab.id };
}

export function App() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));
  const [drawerOpen, setDrawerOpen] = useState(false);

  const [mode, setMode] = useState<Mode>("execute");
  const [expressions, setExpressions] = useState<Expression[]>([
    { id: newId(), text: '{@^}{-,*,_}[3..]{@$} => "<hr/>"', enabled: true },
  ]);
  const [projectName, setProjectName] = useState("untitled");

  const seed = useMemo(initialTabs, []);
  const [tabs, setTabs] = useState<TestTab[]>(seed.tabs);
  const [activeId, setActiveId] = useState(seed.activeId);

  const [result, setResult] = useState<RunResult>({});
  const [savedTick, setSavedTick] = useState(0);
  const savedProjects = useMemo(() => store.listProjects(), [savedTick]);
  const savedTests = useMemo(() => store.listTestStrings(), [savedTick]);

  const activeTab = tabs.find((t) => t.id === activeId) ?? tabs[0];
  const target = activeTab?.text ?? "";

  // Persist the open tabs (the working set) on every change.
  useEffect(() => store.saveTabs(tabs, activeId), [tabs, activeId]);

  // Debounced engine run whenever the inputs change.
  const timer = useRef<number>();
  useEffect(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const active = expressions.filter((e) => e.enabled).map((e) => e.text);
      runEngine(mode, active, target).then(setResult);
    }, 200);
    return () => window.clearTimeout(timer.current);
  }, [mode, expressions, target]);

  // ── expressions ───────────────────────────────────────────────────────────
  const updateExpr = (id: string, patch: Partial<Expression>) =>
    setExpressions((xs) => xs.map((e) => (e.id === id ? { ...e, ...patch } : e)));
  const addExpr = () =>
    setExpressions((xs) => [...xs, { id: newId(), text: "{.}", enabled: true }]);
  const removeExpr = (id: string) =>
    setExpressions((xs) => xs.filter((e) => e.id !== id));

  const loadProject = (p: Project) => {
    setExpressions(p.expressions.map((e) => ({ ...e, id: newId() })));
    setProjectName(p.name);
  };

  // ── test-string tabs ──────────────────────────────────────────────────────
  const setActiveText = (text: string) =>
    setTabs((ts) => ts.map((t) => (t.id === activeId ? { ...t, text } : t)));

  const addTab = (tab?: TestTab) => {
    const next = tab ?? { id: newId(), name: "untitled", text: "" };
    setTabs((ts) => [...ts, next]);
    setActiveId(next.id);
  };

  const closeTab = (id: string) =>
    setTabs((ts) => {
      const remaining = ts.filter((t) => t.id !== id);
      if (remaining.length === 0) {
        const fresh = { id: newId(), name: "untitled", text: "" };
        setActiveId(fresh.id);
        return [fresh];
      }
      if (id === activeId) setActiveId(remaining[remaining.length - 1].id);
      return remaining;
    });

  const renameTab = (id: string, name: string) =>
    setTabs((ts) => ts.map((t) => (t.id === id ? { ...t, name } : t)));

  const loadTestString = (ts: TestString) =>
    addTab({ id: newId(), name: ts.name, text: ts.text });

  // ── render helpers ─────────────────────────────────────────────────────────
  const count = result.count ?? 0;
  const matches = result.matches ?? [];

  const sidebar = (
    <ExpressionSidebar
      expressions={expressions}
      projectName={projectName}
      savedProjects={savedProjects}
      defaultProjects={defaultProjects}
      onChange={updateExpr}
      onAdd={addExpr}
      onRemove={removeExpr}
      onSaveProject={(name) => {
        store.saveProject({ name, expressions });
        setProjectName(name);
        setSavedTick((t) => t + 1);
      }}
      onLoadProject={(p) => {
        loadProject(p);
        setDrawerOpen(false);
      }}
      onDeleteProject={(name) => {
        store.deleteProject(name);
        setSavedTick((t) => t + 1);
      }}
    />
  );

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <AppBar position="static" color="default" elevation={0} sx={{ borderBottom: 1, borderColor: "divider" }}>
        <Toolbar variant="dense" sx={{ gap: 2 }}>
          {isMobile && (
            <IconButton edge="start" onClick={() => setDrawerOpen(true)}>
              <MenuIcon />
            </IconButton>
          )}
          <Typography variant="h6" color="primary" sx={{ fontWeight: 600 }} noWrap>
            Himark Tester
          </Typography>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={mode}
            onChange={(_, v: Mode | null) => v && setMode(v)}
          >
            <ToggleButton value="find">Find</ToggleButton>
            <ToggleButton value="execute">Execute</ToggleButton>
          </ToggleButtonGroup>
        </Toolbar>
      </AppBar>

      <Box sx={{ display: "flex", flex: 1, minHeight: 0 }}>
        {isMobile ? (
          <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)}>
            <Box sx={{ width: SIDEBAR_WIDTH, height: "100%" }}>{sidebar}</Box>
          </Drawer>
        ) : (
          <Box
            sx={{
              width: SIDEBAR_WIDTH,
              flexShrink: 0,
              borderRight: 1,
              borderColor: "divider",
              bgcolor: "background.paper",
            }}
          >
            {sidebar}
          </Box>
        )}

        <Box sx={{ display: "flex", flexDirection: "column", flex: 1, minWidth: 0 }}>
          <TestStringTabs
            tabs={tabs}
            activeId={activeId}
            onSelect={setActiveId}
            onAdd={() => addTab()}
            onClose={closeTab}
            onRename={renameTab}
            onLoad={loadTestString}
            defaultTestStrings={defaultTestStrings}
            savedTests={savedTests}
          />

          <Box
            sx={{
              display: "flex",
              flexDirection: { xs: "column", md: "row" },
              flex: 1,
              minHeight: 0,
            }}
          >
            <Panel title="TEST STRING">
              <HighlightedInput
                value={target}
                onChange={setActiveText}
                matches={mode === "find" ? matches : []}
              />
            </Panel>
            <Panel
              title="OUTPUT"
              badge={count}
              sx={{ borderLeft: { md: 1 }, borderColor: { md: "divider" } }}
            >
              <Box sx={{ position: "relative", flex: 1, minHeight: 0, overflow: "auto" }}>
                {result.error ? (
                  <pre className="output-error">{result.error}</pre>
                ) : mode === "execute" ? (
                  <pre className="output-text">{result.output}</pre>
                ) : (
                  <FindResults target={target} matches={matches} />
                )}
              </Box>
            </Panel>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}

function Panel({
  title,
  badge,
  children,
  sx,
}: {
  title: string;
  badge?: number;
  children: React.ReactNode;
  sx?: object;
}) {
  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        minWidth: 0,
        minHeight: { xs: "40vh", md: 0 },
        ...sx,
      }}
    >
      <Box
        sx={{
          px: 2,
          py: 1,
          borderBottom: 1,
          borderColor: "divider",
          display: "flex",
          alignItems: "center",
          gap: 1,
        }}
      >
        <Typography variant="overline" sx={{ color: "text.secondary" }}>
          {title}
        </Typography>
        {badge !== undefined && (
          <Badge badgeContent={badge} color="primary" showZero sx={{ ml: 1 }} />
        )}
      </Box>
      {children}
    </Box>
  );
}
