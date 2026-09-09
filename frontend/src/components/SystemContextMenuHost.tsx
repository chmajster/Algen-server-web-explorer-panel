import { Check, ChevronRight } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { WebNAS } from "../app/shell/WebNASShell";
import type { ManagedContextMenuItem, ManagedContextMenuRequest } from "../app/shell/ContextMenuManager";
import "./system-context-menu.css";

const VIEWPORT_MARGIN = 8;

function resolvedChildren(item: ManagedContextMenuItem): ManagedContextMenuItem[] {
  if (!item.children) return [];
  return typeof item.children === "function" ? item.children() : item.children;
}

function visibleViewportBounds() {
  const viewport = window.visualViewport;
  if (viewport) {
    return {
      left: viewport.offsetLeft,
      top: viewport.offsetTop,
      right: viewport.offsetLeft + viewport.width,
      bottom: viewport.offsetTop + viewport.height,
    };
  }
  const width = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
  const height = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
  return { left: 0, top: 0, right: width, bottom: height };
}

export function SystemContextMenuHost() {
  const [request, setRequest] = useState<ManagedContextMenuRequest | null>(() => WebNAS.contextMenu.getCurrent());
  const [submenu, setSubmenu] = useState<{ parent: ManagedContextMenuItem; items: ManagedContextMenuItem[] } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ x: VIEWPORT_MARGIN, y: VIEWPORT_MARGIN });
  const mobile = WebNAS.device.isMobile;

  useEffect(() => WebNAS.contextMenu.subscribe((next) => {
    setRequest(next);
    setSubmenu(null);
  }), []);

  useLayoutEffect(() => {
    if (!request) return;
    const currentRequest = request;

    function updatePosition() {
      if (mobile) return;
      const rect = ref.current?.getBoundingClientRect();
      if (!rect) return;
      const viewport = visibleViewportBounds();
      const minX = viewport.left + VIEWPORT_MARGIN;
      const minY = viewport.top + VIEWPORT_MARGIN;
      const maxX = Math.max(minX, viewport.right - rect.width - VIEWPORT_MARGIN);
      const maxY = Math.max(minY, viewport.bottom - rect.height - VIEWPORT_MARGIN);
      const next = {
        x: Math.max(minX, Math.min(currentRequest.x, maxX)),
        y: Math.max(minY, Math.min(currentRequest.y, maxY)),
      };
      setPosition((current) => current.x === next.x && current.y === next.y ? current : next);
    }

    updatePosition();
    ref.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus({ preventScroll: true });

    if (mobile) return;
    const visualViewport = window.visualViewport;
    window.addEventListener("resize", updatePosition);
    window.addEventListener("orientationchange", updatePosition);
    visualViewport?.addEventListener("resize", updatePosition);
    visualViewport?.addEventListener("scroll", updatePosition);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("orientationchange", updatePosition);
      visualViewport?.removeEventListener("resize", updatePosition);
      visualViewport?.removeEventListener("scroll", updatePosition);
    };
  }, [request, submenu, mobile]);

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

  const runItem = (item: ManagedContextMenuItem) => {
    const children = resolvedChildren(item);
    if (children.length) {
      setSubmenu({ parent: item, items: children });
      return;
    }
    if (item.disabled) return;
    try { item.action?.(); } finally { WebNAS.contextMenu.close(request.id); }
  };

  const menu = <div
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

  const menuRoot = request.portalTarget?.closest(".desktop") ?? document.querySelector(".desktop") ?? request.portalTarget ?? document.body;
  return createPortal(menu, menuRoot);
}
