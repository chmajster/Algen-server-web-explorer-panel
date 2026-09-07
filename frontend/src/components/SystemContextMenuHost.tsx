import { Check, ChevronRight } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { WebNAS } from "../app/shell/WebNASShell";
import type { ManagedContextMenuItem, ManagedContextMenuRequest } from "../app/shell/ContextMenuManager";
import "./system-context-menu.css";

function resolvedChildren(item: ManagedContextMenuItem): ManagedContextMenuItem[] {
  if (!item.children) return [];
  return typeof item.children === "function" ? item.children() : item.children;
}

export function SystemContextMenuHost() {
  const [request, setRequest] = useState<ManagedContextMenuRequest | null>(() => WebNAS.contextMenu.getCurrent());
  const [submenu, setSubmenu] = useState<{ parent: ManagedContextMenuItem; items: ManagedContextMenuItem[] } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ x: 8, y: 8 });

  useEffect(() => WebNAS.contextMenu.subscribe((next) => {
    setRequest(next);
    setSubmenu(null);
  }), []);

  useLayoutEffect(() => {
    if (!request) return;
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    setPosition({
      x: Math.max(8, Math.min(request.x, window.innerWidth - rect.width - 8)),
      y: Math.max(8, Math.min(request.y, window.innerHeight - rect.height - 8)),
    });
  }, [request, submenu]);

  useEffect(() => {
    if (!request) return;
    const closeOutside = (event: MouseEvent | PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) WebNAS.contextMenu.close(request.id);
    };
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (submenu) setSubmenu(null); else WebNAS.contextMenu.close(request.id);
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key) || !ref.current) return;
      event.preventDefault();
      const buttons = [...ref.current.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
      if (!buttons.length) return;
      const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const index = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : event.key === "ArrowDown" ? (current + 1) % buttons.length : (current - 1 + buttons.length) % buttons.length;
      buttons[index]?.focus({ preventScroll: true });
    };
    document.addEventListener("pointerdown", closeOutside, true);
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("pointerdown", closeOutside, true);
      document.removeEventListener("keydown", keydown);
    };
  }, [request, submenu]);

  const items = useMemo(() => submenu?.items ?? request?.items ?? [], [request, submenu]);
  if (!request) return null;

  const mobile = WebNAS.device.isMobile;
  const runItem = (item: ManagedContextMenuItem) => {
    const children = resolvedChildren(item);
    if (children.length) {
      setSubmenu({ parent: item, items: children });
      return;
    }
    if (item.disabled) return;
    try { item.action?.(); } finally { WebNAS.contextMenu.close(request.id); }
  };

  return <div
    ref={ref}
    className={`context-menu system-context-menu ${mobile ? "system-context-menu-mobile" : ""} ${request.className || ""}`.trim()}
    style={mobile ? undefined : { left: position.x, top: position.y }}
    role="menu"
    aria-label={request.ariaLabel}
    data-shell-layer="context-menu"
    onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); }}
  >
    {submenu && <button type="button" className="system-context-back" onClick={() => setSubmenu(null)}>‹ {submenu.parent.label}</button>}
    {items.map((item, index) => {
      const children = resolvedChildren(item);
      return <div key={item.id || `${item.label}-${index}`} className={item.separator ? "context-separator" : undefined}>
        <button
          type="button"
          role="menuitem"
          className={item.danger ? "danger" : ""}
          disabled={item.disabled}
          aria-checked={item.checked}
          onMouseEnter={() => { if (!mobile && children.length) setSubmenu({ parent: item, items: children }); }}
          onClick={() => runItem(item)}
        >
          <span className="system-context-icon">{item.checked ? <Check /> : item.icon}</span>
          <span className="system-context-label">{item.label}</span>
          {children.length > 0 && <ChevronRight className="system-context-chevron" />}
        </button>
      </div>;
    })}
  </div>;
}
