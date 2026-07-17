import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export type ContextMenuItem = { label: string; icon?: React.ReactNode; disabled?: boolean; danger?: boolean; separator?: boolean; action: () => void };

export function ContextMenu({ x, y, items, onClose, className = "", portalTarget }: { x: number; y: number; items: ContextMenuItem[]; onClose: () => void; className?: string; portalTarget?: Element | null }) {
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ x, y });
  // Keep menus outside window and scroll containers. A fixed element can still
  // become relative to an animated/transformed ancestor and expand its scroll
  // area, which made application contents jump when a context menu was opened.
  const desktopRoot = portalTarget?.closest(".desktop") ?? document.querySelector(".desktop") ?? document.body;
  useLayoutEffect(() => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    setPosition({ x: Math.max(8, Math.min(x, window.innerWidth - rect.width - 8)), y: Math.max(8, Math.min(y, window.innerHeight - rect.height - 8)) });
  }, [x, y, items]);
  useEffect(() => {
    function close(event: MouseEvent) { if (!ref.current?.contains(event.target as Node)) onClose(); }
    function keydown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key) || !ref.current) return;
      event.preventDefault();
      const buttons = [...ref.current.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
      if (!buttons.length) return;
      const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : event.key === "ArrowDown" ? (current + 1) % buttons.length : (current - 1 + buttons.length) % buttons.length;
      buttons[next].focus({ preventScroll: true });
    }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", keydown);
    ref.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus({ preventScroll: true });
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", keydown); };
  }, [onClose]);
  const menu = <div ref={ref} className={`context-menu ${className}`.trim()} style={{ left: position.x, top: position.y }} role="menu" onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); }}>
    {items.map((item, index) => <div key={`${item.label}-${index}`} className={item.separator ? "context-separator" : undefined}><button role="menuitem" className={item.danger ? "danger" : ""} disabled={item.disabled} onClick={() => { item.action(); onClose(); }}>{item.icon}{item.label}</button></div>)}
  </div>;
  return createPortal(menu, desktopRoot);
}
