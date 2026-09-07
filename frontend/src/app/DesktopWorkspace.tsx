import { File, Folder, Globe2, Package, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { UploadControls } from "../features/transfers/useUploadManager";
import { AppIcon } from "../components/AppIcon";
import { WebNAS } from "./shell/WebNASShell";
import { shellPreferencesClient, type ShellDesktopEntry, type ShellPreferences } from "./shell/preferences";
import type { AppId, Translate } from "./types";
import "./desktop-workspace.css";

type AppShortcut = { id: AppId; label: string; icon: React.ReactNode };
type DesktopWorkspaceProps = {
  apps: AppShortcut[];
  modules: Map<string, string>;
  appIds: Set<AppId>;
  moduleIds: Set<string>;
  home: string;
  uploadControls: UploadControls;
  t: Translate;
  openApp: (app: AppId, initialPath?: string, moduleId?: string) => void;
  toggleAppShortcut: (app: AppId) => void;
  toggleModuleShortcut: (moduleId: string) => void;
};

type SelectionRect = { x: number; y: number; width: number; height: number } | null;
const GRID_X = 92;
const GRID_Y = 92;

function snap(value: number, unit: number) { return Math.max(0, Math.round(value / unit) * unit); }
function idFor(kind: string) { return `${kind}:${Date.now()}:${Math.random().toString(36).slice(2, 9)}`; }
function safeUrl(value: string) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}
function intersects(a: DOMRect, b: { left: number; top: number; right: number; bottom: number }) {
  return a.left <= b.right && a.right >= b.left && a.top <= b.bottom && a.bottom >= b.top;
}

export function DesktopWorkspace({ apps, modules, appIds, moduleIds, home, uploadControls, openApp, toggleAppShortcut, toggleModuleShortcut }: DesktopWorkspaceProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [preferences, setPreferences] = useState<ShellPreferences | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectionRect, setSelectionRect] = useState<SelectionRect>(null);
  const selectionOrigin = useRef<{ x: number; y: number } | null>(null);
  const drag = useRef<{ id: string; offsetX: number; offsetY: number } | null>(null);
  const longPress = useRef<number | null>(null);

  useEffect(() => {
    let active = true;
    void shellPreferencesClient.get().then((value) => { if (active) setPreferences(value); }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  const entries = useMemo(() => {
    const current = preferences?.desktop_entries ?? [];
    const byId = new Map(current.map((item) => [item.id, item]));
    let index = 0;
    const generated: ShellDesktopEntry[] = [];
    for (const app of apps.filter((item) => appIds.has(item.id))) {
      const key = `app:${app.id}`;
      generated.push(byId.get(key) ?? { id: key, kind: "app", name: app.label, target: app.id, position: { x: 12, y: 12 + index++ * GRID_Y }, created_at: Date.now() });
    }
    for (const moduleId of moduleIds) {
      if (!modules.has(moduleId)) continue;
      const key = `module:${moduleId}`;
      generated.push(byId.get(key) ?? { id: key, kind: "module", name: modules.get(moduleId) || moduleId, target: moduleId, position: { x: 12, y: 12 + index++ * GRID_Y }, created_at: Date.now() });
    }
    const custom = current.filter((item) => !item.id.startsWith("app:") && !item.id.startsWith("module:"));
    return [...generated, ...custom];
  }, [appIds, apps, moduleIds, modules, preferences]);

  const persistEntries = useCallback((next: ShellDesktopEntry[]) => {
    setPreferences((current) => current ? { ...current, desktop_entries: next } : current);
    void shellPreferencesClient.patch({ desktop_entries: next }).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!preferences) return;
    const stored = preferences.desktop_entries;
    const missing = entries.filter((item) => !stored.some((storedItem) => storedItem.id === item.id));
    if (missing.length) persistEntries([...stored, ...missing]);
  }, [entries, persistEntries, preferences]);

  const entryById = useCallback((id: string) => entries.find((item) => item.id === id), [entries]);

  const openEntry = useCallback((entry: ShellDesktopEntry) => {
    if (entry.kind === "app") openApp(entry.target);
    else if (entry.kind === "module") openApp("module", undefined, entry.target);
    else if (entry.kind === "directory") openApp("files", entry.target);
    else if (entry.kind === "file") openApp("files", entry.target);
    else if (entry.kind === "url") {
      const url = safeUrl(entry.target);
      if (url) window.open(url, "_blank", "noopener,noreferrer");
    }
  }, [openApp]);

  const removeEntries = useCallback((ids: string[]) => {
    for (const id of ids) {
      const item = entryById(id);
      if (!item) continue;
      if (item.kind === "app") toggleAppShortcut(item.target);
      else if (item.kind === "module") toggleModuleShortcut(item.target);
    }
    const removable = new Set(ids.filter((id) => {
      const item = entryById(id);
      return item && !["app", "module"].includes(item.kind);
    }));
    if (removable.size) persistEntries((preferences?.desktop_entries ?? []).filter((item) => !removable.has(item.id) && !removable.has(item.parent_id || "")));
    setSelected(new Set());
  }, [entryById, persistEntries, preferences, toggleAppShortcut, toggleModuleShortcut]);

  const renameEntry = useCallback((entry: ShellDesktopEntry) => {
    if (["app", "module"].includes(entry.kind)) return;
    const name = window.prompt("Nowa nazwa", entry.name)?.trim();
    if (!name) return;
    persistEntries((preferences?.desktop_entries ?? []).map((item) => item.id === entry.id ? { ...item, name: name.slice(0, 240) } : item));
  }, [persistEntries, preferences]);

  const createFolder = useCallback(() => {
    const name = window.prompt("Nazwa folderu", "Nowy folder")?.trim();
    if (!name) return;
    const next: ShellDesktopEntry = { id: idFor("folder"), kind: "folder", name: name.slice(0, 240), target: "", position: { x: 12, y: 12 }, created_at: Date.now() };
    persistEntries([...(preferences?.desktop_entries ?? []), next]);
  }, [persistEntries, preferences]);

  const createShortcut = useCallback(() => {
    const target = window.prompt("Adres URL albo ścieżka pliku/katalogu")?.trim();
    if (!target) return;
    let kind: ShellDesktopEntry["kind"] = "file";
    let normalized = target;
    const url = safeUrl(target);
    if (url) { kind = "url"; normalized = url; }
    else if (target.endsWith("/")) kind = "directory";
    const name = window.prompt("Nazwa skrótu", target.split("/").filter(Boolean).at(-1) || target)?.trim();
    if (!name) return;
    const next: ShellDesktopEntry = { id: idFor("shortcut"), kind, name: name.slice(0, 240), target: normalized.slice(0, 4096), position: { x: 12, y: 12 }, created_at: Date.now() };
    persistEntries([...(preferences?.desktop_entries ?? []), next]);
  }, [persistEntries, preferences]);

  useEffect(() => {
    const unDesktop = WebNAS.desktop.subscribe((event) => {
      if (event.type === "new-folder") createFolder();
      if (event.type === "new-shortcut") createShortcut();
      if (event.type === "align") {
        const next = entries.map((item, index) => ({ ...item, position: { x: 12 + Math.floor(index / 8) * GRID_X, y: 12 + (index % 8) * GRID_Y } }));
        persistEntries(next);
      }
      if (event.type === "sort" && ["name", "type", "date"].includes(String(event.detail))) {
        const mode = event.detail as "name" | "type" | "date";
        const sorted = [...entries].sort((a, b) => mode === "name" ? a.name.localeCompare(b.name) : mode === "type" ? a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name) : a.created_at - b.created_at);
        persistEntries(sorted.map((item, index) => ({ ...item, position: { x: 12 + Math.floor(index / 8) * GRID_X, y: 12 + (index % 8) * GRID_Y } })));
      }
    });
    return unDesktop;
  }, [createFolder, createShortcut, entries, persistEntries]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) return;
      if (event.ctrlKey && event.key.toLowerCase() === "a") { event.preventDefault(); setSelected(new Set(entries.map((item) => item.id))); return; }
      if (event.ctrlKey && ["c", "x"].includes(event.key.toLowerCase())) {
        event.preventDefault();
        const ids = [...selected];
        if (event.key.toLowerCase() === "c") WebNAS.clipboard.copy(ids); else WebNAS.clipboard.cut(ids);
        return;
      }
      if (event.ctrlKey && event.key.toLowerCase() === "v") {
        const payload = WebNAS.clipboard.get();
        if (!payload) return;
        event.preventDefault();
        if (payload.mode === "cut") {
          const moved = (preferences?.desktop_entries ?? []).map((item) => payload.items.includes(item.id) ? { ...item, parent_id: null } : item);
          persistEntries(moved); WebNAS.clipboard.clear();
        } else {
          const custom = payload.items.map(entryById).filter((item): item is ShellDesktopEntry => Boolean(item && !["app", "module"].includes(item.kind)));
          const copies = custom.map((item, index) => ({ ...item, id: idFor("copy"), name: `${item.name} - kopia`, position: { x: item.position.x + 24 + index * 8, y: item.position.y + 24 + index * 8 }, created_at: Date.now() }));
          if (copies.length) persistEntries([...(preferences?.desktop_entries ?? []), ...copies]);
        }
        return;
      }
      if (event.key === "Delete" && selected.size) { event.preventDefault(); removeEntries([...selected]); }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [entries, entryById, persistEntries, preferences, removeEntries, selected]);

  const startSelection = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || event.button !== 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    selectionOrigin.current = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    setSelectionRect({ x: selectionOrigin.current.x, y: selectionOrigin.current.y, width: 0, height: 0 });
    if (!event.ctrlKey) setSelected(new Set());
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const moveSelection = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!selectionOrigin.current || !rootRef.current) return;
    const root = rootRef.current.getBoundingClientRect();
    const x2 = event.clientX - root.left; const y2 = event.clientY - root.top;
    const left = Math.min(selectionOrigin.current.x, x2); const top = Math.min(selectionOrigin.current.y, y2);
    const right = Math.max(selectionOrigin.current.x, x2); const bottom = Math.max(selectionOrigin.current.y, y2);
    setSelectionRect({ x: left, y: top, width: right - left, height: bottom - top });
    const absolute = { left: root.left + left, top: root.top + top, right: root.left + right, bottom: root.top + bottom };
    const ids = [...rootRef.current.querySelectorAll<HTMLElement>("[data-desktop-entry]")].filter((node) => intersects(node.getBoundingClientRect(), absolute)).map((node) => node.dataset.desktopEntry!).filter(Boolean);
    setSelected(new Set(ids));
  };
  const endSelection = () => { selectionOrigin.current = null; setSelectionRect(null); };

  const startDrag = (event: ReactPointerEvent<HTMLDivElement>, entry: ShellDesktopEntry) => {
    if (event.button !== 0) return;
    const itemRect = event.currentTarget.getBoundingClientRect();
    drag.current = { id: entry.id, offsetX: event.clientX - itemRect.left, offsetY: event.clientY - itemRect.top };
    event.currentTarget.setPointerCapture(event.pointerId);
    if (!selected.has(entry.id)) setSelected(new Set([entry.id]));
  };
  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const active = drag.current;
    if (!active || !rootRef.current) return;
    const root = rootRef.current.getBoundingClientRect();
    const x = snap(event.clientX - root.left - active.offsetX, GRID_X);
    const y = snap(event.clientY - root.top - active.offsetY, GRID_Y);
    setPreferences((current) => current ? { ...current, desktop_entries: current.desktop_entries.map((item) => item.id === active.id ? { ...item, position: { x, y } } : item) } : current);
  };
  const endDrag = () => {
    const active = drag.current; drag.current = null;
    if (!active || !preferences) return;
    persistEntries(preferences.desktop_entries);
  };

  const iconFor = (entry: ShellDesktopEntry) => {
    if (entry.kind === "app") return apps.find((item) => item.id === entry.target)?.icon ?? <Package />;
    if (entry.kind === "module") return <Package />;
    if (entry.kind === "folder" || entry.kind === "directory") return <Folder />;
    if (entry.kind === "url") return <Globe2 />;
    return <File />;
  };

  const openContext = (event: ReactPointerEvent | React.MouseEvent, entry: ShellDesktopEntry) => {
    event.preventDefault(); event.stopPropagation();
    WebNAS.contextMenu.open({
      x: event.clientX,
      y: event.clientY,
      source: "desktop-entry",
      items: [
        { label: "Otwórz", action: () => openEntry(entry) },
        ...(!["app", "module"].includes(entry.kind) ? [{ label: "Zmień nazwę", action: () => renameEntry(entry) }] : []),
        { label: "Usuń skrót", icon: <Trash2 />, danger: true, separator: true, action: () => removeEntries([entry.id]) },
      ],
    });
  };

  const longPressStart = (event: ReactPointerEvent<HTMLDivElement>, entry: ShellDesktopEntry) => {
    if (!WebNAS.device.isMobile) return;
    if (longPress.current !== null) window.clearTimeout(longPress.current);
    const x = event.clientX; const y = event.clientY;
    longPress.current = window.setTimeout(() => WebNAS.contextMenu.open({ x, y, source: "desktop-long-press", items: [
      { label: "Otwórz", action: () => openEntry(entry) },
      { label: "Usuń skrót", danger: true, action: () => removeEntries([entry.id]) },
    ] }), 550);
  };
  const cancelLongPress = () => { if (longPress.current !== null) window.clearTimeout(longPress.current); longPress.current = null; };

  return <div
    ref={rootRef}
    className="desktop-workspace"
    aria-label="Pulpit WebNAS"
    tabIndex={0}
    onPointerDown={startSelection}
    onPointerMove={moveSelection}
    onPointerUp={endSelection}
    onPointerCancel={endSelection}
    onDragOver={(event) => { if (event.dataTransfer.types.includes("Files")) event.preventDefault(); }}
    onDrop={(event) => {
      if (!event.dataTransfer.files.length) return;
      event.preventDefault();
      uploadControls.add([...event.dataTransfer.files], home);
      WebNAS.notification.send({ type: "upload", title: "Przesyłanie plików", body: `Dodano ${event.dataTransfer.files.length} plik(ów) do kolejki`, source: "desktop", level: "info", category: "transfer" });
    }}
  >
    {entries.map((entry) => <div
      key={entry.id}
      data-desktop-entry={entry.id}
      className={`desktop-workspace-item ${selected.has(entry.id) ? "selected" : ""}`}
      style={{ left: entry.position.x, top: entry.position.y }}
      onPointerDown={(event) => { longPressStart(event, entry); startDrag(event, entry); }}
      onPointerMove={(event) => { cancelLongPress(); moveDrag(event); }}
      onPointerUp={() => { cancelLongPress(); endDrag(); }}
      onPointerCancel={() => { cancelLongPress(); endDrag(); }}
      onContextMenu={(event) => openContext(event, entry)}
      onDoubleClick={() => openEntry(entry)}
    >
      <AppIcon label={entry.name} icon={iconFor(entry)} selected={selected.has(entry.id)} onSelect={() => setSelected((current) => new Set(current.has(entry.id) ? [...current].filter((id) => id !== entry.id) : [entry.id]))} onOpen={() => openEntry(entry)} />
    </div>)}
    {selectionRect && <div className="desktop-selection-rect" style={{ left: selectionRect.x, top: selectionRect.y, width: selectionRect.width, height: selectionRect.height }} />}
    {entries.length === 0 && <button className="desktop-empty-create" type="button" onClick={createShortcut}><Plus /> Dodaj skrót</button>}
  </div>;
}
