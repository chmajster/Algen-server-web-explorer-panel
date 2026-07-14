/* eslint-disable react-hooks/refs -- request and gesture refs are read only by async or DOM event handlers */
import {
  ArrowLeft, ArrowRight, ArrowUp, Columns3, Copy, Download, File, FilePlus2, Folder, FolderPlus,
  Grid2X2, Info, LayoutGrid, List, Menu, MoreHorizontal, Move, Pencil, RefreshCw, Scissors,
  Search, SlidersHorizontal, Trash2, Upload, X
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, downloadUrl, type FileItem, type NetworkMount, type Task } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { ContextMenu, type ContextMenuItem } from "../../components/ContextMenu";
import { ConfirmDialog, InputDialog, Modal } from "../../components/Modal";
import { Breadcrumbs } from "./Breadcrumbs";
import { DirectoryTree } from "./DirectoryTree";
import { FilePreview } from "./FilePreview";
import { FileProperties } from "./FileProperties";
import { moveInHistory, pushPath } from "./navigation";
import { formatDate, formatSize, joinPath } from "./utils";

type ViewMode = "list" | "medium" | "large";
type SortField = "name" | "size" | "type" | "owner" | "group" | "permissions" | "modified";
type ClipboardState = { mode: "copy" | "move"; paths: string[] };
type ContextState = { x: number; y: number; item: FileItem | null };
type DialogState =
  | { type: "newFolder" | "newFile" }
  | { type: "rename"; item: FileItem }
  | { type: "delete"; items: FileItem[] }
  | { type: "drop"; target: string; copy: boolean }
  | null;

const columns: Array<{ id: SortField; key: string; defaultWidth: number }> = [
  { id: "name", key: "column.name", defaultWidth: 300 }, { id: "size", key: "column.size", defaultWidth: 100 },
  { id: "type", key: "column.type", defaultWidth: 110 }, { id: "owner", key: "column.owner", defaultWidth: 110 },
  { id: "group", key: "column.group", defaultWidth: 110 }, { id: "permissions", key: "column.permissions", defaultWidth: 120 },
  { id: "modified", key: "column.modified", defaultWidth: 180 }
];

export function FileManager({ homePath, initialPath, tasks, isAdmin, t, toast, onOpenFolderWindow, onShareSamba, onUpload }: {
  homePath: string;
  initialPath?: string;
  tasks: Task[];
  isAdmin: boolean;
  t: Translate;
  toast: ToastFn;
  onOpenFolderWindow: (path: string) => void;
  onShareSamba: (path: string) => void;
  onUpload: (files: File[], path: string) => void;
}) {
  const storagePrefix = "webnas_file_explorer";
  const firstPath = initialPath || localStorage.getItem(`${storagePrefix}_path`) || homePath || "";
  const [history, setHistory] = useState({ entries: [firstPath], index: 0 });
  const path = history.entries[history.index] || "";
  const [items, setItems] = useState<FileItem[]>([]);
  const [meta, setMeta] = useState({ total: 0, pages: 1, page: 1, parent: null as string | null, canWrite: true, canDelete: true });
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<SortField>("name");
  const [direction, setDirection] = useState<"asc" | "desc">("asc");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [clipboard, setClipboard] = useState<ClipboardState | null>(null);
  const [mounts, setMounts] = useState<NetworkMount[]>([]);
  const [sharedPaths, setSharedPaths] = useState<Set<string>>(new Set());
  const [treeVisible, setTreeVisible] = useState(() => localStorage.getItem(`${storagePrefix}_tree`) !== "hidden");
  const [treeWidth, setTreeWidth] = useState(() => Number(localStorage.getItem(`${storagePrefix}_tree_width`) || 238));
  const [compact, setCompact] = useState(() => localStorage.getItem(`${storagePrefix}_compact`) === "true");
  const [view, setView] = useState<ViewMode>(() => (localStorage.getItem(`${storagePrefix}_view`) as ViewMode) || "list");
  const [hiddenColumns, setHiddenColumns] = useState<Set<SortField>>(() => new Set(JSON.parse(localStorage.getItem(`${storagePrefix}_hidden_columns`) || "[]")));
  const [widths, setWidths] = useState<Record<SortField, number>>(() => ({ name: 300, size: 100, type: 110, owner: 110, group: 110, permissions: 120, modified: 180 }));
  const [context, setContext] = useState<ContextState | null>(null);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [preview, setPreview] = useState<FileItem | null>(null);
  const [properties, setProperties] = useState<FileItem | null>(null);
  const [operationErrors, setOperationErrors] = useState<string[]>([]);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [dropTarget, setDropTarget] = useState("");
  const [dragPaths, setDragPaths] = useState<string[]>([]);
  const lastSelectedIndex = useRef<number | null>(null);
  const requestId = useRef(0);
  const uploadInput = useRef<HTMLInputElement>(null);

  useEffect(() => { const timer = setTimeout(() => setFilter(query), 280); return () => clearTimeout(timer); }, [query]);
  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true); setLoadError("");
    try {
      const data = await api.list(path, { page, page_size: 100, sort, direction, folders_first: true, filter });
      if (id !== requestId.current) return;
      setItems(data.items);
      setMeta({ total: data.total_items, pages: data.total_pages, page: data.page, parent: data.parent_path, canWrite: data.can_write, canDelete: data.can_delete });
      setSelection(new Set());
      localStorage.setItem(`${storagePrefix}_path`, data.current_path);
    } catch (error) {
      if (id !== requestId.current) return;
      setLoadError(error instanceof Error ? error.message : t("files.loadError"));
    } finally { if (id === requestId.current) setLoading(false); }
  }, [direction, filter, page, path, sort, t]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { api.mounts().then(setMounts).catch(() => setMounts([])); api.appConfig("samba").then((data) => setSharedPaths(new Set(data.shares.filter((share) => share.enabled).map((share) => share.path)))).catch(() => undefined); }, []);
  useEffect(() => {
    const completed = tasks.some((task) => ["copy", "move", "delete", "upload"].includes(task.type) && ["completed", "failed"].includes(task.status) && (task.finished_at || 0) * 1000 > Date.now() - 2500);
    if (completed) void load();
  }, [load, tasks]);
  useEffect(() => { localStorage.setItem(`${storagePrefix}_view`, view); }, [view]);
  useEffect(() => { localStorage.setItem(`${storagePrefix}_compact`, String(compact)); }, [compact]);
  useEffect(() => { localStorage.setItem(`${storagePrefix}_tree`, treeVisible ? "visible" : "hidden"); }, [treeVisible]);
  useEffect(() => { localStorage.setItem(`${storagePrefix}_hidden_columns`, JSON.stringify([...hiddenColumns])); }, [hiddenColumns]);

  const selectedItems = useMemo(() => items.filter((item) => selection.has(item.path)), [items, selection]);
  const selectedSize = useMemo(() => selectedItems.reduce((sum, item) => sum + (item.is_dir ? 0 : item.size), 0), [selectedItems]);
  const activeTasks = tasks.filter((task) => ["copy", "move", "delete"].includes(task.type) && ["queued", "running", "paused"].includes(task.status)).length;

  const openPath = useCallback((next: string, record = true) => {
    setPage(1);
    setHistory((current) => {
      if (!record) return current;
      return pushPath(current, next);
    });
  }, []);
  function navigateHistory(index: number) { setPage(1); setHistory((current) => moveInHistory(current, index - current.index)); }
  function selectItem(item: FileItem, event: React.MouseEvent, index: number) {
    setSelection((current) => {
      if (event.shiftKey && lastSelectedIndex.current !== null) {
        const [start, end] = [lastSelectedIndex.current, index].sort((a, b) => a - b);
        return new Set(items.slice(start, end + 1).map((entry) => entry.path));
      }
      if (event.ctrlKey || event.metaKey) { const next = new Set(current); if (next.has(item.path)) next.delete(item.path); else next.add(item.path); return next; }
      return new Set([item.path]);
    });
    lastSelectedIndex.current = index;
  }
  function openItem(item = selectedItems[0]) { if (!item) return; if (item.is_dir) openPath(item.path); else setPreview(item); }
  function setClipboardFromSelection(mode: "copy" | "move") { if (selectedItems.length) setClipboard({ mode, paths: selectedItems.map((item) => item.path) }); }
  async function paste(target = path, source = clipboard) {
    if (!source?.paths.length) return;
    try {
      await (source.mode === "copy" ? api.copy(source.paths, target) : api.move(source.paths, target));
      setClipboard(null); toast(t("files.taskQueued"));
    } catch (error) { toast(error instanceof Error ? error.message : t("files.operationFailed"), "error"); }
  }
  async function create(kind: "folder" | "file", name: string) {
    try { await (kind === "folder" ? api.mkdir(joinPath(path, name)) : api.create(joinPath(path, name))); toast(kind === "folder" ? t("files.folderCreated") : t("files.fileCreated")); await load(); }
    catch (error) { toast(error instanceof Error ? error.message : t("files.operationFailed"), "error"); }
  }
  async function rename(item: FileItem, name: string) {
    try { await api.rename(item.path, joinPath(path, name)); toast(t("files.renamed")); await load(); }
    catch (error) { toast(error instanceof Error ? error.message : t("files.operationFailed"), "error"); }
  }
  async function remove(itemsToDelete: FileItem[]) {
    const deletable = itemsToDelete.filter((item) => item.can_delete);
    try {
      await api.delete(deletable.map((item) => item.path));
      toast(t("files.deleteQueued"));
      setOperationErrors([]);
      setSelection(new Set());
    } catch (error) {
      const detail = error instanceof Error ? error.message : t("files.operationFailed");
      setOperationErrors([detail]);
      toast(detail, "error");
    }
  }
  async function upload(files: FileList | null) {
    if (!files?.length) return;
    onUpload([...files], path);
    toast(t("files.uploadQueued"));
  }
  function confirmDrop(target: string) { if (dragPaths.length) setDialog({ type: "drop", target, copy: false }); }
  function dragPreview(event: React.DragEvent, paths: string[]) {
    setDragPaths(paths);
    event.dataTransfer.effectAllowed = "copyMove";
    event.dataTransfer.setData("text/plain", paths.join("\n"));
    const preview = document.createElement("div");
    preview.className = "drag-preview";
    preview.textContent = t("files.dragItems").replace("{count}", String(paths.length));
    document.body.appendChild(preview);
    event.dataTransfer.setDragImage(preview, 18, 18);
    window.setTimeout(() => preview.remove(), 0);
  }

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      const modifier = event.ctrlKey || event.metaKey;
      if (modifier && event.key.toLowerCase() === "a") { event.preventDefault(); setSelection(new Set(items.map((item) => item.path))); }
      else if (modifier && event.key.toLowerCase() === "c") { event.preventDefault(); setClipboardFromSelection("copy"); }
      else if (modifier && event.key.toLowerCase() === "x") { event.preventDefault(); setClipboardFromSelection("move"); }
      else if (modifier && event.key.toLowerCase() === "v") { event.preventDefault(); void paste(); }
      else if (event.key === "F2" && selectedItems[0]?.can_rename) { event.preventDefault(); setDialog({ type: "rename", item: selectedItems[0] }); }
      else if (event.key === "Delete" && selectedItems.length) { event.preventDefault(); setDialog({ type: "delete", items: selectedItems }); }
      else if (event.key === "Enter") { event.preventDefault(); openItem(); }
      else if (event.key === "Backspace" && meta.parent) { event.preventDefault(); openPath(meta.parent); }
      else if (event.key === "Escape") { setDragPaths([]); setDropTarget(""); setContext(null); }
    }
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- commands use the current explorer snapshot
  }, [items, meta.parent, openPath, selectedItems, clipboard, path]);

  function contextItems(state: ContextState): ContextMenuItem[] {
    const item = state.item;
    const targetItems = item ? [item] : selectedItems;
    const menu: ContextMenuItem[] = [];
    if (item) menu.push({ label: t("action.open"), action: () => openItem(item) });
    if (item && !item.is_dir) menu.push({ label: t("action.preview"), action: () => setPreview(item) }, { label: t("action.download"), action: () => window.open(downloadUrl(item.path), "_blank") });
    if (item?.is_dir) menu.push({ label: t("files.openNewWindow"), action: () => onOpenFolderWindow(item.path) });
    if (item) menu.push({ label: t("action.copy"), separator: true, action: () => setClipboard({ mode: "copy", paths: targetItems.map((entry) => entry.path) }) }, { label: t("action.cut"), action: () => setClipboard({ mode: "move", paths: targetItems.map((entry) => entry.path) }) }, { label: t("action.rename"), disabled: !item.can_rename, action: () => setDialog({ type: "rename", item }) }, { label: t("action.delete"), danger: true, disabled: !item.can_delete, action: () => setDialog({ type: "delete", items: targetItems }) });
    else menu.push({ label: t("action.newFolder"), action: () => setDialog({ type: "newFolder" }) }, { label: t("action.newFile"), action: () => setDialog({ type: "newFile" }) }, { label: t("action.upload"), action: () => document.getElementById("file-manager-upload")?.click() });
    menu.push({ label: t("action.paste"), separator: true, disabled: !clipboard, action: () => void paste(item?.is_dir ? item.path : path) }, { label: t("files.copyPath"), action: () => void navigator.clipboard?.writeText(item?.path || path) });
    if (item?.is_dir) menu.push({ label: t("files.shareSamba"), action: () => onShareSamba(item.path) });
    menu.push({ label: item ? t("files.properties") : t("files.directoryProperties"), action: () => item ? setProperties(item) : api.stat(path).then(setProperties).catch(() => undefined) }, { label: t("action.refresh"), action: () => void load() });
    return menu;
  }

  const visibleColumns = columns.filter((column) => !hiddenColumns.has(column.id));
  return <section className="file-manager" aria-label={t("app.fileManager")}>
    <div className="file-toolbar" role="toolbar" aria-label={t("files.toolbar")}>
      <button title={t("files.directoryTree")} aria-pressed={treeVisible} onClick={() => setTreeVisible((value) => !value)}><Menu /></button><span className="toolbar-divider" />
      <button title={t("action.back")} disabled={history.index === 0} onClick={() => navigateHistory(history.index - 1)}><ArrowLeft /></button>
      <button title={t("action.forward")} disabled={history.index >= history.entries.length - 1} onClick={() => navigateHistory(history.index + 1)}><ArrowRight /></button>
      <button title={t("action.parentFolder")} disabled={!meta.parent} onClick={() => meta.parent && openPath(meta.parent)}><ArrowUp /></button>
      <button title={t("action.refresh")} onClick={() => void load()}><RefreshCw className={loading ? "spin" : ""} /></button><span className="toolbar-divider" />
      <button title={t("action.newFolder")} disabled={!meta.canWrite} onClick={() => setDialog({ type: "newFolder" })}><FolderPlus /></button>
      <button title={t("action.newFile")} disabled={!meta.canWrite} onClick={() => setDialog({ type: "newFile" })}><FilePlus2 /></button>
      <button title={t("action.upload")} disabled={!meta.canWrite} onClick={() => uploadInput.current?.click()}><Upload /></button><input id="file-manager-upload" ref={uploadInput} className="visually-hidden" type="file" multiple onChange={(event) => void upload(event.target.files)} />
      <button className="toolbar-wide" title={t("action.download")} disabled={!selectedItems.length || selectedItems.some((item) => item.is_dir)} onClick={() => selectedItems.forEach((item) => window.open(downloadUrl(item.path), "_blank"))}><Download /></button>
      <button className="toolbar-wide" title={t("action.copy")} disabled={!selection.size} onClick={() => setClipboardFromSelection("copy")}><Copy /></button>
      <button className="toolbar-wide" title={t("action.cut")} disabled={!selection.size} onClick={() => setClipboardFromSelection("move")}><Scissors /></button>
      <button className="toolbar-wide" title={t("action.paste")} disabled={!clipboard || !meta.canWrite} onClick={() => void paste()}><Move /></button>
      <button className="toolbar-wide" title={t("action.rename")} disabled={selectedItems.length !== 1 || !selectedItems[0].can_rename} onClick={() => setDialog({ type: "rename", item: selectedItems[0] })}><Pencil /></button>
      <button className="toolbar-wide" title={t("action.delete")} disabled={!selection.size || !meta.canDelete} onClick={() => setDialog({ type: "delete", items: selectedItems })}><Trash2 /></button>
      <div className="toolbar-menu-wrap"><button title={t("action.more")} onClick={() => setMoreOpen((value) => !value)}><MoreHorizontal /></button>{moreOpen && <div className="toolbar-popover more-menu"><button disabled={!selectedItems.length} onClick={() => selectedItems[0] && setProperties(selectedItems[0])}><Info />{t("files.properties")}</button><button disabled={!selection.size} onClick={() => setClipboardFromSelection("copy")}><Copy />{t("action.copy")}</button><button disabled={!selection.size} onClick={() => setDialog({ type: "delete", items: selectedItems })}><Trash2 />{t("action.delete")}</button></div>}</div>
      <div className="view-switcher"><button className={view === "list" ? "active" : ""} title={t("view.list")} onClick={() => setView("list")}><List /></button><button className={view === "medium" ? "active" : ""} title={t("view.medium")} onClick={() => setView("medium")}><Grid2X2 /></button><button className={view === "large" ? "active" : ""} title={t("view.large")} onClick={() => setView("large")}><LayoutGrid /></button></div>
      <div className="toolbar-menu-wrap"><button title={t("files.viewOptions")} onClick={() => setOptionsOpen((value) => !value)}><SlidersHorizontal /></button>{optionsOpen && <div className="toolbar-popover"><label><input type="checkbox" checked={compact} onChange={(event) => setCompact(event.target.checked)} />{t("files.compact")}</label><strong><Columns3 />{t("files.columns")}</strong>{columns.slice(1).map((column) => <label key={column.id}><input type="checkbox" checked={!hiddenColumns.has(column.id)} onChange={() => setHiddenColumns((current) => { const next = new Set(current); if (next.has(column.id)) next.delete(column.id); else next.add(column.id); return next; })} />{t(column.key)}</label>)}</div>}</div>
      <div className="file-search"><Search /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("files.search")} aria-label={t("files.search")} />{query && <button onClick={() => setQuery("")}><X /></button>}</div>
    </div>
    <Breadcrumbs path={path} t={t} onOpen={openPath} />
    <div className="file-workspace" style={{ gridTemplateColumns: treeVisible ? `${treeWidth}px 5px minmax(0, 1fr)` : "0 0 minmax(0, 1fr)" }}>
      <button className="tree-mobile-toggle" title={t("files.directoryTree")} onClick={() => setTreeVisible((value) => !value)}><Menu /></button>
      {treeVisible && <DirectoryTree currentPath={path} homePath={homePath} mounts={mounts} t={t} onOpen={openPath} onDropItems={confirmDrop} />}
      {treeVisible && <div className="tree-resizer" onPointerDown={(event) => { const startX = event.clientX; const start = treeWidth; let finalWidth = start; const move = (next: PointerEvent) => { finalWidth = Math.max(180, Math.min(420, start + next.clientX - startX)); setTreeWidth(finalWidth); }; const up = () => { localStorage.setItem(`${storagePrefix}_tree_width`, String(finalWidth)); window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); }; window.addEventListener("pointermove", move); window.addEventListener("pointerup", up); }} />}
      <main className={`file-content ${compact ? "compact" : ""}`} tabIndex={0} onContextMenu={(event) => { if ((event.target as HTMLElement).closest(".file-entry")) return; event.preventDefault(); setContext({ x: event.clientX, y: event.clientY, item: null }); }} onDragOver={(event) => event.preventDefault()}>
        {loadError && <div className="error-state"><strong>{t("status.error")}</strong><span>{loadError}</span><button onClick={() => void load()}>{t("action.retry")}</button></div>}
        {loading ? <div className="file-skeleton">{Array.from({ length: 8 }, (_, index) => <span key={index} />)}</div> : items.length === 0 ? <div className="empty-state"><Folder /><strong>{t("files.empty")}</strong><span>{t("files.emptyHint")}</span></div> : view === "list" ? <div className="file-list" role="grid">
          <div className="file-list-header" role="row"><span><input type="checkbox" aria-label={t("files.selectAll")} checked={items.length > 0 && selection.size === items.length} onChange={(event) => setSelection(event.target.checked ? new Set(items.map((item) => item.path)) : new Set())} /></span><span />{visibleColumns.map((column) => <button className={column.id} role="columnheader" key={column.id} style={{ width: widths[column.id] }} onClick={() => { if (sort === column.id) setDirection((value) => value === "asc" ? "desc" : "asc"); else { setSort(column.id); setDirection("asc"); } }}>{t(column.key)}{sort === column.id && <i>{direction === "asc" ? "↑" : "↓"}</i>}<b onPointerDown={(event) => { event.stopPropagation(); const startX = event.clientX; const start = widths[column.id]; const move = (next: PointerEvent) => setWidths((current) => ({ ...current, [column.id]: Math.max(70, start + next.clientX - startX) })); const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); }; window.addEventListener("pointermove", move); window.addEventListener("pointerup", up); }} /></button>)}<span>{t("column.actions")}</span></div>
          {items.map((item, index) => <div role="row" key={item.path} className={`file-entry file-row ${selection.has(item.path) ? "selected" : ""} ${dropTarget === item.path ? "drop-target" : ""}`} draggable onDragStart={(event) => dragPreview(event, selection.has(item.path) ? selectedItems.map((entry) => entry.path) : [item.path])} onDragEnd={() => { setDropTarget(""); }} onDragOver={(event) => { if (item.is_dir) { event.preventDefault(); event.dataTransfer.dropEffect = event.ctrlKey ? "copy" : "move"; setDropTarget(item.path); } }} onDragLeave={() => setDropTarget("")} onDrop={(event) => { event.preventDefault(); setDropTarget(""); if (item.is_dir) setDialog({ type: "drop", target: item.path, copy: event.ctrlKey }); }} onClick={(event) => selectItem(item, event, index)} onDoubleClick={() => openItem(item)} onContextMenu={(event) => { event.preventDefault(); if (!selection.has(item.path)) setSelection(new Set([item.path])); setContext({ x: event.clientX, y: event.clientY, item }); }}>
            <span><input type="checkbox" aria-label={`${t("action.select")} ${item.name}`} checked={selection.has(item.path)} onClick={(event) => event.stopPropagation()} onChange={() => setSelection((current) => { const next = new Set(current); if (next.has(item.path)) next.delete(item.path); else next.add(item.path); return next; })} /></span><span className="file-type-icon">{item.is_dir ? <Folder /> : <File />}</span>{visibleColumns.map((column) => <span key={column.id} style={{ width: widths[column.id] }} className={column.id}>{column.id === "name" ? <>{item.name}{item.is_dir && sharedPaths.has(item.path) && <small>SMB</small>}</> : column.id === "size" ? item.is_dir ? "—" : formatSize(item.size) : column.id === "modified" ? formatDate(item.mtime || item.modified) : item[column.id]}</span>)}<span className="row-actions"><button title={t("files.properties")} onClick={(event) => { event.stopPropagation(); setProperties(item); }}><MoreHorizontal /></button></span>
          </div>)}</div> : <div className={`file-grid ${view}`}>{items.map((item, index) => <button key={item.path} className={`file-entry ${selection.has(item.path) ? "selected" : ""}`} draggable onDragStart={(event) => dragPreview(event, selection.has(item.path) ? selectedItems.map((entry) => entry.path) : [item.path])} onClick={(event) => selectItem(item, event, index)} onDoubleClick={() => openItem(item)} onContextMenu={(event) => { event.preventDefault(); setSelection(new Set([item.path])); setContext({ x: event.clientX, y: event.clientY, item }); }} onDragOver={(event) => { if (item.is_dir) event.preventDefault(); }} onDrop={(event) => { if (item.is_dir) setDialog({ type: "drop", target: item.path, copy: event.ctrlKey }); }}>{item.is_dir ? <Folder /> : <File />}<span>{item.name}</span><small>{item.is_dir ? t("files.folder") : formatSize(item.size)}</small></button>)}</div>}
        {meta.pages > 1 && <nav className="pagination" aria-label={t("files.pagination")}><button disabled={page === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>{t("action.previous")}</button><span>{meta.page} / {meta.pages}</span><button disabled={page >= meta.pages} onClick={() => setPage((value) => Math.min(meta.pages, value + 1))}>{t("action.next")}</button></nav>}
      </main>
    </div>
    <footer className="file-status"><span>{t("status.items").replace("{count}", String(meta.total))}</span><span>{t("status.selected").replace("{count}", String(selection.size))} · {formatSize(selectedSize)}</span><span>{t("status.operations").replace("{count}", String(activeTasks))}</span><strong className={loadError ? "error" : ""}>{loading ? t("status.loading") : loadError ? t("status.error") : t("status.ready")}</strong></footer>
    {context && <ContextMenu {...context} items={contextItems(context)} onClose={() => setContext(null)} />}
    {dialog?.type === "newFolder" && <InputDialog title={t("action.newFolder")} label={t("files.folderName")} confirmLabel={t("action.create")} cancelLabel={t("action.cancel")} onClose={() => setDialog(null)} onConfirm={(name) => { setDialog(null); void create("folder", name); }} />}
    {dialog?.type === "newFile" && <InputDialog title={t("action.newFile")} label={t("files.fileName")} confirmLabel={t("action.create")} cancelLabel={t("action.cancel")} onClose={() => setDialog(null)} onConfirm={(name) => { setDialog(null); void create("file", name); }} />}
    {dialog?.type === "rename" && <InputDialog title={t("action.rename")} label={t("files.newName")} value={dialog.item.name} confirmLabel={t("action.rename")} cancelLabel={t("action.cancel")} onClose={() => setDialog(null)} onConfirm={(name) => { const item = dialog.item; setDialog(null); void rename(item, name); }} />}
    {dialog?.type === "delete" && <ConfirmDialog title={t("files.confirmDeleteTitle")} message={t("files.confirmDelete").replace("{count}", String(dialog.items.length))} confirmLabel={t("action.delete")} cancelLabel={t("action.cancel")} danger onClose={() => setDialog(null)} onConfirm={() => { const list = dialog.items; setDialog(null); void remove(list); }} />}
    {dialog?.type === "drop" && <ConfirmDialog title={dialog.copy ? t("files.confirmCopy") : t("files.confirmMove")} message={t("files.confirmDrop").replace("{count}", String(dragPaths.length)).replace("{target}", dialog.target)} confirmLabel={dialog.copy ? t("action.copy") : t("action.move")} cancelLabel={t("action.cancel")} onClose={() => setDialog(null)} onConfirm={() => { const source = { mode: dialog.copy ? "copy" as const : "move" as const, paths: dragPaths }; const target = dialog.target; setDialog(null); setDragPaths([]); void paste(target, source); }} />}
    {preview && <FilePreview item={preview} t={t} onClose={() => setPreview(null)} />}
    {properties && <FileProperties item={properties} currentPath={path} isAdmin={isAdmin} sambaShared={sharedPaths.has(properties.path)} t={t} toast={toast} onClose={() => setProperties(null)} onChanged={() => void load()} />}
    {operationErrors.length > 0 && <Modal title={t("files.operationErrors")} onClose={() => setOperationErrors([])} footer={<button onClick={() => setOperationErrors([])}>{t("action.close")}</button>}><ul className="error-list">{operationErrors.map((error) => <li key={error}>{error}</li>)}</ul></Modal>}
  </section>;
}
