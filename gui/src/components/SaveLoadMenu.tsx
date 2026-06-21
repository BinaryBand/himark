import { useEffect, useRef, useState } from "react";

interface Props {
  label: string;
  items: { name: string; deletable?: boolean }[];
  onSave: (name: string) => void;
  onLoad: (name: string) => void;
  onDelete: (name: string) => void;
  defaultName?: string;
}

// A small dropdown that saves the current thing under a name and lists saved +
// default entries to load or delete. Used for both projects and test strings.
export function SaveLoadMenu({
  label,
  items,
  onSave,
  onLoad,
  onDelete,
  defaultName,
}: Props) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(defaultName ?? "");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => setName(defaultName ?? ""), [defaultName]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div className="menu" ref={ref}>
      <button className="menu-trigger" onClick={() => setOpen((o) => !o)}>
        {label} ▾
      </button>
      {open && (
        <div className="menu-panel">
          <div className="menu-save">
            <input
              value={name}
              placeholder="name…"
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && name.trim()) {
                  onSave(name.trim());
                  setOpen(false);
                }
              }}
            />
            <button
              disabled={!name.trim()}
              onClick={() => {
                onSave(name.trim());
                setOpen(false);
              }}
            >
              Save
            </button>
          </div>
          <div className="menu-list">
            {items.length === 0 && <div className="menu-empty">nothing saved</div>}
            {items.map((it) => (
              <div className="menu-item" key={it.name}>
                <button
                  className="menu-item-name"
                  onClick={() => {
                    onLoad(it.name);
                    setOpen(false);
                  }}
                >
                  {it.name}
                </button>
                {it.deletable !== false && (
                  <button
                    className="menu-item-del"
                    title="delete"
                    onClick={() => onDelete(it.name)}
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
