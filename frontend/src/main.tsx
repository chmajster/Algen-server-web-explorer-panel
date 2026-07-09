import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Bell,
  Activity,
  ChevronDown,
  ChevronRight,
  Package,
  Copy,
  Download,
  File,
  Folder,
  FolderPlus,
  Grid2X2,
  HardDrive,
  Home,
  List,
  Lock,
  LogOut,
  Menu,
  Maximize2,
  Minimize2,
  Moon,
  MoreVertical,
  Move,
  Network,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Settings,
  ServerCog,
  Shield,
  Sun,
  Terminal,
  Trash2,
  Upload,
  UserPlus,
  Users,
  X
} from "lucide-react";
import { AdminGroup, AdminUser, api, downloadUrl, FileItem, login, logout, me, ProxmoxSafety, SettingsMe, SystemdService, SystemLogs, Task, UpdateStatus } from "./api";
import type { AutoUpdateSettings } from "./api";
import type { NetworkMount, NetworkMountPayload, ResourceDashboard, SambaConfig, SambaShare, SambaStatus, SambaUser, StoreApp as StoreModule, StorePlugin } from "./api";
import { AppIcon } from "./components/AppIcon";
import { detectLanguage, Language, supportedLanguages, translate } from "./i18n";
import "./styles/app.css";

type User = { username: string; home: string };
type Toast = { id: number; text: string; type: "ok" | "error" };
type Theme = "light" | "dark" | "system";
type T = (key: string) => string;
type AppId = "dashboard" | "files" | "transfers" | "settings" | "mounts" | "services" | "store" | "samba" | "logs";
type WindowRect = { x: number; y: number; width: number; height: number };
type WindowLayout = WindowRect & { minimized?: boolean; restore?: WindowRect };
type WindowInstance = { id: string; app: AppId };
type Layouts = Record<string, WindowLayout>;
type SavedWindowState = { windows: WindowInstance[]; layouts: Layouts; activeWindowId?: string; counter?: number };
type ResizeEdge = "n" | "e" | "s" | "w" | "ne" | "nw" | "se" | "sw";

const MIN_WINDOW_WIDTH = 360;
const MIN_WINDOW_HEIGHT = 280;
const DESKTOP_MARGIN_X = 16;
const DESKTOP_TOP = 52;
const DESKTOP_BOTTOM = 52;

function getMaximizedRect(): WindowRect {
  return {
    x: DESKTOP_MARGIN_X,
    y: DESKTOP_TOP,
    width: Math.max(MIN_WINDOW_WIDTH, window.innerWidth - DESKTOP_MARGIN_X * 2),
    height: Math.max(MIN_WINDOW_HEIGHT, window.innerHeight - DESKTOP_TOP - DESKTOP_BOTTOM)
  };
}

function isValidRestoreRect(rect?: WindowRect | null): rect is WindowRect {
  if (!rect) return false;
  return [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite)
    && rect.width >= MIN_WINDOW_WIDTH
    && rect.height >= MIN_WINDOW_HEIGHT
    && rect.x > -rect.width
    && rect.y > -rect.height;
}

function clampWindowRect(rect: WindowRect): WindowRect {
  const max = getMaximizedRect();
  const width = Math.min(Math.max(MIN_WINDOW_WIDTH, rect.width), max.width);
  const height = Math.min(Math.max(MIN_WINDOW_HEIGHT, rect.height), max.height);
  const minX = 8;
  const minY = DESKTOP_TOP;
  const maxX = Math.max(minX, window.innerWidth - 16 - width);
  const maxY = Math.max(minY, window.innerHeight - DESKTOP_BOTTOM - height);
  return {
    x: Math.min(Math.max(rect.x, minX), maxX),
    y: Math.min(Math.max(rect.y, minY), maxY),
    width,
    height
  };
}

function restoreForDrag(layout: WindowLayout, pointerX: number, pointerY: number): { rect: WindowRect; offsetX: number; offsetY: number } {
  const fallback = { x: 120, y: DESKTOP_TOP + 24, width: 900, height: 620 };
  const restore = clampWindowRect(isValidRestoreRect(layout.restore) ? layout.restore : fallback);
  const currentWidth = Math.max(1, layout.width || getMaximizedRect().width);
  const ratioX = Math.min(.9, Math.max(.1, (pointerX - layout.x) / currentWidth));
  const titleOffsetY = 19;
  const rect = clampWindowRect({
    ...restore,
    x: pointerX - restore.width * ratioX,
    y: pointerY - titleOffsetY
  });
  return { rect, offsetX: pointerX - rect.x, offsetY: pointerY - rect.y };
}

const defaultLayouts: Layouts = {
  dashboard: { x: 112, y: 78, width: 1040, height: 680 },
  files: { x: 124, y: 82, width: 1120, height: 720 },
  transfers: { x: 220, y: 120, width: 760, height: 560 },
  settings: { x: 180, y: 104, width: 980, height: 660 },
  mounts: { x: 160, y: 92, width: 1040, height: 680 },
  services: { x: 210, y: 112, width: 940, height: 620 },
  store: { x: 190, y: 96, width: 1040, height: 680 },
  samba: { x: 190, y: 96, width: 1100, height: 700 },
  logs: { x: 260, y: 140, width: 880, height: 580 }
};

const appMeta: Record<AppId, { title: string; icon: React.ReactNode; admin?: boolean }> = {
  dashboard: { title: "Dashboard", icon: <Activity size={28} /> },
  files: { title: "File Manager", icon: <HardDrive size={28} /> },
  transfers: { title: "Transfers", icon: <RefreshCw size={28} /> },
  settings: { title: "Settings", icon: <Settings size={28} /> },
  mounts: { title: "Network Mounts", icon: <Network size={28} /> },
  services: { title: "Services", icon: <ServerCog size={28} />, admin: true },
  store: { title: "Store", icon: <Package size={28} />, admin: true },
  samba: { title: "Samba / Windows File Sharing", icon: <Network size={28} />, admin: true },
  logs: { title: "Logs", icon: <Terminal size={28} />, admin: true }
};

function isAppId(value: string): value is AppId {
  return value in appMeta;
}

function joinPath(base: string, name: string) {
  return `${base.replace(/\/$/, "")}/${name}`;
}

function formatSize(size: number) {
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = size / 1024;
  let unit = units.shift() || "KB";
  while (value > 1024 && units.length) {
    value /= 1024;
    unit = units.shift() || unit;
  }
  return `${value.toFixed(value > 100 ? 0 : 1)} ${unit}`;
}

function shortPath(path: string) {
  return path.split(/[\\/]/).filter(Boolean).slice(-2).join("/") || path;
}

function formatDate(value: number | null) {
  return value ? new Date(value * 1000).toLocaleString() : "-";
}

function formatDuration(seconds: number | null) {
  if (seconds === null) return "-";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${days}d ${hours}h ${minutes}m`;
}

function message(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}

function Login({ onLogin, t }: { onLogin: (user: User) => void; t: T }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    try {
      onLogin(await login(username.trim(), password));
    } catch (err) {
      setError(message(err, t("auth.loginFailed")));
    }
  }
  return (
    <main className="login-screen">
      <form className="login-panel" onSubmit={submit}>
        <HardDrive size={34} />
        <h1>WebNAS</h1>
        <input autoFocus placeholder={t("auth.linuxUser")} value={username} onChange={(e) => setUsername(e.target.value)} />
        <input placeholder={t("auth.password")} type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit">{t("auth.signIn")}</button>
      </form>
    </main>
  );
}

function DesktopWindow({
  app,
  title,
  layout,
  active,
  onFocus,
  onClose,
  onMinimize,
  onLayout,
  children
}: {
  app: AppId;
  title?: string;
  layout: WindowLayout;
  active: boolean;
  onFocus: () => void;
  onClose: () => void;
  onMinimize: () => void;
  onLayout: (layout: WindowLayout) => void;
  children: React.ReactNode;
}) {
  const displayTitle = title || appMeta[app].title;
  const drag = useRef<{
    startX: number;
    startY: number;
    layout: WindowLayout;
    mode: "move" | "resize";
    offsetX: number;
    offsetY: number;
    edge?: ResizeEdge;
  } | null>(null);
  const isMaximized = Boolean(layout.restore);
  function toggleMaximize() {
    if (layout.restore) {
      const restored = isValidRestoreRect(layout.restore) ? layout.restore : { x: 120, y: DESKTOP_TOP + 24, width: 900, height: 620 };
      onLayout({ ...clampWindowRect(restored), minimized: false, restore: undefined });
      return;
    }
    const restore = clampWindowRect(layout);
    onLayout({
      ...getMaximizedRect(),
      minimized: false,
      restore
    });
  }
  useEffect(() => {
    function move(event: PointerEvent) {
      if (!drag.current) return;
      const dx = event.clientX - drag.current.startX;
      const dy = event.clientY - drag.current.startY;
      const base = drag.current.layout;
      if (drag.current.mode === "move") {
        onLayout({
          ...base,
          ...clampWindowRect({ ...base, x: event.clientX - drag.current.offsetX, y: event.clientY - drag.current.offsetY }),
          restore: undefined,
          minimized: false
        });
      } else {
        const edge = drag.current.edge || "se";
        let nextX = base.x;
        let nextY = base.y;
        let nextWidth = base.width;
        let nextHeight = base.height;
        if (edge.includes("e")) nextWidth = Math.max(MIN_WINDOW_WIDTH, base.width + dx);
        if (edge.includes("s")) nextHeight = Math.max(MIN_WINDOW_HEIGHT, base.height + dy);
        if (edge.includes("w")) {
          nextWidth = Math.max(MIN_WINDOW_WIDTH, base.width - dx);
          nextX = base.x + (base.width - nextWidth);
        }
        if (edge.includes("n")) {
          nextHeight = Math.max(MIN_WINDOW_HEIGHT, base.height - dy);
          nextY = base.y + (base.height - nextHeight);
        }
        onLayout({ ...base, ...clampWindowRect({ x: nextX, y: nextY, width: nextWidth, height: nextHeight }), restore: undefined, minimized: false });
      }
    }
    function up() { drag.current = null; }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [onLayout]);
  const displayRect = isMaximized ? getMaximizedRect() : clampWindowRect(layout);
  return (
    <section
      className={`window ${active ? "active" : ""}`}
      style={{ left: displayRect.x, top: displayRect.y, width: displayRect.width, height: displayRect.height, zIndex: active ? 9 : 5 }}
      onPointerDown={onFocus}
    >
      <header
        className="window-title"
        onPointerDown={(event) => {
          event.preventDefault();
          if (event.detail > 1) {
            drag.current = null;
            return;
          }
          if (isMaximized) {
            const restored = restoreForDrag({ ...layout, ...displayRect }, event.clientX, event.clientY);
            const nextLayout = { ...restored.rect, minimized: false, restore: undefined };
            onLayout(nextLayout);
            drag.current = { startX: event.clientX, startY: event.clientY, layout: nextLayout, mode: "move", offsetX: restored.offsetX, offsetY: restored.offsetY };
          } else {
            const base = { ...layout, ...displayRect, restore: undefined };
            drag.current = { startX: event.clientX, startY: event.clientY, layout: base, mode: "move", offsetX: event.clientX - displayRect.x, offsetY: event.clientY - displayRect.y };
          }
          onFocus();
        }}
        onDoubleClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          drag.current = null;
          toggleMaximize();
        }}
      >
        <span>{displayTitle}</span>
        <div className="window-controls" onPointerDown={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()}>
          <button title="Minimize" onPointerDown={(event) => event.stopPropagation()} onClick={(event) => { event.stopPropagation(); onMinimize(); }}><Minimize2 size={13} /></button>
          <button title={isMaximized ? "Restore" : "Maximize"} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => { event.stopPropagation(); toggleMaximize(); }}><Maximize2 size={13} /></button>
          <button title="Close" onPointerDown={(event) => event.stopPropagation()} onClick={(event) => { event.stopPropagation(); onClose(); }}><X size={13} /></button>
        </div>
      </header>
      {children}
      {!isMaximized && (["n", "e", "s", "w", "ne", "nw", "se", "sw"] as ResizeEdge[]).map((edge) => (
        <span
          key={edge}
          className={`resize-handle resize-${edge}`}
          onPointerDown={(event) => {
            event.preventDefault();
            event.stopPropagation();
            // eslint-disable-next-line react-hooks/refs -- pointer handlers are allowed to update transient drag refs.
            drag.current = { startX: event.clientX, startY: event.clientY, layout: { ...layout, ...clampWindowRect(layout) }, mode: "resize", edge, offsetX: 0, offsetY: 0 };
            onFocus();
          }}
          aria-hidden="true"
        />
      ))}
    </section>
  );
}

function Breadcrumbs({ path, onOpen }: { path: string; onOpen: (path: string) => void }) {
  const parts = path.split("/").filter(Boolean);
  const crumbs = parts.map((part, index) => ({ label: part, path: `/${parts.slice(0, index + 1).join("/")}` }));
  return (
    <nav className="breadcrumbs">
      <button onClick={() => onOpen("/")}>/</button>
      {crumbs.map((crumb) => (
        <button key={crumb.path} onClick={() => onOpen(crumb.path)}>{crumb.label}</button>
      ))}
    </nav>
  );
}

function Preview({ item, onClose, t }: { item: FileItem | null; onClose: () => void; t: T }) {
  const [content, setContent] = useState("");
  const [mime, setMime] = useState("");
  useEffect(() => {
    if (!item || item.is_dir) return;
    api.preview(item.path).then((data) => {
      setMime(data.mime);
      setContent(data.content_base64);
    });
  }, [item]);
  if (!item) return null;
  const src = `data:${mime};base64,${content}`;
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <header><strong>{item.name}</strong><button title={t("action.close")} onClick={onClose}><X size={16} /></button></header>
        {mime.startsWith("image/") ? <img className="preview-image" src={src} /> : <pre className="preview-text">{content ? atob(content) : ""}</pre>}
      </div>
    </div>
  );
}

function FileManager({ toast, t, tasks }: { toast: (text: string, type?: "ok" | "error") => void; t: T; tasks: Task[] }) {
  const [path, setPath] = useState("");
  const [items, setItems] = useState<FileItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [view, setView] = useState<"list" | "grid">("list");
  const [query, setQuery] = useState("");
  const [clipboard, setClipboard] = useState<{ mode: "copy" | "move"; paths: string[] } | null>(null);
  const [preview, setPreview] = useState<FileItem | null>(null);
  const [refreshedTasks, setRefreshedTasks] = useState<Set<string>>(new Set());
  const [context, setContext] = useState<{ x: number; y: number; item: FileItem | null } | null>(null);
  const [mounts, setMounts] = useState<NetworkMount[]>([]);

  async function load(next = path) {
    try {
      if (query) {
        const data = await api.search(next || path, query);
        setItems(data.items);
      } else {
        const data = await api.list(next);
        setPath(data.path);
        setItems(data.items);
      }
      setSelected(new Set());
    } catch (err) {
      toast(message(err, t("files.loadError")), "error");
    }
  }
  useEffect(() => { load(""); }, []);
  useEffect(() => { api.mounts().then(setMounts).catch(() => undefined); }, []);
  useEffect(() => {
    const completed = tasks.filter((task) => ["copy", "move"].includes(task.type) && task.status === "completed" && !refreshedTasks.has(task.id));
    if (!completed.length) return;
    setRefreshedTasks((current) => new Set([...current, ...completed.map((task) => task.id)]));
    load();
  }, [tasks]);

  const selectedItems = useMemo(() => items.filter((item) => selected.has(item.path)), [items, selected]);
  function toggle(item: FileItem, multi: boolean) {
    setSelected((current) => {
      const next = multi ? new Set(current) : new Set<string>();
      if (next.has(item.path)) next.delete(item.path);
      else next.add(item.path);
      return next;
    });
  }
  async function named(action: string, fn: () => Promise<unknown>) {
    try {
      await fn();
      toast(action);
      await load();
    } catch (err) {
      toast(message(err, t("files.operationFailed")), "error");
    }
  }
  async function paste() {
    if (!clipboard) return;
    if (clipboard.paths.length > 1) {
      await (clipboard.mode === "copy" ? api.copy(clipboard.paths, path) : api.move(clipboard.paths, path));
    } else {
      const src = clipboard.paths[0];
      const name = src.split("/").pop() || "item";
      const dst = joinPath(path, name);
      await (clipboard.mode === "copy" ? api.copy(src, dst) : api.move(src, dst));
    }
    toast(t("files.taskQueued"));
    setClipboard(null);
  }
  function copySelected() {
    if (selectedItems.length) setClipboard({ mode: "copy", paths: selectedItems.map((i) => i.path) });
  }
  function renameItem(item = selectedItems[0]) {
    if (!item) return;
    const name = prompt(t("files.newName"), item.name);
    if (name) named(t("files.renamed"), () => api.rename(item.path, joinPath(path, name)));
  }
  function deleteSelected() {
    selectedItems.forEach((item) => named(t("files.deleteQueued"), () => api.delete(item.path)));
  }
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
        event.preventDefault();
        setSelected(new Set(items.map((item) => item.path)));
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c") {
        event.preventDefault();
        copySelected();
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") {
        event.preventDefault();
        paste().catch((err) => toast(message(err, t("files.operationFailed")), "error"));
      } else if (event.key === "F2") {
        event.preventDefault();
        renameItem();
      } else if (event.key === "Delete") {
        event.preventDefault();
        deleteSelected();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, selectedItems, clipboard, path]);
  return (
    <>
      <div className="toolbar">
        <button title={t("action.refresh")} onClick={() => load()}><RefreshCw size={17} /></button>
        <button title={t("action.newFolder")} onClick={() => { const name = prompt(t("files.folderName")); if (name) named(t("files.folderCreated"), () => api.mkdir(joinPath(path, name))); }}><FolderPlus size={17} /></button>
        <label className="icon-button" title={t("action.upload")}><Upload size={17} /><input type="file" multiple onChange={(e) => Array.from(e.target.files || []).forEach((file) => named(t("files.uploaded"), () => api.upload(path, file)))} /></label>
        <button title={t("action.copy")} disabled={!selected.size} onClick={copySelected}><Copy size={17} /></button>
        <button title={t("action.paste")} disabled={!clipboard} onClick={paste}>{t("action.paste")}</button>
        <button title={t("action.delete")} disabled={!selected.size} onClick={deleteSelected}><Trash2 size={17} /></button>
        <button title={t("action.listView")} onClick={() => setView("list")}><List size={17} /></button>
        <button title={t("action.gridView")} onClick={() => setView("grid")}><Grid2X2 size={17} /></button>
        <div className="search"><Search size={16} /><input placeholder={t("files.search")} value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()} /></div>
      </div>
      <Breadcrumbs path={path} onOpen={load} />
      <div className="file-layout">
        <aside>
          <button onClick={() => load(path)}><Folder size={16} /> {t("files.current")}</button>
          {!!mounts.length && <strong className="sidebar-heading">Network resources</strong>}
          {mounts.map((mount) => <button key={mount.id} onClick={() => load(mount.mount_point)}><Network size={16} /> {mount.name} <span>{mount.status}</span></button>)}
          {items.filter((i) => i.is_dir).slice(0, 40).map((item) => <button key={item.path} onClick={() => load(item.path)}><Folder size={16} /> {item.name}</button>)}
        </aside>
        <main className={view === "grid" ? "grid-view" : "list-view"} onContextMenu={(e) => { e.preventDefault(); setContext({ x: e.clientX, y: e.clientY, item: null }); }}>
          {items.map((item) => (
            <div
              key={item.path}
              className={`file-row ${selected.has(item.path) ? "selected" : ""}`}
              draggable
              onDragStart={() => setClipboard({ mode: "move", paths: [item.path] })}
              onDragOver={(e) => item.is_dir && e.preventDefault()}
              onDrop={() => item.is_dir && clipboard && api.move(clipboard.paths[0], joinPath(item.path, clipboard.paths[0].split("/").pop() || "item")).then(() => load())}
              onClick={(e) => toggle(item, e.ctrlKey || e.metaKey)}
              onContextMenu={(e) => { e.preventDefault(); setSelected(new Set([item.path])); setContext({ x: e.clientX, y: e.clientY, item }); }}
              onDoubleClick={() => item.is_dir ? load(item.path) : setPreview(item)}
            >
              {item.is_dir ? <Folder size={22} /> : <File size={22} />}
              <span className="name">{item.name}</span>
              <span>{item.is_dir ? "" : formatSize(item.size)}</span>
              <span>{item.owner}:{item.group}</span>
              <span>{item.mode}</span>
              <div className="row-actions">
                {!item.is_dir && <a title={t("action.download")} href={downloadUrl(item.path)}><Download size={16} /></a>}
                <button title={t("action.rename")} onClick={(e) => { e.stopPropagation(); renameItem(item); }}>{t("action.rename")}</button>
              </div>
            </div>
          ))}
        </main>
      </div>
      {context && <div className="context-menu" style={{ left: context.x, top: context.y }} onMouseLeave={() => setContext(null)}>
        {context.item?.is_dir && <button onClick={() => { load(context.item!.path); setContext(null); }}>Open</button>}
        {!context.item?.is_dir && context.item && <a href={downloadUrl(context.item.path)} onClick={() => setContext(null)}>Download</a>}
        <button disabled={!selected.size} onClick={() => { copySelected(); setContext(null); }}>Copy</button>
        <button disabled={!clipboard} onClick={() => { paste().catch((err) => toast(message(err, t("files.operationFailed")), "error")); setContext(null); }}>Paste</button>
        <button disabled={!selected.size} onClick={() => { renameItem(); setContext(null); }}>Rename</button>
        <button disabled={!selected.size} onClick={() => { deleteSelected(); setContext(null); }}>Delete</button>
        <button onClick={() => { load(); setContext(null); }}>Refresh</button>
      </div>}
      <Preview item={preview} onClose={() => setPreview(null)} t={t} />
    </>
  );
}

type SortField = "name" | "size" | "type" | "owner" | "group" | "permissions" | "modified";
type SortDirection = "asc" | "desc";
type TreeState = Record<string, { items: FileItem[]; open: boolean; loading: boolean; error?: string }>;

function FileManagerV2({ toast, t, tasks, homePath, onShareSamba }: { toast: (text: string, type?: "ok" | "error") => void; t: T; tasks: Task[]; homePath: string; onShareSamba: (path: string) => void }) {
  const lastPathKey = "webnas_file_manager_last_path";
  const viewKey = "webnas_file_manager_view";
  const [path, setPath] = useState(() => localStorage.getItem(lastPathKey) || "");
  const [items, setItems] = useState<FileItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [clipboard, setClipboard] = useState<{ mode: "copy" | "move"; paths: string[] } | null>(null);
  const [preview, setPreview] = useState<FileItem | null>(null);
  const [context, setContext] = useState<{ x: number; y: number; item: FileItem | null } | null>(null);
  const [mounts, setMounts] = useState<NetworkMount[]>([]);
  const [sambaSharedPaths, setSambaSharedPaths] = useState<Set<string>>(new Set());
  const [tree, setTree] = useState<TreeState>({});
  const [treeVisible, setTreeVisible] = useState(() => localStorage.getItem(`${viewKey}_tree`) !== "hidden");
  const [treeWidth, setTreeWidth] = useState(() => Number(localStorage.getItem(`${viewKey}_tree_width`) || 240));
  const [compact, setCompact] = useState(() => localStorage.getItem(`${viewKey}_density`) === "compact");
  const [viewMode, setViewMode] = useState<"list" | "grid">("list");
  const [sort, setSort] = useState<SortField>("name");
  const [direction, setDirection] = useState<SortDirection>("asc");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [filter, setFilter] = useState("");
  const [debouncedFilter, setDebouncedFilter] = useState("");
  const [foldersFirst, setFoldersFirst] = useState(true);
  const [meta, setMeta] = useState({ total_items: 0, total_pages: 1, can_upload: true, can_delete: true, parent_path: null as string | null });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [refreshedTasks, setRefreshedTasks] = useState<Set<string>>(new Set());

  async function load(next = path, nextPage = page) {
    setLoading(true);
    setError("");
    try {
      const data = await api.list(next, { sort, direction, page: nextPage, page_size: pageSize, folders_first: foldersFirst, filter: debouncedFilter });
      setPath(data.current_path);
      localStorage.setItem(lastPathKey, data.current_path);
      setItems(data.items);
      setMeta({ total_items: data.total_items, total_pages: data.total_pages, can_upload: data.can_upload, can_delete: data.can_delete, parent_path: data.parent_path });
      setSelected(new Set());
      if (data.items.length === 0 && data.page > 1) setPage(data.page - 1);
    } catch (err) {
      setError(message(err, t("files.loadError")));
      toast(message(err, t("files.loadError")), "error");
    } finally {
      setLoading(false);
    }
  }

  async function loadTree(nodePath = path || "") {
    setTree((current) => ({ ...current, [nodePath]: { ...(current[nodePath] || { items: [], open: false }), loading: true, error: "" } }));
    try {
      const data = await api.tree(nodePath);
      setTree((current) => ({ ...current, [data.path]: { items: data.items, open: true, loading: false } }));
    } catch (err) {
      setTree((current) => ({ ...current, [nodePath]: { ...(current[nodePath] || { items: [], open: false }), loading: false, error: message(err, "Cannot read directory") } }));
    }
  }

  function openPath(next: string) {
    setPage(1);
    setPath(next);
  }

  useEffect(() => { const timer = setTimeout(() => setDebouncedFilter(filter), 260); return () => clearTimeout(timer); }, [filter]);
  useEffect(() => { load(path, page); }, [path, page, sort, direction, debouncedFilter, foldersFirst]);
  useEffect(() => { loadTree(path || ""); }, []);
  useEffect(() => { api.mounts().then(setMounts).catch(() => undefined); }, []);
  useEffect(() => { api.appConfig("samba").then((data) => setSambaSharedPaths(new Set((data.shares || []).filter((share) => share.enabled).map((share) => share.path)))).catch(() => undefined); }, [path]);
  useEffect(() => { localStorage.setItem(`${viewKey}_tree`, treeVisible ? "visible" : "hidden"); }, [treeVisible]);
  useEffect(() => { localStorage.setItem(`${viewKey}_tree_width`, String(treeWidth)); }, [treeWidth]);
  useEffect(() => { localStorage.setItem(`${viewKey}_density`, compact ? "compact" : "normal"); }, [compact]);
  useEffect(() => {
    const completed = tasks.filter((task) => ["copy", "move", "delete"].includes(task.type) && ["completed", "failed"].includes(task.status) && !refreshedTasks.has(task.id));
    if (!completed.length) return;
    setRefreshedTasks((current) => new Set([...current, ...completed.map((task) => task.id)]));
    load();
    loadTree(path);
  }, [tasks]);

  const selectedItems = useMemo(() => items.filter((item) => selected.has(item.path)), [items, selected]);
  function toggle(item: FileItem, multi: boolean) {
    setSelected((current) => {
      const next = multi ? new Set(current) : new Set<string>();
      if (next.has(item.path)) next.delete(item.path);
      else next.add(item.path);
      return next;
    });
  }
  function sortBy(field: SortField) {
    if (sort !== field) {
      setSort(field);
      setDirection("asc");
    } else if (direction === "asc") {
      setDirection("desc");
    } else {
      setSort("name");
      setDirection("asc");
    }
    setPage(1);
  }
  function copySelected() {
    if (selectedItems.length) setClipboard({ mode: "copy", paths: selectedItems.map((item) => item.path) });
  }
  async function named(action: string, fn: () => Promise<unknown>) {
    try {
      await fn();
      toast(action);
      await load();
      await loadTree(path);
    } catch (err) {
      toast(message(err, t("files.operationFailed")), "error");
    }
  }
  async function paste(target = path) {
    if (!clipboard) return;
    if (clipboard.paths.length > 1) await (clipboard.mode === "copy" ? api.copy(clipboard.paths, target) : api.move(clipboard.paths, target));
    else {
      const src = clipboard.paths[0];
      await (clipboard.mode === "copy" ? api.copy(src, joinPath(target, src.split("/").pop() || "item")) : api.move(src, joinPath(target, src.split("/").pop() || "item")));
    }
    setClipboard(null);
    toast(t("files.taskQueued"));
  }
  function renameItem(item = selectedItems[0]) {
    if (!item || !item.can_rename) return;
    const name = prompt(t("files.newName"), item.name);
    if (name) named(t("files.renamed"), () => api.rename(item.path, joinPath(path, name)));
  }
  function deleteSelected() {
    selectedItems.filter((item) => item.can_delete).forEach((item) => named(t("files.deleteQueued"), () => api.delete(item.path)));
  }
  function moveSelectedToPrompt() {
    const target = prompt("Move to", path);
    if (target) named(t("files.taskQueued"), () => api.move([...selected], target));
  }
  function openSelected() {
    const item = selectedItems[0];
    if (!item) return;
    if (item.is_dir) openPath(item.path);
    else setPreview(item);
  }
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
        event.preventDefault();
        setSelected(new Set(items.map((item) => item.path)));
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c") {
        event.preventDefault();
        copySelected();
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") {
        event.preventDefault();
        paste().catch((err) => toast(message(err, t("files.operationFailed")), "error"));
      } else if (event.key === "F2") {
        event.preventDefault();
        renameItem();
      } else if (event.key === "Delete") {
        event.preventDefault();
        deleteSelected();
      } else if (event.key === "Enter") {
        event.preventDefault();
        openSelected();
      } else if (event.key === "Backspace" && meta.parent_path) {
        event.preventDefault();
        openPath(meta.parent_path);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, selectedItems, clipboard, path, meta.parent_path]);

  function TreeNode({ item, level = 0 }: { item: FileItem; level?: number }) {
    const state = tree[item.path];
    return (
      <>
        <button
          className={`folder-tree-item ${path === item.path ? "active" : ""}`}
          style={{ paddingLeft: 10 + level * 14 }}
          onClick={() => openPath(item.path)}
          onContextMenu={(event) => { event.preventDefault(); setContext({ x: event.clientX, y: event.clientY, item }); }}
        >
          <span onClick={(event) => {
            event.stopPropagation();
            if (state?.open) setTree((current) => ({ ...current, [item.path]: { ...state, open: false } }));
            else loadTree(item.path);
          }}>{state?.open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
          <Folder size={15} /> <span className="folder-tree-label">{item.name}</span> {state?.loading && <span className="tree-loading">...</span>}
        </button>
        {state?.error && <small className="tree-error">{state.error}</small>}
        {state?.open && state.items.map((child) => <TreeNode key={child.path} item={child} level={level + 1} />)}
      </>
    );
  }

  const rootItems = tree[path]?.items || items.filter((item) => item.is_dir);
  const sortIcon = (field: SortField) => sort === field ? (direction === "asc" ? "^" : "v") : "";
  const activeFileTasks = tasks.filter((task) => ["copy", "move", "delete"].includes(task.type) && ["queued", "running", "paused"].includes(task.status)).length;
  return (
    <section className="app-shell file-manager-shell">
      <header className="file-topbar">
        <div className="file-topbar-title">
          <HardDrive size={18} />
          <div>
            <strong>File Manager</strong>
            <span>{shortPath(path || "/")}</span>
          </div>
        </div>
        <div className="file-topbar-actions">
          <button className="action-button" type="button" title={t("action.refresh")} aria-label={t("action.refresh")} onClick={() => { load(); loadTree(path); }}><RefreshCw size={16} /></button>
          <div className="segmented-control" aria-label="View mode">
            <button className={viewMode === "list" ? "active" : ""} type="button" title={t("action.listView")} aria-label={t("action.listView")} onClick={() => setViewMode("list")}><List size={15} /></button>
            <button className={viewMode === "grid" ? "active" : ""} type="button" title={t("action.gridView")} aria-label={t("action.gridView")} onClick={() => setViewMode("grid")}><Grid2X2 size={15} /></button>
          </div>
          <button className="action-button" type="button" title="Settings" aria-label="Settings"><Settings size={16} /></button>
        </div>
      </header>
      <div className="toolbar">
        <button title="Toggle tree" onClick={() => setTreeVisible((value) => !value)}><Menu size={17} /></button>
        <button title="Home" aria-label="Home" onClick={() => openPath(homePath || "")}><Home size={17} /></button>
        <button title={t("action.refresh")} onClick={() => { load(); loadTree(path); }}><RefreshCw size={17} /></button>
        <button title={t("action.newFolder")} disabled={!meta.can_upload} onClick={() => { const name = prompt(t("files.folderName")); if (name) named(t("files.folderCreated"), () => api.mkdir(joinPath(path, name))); }}><FolderPlus size={17} /></button>
        <label className="icon-button" title={t("action.upload")}><Upload size={17} /><input type="file" multiple disabled={!meta.can_upload} onChange={(e) => Array.from(e.target.files || []).forEach((file) => named(t("files.uploaded"), () => api.upload(path, file)))} /></label>
        <button title={t("action.download")} disabled={!selectedItems.length || selectedItems[0]?.is_dir} onClick={() => selectedItems[0] && window.open(downloadUrl(selectedItems[0].path), "_blank")}><Download size={17} /></button>
        <button title={t("action.copy")} disabled={!selected.size} onClick={copySelected}><Copy size={17} /></button>
        <button title="Move" disabled={!selected.size || !meta.can_upload} onClick={() => { if (selectedItems.length) setClipboard({ mode: "move", paths: selectedItems.map((item) => item.path) }); }}><Move size={17} /></button>
        <button title={t("action.paste")} disabled={!clipboard || !meta.can_upload} onClick={() => paste()}>{t("action.paste")}</button>
        <button title={t("action.delete")} disabled={!selected.size || !meta.can_delete} onClick={deleteSelected}><Trash2 size={17} /></button>
        <label><input type="checkbox" checked={foldersFirst} onChange={(e) => { setFoldersFirst(e.target.checked); setPage(1); }} /> folders first</label>
        <label><input type="checkbox" checked={compact} onChange={(e) => setCompact(e.target.checked)} /> compact</label>
        <div className="search"><Search size={16} /><input placeholder={t("files.search")} value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1); }} />{filter && <button onClick={() => setFilter("")}>×</button>}</div>
      </div>
      <Breadcrumbs path={path} onOpen={openPath} />
      <div className={`file-layout explorer-v2 ${treeVisible ? "" : "tree-hidden"}`} style={{ gridTemplateColumns: treeVisible ? `${treeWidth}px 6px minmax(0,1fr)` : "0 0 minmax(0,1fr)" }}>
        {treeVisible && <aside className="directory-tree">
          <button className={!path ? "active" : ""} onClick={() => openPath(path)}><Folder size={16} /> {t("files.current")}</button>
          {!!mounts.length && <strong className="sidebar-heading">Network resources</strong>}
          {mounts.map((mount) => <button key={mount.id} onClick={() => openPath(mount.mount_point)}><Network size={16} /> {mount.name}<span>{mount.status}</span></button>)}
          <strong className="sidebar-heading">Folders</strong>
          {rootItems.map((item) => <TreeNode key={item.path} item={item} />)}
        </aside>}
        {treeVisible && <span className="tree-resizer" onPointerDown={(event) => {
          const startX = event.clientX;
          const startWidth = treeWidth;
          function move(moveEvent: PointerEvent) { setTreeWidth(Math.min(420, Math.max(170, startWidth + moveEvent.clientX - startX))); }
          function up() { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); }
          window.addEventListener("pointermove", move);
          window.addEventListener("pointerup", up);
        }} />}
        <main className={`file-table ${compact ? "compact" : ""}`} onContextMenu={(e) => { e.preventDefault(); setContext({ x: e.clientX, y: e.clientY, item: null }); }}>
          {selected.size > 0 && <div className="selection-bar"><strong>{selected.size} selected</strong><button onClick={copySelected}>Copy</button><button onClick={moveSelectedToPrompt}>Move</button><button onClick={deleteSelected}>Delete</button><button onClick={() => selectedItems[0] && window.open(downloadUrl(selectedItems[0].path), "_blank")}>Download</button><button onClick={() => { const mode = prompt("Mode", "0644"); if (mode) selectedItems.forEach((item) => named("Permissions changed", () => api.chmod(item.path, mode))); }}>chmod</button><button onClick={() => toast("Archive action is queued for a future backend module")}>Archive</button></div>}
          {debouncedFilter && <p className="filter-note">Filtered by "{debouncedFilter}"</p>}
          {error && <p className="error">{error}</p>}
          {loading ? <div className="table-skeleton"><span /><span /><span /><span /></div> : (
            <div className="file-table-grid">
              <div className="file-header">
                <input aria-label="Select all files" type="checkbox" checked={items.length > 0 && selected.size === items.length} onChange={(e) => setSelected(e.target.checked ? new Set(items.map((item) => item.path)) : new Set())} />
                <span />
                {(["name", "size", "type", "owner", "group", "permissions", "modified"] as SortField[]).map((field) => <button key={field} onClick={() => sortBy(field)}>{field} {sortIcon(field)}</button>)}
                <span>actions</span>
              </div>
              {items.length === 0 && <p className="empty-state">Ten folder jest pusty</p>}
              {items.map((item) => (
                <div
                  key={item.path}
                  className={`file-row ${selected.has(item.path) ? "selected" : ""}`}
                  draggable
                  onDragStart={() => setClipboard({ mode: "move", paths: [item.path] })}
                  onDragOver={(e) => item.is_dir && e.preventDefault()}
                  onDrop={() => item.is_dir && clipboard && window.confirm("Move selected item here?") && paste(item.path)}
                  onClick={(e) => toggle(item, e.ctrlKey || e.metaKey)}
                  onContextMenu={(e) => { e.preventDefault(); setSelected(new Set([item.path])); setContext({ x: e.clientX, y: e.clientY, item }); }}
                  onDoubleClick={() => item.is_dir ? openPath(item.path) : setPreview(item)}
                >
                  <input aria-label={`Select ${item.name}`} type="checkbox" checked={selected.has(item.path)} onChange={(e) => { e.stopPropagation(); toggle(item, true); }} />
                  {item.is_dir ? <Folder className="file-icon folder-icon" size={20} /> : <File className="file-icon" size={20} />}
                  <span className={`name ${item.is_dir ? "folder-name" : ""}`}>{item.name}{item.is_dir && sambaSharedPaths.has(item.path) && <small className="smb-badge">SMB</small>}</span>
                  <span>{item.is_dir ? "—" : formatSize(item.size)}</span>
                  <span>{item.type}</span>
                  <span>{item.owner}</span>
                  <span>{item.group}</span>
                  <span className="permissions">{item.permissions}</span>
                  <span className="modified">{formatDate(item.mtime || item.modified)}</span>
                  <div className="row-actions">{!item.is_dir && <a className="action-button" title={t("action.download")} aria-label={t("action.download")} href={downloadUrl(item.path)}><Download size={15} /></a>}<button className="action-button" title={t("action.rename")} aria-label={t("action.rename")} onClick={(e) => { e.stopPropagation(); renameItem(item); }}><MoreVertical size={15} /></button></div>
                </div>
              ))}
            </div>
          )}
          {meta.total_pages > 1 && <footer className="pagination"><button disabled={page === 1} onClick={() => setPage(1)}>First</button><button disabled={page === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>Prev</button><span>{page} / {meta.total_pages} ({meta.total_items})</span><button disabled={page >= meta.total_pages} onClick={() => setPage((value) => Math.min(meta.total_pages, value + 1))}>Next</button><button disabled={page >= meta.total_pages} onClick={() => setPage(meta.total_pages)}>Last</button></footer>}
        </main>
      </div>
      {context && <div className="context-menu" style={{ left: context.x, top: context.y }} onMouseLeave={() => setContext(null)}>
        {context.item?.is_dir && <button onClick={() => { openPath(context.item!.path); setContext(null); }}>Open</button>}
        <button onClick={() => { const base = context.item?.is_dir ? context.item.path : path; const name = prompt(t("files.folderName")); if (name) named(t("files.folderCreated"), () => api.mkdir(joinPath(base, name))); setContext(null); }}>New folder</button>
        <button disabled={!selected.size} onClick={() => { renameItem(); setContext(null); }}>Rename</button>
        <button disabled={!selected.size} onClick={() => { deleteSelected(); setContext(null); }}>Delete</button>
        <button onClick={() => { navigator.clipboard?.writeText(context.item?.path || path); setContext(null); }}>Copy path</button>
        {(context.item?.is_dir || selectedItems[0]?.is_dir) && <button onClick={() => { const item = context.item || selectedItems[0]; if (item) onShareSamba(item.path); setContext(null); }}>Udostepnij przez Sambe</button>}
        <button onClick={() => { const item = context.item || selectedItems[0]; if (item) alert(`${item.name}\n${item.path}\n${item.permissions}`); setContext(null); }}>Properties</button>
        <button disabled={!clipboard} onClick={() => { paste(context.item?.path || path).catch((err) => toast(message(err, t("files.operationFailed")), "error")); setContext(null); }}>Paste</button>
        <button onClick={() => { load(); loadTree(context.item?.path || path); setContext(null); }}>Refresh</button>
      </div>}
      <Preview item={preview} onClose={() => setPreview(null)} t={t} />
      <footer className="file-statusbar">
        <span>{meta.total_items} items</span>
        <span>{selected.size} selected</span>
        <span>{activeFileTasks} background tasks</span>
        <span>{loading ? "Loading" : "Ready"}</span>
      </footer>
    </section>
  );
}

function TransferPanel({ tasks, t, toast }: { tasks: Task[]; t: T; toast: (text: string, type?: "ok" | "error") => void }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<"all" | "active" | "finished" | "failed" | "cancelled">("all");
  const visibleTaskTypes = ["copy", "move", "delete"];
  const transferTasks = tasks.filter((task) => visibleTaskTypes.includes(task.type) && !hidden.has(task.id));
  const visible = transferTasks.filter((task) => {
    if (!visibleTaskTypes.includes(task.type) || hidden.has(task.id)) return false;
    if (filter === "active") return ["queued", "running", "paused"].includes(task.status);
    if (filter === "finished") return task.status === "completed";
    if (filter === "failed") return task.status === "failed";
    if (filter === "cancelled") return task.status === "cancelled";
    return true;
  });
  if (!transferTasks.length) return null;
  async function action(taskId: string, fn: (taskId: string) => Promise<unknown>) {
    try {
      await fn(taskId);
    } catch (err) {
      toast(message(err, t("error.generic")), "error");
    }
  }
  return (
    <section className="transfer-panel transfer-app">
      <header>
        <strong>{t("transfers.title")}</strong>
        <div className="transfer-filters">
          {(["all", "active", "finished", "failed", "cancelled"] as const).map((item) => <button key={item} className={filter === item ? "active" : ""} onClick={() => setFilter(item)}>{item}</button>)}
        </div>
      </header>
      <div className="transfer-list">
        {visible.map((task) => {
          const expanded = open.has(task.id);
          const done = ["completed", "failed", "cancelled"].includes(task.status);
          const progress = task.progress_percent ?? task.progress ?? 0;
          return (
            <article key={task.id} className={`transfer-item ${task.status}`}>
              <div className="transfer-main">
                <strong>{t(`transfers.${task.type}`)}</strong>
                <span>{t("transfers.status")}: {task.status}</span>
                <span>priority: {task.priority}</span>
                <button onClick={() => setOpen((current) => { const next = new Set(current); if (next.has(task.id)) next.delete(task.id); else next.add(task.id); return next; })}>{t("transfers.details")}</button>
                {["copy", "move"].includes(task.type) && task.status === "running" && <button title="Pause" onClick={() => action(task.id, api.pauseTask)}><Pause size={14} /></button>}
                {["paused", "failed"].includes(task.status) && <button title="Resume" onClick={() => action(task.id, api.resumeTask)}><Play size={14} /></button>}
                {["failed", "cancelled"].includes(task.status) && <button title="Retry" onClick={() => action(task.id, api.retryTask)}><RotateCcw size={14} /></button>}
                {!done && <button onClick={() => action(task.id, api.cancelTask)}>{t("transfers.cancel")}</button>}
                {done && <button onClick={() => setHidden((current) => new Set([...current, task.id]))}>{t("transfers.hide")}</button>}
              </div>
              <div className="transfer-progress"><span style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} /></div>
              <div className="transfer-meta">
                <span>{progress}%</span>
                <span>{task.speed_human || "0 B/s"}</span>
                <span>avg: {task.average_speed_human || "0 B/s"}</span>
                {["copy", "move"].includes(task.type) && <span>{t("transfers.transferred")}: {formatSize(task.bytes_transferred || 0)} / {formatSize(task.total_bytes || 0)}</span>}
                {["copy", "move"].includes(task.type) && <span>{t("transfers.eta")}: {task.eta_human || "-"}</span>}
              </div>
              <div className="transfer-paths">
                <span>{t("transfers.source")}: {task.source_paths.map(shortPath).join(", ")}</span>
                {task.destination_path && <span>{t("transfers.destination")}: {shortPath(task.destination_path)}</span>}
                {task.current_file && <span>{t("transfers.currentFile")}: {task.current_file}</span>}
                {task.error_message && <span className="error">{task.error_message}</span>}
              </div>
              {expanded && <div className="transfer-details">
                <dl>
                  {!!task.command_preview?.length && <><dt>command</dt><dd><code>{task.command_preview.join(" ")}</code></dd></>}
                  <dt>exit code</dt><dd>{task.rsync_exit_code ?? "-"}</dd>
                  <dt>files</dt><dd>{task.files_done} / {task.files_total}</dd>
                  <dt>started</dt><dd>{formatDate(task.started_at)}</dd>
                  <dt>finished</dt><dd>{formatDate(task.finished_at)}</dd>
                  <dt>retries</dt><dd>{task.retry_count}</dd>
                </dl>
                {!!task.stderr_tail?.length && <pre className="transfer-log error">{task.stderr_tail.join("\n")}</pre>}
                <pre className="transfer-log">{(task.log_tail || []).join("\n")}</pre>
              </div>}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function Sparkline({ values }: { values: number[] }) {
  const width = 180;
  const height = 46;
  const points = values.length ? values : [0];
  const path = points.map((value, index) => {
    const x = points.length === 1 ? width : (index / (points.length - 1)) * width;
    const y = height - (Math.max(0, Math.min(100, value)) / 100) * height;
    return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} aria-hidden="true"><path d={path} /></svg>;
}

function MetricCard({ label, value, detail, values }: { label: string; value: string; detail?: string; values?: number[] }) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
      {values && <Sparkline values={values} />}
    </article>
  );
}

function DashboardApp({ toast }: { toast: (text: string, type?: "ok" | "error") => void }) {
  const [snapshot, setSnapshot] = useState<ResourceDashboard | null>(null);
  const [history, setHistory] = useState<ResourceDashboard[]>([]);
  async function load() {
    try {
      const next = await api.resources();
      setSnapshot(next);
      setHistory((current) => [...current, next].slice(-60));
    } catch (err) {
      toast(message(err, "Could not load dashboard"), "error");
    }
  }
  useEffect(() => {
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, []);
  const cpuValues = history.map((item) => item.cpu_percent ?? 0);
  const ramValues = history.map((item) => item.ram.percent);
  const swapValues = history.map((item) => item.swap.percent);
  const latest = snapshot;
  return (
    <section className="dashboard-app">
      <div className="toolbar">
        <button onClick={load}><RefreshCw size={17} />Refresh</button>
        <span>{latest?.scope === "admin" ? "Full server view" : "User-safe view"}</span>
      </div>
      {!latest && <p className="empty-state">Loading resource metrics...</p>}
      {latest && <>
        {!!latest.warnings.length && <div className="dashboard-warnings">{latest.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div>}
        <div className="metric-grid">
          <MetricCard label="CPU" value={`${latest.cpu_percent ?? 0}%`} detail={`load ${latest.load_average?.join(" / ") || "-"}`} values={cpuValues} />
          <MetricCard label="RAM" value={`${latest.ram.percent}%`} detail={`${formatSize(latest.ram.used)} / ${formatSize(latest.ram.total)}`} values={ramValues} />
          <MetricCard label="Swap" value={`${latest.swap.percent}%`} detail={`${formatSize(latest.swap.used)} / ${formatSize(latest.swap.total)}`} values={swapValues} />
          <MetricCard label="Uptime" value={formatDuration(latest.uptime_seconds)} detail={latest.temperature_c ? `CPU ${latest.temperature_c} C` : undefined} />
          {latest.webnas_service && <MetricCard label="webnas.service" value={latest.webnas_service} />}
        </div>
        <section className="dashboard-section">
          <h2>Allowed roots free space</h2>
          <div className="disk-list">{latest.allowed_roots.map((disk) => <div key={disk.path} className={disk.percent >= 90 ? "warn" : ""}><strong>{disk.path}</strong><span>{disk.percent}% used</span><span>{formatSize(disk.free)} free</span></div>)}</div>
        </section>
        {latest.scope === "admin" && <section className="dashboard-section">
          <h2>Disks and mountpoints</h2>
          <div className="disk-list">{latest.mountpoints.map((disk) => <div key={disk.mountpoint || disk.path} className={disk.percent >= 90 ? "warn" : ""}><strong>{disk.mountpoint || disk.path}</strong><span>{disk.fs_type || disk.device}</span><span>{disk.percent}% used</span><span>{formatSize(disk.free)} free</span></div>)}</div>
        </section>}
      </>}
    </section>
  );
}

function SettingsApp({ t, onLanguage, onTheme, onWallpaper, toast }: { t: T; onLanguage: (language: Language) => void; onTheme: (theme: Theme) => void; onWallpaper: (wallpaper: string) => void; toast: (text: string, type?: "ok" | "error") => void }) {
  const [tab, setTab] = useState("account");
  const [settings, setSettings] = useState<SettingsMe | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [groups, setGroups] = useState<AdminGroup[]>([]);
  const [system, setSystem] = useState<Record<string, unknown> | null>(null);
  const [safety, setSafety] = useState<ProxmoxSafety | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null);
  const [autoUpdate, setAutoUpdate] = useState<AutoUpdateSettings | null>(null);
  const [manualUpdateConfig, setManualUpdateConfig] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});

  async function load() {
    const meData = await api.settingsMe();
    setSettings(meData);
    onLanguage(meData.language);
    onTheme(meData.theme);
    onWallpaper(meData.wallpaper || "");
    if (meData.is_admin) {
      api.adminUsers().then(setUsers).catch(() => undefined);
      api.adminGroups().then(setGroups).catch(() => undefined);
      api.systemStatus().then(setSystem).catch(() => undefined);
      api.proxmoxSafety().then(setSafety).catch(() => undefined);
      api.autoUpdate().then(setAutoUpdate).catch(() => undefined);
    }
  }
  useEffect(() => { load().catch((err) => toast(message(err, t("error.generic")), "error")); }, []);

  async function submit(okText: string, fn: () => Promise<unknown>) {
    try {
      await fn();
      toast(okText);
      await load();
    } catch (err) {
      toast(message(err, t("error.generic")), "error");
    }
  }
  const adminPassword = () => form.admin_password || prompt(t("settings.adminPassword")) || "";
  async function checkUpdates() {
    try {
      const result = await api.checkUpdates();
      setUpdateStatus(result);
      toast(result.update_available ? "Update available" : "Application is up to date");
    } catch (err) {
      toast(message(err, "Could not check updates"), "error");
    }
  }
  async function downloadUpdates() {
    try {
      const result = await api.downloadUpdates(manualUpdateConfig);
      toast(`Update started, pid ${result.pid}`);
    } catch (err) {
      toast(message(err, "Could not start update"), "error");
    }
  }
  async function saveAutoUpdate() {
    if (!autoUpdate) return;
    try {
      const saved = await api.saveAutoUpdate({
        enabled: autoUpdate.enabled,
        interval_hours: autoUpdate.interval_hours,
        update_config: autoUpdate.update_config,
      });
      setAutoUpdate(saved);
      toast("Auto update settings saved");
    } catch (err) {
      toast(message(err, "Could not save auto update settings"), "error");
    }
  }
  async function runAutoUpdateNow() {
    try {
      const result = await api.runAutoUpdate(autoUpdate?.update_config || false);
      await api.autoUpdate().then(setAutoUpdate).catch(() => undefined);
      toast(result.updated ? `Auto update started, pid ${result.pid}` : "No update available");
    } catch (err) {
      toast(message(err, "Could not run auto update"), "error");
    }
  }
  async function saveWallpaper(wallpaper: string) {
    try {
      await api.updateSettings({ wallpaper });
      setSettings((current) => current ? { ...current, wallpaper } : current);
      onWallpaper(wallpaper);
      toast(t("settings.saved"));
    } catch (err) {
      toast(message(err, "Nie mozna zapisac tapety"), "error");
    }
  }
  function importWallpaper(file: File | undefined) {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast("Wybierz plik obrazu", "error");
      return;
    }
    if (file.size > 1_400_000) {
      toast("Tapeta jest za duza. Uzyj obrazu do 1.4 MB albo URL.", "error");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const wallpaper = String(reader.result || "");
      setForm((current) => ({ ...current, wallpaper }));
      saveWallpaper(wallpaper);
    };
    reader.onerror = () => toast("Nie mozna wczytac obrazu", "error");
    reader.readAsDataURL(file);
  }

  const settingsTabs = [
    { id: "account", icon: <Lock size={16} />, label: "Konto uzytkownika" },
    { id: "users", icon: <UserPlus size={16} />, label: "Uzytkownicy" },
    { id: "groups", icon: <Users size={16} />, label: "Grupy" },
    { id: "permissions", icon: <Shield size={16} />, label: "Uprawnienia" },
    { id: "system", icon: <Settings size={16} />, label: "System" }
  ];

  return (
    <section className="settings-shell settings-admin-shell">
      <header className="settings-topbar">
        <div>
          <strong>Ustawienia</strong>
          <span>System administration panel</span>
        </div>
      </header>
      <nav className="settings-sidebar" aria-label="Settings sections">
        <strong>Ustawienia</strong>
        <div className="settings-nav">
          {settingsTabs.map((item) => (
            <button key={item.id} className={`settings-nav-item ${tab === item.id ? "active" : ""}`} onClick={() => setTab(item.id)} aria-current={tab === item.id ? "page" : undefined}>{item.icon}<span>{item.label}</span></button>
          ))}
        </div>
      </nav>
      <main className="settings-content">
          {safety?.is_proxmox && safety.safe_mode_enabled && (
            <div className="safe-mode-banner alert-warning">
              <Shield size={18} />
              <div>
                <strong>Proxmox VE Safe Mode active</strong>
                <span>Operations on Proxmox system paths, storage, cluster, network, protected users, groups, and services are blocked.</span>
              </div>
            </div>
          )}
          {tab === "account" && settings && (
            <section className="settings-section">
              <article className="settings-card">
                <header className="settings-card-header"><div><h2 className="settings-card-title">Konto uzytkownika</h2><p className="settings-card-description">Preferencje interfejsu i zmiana hasla lokalnego konta.</p></div></header>
                <div className="settings-form form-grid">
                  <label className="form-field" htmlFor="settings-language"><span className="form-label">{t("settings.language")}</span><select id="settings-language" className="form-input" value={settings.language} onChange={(e) => submit(t("settings.saved"), async () => { const language = e.target.value as Language; await api.updateSettings({ language }); onLanguage(language); })}>{supportedLanguages.map((language) => <option key={language}>{language}</option>)}</select></label>
                  <label className="form-field" htmlFor="settings-theme"><span className="form-label">{t("settings.theme")}</span><select id="settings-theme" className="form-input" value={settings.theme} onChange={(e) => submit(t("settings.saved"), async () => { const theme = e.target.value as Theme; await api.updateSettings({ theme }); onTheme(theme); })}><option value="light">{t("settings.light")}</option><option value="dark">{t("settings.dark")}</option><option value="system">{t("settings.systemTheme")}</option></select></label>
                  <label className="form-field" htmlFor="settings-startup-windows"><span className="form-label">Okna po zalogowaniu</span><select id="settings-startup-windows" className="form-input" value={settings.startup_windows} onChange={(e) => submit(t("settings.saved"), async () => { const startup_windows = e.target.value as SettingsMe["startup_windows"]; await api.updateSettings({ startup_windows }); setSettings({ ...settings, startup_windows }); })}><option value="last">Otworz ostatnio otwarte okna</option><option value="none">Nie otwieraj nic</option></select><span className="form-help">Dotyczy kolejnego logowania na tym urzadzeniu.</span></label>
                  <label className="form-field" htmlFor="settings-wallpaper"><span className="form-label">Tapeta pulpitu</span><input id="settings-wallpaper" className="form-input" placeholder="https://... albo data:image/..." value={form.wallpaper ?? settings.wallpaper ?? ""} onChange={(e) => setForm({ ...form, wallpaper: e.target.value })} /><span className="form-help">URL obrazu albo plik ponizej. Zapisuje sie w profilu i wczytuje po kazdym logowaniu.</span></label>
                  <label className="form-field" htmlFor="settings-wallpaper-file"><span className="form-label">Plik tapety</span><input id="settings-wallpaper-file" className="form-input" type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={(e) => importWallpaper(e.target.files?.[0])} /><span className="form-help">Dla lokalnego obrazu uzyj pliku do 1.4 MB.</span></label>
                  <label className="form-field" htmlFor="settings-current-password"><span className="form-label">{t("settings.currentPassword")}</span><input id="settings-current-password" className="form-input" type="password" onChange={(e) => setForm({ ...form, current_password: e.target.value })} /></label>
                  <label className="form-field" htmlFor="settings-new-password"><span className="form-label">{t("settings.newPassword")}</span><input id="settings-new-password" className="form-input" type="password" onChange={(e) => setForm({ ...form, new_password: e.target.value })} /></label>
                </div>
                <div className="button-row"><button className="button button-primary" onClick={() => submit(t("settings.passwordChanged"), () => api.changeMyPassword(form.current_password, form.new_password))}><Lock size={16} />{t("action.changePassword")}</button><button className="button button-secondary" onClick={() => saveWallpaper(form.wallpaper ?? settings.wallpaper ?? "")}>Zapisz tapete</button><button className="button button-secondary" onClick={() => { setForm({ ...form, wallpaper: "" }); saveWallpaper(""); }}>Usun tapete</button></div>
              </article>
              <article className="settings-card">
                <header className="settings-card-header"><div><h2 className="settings-card-title">Profil systemowy</h2><p className="settings-card-description">Dane konta zwracane przez system.</p></div></header>
                <dl className="info-grid">
                  <dt>{t("settings.username")}</dt><dd>{settings.username}</dd>
                  <dt>{t("settings.uid")}</dt><dd>{settings.uid}</dd>
                  <dt>{t("settings.gid")}</dt><dd>{settings.gid}</dd>
                  <dt>{t("settings.groupsLabel")}</dt><dd>{settings.groups.map((group) => <span key={group} className="badge">{group}</span>)}</dd>
                  <dt>{t("settings.home")}</dt><dd>{settings.home}</dd>
                </dl>
              </article>
            </section>
          )}
          {tab === "users" && (
            <section className="settings-section">
              {!settings?.is_admin && <p className="alert-danger">{t("settings.adminOnly")}</p>}
              {settings?.is_admin && <>
                <article className="settings-card">
                  <header className="settings-card-header"><div><h2 className="settings-card-title">Dodaj uzytkownika</h2><p className="settings-card-description">Utworz lokalne konto systemowe. Operacja wymaga hasla administratora.</p></div></header>
                  <div className="settings-form form-grid">
                    <label className="form-field" htmlFor="new-user-username"><span className="form-label">Nazwa uzytkownika</span><input id="new-user-username" className="form-input" placeholder={t("settings.username")} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
                    <label className="form-field" htmlFor="new-user-password"><span className="form-label">Haslo</span><input id="new-user-password" className="form-input" type="password" placeholder={t("auth.password")} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
                    <label className="form-field" htmlFor="new-user-groups"><span className="form-label">Grupy</span><input id="new-user-groups" className="form-input" placeholder="sudo, users" onChange={(e) => setForm({ ...form, groups: e.target.value })} /><span className="form-help">Oddziel grupy przecinkami</span></label>
                    <label className="form-field" htmlFor="new-user-shell"><span className="form-label">Shell</span><input id="new-user-shell" className="form-input" placeholder={t("settings.shell")} onChange={(e) => setForm({ ...form, shell: e.target.value })} /></label>
                    <label className="form-field" htmlFor="new-user-gecos"><span className="form-label">Opis / GECOS</span><input id="new-user-gecos" className="form-input" placeholder={t("settings.gecos")} onChange={(e) => setForm({ ...form, gecos: e.target.value })} /></label>
                    <label className="form-field system-required" htmlFor="new-user-admin-password"><span className="form-label">Haslo administratora</span><input id="new-user-admin-password" className="form-input" type="password" placeholder={t("settings.adminPassword")} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} /><span className="form-help">Wymagane do operacji systemowej</span></label>
                  </div>
                  <button className="button button-primary" onClick={() => submit(t("settings.addUser"), () => api.createUser({ username: form.username, password: form.password, groups: (form.groups || "").split(",").map((item) => item.trim()).filter(Boolean), shell: form.shell || undefined, gecos: form.gecos || undefined, create_home: true, admin_password: adminPassword() }))}><UserPlus size={16} />{t("settings.addUser")}</button>
                </article>
                <article className="settings-card">
                  <header className="settings-card-header"><div><h2 className="settings-card-title">{t("settings.userList")}</h2><p className="settings-card-description">Lokalne konta uzytkownikow i szybkie akcje administracyjne.</p></div></header>
                  {users.length === 0 ? <div className="empty-state">Brak lokalnych uzytkownikow do wyswietlenia.</div> : <div className="users-table">
                    <div className="users-table-header"><span>uzytkownik</span><span>UID</span><span>grupy</span><span>shell</span><span>home</span><span>status</span><span>akcje</span></div>
                    {users.map((item) => <div className="user-row" key={item.username}><strong>{item.username}</strong><code>{item.uid}</code><span className="badge-list">{item.groups.map((group) => <span key={group} className="badge">{group}</span>)}</span><span>{item.shell || "-"}</span><span>{item.home || "-"}</span><span><span className="badge badge-success">{item.manageable ? "active" : "protected"}</span></span><div className="user-actions"><button className="button button-secondary" title={t("action.lock")} aria-label={`${t("action.lock")} ${item.username}`} onClick={() => submit(t("action.lock"), () => api.lockUser(item.username, adminPassword()))}>{t("action.lock")}</button><button className="button button-secondary" title={t("action.unlock")} aria-label={`${t("action.unlock")} ${item.username}`} onClick={() => submit(t("action.unlock"), () => api.unlockUser(item.username, adminPassword()))}>{t("action.unlock")}</button><button className="button button-warning" title="Reset password" aria-label={`Reset password ${item.username}`} onClick={() => { const password = prompt("New password"); if (password) submit(t("settings.passwordChanged"), () => api.changeUserPassword(item.username, { new_password: password, admin_password: adminPassword() })); }}>Reset</button><button className="button button-secondary" title={t("action.add")} aria-label={`${t("action.add")} group for ${item.username}`} onClick={() => { const group = prompt("Group to add"); if (group) submit(t("action.add"), () => api.patchUser(item.username, { groups_add: [group], admin_password: adminPassword() })); }}>{t("action.add")}</button><button className="button button-secondary" title={t("action.remove")} aria-label={`${t("action.remove")} group from ${item.username}`} onClick={() => { const group = prompt("Group to remove"); if (group) submit(t("action.remove"), () => api.patchUser(item.username, { groups_remove: [group], admin_password: adminPassword() })); }}>{t("action.remove")}</button><button className="button button-secondary" title="Home" aria-label={`Create home for ${item.username}`} onClick={() => submit("Home created", () => api.patchUser(item.username, { create_home: true, admin_password: adminPassword() }))}>Home</button><button className="button button-secondary" title="Quota" aria-label={`Set quota for ${item.username}`} onClick={() => { const quota = prompt("Soft quota MB"); if (quota) submit("Quota saved", () => api.setUserQuota(item.username, { soft_mb: Number(quota), admin_password: adminPassword() })); }}>Quota</button><button className="button button-danger" title={t("action.delete")} aria-label={`${t("action.delete")} ${item.username}`} onClick={() => window.confirm(t("settings.confirmDelete")) && submit(t("action.delete"), () => api.deleteUser(item.username, adminPassword()))}>{t("action.delete")}</button></div></div>)}
                  </div>}
                </article>
              </>}
            </section>
          )}
          {tab === "groups" && (
            <section className="settings-section">
              {!settings?.is_admin && <p className="alert-danger">{t("settings.adminOnly")}</p>}
              {settings?.is_admin && <>
                <article className="settings-card"><header className="settings-card-header"><div><h2 className="settings-card-title">Grupy</h2><p className="settings-card-description">Tworzenie grup i zarzadzanie czlonkostwem.</p></div></header><div className="settings-form form-grid"><label className="form-field" htmlFor="group-name"><span className="form-label">{t("settings.groupName")}</span><input id="group-name" className="form-input" placeholder={t("settings.groupName")} onChange={(e) => setForm({ ...form, groupname: e.target.value })} /></label><label className="form-field" htmlFor="group-member"><span className="form-label">{t("settings.member")}</span><input id="group-member" className="form-input" placeholder={t("settings.member")} onChange={(e) => setForm({ ...form, member: e.target.value })} /></label><label className="form-field system-required" htmlFor="group-admin-password"><span className="form-label">{t("settings.adminPassword")}</span><input id="group-admin-password" className="form-input" type="password" placeholder={t("settings.adminPassword")} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} /></label></div><button className="button button-primary" onClick={() => submit(t("settings.addGroup"), () => api.createGroup({ groupname: form.groupname, admin_password: adminPassword() }))}><Users size={16} />{t("settings.addGroup")}</button></article>
                <article className="settings-card"><header className="settings-card-header"><div><h2 className="settings-card-title">{t("settings.groupList")}</h2><p className="settings-card-description">Lokalne grupy systemowe i przypisani czlonkowie.</p></div></header><div className="admin-list">{groups.map((item) => <div key={item.name}><strong>{item.name}</strong><code>{item.gid}</code><span className="badge-list">{item.members.map((member) => <span key={member} className="badge">{member}</span>)}</span><button className="button button-secondary" onClick={() => submit(t("action.add"), () => api.addGroupMember(item.name, { username: form.member, admin_password: adminPassword() }))}>{t("action.add")}</button><button className="button button-secondary" onClick={() => submit(t("action.remove"), () => api.removeGroupMember(item.name, form.member, adminPassword()))}>{t("action.remove")}</button><button className="button button-danger" onClick={() => window.confirm(t("settings.confirmDelete")) && submit(t("action.delete"), () => api.deleteGroup(item.name, adminPassword()))}>{t("action.delete")}</button></div>)}</div></article>
              </>}
            </section>
          )}
          {tab === "permissions" && (
            <section className="settings-section">
              <article className="settings-card"><header className="settings-card-header"><div><h2 className="settings-card-title">Uprawnienia</h2><p className="settings-card-description">Zmiana trybu i wlasciciela pliku bez zmiany backendowej logiki bezpieczenstwa.</p></div></header><div className="settings-form form-grid"><label className="form-field" htmlFor="perm-path"><span className="form-label">{t("settings.filePath")}</span><input id="perm-path" className="form-input" placeholder={t("settings.filePath")} onChange={(e) => setForm({ ...form, perm_path: e.target.value })} /></label><label className="form-field" htmlFor="perm-mode"><span className="form-label">{t("settings.mode")}</span><input id="perm-mode" className="form-input" placeholder={t("settings.mode")} onChange={(e) => setForm({ ...form, mode: e.target.value })} /></label><label className="form-field" htmlFor="perm-owner"><span className="form-label">{t("settings.owner")}</span><input id="perm-owner" className="form-input" placeholder={t("settings.owner")} onChange={(e) => setForm({ ...form, owner: e.target.value })} /></label><label className="form-field" htmlFor="perm-group"><span className="form-label">{t("settings.group")}</span><input id="perm-group" className="form-input" placeholder={t("settings.group")} onChange={(e) => setForm({ ...form, group: e.target.value })} /></label><label className="form-field system-required" htmlFor="perm-admin-password"><span className="form-label">{t("settings.adminPassword")}</span><input id="perm-admin-password" className="form-input" type="password" placeholder={t("settings.adminPassword")} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} /></label></div><div className="button-row"><button className="button button-primary" onClick={() => submit(t("settings.applyChmod"), () => api.chmod(form.perm_path, form.mode))}><Shield size={16} />{t("settings.applyChmod")}</button><button className="button button-secondary" onClick={() => submit(t("settings.applyOwner"), () => api.chown({ path: form.perm_path, owner: form.owner || undefined, group: form.group || undefined, admin_password: adminPassword() }))}><Shield size={16} />{t("settings.applyOwner")}</button></div></article>
            </section>
          )}
          {tab === "system" && (
            <section className="settings-section">
              {!settings?.is_admin && <p className="alert-danger">{t("settings.adminOnly")}</p>}
              {settings?.is_admin && system && <>
                <article className="settings-card"><header className="settings-card-header"><div><h2 className="settings-card-title">System</h2><p className="settings-card-description">Status instalacji, bezpieczenstwo Proxmox i aktualizacje.</p></div></header><dl className="info-grid">{Object.entries(system).map(([key, value]) => <React.Fragment key={key}><dt>{t(`settings.${key}`) || key}</dt><dd>{String(value)}</dd></React.Fragment>)}</dl></article>
                {safety && <article className="settings-card"><header className="settings-card-header"><div><h2 className="settings-card-title">Bezpieczenstwo</h2><p className="settings-card-description">Ograniczenia ochronne wykryte dla hosta.</p></div></header><dl className="info-grid"><dt>Proxmox</dt><dd>{String(safety.is_proxmox)}</dd><dt>Safe Mode</dt><dd>{String(safety.safe_mode_enabled)}</dd><dt>Service user</dt><dd>{safety.service_user}</dd><dt>Protected paths</dt><dd>{safety.protected_paths.slice(0, 8).join(", ")}{safety.protected_paths.length > 8 ? "..." : ""}</dd><dt>Warnings</dt><dd>{safety.warnings.join(" ") || "-"}</dd></dl></article>}
                {autoUpdate && <article className="settings-card"><header className="settings-card-header"><div><h2 className="settings-card-title">Auto update</h2><p className="settings-card-description">Automatycznie sprawdza GitHub i uruchamia istniejacy instalator aktualizacji, gdy pojawi sie nowy commit.</p></div><span className={`badge ${autoUpdate.enabled ? "badge-success" : ""}`}>{autoUpdate.enabled ? "enabled" : "disabled"}</span></header><div className="settings-form form-grid"><label className="form-field switch-field" htmlFor="auto-update-enabled"><span className="form-label">Wlacz auto update</span><label className="switch-control"><input id="auto-update-enabled" type="checkbox" checked={autoUpdate.enabled} onChange={(e) => setAutoUpdate({ ...autoUpdate, enabled: e.target.checked })} /><span /> enabled</label><span className="form-help">Scheduler dziala w procesie WebNAS i zapisuje stan w katalogu danych.</span></label><label className="form-field" htmlFor="auto-update-interval"><span className="form-label">Interwal sprawdzania</span><input id="auto-update-interval" className="form-input" type="number" min={1} max={168} value={autoUpdate.interval_hours} onChange={(e) => setAutoUpdate({ ...autoUpdate, interval_hours: Math.max(1, Math.min(168, Number(e.target.value) || 24)) })} /><span className="form-help">Godziny, zakres 1-168.</span></label><label className="form-field switch-field" htmlFor="auto-update-config"><span className="form-label">Aktualizuj config</span><label className="switch-control"><input id="auto-update-config" type="checkbox" checked={autoUpdate.update_config} onChange={(e) => setAutoUpdate({ ...autoUpdate, update_config: e.target.checked })} /><span /> --update-config</label><span className="form-help">Opcjonalnie regeneruje config podczas aktualizacji.</span></label></div><dl className="info-grid update-grid"><dt>Last checked</dt><dd>{autoUpdate.last_checked ? formatDate(autoUpdate.last_checked) : "-"}</dd><dt>Last run</dt><dd>{autoUpdate.last_run ? formatDate(autoUpdate.last_run) : "-"}</dd><dt>Next check</dt><dd>{autoUpdate.next_check ? formatDate(autoUpdate.next_check) : "-"}</dd><dt>Last PID</dt><dd>{autoUpdate.last_pid || "-"}</dd><dt>Last error</dt><dd>{autoUpdate.last_error || "-"}</dd></dl><div className="button-row"><button className="button button-primary" onClick={saveAutoUpdate}><Settings size={16} />Save auto update</button><button className="button button-secondary" onClick={runAutoUpdateNow}><RefreshCw size={16} />Run now</button></div></article>}
                <article className="settings-card"><header className="settings-card-header"><div><h2 className="settings-card-title">Aktualizacje i restart</h2><p className="settings-card-description">Dostepne dla aktywnej sesji administratora. Haslo nie jest wymagane ponownie.</p></div><span className="badge badge-success">admin session</span></header><div className="settings-form form-grid"><label className="form-field switch-field" htmlFor="manual-update-config"><span className="form-label">Aktualizuj config przy recznym update</span><label className="switch-control"><input id="manual-update-config" type="checkbox" checked={manualUpdateConfig} onChange={(e) => setManualUpdateConfig(e.target.checked)} /><span /> --update-config</label><span className="form-help">Uzywa tej samej opcji instalatora co auto-update.</span></label></div><div className="button-row"><button className="button button-secondary" onClick={checkUpdates}><Search size={16} />Check updates</button><button className="button button-primary" onClick={downloadUpdates}><Download size={16} />Download updates</button><button className="button button-danger" onClick={() => submit(t("action.restart"), () => api.restartSystem())}><RefreshCw size={16} />{t("action.restart")}</button></div>{updateStatus && <dl className="info-grid update-grid"><dt>Update</dt><dd>{updateStatus.update_available ? "Available" : "Up to date"}</dd><dt>Branch</dt><dd>{updateStatus.branch}</dd><dt>Local</dt><dd>{updateStatus.local.slice(0, 12)}</dd><dt>Remote</dt><dd>{updateStatus.remote.slice(0, 12)}</dd></dl>}</article>
              </>}
            </section>
          )}
      </main>
    </section>
  );
}

function LogsApp({ toast }: { toast: (text: string, type?: "ok" | "error") => void }) {
  const [logs, setLogs] = useState<SystemLogs | null>(null);
  async function load() {
    try {
      setLogs(await api.systemLogs());
    } catch (err) {
      toast(message(err, "Could not load logs"), "error");
    }
  }
  useEffect(() => { load(); }, []);
  return (
    <section className="logs-app">
      <div className="toolbar">
        <button onClick={load}><RefreshCw size={17} />Refresh</button>
        <span>{logs?.source || "logs"}</span>
      </div>
      <pre>{(logs?.lines || []).join("\n")}</pre>
    </section>
  );
}

function ServicesApp({ toast }: { toast: (text: string, type?: "ok" | "error") => void }) {
  const [services, setServices] = useState<SystemdService[]>([]);
  const [selected, setSelected] = useState("");
  const [logs, setLogs] = useState<SystemLogs | null>(null);
  const active = services.find((service) => service.name === selected);
  async function load() {
    try {
      const next = await api.systemdServices();
      setServices(next);
      const name = selected || next[0]?.name || "";
      if (!selected && name) setSelected(name);
      if (name) setLogs(await api.systemdServiceLogs(name));
    } catch (err) {
      toast(message(err, "Could not load services"), "error");
    }
  }
  useEffect(() => { load(); }, [selected]);
  async function run(action: "start" | "stop" | "restart" | "enable" | "disable") {
    if (!selected) return;
    if (action === "restart" && !window.confirm(`Restart ${selected}?`)) return;
    const admin_password = prompt("Admin password") || "";
    if (!admin_password) return;
    try {
      await api.systemdServiceAction(selected, action, admin_password, action === "restart");
      toast(`${action} completed`);
      await load();
    } catch (err) {
      toast(message(err, "Service action failed"), "error");
    }
  }
  return (
    <section className="services-app">
      <aside className="store-list">
        {services.map((service) => <button key={service.name} className={selected === service.name ? "active" : ""} onClick={() => setSelected(service.name)}><strong>{service.name}</strong><span>{service.status} / {service.enabled}</span></button>)}
      </aside>
      <main className="store-detail">
        <header>
          <div><h2>Services</h2><p>Only allowlisted or WebNAS-managed systemd services are visible.</p></div>
          {active && <strong>{active.status}</strong>}
        </header>
        {active && <>
          <div className="toolbar">
            <button onClick={() => run("start")}>Start</button>
            <button onClick={() => run("stop")}>Stop</button>
            <button onClick={() => run("restart")}>Restart</button>
            <button onClick={() => run("enable")}>Enable</button>
            <button onClick={() => run("disable")}>Disable</button>
            <button onClick={load}><RefreshCw size={16} />Refresh</button>
          </div>
          <dl className="info-grid">
            <dt>Status</dt><dd>{active.status} {active.sub_state}</dd>
            <dt>Enabled</dt><dd>{active.enabled}</dd>
            <dt>Uptime</dt><dd>{formatDuration(active.uptime_seconds)}</dd>
            <dt>Managed</dt><dd>{String(active.managed_by_webnas)}</dd>
            <dt>Last error</dt><dd>{active.last_error || "-"}</dd>
          </dl>
          <section className="store-section">
            <h3>Logs</h3>
            <pre className="store-log">{(logs?.lines || []).join("\n")}</pre>
          </section>
        </>}
      </main>
    </section>
  );
}

const emptyMount: NetworkMountPayload = {
  admin_password: "",
  name: "",
  type: "smb",
  host: "",
  share: "",
  export_path: "",
  remote_path: "",
  username: "",
  password: "",
  domain: "",
  smb_version: "auto",
  nfs_version: "auto",
  ssh_port: 22,
  ssh_auth: "key",
  read_only: false,
  persistent: true,
  file_mode: "0644",
  dir_mode: "0755",
  noexec: true,
  advanced_options: [],
  allowed_users: [],
  allowed_groups: []
};

function NetworkMountsApp({ toast }: { toast: (text: string, type?: "ok" | "error") => void }) {
  const [mounts, setMounts] = useState<NetworkMount[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [form, setForm] = useState<NetworkMountPayload>(emptyMount);
  const [logs, setLogs] = useState<string[]>([]);
  const [dryRun, setDryRun] = useState<string[]>([]);
  const active = mounts.find((mount) => mount.id === selected);
  async function load() {
    try {
      const next = await api.mounts();
      setMounts(next);
      if (!selected && next[0]) setSelected(next[0].id);
      const id = selected || next[0]?.id;
      if (id) setLogs((await api.mountLogs(id)).lines);
    } catch (err) {
      toast(message(err, "Could not load network mounts"), "error");
    }
  }
  useEffect(() => { load(); }, [selected]);
  function adminPassword() {
    return prompt("Admin password") || "";
  }
  function fillFromMount(mount: NetworkMount) {
    setSelected(mount.id);
    setForm({
      ...emptyMount,
      admin_password: "",
      name: mount.name,
      type: mount.type,
      host: mount.host,
      mount_point: mount.mount_point,
      read_only: mount.read_only,
      persistent: mount.persistent,
      allowed_users: mount.allowed_users,
      allowed_groups: mount.allowed_groups,
      username: String(mount.config.username || ""),
      smb_version: String(mount.config.smb_version || "auto"),
      nfs_version: String(mount.config.nfs_version || "auto"),
      ssh_port: Number(mount.config.ssh_port || 22),
      ssh_auth: String(mount.config.ssh_auth || "key") as "key" | "password",
      file_mode: String(mount.config.file_mode || "0644"),
      dir_mode: String(mount.config.dir_mode || "0755"),
      noexec: Boolean(mount.config.noexec ?? true),
      advanced_options: Array.isArray(mount.config.advanced_options) ? mount.config.advanced_options as string[] : []
    });
  }
  async function save() {
    const admin_password = form.admin_password || adminPassword();
    if (!admin_password) return;
    try {
      const payload = { ...form, admin_password };
      const saved = selected ? await api.updateMount(selected, payload) : await api.createMount(payload);
      setSelected(saved.id);
      setForm({ ...emptyMount });
      toast("Network mount saved");
      await load();
    } catch (err) {
      toast(message(err, "Mount configuration rejected"), "error");
    }
  }
  async function action(name: "mount" | "unmount" | "remount" | "test", dry = false) {
    if (!selected) return;
    const admin_password = adminPassword();
    if (!admin_password) return;
    try {
      const result = await api.mountAction(selected, name, admin_password, dry) as { command?: string[]; dependencies?: string[] };
      if (dry) setDryRun([...(result.dependencies || []), (result.command || []).join(" ")]);
      toast(dry ? "Dry-run ready" : `${name} queued`);
      await load();
    } catch (err) {
      toast(message(err, "Mount operation failed"), "error");
    }
  }
  async function remove() {
    if (!selected || !window.confirm("Delete network mount?")) return;
    const admin_password = adminPassword();
    if (!admin_password) return;
    try {
      await api.deleteMount(selected, admin_password);
      setSelected("");
      toast("Network mount deleted");
      await load();
    } catch (err) {
      toast(message(err, "Could not delete mount"), "error");
    }
  }
  const writableWarning = !form.read_only && (!form.noexec || !form.uid || !form.gid);
  return (
    <section className="mounts-app">
      <aside className="store-list">
        <button className={!selected ? "active" : ""} onClick={() => { setSelected(""); setForm(emptyMount); }}>New resource</button>
        {mounts.map((mount) => <button key={mount.id} className={selected === mount.id ? "active" : ""} onClick={() => fillFromMount(mount)}><strong>{mount.name}</strong><span>{mount.type} {mount.host} {mount.status}</span></button>)}
      </aside>
      <main className="store-detail">
        <header>
          <div><h2>Network resources</h2><p>SMB/CIFS, NFS, SSHFS and WebDAV mounts managed by WebNAS.</p></div>
          {active && <strong>{active.status}</strong>}
        </header>
        {writableWarning && <p className="safe-mode-banner"><Shield size={18} /> Writable mounts with broad ownership or executable files can expose more of the system than intended.</p>}
        <div className="form-grid">
          <input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as NetworkMountPayload["type"] })}><option value="smb">SMB/CIFS</option><option value="nfs">NFS</option><option value="sshfs">SSHFS</option><option value="webdav">WebDAV</option></select>
          <input placeholder="Host / IP" value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} />
          <input placeholder="Mount point, optional" value={form.mount_point || ""} onChange={(e) => setForm({ ...form, mount_point: e.target.value })} />
          {form.type === "smb" && <><input placeholder="Share" value={form.share || ""} onChange={(e) => setForm({ ...form, share: e.target.value })} /><input placeholder="Domain / workgroup" value={form.domain || ""} onChange={(e) => setForm({ ...form, domain: e.target.value })} /><select value={form.smb_version} onChange={(e) => setForm({ ...form, smb_version: e.target.value })}><option>auto</option><option>2.1</option><option>3.0</option><option>3.1.1</option></select></>}
          {form.type === "nfs" && <><input placeholder="Export path" value={form.export_path || ""} onChange={(e) => setForm({ ...form, export_path: e.target.value })} /><select value={form.nfs_version} onChange={(e) => setForm({ ...form, nfs_version: e.target.value })}><option>auto</option><option>3</option><option>4</option><option>4.1</option><option>4.2</option></select></>}
          {form.type === "sshfs" && <><input placeholder="Remote path" value={form.remote_path || ""} onChange={(e) => setForm({ ...form, remote_path: e.target.value })} /><input type="number" placeholder="Port" value={form.ssh_port} onChange={(e) => setForm({ ...form, ssh_port: Number(e.target.value) })} /><select value={form.ssh_auth} onChange={(e) => setForm({ ...form, ssh_auth: e.target.value as "key" | "password" })}><option value="key">SSH key</option><option value="password">Password</option></select></>}
          {form.type === "webdav" && <input placeholder="WebDAV URL" value={form.remote_path || ""} onChange={(e) => setForm({ ...form, remote_path: e.target.value })} />}
          <input placeholder="Username" value={form.username || ""} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <input placeholder="Password, stored in 0600 credentials file" type="password" value={form.password || ""} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <input placeholder="uid" value={form.uid || ""} onChange={(e) => setForm({ ...form, uid: e.target.value })} />
          <input placeholder="gid" value={form.gid || ""} onChange={(e) => setForm({ ...form, gid: e.target.value })} />
          <input placeholder="file_mode" value={form.file_mode} onChange={(e) => setForm({ ...form, file_mode: e.target.value })} />
          <input placeholder="dir_mode" value={form.dir_mode} onChange={(e) => setForm({ ...form, dir_mode: e.target.value })} />
          <input placeholder="Advanced options, comma separated" value={(form.advanced_options || []).join(",")} onChange={(e) => setForm({ ...form, advanced_options: e.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} />
          <input placeholder="Allowed users, comma separated" value={(form.allowed_users || []).join(",")} onChange={(e) => setForm({ ...form, allowed_users: e.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} />
          <label><input type="checkbox" checked={form.read_only} onChange={(e) => setForm({ ...form, read_only: e.target.checked })} /> read-only</label>
          <label><input type="checkbox" checked={form.persistent} onChange={(e) => setForm({ ...form, persistent: e.target.checked })} /> persistent automount</label>
          <label><input type="checkbox" checked={form.noexec} onChange={(e) => setForm({ ...form, noexec: e.target.checked })} /> noexec</label>
        </div>
        <div className="toolbar">
          <button onClick={save}>Save</button>
          <button disabled={!selected} onClick={() => action("test")}>Test</button>
          <button disabled={!selected} onClick={() => action("mount")}>Mount</button>
          <button disabled={!selected} onClick={() => action("unmount")}>Unmount</button>
          <button disabled={!selected} onClick={() => action("remount")}>Remount</button>
          <button disabled={!selected} onClick={() => action("mount", true)}>Dry-run</button>
          <button disabled={!selected} onClick={remove}>Delete</button>
        </div>
        {!!dryRun.length && <pre className="store-log">{dryRun.join("\n")}</pre>}
        {active && <section className="store-section">
          <h3>Details</h3>
          <dl className="info-grid"><dt>Mount point</dt><dd>{active.mount_point}</dd><dt>Remote</dt><dd>{active.remote}</dd><dt>Filesystem</dt><dd>{active.fs ? `${active.fs.fs_type} ${formatSize(active.fs.free)} free` : "-"}</dd><dt>Error</dt><dd>{active.last_error || "-"}</dd></dl>
        </section>}
        {active && !!active.jobs.length && <section className="store-section"><h3>Jobs</h3><div className="admin-list">{active.jobs.map((job) => <div key={job.id}><strong>{job.action}</strong><span>{job.status}</span><span>{job.exit_code ?? "-"} {job.error}</span></div>)}</div></section>}
        <section className="store-section"><h3>Logs</h3><pre className="store-log">{logs.join("\n")}</pre></section>
      </main>
    </section>
  );
}

const emptyShare: SambaShare = {
  name: "",
  path: "",
  comment: "",
  enabled: true,
  browseable: true,
  hidden: false,
  read_only: true,
  guest_ok: false,
  valid_users: [],
  write_list: [],
  read_list: [],
  admin_users: [],
  force_user: "",
  force_group: "",
  veto_files: "",
  recycle_bin: false,
  create_directory: true,
  directory_owner: "",
  directory_group: "",
  directory_mode: "",
  advanced_options: {},
  create_mask: "0664",
  directory_mask: "0775",
  allow_proxmox_storage: false
};

function parseTokens(value: string) {
  return value.split(/[,\s]+/).map((item) => item.trim()).filter(Boolean);
}

function tokenText(value?: string[]) {
  return (value || []).join(", ");
}

function SambaApp({ toast, initialPath }: { toast: (text: string, type?: "ok" | "error") => void; initialPath?: string }) {
  const [status, setStatus] = useState<SambaStatus | null>(null);
  const [users, setUsers] = useState<SambaUser[]>([]);
  const [config, setConfig] = useState<SambaConfig>({ shares: [], global_options: {} });
  const [draft, setDraft] = useState<SambaShare>({ ...emptyShare, path: initialPath || "" });
  const [preview, setPreview] = useState("");
  const [validation, setValidation] = useState("");
  const [tab, setTab] = useState<"shares" | "users" | "advanced">("shares");
  async function load() {
    try {
      const [nextStatus, nextUsers, nextConfig] = await Promise.all([api.sambaStatus(), api.sambaUsers(), api.appConfig("samba")]);
      setStatus(nextStatus);
      setUsers(nextUsers);
      setConfig({ shares: nextConfig.shares || [], global_options: nextConfig.global_options || {} });
    } catch (err) {
      toast(message(err, "Nie mozna wczytac modulu Samba"), "error");
    }
  }
  useEffect(() => { load(); }, []);
  useEffect(() => { if (initialPath) setDraft((current) => ({ ...current, path: initialPath })); }, [initialPath]);
  async function refreshPreview(next = config) {
    try {
      const result = await api.sambaPreview(next);
      setPreview(result.config);
      setValidation(`${result.validation.ok ? "OK" : "Blad"}\n${result.validation.stderr || result.validation.stdout || ""}`);
    } catch (err) {
      toast(message(err, "Konfiguracja Samby jest niepoprawna"), "error");
    }
  }
  async function applyConfig(next = config) {
    try {
      const nextStatus = await api.sambaApply(next);
      setStatus(nextStatus);
      toast("Konfiguracja Samby zastosowana");
      await load();
    } catch (err) {
      toast(message(err, "Nie mozna zastosowac konfiguracji Samby"), "error");
    }
  }
  function upsertShare() {
    const share = { ...draft, valid_users: draft.valid_users || [], write_list: draft.write_list || [], read_list: draft.read_list || [], admin_users: draft.admin_users || [], advanced_options: draft.advanced_options || {} };
    const next = { ...config, shares: [...config.shares.filter((item) => item.name !== share.name), share] };
    setConfig(next);
    setDraft({ ...emptyShare });
    refreshPreview(next);
  }
  async function service(action: "start" | "stop" | "restart" | "reload") {
    const admin_password = prompt("Haslo administratora") || "";
    if (!admin_password) return;
    try {
      const result = await api.sambaService(action, admin_password);
      setStatus(result.status);
      toast(`Samba: ${action}`);
    } catch (err) {
      toast(message(err, "Operacja uslugi Samba nie powiodla sie"), "error");
    }
  }
  async function enableUser(username: string) {
    const password = prompt(`Nowe haslo SMB dla ${username}`) || "";
    const admin_password = prompt("Haslo administratora") || "";
    if (!password || !admin_password) return;
    try {
      await api.enableSambaUser(username, password, admin_password);
      toast("Uzytkownik SMB wlaczony");
      await load();
    } catch (err) {
      toast(message(err, "Nie mozna wlaczyc uzytkownika SMB"), "error");
    }
  }
  async function disableUser(username: string) {
    const admin_password = prompt("Haslo administratora") || "";
    if (!admin_password) return;
    try {
      await api.disableSambaUser(username, admin_password);
      toast("Uzytkownik SMB wylaczony");
      await load();
    } catch (err) {
      toast(message(err, "Nie mozna wylaczyc uzytkownika SMB"), "error");
    }
  }
  const sharedPaths = new Set(config.shares.filter((share) => share.enabled).map((share) => share.path));
  return (
    <section className="samba-app settings-admin-shell">
      <header className="settings-topbar">
        <div><Network size={22} /><div><strong>Samba / Windows File Sharing</strong><span>Udzialy SMB zarzadzane przez Algen</span></div></div>
        <div className="button-row"><button className="button button-secondary" onClick={load}><RefreshCw size={16} />Odswiez</button><button className="button button-primary" onClick={() => applyConfig()}><Shield size={16} />Zastosuj</button></div>
      </header>
      {status?.proxmox_safe_mode && <p className="alert-warning">Wykryto tryb ochrony Proxmox. Katalogi klastra i konfiguracji PVE sa blokowane.</p>}
      <div className="samba-status-grid">
        <article className="settings-card"><h3>Status uslug</h3><dl className="info-grid">{Object.entries(status?.services || {}).map(([name, value]) => <React.Fragment key={name}><dt>{name}</dt><dd>{value}</dd></React.Fragment>)}<dt>Port 445</dt><dd>{status?.ports["445"] ? "dostepny" : "zamkniety"}</dd><dt>Port 139</dt><dd>{status?.ports["139"] ? "dostepny" : "zamkniety"}</dd></dl><div className="button-row">{(["start", "stop", "restart", "reload"] as const).map((action) => <button className="button button-secondary" key={action} onClick={() => service(action)}>{action}</button>)}</div></article>
        <article className="settings-card"><h3>Walidacja</h3><p className={status?.validation.ok ? "badge badge-success" : "badge badge-danger"}>{status?.validation.ok ? "Konfiguracja poprawna" : "Wymaga poprawy"}</p><pre className="store-log">{status?.validation.stderr || status?.validation.stdout || "Brak wyniku testparm"}</pre></article>
      </div>
      <div className="settings-nav samba-tabs">{(["shares", "users", "advanced"] as const).map((item) => <button key={item} className={`settings-nav-item ${tab === item ? "active" : ""}`} onClick={() => setTab(item)}>{item}</button>)}</div>
      {tab === "shares" && <section className="settings-section samba-grid">
        <article className="settings-card">
          <header className="settings-card-header"><div><h2 className="settings-card-title">Kreator udzialu</h2><p className="settings-card-description">Bez recznej edycji smb.conf.</p></div></header>
          <div className="settings-form form-grid">
            <label className="form-field"><span className="form-label">Nazwa</span><input className="form-input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
            <label className="form-field"><span className="form-label">Sciezka</span><input className="form-input" value={draft.path} onChange={(e) => setDraft({ ...draft, path: e.target.value })} /></label>
            <label className="form-field"><span className="form-label">Opis</span><input className="form-input" value={draft.comment} onChange={(e) => setDraft({ ...draft, comment: e.target.value })} /></label>
            <label className="form-field"><span className="form-label">create mask</span><input className="form-input" value={draft.create_mask} onChange={(e) => setDraft({ ...draft, create_mask: e.target.value })} /></label>
            <label className="form-field"><span className="form-label">directory mask</span><input className="form-input" value={draft.directory_mask} onChange={(e) => setDraft({ ...draft, directory_mask: e.target.value })} /></label>
            <label className="form-field"><span className="form-label">valid users</span><input className="form-input" value={tokenText(draft.valid_users)} onChange={(e) => setDraft({ ...draft, valid_users: parseTokens(e.target.value) })} /></label>
            <label className="form-field"><span className="form-label">write list</span><input className="form-input" value={tokenText(draft.write_list)} onChange={(e) => setDraft({ ...draft, write_list: parseTokens(e.target.value), read_only: false })} /></label>
            <label className="form-field"><span className="form-label">read list</span><input className="form-input" value={tokenText(draft.read_list)} onChange={(e) => setDraft({ ...draft, read_list: parseTokens(e.target.value) })} /></label>
            <label className="form-field"><span className="form-label">admin users</span><input className="form-input" value={tokenText(draft.admin_users)} onChange={(e) => setDraft({ ...draft, admin_users: parseTokens(e.target.value) })} /></label>
            <label className="form-field"><span className="form-label">force user</span><input className="form-input" value={draft.force_user || ""} onChange={(e) => setDraft({ ...draft, force_user: e.target.value })} /></label>
            <label className="form-field"><span className="form-label">force group</span><input className="form-input" value={draft.force_group || ""} onChange={(e) => setDraft({ ...draft, force_group: e.target.value })} /></label>
            <label className="form-field"><span className="form-label">veto files</span><input className="form-input" value={draft.veto_files || ""} onChange={(e) => setDraft({ ...draft, veto_files: e.target.value })} /></label>
          </div>
          <div className="toggle-grid">
            {[
              ["enabled", "Wlaczony"], ["read_only", "Tylko odczyt"], ["browseable", "Browsable"], ["hidden", "Ukryty"], ["guest_ok", "Guest access"], ["recycle_bin", "Recycle bin"], ["create_directory", "Utworz katalog"], ["allow_proxmox_storage", "Zezwol na Proxmox storage"]
            ].map(([key, label]) => <label key={key} className="switch-control"><input type="checkbox" checked={Boolean(draft[key as keyof SambaShare])} onChange={(e) => setDraft({ ...draft, [key]: e.target.checked })} /><span />{label}</label>)}
          </div>
          <div className="button-row"><button className="button button-primary" onClick={upsertShare}>Dodaj / aktualizuj</button><button className="button button-secondary" onClick={() => refreshPreview()}>Podglad configu</button></div>
        </article>
        <article className="settings-card"><h3>Aktywne udzialy</h3><div className="admin-list">{config.shares.map((share) => <div key={share.name}><strong>{share.name}</strong><span>{share.path}</span><span className={sharedPaths.has(share.path) ? "badge badge-success" : "badge"}>{share.enabled ? "enabled" : "disabled"}</span><button className="button button-secondary" onClick={() => setDraft(share)}>Edytuj</button><button className="button button-secondary" onClick={() => applyConfig({ ...config, shares: config.shares.map((item) => item.name === share.name ? { ...item, enabled: !item.enabled } : item) })}>{share.enabled ? "Wylacz" : "Wlacz"}</button><button className="button button-danger" onClick={() => applyConfig({ ...config, shares: config.shares.filter((item) => item.name !== share.name) })}>Usun</button></div>)}</div></article>
      </section>}
      {tab === "users" && <section className="settings-card"><h3>Uzytkownicy Samby</h3><div className="admin-list">{users.map((item) => <div key={item.username}><strong>{item.username}</strong><span>{item.system ? "systemowy" : "lokalny"}</span><span>{item.samba_enabled ? "SMB enabled" : "not in Samba"}</span><button className="button button-secondary" onClick={() => enableUser(item.username)}>{item.samba_enabled ? "Zmien haslo" : "Dodaj do Samby"}</button>{item.samba_enabled && <button className="button button-warning" onClick={() => disableUser(item.username)}>Wylacz</button>}</div>)}</div></section>}
      {tab === "advanced" && <section className="settings-section samba-grid"><article className="settings-card"><h3>Opcje globalne</h3><textarea className="advanced-textarea" value={Object.entries(config.global_options || {}).map(([k, v]) => `${k}=${v}`).join("\n")} onChange={(e) => setConfig({ ...config, global_options: Object.fromEntries(e.target.value.split("\n").map((line) => line.split("=").map((part) => part.trim())).filter((parts) => parts[0] && parts.length >= 2).map((parts) => [parts[0], parts.slice(1).join("=")])) })} /><p className="form-help">Niebezpieczne opcje typu include, preexec, wide links sa blokowane przez backend.</p><div className="button-row"><button className="button button-secondary" onClick={() => refreshPreview()}>Waliduj</button><button className="button button-warning" onClick={() => api.sambaRollback().then(() => { toast("Rollback wykonany"); load(); })}>Rollback</button></div></article><article className="settings-card"><h3>Podglad wygenerowanego configu</h3><pre className="store-log">{preview || "Kliknij Podglad configu albo Waliduj."}</pre><pre className="store-log">{validation}</pre></article></section>}
    </section>
  );
}

function StoreApp({ toast }: { toast: (text: string, type?: "ok" | "error") => void }) {
  const [apps, setApps] = useState<StoreModule[]>([]);
  const [selected, setSelected] = useState("samba");
  const [logs, setLogs] = useState<string[]>([]);
  const [config, setConfig] = useState<SambaConfig>({ shares: [] });
  const [draft, setDraft] = useState<SambaShare>(emptyShare);
  const [plugins, setPlugins] = useState<StorePlugin[]>([]);
  const [pluginTemplate, setPluginTemplate] = useState("");
  const [pluginDraft, setPluginDraft] = useState<Partial<StorePlugin>>({ name: "", github_url: "", branch: "main", enabled: true, codex_instructions: "" });
  const [dryRun, setDryRun] = useState<string[]>([]);
  const app = apps.find((item) => item.id === selected);
  function codexPluginInstructions(url = pluginDraft.github_url || "", branch = pluginDraft.branch || "main") {
    return (pluginTemplate || "").replace("{github_url}", url).replace("{branch}", branch);
  }
  async function load() {
    try {
      const next = await api.apps();
      setApps(next);
      if (next.some((item) => item.id === "samba")) setConfig(await api.appConfig("samba"));
      const pluginData = await api.storePlugins();
      setPlugins(pluginData.plugins);
      setPluginTemplate(pluginData.codex_template);
      if (!pluginDraft.codex_instructions && pluginDraft.github_url) setPluginDraft((current) => ({ ...current, codex_instructions: codexPluginInstructions(current.github_url, current.branch) }));
      const logData = await api.appLogs(selected);
      setLogs(logData.lines);
    } catch (err) {
      toast(message(err, "Could not load store"), "error");
    }
  }
  useEffect(() => { load(); }, [selected]);
  async function appAction(action: "install" | "uninstall" | "update" | "start" | "stop" | "restart", dry = false) {
    const admin_password = prompt("Admin password") || "";
    if (!admin_password) return;
    try {
      const result = await api.appAction(selected, action, admin_password, dry) as { steps?: string[] };
      if (dry && result.steps) setDryRun(result.steps);
      toast(dry ? "Dry-run ready" : `${action} queued`);
      await load();
    } catch (err) {
      toast(message(err, "App operation failed"), "error");
    }
  }
  async function saveConfig(next = config) {
    try {
      await api.saveSambaConfig(next);
      toast("Samba configuration saved");
      await load();
    } catch (err) {
      toast(message(err, "Samba config rejected"), "error");
    }
  }
  function addShare() {
    const share = { ...draft, valid_users: String(draft.valid_users || "").split ? String(draft.valid_users).split(",").map((item) => item.trim()).filter(Boolean) : draft.valid_users };
    const next = { shares: [...config.shares.filter((item) => item.name !== share.name), share] };
    setConfig(next);
    setDraft(emptyShare);
  }
  async function savePlugin() {
    const payload = {
      ...pluginDraft,
      branch: pluginDraft.branch || "main",
      enabled: pluginDraft.enabled ?? true,
      codex_instructions: pluginDraft.codex_instructions || codexPluginInstructions(pluginDraft.github_url || "", pluginDraft.branch || "main")
    };
    try {
      if (pluginDraft.id) await api.updateStorePlugin(pluginDraft.id, payload);
      else await api.createStorePlugin(payload);
      toast("Plugin GitHub zapisany");
      setPluginDraft({ name: "", github_url: "", branch: "main", enabled: true, codex_instructions: "" });
      await load();
    } catch (err) {
      toast(message(err, "Nie mozna zapisac pluginu"), "error");
    }
  }
  async function removePlugin(id: string) {
    try {
      await api.deleteStorePlugin(id);
      toast("Plugin usuniety");
      await load();
    } catch (err) {
      toast(message(err, "Nie mozna usunac pluginu"), "error");
    }
  }
  async function setSambaPassword() {
    const username = prompt("Local username");
    const password = prompt("New Samba password");
    const admin_password = prompt("Admin password");
    if (!username || !password || !admin_password) return;
    try {
      await api.setSambaPassword(username, password, admin_password);
      toast("Samba password updated");
    } catch (err) {
      toast(message(err, "Could not set Samba password"), "error");
    }
  }
  return (
    <section className="store-app">
      <aside className="store-list">
        {apps.map((item) => <button key={item.id} className={selected === item.id ? "active" : ""} onClick={() => setSelected(item.id)}><strong>{item.manifest.name}</strong><span>{item.status}</span></button>)}
      </aside>
      <main className="store-detail">
        {app && <>
          <header>
            <div><h2>{app.manifest.name}</h2><p>{app.manifest.description}</p></div>
            <strong>{app.status}</strong>
          </header>
          <div className="toolbar">
            {(["install", "uninstall", "update", "start", "stop", "restart"] as const).map((action) => <button key={action} onClick={() => appAction(action)}>{action}</button>)}
            <button onClick={() => appAction("install", true)}>Dry-run</button>
          </div>
          {!!dryRun.length && <pre className="store-log">{dryRun.join("\n")}</pre>}
          <section className="store-section">
            <h3>Services</h3>
            <div className="disk-list">{Object.entries(app.services).map(([name, status]) => <div key={name}><strong>{name}</strong><span>{status}</span></div>)}</div>
          </section>
          {!!app.jobs.length && <section className="store-section">
            <h3>Jobs</h3>
            <div className="admin-list">{app.jobs.slice(-6).reverse().map((job) => <div key={job.id}><strong>{job.action}</strong><span>{job.status}</span><span>{job.progress}% {job.error}</span></div>)}</div>
          </section>}
          <section className="store-section plugin-store-section">
            <h3>Pluginy GitHub dla Store</h3>
            <p className="form-help">Dodaj repozytorium pluginu jako instrukcje dla Codex. Codex powinien pobrac/obejrzec repo, przeczytac README i manifest, a potem dopiero dopasowac pliki do konwencji tego projektu.</p>
            <div className="settings-form form-grid">
              <label className="form-field"><span className="form-label">Nazwa pluginu</span><input className="form-input" value={pluginDraft.name || ""} onChange={(e) => setPluginDraft({ ...pluginDraft, name: e.target.value })} /></label>
              <label className="form-field"><span className="form-label">GitHub URL</span><input className="form-input" placeholder="https://github.com/owner/repo" value={pluginDraft.github_url || ""} onChange={(e) => { const github_url = e.target.value; setPluginDraft({ ...pluginDraft, github_url, codex_instructions: codexPluginInstructions(github_url, pluginDraft.branch || "main") }); }} /></label>
              <label className="form-field"><span className="form-label">Branch/ref</span><input className="form-input" value={pluginDraft.branch || "main"} onChange={(e) => { const branch = e.target.value; setPluginDraft({ ...pluginDraft, branch, codex_instructions: codexPluginInstructions(pluginDraft.github_url || "", branch) }); }} /></label>
              <label className="form-field switch-field"><span className="form-label">Aktywny</span><label className="switch-control"><input type="checkbox" checked={pluginDraft.enabled ?? true} onChange={(e) => setPluginDraft({ ...pluginDraft, enabled: e.target.checked })} /><span />enabled</label></label>
            </div>
            <label className="form-field"><span className="form-label">Instrukcja dla Codex</span><textarea className="advanced-textarea" value={pluginDraft.codex_instructions || ""} onChange={(e) => setPluginDraft({ ...pluginDraft, codex_instructions: e.target.value })} /></label>
            <div className="button-row"><button className="button button-primary" onClick={savePlugin}>{pluginDraft.id ? "Zapisz plugin" : "Dodaj plugin"}</button><button className="button button-secondary" onClick={() => setPluginDraft({ name: "", github_url: "", branch: "main", enabled: true, codex_instructions: "" })}>Wyczysc</button></div>
            <details className="plugin-guide">
              <summary>Instrukcja tworzenia pluginow dla Codex</summary>
              <pre className="store-log">{`Minimalna struktura repo pluginu:
- README.md z opisem celu i instrukcja instalacji.
- manifest.yaml albo plugin.json z nazwa, wersja, wymaganiami i lista plikow.
- backend/ jezeli plugin dodaje API lub uslugi.
- frontend/ jezeli plugin dodaje widok, komponent albo wpis w Store.
- tests/ dla generatorow, walidacji i endpointow.

Zasady dla Codex:
1. Najpierw przeczytaj README i manifest pluginu.
2. Sprawdz, czy plugin pasuje do aktualnej architektury Algen.
3. Nie wykonuj skryptow instalacyjnych bez inspekcji.
4. Nie zapisuj sekretow ani hasel w repo.
5. Wprowadz zmiany minimalnie, zgodnie ze stylem projektu.
6. Uruchom typecheck, lint, testy i build dla dotknietych czesci.
7. W odpowiedzi podaj pliki, walidacje i ewentualne ryzyka.`}</pre>
            </details>
            <div className="admin-list">{plugins.map((plugin) => <div key={plugin.id}><strong>{plugin.name}</strong><span>{plugin.github_url}</span><span>{plugin.branch}</span><span className={plugin.enabled ? "badge badge-success" : "badge"}>{plugin.enabled ? "active" : "disabled"}</span><button className="button button-secondary" onClick={() => setPluginDraft(plugin)}>Edytuj</button><button className="button button-danger" onClick={() => removePlugin(plugin.id)}>Usun</button></div>)}</div>
          </section>
          {selected === "samba" && <section className="store-section">
            <h3>Samba shares</h3>
            <div className="form-grid">
              <input placeholder="Share name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              <input placeholder="Path" value={draft.path} onChange={(e) => setDraft({ ...draft, path: e.target.value })} />
              <input placeholder="Comment" value={draft.comment} onChange={(e) => setDraft({ ...draft, comment: e.target.value })} />
              <input placeholder="valid users comma separated" onChange={(e) => setDraft({ ...draft, valid_users: e.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} />
              <label><input type="checkbox" checked={draft.browseable} onChange={(e) => setDraft({ ...draft, browseable: e.target.checked })} /> browseable</label>
              <label><input type="checkbox" checked={draft.read_only} onChange={(e) => setDraft({ ...draft, read_only: e.target.checked })} /> read only</label>
              <label><input type="checkbox" checked={draft.guest_ok} onChange={(e) => setDraft({ ...draft, guest_ok: e.target.checked })} /> guest ok</label>
            </div>
            <button onClick={addShare}>Add / update share</button>
            <button onClick={() => saveConfig()}>Save and test config</button>
            <button onClick={setSambaPassword}>Set Samba password</button>
            <div className="admin-list">{config.shares.map((share) => <div key={share.name}><strong>{share.name}</strong><span>{share.path}</span><span>{share.enabled ? "enabled" : "disabled"}</span><button onClick={() => setDraft(share)}>Edit</button><button onClick={() => saveConfig({ shares: config.shares.filter((item) => item.name !== share.name) })}>Remove</button><button onClick={() => saveConfig({ shares: config.shares.map((item) => item.name === share.name ? { ...item, enabled: !item.enabled } : item) })}>{share.enabled ? "Disable" : "Enable"}</button></div>)}</div>
          </section>}
          <section className="store-section">
            <h3>Logs</h3>
            <pre className="store-log">{logs.join("\n")}</pre>
          </section>
        </>}
      </main>
    </section>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<SettingsMe | null>(null);
  const [language, setLanguage] = useState<Language>(() => detectLanguage(localStorage.getItem("webnas_language")));
  const [theme, setTheme] = useState<Theme>("system");
  const [wallpaper, setWallpaper] = useState("");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [sambaInitialPath, setSambaInitialPath] = useState("");
  const [openWindows, setOpenWindows] = useState<WindowInstance[]>([]);
  const [activeWindowId, setActiveWindowId] = useState("");
  const [layouts, setLayouts] = useState<Layouts>({});
  const eventSources = useRef<Map<string, EventSource>>(new Map());
  const windowIdCounter = useRef(0);
  const windowsRestored = useRef(false);
  const t = (key: string) => translate(language, key);
  const windowsKey = user ? `webnas_open_windows_${user.username}` : "";
  function toast(text: string, type: "ok" | "error" = "ok") {
    const id = Date.now();
    setToasts((items) => [...items, { id, text, type }]);
    setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 4200);
  }
  function changeLanguage(next: Language) {
    setLanguage(next);
    localStorage.setItem("webnas_language", next);
  }
  function restoreWindowState(username: string, startup: SettingsMe["startup_windows"]) {
    windowsRestored.current = false;
    if (startup === "none") {
      setOpenWindows([]);
      setLayouts({});
      setActiveWindowId("");
      windowIdCounter.current = 0;
      windowsRestored.current = true;
      return;
    }
    const saved = localStorage.getItem(`webnas_open_windows_${username}`);
    if (!saved) {
      setOpenWindows([]);
      setLayouts({});
      setActiveWindowId("");
      windowIdCounter.current = 0;
      windowsRestored.current = true;
      return;
    }
    try {
      const parsed = JSON.parse(saved) as SavedWindowState;
      const restoredWindows = (parsed.windows || []).filter((item) => item.id && isAppId(item.app));
      const restoredLayouts = restoredWindows.reduce<Layouts>((result, item) => {
        const layout = parsed.layouts?.[item.id] || defaultLayouts[item.app];
        result[item.id] = layout;
        return result;
      }, {});
      setOpenWindows(restoredWindows);
      setLayouts(restoredLayouts);
      setActiveWindowId(restoredWindows.some((item) => item.id === parsed.activeWindowId) ? parsed.activeWindowId || "" : restoredWindows[0]?.id || "");
      windowIdCounter.current = Math.max(parsed.counter || 0, restoredWindows.length);
    } catch {
      setOpenWindows([]);
      setLayouts({});
      setActiveWindowId("");
      windowIdCounter.current = 0;
    } finally {
      windowsRestored.current = true;
    }
  }
  useEffect(() => { me().then(setUser).catch(() => undefined); }, []);
  useEffect(() => {
    windowsRestored.current = false;
    setOpenWindows([]);
    setLayouts({});
    setActiveWindowId("");
  }, [user?.username]);
  useEffect(() => {
    if (!user || !windowsRestored.current) return;
    const payload: SavedWindowState = { windows: openWindows, layouts, activeWindowId, counter: windowIdCounter.current };
    localStorage.setItem(windowsKey, JSON.stringify(payload));
  }, [openWindows, layouts, activeWindowId, user?.username]);
  useEffect(() => {
    if (!user) return;
    api.settingsMe().then((data) => { setProfile(data); changeLanguage(data.language); setTheme(data.theme); setWallpaper(data.wallpaper || ""); restoreWindowState(user.username, data.startup_windows); }).catch(() => undefined);
    const timer = setInterval(() => api.tasks().then(setTasks).catch(() => undefined), 1500);
    return () => clearInterval(timer);
  }, [user]);
  useEffect(() => {
    if (!user || typeof EventSource === "undefined") return;
    const active = new Set(tasks.filter((task) => ["queued", "running"].includes(task.status)).map((task) => task.id));
    for (const taskId of active) {
      if (eventSources.current.has(taskId)) continue;
      const source = new EventSource(`/api/files/tasks/${encodeURIComponent(taskId)}/events`);
      source.onmessage = (event) => {
        const nextTask = JSON.parse(event.data) as Task;
        setTasks((current) => current.map((task) => task.id === nextTask.id ? nextTask : task));
        if (["completed", "failed", "cancelled"].includes(nextTask.status)) {
          source.close();
          eventSources.current.delete(taskId);
        }
      };
      source.onerror = () => {
        source.close();
        eventSources.current.delete(taskId);
      };
      eventSources.current.set(taskId, source);
    }
    for (const [taskId, source] of eventSources.current) {
      if (!active.has(taskId)) {
        source.close();
        eventSources.current.delete(taskId);
      }
    }
  }, [tasks, user]);
  function openApp(app: AppId) {
    windowIdCounter.current += 1;
    const id = `${app}-${windowIdCounter.current}`;
    const sameAppCount = openWindows.filter((item) => item.app === app).length;
    const base = defaultLayouts[app];
    const layout = {
      ...base,
      x: base.x + ((sameAppCount * 28) % 180),
      y: base.y + ((sameAppCount * 24) % 160),
      minimized: false
    };
    setOpenWindows((current) => [...current, { id, app }]);
    setLayouts((current) => ({ ...current, [id]: layout }));
    setActiveWindowId(id);
  }
  function shareViaSamba(pathToShare: string) {
    setSambaInitialPath(pathToShare);
    openApp("samba");
  }
  function closeWindow(id: string) {
    setOpenWindows((current) => {
      const next = current.filter((item) => item.id !== id);
      setActiveWindowId((active) => active === id ? (next[next.length - 1]?.id || "") : active);
      return next;
    });
    setLayouts((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
  }
  function windowTitle(window: WindowInstance) {
    const sameApp = openWindows.filter((item) => item.app === window.app);
    const index = sameApp.findIndex((item) => item.id === window.id);
    return sameApp.length > 1 ? `${appMeta[window.app].title} ${index + 1}` : appMeta[window.app].title;
  }
  function renderApp(app: AppId) {
    if (app === "dashboard") return <DashboardApp toast={toast} />;
    if (app === "files") return <FileManagerV2 toast={toast} t={t} tasks={tasks} homePath={user?.home || ""} onShareSamba={shareViaSamba} />;
    if (app === "transfers") return <TransferPanel tasks={tasks} t={t} toast={toast} />;
    if (app === "settings") return <SettingsApp t={t} toast={toast} onLanguage={changeLanguage} onTheme={setTheme} onWallpaper={setWallpaper} />;
    if (app === "mounts") return <NetworkMountsApp toast={toast} />;
    if (app === "services") return <ServicesApp toast={toast} />;
    if (app === "store") return <StoreApp toast={toast} />;
    if (app === "samba") return <SambaApp toast={toast} initialPath={sambaInitialPath} />;
    return <LogsApp toast={toast} />;
  }
  const resolvedTheme = theme === "system" && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : theme === "system" ? "dark" : theme;
  if (!user) return <Login onLogin={setUser} t={t} />;
  const desktopApps = (Object.keys(appMeta) as AppId[]).filter((app) => !appMeta[app].admin || profile?.is_admin);
  const wallpaperStyle = wallpaper ? {
    backgroundImage: `linear-gradient(130deg, rgba(8,13,20,.42), rgba(8,13,20,.08) 42%, rgba(8,13,20,.48)), url(${JSON.stringify(wallpaper)})`,
    backgroundSize: "cover",
    backgroundPosition: "center",
    backgroundAttachment: "fixed"
  } as React.CSSProperties : undefined;
  return (
    <div className={`app ${resolvedTheme}`} style={wallpaperStyle}>
      <header className="topbar">
        <strong>WebNAS</strong>
        <span>{user.username}</span>
        <button title="Notifications" onClick={() => setNotificationsOpen((value) => !value)}><Bell size={17} /></button>
        <button title={t("notify.theme")} onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>{resolvedTheme === "dark" ? <Sun size={17} /> : <Moon size={17} />}</button>
        <button title={t("notify.logout")} onClick={() => logout().finally(() => setUser(null))}><LogOut size={17} /></button>
      </header>
      <div className="desktop-icons">
        {desktopApps.map((app) => <AppIcon key={app} label={appMeta[app].title} icon={appMeta[app].icon} onOpen={() => openApp(app)} />)}
      </div>
      {openWindows.map((window) => layouts[window.id] && !layouts[window.id].minimized && (
        <DesktopWindow
          key={window.id}
          app={window.app}
          title={windowTitle(window)}
          layout={layouts[window.id]}
          active={activeWindowId === window.id}
          onFocus={() => setActiveWindowId(window.id)}
          onClose={() => closeWindow(window.id)}
          onMinimize={() => setLayouts((current) => ({ ...current, [window.id]: { ...current[window.id], minimized: true } }))}
          onLayout={(layout) => setLayouts((current) => ({ ...current, [window.id]: layout }))}
        >
          {renderApp(window.app)}
        </DesktopWindow>
      ))}
      {notificationsOpen && <aside className="notification-center">
        <header><strong>Notifications</strong><button onClick={() => setNotificationsOpen(false)}><X size={14} /></button></header>
        {toasts.length ? toasts.slice().reverse().map((item) => <div className={item.type} key={item.id}>{item.text}</div>) : <p>No recent notifications</p>}
        {tasks.slice(-6).reverse().map((task) => <div key={task.id}>{task.type}: {task.status} {task.progress}%</div>)}
      </aside>}
      <footer className="taskbar">
        {openWindows.map((window) => <button key={window.id} className={activeWindowId === window.id ? "active" : ""} onClick={() => { setLayouts((current) => ({ ...current, [window.id]: { ...current[window.id], minimized: false } })); setActiveWindowId(window.id); }}>{windowTitle(window)}</button>)}
        <span className="task-summary">{tasks.slice(-2).map((task) => `${task.op}: ${task.status} ${task.progress}%`).join(" | ")}</span>
      </footer>
      <div className="toasts">{toasts.map((item) => <div className={item.type} key={item.id}>{item.text}</div>)}</div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
