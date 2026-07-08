import React from "react";

export function AppIcon({ label, icon, onOpen }: { label: string; icon: React.ReactNode; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen} onDoubleClick={onOpen}>
      {icon}
      <span>{label}</span>
    </button>
  );
}
