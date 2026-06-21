import AddIcon from "@mui/icons-material/Add";
import CloseIcon from "@mui/icons-material/Close";
import LibraryBooksIcon from "@mui/icons-material/LibraryBooks";
import SaveOutlinedIcon from "@mui/icons-material/SaveOutlined";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import InputBase from "@mui/material/InputBase";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Tooltip from "@mui/material/Tooltip";
import { useState } from "react";
import type { TestString, TestTab } from "../types";
import { SavedItemsMenu } from "./SavedItemsMenu";

interface Props {
  tabs: TestTab[];
  activeId: string;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onClose: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onLoad: (ts: TestString) => void;
  onSaveActive: () => void;
  onDeleteSaved: (name: string) => void;
  defaultTestStrings: TestString[];
  savedTests: TestString[];
}

export function TestStringTabs({
  tabs,
  activeId,
  onSelect,
  onAdd,
  onClose,
  onRename,
  onLoad,
  onSaveActive,
  onDeleteSaved,
  defaultTestStrings,
  savedTests,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);

  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        borderBottom: 1,
        borderColor: "divider",
        bgcolor: "background.paper",
      }}
    >
      <Tabs
        value={activeId}
        onChange={(_, v) => onSelect(v)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{ flex: 1, minHeight: 44 }}
      >
        {tabs.map((t) => (
          <Tab
            key={t.id}
            value={t.id}
            sx={{ minHeight: 44, textTransform: "none", pr: 1 }}
            label={
              <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                {editingId === t.id ? (
                  <InputBase
                    autoFocus
                    defaultValue={t.name}
                    onClick={(e) => e.stopPropagation()}
                    onBlur={(e) => {
                      onRename(t.id, e.target.value.trim() || t.name);
                      setEditingId(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    sx={{ fontSize: 13, width: 110 }}
                  />
                ) : (
                  <Box
                    component="span"
                    onDoubleClick={(e) => {
                      e.stopPropagation();
                      setEditingId(t.id);
                    }}
                    title="Double-click to rename"
                  >
                    {t.name}
                  </Box>
                )}
                <IconButton
                  component="span"
                  size="small"
                  sx={{ p: 0.25 }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onClose(t.id);
                  }}
                >
                  <CloseIcon sx={{ fontSize: 14 }} />
                </IconButton>
              </Box>
            }
          />
        ))}
      </Tabs>

      <Tooltip title="New test string">
        <IconButton size="small" onClick={onAdd} sx={{ ml: 0.5 }}>
          <AddIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title="Save this test string">
        <IconButton size="small" onClick={onSaveActive}>
          <SaveOutlinedIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title="Load a saved or default test string">
        <IconButton size="small" onClick={(e) => setMenuAnchor(e.currentTarget)} sx={{ mr: 0.5 }}>
          <LibraryBooksIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      <SavedItemsMenu
        anchorEl={menuAnchor}
        onClose={() => setMenuAnchor(null)}
        saved={savedTests}
        defaults={defaultTestStrings}
        defaultsLabel="Demo resources"
        onPick={onLoad}
        onDelete={onDeleteSaved}
      />
    </Box>
  );
}
