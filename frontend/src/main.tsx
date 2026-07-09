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
  List,
  Lock,
  LogOut,
  Maximize2,
  Minimize2,
  Moon,
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
import { AdminGroup, AdminUser, api, downloadUrl, FileItem, login, logout, me, ProxmoxSafety, SettingsMe, SystemdService, SystemLogs, Task } from "./api";
import type { NetworkMount, NetworkMountPayload, ResourceDashboard, SambaConfig, SambaShare, StoreApp as StoreModule } from "./api";
import { AppIcon } from "./components/AppIcon";
import { detectLanguage, Language, supportedLanguages, translate } from "./i18n";
import "./styles/app.css";

type User = { username: string; home: string };
type Toast = { id: number; text: string; type: "ok" | "error" };
type Theme = "light" | "dark" | "system";
type T = (key: string) => string;
type AppId = "dashboard" | "files" | "transfers" | "settings" | "mounts" | "services" | "store" | "logs";
type WindowLayout = { x: number; y: number; width: number; height: number; minimized?: boolean };
type WindowInstance = { id: string; app: AppId };
type Layouts = Record<string, WindowLayout>;

const defaultLayouts: Layouts = {
  dashboard: { x: 112, y: 78, width: 1040, height: 680 },
  files: { x: 124, y: 82, width: 1120, height: 720 },
  transfers: { x: 220, y: 120, width: 760, height: 560 },
  settings: { x: 180, y: 104, width: 980, height: 660 },
  mounts: { x: 160, y: 92, width: 1040, height: 680 },
  services: { x: 210, y: 112, width: 940, height: 620 },
  store: { x: 190, y: 96, width: 1040, height: 680 },
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
  logs: { title: "Logs", icon: <Terminal size={28} />, admin: true }
};

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
  const drag = useRef<{ startX: number; startY: number; layout: WindowLayout; mode: "move" | "resize" } | null>(null);
  useEffect(() => {
    function move(event: PointerEvent) {
      if (!drag.current) return;
      const dx = event.clientX - drag.current.startX;
      const dy = event.clientY - drag.current.startY;
      const base = drag.current.layout;
      if (drag.current.mode === "move") {
        onLayout({ ...base, x: Math.max(8, base.x + dx), y: Math.max(50, base.y + dy) });
      } else {
        onLayout({ ...base, width: Math.max(360, base.width + dx), height: Math.max(280, base.height + dy) });
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
  return (
    <section
      className={`window ${active ? "active" : ""}`}
      style={{ left: layout.x, top: layout.y, width: layout.width, height: layout.height, zIndex: active ? 9 : 5 }}
      onPointerDown={onFocus}
    >
      <header
        className="window-title"
        onPointerDown={(event) => {
          event.preventDefault();
          drag.current = { startX: event.clientX, startY: event.clientY, layout, mode: "move" };
          onFocus();
        }}
      >
        <span>{displayTitle}</span>
        <div className="window-controls">
          <button title="Minimize" onClick={(event) => { event.stopPropagation(); onMinimize(); }}><Minimize2 size={13} /></button>
          <button title="Maximize" onClick={(event) => { event.stopPropagation(); onLayout({ ...layout, x: 16, y: 52, width: window.innerWidth - 32, height: window.innerHeight - 104 }); }}><Maximize2 size={13} /></button>
          <button title="Close" onClick={(event) => { event.stopPropagation(); onClose(); }}><X size={13} /></button>
        </div>
      </header>
      {children}
      <span
        className="resize-handle"
        onPointerDown={(event) => {
          event.preventDefault();
          event.stopPropagation();
          drag.current = { startX: event.clientX, startY: event.clientY, layout, mode: "resize" };
          onFocus();
        }}
      />
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

function FileManagerV2({ toast, t, tasks }: { toast: (text: string, type?: "ok" | "error") => void; t: T; tasks: Task[] }) {
  const lastPathKey = "webnas_file_manager_last_path";
  const viewKey = "webnas_file_manager_view";
  const [path, setPath] = useState(() => localStorage.getItem(lastPathKey) || "");
  const [items, setItems] = useState<FileItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [clipboard, setClipboard] = useState<{ mode: "copy" | "move"; paths: string[] } | null>(null);
  const [preview, setPreview] = useState<FileItem | null>(null);
  const [context, setContext] = useState<{ x: number; y: number; item: FileItem | null } | null>(null);
  const [mounts, setMounts] = useState<NetworkMount[]>([]);
  const [tree, setTree] = useState<TreeState>({});
  const [treeVisible, setTreeVisible] = useState(() => localStorage.getItem(`${viewKey}_tree`) !== "hidden");
  const [treeWidth, setTreeWidth] = useState(() => Number(localStorage.getItem(`${viewKey}_tree_width`) || 240));
  const [compact, setCompact] = useState(() => localStorage.getItem(`${viewKey}_density`) === "compact");
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
          className={path === item.path ? "active" : ""}
          style={{ paddingLeft: 10 + level * 14 }}
          onClick={() => openPath(item.path)}
          onContextMenu={(event) => { event.preventDefault(); setContext({ x: event.clientX, y: event.clientY, item }); }}
        >
          <span onClick={(event) => {
            event.stopPropagation();
            if (state?.open) setTree((current) => ({ ...current, [item.path]: { ...state, open: false } }));
            else loadTree(item.path);
          }}>{state?.open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
          <Folder size={15} /> {item.name} {state?.loading && <span>...</span>}
        </button>
        {state?.error && <small className="tree-error">{state.error}</small>}
        {state?.open && state.items.map((child) => <TreeNode key={child.path} item={child} level={level + 1} />)}
      </>
    );
  }

  const rootItems = tree[path]?.items || items.filter((item) => item.is_dir);
  const sortIcon = (field: SortField) => sort === field ? (direction === "asc" ? "^" : "v") : "";
  return (
    <>
      <div className="toolbar">
        <button title="Toggle tree" onClick={() => setTreeVisible((value) => !value)}><List size={17} /></button>
        <button title={t("action.refresh")} onClick={() => { load(); loadTree(path); }}><RefreshCw size={17} /></button>
        <button title={t("action.newFolder")} disabled={!meta.can_upload} onClick={() => { const name = prompt(t("files.folderName")); if (name) named(t("files.folderCreated"), () => api.mkdir(joinPath(path, name))); }}><FolderPlus size={17} /></button>
        <label className="icon-button" title={t("action.upload")}><Upload size={17} /><input type="file" multiple disabled={!meta.can_upload} onChange={(e) => Array.from(e.target.files || []).forEach((file) => named(t("files.uploaded"), () => api.upload(path, file)))} /></label>
        <button title={t("action.copy")} disabled={!selected.size} onClick={copySelected}><Copy size={17} /></button>
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
          {selected.size > 0 && <div className="selection-bar"><strong>{selected.size} selected</strong><button onClick={copySelected}>Copy</button><button onClick={() => { const target = prompt("Move to", path); if (target) api.move([...selected], target).then(() => load()); }}>Move</button><button onClick={deleteSelected}>Delete</button><button onClick={() => selectedItems[0] && window.open(downloadUrl(selectedItems[0].path), "_blank")}>Download</button><button onClick={() => { const mode = prompt("Mode", "0644"); if (mode) selectedItems.forEach((item) => named("Permissions changed", () => api.chmod(item.path, mode))); }}>chmod</button><button onClick={() => toast("Archive action is queued for a future backend module")}>Archive</button></div>}
          {debouncedFilter && <p className="filter-note">Filtered by "{debouncedFilter}"</p>}
          {error && <p className="error">{error}</p>}
          {loading ? <div className="table-skeleton"><span /><span /><span /><span /></div> : (
            <div className="file-table-grid">
              <div className="file-header">
                <input type="checkbox" checked={items.length > 0 && selected.size === items.length} onChange={(e) => setSelected(e.target.checked ? new Set(items.map((item) => item.path)) : new Set())} />
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
                  <input type="checkbox" checked={selected.has(item.path)} onChange={(e) => { e.stopPropagation(); toggle(item, true); }} />
                  {item.is_dir ? <Folder size={20} /> : <File size={20} />}
                  <span className="name">{item.name}</span>
                  <span>{item.is_dir ? "—" : formatSize(item.size)}</span>
                  <span>{item.type}</span>
                  <span>{item.owner}</span>
                  <span>{item.group}</span>
                  <span>{item.permissions}</span>
                  <span>{new Date((item.mtime || item.modified) * 1000).toLocaleString()}</span>
                  <div className="row-actions">{!item.is_dir && <a href={downloadUrl(item.path)}><Download size={15} /></a>}<button onClick={(e) => { e.stopPropagation(); renameItem(item); }}>Rename</button></div>
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
        <button onClick={() => { const item = context.item || selectedItems[0]; if (item) alert(`${item.name}\n${item.path}\n${item.permissions}`); setContext(null); }}>Properties</button>
        <button disabled={!clipboard} onClick={() => { paste(context.item?.path || path).catch((err) => toast(message(err, t("files.operationFailed")), "error")); setContext(null); }}>Paste</button>
        <button onClick={() => { load(); loadTree(context.item?.path || path); setContext(null); }}>Refresh</button>
      </div>}
      <Preview item={preview} onClose={() => setPreview(null)} t={t} />
    </>
  );
}

function TransferPanel({ tasks, t, toast }: { tasks: Task[]; t: T; toast: (text: string, type?: "ok" | "error") => void }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<"all" | "active" | "finished" | "failed" | "cancelled">("all");
  const transferTasks = tasks.filter((task) => ["copy", "move"].includes(task.type) && !hidden.has(task.id));
  const visible = transferTasks.filter((task) => {
    if (!["copy", "move"].includes(task.type) || hidden.has(task.id)) return false;
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
                {task.status === "running" && <button title="Pause" onClick={() => action(task.id, api.pauseTask)}><Pause size={14} /></button>}
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
                <span>{t("transfers.transferred")}: {formatSize(task.bytes_transferred || 0)} / {formatSize(task.total_bytes || 0)}</span>
                <span>{t("transfers.eta")}: {task.eta_human || "-"}</span>
              </div>
              <div className="transfer-paths">
                <span>{t("transfers.source")}: {task.source_paths.map(shortPath).join(", ")}</span>
                <span>{t("transfers.destination")}: {shortPath(task.destination_path)}</span>
                {task.current_file && <span>{t("transfers.currentFile")}: {task.current_file}</span>}
                {task.error_message && <span className="error">{task.error_message}</span>}
              </div>
              {expanded && <div className="transfer-details">
                <dl>
                  <dt>command</dt><dd><code>{(task.command_preview || []).join(" ")}</code></dd>
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

function SettingsApp({ t, onLanguage, onTheme, toast }: { t: T; onLanguage: (language: Language) => void; onTheme: (theme: Theme) => void; toast: (text: string, type?: "ok" | "error") => void }) {
  const [tab, setTab] = useState("account");
  const [settings, setSettings] = useState<SettingsMe | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [groups, setGroups] = useState<AdminGroup[]>([]);
  const [system, setSystem] = useState<Record<string, unknown> | null>(null);
  const [safety, setSafety] = useState<ProxmoxSafety | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});

  async function load() {
    const meData = await api.settingsMe();
    setSettings(meData);
    onLanguage(meData.language);
    onTheme(meData.theme);
    if (meData.is_admin) {
      api.adminUsers().then(setUsers).catch(() => undefined);
      api.adminGroups().then(setGroups).catch(() => undefined);
      api.systemStatus().then(setSystem).catch(() => undefined);
      api.proxmoxSafety().then(setSafety).catch(() => undefined);
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

  return (
    <>
      <div className="settings-shell">
        <nav className="settings-tabs">
          {["account", "users", "groups", "permissions", "system"].map((item) => (
            <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{t(`settings.${item}`)}</button>
          ))}
        </nav>
        <main className="settings-panel">
          {safety?.is_proxmox && safety.safe_mode_enabled && (
            <div className="safe-mode-banner">
              <Shield size={18} />
              <div>
                <strong>Proxmox VE Safe Mode active</strong>
                <span>Operations on Proxmox system paths, storage, cluster, network, protected users, groups, and services are blocked.</span>
              </div>
            </div>
          )}
          {tab === "account" && settings && (
            <section className="settings-section">
              <div className="form-grid">
                <label>{t("settings.language")}<select value={settings.language} onChange={(e) => submit(t("settings.saved"), async () => { const language = e.target.value as Language; await api.updateSettings({ language }); onLanguage(language); })}>{supportedLanguages.map((language) => <option key={language}>{language}</option>)}</select></label>
                <label>{t("settings.theme")}<select value={settings.theme} onChange={(e) => submit(t("settings.saved"), async () => { const theme = e.target.value as Theme; await api.updateSettings({ theme }); onTheme(theme); })}><option value="light">{t("settings.light")}</option><option value="dark">{t("settings.dark")}</option><option value="system">{t("settings.systemTheme")}</option></select></label>
                <label>{t("settings.currentPassword")}<input type="password" onChange={(e) => setForm({ ...form, current_password: e.target.value })} /></label>
                <label>{t("settings.newPassword")}<input type="password" onChange={(e) => setForm({ ...form, new_password: e.target.value })} /></label>
              </div>
              <button onClick={() => submit(t("settings.passwordChanged"), () => api.changeMyPassword(form.current_password, form.new_password))}><Lock size={16} />{t("action.changePassword")}</button>
              <dl className="info-grid">
                <dt>{t("settings.username")}</dt><dd>{settings.username}</dd>
                <dt>{t("settings.uid")}</dt><dd>{settings.uid}</dd>
                <dt>{t("settings.gid")}</dt><dd>{settings.gid}</dd>
                <dt>{t("settings.groupsLabel")}</dt><dd>{settings.groups.join(", ")}</dd>
                <dt>{t("settings.home")}</dt><dd>{settings.home}</dd>
              </dl>
            </section>
          )}
          {tab === "users" && (
            <section className="settings-section">
              {!settings?.is_admin && <p className="error">{t("settings.adminOnly")}</p>}
              {settings?.is_admin && <>
                <div className="form-grid">
                  <input placeholder={t("settings.username")} onChange={(e) => setForm({ ...form, username: e.target.value })} />
                  <input type="password" placeholder={t("auth.password")} onChange={(e) => setForm({ ...form, password: e.target.value })} />
                  <input placeholder="groups, comma separated" onChange={(e) => setForm({ ...form, groups: e.target.value })} />
                  <input placeholder={t("settings.shell")} onChange={(e) => setForm({ ...form, shell: e.target.value })} />
                  <input placeholder={t("settings.gecos")} onChange={(e) => setForm({ ...form, gecos: e.target.value })} />
                  <input type="password" placeholder={t("settings.adminPassword")} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} />
                </div>
                <button onClick={() => submit(t("settings.addUser"), () => api.createUser({ username: form.username, password: form.password, groups: (form.groups || "").split(",").map((item) => item.trim()).filter(Boolean), shell: form.shell || undefined, gecos: form.gecos || undefined, create_home: true, admin_password: adminPassword() }))}><UserPlus size={16} />{t("settings.addUser")}</button>
                <h2>{t("settings.userList")}</h2>
                <div className="admin-list">{users.map((item) => <div key={item.username}><strong>{item.username}</strong><span>{item.uid}</span><span>{item.groups.join(", ")}</span><button onClick={() => submit(t("action.lock"), () => api.lockUser(item.username, adminPassword()))}>{t("action.lock")}</button><button onClick={() => submit(t("action.unlock"), () => api.unlockUser(item.username, adminPassword()))}>{t("action.unlock")}</button><button onClick={() => { const password = prompt("New password"); if (password) submit(t("settings.passwordChanged"), () => api.changeUserPassword(item.username, { new_password: password, admin_password: adminPassword() })); }}>Reset</button><button onClick={() => { const group = prompt("Group to add"); if (group) submit(t("action.add"), () => api.patchUser(item.username, { groups_add: [group], admin_password: adminPassword() })); }}>{t("action.add")}</button><button onClick={() => { const group = prompt("Group to remove"); if (group) submit(t("action.remove"), () => api.patchUser(item.username, { groups_remove: [group], admin_password: adminPassword() })); }}>{t("action.remove")}</button><button onClick={() => submit("Home created", () => api.patchUser(item.username, { create_home: true, admin_password: adminPassword() }))}>Home</button><button onClick={() => { const quota = prompt("Soft quota MB"); if (quota) submit("Quota saved", () => api.setUserQuota(item.username, { soft_mb: Number(quota), admin_password: adminPassword() })); }}>Quota</button><button onClick={() => window.confirm(t("settings.confirmDelete")) && submit(t("action.delete"), () => api.deleteUser(item.username, adminPassword()))}>{t("action.delete")}</button></div>)}</div>
              </>}
            </section>
          )}
          {tab === "groups" && (
            <section className="settings-section">
              {!settings?.is_admin && <p className="error">{t("settings.adminOnly")}</p>}
              {settings?.is_admin && <>
                <div className="form-grid"><input placeholder={t("settings.groupName")} onChange={(e) => setForm({ ...form, groupname: e.target.value })} /><input placeholder={t("settings.member")} onChange={(e) => setForm({ ...form, member: e.target.value })} /><input type="password" placeholder={t("settings.adminPassword")} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} /></div>
                <button onClick={() => submit(t("settings.addGroup"), () => api.createGroup({ groupname: form.groupname, admin_password: adminPassword() }))}><Users size={16} />{t("settings.addGroup")}</button>
                <h2>{t("settings.groupList")}</h2>
                <div className="admin-list">{groups.map((item) => <div key={item.name}><strong>{item.name}</strong><span>{item.gid}</span><span>{item.members.join(", ")}</span><button onClick={() => submit(t("action.add"), () => api.addGroupMember(item.name, { username: form.member, admin_password: adminPassword() }))}>{t("action.add")}</button><button onClick={() => submit(t("action.remove"), () => api.removeGroupMember(item.name, form.member, adminPassword()))}>{t("action.remove")}</button><button onClick={() => window.confirm(t("settings.confirmDelete")) && submit(t("action.delete"), () => api.deleteGroup(item.name, adminPassword()))}>{t("action.delete")}</button></div>)}</div>
              </>}
            </section>
          )}
          {tab === "permissions" && (
            <section className="settings-section">
              <div className="form-grid"><input placeholder={t("settings.filePath")} onChange={(e) => setForm({ ...form, perm_path: e.target.value })} /><input placeholder={t("settings.mode")} onChange={(e) => setForm({ ...form, mode: e.target.value })} /><input placeholder={t("settings.owner")} onChange={(e) => setForm({ ...form, owner: e.target.value })} /><input placeholder={t("settings.group")} onChange={(e) => setForm({ ...form, group: e.target.value })} /><input type="password" placeholder={t("settings.adminPassword")} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} /></div>
              <button onClick={() => submit(t("settings.applyChmod"), () => api.chmod(form.perm_path, form.mode))}><Shield size={16} />{t("settings.applyChmod")}</button>
              <button onClick={() => submit(t("settings.applyOwner"), () => api.chown({ path: form.perm_path, owner: form.owner || undefined, group: form.group || undefined, admin_password: adminPassword() }))}><Shield size={16} />{t("settings.applyOwner")}</button>
            </section>
          )}
          {tab === "system" && (
            <section className="settings-section">
              {!settings?.is_admin && <p className="error">{t("settings.adminOnly")}</p>}
              {settings?.is_admin && system && <>
                <dl className="info-grid">{Object.entries(system).map(([key, value]) => <React.Fragment key={key}><dt>{t(`settings.${key}`) || key}</dt><dd>{String(value)}</dd></React.Fragment>)}</dl>
                {safety && <dl className="info-grid">
                  <dt>Proxmox</dt><dd>{String(safety.is_proxmox)}</dd>
                  <dt>Safe Mode</dt><dd>{String(safety.safe_mode_enabled)}</dd>
                  <dt>Service user</dt><dd>{safety.service_user}</dd>
                  <dt>Protected paths</dt><dd>{safety.protected_paths.slice(0, 8).join(", ")}{safety.protected_paths.length > 8 ? "..." : ""}</dd>
                  <dt>Warnings</dt><dd>{safety.warnings.join(" ")}</dd>
                </dl>}
                <button onClick={() => submit(t("action.restart"), () => api.restartSystem(adminPassword()))}><RefreshCw size={16} />{t("action.restart")}</button>
              </>}
            </section>
          )}
        </main>
      </div>
    </>
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
  read_only: true,
  guest_ok: false,
  valid_users: [],
  force_user: "",
  create_mask: "0664",
  directory_mask: "0775"
};

function StoreApp({ toast }: { toast: (text: string, type?: "ok" | "error") => void }) {
  const [apps, setApps] = useState<StoreModule[]>([]);
  const [selected, setSelected] = useState("samba");
  const [logs, setLogs] = useState<string[]>([]);
  const [config, setConfig] = useState<SambaConfig>({ shares: [] });
  const [draft, setDraft] = useState<SambaShare>(emptyShare);
  const [dryRun, setDryRun] = useState<string[]>([]);
  const app = apps.find((item) => item.id === selected);
  async function load() {
    try {
      const next = await api.apps();
      setApps(next);
      if (next.some((item) => item.id === "samba")) setConfig(await api.appConfig("samba"));
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
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [openWindows, setOpenWindows] = useState<WindowInstance[]>([
    { id: "dashboard-1", app: "dashboard" },
    { id: "files-1", app: "files" }
  ]);
  const [activeWindowId, setActiveWindowId] = useState("dashboard-1");
  const [layouts, setLayouts] = useState<Layouts>({
    "dashboard-1": defaultLayouts.dashboard,
    "files-1": defaultLayouts.files
  });
  const eventSources = useRef<Map<string, EventSource>>(new Map());
  const t = (key: string) => translate(language, key);
  const layoutKey = user ? `webnas_window_layout_${user.username}` : "";
  function toast(text: string, type: "ok" | "error" = "ok") {
    const id = Date.now();
    setToasts((items) => [...items, { id, text, type }]);
    setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 4200);
  }
  function changeLanguage(next: Language) {
    setLanguage(next);
    localStorage.setItem("webnas_language", next);
  }
  useEffect(() => { me().then(setUser).catch(() => undefined); }, []);
  useEffect(() => {
    if (!user) return;
    const saved = localStorage.getItem(layoutKey);
    if (saved) {
      try { setLayouts((current) => ({ ...current, ...JSON.parse(saved) })); } catch { setLayouts({ "dashboard-1": defaultLayouts.dashboard, "files-1": defaultLayouts.files }); }
    }
  }, [user?.username]);
  useEffect(() => {
    if (!user) return;
    localStorage.setItem(layoutKey, JSON.stringify(layouts));
  }, [layouts, user?.username]);
  useEffect(() => {
    if (!user) return;
    api.settingsMe().then((data) => { setProfile(data); changeLanguage(data.language); setTheme(data.theme); }).catch(() => undefined);
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
    const id = `${app}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
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
    if (app === "files") return <FileManagerV2 toast={toast} t={t} tasks={tasks} />;
    if (app === "transfers") return <TransferPanel tasks={tasks} t={t} toast={toast} />;
    if (app === "settings") return <SettingsApp t={t} toast={toast} onLanguage={changeLanguage} onTheme={setTheme} />;
    if (app === "mounts") return <NetworkMountsApp toast={toast} />;
    if (app === "services") return <ServicesApp toast={toast} />;
    if (app === "store") return <StoreApp toast={toast} />;
    return <LogsApp toast={toast} />;
  }
  const resolvedTheme = theme === "system" && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : theme === "system" ? "dark" : theme;
  if (!user) return <Login onLogin={setUser} t={t} />;
  const desktopApps = (Object.keys(appMeta) as AppId[]).filter((app) => !appMeta[app].admin || profile?.is_admin);
  return (
    <div className={`app ${resolvedTheme}`}>
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
