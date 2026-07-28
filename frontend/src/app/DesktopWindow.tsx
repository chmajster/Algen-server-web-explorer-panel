/* eslint-disable react-hooks/refs -- pointer gesture refs are only mutated by pointer event handlers */
import { useEffect, useRef, useState } from "react";
import { Maximize2, Minimize2, Share2, X } from "lucide-react";
import { appById } from "./catalog";
import { clampRect, DESKTOP_TOP, workspaceRect, type ViewportMetrics } from "./windowState";
import type { Translate, WindowInstance, WindowRect } from "./types";

type Edge = "n" | "e" | "s" | "w" | "ne" | "nw" | "se" | "sw";
type Gesture = { mode: "move" | "resize"; edge?: Edge; startX: number; startY: number; rect: WindowRect; offsetX: number; offsetY: number };

const moduleTitles: Record<string, string> = { samba: "Samba", docker: "Docker", pihole: "Pi-hole", "adguard-home": "AdGuard Home", postgresql: "PostgreSQL", mariadb: "MariaDB", redis: "Redis", "home-assistant": "Home Assistant", "ansible-controller": "Ansible Automation Controller" };

export function DesktopWindow({ window: item, active, viewport, t, onFocus, onClose, onMinimize, onCommit, onToggleMaximize, children, animationsEnabled = false }: {
  window: WindowInstance;
  active: boolean;
  viewport?: ViewportMetrics;
  t: Translate;
  onFocus: () => void;
  onClose: () => void;
  onMinimize: () => void;
  onCommit: (rect: WindowRect, restoreRect?: WindowRect) => void;
  onToggleMaximize: () => void;
  children: React.ReactNode;
  animationsEnabled?: boolean;
}) {
  const definition = appById[item.app];
  const moduleTitle = item.moduleId === "linux-updates" ? t("managed.linuxUpdatesName") : item.moduleId ? moduleTitles[item.moduleId] : undefined;
  const title = item.app === "module" && moduleTitle ? moduleTitle : t(definition.labelKey);
  const icon = item.app === "module" && item.moduleId === "samba" ? <Share2 /> : definition.icon;
  const [displayRect, setDisplayRect] = useState(item.rect);
  const [minimizing, setMinimizing] = useState(false);
  const gesture = useRef<Gesture | null>(null);
  const maximized = Boolean(item.restoreRect);

  useEffect(() => { if (!gesture.current) setDisplayRect(item.rect); }, [item.rect]);
  useEffect(() => {
    function move(event: PointerEvent) {
      const current = gesture.current;
      if (!current) return;
      if (current.mode === "move") {
        setDisplayRect(clampRect({ ...current.rect, x: event.clientX - current.offsetX, y: event.clientY - current.offsetY }, definition.minWidth, definition.minHeight, viewport));
        return;
      }
      const dx = event.clientX - current.startX;
      const dy = event.clientY - current.startY;
      const edge = current.edge || "se";
      let { x, y, width, height } = current.rect;
      if (edge.includes("e")) width += dx;
      if (edge.includes("s")) height += dy;
      if (edge.includes("w")) { width -= dx; x += dx; }
      if (edge.includes("n")) { height -= dy; y += dy; }
      const minWidth = definition.minWidth || 360;
      const minHeight = definition.minHeight || 280;
      if (width < minWidth) { if (edge.includes("w")) x -= minWidth - width; width = minWidth; }
      if (height < minHeight) { if (edge.includes("n")) y -= minHeight - height; height = minHeight; }
      setDisplayRect(clampRect({ x, y, width, height }, minWidth, minHeight, viewport));
    }
    function up(event: PointerEvent) {
      if (!gesture.current) return;
      gesture.current = null;
      let rect = displayRect;
      let restoreRect: WindowRect | undefined;
      if (event.clientY <= DESKTOP_TOP + 8) { restoreRect = rect; rect = workspaceRect(viewport); }
      else if (event.clientX <= 8) { restoreRect = rect; const work = workspaceRect(viewport); rect = { ...work, width: work.width / 2 }; }
      else if (event.clientX >= window.innerWidth - 8) { restoreRect = rect; const work = workspaceRect(viewport); rect = { ...work, x: work.x + work.width / 2, width: work.width / 2 }; }
      setDisplayRect(rect);
      onCommit(rect, restoreRect);
    }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, [definition.minHeight, definition.minWidth, displayRect, onCommit, viewport]);

  function startMove(event: React.PointerEvent) {
    if ((event.target as HTMLElement).closest("button")) return;
    event.preventDefault();
    onFocus();
    let rect = displayRect;
    let offsetX = event.clientX - rect.x;
    if (maximized) {
      const restored = clampRect(item.restoreRect || { x: 100, y: 80, width: 900, height: 620 }, definition.minWidth, definition.minHeight, viewport);
      const ratio = (event.clientX - rect.x) / rect.width;
      rect = { ...restored, x: event.clientX - restored.width * ratio, y: event.clientY - 20 };
      offsetX = event.clientX - rect.x;
      setDisplayRect(rect);
    }
    gesture.current = { mode: "move", startX: event.clientX, startY: event.clientY, rect, offsetX, offsetY: event.clientY - rect.y };
  }

  function startResize(edge: Edge, event: React.PointerEvent) {
    event.preventDefault();
    event.stopPropagation();
    onFocus();
    gesture.current = { mode: "resize", edge, startX: event.clientX, startY: event.clientY, rect: displayRect, offsetX: 0, offsetY: 0 };
  }

  function minimize() {
    if (!animationsEnabled || window.matchMedia("(prefers-reduced-motion: reduce)").matches) { onMinimize(); return; }
    setMinimizing(true);
    window.setTimeout(onMinimize, 120);
  }

  return <section role="dialog" aria-modal="false" className={`desktop-window ${active ? "active" : "inactive"} ${maximized ? "maximized" : ""} ${minimizing ? "minimizing" : ""}`} style={{ left: displayRect.x, top: displayRect.y, width: displayRect.width, height: displayRect.height, zIndex: item.zIndex }} onPointerDown={onFocus} aria-label={title}>
    <header className="window-titlebar" onPointerDown={startMove} onDoubleClick={() => { gesture.current = null; onToggleMaximize(); }}>
      <span className="window-app-icon">{icon}</span><strong>{title}</strong>
      <div className="window-controls">
        <button type="button" title={t("window.minimize")} aria-label={t("window.minimize")} onClick={minimize}><Minimize2 /></button>
        <button type="button" title={maximized ? t("window.restore") : t("window.maximize")} aria-label={maximized ? t("window.restore") : t("window.maximize")} onClick={onToggleMaximize}><Maximize2 /></button>
        <button className="window-close" type="button" title={t("action.close")} aria-label={t("action.close")} onClick={onClose}><X /></button>
      </div>
    </header>
    <div className="window-content">{children}</div>
    {!maximized && (["n", "e", "s", "w", "ne", "nw", "se", "sw"] as Edge[]).map((edge) => <span key={edge} className={`resize-handle resize-${edge}`} onPointerDown={(event) => startResize(edge, event)} />)}
  </section>;
}
