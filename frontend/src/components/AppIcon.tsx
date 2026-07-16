import React from "react";

export function AppIcon({ label, icon, selected = false, onSelect, onOpen }: { label: string; icon: React.ReactNode; selected?: boolean; onSelect?: () => void; onOpen: () => void }) {
  return (
    <button type="button" className={selected ? "selected" : ""} aria-pressed={selected} onClick={onSelect || onOpen} onDoubleClick={onOpen} onKeyDown={(event) => { if (event.key === "Enter") onOpen(); }}>
      {icon}
      <span>{label}</span>
    </button>
  );
}
