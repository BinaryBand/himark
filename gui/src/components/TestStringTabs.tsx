import AddIcon from "@mui/icons-material/Add";
import CloseIcon from "@mui/icons-material/Close";
import LibraryBooksIcon from "@mui/icons-material/LibraryBooks";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import InputBase from "@mui/material/InputBase";
import ListSubheader from "@mui/material/ListSubheader";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Tooltip from "@mui/material/Tooltip";
import { useState } from "react";
import type { TestString, TestTab } from "../types";

interface Props {
  tabs: TestTab[];
  activeId: string;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onClose: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onLoad: (ts: TestString) => void;
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
        <IconButton size="small" onClick={onAdd} sx={{ mx: 0.5 }}>
          <AddIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title="Load a saved or default test string">
        <IconButton
          size="small"
          onClick={(e) => setMenuAnchor(e.currentTarget)}
          sx={{ mr: 0.5 }}
        >
          <LibraryBooksIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={() => setMenuAnchor(null)}>
        {savedTests.length > 0 && <ListSubheader>Saved</ListSubheader>}
        {savedTests.map((t) => (
          <MenuItem
            key={`s-${t.name}`}
            onClick={() => {
              onLoad(t);
              setMenuAnchor(null);
            }}
          >
            {t.name}
          </MenuItem>
        ))}
        <ListSubheader>Demo resources</ListSubheader>
        {defaultTestStrings.map((t) => (
          <MenuItem
            key={`d-${t.name}`}
            onClick={() => {
              onLoad(t);
              setMenuAnchor(null);
            }}
          >
            {t.name}
          </MenuItem>
        ))}
      </Menu>
    </Box>
  );
}
