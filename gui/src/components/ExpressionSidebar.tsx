import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import ListSubheader from "@mui/material/ListSubheader";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useState } from "react";
import type { Expression, Project } from "../types";

const MONO = '"SFMono-Regular", Menlo, Consolas, monospace';

interface Props {
  expressions: Expression[];
  projectName: string;
  savedProjects: Project[];
  defaultProjects: Project[];
  onChange: (id: string, patch: Partial<Expression>) => void;
  onAdd: () => void;
  onRemove: (id: string) => void;
  onSaveProject: (name: string) => void;
  onLoadProject: (project: Project) => void;
  onDeleteProject: (name: string) => void;
}

export function ExpressionSidebar({
  expressions,
  projectName,
  savedProjects,
  defaultProjects,
  onChange,
  onAdd,
  onRemove,
  onSaveProject,
  onLoadProject,
  onDeleteProject,
}: Props) {
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Box
        sx={{
          px: 2,
          py: 1.25,
          display: "flex",
          alignItems: "center",
          gap: 1,
          borderBottom: 1,
          borderColor: "divider",
        }}
      >
        <Typography
          variant="overline"
          sx={{ flex: 1, color: "text.secondary", lineHeight: 1.4 }}
          noWrap
        >
          Expressions · {projectName}
        </Typography>
        <Tooltip title="Projects">
          <IconButton size="small" onClick={(e) => setMenuAnchor(e.currentTarget)}>
            <FolderOpenIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>

      <Box sx={{ flex: 1, overflowY: "auto", p: 1.5 }}>
        <Stack spacing={1.5}>
          {expressions.map((e) => (
            <Box key={e.id} sx={{ display: "flex", alignItems: "flex-start", gap: 0.5 }}>
              <Checkbox
                size="small"
                checked={e.enabled}
                onChange={(ev) => onChange(e.id, { enabled: ev.target.checked })}
                sx={{ mt: 0.5 }}
              />
              <TextField
                value={e.text}
                onChange={(ev) => onChange(e.id, { text: ev.target.value })}
                placeholder="HMK expression…"
                multiline
                maxRows={8}
                size="small"
                fullWidth
                slotProps={{ input: { sx: { fontFamily: MONO, fontSize: 13 } } }}
                sx={{ opacity: e.enabled ? 1 : 0.5 }}
              />
              <Tooltip title="Remove">
                <IconButton size="small" onClick={() => onRemove(e.id)} sx={{ mt: 0.5 }}>
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>
          ))}
        </Stack>
      </Box>

      <Box sx={{ p: 1.5, borderTop: 1, borderColor: "divider" }}>
        <Button fullWidth startIcon={<AddIcon />} onClick={onAdd} variant="outlined">
          Add expression
        </Button>
      </Box>

      <ProjectMenu
        anchorEl={menuAnchor}
        onClose={() => setMenuAnchor(null)}
        projectName={projectName}
        savedProjects={savedProjects}
        defaultProjects={defaultProjects}
        onSaveProject={onSaveProject}
        onLoadProject={onLoadProject}
        onDeleteProject={onDeleteProject}
      />
    </Box>
  );
}

interface MenuProps {
  anchorEl: HTMLElement | null;
  onClose: () => void;
  projectName: string;
  savedProjects: Project[];
  defaultProjects: Project[];
  onSaveProject: (name: string) => void;
  onLoadProject: (project: Project) => void;
  onDeleteProject: (name: string) => void;
}

function ProjectMenu({
  anchorEl,
  onClose,
  projectName,
  savedProjects,
  defaultProjects,
  onSaveProject,
  onLoadProject,
  onDeleteProject,
}: MenuProps) {
  const [name, setName] = useState(projectName);

  return (
    <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={onClose}>
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
            onSaveProject(name.trim());
            onClose();
          }}
        >
          Save
        </Button>
      </Box>

      {savedProjects.length > 0 && <ListSubheader>Saved</ListSubheader>}
      {savedProjects.map((p) => (
        <MenuItem
          key={`s-${p.name}`}
          onClick={() => {
            onLoadProject(p);
            onClose();
          }}
        >
          <Box sx={{ flex: 1, fontFamily: MONO }}>{p.name}</Box>
          <IconButton
            size="small"
            onClick={(ev) => {
              ev.stopPropagation();
              onDeleteProject(p.name);
            }}
          >
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        </MenuItem>
      ))}

      <Divider />
      <ListSubheader>Default scripts</ListSubheader>
      {defaultProjects.map((p) => (
        <MenuItem
          key={`d-${p.name}`}
          sx={{ fontFamily: MONO }}
          onClick={() => {
            onLoadProject(p);
            onClose();
          }}
        >
          {p.name}
        </MenuItem>
      ))}
    </Menu>
  );
}
