import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useState } from "react";
import type { Expression, HighlightSpan, Project } from "../types";
import { HighlightedExpression } from "./HighlightedExpression";
import { SavedItemsMenu } from "./SavedItemsMenu";

interface Props {
  expressions: Expression[];
  highlights: Record<string, HighlightSpan[]>;
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
  highlights,
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
              <HighlightedExpression
                value={e.text}
                spans={highlights[e.id] ?? []}
                enabled={e.enabled}
                onChange={(text) => onChange(e.id, { text })}
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

      <SavedItemsMenu
        anchorEl={menuAnchor}
        onClose={() => setMenuAnchor(null)}
        saved={savedProjects}
        defaults={defaultProjects}
        defaultsLabel="Default scripts"
        onPick={onLoadProject}
        onDelete={onDeleteProject}
        saveAs={{ initial: projectName, onSave: onSaveProject }}
      />
    </Box>
  );
}
