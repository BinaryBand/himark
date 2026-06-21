import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import ListSubheader from "@mui/material/ListSubheader";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import { useState } from "react";

// A dropdown that lists saved (user) and default entries to load, with optional
// "save as" and per-saved-item delete. Both the project menu (expressions) and
// the test-string load menu are this same shape, so they share it.
interface Props<T extends { name: string }> {
  anchorEl: HTMLElement | null;
  onClose: () => void;
  saved: T[];
  defaults: T[];
  defaultsLabel: string;
  onPick: (item: T) => void;
  onDelete?: (name: string) => void;
  saveAs?: { initial: string; onSave: (name: string) => void };
}

const MONO = { fontFamily: "var(--mono)" };

export function SavedItemsMenu<T extends { name: string }>({
  anchorEl,
  onClose,
  saved,
  defaults,
  defaultsLabel,
  onPick,
  onDelete,
  saveAs,
}: Props<T>) {
  const pick = (item: T) => {
    onPick(item);
    onClose();
  };

  return (
    <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={onClose}>
      {saveAs && <SaveAsRow initial={saveAs.initial} onSave={saveAs.onSave} onClose={onClose} />}

      {saved.length > 0 && <ListSubheader>Saved</ListSubheader>}
      {saved.map((item) => (
        <MenuItem key={`s-${item.name}`} onClick={() => pick(item)}>
          <Box sx={{ flex: 1, ...MONO }}>{item.name}</Box>
          {onDelete && (
            <IconButton
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(item.name);
              }}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          )}
        </MenuItem>
      ))}

      {saved.length > 0 && <Divider />}
      <ListSubheader>{defaultsLabel}</ListSubheader>
      {defaults.map((item) => (
        <MenuItem key={`d-${item.name}`} sx={MONO} onClick={() => pick(item)}>
          {item.name}
        </MenuItem>
      ))}
    </Menu>
  );
}

function SaveAsRow({
  initial,
  onSave,
  onClose,
}: {
  initial: string;
  onSave: (name: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(initial);
  return (
    <Box sx={{ px: 2, py: 1, display: "flex", gap: 1 }}>
      <TextField
        size="small"
        label="Save as"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.stopPropagation()}
      />
      <Button
        variant="contained"
        disabled={!name.trim()}
        onClick={() => {
          onSave(name.trim());
          onClose();
        }}
      >
        Save
      </Button>
    </Box>
  );
}
