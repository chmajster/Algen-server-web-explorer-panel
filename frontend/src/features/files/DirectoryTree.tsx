import { ChevronDown, ChevronRight, Folder, HardDrive, LoaderCircle, Network, Usb } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type FileItem, type LocalDisk, type NetworkMountRoot } from "../../api";
import type { Translate } from "../../app/types";

type NodeState = { children: FileItem[]; open: boolean; loading: boolean; error?: string };
type TreeState = Record<string, NodeState>;

export function DirectoryTree({ currentPath, homePath, localDisks, mounts, t, onOpen, onDropItems }: {
  currentPath: string;
  homePath: string;
  localDisks: LocalDisk[];
  mounts: NetworkMountRoot[];
  t: Translate;
  onOpen: (path: string) => void;
  onDropItems: (path: string) => void;
}) {
  const storageKey = "webnas_explorer_expanded";
  const [tree, setTree] = useState<TreeState>({});
  const [dropTarget, setDropTarget] = useState("");
  const [dragCount, setDragCount] = useState(0);
  const expandTimer = useRef<number | null>(null);
  const load = useCallback(async (path: string, force = false) => {
    const existing = tree[path];
    if (existing?.children.length && !force) { setTree((state) => ({ ...state, [path]: { ...state[path], open: !state[path].open } })); return; }
    setTree((state) => ({ ...state, [path]: { children: state[path]?.children || [], open: true, loading: true } }));
    try {
      const data = await api.tree(path);
      setTree((state) => ({ ...state, [path]: { children: data.items.filter((item) => item.is_dir), open: true, loading: false } }));
    } catch (error) {
      setTree((state) => ({ ...state, [path]: { children: [], open: true, loading: false, error: error instanceof Error ? error.message : t("files.loadError") } }));
    }
  }, [t, tree]);

  useEffect(() => {
    const expanded = JSON.parse(localStorage.getItem(storageKey) || "[]") as string[];
    const roots = [...new Set([homePath, ...localDisks.map((disk) => disk.mount_point), ...mounts.map((mount) => mount.mount_point), ...expanded])].filter(Boolean).slice(0, 20);
    roots.forEach((path) => { if (expanded.includes(path) || path === homePath) void load(path); });
    // Initial restoration is intentionally run once per root set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [homePath, localDisks.map((disk) => disk.mount_point).join("|"), mounts.map((mount) => mount.mount_point).join("|")]);
  useEffect(() => {
    const expanded = Object.entries(tree).filter(([, value]) => value.open).map(([path]) => path);
    localStorage.setItem(storageKey, JSON.stringify(expanded));
  }, [tree]);

  const pathIsReadOnly = (path: string) => [...localDisks, ...mounts].some((mount) => mount.read_only && (path === mount.mount_point || path.startsWith(`${mount.mount_point}/`)));
  const fixedDisks = localDisks.filter((disk) => !disk.removable);
  const usbDisks = localDisks.filter((disk) => disk.removable);
  function row(path: string, label: string, icon: React.ReactNode, level: number, canExpand = true, details = "") {
    const state = tree[path];
    return <div key={path}>
      <button type="button" className={`tree-row ${currentPath === path ? "active" : ""} ${dropTarget === path ? "drop-target" : ""}`} style={{ paddingLeft: 10 + level * 16 }} onClick={() => onOpen(path)} onDragEnter={(event) => { if (pathIsReadOnly(path)) return; event.preventDefault(); const paths = event.dataTransfer.getData("text/plain").split("\n").filter(Boolean); setDragCount(paths.length); setDropTarget(path); if (canExpand && !state?.open) { if (expandTimer.current !== null) window.clearTimeout(expandTimer.current); expandTimer.current = window.setTimeout(() => void load(path), 650); } }} onDragOver={(event) => { if (pathIsReadOnly(path)) return; event.preventDefault(); setDropTarget(path); }} onDragLeave={(event) => { if (event.currentTarget.contains(event.relatedTarget as Node | null)) return; if (expandTimer.current !== null) window.clearTimeout(expandTimer.current); expandTimer.current = null; setDropTarget(""); setDragCount(0); }} onDrop={(event) => { event.preventDefault(); if (expandTimer.current !== null) window.clearTimeout(expandTimer.current); expandTimer.current = null; setDropTarget(""); setDragCount(0); if (!pathIsReadOnly(path)) onDropItems(path); }}>
        {canExpand ? <span className="tree-toggle" onClick={(event) => { event.stopPropagation(); void load(path); }}>{state?.loading ? <LoaderCircle className="spin" /> : state?.open ? <ChevronDown /> : <ChevronRight />}</span> : <span className="tree-toggle" />}
        {icon}<span className="tree-label">{label}</span>{details && <small className="tree-details">{details}</small>}{dropTarget === path && dragCount > 0 && <small className="drag-count">{dragCount}</small>}
      </button>
      {state?.error && <button className="tree-error" onClick={() => void load(path, true)}>{state.error} · {t("action.retry")}</button>}
      {state?.open && state.children.map((child) => <div key={child.path}>{row(child.path, child.name, <Folder />, level + 1)}</div>)}
    </div>;
  }

  return <aside className="directory-tree" aria-label={t("files.directoryTree")}>
    <h3>{t("files.locations")}</h3>
    {row(homePath || "/", t("files.home"), <HardDrive />, 0)}
    {fixedDisks.length > 0 && <h3>{t("files.localDisks")}</h3>}
    {fixedDisks.map((disk) => row(disk.mount_point, disk.name, <HardDrive />, 0, true, [disk.fs_type, disk.read_only ? t("files.readOnly") : ""].filter(Boolean).join(" · ")))}
    {usbDisks.length > 0 && <h3>{t("files.usbDevices")}</h3>}
    {usbDisks.map((disk) => row(disk.mount_point, disk.name, <Usb />, 0, true, [disk.fs_type, disk.read_only ? t("files.readOnly") : ""].filter(Boolean).join(" · ")))}
    {mounts.length > 0 && <h3>{t("files.networkResources")}</h3>}
    {mounts.map((mount) => row(mount.mount_point, mount.name, <Network />, 0))}
  </aside>;
}
