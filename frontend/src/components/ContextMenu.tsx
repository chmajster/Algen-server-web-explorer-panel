import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { WebNAS } from "../app/shell/WebNASShell";

export type ContextMenuItem = {
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
  danger?: boolean;
  separator?: boolean;
  checked?: boolean;
  children?: ContextMenuItem[] | (() => ContextMenuItem[]);
  action: () => void;
};

/**
 * Compatibility adapter for legacy callers. Rendering is delegated to the
 * single SystemContextMenuHost owned by WebNAS Shell.
 */
export function ContextMenu({ x, y, items, onClose, className = "" }: {
  x: number;
  y: number;
  items: ContextMenuItem[];
  onClose: () => void;
  className?: string;
  portalTarget?: Element | null;
}) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const id = WebNAS.contextMenu.open({
      x,
      y,
      className,
      source: className || "legacy-context-menu",
      items,
      onClose: () => closeRef.current(),
    });
    return () => WebNAS.contextMenu.close(id);
  }, [x, y, items, className]);

  return null;
}
