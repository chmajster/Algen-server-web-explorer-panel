import { Check, Clipboard, Edit3, House, X } from "lucide-react";
import { useState } from "react";
import type { Translate } from "../../app/types";

type BreadcrumbRoot = { path: string; label: string };

export function Breadcrumbs({ path, homePath, roots = [], t, onOpen }: { path: string; homePath: string; roots?: BreadcrumbRoot[]; t: Translate; onOpen: (path: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(path);
  const availableRoots = [{ path: homePath, label: t("files.home") }, ...roots]
    .filter((root, index, all) => root.path && all.findIndex((entry) => entry.path === root.path) === index)
    .sort((left, right) => right.path.length - left.path.length);
  const activeRoot = availableRoots.find((root) => path === root.path || path.startsWith(`${root.path.replace(/\/$/, "")}/`))
    || { path: homePath, label: t("files.home") };
  const relativePath = path === activeRoot.path ? "" : path.slice(activeRoot.path.replace(/\/$/, "").length);
  const parts = relativePath.split("/").filter(Boolean);
  return <nav className="breadcrumbs" aria-label={t("files.path")}>
    {editing ? <form onSubmit={(event) => { event.preventDefault(); onOpen(value); setEditing(false); }}>
      <input value={value} onChange={(event) => setValue(event.target.value)} aria-label={t("files.fullPath")} autoFocus />
      <button type="submit" title={t("action.apply")}><Check /></button><button type="button" title={t("action.cancel")} onClick={() => setEditing(false)}><X /></button>
    </form> : <div className="crumb-list"><button type="button" className="home-crumb" title={t("files.goHome")} onClick={() => onOpen(activeRoot.path)}>{activeRoot.path === homePath && <House />}<span>{activeRoot.label}</span></button>{parts.map((part, index) => { const target = `${activeRoot.path.replace(/\/$/, "")}/${parts.slice(0, index + 1).join("/")}`; return <button type="button" key={target} onClick={() => onOpen(target)}>{part}</button>; })}</div>}
    <div className="breadcrumb-actions"><button type="button" title={t("files.editPath")} onClick={() => { setValue(path); setEditing(true); }}><Edit3 /></button><button type="button" title={t("files.copyPath")} onClick={() => navigator.clipboard?.writeText(path)}><Clipboard /></button></div>
  </nav>;
}
